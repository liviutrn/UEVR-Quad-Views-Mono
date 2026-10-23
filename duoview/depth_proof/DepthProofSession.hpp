#pragma once
// One diagnostic session per process. Independent of the DuoView compositor.
// A capture is an anonymous boundary snapshot, NEVER an RGB-D view pair.
#include <d3d12.h>
#include <wrl/client.h>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <future>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>
#include <algorithm>
#include <limits>

namespace uevr::depth_proof {
class Session {
public:
    template<class T> using Com = Microsoft::WRL::ComPtr<T>;
    static constexpr size_t max_candidates=24, max_lists=256, max_tuples=192;
    using Clock=std::chrono::steady_clock;
    bool start(ID3D12Device* device, const std::filesystem::path& folder) {
        std::scoped_lock lock{mutex_};
        if (started_ || !device) return false;
        device_=device; folder_=folder; started_=true;
        started_at_=Clock::now(); deadline_=started_at_+std::chrono::seconds(10);
        active_.store(true, std::memory_order_release);
        status_="Collecting anonymous depth candidates for 10 seconds";
        return true;
    }
    bool started() const { std::scoped_lock lock{mutex_}; return started_; }
    bool observing() const { return active_.load(std::memory_order_acquire); }
    std::string status() const { std::scoped_lock lock{mutex_}; return status_; }
    void cancel() { std::scoped_lock lock{mutex_}; stop_locked("Cancelled; recorded resources retained"); }

    // Original Reset has succeeded before this callback. A reset starts a new
    // recording epoch and discards any unsubmitted recording from the old one.
    void reset(ID3D12GraphicsCommandList* cmd) {
        if (!observing()) return;
        std::scoped_lock lock{mutex_};
        auto* l=list(cmd,true); if (!l) return;
        for (auto& c:candidates_) if (c.recorded && !c.submitted && c.cmd==cmd && c.epoch==l->epoch) {
            c.discarded=true; ++discarded_;
        }
        ++l->epoch; l->known=true; l->inside=false; l->restricted=false;
    }
    void begin_pass(ID3D12GraphicsCommandList* cmd, D3D12_RENDER_PASS_FLAGS flags) {
        if (!observing()) return;
        std::scoped_lock lock{mutex_};
        auto* l=list(cmd,true); if (!l) return;
        l->inside=true;
        if ((flags & (D3D12_RENDER_PASS_FLAG_SUSPENDING_PASS|D3D12_RENDER_PASS_FLAG_RESUMING_PASS))!=0) {
            l->restricted=true; suspended_seen_=true;
        }
    }
    void end_pass(ID3D12GraphicsCommandList* cmd) {
        if (!observing()) return;
        std::scoped_lock lock{mutex_};
        if (auto* l=list(cmd,false)) l->inside=false;
    }
    void barriers(ID3D12GraphicsCommandList* cmd, UINT count, const D3D12_RESOURCE_BARRIER* barriers) {
        if (!observing() || !cmd || !barriers || cmd->GetType()!=D3D12_COMMAND_LIST_TYPE_DIRECT) return;
        std::unique_lock lock{mutex_,std::try_to_lock};
        if (!lock.owns_lock()) { skipped_contention_.fetch_add(1); return; }
        if (!active_.load(std::memory_order_relaxed) || Clock::now()>deadline_) return;
        auto* l=list(cmd,false);
        for (UINT i=0;i<count;++i) {
            const auto& b=barriers[i];
            if (b.Type!=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION || !b.Transition.pResource) continue;
            const auto& t=b.Transition;
            auto* c=candidate(t.pResource);
            if (!c) continue;
            ++c->hits;
            note_tuple(c-candidates_.data(),cmd,t,b.Flags);
            if (b.Flags!=D3D12_RESOURCE_BARRIER_FLAG_NONE) { ++reject_split_; continue; }
            // Only plane 0's known state is changed, even for planar stencil.
            if (t.Subresource!=0 && t.Subresource!=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES) {
                ++reject_subresource_; continue;
            }
            const unsigned after=static_cast<unsigned>(t.StateAfter);
            constexpr unsigned reads=D3D12_RESOURCE_STATE_DEPTH_READ|
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
            if (t.StateBefore!=D3D12_RESOURCE_STATE_DEPTH_WRITE || !after || (after&~reads)!=0) {
                ++reject_state_; continue;
            }
            if (!l || !l->known) { ++reject_unknown_list_; continue; }
            if (l->inside || l->restricted || suspended_seen_) { ++reject_pass_; continue; }
            bool ambiguous=false;
            for (UINT j=0;j<count;++j) {
                if (barriers[j].Type==D3D12_RESOURCE_BARRIER_TYPE_ALIASING ||
                    (j!=i && barriers[j].Type==D3D12_RESOURCE_BARRIER_TYPE_TRANSITION &&
                     barriers[j].Transition.pResource==t.pResource &&
                     (barriers[j].Transition.Subresource==0 ||
                      barriers[j].Transition.Subresource==D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES))) ambiguous=true;
            }
            if (ambiguous) { ++reject_batch_; continue; }
            if (!c->readback || c->recorded || c->allocation_failed) continue;
            // The incoming barrier is still unexecuted. Restore plane 0 to
            // DEPTH_WRITE before letting the original engine batch proceed.
            D3D12_RESOURCE_BARRIER to_copy{};
            to_copy.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            to_copy.Transition={t.pResource,0,D3D12_RESOURCE_STATE_DEPTH_WRITE,D3D12_RESOURCE_STATE_COPY_SOURCE};
            cmd->ResourceBarrier(1,&to_copy);
            D3D12_TEXTURE_COPY_LOCATION from{}; from.pResource=t.pResource;
            from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX; from.SubresourceIndex=0;
            D3D12_TEXTURE_COPY_LOCATION to{}; to.pResource=c->readback.Get();
            to.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; to.PlacedFootprint=c->footprint;
            cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
            std::swap(to_copy.Transition.StateBefore,to_copy.Transition.StateAfter);
            cmd->ResourceBarrier(1,&to_copy);
            c->recorded=true; c->cmd=cmd; c->epoch=l->epoch;
            c->before=t.StateBefore; c->after=t.StateAfter; c->subresource=t.Subresource;
            c->capture_tick=present_tick_; ++recorded_;
        }
    }
    // Invoked immediately AFTER original ExecuteCommandLists, on that queue.
    // Queue Signal may only cover lists actually included in this submission.
    void submitted(ID3D12CommandQueue* queue, UINT n, ID3D12CommandList* const* lists) {
        if (!observing() || !queue || !lists) return;
        std::scoped_lock lock{mutex_};
        ++submissions_;
        for (auto& c:candidates_) {
            if (!c.recorded || c.submitted || c.discarded || c.signal_failed) continue;
            bool found=false;
            for (UINT i=0;i<n;++i) if (lists[i]==static_cast<ID3D12CommandList*>(c.cmd)) found=true;
            if (!found) continue;
            auto* l=list(c.cmd,false);
            if (!l || l->epoch!=c.epoch) { c.discarded=true; ++discarded_; continue; }
            if (!c.fence || FAILED(queue->Signal(c.fence.Get(),1))) { c.signal_failed=true; continue; }
            c.queue=queue; c.submitted=true; ++submitted_;
        }
    }
    // Called from Present; no waits. Allocation is bounded and one-time.
    // Export runs on a worker only after the exact submission fence completes.
    void service(uint64_t tick) {
        std::scoped_lock lock{mutex_};
        if (!started_ || exported_) return;
        present_tick_=tick;
        if (device_ && FAILED(device_->GetDeviceRemovedReason())) {
            device_lost_=true; stop_locked("Device removed; no readback interpreted as ready");
        }
        // Gather a full second of observations before allocating. Frequency
        // ranks candidates for a bounded readback budget; it does NOT prove
        // scene identity. Keep all candidates/tuples in the report.
        if (active_.load() && !prepared_ && Clock::now()-started_at_>=std::chrono::seconds(1)) {
            std::array<Candidate*,max_candidates> ranked{};
            for (size_t i=0;i<ranked.size();++i) ranked[i]=&candidates_[i];
            std::stable_sort(ranked.begin(),ranked.end(),[](const auto* a,const auto* b){return a->hits>b->hits;});
            unsigned allocated=0;
            for (auto* c:ranked) if(c->resource && allocated<8) {prewarm(*c); if(c->readback)++allocated;}
            prepared_=true;
        }
        for (auto& c:candidates_) {
            if (!c.resource) continue;
            if (c.submitted && !c.complete && c.fence) {
                const auto value=c.fence->GetCompletedValue();
                if (value==UINT64_MAX) { device_lost_=true; continue; }
                if (value>=1) { c.complete=true; ++complete_; }
            }
        }
        if (Clock::now()<deadline_ && active_.load() && !device_lost_) {
            status_="Depth proof: candidates="+std::to_string(candidate_count_)+
                " copied="+std::to_string(recorded_)+" submitted="+std::to_string(submitted_)+
                " completed="+std::to_string(complete_)+" (collecting 10s)";
            return;
        }
        if (device_lost_) { for(auto& c:candidates_) c.complete=false; complete_=0; }
        stop_locked("Saving depth proof; no candidate roles assigned");
        // Retain all GPU resources for process lifetime even on timeout; never
        // release a readback referenced by an unobserved command-list submit.
        exported_=true;
        const auto report=manifest_locked();
        const auto candidates=candidates_;
        const auto folder=folder_;
        export_task_=std::async(std::launch::async,[this,report,candidates,folder] {
            std::string result;
            try {
                std::filesystem::create_directories(folder);
                size_t saved=0;
                std::ostringstream files;
                files<<"{\"images\":[";
                std::ostringstream gallery;
                gallery<<"<!doctype html><meta charset=utf-8><title>DuoView depth candidates</title><style>body{font:16px system-ui;background:#15191f;color:#eee;margin:32px}img{max-width:100%;width:640px;image-rendering:auto}article{display:inline-block;vertical-align:top;margin:16px}p{max-width:900px}</style><h1>Depth candidate captures</h1><p>Anonymous plane-0 raw-Z at a depth-write-to-read boundary. Logarithmic grayscale preview. Scene identity, fovea/periphery roles, RGB frame correspondence and metric depth are UNVERIFIED.</p>";
                bool comma=false;
                for (size_t i=0;i<candidates.size();++i) {
                    if (!candidates[i].complete) continue;
                    if (comma) files<<','; comma=true;
                    if (write_image(folder,i,candidates[i],files)) {
                        ++saved;
                        gallery<<"<article><h2>Candidate "<<i<<" — "<<candidates[i].desc.Width<<" × "<<candidates[i].desc.Height<<"</h2><img src=\"candidate_"<<i<<".bmp\" alt=\"Candidate depth grayscale\"></article>";
                    }
                }
                files<<"]}\n";
                if (!saved) gallery<<"<h2>NO DEPTH IMAGE</h2><p>Inspect manifest.json for rejected states, subresources, command lists and submission evidence.</p>";
                checked_write(folder/"preview.html",gallery.str());
                checked_write(folder/"manifest.json",report);
                checked_write(folder/"image_results.json",files.str());
                result="Saved "+std::to_string(saved)+" depth candidate images: "+folder.string()+
                    (saved ? " (UNVERIFIED scene/view identity)" : " (NO DEPTH IMAGE; read manifest rejection histogram)");
            } catch (const std::exception& e) { result=std::string("Depth proof save FAILED: ")+e.what(); }
            std::scoped_lock done{mutex_}; status_=result;
        });
    }
    // Used by WARP test and UI polling; never waits on a GPU fence.
    bool export_finished() const {
        std::scoped_lock lock{mutex_};
        return exported_ && export_task_.valid() && export_task_.wait_for(std::chrono::seconds(0))==std::future_status::ready;
    }
    void finish_for_test() { std::scoped_lock lock{mutex_}; deadline_=Clock::now(); }
private:
    struct List {
        ID3D12GraphicsCommandList* cmd{}; uint64_t epoch{};
        bool known{},inside{},restricted{};
    };
    struct Candidate {
        Com<ID3D12Resource> resource,readback; Com<ID3D12Fence> fence;
        Com<ID3D12CommandQueue> queue;
        D3D12_RESOURCE_DESC desc{}; D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
        UINT rows{}; UINT64 row_bytes{},bytes{};
        ID3D12GraphicsCommandList* cmd{}; uint64_t epoch{},hits{},capture_tick{};
        D3D12_RESOURCE_STATES before{},after{}; UINT subresource{};
        bool recorded{},submitted{},complete{},allocation_failed{},discarded{},signal_failed{};
    };
    struct Tuple {
        size_t candidate{}; uintptr_t cmd{}; UINT before{},after{},subresource{},flags{}; uint64_t hits{};
    };
    List* list(ID3D12GraphicsCommandList* cmd,bool create) {
        List* empty=nullptr;
        for (auto& l:lists_) { if(l.cmd==cmd) return &l; if(!l.cmd && !empty) empty=&l; }
        if (create && empty) { empty->cmd=cmd; return empty; }
        return nullptr;
    }
    static bool valid_format(DXGI_FORMAT f) {
        return f==DXGI_FORMAT_R32_TYPELESS || f==DXGI_FORMAT_D32_FLOAT ||
            f==DXGI_FORMAT_R24G8_TYPELESS || f==DXGI_FORMAT_D24_UNORM_S8_UINT ||
            f==DXGI_FORMAT_R32G8X24_TYPELESS || f==DXGI_FORMAT_D32_FLOAT_S8X24_UINT ||
            f==DXGI_FORMAT_R16_TYPELESS || f==DXGI_FORMAT_D16_UNORM;
    }
    Candidate* candidate(ID3D12Resource* resource) {
        Candidate* empty=nullptr;
        for (auto& c:candidates_) { if(c.resource.Get()==resource) return &c; if(!c.resource && !empty) empty=&c; }
        if (!empty) { ++candidate_overflow_; return nullptr; }
        const auto d=resource->GetDesc();
        if (d.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D || d.Width<128 || d.Height<128 ||
            d.Width>8192 || d.Height>8192 || d.DepthOrArraySize!=1 || d.MipLevels!=1 ||
            d.SampleDesc.Count!=1 || !valid_format(d.Format) || !(d.Flags&D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL)) return nullptr;
        empty->resource=resource; empty->desc=d; ++candidate_count_; return empty;
    }
    void note_tuple(size_t c,ID3D12GraphicsCommandList* cmd,const D3D12_RESOURCE_TRANSITION_BARRIER& b,D3D12_RESOURCE_BARRIER_FLAGS f) {
        Tuple* empty=nullptr;
        for (auto& t:tuples_) {
            if (t.hits && t.candidate==c && t.cmd==reinterpret_cast<uintptr_t>(cmd) &&
                t.before==b.StateBefore && t.after==b.StateAfter && t.subresource==b.Subresource && t.flags==f) { ++t.hits; return; }
            if (!t.hits && !empty) empty=&t;
        }
        if (empty) *empty={c,reinterpret_cast<uintptr_t>(cmd),static_cast<UINT>(b.StateBefore),static_cast<UINT>(b.StateAfter),b.Subresource,static_cast<UINT>(f),1};
        else ++tuple_overflow_;
    }
    void prewarm(Candidate& c) {
        device_->GetCopyableFootprints(&c.desc,0,1,0,&c.footprint,&c.rows,&c.row_bytes,&c.bytes);
        if (!c.bytes || c.bytes>64ull*1024*1024 || allocated_bytes_+c.bytes>128ull*1024*1024) { c.allocation_failed=true; return; }
        D3D12_HEAP_PROPERTIES heap{}; heap.Type=D3D12_HEAP_TYPE_READBACK; heap.CreationNodeMask=heap.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC buffer{}; buffer.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width=c.bytes; buffer.Height=1; buffer.DepthOrArraySize=1; buffer.MipLevels=1;
        buffer.SampleDesc.Count=1; buffer.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(device_->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&buffer,D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&c.readback))) ||
            FAILED(device_->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&c.fence)))) { c.readback.Reset(); c.fence.Reset(); c.allocation_failed=true; return; }
        allocated_bytes_+=c.bytes;
    }
    void stop_locked(const char* message) { active_.store(false,std::memory_order_release); status_=message; }
    std::string manifest_locked() const {
        std::ostringstream o;
        o<<"{\"schema\":1,\"baseline\":\"60d0aae86949723d21266e4121a833f0191729c2\","
            "\"meaning\":\"anonymous plane-0 snapshots at depth-write-to-read boundary; NOT verified scene depth, fovea/periphery, RGB matching, linear metres or stereo\","
            "\"device_lost\":"<<(device_lost_?"true":"false")<<",\"recorded\":"<<recorded_<<",\"submitted\":"<<submitted_<<",\"completed\":"<<complete_<<","
            "\"rejections\":{\"split\":"<<reject_split_<<",\"non_depth_plane\":"<<reject_subresource_<<",\"state_window\":"<<reject_state_
            <<",\"unknown_recording\":"<<reject_unknown_list_<<",\"render_pass\":"<<reject_pass_<<",\"ambiguous_batch\":"<<reject_batch_
            <<",\"discarded_recording\":"<<discarded_<<",\"callback_contention\":"<<skipped_contention_.load()<<"},"
            "\"candidate_overflow_events\":"<<candidate_overflow_<<",\"tuple_overflow_events\":"<<tuple_overflow_<<",\"queue_submissions_observed\":"<<submissions_<<",\"candidates\":[";
        bool comma=false;
        for(size_t i=0;i<candidates_.size();++i) {
            const auto& c=candidates_[i]; if(!c.resource) continue;
            if(comma)o<<',';comma=true;
            o<<"{\"id\":"<<i<<",\"view_role\":\"unknown\",\"resource\":"<<reinterpret_cast<uintptr_t>(c.resource.Get())<<",\"width\":"<<c.desc.Width<<",\"height\":"<<c.desc.Height
                <<",\"format\":"<<c.desc.Format<<",\"hits\":"<<c.hits<<",\"recorded\":"<<c.recorded<<",\"submitted\":"<<c.submitted<<",\"complete\":"<<c.complete
                <<",\"allocation_failed\":"<<c.allocation_failed<<",\"signal_failed\":"<<c.signal_failed<<",\"discarded\":"<<c.discarded
                <<",\"command_list\":"<<reinterpret_cast<uintptr_t>(c.cmd)<<",\"recording_epoch\":"<<c.epoch<<",\"queue\":"<<reinterpret_cast<uintptr_t>(c.queue.Get())
                <<",\"capture_present_tick\":"<<c.capture_tick<<",\"before\":"<<c.before<<",\"after\":"<<c.after<<",\"incoming_subresource\":"<<c.subresource
                <<",\"copied_subresource\":0,\"footprint_format\":"<<c.footprint.Footprint.Format<<",\"row_pitch\":"<<c.footprint.Footprint.RowPitch<<",\"row_bytes\":"<<c.row_bytes<<"}";
        }
        o<<"],\"transition_histogram\":[";comma=false;
        for(const auto& t:tuples_) {if(!t.hits)continue;if(comma)o<<',';comma=true;
            o<<"{\"candidate\":"<<t.candidate<<",\"command_list\":"<<t.cmd<<",\"before\":"<<t.before<<",\"after\":"<<t.after<<",\"subresource\":"<<t.subresource<<",\"flags\":"<<t.flags<<",\"hits\":"<<t.hits<<"}";}
        o<<"]}\n"; return o.str();
    }
    static void checked_write(const std::filesystem::path& path,const std::string& content) {
        std::ofstream f(path,std::ios::binary);f.exceptions(std::ios::failbit|std::ios::badbit);f<<content;
    }
    static bool write_image(const std::filesystem::path& folder,size_t id,const Candidate& c,std::ostream& json) {
        const auto width=static_cast<size_t>(c.desc.Width),height=static_cast<size_t>(c.desc.Height);
        const auto stride=c.row_bytes/width;
        if (c.row_bytes%width || (stride!=2 && stride!=4 && stride!=8)) { json<<"{\"id\":"<<id<<",\"error\":\"unsupported plane footprint\"}";return false; }
        void* mapped=nullptr;D3D12_RANGE range{0,static_cast<SIZE_T>(c.bytes)};
        if(FAILED(c.readback->Map(0,&range,&mapped)) || !mapped) {json<<"{\"id\":"<<id<<",\"error\":\"Map failed\"}";return false;}
        struct Unmap { ID3D12Resource* r; ~Unmap(){D3D12_RANGE empty{0,0};r->Unmap(0,&empty);} } unmap{c.readback.Get()};
        std::vector<float> values(width*height);std::vector<float> finite;finite.reserve(values.size());
        size_t invalid=0,zero=0;float minimum=std::numeric_limits<float>::infinity(),maximum=-minimum;
        for(size_t y=0;y<height;++y) for(size_t x=0;x<width;++x) {
            const auto* p=static_cast<const unsigned char*>(mapped)+c.footprint.Offset+y*c.footprint.Footprint.RowPitch+x*stride;
            float v=0;
            if(c.desc.Format==DXGI_FORMAT_R16_TYPELESS || c.desc.Format==DXGI_FORMAT_D16_UNORM) {uint16_t bits;std::memcpy(&bits,p,2);v=float(bits)/65535.f;}
            else if(c.desc.Format==DXGI_FORMAT_R24G8_TYPELESS || c.desc.Format==DXGI_FORMAT_D24_UNORM_S8_UINT) {uint32_t bits;std::memcpy(&bits,p,4);v=float(bits&0xFFFFFF)/16777215.f;}
            else std::memcpy(&v,p,4);
            values[y*width+x]=v;
            if(!std::isfinite(v) || v<0 || v>1){++invalid;continue;}
            minimum=std::min(minimum,v);maximum=std::max(maximum,v);if(v==0)++zero;else finite.push_back(std::log2(std::max(v,1e-30f)));
        }
        std::sort(finite.begin(),finite.end());
        const float lo=finite.empty()?0:finite[finite.size()/100];
        const float hi=finite.empty()?1:finite[finite.size()*99/100];
        std::vector<unsigned char> image(values.size());
        for(size_t i=0;i<values.size();++i) {const auto v=values[i];
            image[i]=std::isfinite(v)&&v>0&&v<=1 ? static_cast<unsigned char>(32+223*std::clamp((std::log2(std::max(v,1e-30f))-lo)/std::max(hi-lo,1e-6f),0.f,1.f)):0;}
        const auto prefix="candidate_"+std::to_string(id);
        std::ofstream raw(folder/(prefix+".f32"),std::ios::binary);raw.exceptions(std::ios::failbit|std::ios::badbit);
        raw.write(reinterpret_cast<const char*>(values.data()),values.size()*sizeof(float));raw.close();
        std::ofstream pgm(folder/(prefix+".pgm"),std::ios::binary);pgm.exceptions(std::ios::failbit|std::ios::badbit);
        pgm<<"P5\n"<<width<<' '<<height<<"\n255\n";pgm.write(reinterpret_cast<const char*>(image.data()),image.size());pgm.close();
        // Native Windows/browser preview; no converter or image library needed.
        std::ofstream bmp(folder/(prefix+".bmp"),std::ios::binary);bmp.exceptions(std::ios::failbit|std::ios::badbit);
        const uint32_t bmp_pitch=static_cast<uint32_t>((width*3+3)&~size_t(3));
        const auto put16=[&](uint16_t v){bmp.put(char(v&255));bmp.put(char(v>>8));};
        const auto put32=[&](uint32_t v){put16(uint16_t(v));put16(uint16_t(v>>16));};
        bmp.put('B');bmp.put('M');put32(54+bmp_pitch*static_cast<uint32_t>(height));put32(0);put32(54);
        put32(40);put32(static_cast<uint32_t>(width));put32(static_cast<uint32_t>(-static_cast<int32_t>(height)));
        put16(1);put16(24);put32(0);put32(bmp_pitch*static_cast<uint32_t>(height));put32(2835);put32(2835);put32(0);put32(0);
        for(size_t y=0;y<height;++y) {
            for(size_t x=0;x<width;++x) {const char v=static_cast<char>(image[y*width+x]);bmp.put(v);bmp.put(v);bmp.put(v);}
            for(size_t x=width*3;x<bmp_pitch;++x)bmp.put(0);
        }
        bmp.close();
        json<<"{\"id\":"<<id<<",\"width\":"<<width<<",\"height\":"<<height<<",\"invalid_samples\":"<<invalid<<",\"zero_samples\":"<<zero
            <<",\"min\":"<<(std::isfinite(minimum)?minimum:0)<<",\"max\":"<<(std::isfinite(maximum)?maximum:0)
            <<",\"nonconstant_valid_depth\":"<<((!invalid && maximum>minimum)?"true":"false")
            <<",\"preview\":\"log2 raw-Z percentile stretch; NOT linear metres\",\"raw\":\"little-endian float32 row-major\"}";
        return true;
    }
    mutable std::mutex mutex_;std::atomic<bool> active_{false};
    Com<ID3D12Device> device_;std::filesystem::path folder_;Clock::time_point deadline_{},started_at_{};
    std::array<Candidate,max_candidates> candidates_{};std::array<List,max_lists> lists_{};std::array<Tuple,max_tuples> tuples_{};
    std::future<void> export_task_;std::string status_{"Off; click Capture depth proof once"};
    bool started_{},exported_{},device_lost_{},suspended_seen_{},prepared_{};
    uint64_t present_tick_{},allocated_bytes_{},recorded_{},submitted_{},complete_{},candidate_count_{},candidate_overflow_{},tuple_overflow_{},submissions_{};
    uint64_t reject_split_{},reject_subresource_{},reject_state_{},reject_unknown_list_{},reject_pass_{},reject_batch_{},discarded_{};
    std::atomic<uint64_t> skipped_contention_{0};
};
} // namespace uevr::depth_proof

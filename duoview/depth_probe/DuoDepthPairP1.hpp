#pragma once
// P1 isolated, one-shot, owned GPU depth snapshots. OFF by default.
// This observer does NOT infer Unreal view identity from depth-transition order.
// Candidates are marked unverified until correlated with the exact producer.
#include <atomic>
#include <mutex>
#include <string>
#include <wrl.h>
#include <d3d12.h>
#include <hooks/D3D12Hook.hpp>

namespace uevr::duoview::dx12 {
class DepthPairP1 final : public D3D12DepthStencilObserver {
public:
    using Resource = Microsoft::WRL::ComPtr<ID3D12Resource>;
    bool arm(ID3D12Device* device, ID3D12Resource* scene_depth) {
        std::scoped_lock lock{mutex_};
        if (armed_.load() || captured_.load() || snapshots_[0] || snapshots_[1]) {
            status_="already armed or captures retained; reset runtime before another attempt";
            return false; // prevent racing a resource still referenced on GPU
        }
        if (!device || !scene_depth || FAILED(device->GetDeviceRemovedReason())) {
            status_="no matching scene-sized depth resource available (pool or RHI survey)"; return false;
        }
        const auto desc=scene_depth->GetDesc();
        const auto format=srv_format(desc.Format);
        if (format==DXGI_FORMAT_UNKNOWN || desc.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            !desc.Width || !desc.Height || desc.Width>32768 || desc.Height>32768 ||
            desc.DepthOrArraySize!=1 || desc.MipLevels!=1 ||
            desc.SampleDesc.Count!=1 || desc.SampleDesc.Quality!=0 ||
            !(desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL)) {
            status_="SceneDepthZ incompatible depth format/dimensions/array/MSAA";return false;
        }
        Microsoft::WRL::ComPtr<ID3D12Device> owner;
        if (FAILED(scene_depth->GetDevice(IID_PPV_ARGS(&owner))) || owner.Get()!=device) {
            status_="SceneDepthZ source belongs to a different GPU device";return false;
        }
        auto dst=desc;
        dst.Alignment=0;
        // Copy compatibility is defined by the matching typeless DXGI family.
        // Typed DSV formats are not sampleable SRVs on the owned copy.
        switch (desc.Format) {
        case DXGI_FORMAT_D32_FLOAT: case DXGI_FORMAT_R32_FLOAT:
            dst.Format=DXGI_FORMAT_R32_TYPELESS; break;
        case DXGI_FORMAT_D16_UNORM: case DXGI_FORMAT_R16_UNORM:
            dst.Format=DXGI_FORMAT_R16_TYPELESS; break;
        case DXGI_FORMAT_D24_UNORM_S8_UINT:
            dst.Format=DXGI_FORMAT_R24G8_TYPELESS; break;
        case DXGI_FORMAT_D32_FLOAT_S8X24_UINT:
            dst.Format=DXGI_FORMAT_R32G8X24_TYPELESS; break;
        default: break;
        }
        dst.Flags &= ~(D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL |
            D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET |
            D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS |
            D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE);
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        Resource allocated[2]{};
        for (unsigned i=0;i<2;++i) {
            if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&dst,
                sample_state(),nullptr,IID_PPV_ARGS(&allocated[i])))) {
                status_="prewarm owned depth snapshot failed";return false;
            }
            allocated[i]->SetName(i==0?L"DuoDepthP1 Candidate 0":L"DuoDepthP1 Candidate 1");
        }
        Microsoft::WRL::ComPtr<ID3D12Fence> fence;
        if (FAILED(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)))) {
            status_="failed to create nonblocking capture completion fence";return false;
        }
        fence_=std::move(fence);
        fence_signaled_.store(false,std::memory_order_release);
        source_=scene_depth;
        snapshots_[0]=std::move(allocated[0]);
        snapshots_[1]=std::move(allocated[1]);
        desc_=desc;
        source_format_=format;
        captured_.store(0,std::memory_order_release);
        barriers_seen_.store(0,std::memory_order_release);
        source_seen_.store(0,std::memory_order_release);
        mismatched_states_.store(0,std::memory_order_release);
        armed_.store(true,std::memory_order_release);
        status_="armed, awaiting two qualifying SceneDepthZ transitions";
        return true;
    }
    bool armed() const { return armed_.load(std::memory_order_acquire); }
    unsigned captured() const { return captured_.load(std::memory_order_acquire); }
    bool reset_if_empty() {
        std::scoped_lock lock{mutex_};
        if (captured_.load(std::memory_order_acquire)!=0 ||
            fence_signaled_.load(std::memory_order_acquire)) return false;
        armed_.store(false,std::memory_order_release);
        source_.Reset();
        snapshots_[0].Reset(); snapshots_[1].Reset(); fence_.Reset();
        barriers_seen_.store(0); source_seen_.store(0); mismatched_states_.store(0);
        status_="no-copy attempt reset; safe to select a different depth candidate";
        return true;
    }
    std::string status() const {
        std::scoped_lock lock{mutex_};
        return status_+" | hook_calls="+std::to_string(barriers_seen_.load())+
            " source_transitions="+std::to_string(source_seen_.load())+
            " wrong_state="+std::to_string(mismatched_states_.load())+
            " copies="+std::to_string(captured_.load());
    }
    DXGI_FORMAT srv_format() const { std::scoped_lock lock{mutex_};return source_format_; }
    Resource candidate(unsigned i) const {
        std::scoped_lock lock{mutex_};
        return i<2 && captured_.load(std::memory_order_acquire)==2 ? snapshots_[i] : Resource{};
    }
    // Called only after a complete validated native packet has been queued.
    // No wait; a later XR frame can sample only after the queue marker retires.
    bool signal_after_source_submit(ID3D12CommandQueue* queue) {
        if (!queue || captured_.load(std::memory_order_acquire)!=2 ||
            fence_signaled_.load(std::memory_order_acquire)) return false;
        std::scoped_lock lock{mutex_};
        if (!fence_ || fence_signaled_.load(std::memory_order_relaxed)) return false;
        if (FAILED(queue->Signal(fence_.Get(),1))) {
            status_="queue Signal failed; depth remains unavailable";return false;
        }
        fence_signaled_.store(true,std::memory_order_release);
        status_="copy queue marker pending; pair roles still UNVERIFIED";
        return true;
    }
    bool gpu_ready() const {
        std::scoped_lock lock{mutex_};
        return captured_.load(std::memory_order_acquire)==2 &&
            fence_signaled_.load(std::memory_order_acquire) && fence_ &&
            fence_->GetCompletedValue()>=1;
    }
    void stop() { armed_.store(false,std::memory_order_release); }
    void on_depth_stencil_view_created(ID3D12Resource*,
         const D3D12_DEPTH_STENCIL_VIEW_DESC*,
         D3D12_CPU_DESCRIPTOR_HANDLE) override {}
    void on_resource_barriers(ID3D12GraphicsCommandList* cmd, UINT n,
         const D3D12_RESOURCE_BARRIER* barriers) override {
        if (!armed_.load(std::memory_order_acquire) || !cmd || !barriers ||
            cmd->GetType()!=D3D12_COMMAND_LIST_TYPE_DIRECT) return;
        barriers_seen_.fetch_add(1,std::memory_order_relaxed);
        std::unique_lock lock{mutex_,std::try_to_lock};
        if (!lock.owns_lock() || !armed_.load(std::memory_order_relaxed) || !source_) return;
        for (UINT b=0;b<n;++b) {
            const auto& t=barriers[b];
            if (t.Type!=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION ||
                t.Transition.pResource!=source_.Get()) continue;
            source_seen_.fetch_add(1,std::memory_order_relaxed);
            if ((t.Transition.Subresource!=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES &&
                 t.Transition.Subresource!=0) ||
                t.Transition.StateBefore!=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE ||
                t.Transition.StateAfter!=D3D12_RESOURCE_STATE_DEPTH_WRITE) {
                mismatched_states_.fetch_add(1,std::memory_order_relaxed);
                continue;
            }
            const auto index=captured_.load(std::memory_order_relaxed);
            if (index>=2) { armed_.store(false,std::memory_order_release);break; }
            auto* dst=snapshots_[index].Get();
            if (!dst) { status_="owned copy unexpectedly missing";armed_=false;break; }
            D3D12_RESOURCE_BARRIER barriers_before[2]{};
            barriers_before[0].Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barriers_before[0].Transition={source_.Get(),D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE};
            barriers_before[1].Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barriers_before[1].Transition={dst,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                sample_state(),D3D12_RESOURCE_STATE_COPY_DEST};
            cmd->ResourceBarrier(2,barriers_before);
            D3D12_TEXTURE_COPY_LOCATION from{source_.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
            D3D12_TEXTURE_COPY_LOCATION to{dst,D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
            cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
            for (auto& q:barriers_before) {
                auto& v=q.Transition; const auto tmp=v.StateBefore;
                v.StateBefore=v.StateAfter;v.StateAfter=tmp;
            }
            cmd->ResourceBarrier(2,barriers_before);
            captured_.store(index+1,std::memory_order_release);
            status_= index==0 ? "copied candidate 0; awaiting next depth pass"
                : "two GPU copies recorded; roles/frame still UNVERIFIED";
            if (index==1) armed_.store(false,std::memory_order_release);
            // Never intercept a second qualifying barrier in the same callback.
            // It may represent multiple resource state transitions, not a view.
            break;
        }
    }
private:
    static constexpr D3D12_RESOURCE_STATES sample_state() {
        return static_cast<D3D12_RESOURCE_STATES>(
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|
            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    }
    static DXGI_FORMAT srv_format(DXGI_FORMAT f) {
        switch(f) {
        case DXGI_FORMAT_R32_TYPELESS: case DXGI_FORMAT_D32_FLOAT:
        case DXGI_FORMAT_R32_FLOAT: return DXGI_FORMAT_R32_FLOAT;
        case DXGI_FORMAT_R16_TYPELESS: case DXGI_FORMAT_D16_UNORM:
        case DXGI_FORMAT_R16_UNORM: return DXGI_FORMAT_R16_UNORM;
        case DXGI_FORMAT_R24G8_TYPELESS: case DXGI_FORMAT_D24_UNORM_S8_UINT:
            return DXGI_FORMAT_R24_UNORM_X8_TYPELESS;
        case DXGI_FORMAT_R32G8X24_TYPELESS: case DXGI_FORMAT_D32_FLOAT_S8X24_UINT:
            return DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS;
        default:return DXGI_FORMAT_UNKNOWN;
        }
    }
    mutable std::mutex mutex_;
    Resource source_,snapshots_[2]{};
    D3D12_RESOURCE_DESC desc_{};
    DXGI_FORMAT source_format_{DXGI_FORMAT_UNKNOWN};
    Microsoft::WRL::ComPtr<ID3D12Fence> fence_;
    std::atomic<bool> fence_signaled_{false};
    std::atomic<unsigned> captured_{0};
    std::atomic<bool> armed_{false};
    std::atomic<uint64_t> barriers_seen_{0}, source_seen_{0}, mismatched_states_{0};
    std::string status_{"disabled; no GPU depth copies"};
};
// P2 diagnostic-only fallback for UE5 RDG configurations where SceneDepthZ is
// absent from the RT pool. This does not identify fovea/periphery or copy
// content. All allocation / GPU copying remains outside RHI callback.
class DepthTransitionSurvey final : public D3D12DepthStencilObserver {
public:
    using Resource = Microsoft::WRL::ComPtr<ID3D12Resource>;
    Resource candidate(uint32_t reference_width,uint32_t reference_height) const {
        std::scoped_lock lock{mutex_};
        const Entry* best=nullptr;
        for (const auto& e : entries_) {
            if (!e.resource || e.hits<2 || !reference_width || !reference_height)
                continue;
            // The color target may be DLSS-upscaled. STALKER2 example:
            // 3612x3188 color vs 1208x1064 pre-upscale Z -> ~3x per axis.
            // Accept uniform upscaling 1x..4x, with 8% ratio tolerance.
            // This is an UNVERIFIED candidate selector, NOT proof of scene depth.
            const double scale_x=double(reference_width)/double(e.width);
            const double scale_y=double(reference_height)/double(e.height);
            const bool shape=scale_x>=0.8 && scale_x<=4.2 &&
                scale_y>=0.8 && scale_y<=4.2 &&
                scale_x / scale_y>=0.92 && scale_x / scale_y<=1.08;
            if (shape && (!best || e.hits>best->hits)) best=&e;
        }
        return best ? best->resource : Resource{};
    }
    unsigned total() const { return observed_.load(std::memory_order_acquire); }
    std::string summary() const {
        std::scoped_lock lock{mutex_};
        unsigned best_hits=0; unsigned width=0,height=0,fmt=0;
        for (const auto& e:entries_) if(e.resource && e.hits>best_hits){
            best_hits=e.hits;width=static_cast<unsigned>(e.width);
            height=e.height;fmt=static_cast<unsigned>(e.format);
        }
        std::string report="depth transitions="+std::to_string(observed_.load())+
            "; most frequent "+std::to_string(width)+"x"+std::to_string(height)+
            " format="+std::to_string(fmt)+" hits="+std::to_string(best_hits)+
            "; candidates (UNVERIFIED):";
        for (unsigned i=0;i<12;++i) {
            const auto& e=entries_[i];
            if (!e.resource) continue;
            report+=" #"+std::to_string(i)+"="+std::to_string(e.width)+"x"+
                std::to_string(e.height)+" fmt"+std::to_string(unsigned(e.format))+
                " hits"+std::to_string(e.hits);
        }
        return report;
    }
    void on_depth_stencil_view_created(ID3D12Resource*,
        const D3D12_DEPTH_STENCIL_VIEW_DESC*,
        D3D12_CPU_DESCRIPTOR_HANDLE) override {}
    void on_resource_barriers(ID3D12GraphicsCommandList* cmd,UINT count,
        const D3D12_RESOURCE_BARRIER* barriers) override {
        if (!cmd || !barriers || cmd->GetType()!=D3D12_COMMAND_LIST_TYPE_DIRECT)
            return;
        // D3D12 resource-barrier hook calls this BEFORE the original transition.
        for (UINT i=0;i<count;++i) {
            const auto& t=barriers[i];
            if(t.Type!=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION ||
                t.Transition.StateBefore!=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE ||
                t.Transition.StateAfter!=D3D12_RESOURCE_STATE_DEPTH_WRITE ||
                !t.Transition.pResource) continue;
            const auto desc=t.Transition.pResource->GetDesc();
            if(desc.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
               desc.Width<256 || desc.Height<256 || desc.Width>32768 ||
               desc.Height>32768 || desc.DepthOrArraySize!=1 ||
               desc.MipLevels!=1 || desc.SampleDesc.Count!=1 ||
               !(desc.Flags&D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL) ||
               !valid_format(desc.Format))continue;
            observed_.fetch_add(1,std::memory_order_relaxed);
            std::unique_lock lock{mutex_,std::try_to_lock};
            if(!lock.owns_lock())continue;
            Entry* slot=nullptr;
            for(auto& e:entries_) {
                if(e.resource.Get()==t.Transition.pResource) {slot=&e;break;}
                if(!slot && !e.resource) slot=&e;
            }
            if(!slot)continue; // bounded to avoid growth during rendering
            if (!slot->resource) {
                slot->resource=t.Transition.pResource; // holds live RHI reference
                slot->width=desc.Width;slot->height=desc.Height;slot->format=desc.Format;
            }
            if(slot->hits<UINT32_MAX)++slot->hits;
        }
    }
private:
    struct Entry {
        Resource resource{};
        uint64_t width{};
        unsigned height{};
        DXGI_FORMAT format{DXGI_FORMAT_UNKNOWN};
        uint32_t hits{};
    };
    static bool valid_format(DXGI_FORMAT f) {
        switch(f) {
        case DXGI_FORMAT_D32_FLOAT: case DXGI_FORMAT_R32_TYPELESS:
        case DXGI_FORMAT_R32_FLOAT:
        case DXGI_FORMAT_D24_UNORM_S8_UINT: case DXGI_FORMAT_R24G8_TYPELESS:
        case DXGI_FORMAT_D16_UNORM: case DXGI_FORMAT_R16_TYPELESS:
        case DXGI_FORMAT_D32_FLOAT_S8X24_UINT:
        case DXGI_FORMAT_R32G8X24_TYPELESS:return true;
        default:return false;
        }
    }
    mutable std::mutex mutex_;
    Entry entries_[12]{};
    std::atomic<unsigned> observed_{0};
};

} // namespace uevr::duoview::dx12

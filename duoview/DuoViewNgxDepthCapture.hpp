#pragma once
// v211: GPU-only snapshots of the SELECTED native NGX-SR foveal depth input.
// Only same-device, same-DIRECT-queue, same-DuoView-producer-key resources
// can reach the compositor. Never retain the game's borrowed Depth pointer.
// The bounded pool is recycled only after both producer fence completion and
// all XR command-slot references have been released.
#include "DuoViewFrame.hpp"
#include "DuoViewNgxManualDepth.hpp"
#include <Windows.h>
#include <d3d12.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <vector>

namespace uevr::duoview::ngx {
using Microsoft::WRL::ComPtr;
struct DepthSnapshot {
    ComPtr<ID3D12Resource> texture;
    ComPtr<ID3D12Resource> source_reference; // source must survive GPU copy until producer fence
    FrameKey key{};
    uintptr_t output_identity{}; // borrowed NGX Output identity, comparison ONLY
    uint64_t sequence{};
    uintptr_t feature{};
    uint32_t out_w{}, out_h{}, tex_w{}, tex_h{}, input_w{}, input_h{};
    uint32_t base_x{}, base_y{};
    ID3D12GraphicsCommandList* producer_list{}; // comparison only, never dereferenced
    uint64_t producer_fence{};
    uint64_t submission_tick_ms{};
    bool pending{}, submitted{};
};
class DepthSnapshotPool final {
    static constexpr size_t MaxLeases=6;
    static constexpr uint64_t MaxOwnedDepthBytes=256ull*1024ull*1024ull;
    mutable std::mutex lock_;
    ComPtr<ID3D12CommandQueue> producer_;
    ComPtr<ID3D12Device> device_;
    ComPtr<ID3D12Fence> fence_;
    std::vector<std::shared_ptr<DepthSnapshot>> leases_;
    uint64_t signal_{}, next_capture_sequence_{}, last_unkeyed_used_sequence_{};
    std::atomic<uint64_t> captures_{}, skips_{}, submits_{}, used_{}, unkeyed_captures_{}, output_matches_{}, late_tickets_{}, ordered_matches_{}, expired_ordered_{};
    bool enabled_{};
    static bool depth_format(DXGI_FORMAT f) noexcept {
        return f==DXGI_FORMAT_R32_FLOAT || f==DXGI_FORMAT_D32_FLOAT ||
               f==DXGI_FORMAT_R32_TYPELESS;
    }
    static void transition(ID3D12GraphicsCommandList* cmd,ID3D12Resource* resource,
        D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after) {
        D3D12_RESOURCE_BARRIER b{};
        b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition={resource,0,before,after};
        cmd->ResourceBarrier(1,&b);
    }
public:
    void set_enabled(bool enabled) {
        std::scoped_lock guard(lock_);
        enabled_=enabled;
    }
    // Called on the rendering injection's game queue, NOT on XR's copy callback.
    bool bind_queue(ID3D12CommandQueue* queue) {
        if(!queue || queue->GetDesc().Type!=D3D12_COMMAND_LIST_TYPE_DIRECT)return false;
        std::scoped_lock guard(lock_);
        if(producer_.Get()==queue && fence_)return true;
        // Do not throw away resources that may still be referenced by the GPU.
        // A runtime/device switch falls back to fixed sharpening until reset.
        if(producer_ && producer_.Get()!=queue)return false;
        ComPtr<ID3D12Device> dev;
        if(FAILED(queue->GetDevice(IID_PPV_ARGS(&dev))))return false;
        ComPtr<ID3D12Fence> f;
        if(FAILED(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&f))))return false;
        device_=std::move(dev);
        producer_=queue;
        fence_=std::move(f);
        return true;
    }
    void capture(ID3D12GraphicsCommandList* cmd,ID3D12Resource* depth,
                 const DepthCandidate& c,FrameKey key,ID3D12Resource* ngx_output=nullptr) {
        // Allow either immutable UE RHI packet identity OR the physical
        // NGX output itself, validated against the foveal color resource.
        const bool keyed=key.generation && key.frame;
        const bool output_proof=!key.generation && !key.frame && ngx_output;
        if(!cmd || !depth || cmd->GetType()!=D3D12_COMMAND_LIST_TYPE_DIRECT ||
           (!keyed && !output_proof) || !c.render_width || !c.render_height ||
           !c.output_width || !c.output_height) return;
        const auto desc=depth->GetDesc();
        if(desc.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
           desc.DepthOrArraySize!=1 || desc.MipLevels!=1 ||
           desc.SampleDesc.Count!=1 || !depth_format(desc.Format) ||
           uint64_t(c.depth_x)+c.render_width>desc.Width ||
           uint64_t(c.depth_y)+c.render_height>desc.Height) {++skips_;return;}
        const bool full=(desc.Flags&D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL)!=0;
        const uint32_t w=full?uint32_t(desc.Width):c.render_width;
        const uint32_t h=full?desc.Height:c.render_height;
        if(!w || !h || w>16384 || h>16384 || uint64_t(w)*h*4ull>MaxOwnedDepthBytes) {++skips_;return;}
        ComPtr<ID3D12Device> dev;
        if(FAILED(depth->GetDevice(IID_PPV_ARGS(&dev)))) {++skips_;return;}
        std::scoped_lock guard(lock_);
        if(!enabled_ || !producer_ || !fence_ || dev.Get()!=device_.Get())return;
        std::shared_ptr<DepthSnapshot> slot;
        for(auto& candidate:leases_) {
            if(candidate.use_count()!=1 || candidate->pending ||
               (candidate->producer_fence && fence_->GetCompletedValue()<candidate->producer_fence))
                continue;
            slot=candidate;break;
        }
        if(!slot) {
            if(leases_.size()>=MaxLeases){++skips_;return;}
            slot=std::make_shared<DepthSnapshot>();leases_.push_back(slot);
        }
        const auto existing=slot->texture ? slot->texture->GetDesc():D3D12_RESOURCE_DESC{};
        if(!slot->texture || existing.Width!=w || existing.Height!=h ||
           existing.Format!=DXGI_FORMAT_R32_TYPELESS) {
            uint64_t resident=0;
            for(const auto& lease:leases_) if(lease.get()!=slot.get() && lease->texture) {
                const auto d=lease->texture->GetDesc();
                resident+=uint64_t(d.Width)*d.Height*4ull;
            }
            if(resident+uint64_t(w)*h*4ull>MaxOwnedDepthBytes) {++skips_;return;}
            // Safe: slot is not in use, and its last GPU producer fence retired.
            slot->texture.Reset();
            D3D12_RESOURCE_DESC td=desc;
            td.Width=w;td.Height=h;td.Format=DXGI_FORMAT_R32_TYPELESS;
            td.Flags=D3D12_RESOURCE_FLAG_NONE;td.Alignment=0;
            D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_DEFAULT;
            if(FAILED(dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&td,
                   D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,nullptr,
                   IID_PPV_ARGS(&slot->texture)))) {++skips_;return;}
            slot->texture->SetName(L"DuoView::FovealNGXDepth");
        }
        // NVSDK-NGX D3D12 3.4 requires inputs in NPS state at Evaluate.
        // Recording on the SAME list after Evaluate avoids CPU readback.
        constexpr auto read=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        transition(cmd,depth,read,D3D12_RESOURCE_STATE_COPY_SOURCE);
        transition(cmd,slot->texture.Get(),read,D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_TEXTURE_COPY_LOCATION from{},to{};
        from.pResource=depth;from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        to.pResource=slot->texture.Get();to.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        const D3D12_BOX crop{c.depth_x,c.depth_y,0,c.depth_x+c.render_width,c.depth_y+c.render_height,1};
        cmd->CopyTextureRegion(&to,0,0,0,&from,full?nullptr:&crop);
        transition(cmd,slot->texture.Get(),D3D12_RESOURCE_STATE_COPY_DEST,read);
        transition(cmd,depth,D3D12_RESOURCE_STATE_COPY_SOURCE,read);
        slot->source_reference=depth; // producer lifetime, never sample this borrowed input
        slot->key=key;
        slot->output_identity=output_proof?reinterpret_cast<uintptr_t>(ngx_output):0;
        slot->sequence=++next_capture_sequence_;
        slot->feature=c.feature;
        slot->out_w=c.output_width;slot->out_h=c.output_height;
        slot->tex_w=w;slot->tex_h=h;slot->input_w=c.render_width;slot->input_h=c.render_height;
        slot->base_x=full?c.depth_x:0;slot->base_y=full?c.depth_y:0;
        slot->producer_list=cmd;slot->pending=true;slot->submitted=false;
        slot->producer_fence=0;slot->submission_tick_ms=0;
        ++captures_;
        if(output_proof)++unkeyed_captures_;
    }
    // Called immediately AFTER actual ExecuteCommandLists on the original
    // producer queue. Queue::Signal is GPU ordered after the NGX depth copy.
    void submitted(ID3D12CommandQueue* queue,UINT count,ID3D12CommandList* const* lists,
                   FrameKey executing_rhi_key={}) {
        if(!queue || !count || !lists)return;
        std::scoped_lock guard(lock_);
        if(queue!=producer_.Get() || !enabled_ || !fence_)return;
        std::vector<DepthSnapshot*> matched;
        for(auto& slot:leases_) if(slot->pending)
            for(UINT i=0;i<count;++i)if(static_cast<ID3D12CommandList*>(slot->producer_list)==lists[i]){
                matched.push_back(slot.get());break;
            }
        if(matched.empty())return;
        const uint64_t next=++signal_;
        if(FAILED(queue->Signal(fence_.Get(),next))) {
            for(auto* slot:matched){slot->pending=false;slot->submitted=false;}
            ++skips_;return;
        }
        for(auto* slot:matched){
            // The NGX evaluate callback has no RHI ticket on this game.
            // The exact command-list's ExecuteCommandLists may have one.
            // Never accept a ticket from a different list or partial key.
            if(!slot->key.generation && !slot->key.frame &&
               executing_rhi_key.generation && executing_rhi_key.frame) {
                slot->key=executing_rhi_key;
                ++late_tickets_;
            }
            slot->pending=false;slot->submitted=true;slot->producer_fence=next;
            slot->submission_tick_ms=GetTickCount64();
        }
        submits_+=matched.size();
    }
    // Only the command slot rendering the exact frozen packet may lease it.
    // The caller MUST verify XR's D3D12 queue is producer_ before recording.
    std::shared_ptr<DepthSnapshot> find(ID3D12Device* device,
         ID3D12CommandQueue* queue,FrameKey key,
         uintptr_t feature,uint32_t w,uint32_t h) const {
        std::scoped_lock guard(lock_);
        if(!enabled_ || !device || device!=device_.Get() || !queue ||
           queue!=producer_.Get() || !feature)return {};
        // Lease order is NOT time order: select the newest submitted sample.
        std::shared_ptr<DepthSnapshot> newest{};
        for(const auto& slot:leases_)
            if(slot->submitted && !slot->pending && slot->key==key &&
               slot->producer_fence && slot->feature==feature &&
               slot->out_w==w && slot->out_h==h &&
               (!newest || slot->sequence>newest->sequence)) newest=slot;
        return newest;
    }
    // Only the SAME physical NGX Output used by the fused compositor's
    // native fovea can recover a depth snapshot without a UE RHI ticket.
    // Require the game's exact queue/fence and consume each sequence once.
    std::shared_ptr<DepthSnapshot> find_by_output(ID3D12Device* device,
        ID3D12CommandQueue* queue,ID3D12Resource* fovea,
        uintptr_t feature,uint32_t w,uint32_t h) {
        std::scoped_lock guard(lock_);
        if(!enabled_ || !device || device!=device_.Get() ||
           !queue || queue!=producer_.Get() || !fovea || !feature)return {};
        const auto identity=reinterpret_cast<uintptr_t>(fovea);
        std::shared_ptr<DepthSnapshot> latest{};
        for(const auto& slot:leases_) {
            if(slot->submitted && !slot->pending && !slot->key.generation &&
               !slot->key.frame && slot->output_identity==identity &&
               slot->producer_fence && slot->sequence>last_unkeyed_used_sequence_ &&
               slot->feature==feature && slot->out_w==w && slot->out_h==h &&
               (!latest || slot->sequence>latest->sequence))
                latest=slot;
        }
        if(latest) {
            // Pool order is NOT temporal order: lease slots are recycled.
            // Always choose newest real producer copy, never last vector slot.
            last_unkeyed_used_sequence_=latest->sequence;
            ++output_matches_;
        }
        return latest;
    }
    // Last-resort opt-in delivery path for Unreal post-processing:
    // NGX Output is normally HDR/pre-tonemap while DuoView's native fovea
    // is LDR/post-tonemap, so physical pointer equality is not possible.
    // There is NO fabricated UE frame identity here. Require a LIVE unique
    // selected foveal NGX feature, same actual original game queue/device,
    // a genuinely submitted depth copy, <=100 ms elapsed, and strict one-use.
    // This is ordered producer depth, not a proven same-frame mapping.
    std::shared_ptr<DepthSnapshot> find_recent_ordered(ID3D12Device* device,
        ID3D12CommandQueue* queue, uintptr_t feature,uint32_t w,uint32_t h) {
        std::scoped_lock guard(lock_);
        if(!enabled_ || !device || device!=device_.Get() ||
           !queue || queue!=producer_.Get() || !feature || !w || !h)return {};
        const uint64_t now=GetTickCount64();
        std::shared_ptr<DepthSnapshot> newest{};
        for(const auto& slot:leases_) {
            if(!slot->submitted || slot->pending || slot->key.generation ||
               slot->key.frame || !slot->producer_fence ||
               slot->sequence<=last_unkeyed_used_sequence_ ||
               slot->feature!=feature || slot->out_w!=w || slot->out_h!=h ||
               !slot->submission_tick_ms || slot->submission_tick_ms>now)continue;
            if(now-slot->submission_tick_ms>100u) {++expired_ordered_;continue;}
            if(!newest || slot->sequence>newest->sequence)newest=slot;
        }
        if(newest) {
            last_unkeyed_used_sequence_=newest->sequence;
            ++ordered_matches_;
        }
        return newest;
    }
    void note_used()noexcept {++used_;}
    uint64_t used()const{return used_.load();}
    uint64_t captures()const{return captures_.load();}
    uint64_t unkeyed_captures()const{return unkeyed_captures_.load();}
    uint64_t output_matches()const{return output_matches_.load();}
    uint64_t late_tickets()const{return late_tickets_.load();}
    uint64_t ordered_matches()const{return ordered_matches_.load();}
    uint64_t expired_ordered()const{return expired_ordered_.load();}
    uint64_t skips()const{return skips_.load();}
    uint64_t submits()const{return submits_.load();}
};
inline DepthSnapshotPool& depth_snapshots(){
    static auto* cache=new DepthSnapshotPool();
    return *cache;
}
} // namespace uevr::duoview::ngx

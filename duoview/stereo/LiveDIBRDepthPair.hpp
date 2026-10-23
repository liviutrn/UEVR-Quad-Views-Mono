#pragma once
// Experimental LIVE two-resolution depth snapshots for center-origin DuoView DIBR.
// Candidate extents are deliberately pinned to the user's Build118 STALKER2 proof.
// No Unreal extra views. Explicit opt-in, never enabled in stable Build49 route.
#include <atomic>
#include <chrono>
#include <cstdint>
#include <mutex>
#include <string>
#include <wrl.h>
#include <d3d12.h>
#include <hooks/D3D12Hook.hpp>

namespace uevr::duoview::dx12 {
class DepthPairP1 final : public D3D12DepthStencilObserver {
public:
    using Resource=Microsoft::WRL::ComPtr<ID3D12Resource>;
    bool arm(ID3D12Device* device, ID3D12Resource* /*unused_pool_depth*/) {
        std::scoped_lock lock{mutex_};
        if (armed_.load() || snapshots_[0] || snapshots_[1]) {
            status_="existing experiment still owns depth textures; restart the game to retry";return false;
        }
        if (!device || FAILED(device->GetDeviceRemovedReason())) {
            status_="no healthy D3D12 device";return false;
        }
        // Build118: successful candidate IDs 1/4/5 = 860x684; 6/9 = 344x276.
        // Both were DXGI_FORMAT_R32_TYPELESS (19), and 16->96 barrier candidates.
        // Reject changed DLSS/render settings rather than copy unrelated geometry.
        const unsigned widths[2]={860,344},heights[2]={684,276};
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        Resource allocations[2];
        for (unsigned role=0;role<2;++role) {
            D3D12_RESOURCE_DESC desc{};
            desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
            desc.Width=widths[role];desc.Height=heights[role];
            desc.DepthOrArraySize=desc.MipLevels=1;
            desc.Format=DXGI_FORMAT_R32_TYPELESS;
            desc.SampleDesc.Count=1;
            desc.Layout=D3D12_TEXTURE_LAYOUT_UNKNOWN;
            desc.Flags=D3D12_RESOURCE_FLAG_NONE;
            const auto hr=device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,
                &desc,sample_state(),nullptr,IID_PPV_ARGS(&allocations[role]));
            if (FAILED(hr)) {status_="failed to prewarm a GPU-owned depth SRV";return false;}
            allocations[role]->SetName(role?L"DIBR Periphery Depth":L"DIBR Fovea Depth");
        }
        Microsoft::WRL::ComPtr<ID3D12Fence> fence;
        if (FAILED(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)))) {
            status_="failed to create queue-completion fence";return false;
        }
        snapshots_[0]=std::move(allocations[0]);
        snapshots_[1]=std::move(allocations[1]);
        fence_=std::move(fence);
        device_=device;
        last_us_[0]=last_us_[1]=0;
        recorded_[0]=recorded_[1]=0;
        captured_.store(0,std::memory_order_release);
        fence_signaled_.store(false,std::memory_order_release);
        armed_.store(true,std::memory_order_release);
        status_="LIVE depth armed (860x684 fovea; 344x276 periphery); awaiting safe barriers";
        return true;
    }
    bool armed() const {return armed_.load(std::memory_order_acquire);}
    unsigned captured() const {return captured_.load(std::memory_order_acquire);}
    std::string status() const {std::scoped_lock lock{mutex_};return status_;}
    DXGI_FORMAT srv_format() const {return DXGI_FORMAT_R32_FLOAT;}
    Resource candidate(unsigned index) const {
        std::scoped_lock lock{mutex_};
        return index<2 && captured_.load(std::memory_order_acquire)==2 ?
            snapshots_[index] : Resource{};
    }
    bool signal_after_source_submit(ID3D12CommandQueue* queue) {
        if (!queue || captured_.load(std::memory_order_acquire)!=2 ||
            fence_signaled_.load(std::memory_order_acquire))return false;
        std::scoped_lock lock{mutex_};
        if (!fence_ || fence_signaled_.load(std::memory_order_relaxed))return false;
        // P1 only: this indicates queue marker completion, NOT same-frame RGB-D lineage.
        if (FAILED(queue->Signal(fence_.Get(),1))) {
            status_="queue signal failed: use Mono";return false;
        }
        fence_signaled_.store(true,std::memory_order_release);
        status_="LIVE candidate copies active, queue marker pending; experimental DIBR";
        return true;
    }
    bool gpu_ready() const {
        std::scoped_lock lock{mutex_};
        return captured_.load(std::memory_order_acquire)==2 &&
            fence_signaled_.load(std::memory_order_acquire) &&
            fence_ && fence_->GetCompletedValue()>=1;
    }
    void stop(){armed_.store(false,std::memory_order_release);}
    void on_depth_stencil_view_created(ID3D12Resource*,
        const D3D12_DEPTH_STENCIL_VIEW_DESC*,D3D12_CPU_DESCRIPTOR_HANDLE) override {}
    void on_resource_barriers(ID3D12GraphicsCommandList* cmd,UINT n,
        const D3D12_RESOURCE_BARRIER* barriers) override {
        if (!armed_.load(std::memory_order_acquire)||!cmd||!barriers||
            cmd->GetType()!=D3D12_COMMAND_LIST_TYPE_DIRECT)return;
        std::unique_lock lock{mutex_,std::try_to_lock};
        if (!lock.owns_lock() || !armed_.load(std::memory_order_relaxed))return;
        using Clock=std::chrono::steady_clock;
        const auto us=static_cast<uint64_t>(std::chrono::duration_cast<
            std::chrono::microseconds>(Clock::now().time_since_epoch()).count());
        for (UINT j=0;j<n;++j) {
            const auto& barrier=barriers[j];
            if (barrier.Type!=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION ||
                barrier.Flags!=D3D12_RESOURCE_BARRIER_FLAG_NONE)continue;
            const auto& t=barrier.Transition;
            if (!t.pResource ||
                (t.Subresource!=0 && t.Subresource!=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES) ||
                t.StateBefore!=D3D12_RESOURCE_STATE_DEPTH_WRITE ||
                t.StateAfter!=(D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE|
                               D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE))continue;
            // Avoid copying a resource that also changes state in this barrier batch.
            bool ambiguous=false;
            for(UINT k=0;k<n;++k) if(k!=j &&
                barriers[k].Type==D3D12_RESOURCE_BARRIER_TYPE_TRANSITION &&
                barriers[k].Transition.pResource==t.pResource){ambiguous=true;break;}
            if(ambiguous)continue;
            const auto desc=t.pResource->GetDesc();
            if(desc.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D||
                desc.Format!=DXGI_FORMAT_R32_TYPELESS||
                desc.DepthOrArraySize!=1||desc.MipLevels!=1||desc.SampleDesc.Count!=1||
                !(desc.Flags&D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL))continue;
            unsigned role=2;
            if(desc.Width==860 && desc.Height==684)role=0;
            if(desc.Width==344 && desc.Height==276)role=1;
            if(role>=2 || (last_us_[role] && us-last_us_[role]<20000))continue;
            auto* dst=snapshots_[role].Get();
            if(!dst)continue;
            D3D12_RESOURCE_BARRIER p[2]{};
            p[0].Type=p[1].Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            p[0].Transition={t.pResource,0,D3D12_RESOURCE_STATE_DEPTH_WRITE,
                D3D12_RESOURCE_STATE_COPY_SOURCE};
            p[1].Transition={dst,0,sample_state(),D3D12_RESOURCE_STATE_COPY_DEST};
            cmd->ResourceBarrier(2,p);
            D3D12_TEXTURE_COPY_LOCATION from{},to{};
            from.pResource=t.pResource;
            from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            from.SubresourceIndex=0;
            to.pResource=dst;
            to.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            to.SubresourceIndex=0;
            cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
            for(auto& v:p){
                const auto before=v.Transition.StateBefore;
                v.Transition.StateBefore=v.Transition.StateAfter;
                v.Transition.StateAfter=before;
            }
            cmd->ResourceBarrier(2,p);
            last_us_[role]=us;
            ++recorded_[role];
            if(recorded_[0]&&recorded_[1])
                captured_.store(2,std::memory_order_release);
            else captured_.store(1,std::memory_order_release);
            // One copy per callback: do not extend the render critical section.
            break;
        }
    }
private:
    static constexpr D3D12_RESOURCE_STATES sample_state(){
        return static_cast<D3D12_RESOURCE_STATES>(
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|
            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    }
    mutable std::mutex mutex_;
    Resource snapshots_[2]{};
    Microsoft::WRL::ComPtr<ID3D12Device> device_;
    Microsoft::WRL::ComPtr<ID3D12Fence> fence_;
    uint64_t last_us_[2]{},recorded_[2]{};
    std::atomic<unsigned> captured_{0};
    std::atomic<bool> armed_{false},fence_signaled_{false};
    std::string status_{"disabled; no GPU depth copies"};
};
} // namespace uevr::duoview::dx12

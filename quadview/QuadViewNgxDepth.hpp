#pragma once
// Tri-view B7: capture the DLSS depth input of the PERIPHERY render every frame.
// Hooks (safetyhook, inline): NVSDK_NGX_D3D12_EvaluateFeature(_C) and
// Create/ReleaseFeature(_C) in nvngx_dlss.dll / _nvngx.dll, plus
// ID3D12CommandQueue::ExecuteCommandLists (vtable slot 10) to know when the
// game's command list holding our copy has been submitted. Never interferes
// with DLSS: inputs are restored before the original Evaluate; result is unchanged.
// Selection requires an exact authenticated role-0 source owner; dimensions
// only sanity-check that owner, never supply provenance.
// The depth subrect is copied on the game's own DIRECT command list before
// Evaluate into an owned R32 texture (ALL_SHADER_RESOURCE between uses).
#include <Windows.h>
#include <d3d11.h>
#include <d3d12.h>
#include <wrl/client.h>
#include <safetyhook.hpp>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <utility>
#include <vector>
#include "QuadViewNgxSelect.hpp"
#include "QuadViewDepthIdentity.hpp"

namespace uevr::quadview::ngx {
using Microsoft::WRL::ComPtr;


struct NgxParameters {
    virtual void Set(const char*, unsigned long long) = 0;
    virtual void Set(const char*, float) = 0;
    virtual void Set(const char*, double) = 0;
    virtual void Set(const char*, unsigned int) = 0;
    virtual void Set(const char*, int) = 0;
    virtual void Set(const char*, ID3D11Resource*) = 0;
    virtual void Set(const char*, ID3D12Resource*) = 0;
    virtual void Set(const char*, void*) = 0;
    virtual uint32_t Get(const char*, unsigned long long*) const = 0;
    virtual uint32_t Get(const char*, float*) const = 0;
    virtual uint32_t Get(const char*, double*) const = 0;
    virtual uint32_t Get(const char*, unsigned int*) const = 0;
    virtual uint32_t Get(const char*, int*) const = 0;
    virtual uint32_t Get(const char*, ID3D11Resource**) const = 0;
    virtual uint32_t Get(const char*, ID3D12Resource**) const = 0;
    virtual uint32_t Get(const char*, void**) const = 0;
    virtual void Reset() = 0;
};
inline bool ngx_success(uint32_t r) noexcept { return (r & 0xfff00000u) != 0xbad00000u; }
inline uint32_t ngx_uint(const NgxParameters* p, const char* k) noexcept {
    unsigned int u{};
    if (ngx_success(p->Get(k, &u))) return u;
    int s{};
    return ngx_success(p->Get(k, &s)) && s > 0 ? uint32_t(s) : 0u;
}
inline ID3D12Resource* ngx_resource(const NgxParameters* p, const char* k) noexcept {
    ID3D12Resource* v{};
    return ngx_success(p->Get(k, &v)) ? v : nullptr;
}

struct DepthSnapshot {
    ComPtr<ID3D12Resource> texture;          // owned R32_TYPELESS copy
    ComPtr<ID3D12Resource> source_reference; // retained through producer GPU completion
    ID3D12GraphicsCommandList* producer_list{}; // comparison only
    uint64_t sequence{}, producer_fence_value{}, list_epoch{};
    std::array<float,2> jitter_pixels{}, jitter_uv{};
    bool jitter_valid{};
    DepthOwner owner{};
    bool valid_evaluation{};
    std::chrono::steady_clock::time_point recorded{}, submitted_at{};
    uint32_t out_w{}, out_h{}, rect[4]{};
    DXGI_FORMAT srv_format{DXGI_FORMAT_R32_FLOAT}; // R32_FLOAT or R32_FLOAT_X8X24_TYPELESS (plane 0)
    bool pending{}, submitted{};
};

class PeripheryDepth final {
public:
    static PeripheryDepth& self() { static auto* instance = new PeripheryDepth; return *instance; } // never destroyed

    // Game thread, per draw: expected periphery output size (0 = disabled).
    void set_expected(uint32_t w, uint32_t h) {
        want_w_.store(w, std::memory_order_relaxed); want_h_.store(h, std::memory_order_relaxed);
    }
    // B9 stability gate: no NGX copy recording until exact producer identity,
    // producer completion and consumer retirement are validated together.
    // Existing saved settings and the depth-debug toggle cannot bypass this.
    static constexpr bool capture_supported() noexcept { return false; }
    void set_enabled(bool on) { enabled_.store(on && capture_supported(), std::memory_order_release); }

    // Present thread: install hooks lazily (only while Tri-view depth is on).
    void install(ID3D12CommandQueue* queue) {
        if (!enabled_.load(std::memory_order_acquire) || !queue) return;
        std::scoped_lock lock(mutex_);
        if (!queue_ && queue->GetDesc().Type == D3D12_COMMAND_LIST_TYPE_DIRECT &&
            SUCCEEDED(queue->GetDevice(IID_PPV_ARGS(&device_)))) queue_ = queue;
        if (queue_ && queue_.Get() == queue && !execute_ok_) {
            auto* vtbl = *reinterpret_cast<void***>(queue);
            if (vtbl && vtbl[10]) {
                auto hook = safetyhook::create_inline(vtbl[10], reinterpret_cast<void*>(&execute_commands),
                    safetyhook::InlineHook::StartDisabled);
                if (hook) { execute_ = std::move(hook); if (execute_.enable()) execute_ok_ = true; else execute_.reset(); }
            }
        }
        if (!execute_ok_) return; // never capture without submission tracking
        if (!fence_ && FAILED(device_->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence_)))) return;
        install_group(evals_, eval_ok_, {"NVSDK_NGX_D3D12_EvaluateFeature", "NVSDK_NGX_D3D12_EvaluateFeature_C"},
            {reinterpret_cast<void*>(&evaluate<0>), reinterpret_cast<void*>(&evaluate<1>),
             reinterpret_cast<void*>(&evaluate<2>), reinterpret_cast<void*>(&evaluate<3>),
             reinterpret_cast<void*>(&evaluate<4>), reinterpret_cast<void*>(&evaluate<5>)});
        install_group(creates_, create_ok_, {"NVSDK_NGX_D3D12_CreateFeature", "NVSDK_NGX_D3D12_CreateFeature_C"},
            {reinterpret_cast<void*>(&create<0>), reinterpret_cast<void*>(&create<1>),
             reinterpret_cast<void*>(&create<2>), reinterpret_cast<void*>(&create<3>),
             reinterpret_cast<void*>(&create<4>), reinterpret_cast<void*>(&create<5>)});
        install_group(releases_, release_ok_, {"NVSDK_NGX_D3D12_ReleaseFeature", "NVSDK_NGX_D3D12_ReleaseFeature_C"},
            {reinterpret_cast<void*>(&release<0>), reinterpret_cast<void*>(&release<1>),
             reinterpret_cast<void*>(&release<2>), reinterpret_cast<void*>(&release<3>),
             reinterpret_cast<void*>(&release<4>), reinterpret_cast<void*>(&release<5>)});
    }

    // Exact identity is mandatory. Cross-queue reads are exposed only after
    // producer completion; the consumer retains the shared snapshot until its fence.
    std::shared_ptr<const DepthSnapshot> for_source(const DepthOwner& owner) {
        if (!enabled_.load(std::memory_order_acquire) || !owner.valid()) return {};
        std::scoped_lock lock(mutex_);
        const uint64_t completed=fence_ ? fence_->GetCompletedValue() : 0;
        std::shared_ptr<DepthSnapshot> best;
        for (const auto& slot : pool_) {
            if (slot->submitted && depth_copy_complete(completed,slot->producer_fence_value))
                slot->source_reference.Reset();
            if (slot->submitted && slot->valid_evaluation && slot->texture && slot->owner.same_source(owner) &&
                depth_copy_complete(completed,slot->producer_fence_value) && (!best || slot->sequence>best->sequence)) best=slot;
        }
        if(best) ++used_; else ++missed_;
        return best;
    }
    // Compatibility deliberately refuses the old size/age-only selection.
    std::shared_ptr<const DepthSnapshot> latest() { ++missed_; return {}; }

    struct Stats { uint64_t evaluations, matches, captures, submits, used, missed, skips; uint32_t last_out_w, last_out_h, last_in_w, last_in_h, last_format, hooks; bool queue_hook; };
    Stats stats() const {
        uint32_t hooks = 0; bool queue_hook = false;
        { std::scoped_lock lock(mutex_); for (bool b : eval_ok_) hooks += b; queue_hook = execute_ok_; }
        return {evaluations_.load(), matches_.load(), captures_.load(), submits_.load(), used_.load(), missed_.load(), skips_.load(),
                last_out_w_.load(), last_out_h_.load(), last_in_w_.load(), last_in_h_.load(), last_format_.load(), hooks, queue_hook};
    }

private:
    using Hooks = std::array<safetyhook::InlineHook, 6>; // 3 DLLs x 2 exports
    static constexpr size_t MaxSlots = 8;
    mutable std::mutex mutex_;
    ComPtr<ID3D12CommandQueue> queue_;
    ComPtr<ID3D12Device> device_;
    safetyhook::InlineHook execute_{}, reset_{};
    std::unordered_map<uintptr_t,uint64_t> list_epochs_;
    bool execute_ok_{};
    Hooks evals_{}, creates_{}, releases_{};
    std::array<bool, 6> eval_ok_{}, create_ok_{}, release_ok_{};
    ComPtr<ID3D12Fence> fence_;
    uint64_t next_fence_value_{};
    std::unordered_map<uintptr_t, uint32_t> feature_kind_{};
    std::vector<std::shared_ptr<DepthSnapshot>> pool_{};
    uint64_t next_sequence_{};
    std::atomic<bool> enabled_{false};
    std::atomic<uint32_t> want_w_{}, want_h_{}, last_out_w_{}, last_out_h_{}, last_in_w_{}, last_in_h_{}, last_format_{};
    std::atomic<uint64_t> evaluations_{}, matches_{}, captures_{}, submits_{}, used_{}, missed_{}, skips_{};
    static inline thread_local unsigned nested_{};
    struct Guard { bool outer{nested_++ == 0}; ~Guard() { --nested_; } };

    static void transition(ID3D12GraphicsCommandList* cmd, ID3D12Resource* r, D3D12_RESOURCE_STATES a, D3D12_RESOURCE_STATES b) {
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition = {r, 0, a, b};
        cmd->ResourceBarrier(1, &barrier);
    }

    std::shared_ptr<DepthSnapshot> inspect(ID3D12GraphicsCommandList* cmd, void* feature, const NgxParameters* p) {
        if (!enabled_.load(std::memory_order_acquire) || !cmd || !feature || !p ||
            cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT) return {};
        ++evaluations_;
        const auto* authenticated=DepthOwnerScope::current();
        if (!authenticated || !authenticated->valid()) { ++skips_; return {}; }
        const auto owner=*authenticated;
        const auto out_w = ngx_uint(p, "OutWidth"), out_h = ngx_uint(p, "OutHeight");
        if (!matches_periphery(out_w, out_h, owner.output_width, owner.output_height)) return {};
        {
            std::scoped_lock lock(mutex_);
            const auto found = feature_kind_.find(reinterpret_cast<uintptr_t>(feature));
            if (found != feature_kind_.end() && found->second != 1u) return {}; // only DLSS Super Resolution
        }
        auto* depth = ngx_resource(p, "Depth");
        if (!depth) return {};
        auto in_w = ngx_uint(p, "DLSS.Render.Subrect.Dimensions.Width");
        auto in_h = ngx_uint(p, "DLSS.Render.Subrect.Dimensions.Height");
        if (!in_w) in_w = ngx_uint(p, "Width");
        if (!in_h) in_h = ngx_uint(p, "Height");
        const auto base_x = ngx_uint(p, "DLSS.Input.Depth.Subrect.Base.X"), base_y = ngx_uint(p, "DLSS.Input.Depth.Subrect.Base.Y");
        const auto desc = depth->GetDesc();
        last_format_.store(static_cast<uint32_t>(desc.Format), std::memory_order_relaxed);
        // UE depth is usually D32 + stencil (R32G8X24, two planes): copy and read plane 0 only.
        const bool planar = desc.Format == DXGI_FORMAT_R32G8X24_TYPELESS || desc.Format == DXGI_FORMAT_D32_FLOAT_S8X24_UINT;
        const bool format_ok = planar || desc.Format == DXGI_FORMAT_R32_FLOAT || desc.Format == DXGI_FORMAT_D32_FLOAT ||
                               desc.Format == DXGI_FORMAT_R32_TYPELESS;
        if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.SampleDesc.Count != 1 || desc.DepthOrArraySize != 1 ||
            desc.MipLevels != 1 || !format_ok || !in_w || !in_h || desc.Width > 16384 || desc.Height > 16384 ||
            uint64_t(base_x) + in_w > desc.Width || uint64_t(base_y) + in_h > desc.Height) { ++skips_; return {}; }
        ++matches_;
        last_out_w_.store(out_w, std::memory_order_relaxed); last_out_h_.store(out_h, std::memory_order_relaxed);
        last_in_w_.store(in_w, std::memory_order_relaxed); last_in_h_.store(in_h, std::memory_order_relaxed);
        // Depth-stencil resources only allow whole-subresource copies.
        const bool full = planar || (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL) != 0;
        const auto copy_format = planar ? DXGI_FORMAT_R32G8X24_TYPELESS : DXGI_FORMAT_R32_TYPELESS;
        const uint32_t w = full ? uint32_t(desc.Width) : in_w, h = full ? desc.Height : in_h;
        ComPtr<ID3D12Device> dev;
        if (FAILED(depth->GetDevice(IID_PPV_ARGS(&dev)))) { ++skips_; return {}; }
        std::scoped_lock lock(mutex_);
        if (!device_ || dev.Get() != device_.Get()) { ++skips_; return {}; }
        const auto now = std::chrono::steady_clock::now();
        auto* table=*reinterpret_cast<void***>(cmd);
        if (!table || !table[10]) { ++skips_; return {}; }
        if (!reset_) {
            reset_=safetyhook::create_inline(table[10],reinterpret_cast<void*>(&reset_commands),
                safetyhook::InlineHook::StartDisabled);
            if (!reset_ || !reset_.enable()) { reset_.reset(); ++skips_; return {}; }
        }
        if(reset_.target()!=reinterpret_cast<uint8_t*>(table[10])) { ++skips_; return {}; }
        const auto list_id=reinterpret_cast<uintptr_t>(cmd);
        if(list_epochs_.size()>=128 && !list_epochs_.contains(list_id)) { ++skips_; return {}; }
        auto& epoch=list_epochs_[list_id];if(!epoch) epoch=1;
        if (!fence_) { ++skips_; return {}; }
        const auto completed=fence_->GetCompletedValue();
        std::shared_ptr<DepthSnapshot> slot;
        for (auto& candidate : pool_) {
            if (!depth_slot_reusable(candidate->pending,candidate->submitted,completed,
                    candidate->producer_fence_value,candidate.use_count())) continue;
            if (!slot || candidate->sequence<slot->sequence) slot=candidate;
        }
        if (!slot) {
            if (pool_.size() >= MaxSlots) { ++skips_; return {}; }
            slot = std::make_shared<DepthSnapshot>(); pool_.push_back(slot);
        }
        constexpr auto read = D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE;
        const auto have = slot->texture ? slot->texture->GetDesc() : D3D12_RESOURCE_DESC{};
        if (!slot->texture || have.Width != w || have.Height != h || have.Format != copy_format) {
            // Reallocation only after producer completion and every consumer lease retired.
            slot->texture.Reset();
            D3D12_RESOURCE_DESC td{};
            td.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
            td.Width = w; td.Height = h; td.DepthOrArraySize = 1; td.MipLevels = 1;
            td.Format = copy_format; td.SampleDesc.Count = 1;
            td.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN; td.Flags = D3D12_RESOURCE_FLAG_NONE;
            D3D12_HEAP_PROPERTIES hp{}; hp.Type = D3D12_HEAP_TYPE_DEFAULT;
            if (FAILED(dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &td, read, nullptr, IID_PPV_ARGS(&slot->texture)))) {
                ++skips_; return {};
            }
            slot->texture->SetName(L"QuadView::PeripheryNGXDepth");
        }
        // NGX requires its inputs in NON_PIXEL_SHADER_RESOURCE at Evaluate.
        constexpr auto ngx_state = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        // Plane 0 (depth) only; subresource 0 is the depth plane for every accepted format.
        transition(cmd, depth, ngx_state, D3D12_RESOURCE_STATE_COPY_SOURCE);
        transition(cmd, slot->texture.Get(), read, D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_TEXTURE_COPY_LOCATION from{}, to{};
        from.pResource = depth; from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        to.pResource = slot->texture.Get(); to.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        const D3D12_BOX box{base_x, base_y, 0, base_x + in_w, base_y + in_h, 1};
        cmd->CopyTextureRegion(&to, 0, 0, 0, &from, full ? nullptr : &box);
        transition(cmd, slot->texture.Get(), D3D12_RESOURCE_STATE_COPY_DEST, read);
        transition(cmd, depth, D3D12_RESOURCE_STATE_COPY_SOURCE, ngx_state);
        slot->source_reference = depth;
        slot->owner=owner; slot->list_epoch=epoch; slot->producer_fence_value=0; slot->valid_evaluation=false;
        float jitter_x{},jitter_y{};
        // NVIDIA guide 3.7.3: offsets are actual viewport displacement in
        // render-resolution pixels, screen axes (+right,+down). To sample a
        // jittered depth input for an unjittered color ray, add that displacement.
        slot->jitter_valid=ngx_success(p->Get("Jitter.Offset.X",&jitter_x)) &&
            ngx_success(p->Get("Jitter.Offset.Y",&jitter_y)) &&
            std::isfinite(jitter_x) && std::isfinite(jitter_y) &&
            std::abs(jitter_x)<=0.5f && std::abs(jitter_y)<=0.5f;
        slot->jitter_pixels=slot->jitter_valid ? std::array<float,2>{jitter_x,jitter_y} : std::array<float,2>{};
        slot->jitter_uv={slot->jitter_pixels[0]/in_w,slot->jitter_pixels[1]/in_h};
        slot->producer_list = cmd;
        slot->sequence = ++next_sequence_;
        slot->recorded = now;
        slot->out_w = out_w; slot->out_h = out_h;
        slot->srv_format = planar ? DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS : DXGI_FORMAT_R32_FLOAT;
        slot->rect[0] = full ? base_x : 0; slot->rect[1] = full ? base_y : 0; slot->rect[2] = in_w; slot->rect[3] = in_h;
        slot->pending = true; slot->submitted = false;
        ++captures_;
        return slot;
    }

    void submitted(ID3D12CommandQueue* queue, UINT count, ID3D12CommandList* const* lists) {
        if (!count || !lists) return;
        if (queue != queue_.Get() || !fence_) return;
        bool matched=false;
        for(const auto& slot:pool_) if(slot->pending && list_epochs_[reinterpret_cast<uintptr_t>(slot->producer_list)]==slot->list_epoch)
            for(UINT i=0;i<count;++i) if(static_cast<void*>(lists[i])==static_cast<void*>(slot->producer_list)) matched=true;
        if(!matched) return;
        const auto value=++next_fence_value_;
        // Failure retains all resources and pending slots; time is never retirement proof.
        if(FAILED(queue->Signal(fence_.Get(),value))) { ++skips_; return; }
        for(auto& slot:pool_) if(slot->pending && list_epochs_[reinterpret_cast<uintptr_t>(slot->producer_list)]==slot->list_epoch) for(UINT i=0;i<count;++i) {
            if(static_cast<void*>(lists[i])!=static_cast<void*>(slot->producer_list)) continue;
            slot->pending=false;slot->submitted=true;slot->producer_fence_value=value;
            slot->submitted_at=std::chrono::steady_clock::now();++submits_;break;
        }
    }

    template <unsigned N> static uint32_t __cdecl evaluate(ID3D12GraphicsCommandList* cmd, void* feature, NgxParameters* p, void* cb) {
        auto& s=self(); Guard guard;
        std::shared_ptr<DepthSnapshot> capture;
        // NVIDIA DLSS Programming Guide section 3.4: input depth is
        // NON_PIXEL_SHADER_RESOURCE at API entry. Restore it before NGX executes.
        if(guard.outer) { try { capture=s.inspect(cmd,feature,p); } catch(...) { ++s.skips_; } }
        const auto result=s.evals_[N].unsafe_call<uint32_t>(cmd,feature,p,cb);
        if(capture) { std::scoped_lock lock(s.mutex_);capture->valid_evaluation=ngx_success(result); }
        return result;
    }
    template <unsigned N> static uint32_t __cdecl create(ID3D12GraphicsCommandList* cmd, uint32_t kind, const NgxParameters* p, void** feature) {
        auto& s = self(); Guard g;
        const auto result = s.creates_[N].call<uint32_t>(cmd, kind, p, feature);
        if (g.outer && ngx_success(result) && feature && *feature) {
            std::scoped_lock lock(s.mutex_);
            if (s.feature_kind_.size() >= 128) s.feature_kind_.clear();
            s.feature_kind_[reinterpret_cast<uintptr_t>(*feature)] = kind;
        }
        return result;
    }
    template <unsigned N> static uint32_t __cdecl release(void* feature) {
        auto& s = self(); Guard g;
        const auto result = s.releases_[N].call<uint32_t>(feature);
        if (g.outer && ngx_success(result)) { std::scoped_lock lock(s.mutex_); s.feature_kind_.erase(reinterpret_cast<uintptr_t>(feature)); }
        return result;
    }
    static void __stdcall execute_commands(ID3D12CommandQueue* queue, UINT count, ID3D12CommandList* const* lists) {
        auto& s = self();
        std::scoped_lock lock(s.mutex_);
        s.execute_.unsafe_call<void>(queue, count, lists);
        s.submitted(queue, count, lists);
    }
    static HRESULT __stdcall reset_commands(ID3D12GraphicsCommandList* cmd,ID3D12CommandAllocator* allocator,ID3D12PipelineState* pipeline) {
        auto& s=self();std::scoped_lock lock(s.mutex_);
        const auto result=s.reset_.unsafe_call<HRESULT>(cmd,allocator,pipeline);
        if(SUCCEEDED(result)) {
            const auto id=reinterpret_cast<uintptr_t>(cmd);
            if(s.list_epochs_.contains(id)) ++s.list_epochs_[id];
            // A pending capture from a previous recording is intentionally retained:
            // it cannot be submitted by pointer reuse, recycled by elapsed time, or
            // freed without an independently observed discard proof.
        }
        return result;
    }
    static void install_group(Hooks& hooks, std::array<bool, 6>& installed, std::array<const char*, 2> exports,
                              std::array<void*, 6> callbacks) {
        static const wchar_t* dlls[]{L"nvngx_dlss.dll", L"_nvngx.dll", L"nvngx.dll"};
        for (unsigned dll = 0; dll != 3; ++dll) {
            HMODULE module = GetModuleHandleW(dlls[dll]);
            if (!module) continue;
            for (unsigned e = 0; e != 2; ++e) {
                const unsigned slot = dll * 2 + e;
                if (installed[slot]) continue;
                void* address = reinterpret_cast<void*>(GetProcAddress(module, exports[e]));
                if (!address) continue;
                bool duplicate = false;
                for (unsigned k = 0; k != 6; ++k)
                    if (installed[k] && hooks[k].target() == reinterpret_cast<uint8_t*>(address)) duplicate = true;
                if (duplicate) continue;
                HMODULE pinned{};
                if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_PIN, dlls[dll], &pinned)) continue;
                auto hook = safetyhook::create_inline(address, callbacks[slot], safetyhook::InlineHook::StartDisabled);
                if (!hook) continue;
                hooks[slot] = std::move(hook);
                if (hooks[slot].enable()) installed[slot] = true; else hooks[slot].reset();
            }
        }
    }
};
} // namespace uevr::quadview::ngx

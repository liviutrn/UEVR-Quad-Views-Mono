#pragma once
#include "DepthPolicy.hpp"
#include <hooks/D3D12DepthStencilObserver.hpp>
#include <wrl/client.h>
#include <array>
#include <mutex>
#include <string>
#include <sstream>
#include <algorithm>
#include <unordered_set>

namespace stock_dibr {
// All copies and consumers must be on the swapchain's direct queue. A slot
// belongs to its recording list until actual ExecuteCommandLists, and then to
// its fence until both capture and consumer have retired. No historical image
// is returned when a Present interval contains no newly submitted depth.
class DepthCapture final : public D3D12DepthStencilObserver {
    template<class T> using Ptr = Microsoft::WRL::ComPtr<T>;
    static constexpr size_t Capacity = 12;
    static constexpr auto Read = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE |
        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
    struct Slot {
        Ptr<ID3D12Resource> texture, source;
        Ptr<ID3D12CommandList> list;
        uint64_t epoch{}, serial{}, fence{};
        bool pending{}, leased{};
        Layout layout{Layout::Invalid};
    };
    mutable std::mutex mutex;
    std::array<Slot, Capacity> slots;
    Ptr<ID3D12Device> device;
    Ptr<ID3D12CommandQueue> queue;
    Ptr<ID3D12Fence> fence;
    uint64_t width{}, epoch{1}, serial{}, signal{};
    uint32_t height{}, recorded_this_interval{};
    size_t leased{Capacity};
    bool enabled{};
    std::unordered_set<ID3D12GraphicsCommandList*> render_passes;
    std::string last{"waiting for the first scene extent"};
    uint64_t captured{}, submitted{}, consumed{}, exhausted{}, rejected{};

    static DXGI_FORMAT storage(DXGI_FORMAT f) {
        switch (f) {
        case DXGI_FORMAT_D32_FLOAT: case DXGI_FORMAT_R32_FLOAT: case DXGI_FORMAT_R32_TYPELESS:
            return DXGI_FORMAT_R32_TYPELESS;
        case DXGI_FORMAT_D24_UNORM_S8_UINT: case DXGI_FORMAT_R24G8_TYPELESS:
            return DXGI_FORMAT_R24G8_TYPELESS;
        case DXGI_FORMAT_D16_UNORM: case DXGI_FORMAT_R16_UNORM: case DXGI_FORMAT_R16_TYPELESS:
            return DXGI_FORMAT_R16_TYPELESS;
        default: return DXGI_FORMAT_UNKNOWN;
        }
    }
    bool retire_ready(const Slot& s) const {
        return !s.pending && !s.leased && (!s.fence || completed(fence->GetCompletedValue(), s.fence));
    }
public:
    void configure(ID3D12Device* dev, ID3D12CommandQueue* q, uint64_t w, uint32_t h, bool active) {
        std::scoped_lock lock{mutex};
        // Device/queue changes are handled by the component's drained reset.
        enabled = active && dev && q && q->GetDesc().Type == D3D12_COMMAND_LIST_TYPE_DIRECT;
        if (!enabled) return;
        if (device && (device.Get() != dev || queue.Get() != q)) {
            enabled = false; last = "queue/device changed: runtime reset required"; return;
        }
        if (!device) {
            device = dev; queue = q;
            if (FAILED(dev->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)))) {
                enabled = false; last = "depth fence creation failed"; return;
            }
        }
        if (w && h && (w != width || h != height)) { ++epoch; width = w; height = h; }
    }
    void on_depth_stencil_view_created(ID3D12Resource*, const D3D12_DEPTH_STENCIL_VIEW_DESC*, D3D12_CPU_DESCRIPTOR_HANDLE) override {}
    void on_resource_barriers(ID3D12GraphicsCommandList*, UINT, const D3D12_RESOURCE_BARRIER*) override {}
    void on_render_pass(ID3D12GraphicsCommandList* cmd, bool begin) override {
        std::scoped_lock lock{mutex};
        if (begin) render_passes.insert(cmd); else render_passes.erase(cmd);
    }
    void on_command_list_reset(ID3D12GraphicsCommandList* cmd) override {
        std::scoped_lock lock{mutex};
        render_passes.erase(cmd);
        for (auto& s : slots) if (s.pending && s.list.Get() == cmd) {
            s.pending = false; s.epoch = 0; s.fence = 0;
        }
    }
    void on_post_resource_barriers(ID3D12GraphicsCommandList* cmd, UINT count,
        const D3D12_RESOURCE_BARRIER* barriers) override {
        if (!cmd || !barriers || cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT) return;
        std::scoped_lock lock{mutex};
        if (!enabled || !width || !height || recorded_this_interval >= Capacity || render_passes.contains(cmd)) return;
        for (UINT i = 0; i < count; ++i) {
            const auto& b = barriers[i];
            if (b.Type != D3D12_RESOURCE_BARRIER_TYPE_TRANSITION ||
                b.Flags != D3D12_RESOURCE_BARRIER_FLAG_NONE ||
                (b.Transition.StateBefore & D3D12_RESOURCE_STATE_DEPTH_WRITE) == 0 ||
                (b.Transition.StateAfter & Read) == 0) continue;
            auto* source = b.Transition.pResource;
            if (!source) continue;
            const auto desc = source->GetDesc();
            const auto kind = stock_dibr::layout(desc.Width, desc.Height, width, height);
            const auto format = storage(desc.Format);
            if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
                desc.SampleDesc.Count != 1 || desc.MipLevels != 1 || !desc.DepthOrArraySize ||
                (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL) == 0 ||
                format == DXGI_FORMAT_UNKNOWN || kind == Layout::Invalid) { ++rejected; continue; }
            // Source is the left camera: slice zero, plane zero only. Never
            // copy the right slice or a stencil-only transition.
            if (b.Transition.Subresource != D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES &&
                b.Transition.Subresource != 0) continue;
            auto it = std::find_if(slots.begin(), slots.end(), [&](const Slot& s) { return retire_ready(s); });
            if (it == slots.end()) { ++exhausted; return; }
            auto& s = *it;
            if (!s.texture || s.texture->GetDesc().Width != desc.Width ||
                s.texture->GetDesc().Height != desc.Height || s.texture->GetDesc().Format != format) {
                auto dst = desc; dst.Format = format; dst.DepthOrArraySize = 1;
                dst.Alignment = 0; dst.Flags = D3D12_RESOURCE_FLAG_NONE;
                D3D12_HEAP_PROPERTIES hp{}; hp.Type = D3D12_HEAP_TYPE_DEFAULT;
                s.texture.Reset();
                if (FAILED(device->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &dst,
                    Read, nullptr, IID_PPV_ARGS(&s.texture)))) {
                    last = "live depth allocation failed"; continue;
                }
                s.texture->SetName(L"Stock Joey DIBR live depth");
            }
            D3D12_RESOURCE_BARRIER copy[2]{};
            for (auto& c : copy) c.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            // Original write->read has already executed on the recording list.
            // Only plane zero changes state here, preserving stencil/other eye.
            copy[0].Transition = {source, 0, b.Transition.StateAfter, D3D12_RESOURCE_STATE_COPY_SOURCE};
            copy[1].Transition = {s.texture.Get(), 0, Read, D3D12_RESOURCE_STATE_COPY_DEST};
            cmd->ResourceBarrier(2, copy);
            D3D12_TEXTURE_COPY_LOCATION from{}, to{};
            from.pResource = source; from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            to.pResource = s.texture.Get(); to.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            cmd->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
            std::swap(copy[0].Transition.StateBefore, copy[0].Transition.StateAfter);
            std::swap(copy[1].Transition.StateBefore, copy[1].Transition.StateAfter);
            cmd->ResourceBarrier(2, copy);
            s.source = source; s.list = cmd; s.epoch = epoch; s.serial = ++serial;
            s.pending = true; s.fence = 0; s.layout = kind;
            ++recorded_this_interval; ++captured;
            if (recorded_this_interval >= Capacity) return;
        }
    }
    void on_command_lists_executed(ID3D12CommandQueue* q, UINT count, ID3D12CommandList* const* lists) override {
        std::scoped_lock lock{mutex};
        if (!enabled || !fence || !q || !lists) return;
        bool found{};
        for (auto& s : slots) {
            if (!s.pending) continue;
            bool included{};
            for (UINT i = 0; i < count; ++i) included |= lists[i] == s.list.Get();
            if (!included) continue;
            if (q != queue.Get()) {
                // Unsupported producer queue: keep its recorded resources
                // alive, quarantine the slot and never expose it to DIBR.
                s.epoch = 0; last = "depth executed on another queue; not consumed"; continue;
            }
            if (!found) {
                if (FAILED(q->Signal(fence.Get(), ++signal))) { enabled = false; last = "depth submission signal failed"; return; }
                found = true;
            }
            s.pending = false; s.fence = signal; ++submitted;
        }
    }
    Ptr<ID3D12Resource> acquire() {
        std::scoped_lock lock{mutex};
        Slot* best{};
        for (auto& s : slots) {
            if (s.pending || !s.fence || s.epoch != epoch || s.leased) continue;
            // Prefer the latest write completion of the main-sized source;
            // unequal sizes prefer the largest compatible scene candidate.
            if (!best || s.texture->GetDesc().Width * s.texture->GetDesc().Height >
                    best->texture->GetDesc().Width * best->texture->GetDesc().Height ||
                (s.texture->GetDesc().Width == best->texture->GetDesc().Width && s.serial > best->serial)) best = &s;
        }
        if (!best) { last = "no new submitted scene depth in this Present interval"; return {}; }
        best->leased = true; leased = static_cast<size_t>(best - slots.data()); ++consumed;
        const auto d = best->texture->GetDesc();
        last = "live " + std::to_string(d.Width) + "x" + std::to_string(d.Height) +
            (best->layout == Layout::Packed ? " packed" : " eye") + " copy=" + std::to_string(best->serial);
        return best->texture;
    }
    void finish_frame() {
        std::scoped_lock lock{mutex};
        // Invoked after DIBR has enqueued the consumer. Fence the read before
        // allowing that immutable slot to be overwritten by any producer.
        if (leased < Capacity) {
            auto& s = slots[leased];
            if (FAILED(queue->Signal(fence.Get(), ++signal))) {
                enabled = false; s.pending = true; last = "depth consumer signal failed";
            } else s.fence = signal;
            s.leased = false; leased = Capacity;
        }
        ++epoch; recorded_this_interval = 0;
    }
    std::string summary() const {
        std::scoped_lock lock{mutex};
        return last + " | captured=" + std::to_string(captured) + " submitted=" +
            std::to_string(submitted) + " consumed=" + std::to_string(consumed) +
            " busy=" + std::to_string(exhausted) + " rejected=" + std::to_string(rejected);
    }
    void reset() {
        std::scoped_lock lock{mutex};
        // Caller drains the presentation queue and unregisters the observer.
        // Pending lists may still be submitted by an engine thread after
        // unregistration. Preserve their resources until a Reset cancels them.
        enabled = false;
        for (auto& s : slots) if (retire_ready(s)) s = {};
        width = height = 0; ++epoch; leased = Capacity;
        captured = submitted = consumed = exhausted = rejected = recorded_this_interval = 0;
        last = "reset; waiting for scene depth";
    }
};
}

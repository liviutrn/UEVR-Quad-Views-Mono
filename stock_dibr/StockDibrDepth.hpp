#pragma once
#include "DepthPolicy.hpp"
#include <hooks/D3D12DepthStencilObserver.hpp>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <deque>
#include <list>
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace stock_dibr {
// Captures use a verified direct producer queue; alternate queues require an
// explicit producer fence and a GPU wait on the presentation queue. A slot
// belongs to its recording list until actual ExecuteCommandLists, and then to
// its fence until both capture and consumer have retired. No historical image
// is returned when a Present interval contains no newly submitted depth.
class DepthCapture final : public D3D12DepthStencilObserver {
    template<class T> using Ptr = Microsoft::WRL::ComPtr<T>;
    static constexpr size_t Capacity = 12;
    static constexpr size_t DsvCapacity = 4096;
    static constexpr size_t ListCapacity = 256;
    static constexpr size_t ViewportCapacity = 16;
    static constexpr size_t BindingProofCapacity = 64;
    static constexpr size_t ExecutedProofCapacity = 1024;
    static constexpr auto Read = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE |
        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;

    struct Slot {
        Ptr<ID3D12Resource> texture, source;
        Ptr<ID3D12CommandList> list;
        Ptr<IUnknown> list_identity;
        uint64_t epoch{}, serial{}, fence{}, capture_event{};
        bool pending{}, leased{};
        Ptr<ID3D12Fence> foreign_fence;
        bool quarantined{};
        Layout layout{Layout::Invalid};
        D3D12_VIEWPORT viewport{};
    };
    struct ListState {
        Ptr<ID3D12GraphicsCommandList> owner;
        Ptr<IUnknown> identity;
        SIZE_T bound_dsv_handle{};
        ID3D12Resource* bound_dsv_resource{}; // non-owning; compared only, never dereferenced
        std::array<D3D12_VIEWPORT, ViewportCapacity> viewports{};
        UINT viewport_count{};
        struct BindingProof {
            ID3D12Resource* resource{}; // non-owning; compared only, never dereferenced
            SIZE_T handle{};
            D3D12_VIEWPORT viewport{};
            uint64_t event{};
        };
        std::array<BindingProof, BindingProofCapacity> proofs{};
        UINT proof_count{};
        uint64_t touch{}, event{};
    };
    struct RetiredGeneration {
        Ptr<ID3D12Device> device;
        Ptr<ID3D12CommandQueue> queue;
        Ptr<ID3D12Fence> fence;
        std::array<Slot, Capacity> slots;
        uint64_t signal{};
    };
    struct ExecutedProof {
        ID3D12Resource* resource{}; // non-owning; compared only, never dereferenced
        D3D12_VIEWPORT viewport{};
        Ptr<IUnknown> queue_identity, list_identity;
        uint64_t epoch{}, batch{}, event{};
        UINT list_index{};
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
    std::unordered_map<SIZE_T, ID3D12Resource*> dsv_resources;
    std::unordered_map<SIZE_T, bool> dsv_primary_slice;
    std::deque<SIZE_T> dsv_order;
    std::unordered_map<IUnknown*, ListState> lists;
    std::vector<RetiredGeneration> retired;
    std::deque<ExecutedProof> executed_proofs;
    uint64_t list_touch{};
    uint64_t execute_batch{};
    std::unordered_set<IUnknown*> render_passes;
    std::string last{"waiting for the first scene extent"};
    uint64_t captured{}, submitted{}, consumed{}, exhausted{}, rejected{};
    uint64_t dsv_events{}, bind_events{}, viewport_events{}, read_windows{};
    uint64_t execute_events{}, same_queue_events{}, matched_lists{}, foreign_matches{}, reset_discards{}, cross_queue_consumed{};
    std::array<uint64_t, 7> reject_reasons{};
    std::string observed{"none"};

    static DXGI_FORMAT storage(DXGI_FORMAT f) {
        switch (f) {
        case DXGI_FORMAT_R32G8X24_TYPELESS: case DXGI_FORMAT_D32_FLOAT_S8X24_UINT:
            return DXGI_FORMAT_R32G8X24_TYPELESS;
        case DXGI_FORMAT_D32_FLOAT: case DXGI_FORMAT_R32_FLOAT: case DXGI_FORMAT_R32_TYPELESS:
            return DXGI_FORMAT_R32_TYPELESS;
        case DXGI_FORMAT_D24_UNORM_S8_UINT: case DXGI_FORMAT_R24G8_TYPELESS:
            return DXGI_FORMAT_R24G8_TYPELESS;
        case DXGI_FORMAT_D16_UNORM: case DXGI_FORMAT_R16_UNORM: case DXGI_FORMAT_R16_TYPELESS:
            return DXGI_FORMAT_R16_TYPELESS;
        default: return DXGI_FORMAT_UNKNOWN;
        }
    }
    static bool close_extent(double value, double expected) {
        return std::isfinite(value) && std::abs(value - expected) <= 8.0;
    }
    static bool primary_slice(const D3D12_DEPTH_STENCIL_VIEW_DESC* dsv) {
        if (!dsv) return true;
        switch (dsv->ViewDimension) {
        case D3D12_DSV_DIMENSION_TEXTURE2DARRAY: return dsv->Texture2DArray.FirstArraySlice == 0;
        case D3D12_DSV_DIMENSION_TEXTURE2DMSARRAY: return dsv->Texture2DMSArray.FirstArraySlice == 0;
        default: return true;
        }
    }
    bool main_viewport_shape(const D3D12_VIEWPORT& v) const {
        if (!width || !height || !(v.Width > 0.0f) || !(v.Height > 0.0f) ||
            !close_extent(v.TopLeftX, 0.0) || !close_extent(v.TopLeftY, 0.0)) return false;
        const double scale = double(v.Height) / double(height);
        if (scale < 0.20 || scale > 1.01) return false;
        const double eye_width = double(width / 2) * scale;
        const double packed_width = double(width) * scale;
        return close_extent(v.Width, eye_width) || close_extent(v.Width, packed_width);
    }
    bool viewport_matches_source(const D3D12_VIEWPORT& v,
        const D3D12_RESOURCE_DESC& depth, Layout) const {
        // RDG can retain an oversized allocation after a resolution change.
        // The bound viewport, not the allocation, defines current scene pixels.
        return main_viewport_shape(v) && v.TopLeftX >= 0 && v.TopLeftY >= 0 &&
            double(v.TopLeftX) + v.Width <= double(depth.Width) + 0.01 &&
            double(v.TopLeftY) + v.Height <= double(depth.Height) + 0.01;
    }
    void remember_main_bindings(ListState& state) {
        if (!state.bound_dsv_resource) return;
        for (UINT i = 0; i < state.viewport_count; ++i) {
            const auto& viewport = state.viewports[i];
            if (!main_viewport_shape(viewport)) continue;
            bool exists{};
            // Collapse consecutive equal bindings only. A -> B -> A must
            // retain the last A so publication sees the current rectangle.
            for (UINT j = state.proof_count; j > 0; --j) {
                const auto& proof = state.proofs[j - 1];
                if (proof.resource != state.bound_dsv_resource) continue;
                exists = proof.handle == state.bound_dsv_handle &&
                    proof.viewport.TopLeftX == viewport.TopLeftX && proof.viewport.TopLeftY == viewport.TopLeftY &&
                    proof.viewport.Width == viewport.Width && proof.viewport.Height == viewport.Height;
                break;
            }
            if (exists) continue;
            if (state.proof_count == BindingProofCapacity) {
                std::move(state.proofs.begin() + 1, state.proofs.end(), state.proofs.begin());
                --state.proof_count;
            }
            state.proofs[state.proof_count++] = {state.bound_dsv_resource, state.bound_dsv_handle, viewport, state.event};
        }
    }
    bool recorded_viewport(ID3D12Resource* resource,
        const D3D12_RESOURCE_DESC& depth, D3D12_VIEWPORT& selected) const {
        double best{};
        const auto consider = [&](ID3D12Resource* r, const D3D12_VIEWPORT& vp) {
            if (r == resource && viewport_matches_source(vp, depth, Layout::Eye) &&
                double(vp.Width) * vp.Height > best) {
                selected = vp; best = double(vp.Width) * vp.Height;
            }
        };
        for (const auto& [cmd, state] : lists) {
            (void)cmd;
            for (UINT i = 0; i < state.proof_count; ++i) consider(state.proofs[i].resource, state.proofs[i].viewport);
        }
        for (const auto& proof : executed_proofs)
            if (proof.epoch == epoch) consider(proof.resource, proof.viewport);
        return best > 0;
    }
    bool select_executed_main_binding(ID3D12Resource* resource, const D3D12_RESOURCE_DESC& depth,
        IUnknown* producer, IUnknown* capture_list, uint64_t capture_event, uint64_t batch, UINT list_index,
        D3D12_VIEWPORT& selected) const {
        const ExecutedProof* latest{};
        for (const auto& proof : executed_proofs) {
            if (proof.epoch != epoch || proof.resource != resource || proof.queue_identity.Get() != producer ||
                proof.batch > batch || (proof.batch == batch && proof.list_index > list_index)) continue;
            if (proof.batch == batch && proof.list_index == list_index &&
                proof.list_identity.Get() == capture_list && proof.event > capture_event) continue;
            if (!viewport_matches_source(proof.viewport, depth, Layout::Eye)) continue;
            if (!latest || proof.batch > latest->batch ||
                (proof.batch == latest->batch && proof.list_index > latest->list_index) ||
                (proof.batch == latest->batch && proof.list_index == latest->list_index && proof.event > latest->event))
                latest = &proof;
        }
        if (!latest) return false;
        selected = latest->viewport;
        return true;
    }
    bool retire_ready(const Slot& s, ID3D12Fence* f) const {
        if (s.quarantined || s.pending || s.leased) return false;
        if (s.foreign_fence && !completed(s.foreign_fence->GetCompletedValue(), 1)) return false;
        return !s.pending && !s.leased && (!s.fence || (f && completed(f->GetCompletedValue(), s.fence)));
    }
    static Ptr<IUnknown> object_identity(IUnknown* object) {
        Ptr<IUnknown> result;
        if (object) object->QueryInterface(IID_PPV_ARGS(&result));
        return result;
    }
    ListState& list_state(ID3D12GraphicsCommandList* cmd) {
        auto identity = object_identity(cmd);
        auto found = lists.find(identity.Get());
        if (found != lists.end()) { found->second.touch = ++list_touch; return found->second; }
        if (lists.size() >= ListCapacity) {
            auto oldest = lists.begin();
            for (auto it = lists.begin(); it != lists.end(); ++it)
                if (it->second.touch < oldest->second.touch) oldest = it;
            render_passes.erase(oldest->first);
            lists.erase(oldest);
        }
        auto [it, inserted] = lists.emplace(identity.Get(), ListState{});
        (void)inserted;
        it->second.owner = cmd;
        it->second.identity = std::move(identity);
        it->second.touch = ++list_touch;
        return it->second;
    }
    void collect_retired() {
        for (auto generation = retired.begin(); generation != retired.end();) {
            bool ready = true;
            for (auto& s : generation->slots) {
                if (retire_ready(s, generation->fence.Get())) s = {};
                else ready = false;
            }
            if (ready) generation = retired.erase(generation);
            else ++generation;
        }
    }
    void reset_pending_list(std::array<Slot, Capacity>& slots_to_check, ID3D12GraphicsCommandList* cmd) {
        for (auto& s : slots_to_check) if (s.pending && !s.quarantined && s.list_identity.Get() == object_identity(cmd).Get()) {
            s.pending = false; s.epoch = 0; s.fence = 0;
        }
    }
    static bool submitted_by(const Slot& s, UINT count, ID3D12CommandList* const* submitted_lists) {
        if (!s.pending || !submitted_lists) return false;
        for (UINT i = 0; i < count; ++i) if (submitted_lists[i] == s.list.Get() ||
            (s.list_identity && object_identity(submitted_lists[i]).Get() == s.list_identity.Get())) return true;
        return false;
    }
    static bool same_queue(ID3D12CommandQueue* a, ID3D12CommandQueue* b) {
        if (!a || !b) return false;
        if (a == b) return true;
        Ptr<IUnknown> left, right;
        return SUCCEEDED(a->QueryInterface(IID_PPV_ARGS(&left))) &&
            SUCCEEDED(b->QueryInterface(IID_PPV_ARGS(&right))) && left.Get() == right.Get();
    }
    void submit_retired(ID3D12CommandQueue* q, UINT count, ID3D12CommandList* const* submitted_lists) {
        for (auto& generation : retired) {
            for (auto& s : generation.slots) if (submitted_by(s, count, submitted_lists)) {
                s.epoch = 0;
                if (same_queue(q, generation.queue.Get())) {
                    const auto value = ++generation.signal;
                    if (SUCCEEDED(q->Signal(generation.fence.Get(), value))) {
                        s.pending = false; s.fence = value;
                    } else s.quarantined = true;
                } else {
                    Ptr<ID3D12Device> producer_device;
                    if (SUCCEEDED(s.source->GetDevice(IID_PPV_ARGS(&producer_device))) &&
                        SUCCEEDED(producer_device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&s.foreign_fence))) &&
                        SUCCEEDED(q->Signal(s.foreign_fence.Get(), 1))) {
                        s.pending = false; s.fence = 0;
                    } else s.quarantined = true;
                }
            }
        }
    }

public:
    bool accepts_cached_dsv_metadata() const override { return true; }
    void configure(ID3D12Device* dev, ID3D12CommandQueue* q, uint64_t w, uint32_t h, bool active) {
        std::scoped_lock lock{mutex};
        collect_retired();
        enabled = active && dev && q && q->GetDesc().Type == D3D12_COMMAND_LIST_TYPE_DIRECT;
        if (!enabled) return;
        if (device && (device.Get() != dev || queue.Get() != q)) {
            enabled = false; last = "device/queue changed without reset"; return;
        }
        if (!device) {
            device = dev; queue = q;
            if (FAILED(dev->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)))) {
                enabled = false; last = "depth fence creation failed"; return;
            }
        }
        if (w && h && (w != width || h != height)) {
            ++epoch; width = w; height = h; executed_proofs.clear();
            for (auto& [cmd, state] : lists) { (void)cmd; state.proof_count = 0; }
        }
    }
    void on_depth_stencil_view_created(ID3D12Resource* resource,
        const D3D12_DEPTH_STENCIL_VIEW_DESC* dsv, D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override {
        if (!descriptor.ptr) return;
        std::scoped_lock lock{mutex};
        ++dsv_events;
        const auto key = descriptor.ptr;
        const bool primary = resource && primary_slice(dsv);
        const auto existing = dsv_resources.find(key);
        if (existing != dsv_resources.end()) {
            existing->second = resource;
            dsv_primary_slice[key] = primary;
        } else {
            if (dsv_resources.size() >= DsvCapacity) {
                const auto evicted = dsv_order.front(); dsv_order.pop_front();
                dsv_resources.erase(evicted);
                dsv_primary_slice.erase(evicted);
                for (auto& [cmd, state] : lists) {
                    (void)cmd;
                    if (state.bound_dsv_handle == evicted) state.bound_dsv_resource = nullptr;
                    for (UINT i = 0; i < state.proof_count;) {
                        if (state.proofs[i].handle == evicted) {
                            std::move(state.proofs.begin() + i + 1, state.proofs.begin() + state.proof_count,
                                state.proofs.begin() + i);
                            --state.proof_count;
                        } else ++i;
                    }
                }
            }
            dsv_resources.emplace(key, resource);
            dsv_primary_slice.emplace(key, primary);
            dsv_order.push_back(key);
        }
        for (auto& [cmd, state] : lists) {
            (void)cmd;
            for (UINT i = 0; i < state.proof_count;) {
                if (state.proofs[i].handle == key) {
                    std::move(state.proofs.begin() + i + 1, state.proofs.begin() + state.proof_count,
                        state.proofs.begin() + i);
                    --state.proof_count;
                } else ++i;
            }
            if (state.bound_dsv_handle == key) {
                state.bound_dsv_resource = primary ? resource : nullptr;
                ++state.event;
                remember_main_bindings(state);
            }
        }
    }
    void on_resource_barriers(ID3D12GraphicsCommandList*, UINT, const D3D12_RESOURCE_BARRIER*) override {}
    void on_render_targets(ID3D12GraphicsCommandList* cmd, UINT, D3D12_CPU_DESCRIPTOR_HANDLE dsv) override {
        if (!cmd) return;
        std::scoped_lock lock{mutex};
        auto& state = list_state(cmd);
        ++bind_events; ++state.event;
        state.bound_dsv_handle = dsv.ptr;
        const auto found = dsv_resources.find(dsv.ptr);
        const auto primary = dsv_primary_slice.find(dsv.ptr);
        state.bound_dsv_resource = dsv.ptr && found != dsv_resources.end() &&
            primary != dsv_primary_slice.end() && primary->second ? found->second : nullptr;
        remember_main_bindings(state);
    }
    void on_viewports(ID3D12GraphicsCommandList* cmd, UINT count, const D3D12_VIEWPORT* viewports) override {
        if (!cmd) return;
        std::scoped_lock lock{mutex};
        auto& state = list_state(cmd);
        ++viewport_events; ++state.event;
        state.viewport_count = viewports && count <= ViewportCapacity ? count : 0;
        for (UINT i = 0; i < state.viewport_count; ++i) state.viewports[i] = viewports[i];
        remember_main_bindings(state);
    }
    void on_render_pass(ID3D12GraphicsCommandList* cmd, bool begin) override {
        std::scoped_lock lock{mutex};
        if (begin) { (void)list_state(cmd); render_passes.insert(object_identity(cmd).Get()); }
        else render_passes.erase(object_identity(cmd).Get());
    }
    void on_command_list_reset(ID3D12GraphicsCommandList* cmd) override {
        std::scoped_lock lock{mutex};
        for (const auto& s : slots) if (s.pending && s.list_identity.Get() == object_identity(cmd).Get()) ++reset_discards;
        render_passes.erase(object_identity(cmd).Get());
        lists.erase(object_identity(cmd).Get());
        reset_pending_list(slots, cmd);
        for (auto& generation : retired) reset_pending_list(generation.slots, cmd);
        collect_retired();
    }
    void on_post_resource_barriers(ID3D12GraphicsCommandList* cmd, UINT count,
        const D3D12_RESOURCE_BARRIER* barriers) override {
        if (!cmd || !barriers || cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT) return;
        std::scoped_lock lock{mutex};
        if (!enabled || !width || !height || recorded_this_interval >= Capacity || render_passes.contains(object_identity(cmd).Get())) return;
        const auto capture_event = ++list_state(cmd).event;
        for (UINT i = 0; i < count; ++i) {
            const auto& b = barriers[i];
            if (b.Type != D3D12_RESOURCE_BARRIER_TYPE_TRANSITION ||
                b.Flags != D3D12_RESOURCE_BARRIER_FLAG_NONE ||
                (b.Transition.StateBefore & (D3D12_RESOURCE_STATE_DEPTH_WRITE | D3D12_RESOURCE_STATE_DEPTH_READ)) == 0 ||
                (b.Transition.StateAfter & Read) == 0) continue;
            auto* source = b.Transition.pResource;
            if (!source) continue;
            ++read_windows;
            // The whole barrier batch has executed. A later transition or
            // aliasing operation can invalidate this entry's apparent state.
            bool superseded{};
            for (UINT j = i + 1; j < count; ++j) {
                const auto& later = barriers[j];
                if (later.Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION && later.Transition.pResource == source) superseded = true;
                if (later.Type == D3D12_RESOURCE_BARRIER_TYPE_ALIASING &&
                    (!later.Aliasing.pResourceBefore || !later.Aliasing.pResourceAfter ||
                     later.Aliasing.pResourceBefore == source || later.Aliasing.pResourceAfter == source)) superseded = true;
            }
            if (superseded) { ++reject_reasons[0]; continue; }
            const auto desc = source->GetDesc();
            D3D12_VIEWPORT source_viewport{};
            const auto format = storage(desc.Format);
            if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
                desc.SampleDesc.Count != 1 || desc.MipLevels != 1 || !desc.DepthOrArraySize ||
                (desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL) == 0 ||
                desc.Width > 32768 || desc.Height > 32768 || format == DXGI_FORMAT_UNKNOWN) {
                ++rejected; ++reject_reasons[1]; continue;
            }
            observed = std::to_string(desc.Width) + "x" + std::to_string(desc.Height) + " fmt=" + std::to_string(desc.Format);
            if (!recorded_viewport(source, desc, source_viewport)) {
                ++rejected; ++reject_reasons[2]; continue;
            }
            const auto kind = stock_dibr::layout(static_cast<uint64_t>(std::lround(source_viewport.Width)),
                static_cast<uint32_t>(std::lround(source_viewport.Height)), width, height);
            if (kind == Layout::Invalid) { ++rejected; ++reject_reasons[3]; continue; }
            Ptr<IUnknown> source_device, command_device, expected_device;
            if (FAILED(source->GetDevice(IID_PPV_ARGS(&source_device))) ||
                FAILED(cmd->GetDevice(IID_PPV_ARGS(&command_device))) ||
                FAILED(device.As(&expected_device)) || source_device.Get() != expected_device.Get() ||
                command_device.Get() != expected_device.Get()) { ++rejected; ++reject_reasons[4]; continue; }
            // Source is the left camera: slice zero, plane zero only. Never
            // copy the right slice or a stencil-only transition.
            if (b.Transition.Subresource != D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES &&
                b.Transition.Subresource != 0) { ++reject_reasons[5]; continue; }
            auto it = std::find_if(slots.begin(), slots.end(), [&](const Slot& s) { return retire_ready(s, fence.Get()); });
            if (it == slots.end()) { ++exhausted; return; }
            auto& s = *it;
            s.foreign_fence.Reset();
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
            // Original write->read has already been recorded on the list.
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
            s.source = source; s.list = cmd; s.list_identity = object_identity(cmd); s.epoch = epoch; s.serial = ++serial;
            s.pending = true; s.fence = 0; s.capture_event = capture_event; s.layout = kind; s.viewport = source_viewport;
            ++recorded_this_interval; ++captured;
            if (recorded_this_interval >= Capacity) return;
        }
    }
    void on_command_lists_executed(ID3D12CommandQueue* q, UINT count, ID3D12CommandList* const* submitted_lists) override {
        std::scoped_lock lock{mutex};
        if (!q || !submitted_lists) return;
        ++execute_events;
        const bool current_queue = fence && same_queue(q, queue.Get());
        if (current_queue) ++same_queue_events;
        const auto producer_identity = object_identity(q);
        Ptr<IUnknown> producer_device, expected_device;
        const bool valid_producer = device && q->GetDesc().Type == D3D12_COMMAND_LIST_TYPE_DIRECT &&
            SUCCEEDED(q->GetDevice(IID_PPV_ARGS(&producer_device))) &&
            SUCCEEDED(device.As(&expected_device)) && producer_device.Get() == expected_device.Get();
        const auto batch = ++execute_batch;
        if (valid_producer) {
            for (UINT i = 0; i < count; ++i) {
                if (submitted_lists[i] == nullptr || submitted_lists[i]->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT)
                    continue;
                const auto identity = object_identity(submitted_lists[i]);
                const auto found = lists.find(identity.Get());
                if (found == lists.end()) continue;
                for (UINT j = 0; j < found->second.proof_count; ++j) {
                    const auto& proof = found->second.proofs[j];
                    executed_proofs.push_back({proof.resource, proof.viewport, producer_identity, identity, epoch, batch, proof.event, i});
                    if (executed_proofs.size() > ExecutedProofCapacity) executed_proofs.pop_front();
                }
            }
        }
        bool found{};
        for (auto& s : slots) {
            if (!submitted_by(s, count, submitted_lists)) continue;
            ++matched_lists;
            UINT capture_index{};
            for (; capture_index < count; ++capture_index)
                if (submitted_lists[capture_index] == s.list.Get() ||
                    object_identity(submitted_lists[capture_index]).Get() == s.list_identity.Get()) break;
            const auto desc = s.source->GetDesc();
            // Recording-time metadata only establishes whether a copy is worth
            // recording. Its viewport may belong to an unsubmitted list. Use
            // the actual ordered producer proof for the published sample rect.
            const bool provenance_ok = enabled && valid_producer && select_executed_main_binding(
                s.source.Get(), desc, producer_identity.Get(), s.list_identity.Get(), s.capture_event,
                batch, capture_index, s.viewport);
            if (provenance_ok) s.layout = stock_dibr::layout(
                static_cast<uint64_t>(std::lround(s.viewport.Width)),
                static_cast<uint32_t>(std::lround(s.viewport.Height)), width, height);
            if (current_queue) {
                if (!found) {
                    if (FAILED(q->Signal(fence.Get(), ++signal))) { enabled = false; last = "depth submission signal failed"; return; }
                    found = true;
                }
                s.pending = false; s.fence = signal;
            } else {
                // Alternate direct scene queues are supported only after a real
                // submission and producer-local DSV/viewport ordering proof.
                // Give this owned copy a producer fence; acquire adds a GPU
                // wait on the presentation queue before the synthesis dispatch.
                ++foreign_matches; s.fence = 0;
                if (SUCCEEDED(s.source->GetDevice(IID_PPV_ARGS(&producer_device))) &&
                    SUCCEEDED(q->GetDevice(IID_PPV_ARGS(&expected_device))) &&
                    producer_device.Get() == expected_device.Get() &&
                    SUCCEEDED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&s.foreign_fence))) &&
                    SUCCEEDED(q->Signal(s.foreign_fence.Get(), 1))) {
                    s.pending = false;
                } else {
                    s.epoch = 0; s.quarantined = true;
                    last = "alternate queue submission could not be fenced; slot quarantined";
                    continue;
                }
            }
            if (!provenance_ok) { s.epoch = 0; ++rejected; ++reject_reasons[6]; last = "capture rejected: no prior same-queue main DSV/viewport proof"; }
            else ++submitted;
        }
        submit_retired(q, count, submitted_lists);
        collect_retired();
    }
    Ptr<ID3D12Resource> acquire() {
        std::scoped_lock lock{mutex};
        collect_retired();
        Slot* best{};
        for (auto& s : slots) {
            if (s.pending || (!s.fence && !s.foreign_fence) || s.epoch != epoch || s.leased || s.quarantined) continue;
            if (!best || double(s.viewport.Width) * s.viewport.Height > double(best->viewport.Width) * best->viewport.Height ||
                (s.viewport.Width == best->viewport.Width && s.serial > best->serial)) best = &s;
        }
        if (!best) { last = "no new submitted main-view depth in this Present interval"; return {}; }
        if (best->foreign_fence) {
            if (!queue || FAILED(queue->Wait(best->foreign_fence.Get(), 1))) {
                best->epoch = 0; last = "alternate queue consumer wait failed"; return {};
            }
            ++cross_queue_consumed;
        }
        best->leased = true; leased = static_cast<size_t>(best - slots.data()); ++consumed;
        const auto d = best->texture->GetDesc();
        last = "live main-view " + std::to_string(d.Width) + "x" + std::to_string(d.Height) +
            (best->layout == Layout::Packed ? " packed" : " eye") + " copy=" + std::to_string(best->serial);
        return best->texture;
    }
    std::array<float, 4> sample_uv() const {
        std::scoped_lock lock{mutex};
        if (leased >= Capacity) return {};
        const auto& s = slots[leased]; const auto d = s.texture->GetDesc();
        const auto left_width = s.viewport.Width / (s.layout == Layout::Packed ? 2.0f : 1.0f);
        return {left_width / float(d.Width), s.viewport.Height / float(d.Height),
            s.viewport.TopLeftX / float(d.Width), s.viewport.TopLeftY / float(d.Height)};
    }
    void finish_frame() {
        std::scoped_lock lock{mutex};
        if (leased < Capacity) {
            auto& s = slots[leased];
            if (queue && fence && SUCCEEDED(queue->Signal(fence.Get(), ++signal))) s.fence = signal;
            else { enabled = false; s.pending = true; last = "depth consumer signal failed"; }
            s.leased = false; leased = Capacity;
        }
        ++epoch; recorded_this_interval = 0;
        executed_proofs.clear();
        collect_retired();
    }
    std::string summary() const {
        std::scoped_lock lock{mutex};
        return last + " | captured=" + std::to_string(captured) + " submitted=" +
            std::to_string(submitted) + " consumed=" + std::to_string(consumed) +
            " busy=" + std::to_string(exhausted) + " rejected=" + std::to_string(rejected) +
            " retired=" + std::to_string(retired.size()) +
            " hooks[dsv/bind/vp]=" + std::to_string(dsv_events) + "/" + std::to_string(bind_events) + "/" + std::to_string(viewport_events) +
            " exec[all/same/matched/alternate/resetDiscard]=" + std::to_string(execute_events) + "/" +
            std::to_string(same_queue_events) + "/" + std::to_string(matched_lists) + "/" +
            std::to_string(foreign_matches) + "/" + std::to_string(reset_discards) +
            " crossQueueUsed=" + std::to_string(cross_queue_consumed) +
            " windows=" + std::to_string(read_windows) + " rejects[batch/shape/binding/layout/device/slice/order]=" +
            std::to_string(reject_reasons[0]) + "/" + std::to_string(reject_reasons[1]) + "/" + std::to_string(reject_reasons[2]) + "/" +
            std::to_string(reject_reasons[3]) + "/" + std::to_string(reject_reasons[4]) + "/" + std::to_string(reject_reasons[5]) + "/" + std::to_string(reject_reasons[6]) +
            " observed=" + observed;
    }
    void reset() {
        std::scoped_lock lock{mutex};
        enabled = false;
        if (device || queue || fence) {
            RetiredGeneration generation{};
            generation.device = std::move(device);
            generation.queue = std::move(queue);
            generation.fence = std::move(fence);
            generation.signal = signal;
            generation.slots = std::move(slots);
            // This signal is only a retirement marker for work already queued;
            // unsubmitted recordings remain pending until their list is Reset.
            const auto drain = generation.signal + 1;
            if (generation.queue && generation.fence && SUCCEEDED(generation.queue->Signal(generation.fence.Get(), drain))) {
                generation.signal = drain;
                for (auto& s : generation.slots) if (!s.pending) {
                    s.leased = false;
                    s.fence = drain;
                }
            }
            retired.push_back(std::move(generation));
        }
        slots = {};
        width = 0; height = 0; ++epoch; leased = Capacity; signal = 0;
        recorded_this_interval = 0;
        lists.clear(); render_passes.clear(); executed_proofs.clear(); execute_batch = 0;
        captured = submitted = consumed = exhausted = rejected = 0;
        collect_retired();
        last = "reset; waiting for scene depth";
    }
};
}

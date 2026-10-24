#pragma once

#include "../dibr/DuoViewDibrD3D12.hpp"
#include "../dibr/ManualDibrPreview.hpp"
#if __has_include("../joey_stage1/DuoViewDelivery.hpp")
#include "../joey_stage1/DuoViewDelivery.hpp"
#else
#include "../DuoViewDelivery.hpp"
#endif

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <vector>
#include <windows.h>
#include <wrl.h>

namespace uevr::duoview::dibr::dx12 {

using Microsoft::WRL::ComPtr;

inline thread_local bool manual_dibr_injected_command = false;
struct ManualDibrInjectedCommandGuard {
    bool previous{manual_dibr_injected_command};
    ManualDibrInjectedCommandGuard() { manual_dibr_injected_command = true; }
    ~ManualDibrInjectedCommandGuard() { manual_dibr_injected_command = previous; }
};

struct CandidateView {
    Candidate candidate{};
    std::string status{};
    std::shared_ptr<const PreviewPayload> preview{};
    CandidatePreviewStatus preview_status{CandidatePreviewStatus::waiting_for_live_capture};
    uint64_t age_ms{};
};

// A bounded observer for live D3D12 depth transitions. Each candidate owns a
// fixed three-slot immutable snapshot ring. Captures use a D32S8-safe plane-0
// buffer bridge, and every GPU/CPU consumer retains a slot lease until its own
// fence has completed. The hook adapter lives in the installed backend tree.
class ManualDibrCapture final {
public:
    static constexpr size_t kMaxCandidates = 32;
    static constexpr size_t kSnapshotSlots = 3;
    static constexpr size_t kPreviewReadbackSlots = 4;
    static constexpr size_t kPreviewPageSize = kManualDibrCandidatePageSize;
    static constexpr uint32_t kMaxPreviewDimension = 8192;
    static constexpr uint64_t kMaxPreviewBytes = 64ull * 1024 * 1024;

    void set_requested(bool picker_open, bool stereo_requested) noexcept {
        picker_open_.store(picker_open, std::memory_order_release);
        stereo_requested_.store(stereo_requested, std::memory_order_release);
    }

    bool requested() const noexcept {
        return picker_open_.load(std::memory_order_acquire) ||
            stereo_requested_.load(std::memory_order_acquire);
    }

    void set_preview_page(size_t first) {
        std::scoped_lock lock{mutex_};
        const auto window = candidate_page_window(candidate_count_locked(), first, kPreviewPageSize);
        preview_first_ = window.first;
    }

    size_t preview_page() const {
        std::scoped_lock lock{mutex_};
        return preview_first_;
    }

    bool candidates_complete() const {
        std::scoped_lock lock{mutex_};
        return !overflowed_;
    }

    bool overflowed() const {
        std::scoped_lock lock{mutex_};
        return overflowed_;
    }

    bool assign_periphery(CandidateKey key) { return assign(key, true); }
    bool assign_fovea(CandidateKey key) { return assign(key, false); }

    void clear_periphery() {
        std::scoped_lock lock{mutex_};
        roles_.clear_periphery();
    }

    void clear_fovea() {
        std::scoped_lock lock{mutex_};
        roles_.clear_fovea();
    }

    RoleAssignments assignments() const {
        std::scoped_lock lock{mutex_};
        return roles_;
    }

    std::vector<CandidateView> candidates() const {
        std::scoped_lock lock{mutex_};
        std::vector<CandidateView> result;
        result.reserve(candidate_count_locked());
        const auto now = GetTickCount64();
        for (const auto& entry : candidates_) {
            if (!entry.used) continue;
            CandidateView view{};
            view.candidate = entry.candidate;
            view.status = status_locked(entry);
            view.preview = entry.preview;
            view.preview_status = preview_status_locked(entry, now);
            view.age_ms = entry.preview && now >= entry.preview->completed_ms
                ? now - entry.preview->completed_ms : 0;
            result.emplace_back(std::move(view));
        }
        return result;
    }

    // DSV discovery is metadata-only. Retaining the COM resource prevents a
    // pointer reuse from aliasing a candidate generation while that candidate
    // remains registered.
    void on_depth_stencil_view_created(
        ID3D12Resource* resource,
        const D3D12_DEPTH_STENCIL_VIEW_DESC* desc,
        D3D12_CPU_DESCRIPTOR_HANDLE)
    {
        if (!requested() || !resource) return;
        const auto source = resource->GetDesc();
        if (source.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || !source.MipLevels ||
            !source.DepthOrArraySize || source.SampleDesc.Count != 1 || source.SampleDesc.Quality != 0)
            return;

        uint32_t mip = 0, first_slice = 0, slice_count = 1;
        if (desc) {
            switch (desc->ViewDimension) {
            case D3D12_DSV_DIMENSION_TEXTURE2D:
                mip = desc->Texture2D.MipSlice;
                break;
            case D3D12_DSV_DIMENSION_TEXTURE2DARRAY:
                mip = desc->Texture2DArray.MipSlice;
                first_slice = desc->Texture2DArray.FirstArraySlice;
                slice_count = desc->Texture2DArray.ArraySize;
                break;
            case D3D12_DSV_DIMENSION_TEXTURE2DMS:
            case D3D12_DSV_DIMENSION_TEXTURE2DMSARRAY:
            default:
                return;
            }
        }
        if (mip != 0 || first_slice >= source.DepthOrArraySize) return;
        slice_count = (std::min)(slice_count,
            static_cast<uint32_t>(source.DepthOrArraySize) - first_slice);

        // Plane zero is the R32 depth value of R32G8X24_TYPELESS. Plane one is
        // stencil and is intentionally never registered as a depth candidate.
        if (!depth_plane_supported(source.Format)) return;
        std::scoped_lock lock{mutex_};
        if (!requested()) return;
        for (uint32_t slice = 0; slice < slice_count; ++slice) {
            const auto subresource = calc_subresource(mip, first_slice + slice, 0,
                source.MipLevels, source.DepthOrArraySize);
            register_resource_locked(resource, subresource, source);
        }
    }

    void on_resource_barriers_scoped(
        ID3D12GraphicsCommandList* command_list,
        UINT count,
        const D3D12_RESOURCE_BARRIER* barriers,
        const CaptureSourceStamp& source_stamp,
        CommandListEpoch epoch)
    {
        // The hot path is an atomic bypass while the picker and stereo output
        // are both off. Never let a Slate or deferred callback install proof.
        if (!requested() || manual_dibr_injected_command || !command_list || !count || !barriers ||
            !epoch.known || !epoch.open || epoch.closed || epoch.render_pass ||
            command_list->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT)
            return;

        std::scoped_lock lock{mutex_};
        if (!requested() || retiring_) return;
        for (UINT i = 0; i < count; ++i) {
            const auto& barrier = barriers[i];
            if (barrier.Type != D3D12_RESOURCE_BARRIER_TYPE_TRANSITION ||
                barrier.Flags != D3D12_RESOURCE_BARRIER_FLAG_NONE ||
                !barrier.Transition.pResource ||
                barrier.Transition.StateBefore != D3D12_RESOURCE_STATE_DEPTH_WRITE ||
                !(barrier.Transition.StateAfter & (D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |
                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)))
                continue;

            const auto source_desc = barrier.Transition.pResource->GetDesc();
            if (source_desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
                !depth_plane_supported(source_desc.Format))
                continue;

            // The supported depth plane subresources are the first array/mip
            // plane. A D32S8 plane-1 subresource is stencil, never depth.
            const uint32_t depth_plane_count = static_cast<uint32_t>(source_desc.DepthOrArraySize);
            for (uint32_t array_slice = 0; array_slice < depth_plane_count; ++array_slice) {
                const uint32_t subresource = calc_subresource(0, array_slice, 0,
                    source_desc.MipLevels, source_desc.DepthOrArraySize);
                if (barrier.Transition.Subresource != D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES &&
                    barrier.Transition.Subresource != subresource)
                    continue;
                auto* entry = register_resource_locked(barrier.Transition.pResource, subresource, source_desc);
                if (!entry || !should_capture_locked(*entry, source_stamp)) continue;
                auto* slot = acquire_slot_locked(*entry, source_desc);
                if (!slot || !record_capture_locked(*entry, *slot, command_list, epoch.value,
                        barrier.Transition.StateBefore, source_stamp))
                    continue;
            }
        }
    }

    void on_command_list_reset(ID3D12GraphicsCommandList* command_list, uint64_t new_epoch) {
        if (!command_list) return;
        std::scoped_lock lock{mutex_};
        cancel_unsubmitted_locked(reinterpret_cast<uintptr_t>(command_list), new_epoch);
    }

    void on_command_list_close(ID3D12GraphicsCommandList* command_list, bool succeeded, uint64_t epoch) {
        if (!command_list || succeeded) return;
        std::scoped_lock lock{mutex_};
        cancel_unsubmitted_locked(reinterpret_cast<uintptr_t>(command_list), epoch + 1);
    }

    // Called only after ExecuteCommandLists has accepted the command batch.
    // The private signal is appended to that same queue, so the fence proves
    // both the owned depth copy and any submitted preview readback are done.
    void on_queue_execute_command_lists(
        ID3D12CommandQueue* queue,
        UINT count,
        ID3D12CommandList* const* command_lists,
        uint64_t submission_order)
    {
        if (!queue || !count || !command_lists || !submission_order) return;
        std::scoped_lock lock{mutex_};
        for (UINT i = 0; i < count; ++i) {
            auto* list = command_lists[i];
            const auto epoch = command_list_epochs.current(reinterpret_cast<uintptr_t>(list));
            if (!epoch.known || !epoch.closed) continue;
            const auto list_key = reinterpret_cast<uintptr_t>(list);
            for (auto& entry : candidates_) {
                if (!entry.used) continue;
                for (auto& slot : entry.snapshots) {
                    if (!slot.pending || slot.pending_command != list_key || slot.pending_epoch != epoch.value)
                        continue;
                    if (!signal_capture_slot_locked(slot, entry, queue, submission_order))
                        slot.orphaned = true;
                }
            }
            for (auto& readback : readbacks_) {
                if (!readback.pending || readback.pending_command != list_key ||
                    readback.pending_epoch != epoch.value)
                    continue;
                if (!signal_readback_slot_locked(readback, queue, submission_order))
                    readback.orphaned = true;
            }
        }
    }

    // Record at most one asynchronous raw-depth preview for each visible page
    // entry. The caller owns this command list and its queue; no CPU wait is
    // issued here or on the XR path.
    size_t record_preview_readbacks(
        ID3D12Device* device,
        ID3D12GraphicsCommandList* command_list,
        ID3D12CommandQueue* queue,
        uint64_t command_epoch)
    {
        if (!picker_open_.load(std::memory_order_acquire) || !device || !command_list || !queue ||
            !command_epoch || command_list->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT)
            return 0;
        std::scoped_lock lock{mutex_};
        if (retiring_ || !picker_open_.load(std::memory_order_relaxed)) return 0;
        poll_readbacks_locked();
        const auto page = candidate_page_window(candidate_count_locked(), preview_first_, kPreviewPageSize);
        size_t recorded = 0;
        ManualDibrInjectedCommandGuard injected_command_guard;
        for (size_t index = page.first; index < page.end; ++index) {
            auto* entry = candidate_at_locked(index);
            if (!entry || !entry->candidate.preview_supported || !entry->candidate.capture_supported ||
                !preview_due_locked(*entry))
                continue;
            auto* source_slot = latest_snapshot_locked(*entry);
            if (!source_slot || !source_slot->lease || !source_slot->sample.completion_recorded ||
                source_slot->sample.resource_update_serial != entry->candidate.update_serial ||
                source_slot->orphaned || !source_slot->texture)
                continue;
            if (source_slot->width > kMaxPreviewDimension || source_slot->height > kMaxPreviewDimension ||
                source_slot->byte_size > kMaxPreviewBytes)
                continue;
            auto* readback = free_readback_slot_locked();
            if (!readback) break;
            const auto consumer_queue = reinterpret_cast<uintptr_t>(queue);
            if (source_slot->lease->consumer_queue && source_slot->lease->consumer_queue != consumer_queue)
                continue;
            if (source_slot->lease->consumer_queue == 0)
                source_slot->lease->consumer_queue = consumer_queue;

            const auto producer_queue = source_slot->sample.queue.producer_queue;
            uint64_t waited_fence = 0;
            if (producer_queue != consumer_queue) {
                if (!source_slot->lease->fence || !source_slot->lease->fence_value ||
                    FAILED(queue->Wait(source_slot->lease->fence.Get(), source_slot->lease->fence_value)))
                    continue;
                waited_fence = source_slot->lease->fence_value;
            }
            if (!ensure_readback_buffer_locked(device, *readback, source_slot->byte_size)) continue;

            transition(command_list, source_slot->texture.Get(), D3D12_RESOURCE_STATE_COPY_DEST,
                D3D12_RESOURCE_STATE_COPY_SOURCE, 0);
            D3D12_TEXTURE_COPY_LOCATION from{};
            from.pResource = source_slot->texture.Get();
            from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            from.SubresourceIndex = 0;
            D3D12_TEXTURE_COPY_LOCATION to{};
            to.pResource = readback->buffer.Get();
            to.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            to.PlacedFootprint = source_slot->footprint;
            command_list->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
            transition(command_list, source_slot->texture.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE,
                D3D12_RESOURCE_STATE_COPY_DEST, 0);

            readback->pending = true;
            readback->key = entry->candidate.key;
            readback->capture_serial = source_slot->sample.capture_serial;
            readback->update_serial = source_slot->sample.resource_update_serial;
            readback->producer = source_slot->sample.producer;
            readback->producer_queue = source_slot->sample.queue.producer_queue;
            readback->producer_order = source_slot->sample.queue.producer_order;
            readback->producer_fence_value = source_slot->lease->fence_value;
            readback->consumer_wait = waited_fence;
            readback->pending_command = reinterpret_cast<uintptr_t>(command_list);
            readback->pending_epoch = command_epoch;
            readback->pending_command_ref = command_list;
            readback->source_lease = source_slot->lease;
            readback->width = source_slot->width;
            readback->height = source_slot->height;
            readback->footprint = source_slot->footprint;
            entry->last_preview_capture = std::chrono::steady_clock::now();
            ++recorded;
        }
        return recorded;
    }

    // Polling is nonblocking. Raw CPU depth is published only after the exact
    // private readback fence has completed, with its queue proof retained.
    void poll_completed_previews() {
        std::scoped_lock lock{mutex_};
        poll_readbacks_locked();
        collect_retired_locked();
    }

    std::optional<OwnedDepthTexture> selected_periphery(
        ProducerKey consumer,
        ID3D12CommandQueue* queue,
        uint64_t consumer_order) const
    {
        return selected(consumer, queue, consumer_order, true);
    }

    std::optional<OwnedDepthTexture> selected_fovea(
        ProducerKey consumer,
        ID3D12CommandQueue* queue,
        uint64_t consumer_order) const
    {
        return selected(consumer, queue, consumer_order, false);
    }

    // A reset disables capture immediately but retains every submitted GPU
    // lease until its fence completes. Candidate/resource IDs remain monotonic
    // so old UI selections can never alias a later resource.
    void reset() {
        set_requested(false, false);
        std::scoped_lock lock{mutex_};
        roles_ = {};
        preview_first_ = 0;
        retiring_ = true;
        collect_retired_locked();
    }

    void resume() {
        std::scoped_lock lock{mutex_};
        retiring_ = false;
    }

private:
    struct SnapshotLease {
        ComPtr<ID3D12Resource> texture{};
        ComPtr<ID3D12Fence> fence{};
        ComPtr<ID3D12CommandQueue> producer_queue{};
        uint64_t fence_value{};
        uint64_t producer_order{};
        uintptr_t consumer_queue{}; // accessed only under ManualDibrCapture::mutex_
    };

    struct SnapshotSlot {
        ComPtr<ID3D12Resource> texture{};
        ComPtr<ID3D12Resource> depth_staging{};
        ComPtr<ID3D12Fence> fence{};
        ComPtr<ID3D12CommandList> pending_command_ref{};
        std::shared_ptr<SnapshotLease> lease{};
        OwnedDepthSample sample{};
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
        uint64_t byte_size{};
        uint64_t next_fence_value{};
        uint64_t pending_fence_value{};
        uint64_t pending_capture_serial{};
        uint64_t pending_update_serial{};
        uint64_t pending_epoch{};
        uintptr_t pending_command{};
        ProducerKey pending_source{};
        uint32_t width{}, height{};
        D3D12_RESOURCE_STATES staging_state{D3D12_RESOURCE_STATE_COPY_DEST};
        D3D12_RESOURCE_STATES pending_previous_staging_state{D3D12_RESOURCE_STATE_COPY_DEST};
        bool pending{}, orphaned{};
    };

    struct ReadbackSlot {
        ComPtr<ID3D12Resource> buffer{};
        ComPtr<ID3D12Fence> fence{};
        ComPtr<ID3D12CommandList> pending_command_ref{};
        std::shared_ptr<SnapshotLease> source_lease{};
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
        uint64_t buffer_size{};
        uint64_t next_fence_value{};
        uint64_t fence_value{};
        uint64_t capture_serial{}, update_serial{};
        uint64_t producer_fence_value{}, producer_order{}, submitted_order{}, consumer_wait{};
        uintptr_t producer_queue{}, consumer_queue{}, pending_command{};
        uint64_t pending_epoch{};
        CandidateKey key{};
        ProducerKey producer{};
        QueueProof queue_proof{};
        uint32_t width{}, height{};
        bool pending{}, submitted{}, orphaned{};
    };

    struct Entry {
        bool used{};
        Candidate candidate{};
        ComPtr<ID3D12Resource> source{};
        std::array<SnapshotSlot, kSnapshotSlots> snapshots{};
        std::shared_ptr<const PreviewPayload> preview{};
        std::chrono::steady_clock::time_point last_preview_capture{};
        std::chrono::steady_clock::time_point last_unstamped_capture{};
        uint64_t last_captured_frame{};
        uint64_t last_seen{};
    };

    static bool depth_plane_supported(DXGI_FORMAT format) {
        return format == DXGI_FORMAT_R32_TYPELESS || format == DXGI_FORMAT_R32_FLOAT ||
            format == DXGI_FORMAT_R32G8X24_TYPELESS;
    }

    static constexpr uint32_t calc_subresource(uint32_t mip, uint32_t array_slice,
        uint32_t plane, uint32_t mip_levels, uint32_t array_size) {
        return mip + array_slice * mip_levels + plane * mip_levels * array_size;
    }

    static bool supported_resource_shape(const D3D12_RESOURCE_DESC& desc, uint32_t subresource) {
        const uint64_t plane_zero_count = desc.DepthOrArraySize;
        return desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && desc.Width > 0 && desc.Height > 0 &&
            desc.Width <= UINT32_MAX && desc.Height <= UINT32_MAX && desc.MipLevels > 0 &&
            desc.SampleDesc.Count == 1 && desc.SampleDesc.Quality == 0 &&
            subresource < plane_zero_count;
    }

    size_t candidate_count_locked() const {
        size_t count = 0;
        for (const auto& entry : candidates_) if (entry.used) ++count;
        return count;
    }

    Entry* candidate_at_locked(size_t visible_index) {
        size_t current = 0;
        for (auto& entry : candidates_) if (entry.used) {
            if (current++ == visible_index) return &entry;
        }
        return nullptr;
    }

    const Entry* find_locked(CandidateKey key) const {
        for (const auto& entry : candidates_)
            if (entry.used && entry.candidate.key == key) return &entry;
        return nullptr;
    }

    Entry* find_locked(CandidateKey key) {
        for (auto& entry : candidates_)
            if (entry.used && entry.candidate.key == key) return &entry;
        return nullptr;
    }

    Entry* find_resource_locked(ID3D12Resource* resource, uint32_t subresource) {
        for (auto& entry : candidates_)
            if (entry.used && entry.source.Get() == resource && entry.candidate.key.subresource == subresource)
                return &entry;
        return nullptr;
    }

    bool slot_reusable_locked(const SnapshotSlot& slot) const {
        if (slot.pending || slot.orphaned || (slot.lease && slot.lease.use_count() > 1)) return false;
        if (slot.pending_fence_value && slot.fence && slot.fence->GetCompletedValue() < slot.pending_fence_value)
            return false;
        return true;
    }

    bool entry_evictable_locked(const Entry& entry) const {
        if (!entry.used || (roles_.periphery && *roles_.periphery == entry.candidate.key) ||
            (roles_.fovea && *roles_.fovea == entry.candidate.key))
            return false;
        for (const auto& slot : entry.snapshots) if (!slot_reusable_locked(slot)) return false;
        for (const auto& readback : readbacks_)
            if (readback.pending && readback.key == entry.candidate.key) return false;
        return true;
    }

    Entry* allocate_entry_locked() {
        for (auto& entry : candidates_) if (!entry.used) return &entry;
        Entry* oldest = nullptr;
        for (auto& entry : candidates_) if (entry_evictable_locked(entry) &&
            (!oldest || entry.last_seen < oldest->last_seen)) oldest = &entry;
        if (!oldest) {
            overflowed_ = true;
            return nullptr;
        }
        if (roles_.periphery && *roles_.periphery == oldest->candidate.key) roles_.clear_periphery();
        if (roles_.fovea && *roles_.fovea == oldest->candidate.key) roles_.clear_fovea();
        *oldest = {};
        return oldest;
    }

    Entry* register_resource_locked(ID3D12Resource* resource, uint32_t subresource,
        const D3D12_RESOURCE_DESC& desc)
    {
        if (auto* existing = find_resource_locked(resource, subresource)) {
            existing->last_seen = ++clock_;
            return existing;
        }
        auto* entry = allocate_entry_locked();
        if (!entry) return nullptr;
        const bool shape = supported_resource_shape(desc, subresource);
        ComPtr<ID3D12Resource> retained{resource};
        const auto resource_generation = next_resource_generation_++;
        const CandidateKey key{next_id_++, resource_generation, subresource};
        entry->used = true;
        entry->source = std::move(retained);
        entry->candidate = {key, static_cast<uint32_t>(desc.Width), desc.Height,
            {0, 0, static_cast<uint32_t>(desc.Width), desc.Height},
            static_cast<uint32_t>(desc.Format), CaptureStage::depth_write_to_shader_read,
            depth_plane_supported(desc.Format) && shape,
            depth_plane_supported(desc.Format) && shape, 0, 0};
        entry->last_seen = ++clock_;
        if (preview_first_ && preview_first_ >= candidate_count_locked()) {
            const auto page = candidate_page_window(candidate_count_locked(), preview_first_, kPreviewPageSize);
            preview_first_ = page.first;
        }
        return entry;
    }

    void register_resource(ID3D12Resource* resource, uint32_t subresource,
        const D3D12_RESOURCE_DESC& desc)
    {
        if (!resource || !requested()) return;
        std::scoped_lock lock{mutex_};
        if (!retiring_) register_resource_locked(resource, subresource, desc);
    }

    bool assign(CandidateKey key, bool full_view) {
        std::scoped_lock lock{mutex_};
        const auto* entry = find_locked(key);
        if (!entry || !entry->candidate.capture_supported) return false;
        if (full_view) roles_.assign_periphery(key);
        else roles_.assign_fovea(key);
        return true;
    }

    bool should_capture_locked(const Entry& entry, const CaptureSourceStamp& stamp) const {
        const bool selected = (roles_.periphery && *roles_.periphery == entry.candidate.key) ||
            (roles_.fovea && *roles_.fovea == entry.candidate.key);
        const auto page = candidate_page_window(candidate_count_locked(), preview_first_, kPreviewPageSize);
        size_t index = 0;
        for (const auto& candidate : candidates_) if (candidate.used) {
            if (&candidate == &entry) break;
            ++index;
        }
        const bool visible = picker_open_.load(std::memory_order_relaxed) &&
            index >= page.first && index < page.end;
        if (!selected && !visible) return false;
        if (!stamp.valid()) {
            if (!visible) return false;
            const auto now = std::chrono::steady_clock::now();
            return entry.last_unstamped_capture.time_since_epoch().count() == 0 ||
                now - entry.last_unstamped_capture >= std::chrono::milliseconds(250);
        }
        const ProducerKey producer{stamp.generation, stamp.frame};
        for (const auto& slot : entry.snapshots)
            if (slot.pending && slot.pending_source == producer) return false;
        return stamp.frame != entry.last_captured_frame;
    }

    bool ensure_snapshot_storage_locked(ID3D12Resource* source, SnapshotSlot& slot,
        const D3D12_RESOURCE_DESC& source_desc)
    {
        const auto width = static_cast<uint32_t>(source_desc.Width);
        const auto height = source_desc.Height;
        if (slot.texture && slot.depth_staging && slot.width == width && slot.height == height && slot.fence)
            return true;
        if (!slot_reusable_locked(slot)) return false;
        ComPtr<ID3D12Device> device;
        if (FAILED(source->GetDevice(IID_PPV_ARGS(&device)))) return false;

        D3D12_RESOURCE_DESC texture_desc{};
        texture_desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        texture_desc.Width = source_desc.Width;
        texture_desc.Height = source_desc.Height;
        texture_desc.DepthOrArraySize = 1;
        texture_desc.MipLevels = 1;
        texture_desc.Format = DXGI_FORMAT_R32_TYPELESS;
        texture_desc.SampleDesc.Count = 1;
        texture_desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;

        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
        UINT rows = 0;
        UINT64 row_size = 0, total_bytes = 0;
        device->GetCopyableFootprints(&texture_desc, 0, 1, 0, &footprint, &rows, &row_size, &total_bytes);
        if (!total_bytes || !rows || !row_size) return false;

        D3D12_RESOURCE_DESC buffer_desc{};
        buffer_desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer_desc.Width = total_bytes;
        buffer_desc.Height = 1;
        buffer_desc.DepthOrArraySize = 1;
        buffer_desc.MipLevels = 1;
        buffer_desc.SampleDesc.Count = 1;
        buffer_desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;

        D3D12_HEAP_PROPERTIES default_heap{};
        default_heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        default_heap.CreationNodeMask = default_heap.VisibleNodeMask = 1;
        ComPtr<ID3D12Resource> owned_texture, staging_buffer;
        if (FAILED(device->CreateCommittedResource(&default_heap, D3D12_HEAP_FLAG_NONE, &texture_desc,
                D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&owned_texture))) ||
            FAILED(device->CreateCommittedResource(&default_heap, D3D12_HEAP_FLAG_NONE, &buffer_desc,
                D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&staging_buffer))))
            return false;
        owned_texture->SetName(L"DuoView DIBR Immutable Owned R32 Depth Snapshot");
        staging_buffer->SetName(L"DuoView DIBR Plane 0 Staging Buffer");

        ComPtr<ID3D12Fence> fence;
        if (FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence))) || !fence)
            return false;
        slot.texture = std::move(owned_texture);
        slot.depth_staging = std::move(staging_buffer);
        slot.fence = std::move(fence);
        slot.footprint = footprint;
        slot.byte_size = total_bytes;
        slot.width = width;
        slot.height = height;
        slot.staging_state = D3D12_RESOURCE_STATE_COPY_DEST;
        slot.sample = {};
        slot.lease.reset();
        slot.pending_fence_value = 0;
        slot.orphaned = false;
        return true;
    }

    SnapshotSlot* acquire_slot_locked(Entry& entry, const D3D12_RESOURCE_DESC& source_desc) {
        for (auto& slot : entry.snapshots) {
            if (!slot_reusable_locked(slot)) continue;
            if (!ensure_snapshot_storage_locked(entry.source.Get(), slot, source_desc)) continue;
            return &slot;
        }
        return nullptr;
    }

    bool record_capture_locked(Entry& entry, SnapshotSlot& slot,
        ID3D12GraphicsCommandList* command_list, uint64_t command_epoch,
        D3D12_RESOURCE_STATES source_state, const CaptureSourceStamp& source_stamp)
    {
        if (slot.pending || slot.orphaned || !entry.source || !slot.texture || !slot.depth_staging ||
            !slot.fence || !command_epoch)
            return false;
        const auto subresource = entry.candidate.key.subresource;
        slot.pending_previous_staging_state = slot.staging_state;

        if (slot.staging_state != D3D12_RESOURCE_STATE_COPY_DEST) {
            transition(command_list, slot.depth_staging.Get(), slot.staging_state,
                D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES);
            slot.staging_state = D3D12_RESOURCE_STATE_COPY_DEST;
        }
        transition(command_list, entry.source.Get(), source_state,
            D3D12_RESOURCE_STATE_COPY_SOURCE, subresource);

        D3D12_TEXTURE_COPY_LOCATION source_location{};
        source_location.pResource = entry.source.Get();
        source_location.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        source_location.SubresourceIndex = subresource;
        D3D12_TEXTURE_COPY_LOCATION staging_location{};
        staging_location.pResource = slot.depth_staging.Get();
        staging_location.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        staging_location.PlacedFootprint = slot.footprint;
        command_list->CopyTextureRegion(&staging_location, 0, 0, 0, &source_location, nullptr);

        transition(command_list, entry.source.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE,
            source_state, subresource);
        transition(command_list, slot.depth_staging.Get(), D3D12_RESOURCE_STATE_COPY_DEST,
            D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES);
        slot.staging_state = D3D12_RESOURCE_STATE_COPY_SOURCE;

        D3D12_TEXTURE_COPY_LOCATION owned_location{};
        owned_location.pResource = slot.texture.Get();
        owned_location.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        owned_location.SubresourceIndex = 0;
        command_list->CopyTextureRegion(&owned_location, 0, 0, 0, &staging_location, nullptr);

        entry.candidate.stage = CaptureStage::depth_write_to_shader_read;

        slot.sample = {};
        slot.pending_command_ref = command_list;
        slot.pending = true;
        slot.pending_epoch = command_epoch;
        slot.pending_command = reinterpret_cast<uintptr_t>(command_list);
        slot.pending_capture_serial = next_capture_serial_++;
        slot.pending_update_serial = entry.candidate.update_serial + 1;
        if (!slot.pending_update_serial) ++slot.pending_update_serial;
        slot.pending_source = source_stamp.valid()
            ? ProducerKey{source_stamp.generation, source_stamp.frame} : ProducerKey{};
        if (!source_stamp.valid()) entry.last_unstamped_capture = std::chrono::steady_clock::now();
        return true;
    }

    bool signal_capture_slot_locked(SnapshotSlot& slot, Entry& entry,
        ID3D12CommandQueue* queue, uint64_t submission_order)
    {
        if (!slot.pending || !slot.fence || !queue) return false;
        const auto value = ++slot.next_fence_value;
        if (!value || FAILED(queue->Signal(slot.fence.Get(), value))) return false;
        slot.pending_fence_value = value;
        slot.sample.key = entry.candidate.key;
        slot.sample.producer = slot.pending_source;
        slot.sample.stage = entry.candidate.stage;
        slot.sample.capture_serial = slot.pending_capture_serial;
        slot.sample.resource_update_serial = slot.pending_update_serial;
        slot.sample.copy = {entry.candidate.key, entry.candidate.key.subresource, 0,
            slot.pending_capture_serial};
        slot.sample.active_rect = entry.candidate.active_rect;
        slot.sample.owned_snapshot = true;
        slot.sample.completion_recorded = true;
        slot.sample.queue = {QueueRelation::unknown,
            reinterpret_cast<uintptr_t>(queue), 0, submission_order, 0, value, 0};
        entry.candidate.update_serial = slot.pending_update_serial;
        entry.candidate.last_update_ms = GetTickCount64();
        entry.last_seen = ++clock_;
        if (slot.pending_source.frame) entry.last_captured_frame = slot.pending_source.frame;
        slot.lease = std::make_shared<SnapshotLease>();
        slot.lease->texture = slot.texture;
        slot.lease->fence = slot.fence;
        slot.lease->producer_queue = queue;
        slot.lease->fence_value = value;
        slot.lease->producer_order = submission_order;
        slot.pending = false;
        slot.pending_command_ref.Reset();
        slot.pending_command = 0;
        slot.pending_epoch = 0;
        slot.pending_source = {};
        slot.pending_capture_serial = 0;
        slot.pending_update_serial = 0;
        return true;
    }

    bool signal_readback_slot_locked(ReadbackSlot& readback, ID3D12CommandQueue* queue,
        uint64_t submission_order)
    {
        if (!readback.pending || !readback.fence || !queue) return false;
        const auto value = ++readback.next_fence_value;
        if (!value || FAILED(queue->Signal(readback.fence.Get(), value))) return false;
        readback.fence_value = value;
        readback.submitted_order = submission_order;
        readback.consumer_queue = reinterpret_cast<uintptr_t>(queue);
        readback.queue_proof = {readback.producer_queue == readback.consumer_queue
                ? QueueRelation::same_queue : QueueRelation::cross_queue,
            readback.producer_queue, readback.consumer_queue,
            readback.producer_order, submission_order,
            readback.producer_fence_value,
            readback.producer_queue == readback.consumer_queue ? 0 : readback.consumer_wait};
        readback.submitted = true;
        readback.pending = false;
        readback.pending_command_ref.Reset();
        readback.pending_command = 0;
        readback.pending_epoch = 0;
        return true;
    }

    void cancel_unsubmitted_locked(uintptr_t command, uint64_t new_epoch) {
        for (auto& entry : candidates_) if (entry.used)
            for (auto& slot : entry.snapshots) {
                if (slot.pending && slot.pending_command == command && slot.pending_epoch < new_epoch) {
                    slot.pending = false;
                    slot.pending_command_ref.Reset();
                    slot.pending_command = 0;
                    slot.pending_epoch = 0;
                    slot.pending_source = {};
                    slot.pending_capture_serial = 0;
                    slot.pending_update_serial = 0;
                    slot.sample = {};
                    slot.staging_state = slot.pending_previous_staging_state;
                    slot.pending_previous_staging_state = D3D12_RESOURCE_STATE_COPY_DEST;
                }
            }
        for (auto& readback : readbacks_) {
            if (readback.pending && readback.pending_command == command && readback.pending_epoch < new_epoch) {
                readback.pending = false;
                readback.pending_command_ref.Reset();
                readback.pending_command = 0;
                readback.pending_epoch = 0;
                readback.source_lease.reset();
                readback.key = {};
            }
        }
    }

    SnapshotSlot* latest_snapshot_locked(Entry& entry) {
        SnapshotSlot* latest = nullptr;
        for (auto& slot : entry.snapshots)
            if (slot.sample.capture_serial && (!latest ||
                slot.sample.resource_update_serial > latest->sample.resource_update_serial)) latest = &slot;
        return latest;
    }

    const SnapshotSlot* latest_snapshot_locked(const Entry& entry) const {
        const SnapshotSlot* latest = nullptr;
        for (const auto& slot : entry.snapshots)
            if (slot.sample.capture_serial && (!latest ||
                slot.sample.resource_update_serial > latest->sample.resource_update_serial)) latest = &slot;
        return latest;
    }

    bool preview_due_locked(const Entry& entry) const {
        const auto* latest = latest_snapshot_locked(entry);
        if (!latest || !latest->sample.capture_serial) return false;
        if (entry.preview && entry.preview->capture_serial == latest->sample.capture_serial) return false;
        const auto now = std::chrono::steady_clock::now();
        return entry.last_preview_capture.time_since_epoch().count() == 0 ||
            now - entry.last_preview_capture >= std::chrono::milliseconds(250);
    }

    ReadbackSlot* free_readback_slot_locked() {
        for (auto& slot : readbacks_) {
            if (slot.pending || slot.submitted || slot.orphaned) continue;
            return &slot;
        }
        return nullptr;
    }

    bool ensure_readback_buffer_locked(ID3D12Device* device, ReadbackSlot& slot, uint64_t size) {
        if (!device || !size) return false;
        if (slot.buffer && slot.buffer_size == size && slot.fence) return true;
        if (slot.submitted || slot.pending) return false;
        D3D12_RESOURCE_DESC desc{};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = size;
        desc.Height = 1;
        desc.DepthOrArraySize = 1;
        desc.MipLevels = 1;
        desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type = D3D12_HEAP_TYPE_READBACK;
        heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        ComPtr<ID3D12Resource> buffer;
        if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
                D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&buffer)))) return false;
        buffer->SetName(L"DuoView Manual DIBR Fenced Raw Depth Readback");
        ComPtr<ID3D12Fence> fence;
        if (FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)))) return false;
        slot.buffer = std::move(buffer);
        slot.fence = std::move(fence);
        slot.buffer_size = size;
        return true;
    }

    void poll_readbacks_locked() {
        const auto now = GetTickCount64();
        for (auto& readback : readbacks_) {
            if (!readback.submitted || !readback.fence ||
                readback.fence->GetCompletedValue() < readback.fence_value || !readback.buffer)
                continue;
            const auto* entry = find_locked(readback.key);
            if (entry) {
                D3D12_RANGE read_range{0, static_cast<SIZE_T>(readback.buffer_size)};
                void* mapped = nullptr;
                if (SUCCEEDED(readback.buffer->Map(0, &read_range, &mapped)) && mapped) {
                    auto payload = std::make_shared<PreviewPayload>();
                    payload->key = readback.key;
                    payload->capture_serial = readback.capture_serial;
                    payload->producer_generation = readback.producer.generation;
                    payload->producer_frame = readback.producer.frame;
                    payload->submitted_order = readback.submitted_order;
                    payload->completed_ms = now;
                    payload->queue = readback.queue_proof;
                    payload->private_readback_fence_value = readback.fence_value;
                    payload->completed_private_readback_fence_value = readback.fence->GetCompletedValue();
                    payload->association = readback.producer.generation && readback.producer.frame
                        ? PreviewAssociation::producer_frame_matched
                        : PreviewAssociation::timing_unverified;
                    payload->width = kPreviewWidth;
                    payload->height = kPreviewHeight;
                    const auto* bytes = static_cast<const uint8_t*>(mapped);
                    for (uint32_t y = 0; y < kPreviewHeight; ++y) {
                        const uint32_t sy = (std::min)(readback.height - 1,
                            static_cast<uint32_t>((uint64_t{y} * readback.height) / kPreviewHeight));
                        for (uint32_t x = 0; x < kPreviewWidth; ++x) {
                            const uint32_t sx = (std::min)(readback.width - 1,
                                static_cast<uint32_t>((uint64_t{x} * readback.width) / kPreviewWidth));
                            float raw_depth = 0.f;
                            const auto offset = readback.footprint.Offset +
                                uint64_t{sy} * readback.footprint.Footprint.RowPitch + uint64_t{sx} * sizeof(float);
                            if (offset + sizeof(float) <= readback.buffer_size)
                                std::memcpy(&raw_depth, bytes + offset, sizeof(raw_depth));
                            payload->raw_depth[size_t{y} * kPreviewWidth + x] = raw_depth;
                        }
                    }
                    D3D12_RANGE written_range{0, 0};
                    readback.buffer->Unmap(0, &written_range);
                    if (valid_preview_payload(*payload, readback.key)) {
                        auto* mutable_entry = find_locked(readback.key);
                        if (mutable_entry && (!mutable_entry->preview ||
                            mutable_entry->preview->capture_serial <= payload->capture_serial))
                            mutable_entry->preview = std::move(payload);
                    }
                }
            }
            readback.submitted = false;
            readback.source_lease.reset();
            readback.key = {};
            readback.producer = {};
            readback.capture_serial = readback.update_serial = 0;
            readback.producer_queue = readback.consumer_queue = 0;
            readback.producer_fence_value = readback.producer_order = readback.submitted_order = 0;
            readback.consumer_wait = 0;
            readback.queue_proof = {};
        }
    }

    void collect_retired_locked() {
        if (!retiring_) return;
        for (const auto& entry : candidates_) if (entry.used && !entry_evictable_locked(entry)) return;
        for (const auto& readback : readbacks_) if (readback.pending || readback.submitted || readback.orphaned) return;
        candidates_ = {};
        preview_first_ = 0;
        overflowed_ = false;
        retiring_ = false;
    }

    std::string status_locked(const Entry& entry) const {
        if (!entry.candidate.preview_supported) return "Preview unavailable: unsupported depth format";
        if (!entry.candidate.capture_supported) return "Capture unavailable: unsupported shape or subresource";
        const auto* slot = latest_snapshot_locked(entry);
        if (!slot) return "Waiting for a live depth transition";
        if (slot->pending) return "Owned copy recorded; waiting for actual queue submission";
        if (!slot->sample.completion_recorded || !slot->lease) return "Waiting for an owned snapshot fence";
        if (!slot->sample.producer.generation || !slot->sample.producer.frame)
            return "Selected; timing unverified";
        return "Owned depth snapshot for producer frame " + std::to_string(slot->sample.producer.frame);
    }

    CandidatePreviewStatus preview_status_locked(const Entry& entry, uint64_t now) const {
        if (!entry.candidate.preview_supported) return CandidatePreviewStatus::unsupported;
        if (!entry.preview) {
            for (const auto& readback : readbacks_)
                if ((readback.pending || readback.submitted) && readback.key == entry.candidate.key)
                    return CandidatePreviewStatus::readback_pending;
            return CandidatePreviewStatus::waiting_for_live_capture;
        }
        const auto age = now >= entry.preview->completed_ms ? now - entry.preview->completed_ms : UINT64_MAX;
        const auto* latest = latest_snapshot_locked(entry);
        if (age > 1000 || (latest && latest->sample.capture_serial != entry.preview->capture_serial))
            return CandidatePreviewStatus::stale;
        return CandidatePreviewStatus::live;
    }

    std::optional<OwnedDepthTexture> selected(ProducerKey consumer,
        ID3D12CommandQueue* queue, uint64_t consumer_order, bool full_view) const
    {
        if (!stereo_requested_.load(std::memory_order_acquire) || !queue || !consumer.generation ||
            !consumer.frame || !consumer_order)
            return {};
        std::scoped_lock lock{mutex_};
        const auto& role = full_view ? roles_.periphery : roles_.fovea;
        if (!role) return {};
        auto* entry = const_cast<Entry*>(find_locked(*role));
        if (!entry || !entry->candidate.capture_supported ||
            entry->candidate.update_serial == 0)
            return {};
        SnapshotSlot* slot = nullptr;
        for (auto& candidate_slot : entry->snapshots) {
            if (candidate_slot.sample.resource_update_serial == entry->candidate.update_serial &&
                candidate_slot.sample.capture_serial && candidate_slot.sample.producer == consumer &&
                candidate_slot.sample.completion_recorded && candidate_slot.lease &&
                !candidate_slot.orphaned) {
                slot = &candidate_slot;
                break;
            }
        }
        if (!slot) return {};
        const auto consumer_id = reinterpret_cast<uintptr_t>(queue);
        if (slot->lease->consumer_queue && slot->lease->consumer_queue != consumer_id) return {};
        const auto producer_id = slot->sample.queue.producer_queue;
        if (producer_id == consumer_id) {
            if (slot->sample.queue.producer_order >= consumer_order) return {};
            slot->sample.queue.relation = QueueRelation::same_queue;
            slot->sample.queue.consumer_queue = consumer_id;
            slot->sample.queue.consumer_order = consumer_order;
            slot->sample.queue.consumer_wait = 0;
        } else {
            if (!slot->lease->fence || !slot->lease->fence_value ||
                FAILED(queue->Wait(slot->lease->fence.Get(), slot->lease->fence_value)))
                return {};
            slot->sample.queue.relation = QueueRelation::cross_queue;
            slot->sample.queue.consumer_queue = consumer_id;
            slot->sample.queue.consumer_order = consumer_order;
            slot->sample.queue.consumer_wait = slot->lease->fence_value;
        }
        slot->lease->consumer_queue = consumer_id;
        return OwnedDepthTexture{entry->candidate, slot->sample, slot->texture,
            entry->candidate.update_serial, slot->lease->fence, slot->lease->fence_value,
            std::static_pointer_cast<const void>(slot->lease),
            static_cast<uint32_t>(DXGI_FORMAT_R32_TYPELESS)};
    }

    static void transition(ID3D12GraphicsCommandList* command_list, ID3D12Resource* resource,
        D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after, UINT subresource) {
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition = {resource, subresource, before, after};
        command_list->ResourceBarrier(1, &barrier);
    }

    mutable std::mutex mutex_{};
    std::array<Entry, kMaxCandidates> candidates_{};
    std::array<ReadbackSlot, kPreviewReadbackSlots> readbacks_{};
    RoleAssignments roles_{};
    std::atomic<bool> picker_open_{false};
    std::atomic<bool> stereo_requested_{false};
    size_t preview_first_{};
    bool overflowed_{}, retiring_{};
    uint64_t next_id_{1}, next_resource_generation_{1}, next_capture_serial_{1}, clock_{};
};

} // namespace uevr::duoview::dibr::dx12

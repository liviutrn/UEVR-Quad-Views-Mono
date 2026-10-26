#include <spdlog/spdlog.h>
#include <utility/String.hpp>
#include <atomic>
#include <chrono>
#include <string_view>

#include "Framework.hpp"
#include "render/D3D12Diagnostics.hpp"

#include "TextureContext.hpp"
#include "CommandContext.hpp"
#include "utility/GpuRetirement.hpp"

namespace {
constexpr auto FENCE_PROFILER_LOG_INTERVAL = std::chrono::seconds(5);
std::atomic_bool g_fence_profiler_enabled{false};

bool checked_submission_device_removed(ID3D12Fence* fence) {
    if (fence == nullptr || fence->GetCompletedValue() == UINT64_MAX) {
        return fence != nullptr;
    }

    Microsoft::WRL::ComPtr<ID3D12Device> device{};
    if (FAILED(fence->GetDevice(IID_PPV_ARGS(&device))) || device == nullptr) {
        return false;
    }
    return FAILED(device->GetDeviceRemovedReason());
}

struct FenceTimingStats {
    uint64_t count{};
    double total_ms{};
    double max_ms{};

    void add(std::chrono::steady_clock::duration duration) {
        const auto ms = std::chrono::duration<double, std::milli>{duration}.count();
        ++count;
        total_ms += ms;
        if (ms > max_ms) {
            max_ms = ms;
        }
    }

    double avg() const {
        return count == 0 ? 0.0 : total_ms / (double)count;
    }

    void reset() {
        count = 0;
        total_ms = 0.0;
        max_ms = 0.0;
    }
};

struct FenceProfilerState {
    std::mutex mtx{};
    std::chrono::steady_clock::time_point last_log{};
    FenceTimingStats wait{};
    FenceTimingStats execute_signal{};
    uint64_t wait_zero_timeout{};
    uint64_t wait_nonzero_timeout{};
    uint64_t wait_infinite{};
    uint64_t long_wait{};
    uint64_t pending_after_execute{};

    void reset() {
        wait.reset();
        execute_signal.reset();
        wait_zero_timeout = 0;
        wait_nonzero_timeout = 0;
        wait_infinite = 0;
        long_wait = 0;
        pending_after_execute = 0;
    }
};

FenceProfilerState& fence_profiler() {
    static FenceProfilerState state{};
    return state;
}

void maybe_log_fence_profiler_locked(FenceProfilerState& state, std::chrono::steady_clock::time_point now) {
    if (state.last_log.time_since_epoch().count() == 0) {
        state.last_log = now;
        return;
    }

    if (now - state.last_log < FENCE_PROFILER_LOG_INTERVAL) {
        return;
    }

    if (state.wait.count == 0 && state.execute_signal.count == 0) {
        state.last_log = now;
        return;
    }

    spdlog::info(
        "[D3D12][fence-profiler] wait avg={:.2f}ms max={:.2f}ms n={} execute_signal avg={:.2f}ms max={:.2f}ms n={} wait_zero_timeout={} wait_nonzero_timeout={} wait_infinite={} long_waits={} pending_after_execute={}",
        state.wait.avg(),
        state.wait.max_ms,
        state.wait.count,
        state.execute_signal.avg(),
        state.execute_signal.max_ms,
        state.execute_signal.count,
        state.wait_zero_timeout,
        state.wait_nonzero_timeout,
        state.wait_infinite,
        state.long_wait,
        state.pending_after_execute
    );

    state.last_log = now;
    state.reset();
}

void record_fence_wait(
    std::chrono::steady_clock::duration duration,
    uint32_t requested_ms,
    DWORD wait_result,
    UINT64 fence_value,
    UINT64 completed_before,
    UINT64 completed_after,
    std::wstring_view name)
{
    const auto now = std::chrono::steady_clock::now();
    const auto duration_ms = std::chrono::duration<double, std::milli>{duration}.count();

    auto& state = fence_profiler();
    std::scoped_lock _{state.mtx};

    state.wait.add(duration);

    if (requested_ms == INFINITE) {
        ++state.wait_infinite;
    }

    if (wait_result == WAIT_TIMEOUT) {
        if (requested_ms == 0) {
            ++state.wait_zero_timeout;
        } else {
            ++state.wait_nonzero_timeout;
        }
    }

    if (duration_ms >= 10.0) {
        ++state.long_wait;
        const auto context_name = utility::narrow(std::wstring{name.begin(), name.end()});
        spdlog::warn(
            "[D3D12][fence-profiler] WaitForSingleObject took {:.2f}ms context={} requested_ms={} result={} fence={} completed_before={} completed_after={}",
            duration_ms,
            context_name,
            requested_ms,
            wait_result,
            fence_value,
            completed_before,
            completed_after
        );
    }

    maybe_log_fence_profiler_locked(state, now);
}

void record_fence_execute_signal(
    std::chrono::steady_clock::duration duration,
    UINT64 fence_value,
    UINT64 completed_after_signal,
    std::wstring_view name)
{
    const auto now = std::chrono::steady_clock::now();
    const auto duration_ms = std::chrono::duration<double, std::milli>{duration}.count();

    auto& state = fence_profiler();
    std::scoped_lock _{state.mtx};

    state.execute_signal.add(duration);

    if (completed_after_signal < fence_value) {
        ++state.pending_after_execute;
    }

    if (duration_ms >= 10.0) {
        const auto context_name = utility::narrow(std::wstring{name.begin(), name.end()});
        spdlog::warn(
            "[D3D12][fence-profiler] ExecuteCommandLists/Signal took {:.2f}ms context={} fence={} completed_after_signal={}",
            duration_ms,
            context_name,
            fence_value,
            completed_after_signal
        );
    }

    maybe_log_fence_profiler_locked(state, now);
}

void record_barriers(std::string_view source, UINT count, const D3D12_RESOURCE_BARRIER* barriers) {
    render::D3D12Diagnostics::get().record_resource_barriers(source, count, barriers);
}
}

namespace d3d12 {
void set_fence_profiler_enabled(bool enabled) {
    if (g_fence_profiler_enabled.load(std::memory_order_relaxed) == enabled) {
        return;
    }

    if (g_fence_profiler_enabled.exchange(enabled, std::memory_order_relaxed) == enabled) {
        return;
    }

    auto& state = fence_profiler();
    std::scoped_lock _{state.mtx};
    state.last_log = {};
    state.reset();
}

bool is_fence_profiler_enabled() {
    return g_fence_profiler_enabled.load(std::memory_order_relaxed);
}

bool CommandContext::setup(const wchar_t* name) {
    std::scoped_lock _{this->mtx};

    if (this->untracked_submission && !this->wait(2000)) {
        spdlog::error("[VR] Refusing to rebuild command context {} while DIBR work is untracked", utility::narrow(name));
        return false;
    }

    if (this->waiting_for_fence && !this->wait(2000)) {
        spdlog::error("[VR] Refusing to rebuild command context {} while GPU work is still pending", utility::narrow(name));
        return false;
    }

    this->internal_name = name;

    auto& hook = g_framework->get_d3d12_hook();
    auto device = hook->get_device();

    this->cmd_allocator.Reset();
    this->cmd_list.Reset();
    this->fence.Reset();
    this->submission_queue.Reset();
    if (this->fence_event != nullptr) {
        CloseHandle(this->fence_event);
        this->fence_event = nullptr;
    }
    this->fence_value = 0;
    this->waiting_for_fence = false;
    this->has_commands = false;
    this->poisoned = false;
    this->untracked_submission = false;
    this->fence_event_armed = false;
    this->device_removed_after_untracked = false;
    this->close_failure_count = 0;

    if (FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&this->cmd_allocator)))) {
        spdlog::error("[VR] Failed to create command allocator for {}", utility::narrow(name));
        return false;
    }

    this->cmd_allocator->SetName(name);

    if (FAILED(device->CreateCommandList(
            0, D3D12_COMMAND_LIST_TYPE_DIRECT, this->cmd_allocator.Get(), nullptr, IID_PPV_ARGS(&this->cmd_list)))) {
        spdlog::error("[VR] Failed to create command list for {}", utility::narrow(name));
        return false;
    }
    
    this->cmd_list->SetName(name);

    if (FAILED(device->CreateFence(this->fence_value, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&this->fence)))) {
        spdlog::error("[VR] Failed to create fence for {}", utility::narrow(name));
        return false;
    }

    this->fence->SetName(name);
    this->fence_event = CreateEvent(nullptr, FALSE, FALSE, nullptr);
    if (this->fence_event == nullptr) {
        spdlog::error("[VR] Failed to create fence event for {}", utility::narrow(name));
        this->cmd_allocator.Reset();
        this->cmd_list.Reset();
        this->fence.Reset();
        this->poisoned = true;
        return false;
    }

    return true;
}

void CommandContext::reset() {
    std::scoped_lock _{this->mtx};
    if ((this->untracked_submission || this->waiting_for_fence) && !this->wait(2000)) {
        this->quarantine_untracked_objects();
        return;
    }
    if (!this->wait(2000) && (this->untracked_submission || this->waiting_for_fence)) {
        this->quarantine_untracked_objects();
        return;
    }
    //this->on_post_present(VR::get().get());

    this->cmd_allocator.Reset();
    this->cmd_list.Reset();
    this->fence.Reset();
    this->submission_queue.Reset();
    this->fence_value = 0;
    if (this->fence_event != nullptr) {
        CloseHandle(this->fence_event);
        this->fence_event = nullptr;
    }
    this->waiting_for_fence = false;
    this->has_commands = false;
    this->poisoned = false;
    this->untracked_submission = false;
    this->fence_event_armed = false;
    this->device_removed_after_untracked = false;
    this->close_failure_count = 0;
}

bool CommandContext::wait(uint32_t ms) {
    std::scoped_lock _{this->mtx};

    if (this->untracked_submission) {
        const auto start = GetTickCount64();
        for (;;) {
            if (this->try_wait()) {
                break;
            }
            if (!this->untracked_submission) {
                if (this->device_removed_after_untracked) {
                    // Device removal ends execution and makes all DIBR references safe to release.
                    return true;
                }
                // A retry signal established a tracked fence. Continue through
                // the ordinary wait path below until that fence retires.
                break;
            }
            if (ms == 0 || (ms != INFINITE && GetTickCount64() - start >= ms)) {
                return false;
            }
            Sleep(1);
        }
    }

    if (this->device_removed_after_untracked) {
        return true;
    }

    if (this->poisoned && !this->waiting_for_fence) {
        const auto name = this->internal_name;
        return this->setup(name.c_str());
    }

    if (!this->waiting_for_fence) {
        return this->ready();
    }

    if (this->fence_event == nullptr || this->fence == nullptr || this->cmd_allocator == nullptr || this->cmd_list == nullptr) {
        this->poisoned = true;
        return false;
    }

    DWORD wait_result = WAIT_OBJECT_0;
    const auto completed_before = this->fence->GetCompletedValue();
    if (completed_before < this->fence_value) {
        if (!this->fence_event_armed) {
            const auto start = GetTickCount64();
            while (this->fence->GetCompletedValue() < this->fence_value) {
                if (ms == 0 || (ms != INFINITE && GetTickCount64() - start >= ms)) {
                    return false;
                }
                Sleep(1);
            }
        } else if (is_fence_profiler_enabled()) {
            const auto wait_start = std::chrono::steady_clock::now();
            wait_result = WaitForSingleObject(this->fence_event, ms);
            const auto wait_duration = std::chrono::steady_clock::now() - wait_start;
            const auto completed_after = this->fence->GetCompletedValue();
            record_fence_wait(wait_duration, ms, wait_result, this->fence_value, completed_before, completed_after, this->internal_name);
        } else {
            wait_result = WaitForSingleObject(this->fence_event, ms);
        }
    }

    const auto completed_after = this->fence->GetCompletedValue();
    if (completed_after < this->fence_value) {
        if (wait_result == WAIT_FAILED) {
            spdlog::error(
                "[VR] Fence wait failed for {} (error={})",
                utility::narrow(this->internal_name),
                GetLastError());
        }
        return false;
    }

    ResetEvent(this->fence_event);
    this->waiting_for_fence = false;
    this->fence_event_armed = false;
    this->submission_queue.Reset();
    if (FAILED(this->cmd_allocator->Reset())) {
        spdlog::error("[VR] Failed to reset command allocator for {}", utility::narrow(this->internal_name));
        this->poisoned = true;
        return false;
    }

    if (FAILED(this->cmd_list->Reset(this->cmd_allocator.Get(), nullptr))) {
        spdlog::error("[VR] Failed to reset command list for {}", utility::narrow(this->internal_name));
        this->poisoned = true;
        return false;
    }

    this->has_commands = false;
    this->poisoned = false;
    return true;
}

bool CommandContext::try_wait() {
    std::scoped_lock _{this->mtx};

    if (this->untracked_submission) {
        if (checked_submission_device_removed(this->fence.Get())) {
            this->untracked_submission = false;
            this->device_removed_after_untracked = true;
            this->waiting_for_fence = false;
            this->has_commands = false;
            this->poisoned = true;
            return false;
        }

        if (this->fence == nullptr || this->cmd_allocator == nullptr || this->cmd_list == nullptr) {
            return false;
        }

        auto* command_queue = this->submission_queue.Get();
        if (command_queue == nullptr) {
            return false;
        }

        const auto next_fence_value = this->fence_value + 1;
        const auto signal_result = command_queue->Signal(this->fence.Get(), next_fence_value);
        if (FAILED(signal_result)) {
            if (checked_submission_device_removed(this->fence.Get())) {
                this->untracked_submission = false;
                this->device_removed_after_untracked = true;
                this->waiting_for_fence = false;
                this->has_commands = false;
                this->poisoned = true;
            }
            return false;
        }

        this->fence_value = next_fence_value;
        this->waiting_for_fence = true;
        this->has_commands = false;
        this->poisoned = false;
        this->untracked_submission = false;
        this->device_removed_after_untracked = false;
        const auto event_result = this->fence->SetEventOnCompletion(this->fence_value, this->fence_event);
        this->fence_event_armed = SUCCEEDED(event_result);
    }

    if (this->poisoned && !this->waiting_for_fence) {
        const auto name = this->internal_name;
        return this->setup(name.c_str());
    }

    if (!this->waiting_for_fence) {
        return this->ready();
    }

    if (this->fence == nullptr || this->cmd_allocator == nullptr || this->cmd_list == nullptr ||
        this->fence->GetCompletedValue() < this->fence_value) {
        return false;
    }

    if (this->fence_event != nullptr) {
        ResetEvent(this->fence_event);
    }

    this->waiting_for_fence = false;
    this->fence_event_armed = false;
    this->submission_queue.Reset();

    if (FAILED(this->cmd_allocator->Reset())) {
        spdlog::error("[VR] Failed to reset completed command allocator for {}", utility::narrow(this->internal_name));
        this->poisoned = true;
        return false;
    }

    if (FAILED(this->cmd_list->Reset(this->cmd_allocator.Get(), nullptr))) {
        spdlog::error("[VR] Failed to reset completed command list for {}", utility::narrow(this->internal_name));
        this->poisoned = true;
        return false;
    }

    this->has_commands = false;
    this->poisoned = false;
    return true;
}
void CommandContext::copy(ID3D12Resource* src, ID3D12Resource* dst, D3D12_RESOURCE_STATES src_state, D3D12_RESOURCE_STATES dst_state) {
    std::scoped_lock _{this->mtx};

    if (src == nullptr || dst == nullptr) {
        spdlog::error("[VR] nullptr passed to copy");
        return;
    }

    // Switch src into copy source.
    D3D12_RESOURCE_BARRIER src_barrier{};

    src_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    src_barrier.Flags = D3D12_RESOURCE_BARRIER_FLAG_NONE;
    src_barrier.Transition.pResource = src;
    src_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    src_barrier.Transition.StateBefore = src_state;
    src_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;

    // Switch dst into copy destination.
    D3D12_RESOURCE_BARRIER dst_barrier{};
    dst_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    dst_barrier.Flags = D3D12_RESOURCE_BARRIER_FLAG_NONE;
    dst_barrier.Transition.pResource = dst;
    dst_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    dst_barrier.Transition.StateBefore = dst_state;
    dst_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_DEST;

    {
        D3D12_RESOURCE_BARRIER barriers[2]{src_barrier, dst_barrier};
        record_barriers("VR::CommandContext::copy/ToCopy", 2, barriers);
        this->cmd_list->ResourceBarrier(2, barriers);
    }

    // Copy the resource.
    this->cmd_list->CopyResource(dst, src);

    // Switch back to present.
    src_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE;
    src_barrier.Transition.StateAfter = src_state;
    dst_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    dst_barrier.Transition.StateAfter = dst_state;

    {
        D3D12_RESOURCE_BARRIER barriers[2]{src_barrier, dst_barrier};
        record_barriers("VR::CommandContext::copy/Restore", 2, barriers);
        this->cmd_list->ResourceBarrier(2, barriers);
    }

    this->has_commands = true;
}

void CommandContext::copy_region(ID3D12Resource* src, ID3D12Resource* dst, D3D12_BOX* src_box, D3D12_RESOURCE_STATES src_state, D3D12_RESOURCE_STATES dst_state) {
    copy_region_to_subresource(src, dst, src_box, 0, src_state, dst_state);
}

void CommandContext::copy_region_to_subresource(ID3D12Resource* src, ID3D12Resource* dst, D3D12_BOX* src_box, UINT dst_subresource, D3D12_RESOURCE_STATES src_state, D3D12_RESOURCE_STATES dst_state) {
    std::scoped_lock _{this->mtx};

    if (src == nullptr || dst == nullptr) {
        spdlog::error("[VR] nullptr passed to copy_region_to_subresource");
        return;
    }

    // Switch src into copy source.
    D3D12_RESOURCE_BARRIER src_barrier{};

    src_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    src_barrier.Flags = D3D12_RESOURCE_BARRIER_FLAG_NONE;
    src_barrier.Transition.pResource = src;
    src_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    src_barrier.Transition.StateBefore = src_state;
    src_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;

    // Switch dst into copy destination.
    D3D12_RESOURCE_BARRIER dst_barrier{};
    dst_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    dst_barrier.Flags = D3D12_RESOURCE_BARRIER_FLAG_NONE;
    dst_barrier.Transition.pResource = dst;
    dst_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    dst_barrier.Transition.StateBefore = dst_state;
    dst_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_DEST;

    {
        D3D12_RESOURCE_BARRIER barriers[2]{src_barrier, dst_barrier};
        record_barriers("VR::CommandContext::copy_region/ToCopy", 2, barriers);
        this->cmd_list->ResourceBarrier(2, barriers);
    }

    // Copy the resource.
    D3D12_TEXTURE_COPY_LOCATION src_loc{};
    src_loc.pResource = src;
    src_loc.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    src_loc.SubresourceIndex = 0;

    D3D12_TEXTURE_COPY_LOCATION dst_loc{};
    dst_loc.pResource = dst;
    dst_loc.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    dst_loc.SubresourceIndex = dst_subresource;

    this->cmd_list->CopyTextureRegion(&dst_loc, 0, 0, 0, &src_loc, src_box);

    // Switch back to present.
    src_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE;
    src_barrier.Transition.StateAfter = src_state;
    dst_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    dst_barrier.Transition.StateAfter = dst_state;

    {
        D3D12_RESOURCE_BARRIER barriers[2]{src_barrier, dst_barrier};
        record_barriers("VR::CommandContext::copy_region/Restore", 2, barriers);
        this->cmd_list->ResourceBarrier(2, barriers);
    }

    this->has_commands = true;
}

void CommandContext::copy_region(ID3D12Resource* src, ID3D12Resource* dst, D3D12_BOX* src_box, UINT dst_x, UINT dst_y, UINT dst_z, D3D12_RESOURCE_STATES src_state, D3D12_RESOURCE_STATES dst_state) {
    std::scoped_lock _{this->mtx};

    if (src == nullptr || dst == nullptr) {
        spdlog::error("[VR] nullptr passed to copy_region");
        return;
    }

    // Switch src into copy source.
    D3D12_RESOURCE_BARRIER src_barrier{};

    src_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    src_barrier.Flags = D3D12_RESOURCE_BARRIER_FLAG_NONE;
    src_barrier.Transition.pResource = src;
    src_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    src_barrier.Transition.StateBefore = src_state;
    src_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;

    // Switch dst into copy destination.
    D3D12_RESOURCE_BARRIER dst_barrier{};
    dst_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    dst_barrier.Flags = D3D12_RESOURCE_BARRIER_FLAG_NONE;
    dst_barrier.Transition.pResource = dst;
    dst_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    dst_barrier.Transition.StateBefore = dst_state;
    dst_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_DEST;

    {
        D3D12_RESOURCE_BARRIER barriers[2]{src_barrier, dst_barrier};
        record_barriers("VR::CommandContext::copy_region_offset/ToCopy", 2, barriers);
        this->cmd_list->ResourceBarrier(2, barriers);
    }

    // Copy the resource.
    D3D12_TEXTURE_COPY_LOCATION src_loc{};
    src_loc.pResource = src;
    src_loc.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    src_loc.SubresourceIndex = 0;

    D3D12_TEXTURE_COPY_LOCATION dst_loc{};
    dst_loc.pResource = dst;
    dst_loc.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    dst_loc.SubresourceIndex = 0;

    this->cmd_list->CopyTextureRegion(&dst_loc, dst_x, dst_y, dst_z, &src_loc, src_box);

    // Switch back to present.
    src_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_SOURCE;
    src_barrier.Transition.StateAfter = src_state;
    dst_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    dst_barrier.Transition.StateAfter = dst_state;

    {
        D3D12_RESOURCE_BARRIER barriers[2]{src_barrier, dst_barrier};
        record_barriers("VR::CommandContext::copy_region_offset/Restore", 2, barriers);
        this->cmd_list->ResourceBarrier(2, barriers);
    }

    this->has_commands = true;
}

// More optimal than two copy_region calls.
void CommandContext::copy_region_stereo(ID3D12Resource* srcleft, ID3D12Resource* srcright, ID3D12Resource* dst, D3D12_BOX* srcleft_box, D3D12_BOX* srcright_box,
    UINT dstleft_x, UINT dstleft_y, UINT dstleft_z,
    UINT dstright_x, UINT dstright_y, UINT dstright_z,
    D3D12_RESOURCE_STATES src_state,
    D3D12_RESOURCE_STATES dst_state)
{
    if (srcleft == nullptr || srcright == nullptr || dst == nullptr) {
        spdlog::error("[VR] nullptr passed to copy_region_stereo");
        return;
    }

    // Transition states to copy source / dest.
    D3D12_RESOURCE_BARRIER barriers[3]
    {
        { D3D12_RESOURCE_BARRIER_TYPE_TRANSITION, D3D12_RESOURCE_BARRIER_FLAG_NONE, {srcleft, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, src_state, D3D12_RESOURCE_STATE_COPY_SOURCE} },
        { D3D12_RESOURCE_BARRIER_TYPE_TRANSITION, D3D12_RESOURCE_BARRIER_FLAG_NONE, {srcright, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, src_state, D3D12_RESOURCE_STATE_COPY_SOURCE} },
        { D3D12_RESOURCE_BARRIER_TYPE_TRANSITION, D3D12_RESOURCE_BARRIER_FLAG_NONE, {dst, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, dst_state, D3D12_RESOURCE_STATE_COPY_DEST} }
    };
    
    record_barriers("VR::CommandContext::copy_region_stereo/ToCopy", 3, barriers);
    this->cmd_list->ResourceBarrier(3, barriers);

    // Copy left half
    D3D12_TEXTURE_COPY_LOCATION src_loc_left = { srcleft, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX, 0 };
    D3D12_TEXTURE_COPY_LOCATION dst_loc = { dst, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX, 0 };

    this->cmd_list->CopyTextureRegion(&dst_loc, dstleft_x, dstleft_y, dstleft_z, &src_loc_left, srcleft_box);

    // Copy right half
    D3D12_TEXTURE_COPY_LOCATION src_loc_right = { srcright, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX, 0 };

    this->cmd_list->CopyTextureRegion(&dst_loc, dstright_x, dstright_y, dstright_z, &src_loc_right, srcright_box);

    // Transition states back to original.
    barriers[0] = { D3D12_RESOURCE_BARRIER_TYPE_TRANSITION, D3D12_RESOURCE_BARRIER_FLAG_NONE, {srcleft, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, D3D12_RESOURCE_STATE_COPY_SOURCE, src_state} };
    barriers[1] = { D3D12_RESOURCE_BARRIER_TYPE_TRANSITION, D3D12_RESOURCE_BARRIER_FLAG_NONE, {srcright, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, D3D12_RESOURCE_STATE_COPY_SOURCE, src_state} };
    barriers[2] = { D3D12_RESOURCE_BARRIER_TYPE_TRANSITION, D3D12_RESOURCE_BARRIER_FLAG_NONE, {dst, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, D3D12_RESOURCE_STATE_COPY_DEST, dst_state} };

    record_barriers("VR::CommandContext::copy_region_stereo/Restore", 3, barriers);
    this->cmd_list->ResourceBarrier(3, barriers);

    this->has_commands = true;
}

void CommandContext::clear_rtv(ID3D12Resource* dst, D3D12_CPU_DESCRIPTOR_HANDLE rtv, const float* color, D3D12_RESOURCE_STATES dst_state) {
    std::scoped_lock _{this->mtx};

    if (dst == nullptr) {
        spdlog::error("[VR] nullptr passed to clear_rtv");
        return;
    }

    // Switch dst into copy destination.
    D3D12_RESOURCE_BARRIER dst_barrier{};
    dst_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    dst_barrier.Flags = D3D12_RESOURCE_BARRIER_FLAG_NONE;
    dst_barrier.Transition.pResource = dst;
    dst_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    dst_barrier.Transition.StateBefore = dst_state;
    dst_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_RENDER_TARGET;

    // No need to switch if we're already in the right state.
    if (dst_state != dst_barrier.Transition.StateAfter) {
        D3D12_RESOURCE_BARRIER barriers[1]{dst_barrier};
        record_barriers("VR::CommandContext::clear_rtv/ToRT", 1, barriers);
        this->cmd_list->ResourceBarrier(1, barriers);
    }

    // Clear the resource.
    this->cmd_list->ClearRenderTargetView(rtv, color, 0, nullptr);

    // Switch back to present.
    dst_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_RENDER_TARGET;
    dst_barrier.Transition.StateAfter = dst_state;

    if (dst_state != dst_barrier.Transition.StateBefore) {
        D3D12_RESOURCE_BARRIER barriers[1]{dst_barrier};
        record_barriers("VR::CommandContext::clear_rtv/Restore", 1, barriers);
        this->cmd_list->ResourceBarrier(1, barriers);
    }

    this->has_commands = true;
}

void CommandContext::clear_rtv(d3d12::TextureContext& tex, const float* color, D3D12_RESOURCE_STATES dst_state) {
    if (tex.texture == nullptr || tex.rtv_heap == nullptr) {
        return;
    }

    this->clear_rtv(tex.texture.Get(), tex.get_rtv(), color, dst_state);
}

bool CommandContext::references_retired() {
    std::scoped_lock _{this->mtx};
    if (this->device_removed_after_untracked) {
        return true;
    }
    if (this->untracked_submission) {
        return checked_submission_device_removed(this->fence.Get());
    }
    // An idle or merely recorded command list has never been handed to a
    // queue. In particular, an uninitialized context is safe to destroy even
    // though wait() returns false for it because it is not ready.
    if (!this->waiting_for_fence) {
        return true;
    }
    return utility::gpu::references_retired(this->has_commands, this->waiting_for_fence,
        this->poisoned, this->fence != nullptr, this->fence_value,
        [&] { return this->fence->GetCompletedValue(); });
}

void CommandContext::execute() {
    std::scoped_lock _{this->mtx};

    if (this->poisoned || !this->ready()) {
        return;
    }

    if (this->has_commands) {
        const auto close_result = this->cmd_list->Close();
        if (FAILED(close_result)) {
            this->has_commands = false;
            this->poisoned = true;
            const auto failure_count = ++this->close_failure_count;
            if (failure_count == 1 || failure_count % 120 == 0) {
                spdlog::error(
                    "[VR] Failed to close command list. ({} hr=0x{:08x}, consecutive={})",
                    utility::narrow(this->internal_name),
                    static_cast<uint32_t>(close_result),
                    failure_count);
            }
            return;
        }

        this->close_failure_count = 0;
        
        auto command_queue = g_framework->get_d3d12_hook()->get_command_queue();
        if (command_queue == nullptr) {
            this->poisoned = true;
            this->has_commands = false;
            spdlog::error("[VR] Cannot execute command list without a command queue. ({})", utility::narrow(this->internal_name));
            return;
        }

        ID3D12CommandList* const cmd_lists[] = {this->cmd_list.Get()};
        const auto profile_fence = is_fence_profiler_enabled();
        const auto execute_start = profile_fence
            ? std::chrono::steady_clock::now()
            : std::chrono::steady_clock::time_point{};
        command_queue->ExecuteCommandLists(1, cmd_lists);
        this->submission_queue = command_queue;
        const auto next_fence_value = this->fence_value + 1;
        const auto signal_result = command_queue->Signal(this->fence.Get(), next_fence_value);
        if (FAILED(signal_result)) {
            this->poisoned = true;
            this->has_commands = false;
            this->untracked_submission = true;
            this->waiting_for_fence = false;
            this->fence_event_armed = false;
            spdlog::error(
                "[VR] Failed to signal command fence. ({} hr=0x{:08x})",
                utility::narrow(this->internal_name),
                static_cast<uint32_t>(signal_result));
            return;
        }

        this->fence_value = next_fence_value;
        const auto event_result = this->fence->SetEventOnCompletion(this->fence_value, this->fence_event);
        if (FAILED(event_result)) {
            // The signal itself succeeded, so this is tracked work. Keep the
            // original queue and poll the fence instead of treating the
            // submitted list as idle or untracked.
            this->waiting_for_fence = true;
            this->fence_event_armed = false;
            this->has_commands = false;
            this->poisoned = false;
            spdlog::error(
                "[VR] Failed to arm command fence event. ({} hr=0x{:08x})",
                utility::narrow(this->internal_name),
                static_cast<uint32_t>(event_result));
            return;
        }
        if (profile_fence) {
            record_fence_execute_signal(
                std::chrono::steady_clock::now() - execute_start,
                this->fence_value,
                this->fence != nullptr ? this->fence->GetCompletedValue() : 0,
                this->internal_name
            );
        }
        this->waiting_for_fence = true;
        this->fence_event_armed = true;
        this->has_commands = false;
    }
}

bool CommandContext::discard_recording() {
    std::scoped_lock _{this->mtx};
    if (this->waiting_for_fence || this->untracked_submission || this->poisoned ||
        this->cmd_allocator == nullptr || this->cmd_list == nullptr) {
        return false;
    }

    const auto context_name = this->internal_name;
    const auto discarded = dibr_transaction::discard_open_recording(
        [&] { return this->cmd_list->Close(); },
        [&] { return this->cmd_allocator->Reset(); },
        [&] { return this->cmd_list->Reset(this->cmd_allocator.Get(), nullptr); },
        [&] {
            this->has_commands = false;
            this->poisoned = true;
            return this->setup(context_name.c_str());
        });
    if (!discarded) {
        this->has_commands = false;
        this->poisoned = true;
        return false;
    }
    this->has_commands = false;
    this->fence_event_armed = false;
    return true;
}

dibr_transaction::ExecuteResult CommandContext::execute_checked() {
    std::scoped_lock _{this->mtx};

    if (this->poisoned || !this->ready()) {
        return dibr_transaction::ExecuteResult::NotSubmitted;
    }
    if (!this->has_commands) {
        return dibr_transaction::ExecuteResult::NoWork;
    }

    auto hook = g_framework != nullptr ? g_framework->get_d3d12_hook() : nullptr;
    auto command_queue = hook != nullptr ? hook->get_command_queue() : nullptr;
    if (command_queue == nullptr) {
        this->has_commands = false;
        this->poisoned = true;
        spdlog::error("[VR] Cannot execute checked DIBR list without a command queue. ({})", utility::narrow(this->internal_name));
        const auto context_name = this->internal_name;
        if (!this->setup(context_name.c_str())) {
            this->poisoned = true;
        }
        return dibr_transaction::ExecuteResult::NotSubmitted;
    }

    const auto next_fence_value = this->fence_value + 1;
    HRESULT close_result{E_FAIL};
    HRESULT signal_result{E_FAIL};
    HRESULT event_result{E_FAIL};
    ID3D12CommandList* const cmd_lists[] = {this->cmd_list.Get()};
    const auto profile_fence = is_fence_profiler_enabled();
    const auto execute_start = profile_fence
        ? std::chrono::steady_clock::now()
        : std::chrono::steady_clock::time_point{};

    const auto result = dibr_transaction::submit_recorded_commands(
        [&] {
            close_result = this->cmd_list->Close();
            return close_result;
        },
        [&] { command_queue->ExecuteCommandLists(1, cmd_lists); },
        [&] {
            signal_result = command_queue->Signal(this->fence.Get(), next_fence_value);
            return signal_result;
        },
        [&] {
            event_result = this->fence->SetEventOnCompletion(next_fence_value, this->fence_event);
            return event_result;
        });

    if (result == dibr_transaction::ExecuteResult::NotSubmitted) {
        this->has_commands = false;
        this->poisoned = true;
        const auto failure_count = ++this->close_failure_count;
        if (failure_count == 1 || failure_count % 120 == 0) {
            spdlog::error(
                "[VR] Failed to close checked DIBR command list. ({} hr=0x{:08x}, consecutive={})",
                utility::narrow(this->internal_name),
                static_cast<uint32_t>(close_result),
                failure_count);
        }
        // Close failed before ExecuteCommandLists. Nothing reached the queue,
        // so rebuilding the idle context drops the incomplete list and every
        // resource reference held by that partial recording.
        const auto context_name = this->internal_name;
        if (!this->setup(context_name.c_str())) {
            this->poisoned = true;
        }
        return result;
    }

    this->close_failure_count = 0;
    this->has_commands = false;
    this->submission_queue = command_queue;
    if (result == dibr_transaction::ExecuteResult::SubmittedUntracked) {
        this->waiting_for_fence = false;
        this->fence_event_armed = false;
        this->untracked_submission = true;
        this->device_removed_after_untracked = false;
        this->poisoned = true;
        spdlog::error(
            "[VR] Checked DIBR submission is in flight without a retirement fence. ({}, hr=0x{:08x}); retaining its resources",
            utility::narrow(this->internal_name),
            static_cast<uint32_t>(signal_result));
        return result;
    }

    this->fence_value = next_fence_value;
    this->waiting_for_fence = true;
    this->poisoned = false;
    this->fence_event_armed = result == dibr_transaction::ExecuteResult::SubmittedTracked;
    if (result == dibr_transaction::ExecuteResult::SubmittedTrackedNeedsPolling) {
        spdlog::error(
            "[VR] Checked DIBR fence event could not be armed; polling its signaled fence for retirement. ({}, hr=0x{:08x})",
            utility::narrow(this->internal_name),
            static_cast<uint32_t>(event_result));
    }
    if (profile_fence) {
        record_fence_execute_signal(
            std::chrono::steady_clock::now() - execute_start,
            this->fence_value,
            this->fence->GetCompletedValue(),
            this->internal_name);
    }
    return result;
}

void CommandContext::quarantine_untracked_objects() {
    if (!this->untracked_submission && !this->waiting_for_fence) {
        return;
    }

    dibr_transaction::retain_untracked_com_object(this->cmd_allocator.Get());
    dibr_transaction::retain_untracked_com_object(this->cmd_list.Get());
    dibr_transaction::retain_untracked_com_object(this->fence.Get());
    dibr_transaction::retain_untracked_com_object(this->submission_queue.Get());
}
}

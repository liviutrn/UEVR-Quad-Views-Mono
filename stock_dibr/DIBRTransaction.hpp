#pragma once

#include <d3d12.h>
#include <wrl.h>

#include <memory>
#include <mutex>
#include <utility>
#include <vector>

namespace d3d12::dibr_transaction {

enum class ExecuteResult : unsigned char {
    NoWork,
    NotSubmitted,
    SubmittedTracked,
    SubmittedTrackedNeedsPolling,
    SubmittedUntracked,
};

enum class RetirementExtendResult : unsigned char {
    Tracked,
    TrackedNeedsPolling,
    SubmittedUntracked,
};

// This is the production phase ordering used by CommandContext's checked DIBR
// path. `submit` runs only after Close succeeds. Once it runs, a failed fence
// signal must be treated as an in-flight, untracked submission.
template <typename Close, typename Submit, typename Signal, typename ArmEvent>
ExecuteResult submit_recorded_commands(Close&& close, Submit&& submit, Signal&& signal, ArmEvent&& arm_event) {
    if (FAILED(close())) {
        return ExecuteResult::NotSubmitted;
    }

    submit();
    if (FAILED(signal())) {
        return ExecuteResult::SubmittedUntracked;
    }

    return FAILED(arm_event())
        ? ExecuteResult::SubmittedTrackedNeedsPolling
        : ExecuteResult::SubmittedTracked;
}

// Drop a recording that has never been submitted. D3D12 requires the list to
// be closed before allocator/list reset. If any step fails, recreate the idle
// context so the partially recorded list and its references are released.
template <typename Close, typename ResetAllocator, typename ResetList, typename Recreate>
bool discard_open_recording(Close&& close, ResetAllocator&& reset_allocator, ResetList&& reset_list, Recreate&& recreate) {
    if (FAILED(close())) {
        return recreate();
    }
    if (FAILED(reset_allocator())) {
        return recreate();
    }
    if (FAILED(reset_list())) {
        return recreate();
    }
    return true;
}

// Advance a queue retirement fence at the end of a transaction. D3D12 cannot
// cancel an older SetEventOnCompletion registration, so tail fences are always
// polled: the producer's old event may wake early while downstream work is in
// flight. A signal failure leaves submitted work untracked.
template <typename ResetNotification, typename Signal>
RetirementExtendResult extend_queue_retirement(
    ResetNotification&& reset_notification,
    Signal&& signal)
{
    reset_notification();
    if (FAILED(signal())) {
        return RetirementExtendResult::SubmittedUntracked;
    }

    return RetirementExtendResult::TrackedNeedsPolling;
}

class OutputWriteState {
public:
    bool begin_after_preparation(bool preview_prepared, bool presentation_prepared) {
        return begin_after_preparation(preview_prepared && presentation_prepared);
    }

    bool begin_after_preparation(bool preparation_succeeded) {
        if (!preparation_succeeded || m_recording_pending) {
            return false;
        }

        m_recording_pending = true;
        return true;
    }

    void commit() {
        if (m_recording_pending) {
            m_output_written = true;
            m_recording_pending = false;
        }
    }

    void abort() { m_recording_pending = false; }

    void replace_output() {
        m_output_written = false;
        m_recording_pending = false;
    }

    bool output_written() const { return m_output_written; }
    bool recording_pending() const { return m_recording_pending; }

private:
    bool m_output_written{};
    bool m_recording_pending{};
};

inline bool needs_ui_alpha(bool ui_edge_guard, bool ui_footprint_reprojection, bool footprint_debug_mask) {
    return ui_edge_guard || ui_footprint_reprojection || footprint_debug_mask;
}

// Process-lifetime storage is intentional: if ExecuteCommandLists succeeded
// but no fence can be signaled, releasing any referenced object before device
// removal may invalidate work still owned by the queue. Callers use this only
// after bounded retirement fails for a checked DIBR submission.
inline void retain_untracked_com_object(IUnknown* object) {
    if (object == nullptr) {
        return;
    }

    struct Store {
        std::mutex mutex{};
        std::vector<Microsoft::WRL::ComPtr<IUnknown>> objects{};
    };
    static auto* store = new Store{};

    Microsoft::WRL::ComPtr<IUnknown> retained{};
    if (FAILED(object->QueryInterface(IID_PPV_ARGS(&retained)))) {
        return;
    }

    std::scoped_lock lock{store->mutex};
    store->objects.emplace_back(std::move(retained));
}

template <typename T>
void retain_untracked_unique(std::unique_ptr<T>& object) {
    if (!object) {
        return;
    }

    struct Store {
        std::mutex mutex{};
        std::vector<std::unique_ptr<T>> objects{};
    };
    static auto* store = new Store{};

    std::scoped_lock lock{store->mutex};
    store->objects.emplace_back(std::move(object));
}

} // namespace d3d12::dibr_transaction

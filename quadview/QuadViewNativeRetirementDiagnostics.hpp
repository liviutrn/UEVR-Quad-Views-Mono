#pragma once

#include <cstddef>
#include <cstdint>
#include <type_traits>

namespace uevr::quadview {

inline constexpr size_t native_retirement_list_walk_cap = 256;

enum class NativeRetirementPollState : uint8_t {
    unobserved,
    value_observed,
    device_removed,
};

struct NativeRetirementListCount {
    uint32_t count{}; // Lower bound when truncated is true.
    bool truncated{};
};

// A fixed-size, ownership-free snapshot. List caps apply independently to
// pending, staged, in-flight, and ready lists (up to 4 * 256 nodes total).
struct NativeRetirementDiagnostics {
    NativeRetirementListCount pending{};
    NativeRetirementListCount staged{};
    NativeRetirementListCount in_flight{};
    NativeRetirementListCount ready{};
    uintptr_t last_successful_queue{};
    uintptr_t last_successful_device{};
    uintptr_t last_successful_fence{};
    uint64_t last_successful_signal_value{};
    uintptr_t last_poll_fence{};
    uintptr_t last_poll_device{};
    uint64_t last_poll_completed_value{};
    uint64_t last_poll_target_value{};
    NativeRetirementPollState last_poll_state{NativeRetirementPollState::unobserved};
    bool observed{};
    bool busy{};
    bool last_successful_signal_observed{};
};
static_assert(std::is_trivially_copyable_v<NativeRetirementDiagnostics>);

template <class Node, class Next>
NativeRetirementListCount count_native_retirement_list(
    Node* head, Next&& next, size_t cap = native_retirement_list_walk_cap) noexcept {
    NativeRetirementListCount result{};
    if (cap > native_retirement_list_walk_cap) cap = native_retirement_list_walk_cap;
    while (head && result.count < cap) {
        ++result.count;
        head = next(head);
    }
    result.truncated = head != nullptr;
    return result;
}

constexpr NativeRetirementPollState native_retirement_poll_state(
    bool observed, uint64_t completed_value) noexcept {
    if (!observed) return NativeRetirementPollState::unobserved;
    return completed_value == UINT64_MAX
        ? NativeRetirementPollState::device_removed
        : NativeRetirementPollState::value_observed;
}

constexpr const char* to_string(NativeRetirementPollState state) noexcept {
    switch (state) {
    case NativeRetirementPollState::unobserved: return "unobserved";
    case NativeRetirementPollState::value_observed: return "value_observed";
    case NativeRetirementPollState::device_removed: return "device_removed";
    }
    return "unknown";
}

} // namespace uevr::quadview

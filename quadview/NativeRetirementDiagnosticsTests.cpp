#include "QuadViewNativeRetirementDiagnostics.hpp"

#include <array>
#include <cassert>
#include <cstring>
#include <type_traits>

using namespace uevr::quadview;

struct Node { Node* next{}; };

int main() {
    static_assert(std::is_trivially_copyable_v<NativeRetirementDiagnostics>);
    static_assert(std::is_trivially_copyable_v<NativeRetirementListCount>);

    const auto empty = count_native_retirement_list(static_cast<Node*>(nullptr),
        [](Node* node) { return node->next; });
    assert(empty.count == 0 && !empty.truncated);

    std::array<Node,3> line{};
    line[0].next=&line[1]; line[1].next=&line[2];
    const auto full = count_native_retirement_list(&line[0],
        [](Node* node) { return node->next; });
    assert(full.count == 3 && !full.truncated);
    const auto partial = count_native_retirement_list(&line[0],
        [](Node* node) { return node->next; }, 2);
    assert(partial.count == 2 && partial.truncated);

    // Corruption cannot make a production walk unbounded. Even a caller that
    // supplies a larger cap is limited to the fixed per-list ceiling.
    std::array<Node,3> cycle{};
    cycle[0].next=&cycle[1]; cycle[1].next=&cycle[2]; cycle[2].next=&cycle[0];
    const auto cyclic = count_native_retirement_list(&cycle[0],
        [](Node* node) { return node->next; }, 2);
    assert(cyclic.count == 2 && cyclic.truncated);
    const auto oversized = count_native_retirement_list(&cycle[0],
        [](Node* node) { return node->next; }, native_retirement_list_walk_cap + 4096);
    assert(oversized.count == native_retirement_list_walk_cap && oversized.truncated);

    assert(native_retirement_poll_state(false, 0) == NativeRetirementPollState::unobserved);
    assert(native_retirement_poll_state(true, 0) == NativeRetirementPollState::value_observed);
    assert(native_retirement_poll_state(true, 17) == NativeRetirementPollState::value_observed);
    const auto removed = native_retirement_poll_state(true, UINT64_MAX);
    assert(removed == NativeRetirementPollState::device_removed);
    assert(std::strcmp(to_string(removed), "device_removed") == 0);
}

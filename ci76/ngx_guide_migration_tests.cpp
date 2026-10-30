#include "DuoViewNgxGuide.hpp"

#include <array>
#include <cassert>
#include <cstdint>

using namespace uevr::duoview::ngx;

static void right_pin_migrates_only_for_same_feature() {
    ManualNgxRegistry registry;
    registry.set_outputs({2030, 1614, 812, 646});
    constexpr uintptr_t selected = 0x1234;
    constexpr uintptr_t other = 0x5678;

    registry.observe({selected, 10, 1, 812, 646, 2030, 1614, 1, true, true, 0});
    assert(registry.pin(1, selected, 812, 646));
    assert(registry.role(selected, 812, 646) == 2);

    registry.set_outputs({2030, 1614, 2026, 1611});
    assert(registry.role(selected, 812, 646) == 0);
    assert(registry.role(selected, 2026, 1611) == 2);

    registry.observe({other, 11, 1, 2026, 1611, 2030, 1614, 1, true, true, 0});
    assert(registry.role(other, 2026, 1611) == 0); // no feature auto-selection
    assert(registry.role(selected, 2026, 1611) == 2);

    registry.released(selected);
    assert(registry.role(selected, 2026, 1611) == 0);
    assert(registry.pins()[1][0] == 0);
}

static void wrong_sized_candidate_cannot_be_pinned() {
    ManualNgxRegistry registry;
    registry.set_outputs({2030, 1614, 2026, 1611});
    constexpr uintptr_t feature = 0x2468;
    registry.observe({feature, 1, 1, 812, 646, 2030, 1614, 1, true, true, 0});
    assert(!registry.pin(1, feature, 812, 646));
    assert(registry.role(feature, 812, 646) == 0);
}

static void one_handle_can_keep_two_different_extent_roles() {
    ManualNgxRegistry registry;
    registry.set_outputs({2030, 1614, 812, 646});
    constexpr uintptr_t feature = 0x369a;
    registry.observe({feature, 1, 1, 2030, 1614, 2030, 1614, 1, true, true, 0});
    registry.observe({feature, 2, 2, 812, 646, 2030, 1614, 1, true, true, 0});
    assert(registry.pin(0, feature, 2030, 1614));
    assert(registry.pin(1, feature, 812, 646));
    assert(registry.role(feature, 2030, 1614) == 1);
    assert(registry.role(feature, 812, 646) == 2);

    registry.set_outputs({2040, 1620, 2026, 1611});
    assert(registry.role(feature, 2030, 1614) == 0);
    assert(registry.role(feature, 812, 646) == 0);
    assert(registry.role(feature, 2040, 1620) == 1);
    assert(registry.role(feature, 2026, 1611) == 2);
}

int main() {
    right_pin_migrates_only_for_same_feature();
    wrong_sized_candidate_cannot_be_pinned();
    one_handle_can_keep_two_different_extent_roles();
}

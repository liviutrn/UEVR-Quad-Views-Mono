#include "QuadViewSettings.hpp"

#include <cassert>
#include <cmath>
#include <limits>

using uevr::quadview::Settings;
using uevr::quadview::reconcile_settings;
using uevr::quadview::same_settings;

int main() {
    const Settings defaults{};
    auto accepted = reconcile_settings(defaults, defaults, 1920, 1080);
    assert(accepted.rejected == 0);
    assert(accepted.settings.seam_mode == 0);
    assert(accepted.settings.seam_strength == .85f);
    assert(accepted.settings.seam_max_gain == .20f);
    assert(accepted.settings.seam_brightness_ev == 0.f);
    assert(accepted.settings.seam_color_strength == .5f);
    assert(accepted.settings.seam_local_strength == .5f);
    assert(accepted.settings.seam_radius_px == 120.f);
    assert(accepted.settings.seam_transition_px == 0.f);
    assert(!accepted.settings.seam_debug);
    assert(!accepted.settings.focus_lift_enabled);
    assert(accepted.settings.focus_center_ev == 0.f);
    assert(accepted.settings.focus_edge_ev == .25f);

    Settings edge = defaults;
    edge.seam_mode = 2;
    edge.seam_strength = 0.f;
    edge.seam_max_gain = .01f;
    edge.seam_brightness_ev = -.5f;
    edge.seam_color_strength = 1.f;
    edge.seam_local_strength = 0.f;
    edge.seam_radius_px = 16.f;
    edge.seam_transition_px = 64.f;
    edge.seam_debug = true;
    edge.focus_lift_enabled = true;
    edge.focus_center_ev = -.5f;
    edge.focus_edge_ev = 0.f;
    accepted = reconcile_settings(edge, defaults, 1920, 1080);
    assert(accepted.rejected == 0);
    assert(same_settings(accepted.settings, edge));
    edge.focus_center_ev = .5f;
    edge.focus_edge_ev = 1.5f;
    accepted = reconcile_settings(edge, defaults, 1920, 1080);
    assert(accepted.rejected == 0);
    assert(same_settings(accepted.settings, edge));

    Settings lift_while_seams_off = defaults;
    lift_while_seams_off.focus_lift_enabled = true;
    accepted = reconcile_settings(lift_while_seams_off, defaults, 1920, 1080);
    assert(accepted.rejected == 0);
    assert(accepted.settings.seam_mode == 0);
    assert(accepted.settings.focus_lift_enabled);

    edge.seam_local_strength = 1.f;
    edge.seam_radius_px = 512.f;
    accepted = reconcile_settings(edge, defaults, 1920, 1080);
    assert(accepted.rejected == 0);
    assert(same_settings(accepted.settings, edge));

    const auto rejects_seam = [&](auto set_invalid, auto check_preserved) {
        Settings requested = defaults;
        set_invalid(requested);
        const auto result = reconcile_settings(requested, defaults, 1920, 1080);
        assert((result.rejected & uevr::quadview::reject_seam) != 0);
        check_preserved(result.settings);
    };
    rejects_seam([](Settings& s) { s.seam_mode = 3; },
        [](const Settings& s) { assert(s.seam_mode == 0); });
    rejects_seam([](Settings& s) { s.seam_strength = -0.01f; },
        [](const Settings& s) { assert(s.seam_strength == .85f); });
    rejects_seam([](Settings& s) { s.seam_max_gain = 0.f; },
        [](const Settings& s) { assert(s.seam_max_gain == .20f); });
    rejects_seam([](Settings& s) { s.seam_brightness_ev = .51f; },
        [](const Settings& s) { assert(s.seam_brightness_ev == 0.f); });
    rejects_seam([](Settings& s) { s.seam_color_strength = std::numeric_limits<float>::quiet_NaN(); },
        [](const Settings& s) { assert(s.seam_color_strength == .5f); });
    rejects_seam([](Settings& s) { s.seam_local_strength = -0.01f; },
        [](const Settings& s) { assert(s.seam_local_strength == .5f); });
    rejects_seam([](Settings& s) { s.seam_radius_px = 15.f; },
        [](const Settings& s) { assert(s.seam_radius_px == 120.f); });
    rejects_seam([](Settings& s) { s.seam_transition_px = 64.01f; },
        [](const Settings& s) { assert(s.seam_transition_px == 0.f); });
    rejects_seam([](Settings& s) { s.focus_center_ev = -.51f; },
        [](const Settings& s) { assert(s.focus_center_ev == 0.f); });
    rejects_seam([](Settings& s) { s.focus_edge_ev = 1.51f; },
        [](const Settings& s) { assert(s.focus_edge_ev == .25f); });

    Settings changed = defaults;
    changed.seam_mode = 1;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.seam_strength += .01f;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.seam_max_gain += .01f;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.seam_brightness_ev += .01f;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.seam_color_strength += .01f;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.seam_local_strength += .01f;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.seam_radius_px = 121.f;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.seam_transition_px = 1.f;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.seam_debug = true;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.focus_lift_enabled = true;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.focus_center_ev = .1f;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.focus_edge_ev = .5f;
    assert(!same_settings(defaults, changed));
}

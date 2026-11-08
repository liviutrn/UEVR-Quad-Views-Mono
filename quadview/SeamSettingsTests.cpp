#include "QuadViewSettings.hpp"

#include <cassert>
#include <limits>

using uevr::quadview::Settings;
using uevr::quadview::reconcile_settings;
using uevr::quadview::same_settings;

int main() {
    const Settings defaults{};
    auto result = reconcile_settings(defaults, defaults, 1920, 1080);
    assert(result.rejected == 0);
    assert(result.settings.seam_mode == 0); // portable default preserves legacy GPU tests
    assert(result.settings.seam_strength == .85f);
    assert(result.settings.seam_max_gain == .20f);
    assert(result.settings.seam_brightness_ev == 0.f);
    assert(result.settings.seam_color_strength == .5f);
    assert(result.settings.seam_local_strength == .5f);
    assert(result.settings.seam_radius_px == 120.f);
    assert(result.settings.seam_transition_px == 0.f);
    assert(result.settings.seam_noise_guard == .035f);
    assert(result.settings.seam_chroma_guard == .015f);
    assert(!result.settings.seam_debug);

    Settings minimum = defaults;
    minimum.seam_mode = 1;
    minimum.seam_strength = 0.f;
    minimum.seam_max_gain = .01f;
    minimum.seam_brightness_ev = -.5f;
    minimum.seam_color_strength = 0.f;
    minimum.seam_local_strength = 0.f;
    minimum.seam_radius_px = 16.f;
    minimum.seam_transition_px = 0.f;
    minimum.seam_debug = true;
    result = reconcile_settings(minimum, defaults, 1920, 1080);
    assert(result.rejected == 0);
    assert(same_settings(result.settings, minimum));

    Settings maximum = defaults;
    maximum.seam_mode = 2;
    maximum.seam_strength = 1.f;
    maximum.seam_max_gain = .5f;
    maximum.seam_brightness_ev = .5f;
    maximum.seam_color_strength = 1.f;
    maximum.seam_local_strength = 1.f;
    maximum.seam_radius_px = 512.f;
    maximum.seam_transition_px = 64.f;
    maximum.seam_debug = true;
    result = reconcile_settings(maximum, defaults, 1920, 1080);
    assert(result.rejected == 0);
    assert(same_settings(result.settings, maximum));

    const auto rejects = [&](auto set_invalid, auto check_preserved) {
        Settings requested = defaults;
        set_invalid(requested);
        const auto rejected = reconcile_settings(requested, defaults, 1920, 1080);
        assert(rejected.rejected & uevr::quadview::reject_seam);
        check_preserved(rejected.settings);
    };
    rejects([](Settings& s) { s.seam_mode = 4; },
        [](const Settings& s) { assert(s.seam_mode == 0); });
    rejects([](Settings& s) { s.seam_strength = -0.01f; },
        [](const Settings& s) { assert(s.seam_strength == .85f); });
    rejects([](Settings& s) { s.seam_max_gain = 0.f; },
        [](const Settings& s) { assert(s.seam_max_gain == .20f); });
    rejects([](Settings& s) { s.seam_brightness_ev = .51f; },
        [](const Settings& s) { assert(s.seam_brightness_ev == 0.f); });
    rejects([](Settings& s) { s.seam_color_strength = std::numeric_limits<float>::quiet_NaN(); },
        [](const Settings& s) { assert(s.seam_color_strength == .5f); });
    rejects([](Settings& s) { s.seam_local_strength = -0.01f; },
        [](const Settings& s) { assert(s.seam_local_strength == .5f); });
    rejects([](Settings& s) { s.seam_radius_px = 15.f; },
        [](const Settings& s) { assert(s.seam_radius_px == 120.f); });
    rejects([](Settings& s) { s.seam_transition_px = 64.01f; },
        [](const Settings& s) { assert(s.seam_transition_px == 0.f); });

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
    changed = defaults; changed.seam_radius_px += 1.f;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.seam_transition_px = 1.f;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.seam_mode = 3;
    assert(!same_settings(defaults, changed));
    auto boundary = defaults; boundary.seam_mode = 3;
    const auto accepted = reconcile_settings(boundary, defaults, 1810, 1440);
    assert(accepted.settings.seam_mode == 3);
    changed = defaults; changed.seam_noise_guard = .07f;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.seam_chroma_guard = .05f;
    assert(!same_settings(defaults, changed));
    changed = defaults; changed.seam_debug = true;
    assert(!same_settings(defaults, changed));
}

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
    assert(!result.settings.focus_lift_enabled); // portable default preserves legacy callers
    assert(result.settings.focus_brightness == 1.f);
    assert(result.settings.focus_lift_strength == 1.f);
    assert(result.settings.focus_corner_gain == uevr::quadview::focus_lift::default_corner_gain);
    assert(result.settings.focus_lift_onset == uevr::quadview::focus_lift::default_onset);
    assert(result.settings.focus_lift_power == uevr::quadview::focus_lift::default_power);

    Settings minimum = defaults;
    minimum.focus_lift_enabled = true;
    minimum.focus_brightness = .8f;
    minimum.focus_lift_strength = 0.f;
    minimum.focus_corner_gain = 1.f;
    minimum.focus_lift_onset = 0.f;
    minimum.focus_lift_power = .5f;
    result = reconcile_settings(minimum, defaults, 1920, 1080);
    assert(result.rejected == 0);
    assert(same_settings(result.settings, minimum));

    Settings maximum = defaults;
    maximum.focus_lift_enabled = true;
    maximum.focus_brightness = 1.3f;
    maximum.focus_lift_strength = 2.f;
    maximum.focus_corner_gain = 1.5f;
    maximum.focus_lift_onset = .9f;
    maximum.focus_lift_power = 3.f;
    result = reconcile_settings(maximum, defaults, 1920, 1080);
    assert(result.rejected == 0);
    assert(same_settings(result.settings, maximum));

    const auto rejects = [&](auto set_invalid, auto check_preserved) {
        Settings requested = defaults;
        set_invalid(requested);
        const auto rejected = reconcile_settings(requested, defaults, 1920, 1080);
        assert(rejected.rejected & uevr::quadview::reject_focus_lift);
        check_preserved(rejected.settings);
    };
    rejects([](Settings& s) { s.focus_brightness = .79f; },
        [](const Settings& s) { assert(s.focus_brightness == 1.f); });
    rejects([](Settings& s) { s.focus_lift_strength = 2.01f; },
        [](const Settings& s) { assert(s.focus_lift_strength == 1.f); });
    rejects([](Settings& s) { s.focus_corner_gain = .99f; },
        [](const Settings& s) { assert(s.focus_corner_gain == uevr::quadview::focus_lift::default_corner_gain); });
    rejects([](Settings& s) { s.focus_lift_onset = .91f; },
        [](const Settings& s) { assert(s.focus_lift_onset == uevr::quadview::focus_lift::default_onset); });
    rejects([](Settings& s) { s.focus_lift_power = .49f; },
        [](const Settings& s) { assert(s.focus_lift_power == uevr::quadview::focus_lift::default_power); });
    rejects([](Settings& s) { s.focus_lift_power = std::numeric_limits<float>::quiet_NaN(); },
        [](const Settings& s) { assert(s.focus_lift_power == uevr::quadview::focus_lift::default_power); });

    Settings enabled = defaults;
    enabled.focus_lift_enabled = true;
    assert(!same_settings(defaults, enabled));
    enabled = defaults; enabled.focus_brightness += .01f;
    assert(!same_settings(defaults, enabled));
    enabled = defaults; enabled.focus_lift_strength += .01f;
    assert(!same_settings(defaults, enabled));
    enabled = defaults; enabled.focus_corner_gain += .01f;
    assert(!same_settings(defaults, enabled));
    enabled = defaults; enabled.focus_lift_onset += .01f;
    assert(!same_settings(defaults, enabled));
    enabled = defaults; enabled.focus_lift_power += .01f;
    assert(!same_settings(defaults, enabled));
}

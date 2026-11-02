#include "DuoViewConfig.hpp"
#include "DuoViewDistanceCurve.hpp"
#include <cassert>
#include <cmath>
#include <limits>

int main() {
    namespace d = uevr::duoview;
    const d::DistanceSharpenCurve curve{};
    assert(d::valid_distance_sharpen_curve(curve));
    assert(d::distance_sharpen_strength(curve, 0.f, 2.f).strength == 5.f);
    assert(d::distance_sharpen_strength(curve, .5f, 2.f).strength == 5.f);
    assert(d::distance_sharpen_strength(curve, 10.f, 2.f).strength == 1.f);
    assert(d::distance_sharpen_strength(curve, 100.f, 2.f).strength == 1.f);
    assert(d::distance_sharpen_strength(curve, 5.25f, 2.f).strength == 3.f);
    auto linear = curve;
    linear.smoothstep = false;
    assert(std::abs(d::distance_sharpen_strength(linear, 2.875f, 2.f).strength - 4.f) < 0.0001f);
    assert(std::abs(d::distance_sharpen_strength(curve, 2.875f, 2.f).strength - 4.375f) < 0.0001f);
    auto inverse = curve;
    inverse.near_strength = 1.f;
    inverse.far_strength = 5.f;
    assert(d::distance_sharpen_strength(inverse, .5f, 2.f).strength == 1.f);
    assert(d::distance_sharpen_strength(inverse, 10.f, 2.f).strength == 5.f);

    const auto nan = std::numeric_limits<float>::quiet_NaN();
    const auto infinity = std::numeric_limits<float>::infinity();
    assert(!d::distance_sharpen_strength(curve, nan, 2.f).used_depth);
    assert(!d::distance_sharpen_strength(curve, infinity, 2.f).used_depth);
    assert(!d::distance_sharpen_strength(curve, -.01f, 2.f).used_depth);
    assert(d::distance_sharpen_strength(curve, nan, 2.f).strength == 2.f);
    assert(!d::valid_distance_sharpen_range(2.f, 2.f));
    assert(!d::valid_distance_sharpen_range(2.f, 1.f));
    assert(!d::valid_distance_sharpen_range(nan, 10.f));
    assert(!d::valid_distance_sharpen_range(0.f, infinity));
    assert(!d::valid_distance_sharpen_range(0.f, 1000.01f));

    d::ConfigLatch latch;
    d::Settings settings{};
    assert(latch.set_settings(settings));
    settings.distance_sharpen_enabled = true;
    settings.sharpen_near_strength = 5.f;
    settings.sharpen_far_strength = 1.f;
    settings.sharpen_near_m = .5f;
    settings.sharpen_far_m = 10.f;
    settings.sharpen_distance_smooth = true;
    assert(latch.set_settings(settings));
    assert(latch.for_frame({1,1}, 1000, 1000, {.5f,.5f})->settings.distance_sharpen_enabled);
    settings.sharpen_near_strength = 0.f;
    settings.sharpen_far_strength = 5.f;
    settings.sharpen_distance_smooth = false;
    assert(latch.set_settings(settings));
    assert(latch.for_frame({1,1}, 1000, 1000, {.5f,.5f})->settings.sharpen_near_strength == 5.f);
    const auto next = latch.for_frame({1,2}, 1000, 1000, {.5f,.5f});
    assert(next && next->settings.sharpen_near_strength == 0.f && !next->settings.sharpen_distance_smooth);

    auto bad = settings;
    bad.sharpen_far_m = bad.sharpen_near_m;
    assert(!latch.set_settings(bad));
    auto reconciled = d::reconcile_ui_settings(bad, settings);
    assert(reconciled.rejected & d::reject_sharpen_distance);
    assert(reconciled.settings.sharpen_near_m == settings.sharpen_near_m);
    assert(reconciled.settings.sharpen_far_m == settings.sharpen_far_m);

    bad = settings;
    bad.sharpen_near_strength = nan;
    assert(!latch.set_settings(bad));
    reconciled = d::reconcile_ui_settings(bad, settings);
    assert(reconciled.rejected & d::reject_sharpen_near);
    assert(reconciled.settings.sharpen_near_strength == settings.sharpen_near_strength);
    assert(reconciled.settings.sharpen_far_strength == settings.sharpen_far_strength);

    bad = settings;
    bad.sharpen_far_strength = 5.01f;
    assert(!latch.set_settings(bad));
    reconciled = d::reconcile_ui_settings(bad, settings);
    assert(reconciled.rejected & d::reject_sharpen_far);

    bad = settings;
    bad.sharpen_near_m = infinity;
    assert(!latch.set_settings(bad));
    assert(d::reconcile_ui_settings(bad, settings).rejected & d::reject_sharpen_distance);
    return 0;
}

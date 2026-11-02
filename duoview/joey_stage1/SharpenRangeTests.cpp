#include "DuoViewConfig.hpp"
#include <cassert>
#include <cmath>
#include <limits>

int main() {
    namespace d = uevr::duoview;
    d::ConfigLatch latch;
    d::Settings settings;
    for (float strength : {0.f, 1.f, 2.f, 3.f, 5.f}) {
        settings.sharpen_strength = strength;
        assert(latch.set_settings(settings));
        const auto result = d::reconcile_ui_settings(settings, {});
        assert(!(result.rejected & d::reject_sharpen));
        assert(result.settings.sharpen_strength == strength);
    }
    for (float strength : {-0.01f, 5.01f, std::numeric_limits<float>::infinity(),
                           std::numeric_limits<float>::quiet_NaN()}) {
        settings.sharpen_strength = strength;
        assert(!latch.set_settings(settings));
        const auto result = d::reconcile_ui_settings(settings, {});
        assert(result.rejected & d::reject_sharpen);
        assert(result.settings.sharpen_strength == 0.f);
    }
    settings.sharpen_strength = 5.f;
    assert(latch.set_settings(settings));
    const auto frame = latch.for_frame({1, 1}, 1000, 1000, {.5f, .5f});
    assert(frame && frame->settings.sharpen_strength == 5.f);
    settings.sharpen_strength = 1.f;
    assert(latch.set_settings(settings));
    assert(latch.for_frame({1, 1}, 1000, 1000, {.5f, .5f})->settings.sharpen_strength == 5.f);
    assert(latch.for_frame({1, 2}, 1000, 1000, {.5f, .5f})->settings.sharpen_strength == 1.f);
}

#pragma once
#include <algorithm>
#include <cmath>

namespace uevr::quadview::focus_lift {
// Robust fit to 52,584 flat-gray sky samples. These are source-domain gain
// parameters, not an assertion about the game's underlying postprocess.
inline constexpr float default_corner_gain = 1.14799273f;
inline constexpr float default_onset = .46940367f;
inline constexpr float default_power = .92386647f;

struct Profile {
    float brightness{1.f}, strength{1.f};
    float corner_gain{default_corner_gain}, onset{default_onset}, power{default_power};
};

inline float gain(float u, float v, const Profile& p = {}) {
    const float x=2.f*u-1.f, y=2.f*v-1.f;
    const float r2=(std::clamp)((x*x+y*y)*.5f,0.f,1.f);
    const float t=(std::clamp)((r2-p.onset)/(1.f-p.onset),0.f,1.f);
    return p.brightness*(1.f+(p.corner_gain-1.f)*p.strength*std::pow(t,p.power));
}
} // namespace uevr::quadview::focus_lift

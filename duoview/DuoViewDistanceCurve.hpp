#pragma once
// V209: pure CPU reference for future fovea-only DLSS-depth sharpening.
// A depth value is camera-FORWARD distance in meters, not device Z.
// The compositor must not call this until source-frame/rect/projection are proven.
// No GPU texture, hook, allocation or rendering change is made here.
#include <algorithm>
#include <cmath>

namespace uevr::duoview {

struct DistanceSharpenCurve {
    float near_strength{5.f};
    float far_strength{1.f};
    float near_m{0.5f};
    float far_m{10.f};
    bool smoothstep{true};
};

inline bool valid_distance_sharpen_range(float near_m, float far_m) {
    return std::isfinite(near_m) && std::isfinite(far_m) &&
           near_m >= 0.f && far_m <= 1000.f && far_m > near_m;
}

inline bool valid_distance_sharpen_curve(const DistanceSharpenCurve& p) {
    return valid_distance_sharpen_range(p.near_m, p.far_m) &&
           std::isfinite(p.near_strength) && p.near_strength >= 0.f &&
           p.near_strength <= 5.f && std::isfinite(p.far_strength) &&
           p.far_strength >= 0.f && p.far_strength <= 5.f;
}

struct DistanceSharpenResult {
    float strength{};
    bool used_depth{}; // false means caller must report fixed-strength fallback.
};

inline DistanceSharpenResult distance_sharpen_strength(
    const DistanceSharpenCurve& p, float forward_m, float fixed_strength)
{
    if (!valid_distance_sharpen_curve(p) || !std::isfinite(forward_m) ||
        forward_m < 0.f || !std::isfinite(fixed_strength)) {
        return {fixed_strength, false};
    }
    float t = std::clamp((forward_m - p.near_m) / (p.far_m - p.near_m), 0.f, 1.f);
    if (p.smoothstep) t = t * t * (3.f - 2.f * t);
    return {p.near_strength + (p.far_strength - p.near_strength) * t, true};
}
} // namespace uevr::duoview

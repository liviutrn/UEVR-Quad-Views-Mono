#pragma once
// B318: one immutable, VERTICAL-ONLY source-camera fit per OpenXR generation.
// The headset/output and gaze stay in logical symmetric UV. Unreal's
// periphery renders a smaller asymmetric source; the fovea retains its old
// angular density. Stereo warp samples source UV and returns logical UV for
// seam/fovea compositing. No horizontal fit until no-fold bounds are proven.
#include "DuoViewGeometry.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <optional>

namespace uevr::duoview {

struct SourceFit {
    float v0{0.f}, v1{1.f}; // visible source range in original centered-camera UV
    constexpr float span() const { return v1-v0; }
    bool valid() const {
        return std::isfinite(v0) && std::isfinite(v1) &&
            v0>=0.f && v1<=1.f && span()>=.5f && span()<=1.f;
    }
    bool active() const { return valid() && (v0>.00001f || v1<.99999f); }
    float to_source_v(float logical_v) const { return (logical_v-v0)/span(); }
    float to_logical_v(float source_v) const { return v0+span()*source_v; }
    uint32_t periphery_height(uint32_t old_height) const {
        if (!valid() || !old_height) return old_height;
        // Align the DLSS/Native view rectangle upward to eight pixels;
        // never grow past the baseline or collapse the view.
        const auto h=static_cast<uint32_t>(std::ceil(float(old_height)*span()));
        return (std::min)(old_height,(std::max)(8u,(h+7u)&~7u));
    }
};

// MonoRenderingPolicy::geometry already rotated the right eye's calibrated
// frustum into the same left-optical basis as the center Unreal camera.
inline SourceFit fit_vertical_source(
    const std::array<std::array<float,4>,2>& bounds, float guard=.02f) {
    if (!std::isfinite(guard) || guard<.015f || guard>.06f) return {};
    for(const auto& b:bounds)
        if (!std::isfinite(b[2]) || !std::isfinite(b[3]) ||
            b[2]<0.f || b[3]>1.f || b[3]<=b[2]) return {};
    const float min_v=(std::min)(bounds[0][2],bounds[1][2]);
    const float max_v=(std::max)(bounds[0][3],bounds[1][3]);
    // Snap the fit outward to stable 1/128 increments; the same answer is
    // frozen for the entire generation to prevent gaze-driven reallocations.
    const float top=(std::max)(0.f,std::floor((min_v-guard)*128.f)/128.f);
    const float bottom=(std::min)(1.f,std::ceil((max_v+guard)*128.f)/128.f);
    SourceFit f{top,bottom};
    // Avoid tiny savings whose viewport alignment costs more than they save.
    return f.valid() && f.span()<=.97f ? f : SourceFit{};
}

inline bool apply_source_fit_projection(std::array<float,16>& p, SourceFit fit) {
    if (!fit.valid() || !std::isfinite(p[5]) || p[5]<=0.f) return false;
    const float inv=1.f/fit.span();
    const float shift=1.f-inv+2.f*fit.v0*inv;
    // Column-major GLM/D3D perspective. This changes the actual Unreal
    // camera clip plane before source view rendering, not XR submission.
    // Reversed-Z depth row and w remain untouched.
    for(unsigned col=0; col<4; ++col) {
        const auto y=col*4+1u, w=col*4+3u;
        p[y]=p[y]*inv+p[w]*shift;
        if (!std::isfinite(p[y])) return false;
    }
    return true;
}

inline Rect fitted_periphery_rect(const Rect& source, SourceFit fit) {
    Rect r=source;
    r.height=fit.periphery_height(source.height);
    return r;
}
} // namespace uevr::duoview

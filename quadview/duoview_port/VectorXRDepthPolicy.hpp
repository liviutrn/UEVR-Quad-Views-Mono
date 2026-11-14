#pragma once
// DuoView <-> VectorXR: all-or-nothing depth packet admission.
// Pure C++ to make generation, geometry, and availability gates testable.
#include <array>
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace uevr::duoview::xrdepth {
struct Rect {
    int32_t x{}, y{}, w{}, h{};
    bool valid() const { return x >= 0 && y >= 0 && w > 0 && h > 0; }
    bool operator==(const Rect&) const = default;
};
struct Image {
    uint64_t swapchain{}, generation{};
    uint32_t slice{}, samples{};
    Rect rect{};
};
struct View {
    // Frozen OpenXR pose (position xyz, orientation xyzw) and FOV angles.
    std::array<float,7> pose{};
    std::array<float,4> fov{};
    bool operator==(const View&) const = default;
};
struct Eye {
    uint64_t frame{}, source{}, output{};
    Image color{}, depth{};
    View render_pose{}, submit_pose{};
    bool selected_final_color_uv{}, selected_background_fill{};
    bool depth_written{}, copy_queued{}, released{}, state_restored{};
    bool sampleable{}, supported_format{};
};
struct Packet {
    uint64_t frame{}, source{}, output{}, color_generation{}, depth_generation{};
    bool enabled{}, depth_extension{}, holding_color{};
    float near_m{}, far_m{}, min_depth{}, max_depth{1.f};
    std::array<Eye,2> eye{};
};
enum class Decision : uint8_t {
    Attach, Disabled, NoExtension, HeldColor, BadEncoding,
    Stale, Generation, Pose, RectMismatch, BadSwapchain, MissingEye, NotReleased
};
inline const char* reason(Decision d) {
    switch(d) {
    case Decision::Attach: return "both eyes depth attached";
    case Decision::Disabled: return "output disabled";
    case Decision::NoExtension: return "runtime lacks depth extension";
    case Decision::HeldColor: return "color frame reused/held";
    case Decision::BadEncoding: return "invalid reversed-Z metadata";
    case Decision::Stale: return "depth and color producer packet mismatch";
    case Decision::Generation: return "swapchain generation mismatch";
    case Decision::Pose: return "eye pose or FOV mismatch";
    case Decision::RectMismatch: return "rect or array slice mismatch";
    case Decision::BadSwapchain: return "depth format, sampling or MSAA unsupported";
    case Decision::MissingEye: return "depth missing for at least one eye";
    case Decision::NotReleased: return "depth copy/release/state incomplete";
    }
    return "unknown";
}
inline Decision admit(const Packet& p) {
    if(!p.enabled) return Decision::Disabled;
    if(!p.depth_extension) return Decision::NoExtension;
    if(p.holding_color) return Decision::HeldColor;
    if(!std::isfinite(p.near_m) || !std::isfinite(p.far_m) ||
       p.near_m<=p.far_m || p.far_m<=0.f ||
       p.min_depth!=0.f || p.max_depth!=1.f) return Decision::BadEncoding;
    if(!p.frame || !p.source || !p.output) return Decision::Stale;
    if(!p.color_generation || !p.depth_generation) return Decision::Generation;
    for(const Eye& e:p.eye) {
        if(e.frame!=p.frame || e.source!=p.source || e.output!=p.output)
            return Decision::Stale;
        if(e.color.generation!=p.color_generation ||
           e.depth.generation!=p.depth_generation) return Decision::Generation;
        if(!(e.render_pose==e.submit_pose)) return Decision::Pose;
        if(!e.color.rect.valid() || !e.depth.rect.valid() ||
           e.color.rect!=e.depth.rect || e.color.slice!=e.depth.slice)
            return Decision::RectMismatch;
        if(!e.color.swapchain || !e.depth.swapchain || e.color.samples!=1 ||
           e.depth.samples!=1 || !e.sampleable || !e.supported_format)
            return Decision::BadSwapchain;
        if(!e.selected_final_color_uv || !e.selected_background_fill ||
           !e.depth_written) return Decision::MissingEye;
        if(!e.copy_queued || !e.released || !e.state_restored)
            return Decision::NotReleased;
    }
    return Decision::Attach;
}

// Pass the INVERSE depth selected at the FINAL color source sample, after
// foreground conditioning, near-knee and any disocclusion fill selection.
// The submitted OpenXR eye poses keep physical IPD even if stereo strength<1.
// For infinite reversed Z, normalized depth = apparent inverse depth * 
// (engine near plane * OpenXR depth scale), i.e. strength * selected D.
inline float reversed_infinite(float selected_inv_engine, float near_engine,
                               float depth_scale, float stereo_strength) {
    if(!std::isfinite(selected_inv_engine) || !std::isfinite(near_engine) ||
       !std::isfinite(depth_scale) || !std::isfinite(stereo_strength) ||
       selected_inv_engine<0.f || near_engine<=0.f || depth_scale<=0.f ||
       stereo_strength<0.f || stereo_strength>1.f) return 0.f;
    return std::clamp(selected_inv_engine*near_engine*depth_scale*stereo_strength,
                      0.f,1.f);
}
inline float near_knee(float inverse, float limit) {
    if(!std::isfinite(inverse) || !std::isfinite(limit) || inverse<0.f) return 0.f;
    if(limit>0.f && inverse>limit) {
        const float over=inverse-limit;
        return limit+over/(1.f+over/limit);
    }
    return inverse;
}
} // namespace uevr::duoview::xrdepth

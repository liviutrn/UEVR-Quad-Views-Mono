#pragma once

#include "QuadViewGeometry.hpp"
#include "QuadViewFocusLift.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace uevr::quadview {

// Stereo-specific subset of the published v186.1 DuoView controls. Settings
// that only affect ID6's two-source capture or XR output path are not exposed
// here; every retained value is frozen with the ID7 source transaction.
struct Settings {
    float crop_width{.50f}, crop_height{.50f};
    float context_scale{.20f};
    float foveal_density{1.f};
    float feather_fraction{.08f};
    float sharpen_strength{1.f};
    bool focus_lift_enabled{false};
    float focus_brightness{1.f};
    float focus_lift_strength{1.f};
    float focus_corner_gain{focus_lift::default_corner_gain};
    float focus_lift_onset{focus_lift::default_onset};
    float focus_lift_power{focus_lift::default_power};
    uint32_t seam_mode{0}; // Off=0, Manual=1, Adaptive=2
    float seam_strength{.85f};
    float seam_max_gain{.20f};
    float seam_brightness_ev{};
    float seam_color_strength{.5f};
    float seam_local_strength{.5f};
    float seam_radius_px{120.f};
    float seam_transition_px{};
    bool seam_debug{};
    bool gpu_timing{};
    bool debug_border{};
    bool eye_tracked{true};
    uint32_t diagnostic_view{}; // 0 composite, 1 context, 2 focus, 3 layout colors
    bool stabilize_crop{true};
    float guard_fraction{.05f};
    uint32_t gaze_quant_pixels{2};
    int32_t gaze_hold_ms{350};
    int32_t gaze_reacquire_samples{2};
    float gaze_offset_u{}, gaze_offset_v{};
    float gaze_micro_gain{};
    float gaze_breakout_radius{.035f};
    float gaze_still_radius{.008f};
    uint32_t gaze_relock_samples{3};
};

enum Reject : uint32_t {
    reject_width=1u<<0, reject_height=1u<<1, reject_context=1u<<2,
    reject_density=1u<<3, reject_feather=1u<<4, reject_sharpen=1u<<5,
    reject_diagnostic=1u<<6, reject_guard=1u<<7, reject_quant=1u<<8,
    reject_hold=1u<<9, reject_reacquire=1u<<10, reject_offset_u=1u<<11,
    reject_offset_v=1u<<12, reject_micro=1u<<13, reject_breakout=1u<<14,
    reject_still=1u<<15, reject_relock=1u<<16
};

inline constexpr uint32_t reject_focus_lift=1u<<20;
inline constexpr uint32_t reject_seam=1u<<21;

struct Reconciled {
    Settings settings{};
    uint32_t rejected{};
    bool dimension_fallback{};
};

inline Reconciled reconcile_settings(const Settings& requested, const Settings& current,
                                    uint32_t output_width, uint32_t output_height) {
    Reconciled result{current, 0, false};
    auto& out = result.settings;
    const auto valid = [](float value, float lo, float hi) {
        return std::isfinite(value) && value >= lo && value <= hi;
    };
    const auto valid_quality = [=](const Settings& value) {
        return make_layout(output_width, output_height, value.crop_width, value.crop_height,
            value.context_scale, value.foveal_density).has_value();
    };

    const bool previous_quality_invalid=!valid_quality(out);
    if (previous_quality_invalid) {
        out.crop_width=.50f;
        out.crop_height=.50f;
        out.context_scale=.20f;
        out.foveal_density=1.f;
        result.dimension_fallback=true;
        result.rejected|=reject_width|reject_height|reject_context|reject_density;
        if (!valid_quality(out)) {
            out.crop_width=.05f;
            out.crop_height=.05f;
            out.context_scale=.05f;
            out.foveal_density=.25f;
        }
    }

    if (valid_quality(requested)) {
        out.crop_width=requested.crop_width;
        out.crop_height=requested.crop_height;
        out.context_scale=requested.context_scale;
        out.foveal_density=requested.foveal_density;
        result.dimension_fallback=false;
        result.rejected&=~(reject_width|reject_height|reject_context|reject_density);
    } else {
        const auto quality_field = [&](float value, float lo, float hi,
                                       uint32_t mask, float Settings::* field) {
            Settings attempt=out;
            attempt.*field=value;
            if (valid(value,lo,hi) && valid_quality(attempt)) {
                out.*field=value;
                result.rejected&=~mask;
            } else result.rejected|=mask;
        };
        quality_field(requested.crop_width,.05f,1.f,reject_width,&Settings::crop_width);
        quality_field(requested.crop_height,.05f,1.f,reject_height,&Settings::crop_height);
        quality_field(requested.foveal_density,.25f,4.f,reject_density,&Settings::foveal_density);
        quality_field(requested.context_scale,.05f,.50f,reject_context,&Settings::context_scale);
        result.dimension_fallback=previous_quality_invalid;
    }

    out.debug_border=requested.debug_border;
    out.gpu_timing=requested.gpu_timing;
    out.eye_tracked=requested.eye_tracked;
    out.stabilize_crop=requested.stabilize_crop;
    out.focus_lift_enabled=requested.focus_lift_enabled;
    out.seam_debug=requested.seam_debug;
    const auto scalar = [&](float value,float lo,float hi,uint32_t mask,float Settings::* field) {
        if (valid(value,lo,hi)) out.*field=value;
        else result.rejected|=mask;
    };
    const auto integer = [&](int32_t value,int32_t lo,int32_t hi,uint32_t mask,int32_t Settings::* field) {
        if (value>=lo && value<=hi) out.*field=value;
        else result.rejected|=mask;
    };
    const auto unsigned_integer = [&](uint32_t value,uint32_t lo,uint32_t hi,uint32_t mask,uint32_t Settings::* field) {
        if (value>=lo && value<=hi) out.*field=value;
        else result.rejected|=mask;
    };
    scalar(requested.feather_fraction,0.f,.45f,reject_feather,&Settings::feather_fraction);
    scalar(requested.sharpen_strength,0.f,2.f,reject_sharpen,&Settings::sharpen_strength);
    scalar(requested.focus_brightness,.8f,1.3f,reject_focus_lift,&Settings::focus_brightness);
    scalar(requested.focus_lift_strength,0.f,2.f,reject_focus_lift,&Settings::focus_lift_strength);
    scalar(requested.focus_corner_gain,1.f,1.5f,reject_focus_lift,&Settings::focus_corner_gain);
    scalar(requested.focus_lift_onset,0.f,.9f,reject_focus_lift,&Settings::focus_lift_onset);
    scalar(requested.focus_lift_power,.5f,3.f,reject_focus_lift,&Settings::focus_lift_power);
    scalar(requested.seam_strength,0.f,1.f,reject_seam,&Settings::seam_strength);
    scalar(requested.seam_max_gain,.01f,.5f,reject_seam,&Settings::seam_max_gain);
    scalar(requested.seam_brightness_ev,-.5f,.5f,reject_seam,&Settings::seam_brightness_ev);
    scalar(requested.seam_color_strength,0.f,1.f,reject_seam,&Settings::seam_color_strength);
    scalar(requested.seam_local_strength,0.f,1.f,reject_seam,&Settings::seam_local_strength);
    scalar(requested.seam_radius_px,16.f,512.f,reject_seam,&Settings::seam_radius_px);
    scalar(requested.seam_transition_px,0.f,64.f,reject_seam,&Settings::seam_transition_px);
    unsigned_integer(requested.seam_mode,0u,2u,reject_seam,&Settings::seam_mode);
    scalar(requested.guard_fraction,0.f,.05f,reject_guard,&Settings::guard_fraction);
    scalar(requested.gaze_offset_u,-.25f,.25f,reject_offset_u,&Settings::gaze_offset_u);
    scalar(requested.gaze_offset_v,-.25f,.25f,reject_offset_v,&Settings::gaze_offset_v);
    scalar(requested.gaze_micro_gain,0.f,1.f,reject_micro,&Settings::gaze_micro_gain);
    unsigned_integer(requested.diagnostic_view,0u,3u,reject_diagnostic,&Settings::diagnostic_view);
    unsigned_integer(requested.gaze_quant_pixels,0u,16u,reject_quant,&Settings::gaze_quant_pixels);
    unsigned_integer(requested.gaze_relock_samples,1u,10u,reject_relock,&Settings::gaze_relock_samples);
    integer(requested.gaze_hold_ms,50,2000,reject_hold,&Settings::gaze_hold_ms);
    integer(requested.gaze_reacquire_samples,1,4,reject_reacquire,&Settings::gaze_reacquire_samples);

    const bool valid_breakout=valid(requested.gaze_breakout_radius,.005f,.25f);
    const bool valid_still=valid(requested.gaze_still_radius,0.f,.05f);
    if (valid_breakout && valid_still && requested.gaze_still_radius<requested.gaze_breakout_radius) {
        out.gaze_breakout_radius=requested.gaze_breakout_radius;
        out.gaze_still_radius=requested.gaze_still_radius;
    } else {
        if (valid_breakout && out.gaze_still_radius<requested.gaze_breakout_radius)
            out.gaze_breakout_radius=requested.gaze_breakout_radius;
        else result.rejected|=reject_breakout;
        if (valid_still && requested.gaze_still_radius<out.gaze_breakout_radius)
            out.gaze_still_radius=requested.gaze_still_radius;
        else result.rejected|=reject_still;
    }
    return result;
}

inline bool same_settings(const Settings& a, const Settings& b) {
    return a.crop_width==b.crop_width && a.crop_height==b.crop_height &&
        a.context_scale==b.context_scale && a.foveal_density==b.foveal_density &&
        a.feather_fraction==b.feather_fraction && a.sharpen_strength==b.sharpen_strength &&
        a.focus_lift_enabled==b.focus_lift_enabled && a.focus_brightness==b.focus_brightness &&
        a.focus_lift_strength==b.focus_lift_strength && a.focus_corner_gain==b.focus_corner_gain &&
        a.focus_lift_onset==b.focus_lift_onset && a.focus_lift_power==b.focus_lift_power &&
        a.seam_mode==b.seam_mode && a.seam_strength==b.seam_strength &&
        a.seam_max_gain==b.seam_max_gain && a.seam_brightness_ev==b.seam_brightness_ev &&
        a.seam_color_strength==b.seam_color_strength && a.seam_local_strength==b.seam_local_strength &&
        a.seam_radius_px==b.seam_radius_px && a.seam_transition_px==b.seam_transition_px &&
        a.seam_debug==b.seam_debug &&
        a.gpu_timing==b.gpu_timing &&
        a.debug_border==b.debug_border && a.eye_tracked==b.eye_tracked &&
        a.diagnostic_view==b.diagnostic_view && a.stabilize_crop==b.stabilize_crop &&
        a.guard_fraction==b.guard_fraction && a.gaze_quant_pixels==b.gaze_quant_pixels &&
        a.gaze_hold_ms==b.gaze_hold_ms && a.gaze_reacquire_samples==b.gaze_reacquire_samples &&
        a.gaze_offset_u==b.gaze_offset_u && a.gaze_offset_v==b.gaze_offset_v &&
        a.gaze_micro_gain==b.gaze_micro_gain && a.gaze_breakout_radius==b.gaze_breakout_radius &&
        a.gaze_still_radius==b.gaze_still_radius && a.gaze_relock_samples==b.gaze_relock_samples;
}

} // namespace uevr::quadview

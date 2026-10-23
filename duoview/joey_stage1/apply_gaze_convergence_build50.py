#!/usr/bin/env python3
"""Build 50 experimental gaze-convergence-driven OpenXR Mono eye alignment.
Safe first test: uses PSVR2 Toolkit vergence estimate, NOT Unreal scene depth.
A missing/invalid gaze sample falls back to the calibrated static percent.
Run after Build49; no changes to scene captures, foveation or shading.
"""
from pathlib import Path
import argparse

def once(s, old, new, label):
    n=s.count(old)
    if n != 1: raise RuntimeError(f"{label}: expected one anchor, found {n}")
    return s.replace(old, new, 1)

a=argparse.ArgumentParser()
a.add_argument("backend", type=Path)
root=a.parse_args().backend/"src"/"mods"
vr=root/"VR.hpp"
g=root/"vr"/"DuoViewPSVR2Gaze.hpp"
xr=root/"vr"/"runtimes"/"OpenXR.cpp"
xh=root/"vr"/"runtimes"/"OpenXR.hpp"

s=g.read_text(encoding="utf-8")
s=once(s, '    bool active() const { return active_.load(std::memory_order_acquire); }',
'''    bool active() const { return active_.load(std::memory_order_acquire); }
    // PSVR2 physiological vergence, NOT depth sampled from the game's Z buffer.
    // Stale/invalid/closed-eye data returns 0, never a misleading far target.
    float convergence_depth_m() const {
        const uint64_t tick = focus_tick_.load(std::memory_order_acquire);
        const uint64_t now = GetTickCount64();
        if (!tick || now < tick || now - tick > 100 ||
            !active_.load(std::memory_order_acquire)) return 0.f;
        const float z = focus_m_.load(std::memory_order_relaxed);
        return std::isfinite(z) && z >= .20f && z <= 30.f ? z : 0.f;
    }''',
'reader getter')
s=once(s,'        const bool invalid = fresh && !sample.has_value();',
'''        const bool invalid = fresh && !sample.has_value();
        if (fresh) {
            const float m = candidate.tracked.convergence_distance_mm * .001f;
            const bool distance_valid = sample.has_value() &&
                candidate.raw.convergence_distance_valid == Bool::yes &&
                std::isfinite(m) && m >= .20f && m <= 30.f;
            focus_m_.store(distance_valid ? m : 0.f, std::memory_order_relaxed);
            focus_tick_.store(distance_valid ? now : 0, std::memory_order_release);
        }''','convergence sample')
s=once(s,'    HMODULE module_{};',
'''    std::atomic<float> focus_m_{0.f};
    std::atomic<uint64_t> focus_tick_{0};
    HMODULE module_{};''','reader members')
g.write_text(s,encoding="utf-8",newline="")

s=vr.read_text(encoding="utf-8")
s=once(s,'    bool duoview_gaze_active() const { return m_duoview.settings().eye_tracked && m_duoview_gaze.active(); }',
'''    bool duoview_gaze_active() const { return m_duoview.settings().eye_tracked && m_duoview_gaze.active(); }
    float duoview_convergence_depth_m() const {
        return duoview_gaze_active() ? m_duoview_gaze.convergence_depth_m() : 0.f;
    }''','expose single-reader depth')
s=once(s,'''        const float saved_mono_eye_alignment_percent =
            m_openxr != nullptr ? m_openxr->mono_eye_alignment_percent->value() : 0.0f;''',
'''        const float saved_mono_eye_alignment_percent =
            m_openxr != nullptr ? m_openxr->mono_eye_alignment_percent->value() : 0.0f;
        const bool saved_depth_enabled =
            m_openxr != nullptr && m_openxr->mono_gaze_depth_enabled->value();
        const float saved_depth_near_m = m_openxr ? m_openxr->mono_gaze_depth_near_m->value() : 0.5f;
        const float saved_depth_far_m = m_openxr ? m_openxr->mono_gaze_depth_far_m->value() : 10.f;
        const float saved_depth_near_percent = m_openxr ? m_openxr->mono_gaze_depth_near_percent->value() : -2.f;
        const float saved_depth_far_percent = m_openxr ? m_openxr->mono_gaze_depth_far_percent->value() : -1.25f;
        const float saved_depth_smoothing_ms = m_openxr ? m_openxr->mono_gaze_depth_smoothing_ms->value() : 180.f;''','reset snapshot')
s=once(s,'''            m_openxr->mono_eye_alignment_enabled->value() =
                valid_percent && saved_mono_eye_alignment_enabled;''',
'''            m_openxr->mono_eye_alignment_enabled->value() =
                valid_percent && saved_mono_eye_alignment_enabled;
            const bool valid_depth = std::isfinite(saved_depth_near_m) &&
                std::isfinite(saved_depth_far_m) &&
                saved_depth_near_m >= .2f && saved_depth_far_m <= 30.f &&
                saved_depth_far_m > saved_depth_near_m + .01f &&
                std::isfinite(saved_depth_near_percent) &&
                std::isfinite(saved_depth_far_percent) &&
                saved_depth_near_percent >= -3.f && saved_depth_near_percent <= 3.f &&
                saved_depth_far_percent >= -3.f && saved_depth_far_percent <= 3.f &&
                std::isfinite(saved_depth_smoothing_ms) &&
                saved_depth_smoothing_ms >= 0.f && saved_depth_smoothing_ms <= 1000.f;
            if (valid_depth) {
                m_openxr->mono_gaze_depth_near_m->value()=saved_depth_near_m;
                m_openxr->mono_gaze_depth_far_m->value()=saved_depth_far_m;
                m_openxr->mono_gaze_depth_near_percent->value()=saved_depth_near_percent;
                m_openxr->mono_gaze_depth_far_percent->value()=saved_depth_far_percent;
                m_openxr->mono_gaze_depth_smoothing_ms->value()=saved_depth_smoothing_ms;
            }
            m_openxr->mono_gaze_depth_enabled->value()=valid_depth && saved_depth_enabled;''',
'reset restore')
vr.write_text(s,encoding="utf-8",newline="")

s=xh.read_text(encoding="utf-8")
s=once(s,'''    const ModSlider::Ptr mono_eye_alignment_percent{
        ModSlider::create("OpenXR_MonoEyeAlignmentPercent", -3.0f, 3.0f, 0.0f) };''',
'''    const ModSlider::Ptr mono_eye_alignment_percent{
        ModSlider::create("OpenXR_MonoEyeAlignmentPercent", -3.0f, 3.0f, 0.0f) };
    // Default OFF: opt-in physiological vergence test for DuoView ID6.
    const ModToggle::Ptr mono_gaze_depth_enabled{
        ModToggle::create("OpenXR_MonoGazeDepthEnabled", false) };
    const ModSlider::Ptr mono_gaze_depth_near_m{
        ModSlider::create("OpenXR_MonoGazeDepthNearMeters", .2f, 10.f, .5f) };
    const ModSlider::Ptr mono_gaze_depth_far_m{
        ModSlider::create("OpenXR_MonoGazeDepthFarMeters", 1.f, 30.f, 10.f) };
    const ModSlider::Ptr mono_gaze_depth_near_percent{
        ModSlider::create("OpenXR_MonoGazeDepthNearPercent", -3.f, 3.f, -2.f) };
    const ModSlider::Ptr mono_gaze_depth_far_percent{
        ModSlider::create("OpenXR_MonoGazeDepthFarPercent", -3.f, 3.f, -1.25f) };
    const ModSlider::Ptr mono_gaze_depth_smoothing_ms{
        ModSlider::create("OpenXR_MonoGazeDepthSmoothMs", 0.f, 1000.f, 180.f) };
    float mono_gaze_smoothed_percent{};
    uint64_t mono_gaze_smoothed_tick{};
    bool mono_gaze_smoothed_valid{};''','XR options')
s=once(s,'''        *mono_eye_alignment_enabled,
        *mono_eye_alignment_percent,
        *ignore_vd_checks,''',
'''        *mono_eye_alignment_enabled,
        *mono_eye_alignment_percent,
        *mono_gaze_depth_enabled,
        *mono_gaze_depth_near_m,
        *mono_gaze_depth_far_m,
        *mono_gaze_depth_near_percent,
        *mono_gaze_depth_far_percent,
        *mono_gaze_depth_smoothing_ms,
        *ignore_vd_checks,''','persistence list')
xh.write_text(s,encoding="utf-8",newline="")

s=xr.read_text(encoding="utf-8")
s=once(s,'''                if (ImGui::Button("Reset Mono Eye Shift to Zero")) {
                    mono_eye_alignment_percent->value() = 0.0f;
                }''',
'''                if (ImGui::Button("Reset Mono Eye Shift to Zero")) {
                    mono_eye_alignment_percent->value() = 0.0f;
                }
                if (VR::get()->is_using_duoview_mono()) {
                    mono_gaze_depth_enabled->draw("DuoView Adaptive Gaze Shift (EXPERIMENTAL)");
                    if (mono_gaze_depth_enabled->value()) {
                        mono_gaze_depth_near_m->draw("Near vergence distance (m)");
                        mono_gaze_depth_near_percent->draw("Shift at near distance (%)");
                        mono_gaze_depth_far_m->draw("Far vergence distance (m)");
                        mono_gaze_depth_far_percent->draw("Shift at far distance (%)");
                        mono_gaze_depth_smoothing_ms->draw("Shift smoothing (ms)");
                        const float gaze_m=VR::get()->duoview_convergence_depth_m();
                        ImGui::Text("PSVR2 vergence: %.2f m (%s); applied shift %.3f%%",
                            gaze_m,gaze_m > 0.f ? "valid" : "invalid/fallback",
                            mono_gaze_smoothed_valid ? mono_gaze_smoothed_percent :
                                mono_eye_alignment_percent->value());
                        ImGui::TextWrapped("Uses eye vergence, NOT Unreal scene Z depth. "
                            "On gaze loss returns to the static Mono Eye Alignment percent "
                            "(the centered view). No extra rendering. Configurable depth "
                            "anchors interpolate the full image shift. Start gently.");
                    }
                }''','XR UI')
s=once(s,'''                const float total_percent = mono_eye_alignment_percent->value();
                const auto& fov = projection_layer_views[i].fov;''',
'''                const float baseline_percent = mono_eye_alignment_percent->value();
                float total_percent = baseline_percent;
                const bool adaptive_enabled = vr->is_using_duoview_mono() &&
                    mono_gaze_depth_enabled->value();
                if (adaptive_enabled) {
                    // Update once for the binocular pair, never separately for each eye.
                    if (i == 0 || !mono_gaze_smoothed_valid) {
                        const float near_m=mono_gaze_depth_near_m->value();
                        const float far_m=mono_gaze_depth_far_m->value();
                        const float near_pct=mono_gaze_depth_near_percent->value();
                        const float far_pct=mono_gaze_depth_far_percent->value();
                        const float smoothing=mono_gaze_depth_smoothing_ms->value();
                        const float gaze=vr->duoview_convergence_depth_m();
                        float target=baseline_percent;
                        const bool valid=std::isfinite(near_m) && std::isfinite(far_m) &&
                            near_m >= .2f && far_m <= 30.f && far_m > near_m+.01f &&
                            std::isfinite(near_pct) && std::abs(near_pct)<=3.f &&
                            std::isfinite(far_pct) && std::abs(far_pct)<=3.f &&
                            std::isfinite(smoothing) && smoothing>=0.f && smoothing<=1000.f;
                        if (valid && gaze >= .2f && std::isfinite(gaze)) {
                            const float t=std::clamp((gaze-near_m)/(far_m-near_m),0.f,1.f);
                            target=near_pct+(far_pct-near_pct)*t;
                        }
                        const uint64_t now=GetTickCount64();
                        if (!mono_gaze_smoothed_valid || now<mono_gaze_smoothed_tick ||
                            !std::isfinite(mono_gaze_smoothed_percent)) {
                            mono_gaze_smoothed_percent=baseline_percent;
                            mono_gaze_smoothed_valid=true;
                        }
                        const float delta=static_cast<float>(std::min<uint64_t>(
                            now-mono_gaze_smoothed_tick,250));
                        const float a=smoothing<=0.f ? 1.f : 1.f-std::exp(-delta/smoothing);
                        mono_gaze_smoothed_percent += a*(target-mono_gaze_smoothed_percent);
                        mono_gaze_smoothed_percent=std::clamp(
                            mono_gaze_smoothed_percent,-3.f,3.f);
                        mono_gaze_smoothed_tick=now;
                    }
                    total_percent=mono_gaze_smoothed_percent;
                } else {
                    mono_gaze_smoothed_valid=false;
                    mono_gaze_smoothed_tick=0;
                }
                const auto& fov = projection_layer_views[i].fov;''',
'adaptive submit shift')
xr.write_text(s,encoding="utf-8",newline="")
print("Build50: adaptive PSVR2 vergence-only DuoView alignment, default OFF, safe static fallback.")
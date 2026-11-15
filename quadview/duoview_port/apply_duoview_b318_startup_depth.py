#!/usr/bin/env python3
"""B318: stage saved synthetic stereo behind a visible mono frame; fix startup XR depth allocation.
Run AFTER M8 and M9 overlays. All edits are guarded and only touch ID6."""
import argparse
from pathlib import Path
from apply_duoview_b40_pipeline import patch


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("backend",type=Path)
    args=ap.parse_args()
    mods=args.backend/"src/mods"
    patch(mods/"VR.hpp",[
        ("B318 startup fields", 
         "    std::atomic<uint64_t> m_duoview_draw_serial{};",
         """    // B318: transient, unsaved startup gate. The persisted stereo toggle is never modified.
    std::atomic<uint64_t> m_duo_bootstrap_generation{0};
    std::atomic<uint64_t> m_duo_mono_visible_generation{0};
    std::atomic<bool> m_duo_stereo_bootstrap_ready{false};
    std::atomic<uint64_t> m_duoview_draw_serial{};"""),
        ("B318 stereo startup draw gate",
         """    void duoview_start_draw() {
        m_duoview_draw_serial.fetch_add(1, std::memory_order_acq_rel);""",
         """    void duoview_start_draw() {
        const auto generation = mono_generation();
        if (m_duo_bootstrap_generation.exchange(generation, std::memory_order_acq_rel) != generation) {
            // Any OpenXR/renderer generation change must first submit real mono pixels.
            m_duo_stereo_bootstrap_ready.store(false, std::memory_order_release);
            m_duo_mono_visible_generation.store(0, std::memory_order_release);
        }
        if (generation != 0 && !m_duo_stereo_bootstrap_ready.load(std::memory_order_acquire) &&
            m_duo_mono_visible_generation.load(std::memory_order_acquire) == generation) {
            m_duo_stereo_bootstrap_ready.store(true, std::memory_order_release);
            configure_duoview(); // Stage on the next immutable UE source frame; no mid-frame mutation.
        }
        m_duoview_draw_serial.fetch_add(1, std::memory_order_acq_rel);"""),
        ("B318 visible mono notifier",
         "    void duoview_abort(const char* reason);",
         """    void duoview_abort(const char* reason);
    // Called only after xrEndFrame succeeds with a visible, non-held ID6 mono scene.
    void note_duoview_first_visible_mono(uint64_t generation) {
        if (generation != 0 &&
            m_duo_bootstrap_generation.load(std::memory_order_acquire) == generation)
            m_duo_mono_visible_generation.store(generation, std::memory_order_release);
    }"""),
        ("B318 startup skip uses selected ID6, not active ID6",
         """        return m_duo_skip_depth->value() && is_duoview_renderer_active() &&
            !m_enable_depth->value() && !is_depth_enabled() &&""",
         """        // OpenXR allocates chains BEFORE ID6 is active. Use the resolved selected
        // or requested mode, and do not skip when any runtime-depth consumer exists.
        const bool id6_requested = is_using_duoview_mono() ||
            requested_rendering_method() == RenderingMethod::DUOVIEW_MONO;
        return m_duo_skip_depth->value() && id6_requested &&
            !m_enable_depth->value() && !is_depth_enabled() &&"""),
        ("B318 skip default on",
         'ModToggle::create(generate_name("DuoViewSkipDepthSwapchain"), false)',
         'ModToggle::create(generate_name("DuoViewSkipDepthSwapchain"), true)'),
        ("B318 taper default 0",
         'ModSlider::create(generate_name("DuoM24VerticalTaper"),0.f,8.f,2.f)',
         'ModSlider::create(generate_name("DuoM24VerticalTaper"),0.f,8.f,0.f)'),
    ])
    patch(mods/"vr/DuoViewConfig.hpp", [
        ("B318 config taper 0",
         "    float m24_vertical_taper{2.f};",
         "    float m24_vertical_taper{0.f};"),
        # Preserve M1's proven stereo invariant: only mono may submit shared-eye.
    ])
    patch(mods/"VR.cpp",[
        ("B318 guard requested stereo until first visible mono",
         ".synthetic_stereo=m_duo_stereo->value(),",
         """.synthetic_stereo=m_duo_stereo->value() &&
            m_duo_stereo_bootstrap_ready.load(std::memory_order_acquire),"""),
        ("B318 cold boot uses PLAIN mono even when the saved stereo profile has mono distance fade enabled",
         ".m24_distance_fade=m_duo_m24_distance->value(),",
         """.m24_distance_fade=m_duo_m24_distance->value() &&
            (!m_duo_stereo->value() ||
             m_duo_stereo_bootstrap_ready.load(std::memory_order_acquire)),"""),
        ("B318 restore taper 0",
         "m_duo_m24_vertical->value()=2.f;",
         "m_duo_m24_vertical->value()=0.f;"),
        ("B318 restore skip on",
         "m_duo_skip_depth->value()=false; // v208d",
         "m_duo_skip_depth->value()=true; // B318"),
    ])
    patch(mods/"vr/runtimes/OpenXR.cpp", [
        ("B318 acknowledge an ACTUAL OpenXR mono submit",
         """        if (result==XR_SUCCESS && !projection_layer_views.empty()) {
            if (duoview_holding) ++duoview_hold_submits;""",
         """        if (result==XR_SUCCESS && !projection_layer_views.empty()) {
            if (!duoview_holding && !submit_state.duoview_stereo_output) {
                vr->note_duoview_first_visible_mono(vr->mono_generation());
                SPDLOG_INFO_ONCE("[DuoView][Startup] First real mono scene submitted; stereo may arm at next UE draw");
            }
            if (duoview_holding) ++duoview_hold_submits;"""),
    ])
    # B318 must not force the same XR image on left/right when M1 stereo is active.
    # Fail the release build if a future overlay inadvertently regresses this.
    config_text=(mods/"vr/DuoViewConfig.hpp").read_text(encoding="utf-8")
    if "out.shared_eye_image=!out.synthetic_stereo && requested.shared_eye_image;" not in config_text:
        raise RuntimeError("B318 requires separate-eye images for synthetic stereo")
    print("B318 startup/depth: ID6 mono-first activation, M1 fallback preserved, early XR depth skip and taper=0")


if __name__=="__main__":
    main()

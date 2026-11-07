#!/usr/bin/env python3
"""B30: add persisted seam matching settings and controls after B28+B29 overlays.

This patch deliberately adds no compositor constants or shader behavior. It
publishes bounded settings for the B30 compositor implementation.
"""
from pathlib import Path
import sys


def once(source, before, after, name):
    count = source.count(before)
    if count != 1:
        raise RuntimeError(f'B30 {name}: expected one anchor, got {count}: {before[:100]!r}')
    return source.replace(before, after, 1)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: apply_triview_b30_controls.py <backend>')
    root = Path(sys.argv[1]) / 'src/mods'
    files = {}

    p = root/'VR.hpp'
    s = p.read_text(encoding='utf-8')
    s = once(s,
        '    static const inline std::vector<std::string> s_desktop_mirror_mode_names{',
        '    static const inline std::vector<std::string> s_quadview_seam_mode_names{ "Off", "Manual", "Adaptive" };\n'
        '    static const inline std::vector<std::string> s_desktop_mirror_mode_names{', 'VR.hpp seam mode names')
    s = once(s,
        '    const ModSlider::Ptr m_quadview_feather{ModSlider::create(generate_name("QuadViewFeather"), 0.f, .45f, .08f)};\n',
        '    const ModSlider::Ptr m_quadview_feather{ModSlider::create(generate_name("QuadViewFeather"), 0.f, .45f, .08f)};\n'
        '    const ModCombo::Ptr m_quadview_seam_mode{ModCombo::create(generate_name("QuadViewSeamMode"), s_quadview_seam_mode_names, 0)};\n'
        '    const ModSlider::Ptr m_quadview_seam_strength{ModSlider::create(generate_name("QuadViewSeamStrength"), 0.f, 1.f, .85f)};\n'
        '    const ModSlider::Ptr m_quadview_seam_max_gain{ModSlider::create(generate_name("QuadViewSeamMaxGain"), .01f, .5f, .20f)};\n'
        '    const ModSlider::Ptr m_quadview_seam_brightness_ev{ModSlider::create(generate_name("QuadViewSeamBrightnessEV"), -.5f, .5f, 0.f)};\n'
        '    const ModSlider::Ptr m_quadview_seam_color_strength{ModSlider::create(generate_name("QuadViewSeamColorStrength"), 0.f, 1.f, .5f)};\n'
        '    const ModSlider::Ptr m_quadview_seam_local_strength{ModSlider::create(generate_name("QuadViewSeamLocalStrength"), 0.f, 1.f, .5f)};\n'
        '    const ModSlider::Ptr m_quadview_seam_radius_px{ModSlider::create(generate_name("QuadViewSeamRadiusPixels"), 16.f, 512.f, 120.f)};\n'
        '    const ModSlider::Ptr m_quadview_seam_transition_px{ModSlider::create(generate_name("QuadViewSeamTransitionPixels"), 0.f, 64.f, 0.f)};\n'
        '    const ModToggle::Ptr m_quadview_seam_debug{ModToggle::create(generate_name("QuadViewSeamDebug"), false)};\n',
        'VR.hpp seam controls')
    s = once(s,
        '    const ModSlider::Ptr m_quadview_feather{ModSlider::create(generate_name("QuadViewFeather"), 0.f, .45f, .08f)};\n',
        '    const ModSlider::Ptr m_quadview_feather{ModSlider::create(generate_name("QuadViewFeather"), 0.f, .45f, .08f)};\n'
        '    const ModToggle::Ptr m_quadview_focus_lift_enabled{ModToggle::create(generate_name("QuadViewFocusBrightnessCorrection"), false)};\n'
        '    const ModSlider::Ptr m_quadview_focus_center_ev{ModSlider::create(generate_name("QuadViewFocusCenterEV"), -.5f, .5f, 0.f)};\n'
        '    const ModSlider::Ptr m_quadview_focus_edge_ev{ModSlider::create(generate_name("QuadViewFocusEdgeLiftEV"), 0.f, 1.5f, .25f)};\n',
        'VR.hpp focus lift controls')
    s = once(s,
        '            *m_quadview_tri_view, *m_quadview_foveal_density, *m_quadview_feather,\n',
        '            *m_quadview_tri_view, *m_quadview_foveal_density, *m_quadview_feather,\n'
        '            *m_quadview_focus_lift_enabled, *m_quadview_focus_center_ev, *m_quadview_focus_edge_ev,\n'
        '            *m_quadview_seam_mode, *m_quadview_seam_strength, *m_quadview_seam_max_gain,\n'
        '            *m_quadview_seam_brightness_ev, *m_quadview_seam_color_strength,\n'
        '            *m_quadview_seam_local_strength, *m_quadview_seam_radius_px,\n'
        '            *m_quadview_seam_transition_px, *m_quadview_seam_debug,\n',
        'VR.hpp saved options')
    files[p] = s

    p = root/'VR.cpp'
    s = p.read_text(encoding='utf-8')
    s = once(s,
        '                m_quadview_feather->draw("Context/focus blend feather");\n',
        '                m_quadview_feather->draw("Context/focus blend feather");\n'
        '                if (ImGui::TreeNode("Fovea brightness correction")) {\n'
        '                    ImGui::TextWrapped("Optional manual brightness compensation for the fovea, independent of seam matching. Edge and corner lift fades to zero at the center; it adds no blur. Default is off.");\n'
        '                    m_quadview_focus_lift_enabled->draw("Enable fovea brightness correction");\n'
        '                    if (m_quadview_focus_lift_enabled->value()) {\n'
        '                        m_quadview_focus_center_ev->draw("Fovea center exposure bias (EV)");\n'
        '                        m_quadview_focus_edge_ev->draw("Edge and corner lift (EV)");\n'
        '                    }\n'
        '                    ImGui::TreePop();\n'
        '                }\n',
        'VR.cpp independent focus lift UI')
    s = once(s,
        '                m_quadview_feather->draw("Context/focus blend feather");\n',
        '                m_quadview_feather->draw("Context/focus blend feather");\n'
        '                if (ImGui::TreeNode("Advanced Seam Matching")) {\n'
        '                    ImGui::TextWrapped("Seam matching adjusts color across the existing context/focus overlap. Off preserves the legacy blend. Manual applies a fixed exposure bias; Adaptive estimates per-eye gain. No camera or render target dimensions change.");\n'
        '                    m_quadview_seam_mode->draw("Mode");\n'
        '                    if (m_quadview_seam_mode->value()!=0) {\n'
        '                        m_quadview_seam_strength->draw("Correction strength");\n'
        '                        if (m_quadview_seam_mode->value()==1)\n'
        '                            m_quadview_seam_brightness_ev->draw("Manual global exposure bias (EV)");\n'
        '                        if (m_quadview_seam_mode->value()==2) {\n'
        '                            m_quadview_seam_max_gain->draw("Adaptive relative gain cap (+/-)");\n'
        '                            m_quadview_seam_color_strength->draw("Color matching (0=luma, 1=chroma and luma)");\n'
        '                            m_quadview_seam_local_strength->draw("Local boundary residual strength (0=off)");\n'
        '                            m_quadview_seam_radius_px->draw("Local residual fade radius (pixels)");\n'
        '                            ImGui::TextWrapped("Adaptive matching applies a global gain across the periphery, plus an optional locally fitted boundary residual that fades outward over this radius. It does not change fovea pixels.");\n'
        '                            m_quadview_seam_debug->draw("Show adaptive confidence diagnostic");\n'
        '                        }\n'
        '                        m_quadview_seam_transition_px->draw("Reserve existing rendered edge for transition (pixels)");\n'
        '                        ImGui::TextWrapped("A positive transition reserves part of the rendered focus edge for blending and moves the sharp interior inward; it adds no rendered pixels. At zero, matching uses the full focus crop.");\n'
        '                    }\n'
        '                    ImGui::TreePop();\n'
        '                }\n',
        'VR.cpp seam controls UI')
    s = once(s,
        '                    if (rejected&uevr::quadview::reject_sharpen_right_max) ImGui::TextUnformatted("Right sharpen max change rejected");\n',
        '                    if (rejected&uevr::quadview::reject_sharpen_right_max) ImGui::TextUnformatted("Right sharpen max change rejected");\n'
        '                    if (rejected&uevr::quadview::reject_seam) ImGui::TextUnformatted("One or more seam matching settings rejected");\n',
        'VR.cpp seam rejection')
    s = once(s,
        '            requested.feather_fraction=m_quadview_feather->value();\n',
        '            requested.feather_fraction=m_quadview_feather->value();\n'
        '            requested.seam_mode=static_cast<uint32_t>(m_quadview_seam_mode->value());\n'
        '            requested.seam_strength=m_quadview_seam_strength->value();\n'
        '            requested.seam_max_gain=m_quadview_seam_max_gain->value();\n'
        '            requested.seam_brightness_ev=m_quadview_seam_brightness_ev->value();\n'
        '            requested.seam_color_strength=m_quadview_seam_color_strength->value();\n'
        '            requested.seam_local_strength=m_quadview_seam_local_strength->value();\n'
        '            requested.seam_radius_px=m_quadview_seam_radius_px->value();\n'
        '            requested.seam_transition_px=m_quadview_seam_transition_px->value();\n'
        '            requested.seam_debug=m_quadview_seam_debug->value();\n',
        '            requested.seam_debug=m_quadview_seam_debug->value();\n'
        '            requested.focus_lift_enabled=m_quadview_focus_lift_enabled->value();\n'
        '            requested.focus_center_ev=m_quadview_focus_center_ev->value();\n'
        '            requested.focus_edge_ev=m_quadview_focus_edge_ev->value();\n',
        'VR.cpp seam setting copy')
    s = once(s,
        'm_quadview_gpu_timing->draw("GPU timing: QuadView raster (completed slot; excludes UE and source gather)");',
        'm_quadview_gpu_timing->draw("GPU timing: composite + seam analysis (completed slot; excludes UE/source gather)");',
        'VR.cpp total timing label')
    s = once(s,
        '                    const float value=quadview_gpu_ms();',
        '                    const float analysis=uevr::quadview::dx12::last_seam_analysis_milliseconds().load(std::memory_order_relaxed);\n'
        '                    if (analysis>=0.f) ImGui::Text("Last retired seam analysis: %.3f ms",analysis);\n'
        '                    const float value=quadview_gpu_ms();',
        'VR.cpp separate seam analysis timing')
    files[p] = s

    p = root/'vr/QuadViewSettings.hpp'
    s = p.read_text(encoding='utf-8')
    inherited_seam_contract = [
        '    uint32_t seam_mode{0}; // Off=0, Manual=1, Adaptive=2\n',
        '    float seam_strength{.85f};\n',
        '    float seam_max_gain{.20f};\n',
        '    float seam_brightness_ev{};\n',
        '    float seam_color_strength{.5f};\n',
        '    float seam_local_strength{.5f};\n',
        '    float seam_radius_px{120.f};\n',
        '    float seam_transition_px{}; // reserves existing rendered edge; adds no pixels\n',
        '    bool seam_debug{};\n',
        '    bool focus_lift_enabled{};\n',
        '    float focus_center_ev{};\n',
        '    float focus_edge_ev{.25f};\n',
        'inline constexpr uint32_t reject_seam=1u<<20;\n',
        '    scalar(requested.seam_strength,0.f,1.f,reject_seam,&Settings::seam_strength);\n',
        '    scalar(requested.seam_max_gain,.01f,.5f,reject_seam,&Settings::seam_max_gain);\n',
        '    scalar(requested.seam_brightness_ev,-.5f,.5f,reject_seam,&Settings::seam_brightness_ev);\n',
        '    scalar(requested.seam_color_strength,0.f,1.f,reject_seam,&Settings::seam_color_strength);\n',
        '    scalar(requested.seam_local_strength,0.f,1.f,reject_seam,&Settings::seam_local_strength);\n',
        '    scalar(requested.seam_radius_px,16.f,512.f,reject_seam,&Settings::seam_radius_px);\n',
        '    scalar(requested.seam_transition_px,0.f,64.f,reject_seam,&Settings::seam_transition_px);\n',
        '    scalar(requested.focus_center_ev,-.5f,.5f,reject_seam,&Settings::focus_center_ev);\n',
        '    scalar(requested.focus_edge_ev,0.f,1.5f,reject_seam,&Settings::focus_edge_ev);\n',
        '    out.focus_lift_enabled=requested.focus_lift_enabled;\n',
        '        a.focus_lift_enabled==b.focus_lift_enabled && a.focus_center_ev==b.focus_center_ev &&\n',
        '        a.focus_edge_ev==b.focus_edge_ev &&\n',
        '    unsigned_integer(requested.seam_mode,0u,2u,reject_seam,&Settings::seam_mode);\n',
        '        a.seam_mode==b.seam_mode && a.seam_strength==b.seam_strength &&\n',
        '        a.seam_color_strength==b.seam_color_strength && a.seam_local_strength==b.seam_local_strength &&\n',
        '        a.seam_radius_px==b.seam_radius_px && a.seam_transition_px==b.seam_transition_px &&\n',
    ]
    for line in inherited_seam_contract:
        if s.count(line) != 1:
            raise RuntimeError(f'B30 inherited seam setting expected exactly once, got {s.count(line)}: {line.strip()}')

    # Validate and prepare every transformed file before writing any of them.
    for path, content in files.items():
        path.write_text(content, encoding='utf-8', newline='\n')
    print('B30 controls: persisted Off/Manual/Adaptive seam settings, bounded validation, and UI overlay applied.')


if __name__ == '__main__':
    main()

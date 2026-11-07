#!/usr/bin/env python3
"""B30 focus-lift UI overlay for a corrected B29 generated backend.

The base QuadViewSettings.hpp is copied before these overlays. This script
therefore verifies its focus-lift contract instead of inserting duplicate
settings fields or validation code.
"""
from pathlib import Path
import sys


def once(source, before, after, label):
    count = source.count(before)
    if count != 1:
        raise RuntimeError(f'B30 focus lift {label}: expected one anchor, got {count}: {before[:100]!r}')
    return source.replace(before, after, 1)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: apply_triview_b30_focus_lift.py <backend>')
    root = Path(sys.argv[1]) / 'src/mods'
    files = {}

    p = root/'VR.hpp'
    s = p.read_text(encoding='utf-8')
    s = once(s,
        '    const ModSlider::Ptr m_quadview_feather{ModSlider::create(generate_name("QuadViewFeather"), 0.f, .45f, .08f)};\n',
        '    const ModSlider::Ptr m_quadview_feather{ModSlider::create(generate_name("QuadViewFeather"), 0.f, .45f, .08f)};\n'
        '    const ModToggle::Ptr m_quadview_focus_lift_enabled{ModToggle::create(generate_name("QuadViewFocusLiftEnabled"), true)};\n'
        '    const ModSlider::Ptr m_quadview_focus_brightness{ModSlider::create(generate_name("QuadViewFocusBrightness"), .8f, 1.3f, 1.f)};\n'
        '    const ModSlider::Ptr m_quadview_focus_lift_strength{ModSlider::create(generate_name("QuadViewFocusLiftStrength"), 0.f, 2.f, 1.f)};\n'
        '    const ModSlider::Ptr m_quadview_focus_corner_gain{ModSlider::create(generate_name("QuadViewFocusCornerGain"), 1.f, 1.5f, uevr::quadview::focus_lift::default_corner_gain)};\n'
        '    const ModSlider::Ptr m_quadview_focus_lift_onset{ModSlider::create(generate_name("QuadViewFocusLiftOnset"), 0.f, .9f, uevr::quadview::focus_lift::default_onset)};\n'
        '    const ModSlider::Ptr m_quadview_focus_lift_power{ModSlider::create(generate_name("QuadViewFocusLiftPower"), .5f, 3.f, uevr::quadview::focus_lift::default_power)};\n',
        'VR.hpp controls')
    s = once(s,
        '            *m_quadview_tri_view, *m_quadview_foveal_density, *m_quadview_feather,\n',
        '            *m_quadview_tri_view, *m_quadview_foveal_density, *m_quadview_feather,\n'
        '            *m_quadview_focus_lift_enabled, *m_quadview_focus_brightness, *m_quadview_focus_lift_strength,\n'
        '            *m_quadview_focus_corner_gain, *m_quadview_focus_lift_onset, *m_quadview_focus_lift_power,\n',
        'VR.hpp persisted options')
    files[p] = s

    p = root/'VR.cpp'
    s = p.read_text(encoding='utf-8')
    s = once(s,
        '                m_quadview_feather->draw("Context/focus blend feather");\n',
        '                m_quadview_feather->draw("Context/focus blend feather");\n'
        '                if (ImGui::TreeNode("Fovea brightness / anti-vignette")) {\n'
        '                    ImGui::TextWrapped("Manual brightness compensation for the foveas. Edge and corner lift fades toward the center without blur. The preset is calibrated from screenshots and may not match every runtime exactly.");\n'
        '                    if (ImGui::Button("Restore calibrated focus lift preset")) {\n'
        '                        m_quadview_focus_lift_enabled->value()=true;\n'
        '                        m_quadview_focus_brightness->value()=1.f;\n'
        '                        m_quadview_focus_lift_strength->value()=1.f;\n'
        '                        m_quadview_focus_corner_gain->value()=uevr::quadview::focus_lift::default_corner_gain;\n'
        '                        m_quadview_focus_lift_onset->value()=uevr::quadview::focus_lift::default_onset;\n'
        '                        m_quadview_focus_lift_power->value()=uevr::quadview::focus_lift::default_power;\n'
        '                    }\n'
        '                    m_quadview_focus_lift_enabled->draw("Enable fovea brightness correction");\n'
        '                    if (ImGui::TreeNode("Advanced focus lift shape")) {\n'
        '                        m_quadview_focus_brightness->draw("Fovea brightness multiplier (0.8-1.3)");\n'
        '                        m_quadview_focus_lift_strength->draw("Edge and corner lift strength (0-2)");\n'
        '                        m_quadview_focus_corner_gain->draw("Corner gain (1-1.5)");\n'
        '                        m_quadview_focus_lift_onset->draw("Lift onset (0-0.9) ");\n'
        '                        m_quadview_focus_lift_power->draw("Lift curve power (0.5-3)");\n'
        '                        ImGui::TreePop();\n'
        '                    }\n'
        '                    ImGui::TreePop();\n'
        '                }\n',
        'VR.cpp UI')
    s = once(s,
        '                    if (rejected&uevr::quadview::reject_sharpen_right_max) ImGui::TextUnformatted("Right sharpen max change rejected");\n',
        '                    if (rejected&uevr::quadview::reject_sharpen_right_max) ImGui::TextUnformatted("Right sharpen max change rejected");\n'
        '                    if (rejected&uevr::quadview::reject_focus_lift) ImGui::TextUnformatted("One or more focus brightness settings rejected");\n',
        'VR.cpp rejection status')
    s = once(s,
        '            requested.feather_fraction=m_quadview_feather->value();\n',
        '            requested.focus_lift_enabled=m_quadview_focus_lift_enabled->value();\n'
        '            requested.focus_brightness=m_quadview_focus_brightness->value();\n'
        '            requested.focus_lift_strength=m_quadview_focus_lift_strength->value();\n'
        '            requested.focus_corner_gain=m_quadview_focus_corner_gain->value();\n'
        '            requested.focus_lift_onset=m_quadview_focus_lift_onset->value();\n'
        '            requested.focus_lift_power=m_quadview_focus_lift_power->value();\n'
        '            requested.feather_fraction=m_quadview_feather->value();\n',
        'VR.cpp request copy')
    files[p] = s

    p = root/'vr/QuadViewSettings.hpp'
    settings = p.read_text(encoding='utf-8')
    contract = [
        '#include "QuadViewFocusLift.hpp"\n',
        '    bool focus_lift_enabled{false};\n',
        '    float focus_brightness{1.f};\n',
        '    float focus_lift_strength{1.f};\n',
        '    float focus_corner_gain{focus_lift::default_corner_gain};\n',
        '    float focus_lift_onset{focus_lift::default_onset};\n',
        '    float focus_lift_power{focus_lift::default_power};\n',
        'inline constexpr uint32_t reject_focus_lift=1u<<20;\n',
        '    out.focus_lift_enabled=requested.focus_lift_enabled;\n',
        '    scalar(requested.focus_brightness,.8f,1.3f,reject_focus_lift,&Settings::focus_brightness);\n',
        '    scalar(requested.focus_lift_strength,0.f,2.f,reject_focus_lift,&Settings::focus_lift_strength);\n',
        '    scalar(requested.focus_corner_gain,1.f,1.5f,reject_focus_lift,&Settings::focus_corner_gain);\n',
        '    scalar(requested.focus_lift_onset,0.f,.9f,reject_focus_lift,&Settings::focus_lift_onset);\n',
        '    scalar(requested.focus_lift_power,.5f,3.f,reject_focus_lift,&Settings::focus_lift_power);\n',
        '        a.focus_lift_enabled==b.focus_lift_enabled && a.focus_brightness==b.focus_brightness &&\n',
        '        a.focus_lift_strength==b.focus_lift_strength && a.focus_corner_gain==b.focus_corner_gain &&\n',
        '        a.focus_lift_onset==b.focus_lift_onset && a.focus_lift_power==b.focus_lift_power &&\n',
    ]
    for line in contract:
        if settings.count(line) != 1:
            raise RuntimeError(f'B30 focus lift inherited setting expected once, got {settings.count(line)}: {line.strip()}')

    helper = Path(__file__).with_name('QuadViewFocusLift.hpp').read_text(encoding='utf-8')
    for path, content in files.items():
        path.write_text(content, encoding='utf-8', newline='\n')
    (root/'vr/QuadViewFocusLift.hpp').write_text(helper, encoding='utf-8', newline='\n')
    print('B30 focus lift controls applied.')


if __name__ == '__main__':
    main()

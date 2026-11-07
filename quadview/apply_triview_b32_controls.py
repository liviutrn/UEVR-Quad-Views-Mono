#!/usr/bin/env python3
"""B32 controls added after B30 focus and seam overlays; exact guarded anchors."""
from pathlib import Path
import sys

def once(source, before, after, name):
    count=source.count(before)
    if count!=1:
        raise RuntimeError(f'B32 controls {name}: expected one anchor, got {count}: {before[:110]!r}')
    return source.replace(before,after,1)

def main():
    if len(sys.argv)!=2:
        raise SystemExit('Usage: apply_triview_b32_controls.py <backend>')
    root=Path(sys.argv[1])/'src/mods'
    paths={}
    p=root/'VR.hpp'
    s=p.read_text(encoding='utf-8')
    for a,b in (
        ('ModSlider::create(generate_name("QuadViewSeamStrength"), 0.f, 1.f, .85f)',
         'ModSlider::create(generate_name("QuadViewSeamStrength"), 0.f, 1.5f, 1.20f)'),
        ('ModSlider::create(generate_name("QuadViewSeamMaxGain"), .01f, .5f, .20f)',
         'ModSlider::create(generate_name("QuadViewSeamMaxGain"), .01f, .75f, .50f)'),
        ('ModSlider::create(generate_name("QuadViewSeamColorStrength"), 0.f, 1.f, .5f)',
         'ModSlider::create(generate_name("QuadViewSeamColorStrength"), 0.f, 1.f, .7f)'),
        ('ModSlider::create(generate_name("QuadViewSeamLocalStrength"), 0.f, 1.f, .5f)',
         'ModSlider::create(generate_name("QuadViewSeamLocalStrength"), 0.f, 1.f, .65f)'),
        ('ModSlider::create(generate_name("QuadViewSeamTransitionPixels"), 0.f, 64.f, 0.f)',
         'ModSlider::create(generate_name("QuadViewSeamTransitionPixels"), 0.f, 512.f, 0.f)'),
    ):
        s=once(s,a,b,'slider range/default')
    s=once(s,
        '    const ModToggle::Ptr m_quadview_seam_debug{ModToggle::create(generate_name("QuadViewSeamDebug"), false)};\n',
        '    const ModToggle::Ptr m_quadview_seam_debug{ModToggle::create(generate_name("QuadViewSeamDebug"), false)};\n'
        '    const ModToggle::Ptr m_quadview_seam_temporal{ModToggle::create(generate_name("QuadViewSeamTemporal"), true)};\n'
        '    const ModSlider::Ptr m_quadview_seam_stability{ModSlider::create(generate_name("QuadViewSeamStability"), 0.f, 1.f, .85f)};\n'
        '    const ModSlider::Ptr m_quadview_seam_max_frame_change{ModSlider::create(generate_name("QuadViewSeamMaxFrameChange"), .005f, .30f, .05f)};\n'
        '    const ModToggle::Ptr m_quadview_seam_blend_basic{ModToggle::create(generate_name("QuadViewSeamBlendBasic"), true)};\n'
        '    const ModSlider::Ptr m_quadview_seam_outward_fraction{ModSlider::create(generate_name("QuadViewSeamOutwardFraction"), 0.f, 1.f, .25f)};\n',
        'B32 slider declaration')
    s=once(s,
        '            *m_quadview_seam_transition_px, *m_quadview_seam_debug,\n',
        '            *m_quadview_seam_transition_px, *m_quadview_seam_debug,\n'
        '            *m_quadview_seam_temporal, *m_quadview_seam_stability,\n'
        '            *m_quadview_seam_max_frame_change, *m_quadview_seam_blend_basic,\n'
        '            *m_quadview_seam_outward_fraction,\n',
        'B32 persisted controls')
    paths[p]=s

    p=root/'VR.cpp'
    s=p.read_text(encoding='utf-8')
    s=once(s,
        '                    ImGui::TextWrapped("Off preserves the legacy feather blend. Manual applies a fixed exposure bias. Adaptive matches the periphery to each fovea using per-eye gain and an optional locally fitted boundary residual. Focus lift remains independent. Matching uses the full fovea crop when transition is zero and bypasses the feather blend while active.");\n',
        '                    ImGui::TextWrapped("B32: anti-vignette remains independent. Adaptive matches NR-before-SR foveas against the original periphery, smooths only 18 color-gain records between fence-retired frames, and by default combines with the basic percentage feather.");\n',
        'B32 help text')
    s=once(s,
        '                        m_quadview_seam_local_strength->draw("Local boundary residual strength (0=off)");\n',
        '                        m_quadview_seam_local_strength->draw("Local boundary residual strength (0=off)");\n'
        '                        m_quadview_seam_outward_fraction->draw("Outward matching falloff (% eye width; 0=global)");\n'
        '                        m_quadview_seam_temporal->draw("Temporal stabilization (fence-safe)");\n'
        '                        if (m_quadview_seam_temporal->value()) {\n'
        '                            m_quadview_seam_stability->draw("Temporal stability (0=fast, 1=very stable)");\n'
        '                            m_quadview_seam_max_frame_change->draw("Max gain change per frame");\n'
        '                        }\n',
        'B32 temporal UI')
    s=once(s,
        '                        m_quadview_seam_transition_px->draw("Reserve existing rendered edge for transition (pixels)");\n'
        '                        ImGui::TextWrapped("A positive transition reserves part of the existing rendered fovea edge for blending and moves the sharp interior inward; it adds no rendered pixels.");\n',
        '                        m_quadview_seam_blend_basic->draw("Combine with basic percentage feather");\n'
        '                        if (!m_quadview_seam_blend_basic->value())\n'
        '                            m_quadview_seam_transition_px->draw("Alternative inward transition (pixels, 0=full sharp)");\n'
        '                        ImGui::TextWrapped("The percentage feather uses the existing Context/focus blend slider above. Both methods stay inside the rendered fovea crop; neither invents missing outer pixels.");\n',
        'B32 hybrid UI')
    s=once(s,
        '            requested.seam_debug=m_quadview_seam_debug->value();\n',
        '            requested.seam_debug=m_quadview_seam_debug->value();\n'
        '            requested.seam_temporal_enabled=m_quadview_seam_temporal->value();\n'
        '            requested.seam_stability=m_quadview_seam_stability->value();\n'
        '            requested.seam_max_frame_change=m_quadview_seam_max_frame_change->value();\n'
        '            requested.seam_blend_basic=m_quadview_seam_blend_basic->value();\n'
        '            requested.seam_outward_fraction=m_quadview_seam_outward_fraction->value();\n',
        'B32 requested controls')
    paths[p]=s
    for path,contents in paths.items():
        path.write_text(contents,encoding='utf-8',newline='\n')
    print('B32 stronger/hybrid/stabilized controls applied with exact guards.')

if __name__=='__main__':
    main()

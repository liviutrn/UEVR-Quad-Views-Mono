#!/usr/bin/env python3
"""B34 boundary-mode UI after B30 controls; generated backend keeps B31 base."""
from pathlib import Path
import sys

def once(s,a,b,description):
    n=s.count(a)
    if n!=1: raise RuntimeError(f"B34 {description}: expected one anchor, found {n}")
    return s.replace(a,b,1)

def main():
    if len(sys.argv)!=2: raise SystemExit("Usage: script <backend>")
    root=Path(sys.argv[1])/"src/mods"
    h=root/"VR.hpp"
    s=h.read_text(encoding="utf-8")
    s=once(s,'s_quadview_seam_mode_names{ "Off", "Manual", "Adaptive" }',
      's_quadview_seam_mode_names{ "Off", "Manual", "Adaptive B31", "Boundary B34" }',"mode names")
    s=once(s,'generate_name("QuadViewSeamMode"), s_quadview_seam_mode_names, 2)',
      'generate_name("QuadViewBoundaryMode"), s_quadview_seam_mode_names, 3)',"fresh mode preference")
    controls=[
        ("QuadViewSeamStrength", "QuadViewBoundaryStrength", "0.f, 1.f, .85f", "0.f, 1.f, .95f"),
        ("QuadViewSeamMaxGain", "QuadViewBoundaryMaxGain", ".01f, .5f, .20f", ".01f, .5f, .40f"),
        ("QuadViewSeamColorStrength", "QuadViewBoundaryColor", "0.f, 1.f, .5f", "0.f, 1.f, .80f"),
        ("QuadViewSeamLocalStrength", "QuadViewBoundaryLocal", "0.f, 1.f, .5f", "0.f, 1.f, .9f"),
        ("QuadViewSeamRadiusPixels", "QuadViewBoundaryReachR2", "16.f, 512.f, 120.f", "16.f, 512.f, 280.f"),
        ("QuadViewSeamTransitionPixels", "QuadViewBoundaryFeatherR2", "0.f, 64.f, 0.f", "0.f, 64.f, 28.f"),
    ]
    for oldkey,newkey,oldvalues,newvalues in controls:
        s=once(s,f'generate_name("{oldkey}"), {oldvalues})',
                 f'generate_name("{newkey}"), {newvalues})',newkey)
    s=once(s,
        '    const ModSlider::Ptr m_quadview_seam_transition_px{',
        '    const ModSlider::Ptr m_quadview_seam_noise_guard{ModSlider::create(generate_name("QuadViewBoundaryNoiseGuard"), 0.f, .15f, .035f)};\n'
        '    const ModSlider::Ptr m_quadview_seam_chroma_guard{ModSlider::create(generate_name("QuadViewBoundaryChromaGuard"), 0.f, .08f, .015f)};\n'
        '    const ModSlider::Ptr m_quadview_seam_transition_px{',
        "noise control declarations")
    s=once(s,
        '            *m_quadview_seam_transition_px, *m_quadview_seam_debug,',
        '            *m_quadview_seam_transition_px, *m_quadview_seam_noise_guard,\n'
        '            *m_quadview_seam_chroma_guard, *m_quadview_seam_debug,',
        "saved noise controls")
    h.write_text(s,encoding="utf-8",newline="\n")
    v=root/"VR.cpp"
    s=v.read_text(encoding="utf-8")
    s=once(s,'m_quadview_seam_mode->value()==2) {','m_quadview_seam_mode->value()>=2) {',"shared automatic controls")
    s=once(s,
        '                    ImGui::TextWrapped("Off preserves the legacy feather blend. Manual applies a fixed exposure bias. Adaptive matches the periphery to each fovea using per-eye gain and an optional locally fitted boundary residual. Focus lift remains independent. Matching uses the full fovea crop when transition is zero and bypasses the feather blend while active.");',
        '                    ImGui::TextWrapped("Boundary B34-R2 (default): automatic boundary brightness/RGB matching with current-frame noise suppression. Larger outward reach and inward feather. No temporal history, readback, new render targets or GPU waits; geometry and strong lighting changes can still flicker. B31 Adaptive remains available.");',
        "help")
    s=once(s,
        '                    if (m_quadview_seam_mode->value()!=0) {\n                        m_quadview_seam_transition_px->draw("Reserve existing rendered edge for transition (pixels)");',
        '                    if (m_quadview_seam_mode->value()!=0) {\n                        m_quadview_seam_transition_px->draw("Inward feather (pixels; default 28)");',
        "feather label")
    s=once(s,
        '                        m_quadview_seam_debug->draw("Show adaptive confidence diagnostic");',
        '                        m_quadview_seam_debug->draw("Show adaptive confidence diagnostic");\n'
        '                        if (m_quadview_seam_mode->value()==3) {\n'
        '                            m_quadview_seam_noise_guard->draw("Brightness noise suppression (0=off)");\n'
        '                            m_quadview_seam_chroma_guard->draw("RGB noise suppression (0=off)");\n'
        '                        }',
        "noise UI")
    s=once(s,
        '            requested.seam_transition_px=m_quadview_seam_transition_px->value();',
        '            requested.seam_transition_px=m_quadview_seam_transition_px->value();\n'
        '            requested.seam_noise_guard=m_quadview_seam_noise_guard->value();\n'
        '            requested.seam_chroma_guard=m_quadview_seam_chroma_guard->value();',
        "noise settings")
    v.write_text(s,encoding="utf-8",newline="\n")
    print("B34-R2 boundary matching with noise gates and adjustable inward/outward controls installed")

if __name__=="__main__": main()

#!/usr/bin/env python3
"""B33 stateless safe controls; generated after original B30 overlay."""
from pathlib import Path
import sys

def once(s,a,b,what):
    n=s.count(a)
    if n!=1: raise RuntimeError(f"B33 {what}: expected one anchor, got {n}: {a[:90]}")
    return s.replace(a,b,1)

def main():
    if len(sys.argv)!=2: raise SystemExit("Usage: script <backend>")
    root=Path(sys.argv[1])/"src/mods"
    out={}
    p=root/"VR.hpp"; s=p.read_text(encoding="utf-8")
    # Old B31/B32 Adaptive preference must not force this build into an unstable mode.
    s=once(s,'ModCombo::create(generate_name("QuadViewSeamMode"), s_quadview_seam_mode_names, 2)',
      'ModCombo::create(generate_name("QuadViewStableSeamMode"), s_quadview_seam_mode_names, 1)',"manual mode")
    s=once(s,
      '    const ModToggle::Ptr m_quadview_seam_debug{ModToggle::create(generate_name("QuadViewSeamDebug"), false)};\n',
      '    const ModToggle::Ptr m_quadview_seam_debug{ModToggle::create(generate_name("QuadViewSeamDebug"), false)};\n'
      '    const ModSlider::Ptr m_quadview_seam_temperature{ModSlider::create(generate_name("QuadViewStableSeamTemperature"), -1.f, 1.f, 0.f)};\n'
      '    const ModSlider::Ptr m_quadview_seam_tint{ModSlider::create(generate_name("QuadViewStableSeamTint"), -1.f, 1.f, 0.f)};\n'
      '    const ModToggle::Ptr m_quadview_seam_hybrid{ModToggle::create(generate_name("QuadViewStableSeamHybrid"), true)};\n',
      "declarations")
    s=once(s,'            *m_quadview_seam_transition_px, *m_quadview_seam_debug,\n',
      '            *m_quadview_seam_transition_px, *m_quadview_seam_debug,\n'
      '            *m_quadview_seam_temperature, *m_quadview_seam_tint, *m_quadview_seam_hybrid,\n',
      "saved controls")
    out[p]=s
    p=root/"VR.cpp"; s=p.read_text(encoding="utf-8")
    s=once(s,
      '                    ImGui::TextWrapped("Off preserves the legacy feather blend. Manual applies a fixed exposure bias. Adaptive matches the periphery to each fovea using per-eye gain and an optional locally fitted boundary residual. Focus lift remains independent. Matching uses the full fovea crop when transition is zero and bypasses the feather blend while active.");\n',
      '                    ImGui::TextWrapped("B33 safe default: Manual white balance/exposure + B31 percentage feather. Adaptive RGB matching remains optional, but it can vary with depth and scene content. No temporal GPU readback or extra passes.");\n',
      "help")
    s=once(s,
      '                    if (m_quadview_seam_mode->value()!=0) {\n'
      '                        m_quadview_seam_transition_px->draw("Reserve existing rendered edge for transition (pixels)");\n'
      '                        ImGui::TextWrapped("A positive transition reserves part of the existing rendered fovea edge for blending and moves the sharp interior inward; it adds no rendered pixels.");\n',
      '                    if (m_quadview_seam_mode->value()!=0) {\n'
      '                        m_quadview_seam_temperature->draw("Periphery warmth: cool (-1) to warm (+1)");\n'
      '                        m_quadview_seam_tint->draw("Periphery tint: magenta (-1) to green (+1)");\n'
      '                        m_quadview_seam_hybrid->draw("Blend using B31 percentage feather");\n'
      '                        if (!m_quadview_seam_hybrid->value())\n'
      '                            m_quadview_seam_transition_px->draw("Alternative inward transition in pixels");\n'
      '                        ImGui::TextWrapped("Manual color correction is constant over time. Feather width is set by Context/focus blend above.");\n',
      "UI")
    s=once(s,'            requested.seam_debug=m_quadview_seam_debug->value();\n',
      '            requested.seam_debug=m_quadview_seam_debug->value();\n'
      '            requested.seam_temperature=m_quadview_seam_temperature->value();\n'
      '            requested.seam_tint=m_quadview_seam_tint->value();\n'
      '            requested.seam_hybrid_blend=m_quadview_seam_hybrid->value();\n',
      "settings transaction")
    out[p]=s
    inherited=(root/"vr/QuadViewSettings.hpp").read_text(encoding="utf-8")
    for field in (
      'float seam_temperature{};', 'float seam_tint{};', 'bool seam_hybrid_blend{true};',
      'out.seam_hybrid_blend=requested.seam_hybrid_blend;',
      'scalar(requested.seam_temperature,-1.f,1.f,reject_seam,&Settings::seam_temperature);',
      'scalar(requested.seam_tint,-1.f,1.f,reject_seam,&Settings::seam_tint);'
    ):
        if inherited.count(field)!=1: raise RuntimeError("B33 inherited settings mismatch: "+field)
    for path,content in out.items(): path.write_text(content,encoding="utf-8",newline="\n")
    print("B33 safe stateless manual RGB and feather controls installed")

if __name__=="__main__": main()

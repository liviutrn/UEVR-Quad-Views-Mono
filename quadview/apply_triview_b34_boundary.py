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
        ("QuadViewSeamRadiusPixels", "QuadViewBoundaryReach", "16.f, 512.f, 120.f", "16.f, 512.f, 180.f"),
        ("QuadViewSeamTransitionPixels", "QuadViewBoundaryFeather", "0.f, 64.f, 0.f", "0.f, 64.f, 12.f"),
    ]
    for oldkey,newkey,oldvalues,newvalues in controls:
        s=once(s,f'generate_name("{oldkey}"), {oldvalues})',
                 f'generate_name("{newkey}"), {newvalues})',newkey)
    h.write_text(s,encoding="utf-8",newline="\n")
    v=root/"VR.cpp"
    s=v.read_text(encoding="utf-8")
    s=once(s,'m_quadview_seam_mode->value()==2) {','m_quadview_seam_mode->value()>=2) {',"shared automatic controls")
    s=once(s,
        '                    ImGui::TextWrapped("Off preserves the legacy feather blend. Manual applies a fixed exposure bias. Adaptive matches the periphery to each fovea using per-eye gain and an optional locally fitted boundary residual. Focus lift remains independent. Matching uses the full fovea crop when transition is zero and bypasses the feather blend while active.");',
        '                    ImGui::TextWrapped("Boundary B34 (default): automatic local brightness and RGB warm/cool matching near the actual foveal edge, with a narrow inward detail blend. B31 Adaptive remains selectable. No temporal readback or extra rendered views; occlusion/depth mismatch may still flicker.");',
        "help")
    s=once(s,
        '                    if (m_quadview_seam_mode->value()!=0) {\n                        m_quadview_seam_transition_px->draw("Reserve existing rendered edge for transition (pixels)");',
        '                    if (m_quadview_seam_mode->value()!=0) {\n                        m_quadview_seam_transition_px->draw("Inward feather (pixels; 12 recommended)");',
        "feather label")
    v.write_text(s,encoding="utf-8",newline="\n")
    print("B34 boundary-mode persisted UI installed after B31/B30 source")

if __name__=="__main__": main()

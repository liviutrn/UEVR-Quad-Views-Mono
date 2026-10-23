#!/usr/bin/env python3
"""Read-only headset proof of actual GPU Z candidates, with 4 L/R assignments.
Applied after P1, S0 shader and recovery UI. No change to production compositor
when Depth Discovery is off, and no automatic stereo enabling.
"""
from pathlib import Path
import argparse

def patch(root,path,old,new):
    p=root/path
    s=p.read_text(encoding="utf-8-sig")
    n=s.count(old)
    if n!=1:
        raise RuntimeError(f"EyeDepth source drift {path}, {n} occurrences: {old[:65]}")
    p.write_text(s.replace(old,new,1),encoding="utf-8",newline="\n")

def apply(root):
    patch(root,"src/mods/VR.hpp",
        '''    const ModToggle::Ptr m_duo_eye_test{ModToggle::create(generate_name("DuoViewS0EyeOutputTest"), false)};''',
        '''    const ModToggle::Ptr m_duo_eye_test{ModToggle::create(generate_name("DuoViewS0EyeOutputTest"), false)};
    const ModInt32::Ptr m_duo_depth_eyes{ModSliderInt32::create(generate_name("DuoViewP1EachEyeRawZ"), 0, 4, 0)};''')
    patch(root,"src/mods/VR.hpp",
        '''*m_duo_center_stereo_preview, *m_duo_center_stereo_strength, *m_duo_eye_test,''',
        '''*m_duo_center_stereo_preview, *m_duo_center_stereo_strength, *m_duo_eye_test, *m_duo_depth_eyes,''')
    patch(root,"src/mods/VR.hpp",
        '''        if (!is_duoview_depth_discovery_enabled()) return 0u;
        if (m_duo_center_stereo_preview->value() &&
            m_duo_center_stereo_strength->value()>0) return 5u;''',
        '''        if (!is_duoview_depth_discovery_enabled()) return 0u;
        // Explicit P1 inspection mode overrides stereo reprojection when requested.
        if (m_duo_depth_eyes->value()>=1 && m_duo_depth_eyes->value()<=4)
            return 6u + static_cast<uint32_t>(m_duo_depth_eyes->value());
        if (m_duo_center_stereo_preview->value() &&
            m_duo_center_stereo_strength->value()>0) return 5u;''')
    patch(root,"src/mods/VR.cpp",
        '''                    m_duo_depth_visual->draw("P1 raw-Z debug 0=Mono 1=Periph candidate 2=Fovea candidate 3=Both 4=UNVERIFIED mask");''',
        '''                    m_duo_depth_visual->draw("P1 old cropped raw Z 0..4 (disable during per-eye test)");
                    m_duo_depth_eyes->draw("P1 per-eye depth: 0=off 1=Z0 both 2=Z1 both 3=left Z0/right Z1 4=left Z1/right Z0");
                    ImGui::TextWrapped("Candidate Z is mapped FULL-FRAME in each eye, regardless of DLSS or XR output size. Cyan stripe=Z0; pink stripe=Z1. Turn S0 Eye Output Check OFF.");
                    if (m_duo_depth_eyes->value()>0 && !d3d12().duoview_p1_gpu_ready()) {
                        ImGui::TextColored(ImVec4(1.f,.65f,.14f,1.f),
                            "Depth eye view BLOCKED: capture 2/2 and GPU fence completion required.");
                    }''')
    print("P1 per-eye Z inspection integrated: off; Z0both; Z1both; L0/R1; L1/R0.")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("backend",type=Path)
    apply(p.parse_args().backend)

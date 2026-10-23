#!/usr/bin/env python3
"""Experimental S0 center-stereo preview; default OFF and never marketed as true A+.
Order after apply_depth_capture_p1.py and apply_depth_visual_p1.py.
The live RGB-D producer role remains unverified in P1. This is an opt-in proof
of two-eye shader/raster/submission plumbing, not calibrated headset stereo.
"""
from pathlib import Path
import argparse

def replace(root, relative, before, after):
    path=root/relative
    source=path.read_text(encoding="utf-8-sig")
    count=source.count(before)
    if count!=1:
        raise RuntimeError(f"StereoS0 source drift: {relative} matches={count} anchor={before[:85]!r}")
    path.write_text(source.replace(before,after,1),encoding="utf-8",newline="\n")

def apply(root):
    replace(root,"src/mods/VR.hpp",
        '''    uint32_t duoview_p1_depth_visual_mode() const {
        return is_duoview_depth_discovery_enabled()
            ? static_cast<uint32_t>(m_duo_depth_visual->value()) : 0u;
    }''',
        '''    uint32_t duoview_p1_depth_visual_mode() const {
        if (!is_duoview_depth_discovery_enabled()) return 0u;
        if (m_duo_center_stereo_preview->value() &&
            m_duo_center_stereo_strength->value()>0) return 5u;
        return static_cast<uint32_t>(m_duo_depth_visual->value());
    }
    uint32_t duoview_p1_stereo_preview_strength() const {
        return is_duoview_depth_discovery_enabled() &&
            m_duo_center_stereo_preview->value()
            ? static_cast<uint32_t>(m_duo_center_stereo_strength->value()) : 0u;
    }
    bool duoview_s0_eye_test_enabled() const {
        return is_duoview_renderer_active() && m_duo_eye_test->value();
    }''')
    replace(root,"src/mods/VR.hpp",
        '''    const ModInt32::Ptr m_duo_depth_visual{ModSliderInt32::create(generate_name("DuoViewP1RawDepthView"), 0, 4, 0)};''',
        '''    const ModInt32::Ptr m_duo_depth_visual{ModSliderInt32::create(generate_name("DuoViewP1RawDepthView"), 0, 4, 0)};
    const ModToggle::Ptr m_duo_center_stereo_preview{ModToggle::create(generate_name("DuoViewExperimentalStereoS0"), false)};
    const ModInt32::Ptr m_duo_center_stereo_strength{ModSliderInt32::create(generate_name("DuoViewStereoS0StrengthPct"), 0, 40, 8)};
    const ModToggle::Ptr m_duo_eye_test{ModToggle::create(generate_name("DuoViewS0EyeOutputTest"), false)};''')
    replace(root,"src/mods/VR.hpp",
        '''*m_duo_debug_source, *m_duo_depth_discovery, *m_duo_depth_visual,''',
        '''*m_duo_debug_source, *m_duo_depth_discovery, *m_duo_depth_visual,
            *m_duo_center_stereo_preview, *m_duo_center_stereo_strength, *m_duo_eye_test,''')
    replace(root,"src/mods/VR.cpp",
        '''                    m_duo_depth_visual->draw("P1 raw-Z debug 0=Mono 1=Periph candidate 2=Fovea candidate 3=Both 4=UNVERIFIED mask");''',
        '''                    m_duo_depth_visual->draw("P1 raw-Z debug 0=Mono 1=Periph candidate 2=Fovea candidate 3=Both 4=UNVERIFIED mask");
                    m_duo_center_stereo_preview->draw("S0 two-eye stereo WARP TEST (unverified Z, OFF recommended)");
                    m_duo_center_stereo_strength->draw("S0 test strength: 0..40% (8% initial)");
                    ImGui::TextWrapped("STEREO S0 WARNING: copies from pooled SceneDepthZ have NOT been proven to match fovea/periphery or the current RGB frame; depth may be stale. This only tests actual L/R double-wide submission. It is NOT calibrated stereo. For comfort: start at 8%% then raise cautiously. For normal play leave OFF.");''')
    replace(root,"src/mods/VR.cpp",
        '                if (ImGui::TreeNode("DuoView P1 owned depth capture (experimental)")) {',
        '''                m_duo_eye_test->draw("S0 EYE OUTPUT CHECK (no depth; cyan left / orange right)");
                ImGui::TextWrapped("This confirms two different eye images reach OpenXR. It requires no depth and is NOT a stereo-geometry test.");
                if (ImGui::TreeNode("DuoView P1 owned depth capture (experimental)")) {''')
    replace(root,"src/mods/vr/D3D12Component.cpp",
        '''                            const uint32_t p1_debug=m_duoview_p1.gpu_ready() ?
                                vr->duoview_p1_depth_visual_mode() : 0u;''',
        '''                            const uint32_t p1_debug=vr->duoview_s0_eye_test_enabled() ? 6u :
                                (m_duoview_p1.gpu_ready() ? vr->duoview_p1_depth_visual_mode() : 0u);
                            if (p1_debug==6u)
                                SPDLOG_INFO_ONCE("[StereoS0][EyeCheck] requested; no depth required");
                            const uint32_t p1_stereo_strength=p1_debug==5 ?
                                vr->duoview_p1_stereo_preview_strength() : 0u;''')
    replace(root,"src/mods/vr/D3D12Component.cpp",
        'depth0,depth1,p1_debug,',
        'depth0,depth1,p1_debug,p1_stereo_strength,')
    replace(root,"src/mods/vr/D3D12Component.cpp",
        '''depth0.Get(),depth1.Get(),p1_debug);''',
        '''depth0.Get(),depth1.Get(),p1_debug,p1_stereo_strength);''')
    print("Stereo S0: guarded two-eye double-wide raster preview. Feature OFF unchanged.")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("backend",type=Path)
    apply(p.parse_args().backend)

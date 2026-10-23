#!/usr/bin/env python3
"""S0 independent source invariants: do not silently replace Build49 MONO."""
import argparse
from pathlib import Path

def validate(root):
    def read(p):return (root/p).read_text(encoding="utf-8-sig")
    vr=read("src/mods/VR.hpp")
    ui=read("src/mods/VR.cpp")
    dx=read("src/mods/vr/D3D12Component.cpp")
    gpu=read("src/mods/vr/DuoViewD3D12.hpp")
    shaders=read("src/mods/vr/DuoViewShaderSource.hpp")
    assert 'DuoViewExperimentalStereoS0"), false' in vr
    assert 'DuoViewS0EyeOutputTest"), false' in vr
    assert 'duoview_s0_eye_test_enabled()' in vr
    assert 'S0 EYE OUTPUT CHECK (no depth' in ui
    assert 'vr->duoview_s0_eye_test_enabled() ? 6u' in dx
    assert 'native_eye_check_pixel_shader_bytecode' in shaders
    assert 'native_eye_check_pipeline_' in gpu
    assert 'const bool eye_test=depth_debug==6' in gpu
    assert 'const bool direct_xr=eye_test ||' in gpu
    assert 'DuoViewStereoS0StrengthPct"), 0, 40, 8' in vr
    assert 'if (!is_duoview_depth_discovery_enabled()) return 0u' in vr
    assert 'duoview_p1_stereo_preview_strength()' in vr
    assert 'S0 two-eye stereo WARP TEST (unverified Z, OFF recommended)' in ui
    assert 'S0 test strength: 0..40%' in ui
    assert 'copies from pooled SceneDepthZ have NOT been proven' in ui
    assert 'const uint32_t p1_stereo_strength=p1_debug==5' in dx
    assert 'depth0.Get(),depth1.Get(),p1_debug,p1_stereo_strength' in dx
    assert 'native_stereo_preview_pixel_shader_bytecode' in shaders
    assert 'native_stereo_preview_pipeline_' in gpu
    assert 'const bool stereo_preview=depth_debug==5' in gpu
    assert 'const bool direct_xr=stereo_preview ||' in gpu
    assert 'if ((depth_mode || stereo_preview) && !ensure_depth_srvs' in gpu
    assert 'return record_native_gather' in gpu
    assert 'cmd->SetPipelineState(stereo_preview ? native_stereo_preview_pipeline_' in gpu
    assert 'copy_composite_to_stereo(' in gpu
    assert 'const bool stereo_preview=' in gpu and 'direct_compatible' in gpu
    assert 'source_to_right' not in gpu
    assert 'Stereo S0' not in read("src/mods/vr/runtimes/OpenXR.cpp")
    print("S0 gates passed: default OFF; opt-in; owns 2 raster eyes; fallback unchanged; precompiled DXBC.")
if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("backend",type=Path)
    validate(a.parse_args().backend)

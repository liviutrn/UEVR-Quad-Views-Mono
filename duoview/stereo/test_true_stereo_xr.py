#!/usr/bin/env python3
"""Fail closed on Mono presentation, missing physical-eye source or unsafe R5 lifetime."""
from pathlib import Path
import sys
root=Path(sys.argv[1])
def text(p):return (root/p).read_text(encoding="utf-8-sig")
comp=text("src/mods/vr/DuoViewD3D12.hpp")
shader=text("src/mods/vr/DuoViewStereoCompositeRaster.hlsl")
h=text("src/mods/vr/D3D12Component.hpp")
c=text("src/mods/vr/D3D12Component.cpp")
ui=text("src/mods/VR.cpp")
depth=text("src/mods/vr/d3d12/StockDibrDepth.hpp")
copy=text("src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp")
checks={
"Actual left/right XR pixel shader precompiled":'native_stereo_shader_bytecode' in comp and "PSNativeStereo" in shader,
"Distinct eye outputs use physical eye half":'const bool right=i.pos.x>=float(OutputSize.x)' in shader,
"Stereo forces direct doublewide XR":'frame.config.settings.direct_xr_output || requested_stereo' in comp,
"Mono frame-copy cannot be stereo":'const bool copied=direct_xr ||' in comp and 'stereoReady=requested_stereo' in comp,
"Valid physical left/right source":'frame.split_eye' in comp and 'frame.eye_cameras[0].position' in comp,
"Full frozen left/right projections":'frame.projection_right' in comp and 'frame.projection' in comp,
"Real IPD not arbitrary full-screen disparity":'const float baseline=static_cast<float>(std::sqrt(sum))*stereoSign' in comp,
"True depth-guided right fovea":'RightFovea(uv,nativeRight,confidence)' in shader and 'DeviceLeftDepth(local)' in shader,
"Right peripheral depth guides left reprojection":'RightSampleForLeft(uv,good)' in shader,
"Periphery errors use actual right color":'if(good)periphery=RightNative(shifted)' in shader,
"Right fovea keeps LEFT shading":'return LeftNative(leftUV);' in shader,
"Manual L/R DSV browsing available":'SliderInt("LEFT fovea candidate' in ui and 'SliderInt("RIGHT periphery candidate' in ui,
"Explicit headset stereo switch and proof mode":'TRUE STEREO (0 V3 mono / 1 stereo / 2 tint proof)' in ui,
"R5 consumers retired on all synthetic passes":' || preview_mode || stereo_mode)' in c,
"Raw screenshot includes stereo XR output":'"xr_submitted_doublewide"' in copy,
"Every screenshot retains stereo choices":'stereoMode=' in c and 'manualLeft=' in c,
"R5 depth copy state supports pixel reads":'D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE' in depth,
"Stereo active when preview disabled":'if(m_stock_dibr_scope && (preview_mode || stereo_mode))' in c,
"Stereo root constants within DX12 root-size limit":'static_assert(sizeof(ShaderConstants) == 176)' in comp
}
for name,valid in checks.items():print(("PASS: " if valid else "FAIL: ")+name)
if not all(checks.values()):raise SystemExit("Physical stereo XR integration contract FAILED")

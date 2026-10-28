#!/usr/bin/env python3
"""CI31 opt-in mode 3 checks. This is NOT headset or geometric verification."""
from pathlib import Path
import sys
root=Path(sys.argv[1])
def load(path):return (root/path).read_text(encoding="utf-8-sig")
shader=load("src/mods/vr/DuoViewStereoCompositeRaster.hlsl")
comp=load("src/mods/vr/DuoViewD3D12.hpp")
ui=load("src/mods/VR.cpp")
hdr=load("src/mods/vr/D3D12Component.hpp")
assert "stereoMode>3u" in comp
assert "stereoMode==3?3.f:0.f" in comp
assert "if(!right && StereoCheck.w<2.5f)" in shader
assert "const float4 nativeRight=RightNative(uv);" in shader
assert "float4 periphery=nativeRight;" in shader
assert "if(abs(StereoCheck.w-1.0f)<0.25f && right)" in shader
assert "RightFovea(uv,nativeRight,confidence)" in shader
assert "LeftNative(uv)" in shader
assert "stereo_mode,0,3" in ui
assert "m_duo_stereo_mode{0}" in hdr
print("PASS CI31 mode 3 isolates RIGHT fovea only; two peripheries use same real RIGHT color")

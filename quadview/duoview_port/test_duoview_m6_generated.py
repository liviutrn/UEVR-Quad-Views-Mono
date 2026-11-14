#!/usr/bin/env python3
"""Verify the temporal path uses retained fine input, its camera, and its crop."""
import sys
from pathlib import Path

vr = Path(sys.argv[1]) / "src/mods/vr"
shaders = Path(sys.argv[2])
def read(path):
    return path.read_text(encoding="utf-8")

depth = read(vr / "DuoViewM1D3D12.hpp")
compositor = read(vr / "DuoViewD3D12.hpp")
present = read(vr / "D3D12Component.cpp")
stereo = read(shaders / "DuoViewM1Stereo.hlsl")
raster = read(shaders / "DuoViewNativeCompositeRaster.hlsl")

assert "sizeof(M1Constants) == 496" in depth
assert "previous_fovea_lease=previous->depth.lease;" in depth
assert "previous->depth.jitter[0]*previous->jitter_sign;" in depth
assert "m4_field_range.NumDescriptors=2;" in compositor
assert "m4_table.ptr+=2u*srv_descriptor_increment_;" in compositor
assert "last->key.generation==frame.config.key.generation" in compositor
assert "last->depth_coefficients==stereo_geometry->depth_coefficients" in compositor
assert "if (require_fine && (!m1_active || !m1_.m4_active))" in compositor
assert "if (submitted && recorded && callback_attempted) {\n                                recorded_compositor->note_fine_depth_enqueued();" in present
assert "Texture2D<float> M6PreviousDepth : register(t9);" in stereo
assert "const float4 ray=float4" in stereo and "dot(M6View[2],ray)" in stereo
assert "(previousUv-M6PreviousCrop.xy)/(M6PreviousCrop.zw-M6PreviousCrop.xy)" in stereo
assert "fine=M6StabilizeFineEdge(local,fine,farDepth);" in stereo
assert "(fineNear-fineFar)*disparity < .16" in stereo
assert "abs(tapDepth-d)<=max(.05*d,1.e-4)" in stereo
assert "DebugViewMode==0 && fill.y>0." in raster
print("PASS: pose- and crop-aware fine-depth history; background-only hole blur")

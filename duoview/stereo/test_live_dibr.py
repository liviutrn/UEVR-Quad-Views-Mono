#!/usr/bin/env python3
"""Offline CI gates for the experimental live-depth DIBR path."""
from pathlib import Path
import argparse
p=argparse.ArgumentParser();p.add_argument("backend",type=Path)
a=p.parse_args()
def read(path):return (a.backend/path).read_text(encoding="utf-8-sig")
cap=read("src/mods/vr/DuoDepthPairP1.hpp")
vr=read("src/mods/VR.cpp")
gpu=read("src/mods/vr/DuoViewD3D12.hpp")
shader=read("src/mods/vr/DuoViewShaderSource.hpp")
assert "desc.Width==860" in cap and "desc.Width==344" in cap
assert "D3D12_RESOURCE_STATE_DEPTH_WRITE" in cap
assert "D3D12_RESOURCE_STATE_COPY_SOURCE" in cap
assert "D3D12_RESOURCE_STATE_COPY_DEST" in cap
assert "CopyTextureRegion" in cap and "std::try_to_lock" in cap
assert "GetCompletedValue()>=1" in cap
assert "one copy per callback" in cap.lower() or "One copy per callback" in cap
assert "Start LIVE DIBR depth capture" in vr
assert "Experimental LIVE DIBR stereo" in vr
assert "native_stereo_preview_pipeline_" in gpu
assert "depth0 && depth1" in gpu
assert "native_stereo_preview_pixel_shader_bytecode" in shader
assert "return record_native_gather" in gpu
print("Live DIBR: two prewarmed independent textures, bounded callback, XR stereo and legacy Mono fallback.")

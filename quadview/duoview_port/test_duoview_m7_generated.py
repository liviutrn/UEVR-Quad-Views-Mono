#!/usr/bin/env python3
"""Check accumulated histories, fovea-only shader routing, and saved controls."""
import re
import sys
from pathlib import Path

vr = Path(sys.argv[1]) / "src/mods/vr"
sh = Path(sys.argv[2])
def read(path):
    return path.read_text(encoding="utf-8")

depth = read(vr / "DuoViewM1D3D12.hpp")
dx = read(vr / "DuoViewD3D12.hpp")
settings = read(vr / "DuoViewConfig.hpp")
ui = read(vr.parent / "VR.cpp")
ui_header = read(vr.parent / "VR.hpp")
stereo = read(sh / "DuoViewM1Stereo.hlsl")
raster = read(sh / "DuoViewNativeCompositeRaster.hlsl")

assert "sizeof(M1Constants) == 528" in depth
assert "buffer.Width = m1_constant_bytes;" in depth
assert "std::array<ComPtr<ID3D12Resource>,2> temporal;" in dx
assert "write_index=last ? 1u-last->index : 0u" in dx
assert "next_fine_depth_.key==b40_history_->fine_depth.key" in dx
assert "m4_field_range.NumDescriptors=3;" in dx
assert "m4_output_range.NumDescriptors=2;" in dx
assert "m4_table.ptr+=3u*srv_descriptor_increment_;" in dx
assert "D3D12_RESOURCE_STATE_UNORDERED_ACCESS,history_read" in dx
assert "filtered=history.x;" in stereo
assert "float4(fine,representativeDepth,packed,rawNear)" in stereo
assert "float3 oldColor=M7UnpackColor(history.z);" in stereo
assert "M7PackColor(M7AccumulateFillColor(" in stereo
assert "const bool inCrop=M4Flags.x>.5 && all(uv>M2Crop.xy) && all(uv<M2Crop.zw);" in stereo
assert "if (inCrop && um>M2Crop.x && um<M2Crop.z)" in stereo
assert "fill.z>.5 && (M7Controls.y>0. || M7Controls.z>0.)" in raster
assert "fill.x*M7Controls.z/M23Wide.z" in raster
assert "all(tap>M2Crop.xy) && all(tap<M2Crop.zw)" in raster
assert "if (require_fine && (!m1_active || !m1_.m4_active))" in dx

struct = settings.split("struct Settings {",1)[1].split("\n};",1)[0]
declared = re.findall(r"(\w+)\{[^{};]*\}\s*[,;]",re.sub(r"//[^\n]*","",struct))
candidate = ui.split("uevr::duoview::Settings candidate{",1)[1].split("\n    };",1)[0]
positions = [declared.index(field) for field in re.findall(r"(?:^|[\s,{])\.(\w+)=(?!=)",candidate,re.M) if field in declared]
assert positions == sorted(positions)
for setting, control in (("edge_history","edge_history"),("fill_history","fill_history"),("fill_blur_px","fill_blur")):
    assert setting in declared
    assert f".{setting}=m_duo_{control}->value()" in candidate
    assert f"*m_duo_{control}," in ui_header
    assert f"m_duo_{control}->draw(" in ui
print("PASS: accumulated fovea depth and colour history, independent blur, saved controls")

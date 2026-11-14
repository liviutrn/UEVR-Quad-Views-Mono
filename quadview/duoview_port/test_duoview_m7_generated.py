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

assert "sizeof(M1Constants) == 544" in depth
assert "float m7_tuning[4]{};" in depth
assert "data.m7_tuning[0]=edge_reach_px;" in depth
assert "buffer.Width = m1_constant_bytes;" in depth
assert "std::array<ComPtr<ID3D12Resource>,2> temporal;" in dx
assert "write_index=last ? 1u-last->index : 0u" in dx
assert "next_fine_depth_.key==b40_history_->fine_depth.key" in dx
assert "m4_field_range.NumDescriptors=3;" in dx
assert "m4_output_range.NumDescriptors=2;" in dx
assert "m4_table.ptr+=3u*srv_descriptor_increment_;" in dx
assert "D3D12_RESOURCE_STATE_UNORDERED_ACCESS,history_read" in dx
assert "filtered=history.x;" in stereo
assert "float4 M7Tuning;" in stereo
assert "const float pixelBudget=reach;" in stereo
assert "const float3 bounded=clamp(oldColor,current-.50,current+.50);" in stereo
assert "float4(fine,representativeDepth,packed,rawNear)" in stereo
assert "float3 oldColor=M7UnpackColor(history.z);" in stereo
assert "M7PackColor(M7AccumulateFillColor(" in stereo
assert "const bool inCrop=M4Flags.x>.5 && all(uv>M2Crop.xy) && all(uv<M2Crop.zw);" in stereo
assert "if (inCrop && um>M2Crop.x && um<M2Crop.z)" in stereo
assert "fill.z>.5 && (M7Controls.y>0. || M7Controls.z>0.)" in raster
assert "fill.x*M7Controls.z/M23Wide.z" in raster
assert "[unroll] for (int offset=-2;offset<=2;++offset)" in raster
assert "saturate(M7Controls.z/2.)" in raster
assert "all(tap>M2Crop.xy) && all(tap<M2Crop.zw)" in raster
assert "if (require_fine && (!m1_active || !m1_.m4_active))" in dx

struct = settings.split("struct Settings {",1)[1].split("\n};",1)[0]
declared = re.findall(r"(\w+)\{[^{};]*\}\s*[,;]",re.sub(r"//[^\n]*","",struct))
candidate = ui.split("uevr::duoview::Settings candidate{",1)[1].split("\n    };",1)[0]
positions = [declared.index(field) for field in re.findall(r"(?:^|[\s,{])\.(\w+)=(?!=)",candidate,re.M) if field in declared]
assert positions == sorted(positions)
for setting, control in (("edge_history","edge_history"),("fill_history","fill_history"),("fill_blur_px","fill_blur"),("edge_reach_px","edge_reach")):
    assert setting in declared
    assert f".{setting}=m_duo_{control}->value()" in candidate
    assert f"*m_duo_{control}," in ui_header
    assert f"m_duo_{control}->draw(" in ui
assert "out.edge_reach_px=(std::clamp)(requested.edge_reach_px,2.f,20.f);" in settings
assert "out.edge_history=(std::clamp)(requested.edge_history,0.f,1.f);" in settings
assert 'generate_name("DuoEdgeHistory"),0.f,1.f,.70f' in ui_header
assert "out.fill_blur_px=(std::clamp)(requested.fill_blur_px,0.f,32.f);" in settings
print("PASS: M9 tunable 2-20px temporal depth, wider colour history, masked 32px blur, saved controls")

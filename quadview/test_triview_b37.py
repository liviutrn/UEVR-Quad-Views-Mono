#!/usr/bin/env python3
"""B37: captured final color coordinates and unchanged B31 focus renderer."""
from pathlib import Path
import subprocess,sys
r=Path(__file__).resolve().parent
s=(r/'QuadViewComposite.hlsl').read_text();h=(r/'QuadViewD3D12.hpp').read_text()
baseline=subprocess.check_output(['git','-C',str(r.parent),'show','008c9f7548c43f5977c1197c4180cddb435c64de:quadview/QuadViewComposite.hlsl'],text=True)
def body(text,name):
 start=text.index(name);a=text.index('{',start);i=a+1;level=1
 while level: level+=(text[i]=='{')-(text[i]=='}');i+=1
 return text[start:i]
for name in ['float2 AtlasUvKnownSize(','float3 ReadFocus(','float3 GlamSharpenFocus(','float3 CorrectFocusColor(','float4 ScenePixel(']:
 assert body(s,name)==body(baseline,name),name
assert 'Seam.x < 0.5 || Seam.x > 2.5' in s
assert 'const auto rect = color_source_rect(layout,view == 1 && layout.shared_context ? 0 : view);' in h
assert 'DetectBlank' not in s and 'padding_guard' not in s
if len(sys.argv)>1:
 b=Path(sys.argv[1])/'src/mods';depth=(b/'vr/QuadViewNgxDepth.hpp').read_text();vr=(b/'VR.cpp').read_text()
 assert 'if (candidate.get()==protected_slot) continue;' in depth
 assert 'std::chrono::milliseconds(250)' in depth
 assert '(!slot->foreign_queue || depth_copy_complete(completed, slot->producer_fence_value))' in depth
 assert 'm_quadview_edge_feather' not in vr
 assert 'requested.feather_fraction=m_quadview_feather->value();' in vr
print('B37: original B31 focus sampling/sharpen/anti-vignette/display code identical; final color rect separated from engine role, original feather and depth safety preserved; WARP still required')

#!/usr/bin/env python3
"""B35 source/ownership gates. Pixel/temporal behavior is tested by production WARP."""
from pathlib import Path
import math,sys,subprocess
r=Path(__file__).resolve().parent
h=(r/'QuadViewD3D12.hpp').read_text();s=(r/'QuadViewComposite.hlsl').read_text()
def function(text,name):
 start=text.index(name);a=text.index('{',start);depth=1;b=a+1
 while depth:
  depth+=(text[b]=='{')-(text[b]=='}');b+=1
 return text[start:b]
original=subprocess.check_output(['git','-C',str(r.parent),'show','008c9f7548c43f5977c1197c4180cddb435c64de:quadview/QuadViewComposite.hlsl'],text=True)
assert function(original,'float3 CorrectFocusColor(')==function(s,'float3 CorrectFocusColor('),'B31 anti-vignette changed'
assert 'sizeof(ShaderConstants) == 512' in h
assert 'match_srv.Buffer.NumElements = 148;' in h and 'match_uav.Buffer.NumElements = 148;' in h
assert h.count('order.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV')==2
assert 'SetComputeRootUnorderedAccessView(3,history->GetGPUVirtualAddress())' in h
assert 'float3 correction=slow*stable+fast*(target-stable)' in s
assert 'error>EdgeV2.w : error>2.0*EdgeV2.w' in s
assert 'clamp(delta,-EdgeV2.z*float(elapsed)*0.001,EdgeV2.z*float(elapsed)*0.001)' in s
assert '((uint)floor(k))%32u' in s
v2=function(s,'void UpdateEdgeV2(')+function(s,'bool EdgeDifference(')+function(s,'float4 MatchEdgeV2(')
assert 'Seam.z' not in v2,'Legacy amplitude cap leaked into V2'
assert 'Readback' not in function(s,'void UpdateEdgeV2(')
if len(sys.argv)>1:
 b=Path(sys.argv[1])/'src/mods'
 dx=(b/'vr/D3D12Component.cpp').read_text();cc=(b/'vr/d3d12/CommandContext.cpp').read_text()
 vh=(b/'VR.hpp').read_text();vr=(b/'VR.cpp').read_text()
 for field in ('reach_px','fast_px','rate','hysteresis'):
  assert 'requested.edge_'+field+'=' in vr
 assert 's_quadview_edge_mode_names, 2)' in vh
 assert 'comp->set_edge_history(quadview_edge_history)' in dx
 assert 'commands.seam_submission_queue=seam_queue' in dx
 assert 'std::exchange(this->seam_submission_queue' in cc
 assert cc.index('auto command_queue = std::exchange')<cc.index('command_queue->ExecuteCommandLists')<cc.index('command_queue->Signal')
 assert 'this->quadview_edge_history.reset()' in dx
 expected=h.replace('constants.sharpen[2] = .10f;', 'constants.sharpen[2] = settings.sharpen_max_change;').replace('constants.sharpen_eye[1] = settings.sharpen_strength;', 'constants.sharpen_eye[1] = settings.sharpen_link_right ? settings.sharpen_strength : settings.sharpen_right_strength;').replace('constants.sharpen_eye[2] = .10f;', 'constants.sharpen_eye[2] = settings.sharpen_max_change;').replace('constants.sharpen_eye[3] = .10f;', 'constants.sharpen_eye[3] = settings.sharpen_link_right ? settings.sharpen_max_change : settings.sharpen_right_max_change;')
 assert (b/'vr/QuadViewD3D12.hpp').read_text()==expected
# Independent arithmetic identities, not substitutes for GPU behavior.
for target in (-100.,-2.,-.1,0.,.1,2.,100.):
 stable=0.
 for i in range(20001):
  delta=target-stable;stable+=max(-.01,min(.01,delta))
 assert abs(stable-target)<1e-9
 assert abs((stable+(target-stable))-target)<1e-9
print('B35: B31 anti-vignette byte identity, generated queue/history ownership, rate-only correction gates passed; WARP still required')

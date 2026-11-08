#!/usr/bin/env python3
"""B36 source integration gates; production image behavior is exercised in WARP."""
from pathlib import Path
import sys
r=Path(__file__).resolve().parent
s=(r/'QuadViewComposite.hlsl').read_text();h=(r/'QuadViewD3D12.hpp').read_text()
assert 'min(FocusWeight(uv,crop),pixelWeight)' in s,'Original feather must compose with Edge V2'
assert 'FocusSampleUv(2u+eye, focusSourceSize, focusRect, focusUv)' in s
assert 'FocusSampleUv(sourceIndex, sourceSize, rect, local)' in s,'Sharpening must not read blank rim'
assert 'lit>=6u' in s and 'all(abs(c)<0.0001)' in s
assert 'GroupMemoryBarrierWithGroupSync();\n        if(lane==0u) SeamOutput[146u+eye]' in s
assert 'stamp.z!=guardKey' in s
assert 'match_srv.Buffer.NumElements = 148;' in h and 'match_uav.Buffer.NumElements = 148;' in h
assert '(settings.seam_mode>=3 && settings.edge_padding_guard)' in h
assert 'constants.focus_profile[2]=settings.edge_padding_guard ? 1.f : 0.f;' in h
if len(sys.argv)>1:
 b=Path(sys.argv[1])/'src/mods'
 vr=(b/'VR.cpp').read_text();vh=(b/'VR.hpp').read_text();depth=(b/'vr/QuadViewNgxDepth.hpp').read_text()
 assert 'requested.edge_padding_guard=m_quadview_edge_padding->value();' in vr
 assert '*m_quadview_edge_padding' in vh
 assert 'if (candidate.get()==protected_slot) continue;' in depth
 assert depth.index('if (candidate.get()==protected_slot) continue;')<depth.index('if (!depth_slot_reusable(candidate->pending')
 assert 'std::chrono::milliseconds(250)' in depth,'Do not loosen the selector age limit'
 assert '(!slot->foreign_queue || depth_copy_complete(completed, slot->producer_fence_value))' in depth
 assert 'MaxSlots = 12' in depth or 'max_slots = 12' in depth or 'pool_.size() >= 12' in depth
print('B36 source gates: standard feather restored, blank-rim reads bounded, protected depth reuse and original safety limits retained; WARP required')

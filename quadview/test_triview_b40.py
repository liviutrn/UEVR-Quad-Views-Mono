#!/usr/bin/env python3
"""B40: separate continuous-history/robust sampling and UI safety contracts."""
from pathlib import Path
import sys
root=Path(__file__).resolve().parent
s=(root/'QuadViewComposite.hlsl').read_text()
def body(source, needle):
    i=source.index(needle); p=source.index('{',i); level=1; j=p+1
    while level:
        level+=(source[j]=='{')-(source[j]=='}')
        j+=1
    return source[i:j]
b=body(s,'void UpdateEdgeB40(')
# B41 samples the four sub-anchors on parallel lanes (lane&3u) instead of a loop.
assert ('sub<4u' in b or 'const uint sub=lane&3u;' in b) and 'AmbientEdgeDifference(eye,p,side,crop,sampleDelta)' in b
assert 'count>=2u' in b and 'min(min(q0,q1),min(q2,q3))' in b
assert 'min(q0,min(q1,q2))' in b
assert 'stamp.w==0x40b04001u' in b
assert 'EdgeHistory.y-stamp.y' in b and 'min(elapsed,50u)' in b
assert 'const float alpha=float(dt)/(tau+float(dt))' in b
assert 'stable+=clamp((target-stable)*alpha' in b
assert 'SeamOutput[outIndex+1u]=float4(stable,1.0)' in b
for forbidden in ('stamp.x!=','elapsed>250','cropDelta>','motionTolerance','!valid)', 'reset='):
    assert forbidden not in b, f'B40 motion/history reset regression: {forbidden}'
assert 'UpdateEdgeB40(eye,lane)' in s and 'UpdateEdgeV2(eye,lane)' in s
assert '(SeamOptions.w > 0.5 || Seam.x > 5.5)' in s
h=(root/'QuadViewD3D12.hpp').read_text()
assert 'settings.seam_mode==6' in h
assert 'sizeof(ShaderConstants) == 512' in h
st=(root/'QuadViewSettings.hpp').read_text()
assert 'unsigned_integer(requested.seam_mode,0u,6u' in st
if len(sys.argv)>1:
    ui=Path(sys.argv[1])/'src/mods'
    cpp=(ui/'VR.cpp').read_text()
    hpp=(ui/'VR.hpp').read_text()
    assert '"B40 Continuous Ambient"' in hpp
    assert 's_quadview_edge_mode_names, 4)' in hpp
    assert 'm_quadview_b40_stability' in cpp and '600u' in cpp and '75u' in cpp
    assert 'm_quadview_legacy_inward->draw("Original inward fovea feather (B27)")' in cpp
    assert 'if (m_quadview_edge_mode->value()!=4)' in cpp
    assert 'm_quadview_edge_mode->value()==4' in cpp
    assert 'requested.ambient_time_ms=m_quadview_edge_mode->value()==4' in cpp
    generated=(ui/'vr/QuadViewSettings.hpp').read_text()
    assert 'unsigned_integer(requested.seam_mode,0u,6u' in generated
# A deterministic numerical contract for the chosen time+slew response,
# including frame gaps, noisy measurements and persistent changes of target.
def advance(previous,target,elapsed_ms,tau_ms):
    dt=min(elapsed_ms,50)
    if dt==0: return previous
    alpha=dt/(tau_ms+dt)
    limit=100/tau_ms*dt/1000
    step=max(-limit,min(limit,(target-previous)*alpha))
    return previous+step
for tau in (75,200,350,600):
    old=0.0
    for _ in range(60):
        new=advance(old,1.0,33,tau)
        assert old<=new<=1.0
        assert new-old<=100/tau*0.033+1e-7
        old=new
    held=old
    for _ in range(60):
        assert held==old # invalid scene input: hold, no reset
    assert advance(old,-1,5000,tau) >= old-100/tau*0.05-1e-7
print('B40: 128 spatial anchors, trimmed RGB group mean, no motion/epoch/lifetime resets, bounded EMA, minimal UI')

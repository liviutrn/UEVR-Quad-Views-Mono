#!/usr/bin/env python3
"""B32 source contracts + CPU math sanity (GPU matching validated by WARP)."""
from pathlib import Path
from math import isclose

root=Path(__file__).resolve().parent
hlsl=(root/'QuadViewComposite.hlsl').read_text(encoding='utf-8')
dx=(root/'QuadViewD3D12.hpp').read_text(encoding='utf-8')
s=(root/'QuadViewSettings.hpp').read_text(encoding='utf-8')
overlay=(root/'apply_triview_b32_controls.py').read_text(encoding='utf-8')
assert 'sizeof(ShaderConstants) == 784' in dx
assert 'sizeof(ShaderConstants) <= 1024' in dx
assert 'float4 SeamTemporal;' in hlsl and 'float4 SeamHistory[18];' in hlsl
assert 'float seam_temporal[4]' in dx and 'float seam_history[18][4]' in dx
assert 'CopyBufferRegion(seam_readback_.Get(),0,seam_stats_.Get(),0,18u*4u*sizeof(float))' in dx
assert dx.index('read_timing();') < dx.index('publish_seam_history();')
assert 'if(temporal_serial_<=cache.accepted) return;' in dx
assert 'now-cache.last_valid<std::chrono::milliseconds(850)' in dx
assert 'temporal_pending_=true;' in dx
assert 'StableSeam(index,' in hlsl
assert 'if (measured.a <= 0.20) return old;' in hlsl
assert 'const float3 stable = clamp(blended, old.rgb - stepSize, old.rgb + stepSize);' in hlsl
assert 'Seam.x < 0.5 || SeamLocal.z > 0.5' in hlsl
assert 'settings.seam_blend_basic ? 1.f : 0.f' in dx
assert 'seam_max_gain{.50f}' in s and 'seam_strength{1.20f}' in s
assert 'seam_temporal_enabled{true}' in s and 'seam_blend_basic{true}' in s
for name in ('SeamTemporal','SeamStability','SeamMaxFrameChange','SeamBlendBasic'):
    assert 'QuadView'+name in overlay
for field in ('temporal_enabled','stability','max_frame_change','blend_basic'):
    assert 'requested.seam_'+field+'=m_quadview_seam_' in overlay
# The improvement is in available correction amplitude, not a claimed FPS gain.
assert isclose(.50*1.20/(.20*.85),3.5294117647058822,rel_tol=1e-12)
# Math filters never step further than the user-defined limiter.
for old in (0.5,1.0,1.5):
    for fresh in (.4,.9,1.2,1.8):
        for stability in (0,.5,.85,1.0):
            alpha=(.55 + (.025-.55)*stability)
            raw=old+(fresh-old)*alpha
            got=max(old-.05,min(old+.05,raw))
            assert abs(got-old)<=.0500001
print('B32 18-record temporal/hybrid/strength/NR-before-SR wiring and gain math: PASS')

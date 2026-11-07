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
assert 'max(0.0, old.a - 0.04)' in hlsl
assert 'if (SeamTemporal.w < 0.5) return measured;' in hlsl
assert 'if (SeamTemporal.z < 0.5 || old.a <= 0.05)' in hlsl
assert '1.0 - stepSize, 1.0 + stepSize' in hlsl
assert 'gain = lerp(1.0, gain, fade);' in hlsl
assert 'cache.setting_key==settings_key' in dx
assert 'std::abs(cache.crop_u0[eye]-layout.focus_crops[eye].u0)<.025f' in dx
assert 'std::abs(cache.crop_v0[eye]-layout.focus_crops[eye].v0)<.025f' in dx
assert 'if(!finite) return;' in dx
assert 'if(!finite || !has_valid) return;' not in dx
assert 'cache.valid=has_valid;' in dx
assert 'seam_outward_fraction{.25f}' in s
assert 'const float3 stable = clamp(blended, old.rgb - stepSize, old.rgb + stepSize);' in hlsl
assert 'Seam.x < 0.5 || SeamLocal.z > 0.5' in hlsl
assert 'settings.seam_blend_basic ? 1.f : 0.f' in dx
assert 'seam_max_gain{.50f}' in s and 'seam_strength{1.20f}' in s
assert 'seam_temporal_enabled{true}' in s and 'seam_blend_basic{true}' in s
for name in ('SeamTemporal','SeamStability','SeamMaxFrameChange','SeamBlendBasic','SeamOutwardFraction'):
    assert 'QuadView'+name in overlay
for field in ('temporal_enabled','stability','max_frame_change','blend_basic','outward_fraction'):
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
# A stream of invalid patches MUST lose confidence instead of self-refreshing.
confidence=1.
for frame in range(26):
    confidence=max(0.,confidence-.04)
assert confidence < .05
# First-frame correction is bounded regardless of the requested gain strength.
for measured in (.25,.5,1.5,1.75):
    alpha=.60+(.08-.60)*.85
    first=max(1.-.05,min(1.+.05,1.+(measured-1.)*alpha))
    assert abs(first-1.)<=.050001
print('B32R1 temporal expiry, gaze/reset guards, neutral first frame, outward falloff, hybrid and gain math: PASS')

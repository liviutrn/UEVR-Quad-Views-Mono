#!/usr/bin/env python3
"""B41 contracts: parallel B40 sampling keeps B40 maths, neutral fallback,
mode-6 blend shape, hold window, queue pin 4-6, split rejection log, UI."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
s = (root / 'QuadViewComposite.hlsl').read_text()


def body(source, needle):
    i = source.index(needle); p = source.index('{', i); level = 1; j = p + 1
    while level:
        level += (source[j] == '{') - (source[j] == '}')
        j += 1
    return source[i:j]


b = body(s, 'void UpdateEdgeB40(')
# Parallel layout: every lane samples one sub-anchor, lane 0 of a knot combines.
assert 'const uint knot=lane>>2u;' in b and 'const uint sub=lane&3u;' in b
assert 'lane >= 32u' not in b, 'B41 must use all 128 lanes'
assert b.index('GroupMemoryBarrierWithGroupSync();') < b.index('[branch] if (sub==0u)')
assert b.count('GroupMemoryBarrierWithGroupSync();') == 1
assert 'SeamFocusSums[lane+k]' in b and 'k<4u' in b
# B40 maths unchanged.
for keep in ('min(min(q0,q1),min(q2,q3))', 'min(q0,min(q1,q2))', 'count>=2u', 'stamp.w==0x40b04001u',
             'min(elapsed,50u)', 'const float alpha=float(dt)/(tau+float(dt))',
             'stable+=clamp((target-stable)*alpha', 'SeamOutput[outIndex+1u]=float4(stable,1.0)',
             'const uint h=(eye*32u+knot)*3u;', 'const uint outIndex=18u+eye*64u+knot*2u;'):
    assert keep in b, keep
# Neutral fallback, never the raw target.
assert 'float3 stable=float3(0.0,0.0,0.0);' in b
assert 'valid ? target : 0.0' not in b
for forbidden in ('stamp.x!=', 'elapsed>250', 'cropDelta>', 'motionTolerance', '!valid)', 'reset='):
    assert forbidden not in b, forbidden
# Blend shape only in mode 6; shape 1 equals the B40 curve.
assert '(Seam.x>5.5 && EdgeV2.w!=1.0) ? EdgeFadeShaped(distance,EdgeV2.x,EdgeV2.w) : EdgeFade(distance,EdgeV2.x)' in s
h = (root / 'QuadViewD3D12.hpp').read_text()
assert 'constants.edge_v2[3]=settings.seam_mode==6 ? settings.edge_shape : settings.edge_hysteresis;' in h
assert 'sizeof(ShaderConstants) == 512' in h
st = (root / 'QuadViewSettings.hpp').read_text()
assert 'float edge_shape{1.f};' in st and 'scalar(requested.edge_shape,.5f,2.f' in st
assert 'a.edge_shape==b.edge_shape' in st


def fade(d, reach, shape=None):
    t = min(max(d / max(reach, 1.0), 0.0), 1.0)
    if shape is not None:
        t = t ** min(max(shape, .25), 4.0)
    return 1.0 - t * t * (3.0 - 2.0 * t)


for d in range(0, 800, 7):
    assert abs(fade(d, 240) - fade(d, 240, 1.0)) < 1e-12  # shape 1 == B40
    assert fade(d, 720, 2.0) >= fade(d, 720, 1.0) >= fade(d, 720, 0.5) - 1e-12
    assert fade(d, 720) >= fade(d, 240) - 1e-12  # farther reach never weaker

# The parallel combine is the same function of the four sub results as B40's
# loop (results compacted in sub order), including invalid sub-anchors.
import itertools, random
random.seed(41)


def combine(vals):
    q = [v for v in vals if v is not None]
    if len(q) == 4:
        return 0.5 * (sum(q) - min(q) - max(q))
    if len(q) == 3:
        return sum(q) - min(q) - max(q)
    if len(q) == 2:
        return 0.5 * (q[0] + q[1])
    return None


for mask in itertools.product((True, False), repeat=4):
    vals = [random.uniform(-.3, .3) if m else None for m in mask]
    serial = combine(vals)
    lanes = [(1.0, v) if v is not None else (0.0, 0.0) for v in vals]
    parallel = combine([v if a > .5 else None for a, v in lanes])
    assert serial == parallel

if len(sys.argv) > 1:
    mods = Path(sys.argv[1]) / 'src/mods'
    xr = (mods / 'vr/runtimes/OpenXR.cpp').read_text()
    xh = (mods / 'vr/runtimes/OpenXR.hpp').read_text()
    assert 'uevr::quadview::TriViewHold quadview_continuity;' in xh
    assert 'uevr::duoview::SubmitContinuity quadview_continuity' not in xh
    assert 'SubmitContinuity duoview_continuity' in xh or 'duoview_continuity' in xh
    assert '[TriView][BlankFrame]' in xr and '++triview_blank_frames;' in xr
    hold = (mods / 'vr/TriViewHold.hpp').read_text()
    assert 'default_window_ms = 250' in hold and 'max_window_ms = 1000' in hold
    dx = (mods / 'vr/D3D12Component.cpp').read_text()
    assert '(frozen->settings.seam_mode>=4 && frozen->settings.seam_mode<=6) ? comp.edge_submission_queue()' in dx
    assert 'frozen->settings.seam_mode==4 ? comp.edge_submission_queue()' not in dx
    assert 'commands.seam_submission_queue=seam_queue' in dx
    fh = (mods / 'vr/FFakeStereoRenderingHook.cpp').read_text()
    assert 'native_resource={} hook={} hook_device={:x} get_device_hr={:#x}' in fh
    assert 'reason=!owner ? "missing-owner"' in fh  # B25 admission unchanged
    vr = (mods / 'VR.cpp').read_text(); vh = (mods / 'VR.hpp').read_text()
    for name in ('QuadViewB41HoldMs', 'QuadViewB41BlendDistance', 'QuadViewB41BlendShape'):
        assert name in vh, name
    assert '*m_quadview_b41_hold_ms, *m_quadview_b41_reach_scale, *m_quadview_b41_shape,' in vh
    assert 'TriViewHold::set_window_ms(' in vr
    assert 'requested.edge_reach_px=std::min(m_quadview_edge_reach->value()*m_quadview_b41_reach_scale->value(),1024.f);' in vr
    assert '[TriView][Build] B41' in vr
    gen = (mods / 'vr/QuadViewSettings.hpp').read_text()
    assert 'edge_shape' in gen
print('B41: parallel B40 sampling (same maths), neutral fallback, blend distance/shape, hold window, queue pin 4-6, split rejection log')

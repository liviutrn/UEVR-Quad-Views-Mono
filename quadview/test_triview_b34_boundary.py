#!/usr/bin/env python3
"""Verify generated B34 UI, resource identity, stateless seam and GPU contracts."""
from pathlib import Path
import sys
root=Path(sys.argv[1])/"src/mods"
v=(root/"VR.cpp").read_text()
h=(root/"VR.hpp").read_text()
d=(root/"vr/QuadViewD3D12.hpp").read_text()
s=Path(__file__).with_name("QuadViewComposite.hlsl").read_text()
q=Path(__file__).with_name("QuadViewSettings.hpp").read_text()
assert 's_quadview_seam_mode_names, 3)' in h and 'Boundary B34' in h
assert 'QuadViewBoundaryMode' in h and 'generate_name("QuadViewSeamMode")' not in h
assert 'm_quadview_seam_mode->value()>=2' in v and 'requested.seam_mode=' in v
assert 'unsigned_integer(requested.seam_mode,0u,3u' in q
assert 'sizeof(ShaderConstants) == 480' in d and 'sizeof(ShaderConstants) <= 512' in d
assert 'const bool analyze = settings.seam_mode >= 2 &&' in d
assert 'const float darkGuard = saturate(dot(color.rgb, GlamLuma) * 4.0);' in s
assert 'Seam.x > 2.5' in s and 'float3(1.0, 0.0, 0.0)' in s
assert s.count('CSSeam(')==1 and 'GroupMemoryBarrierWithGroupSync()' in s
assert 'if (Seam.x < 0.5) return FocusWeight(uv, crop)' in s
assert s.count('CorrectFocusColor(')==3
for forbidden in ('seam_readback_','publish_seam_history','SeamTemporal'):
    assert forbidden not in d and forbidden not in s
print("B34 PASS: generated UI, B31 anti-vignette, 480-byte constants, no B32 history")

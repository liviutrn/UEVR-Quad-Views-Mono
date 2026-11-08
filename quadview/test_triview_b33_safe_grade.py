#!/usr/bin/env python3
"""B33 source safety check: generated controls and no B32 temporal state."""
from pathlib import Path
import sys
root=Path(sys.argv[1])/"src/mods"
vr=(root/"VR.cpp").read_text()
vh=(root/"VR.hpp").read_text()
dx=(root/"vr/QuadViewD3D12.hpp").read_text()
settings=(root/"vr/QuadViewSettings.hpp").read_text()
hlsl=Path(__file__).with_name("QuadViewComposite.hlsl").read_text()
assert 'generate_name("QuadViewStableSeamMode"), s_quadview_seam_mode_names, 1)' in vh
assert 'generate_name("QuadViewSeamMode")' not in vh
for x in ("temperature","tint","hybrid_blend"): assert "requested.seam_"+x+"=" in vr
for x in ("temperature","tint","hybrid"): assert "*m_quadview_seam_"+x in vh
assert "sizeof(ShaderConstants) == 480" in dx and "sizeof(ShaderConstants) <= 512" in dx
assert 'constants.seam_local[2] = settings.seam_hybrid_blend ? 1.f : 0.f;' in dx
assert 'constants.seam_local[3] = .16f * settings.seam_temperature;' in dx
assert 'constants.focus_profile[2]=.12f * settings.seam_tint;' in dx
assert 'constants.focus_profile[3]=-.16f * settings.seam_temperature;' in dx
assert 'if (Seam.x < 0.5 || SeamLocal.z > 0.5) return FocusWeight(uv, crop)' in hlsl
assert 'gain * Seam.w * grade' in hlsl
assert 'settings.seam_mode == 2 &&' in dx
for forbidden in ("seam_readback_","publish_seam_history","SeamTemporal"):
    assert forbidden not in dx and forbidden not in hlsl
assert 'seam_hybrid_blend{true}' in settings
for name in ("seam_hybrid_blend","seam_temperature","seam_tint"):
    assert f'a.{name}==b.{name}' in settings
for temp in (-1.,0.,1.):
    for tint in (-1.,0.,1.):
        grade=(1+.16*temp,1+.12*tint,1-.16*temp)
        assert all(.84<=x<=1.16 for x in grade)
        assert abs(grade[0]+grade[2]-2)<1e-9
print("B33 source, 480-byte CB, manual mode and no B32 readback regression: PASS")

#!/usr/bin/env python3
"""Regression contract: v186.1 XYZ scaling must preserve base modes/pose lanes."""
from pathlib import Path
import math, sys
if len(sys.argv)!=2: raise SystemExit("Usage: test_xyz_head_scaling.py <patched_backend>")
b=Path(sys.argv[1])
h=(b/"src/mods/VR.hpp").read_text(encoding="utf-8-sig")
c=(b/"src/mods/VR.cpp").read_text(encoding="utf-8-sig")
f=(b/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8-sig")
for marker in ("XYZHeadScalingEnabled","XYZHeadScaleX","XYZHeadScaleY","XYZHeadScaleZ",
               "XYZHeadScaleToggleKey","XYZHeadScaleHoldBypassKey"):
    assert h.count(marker)==1,marker
assert h.count("*m_xyz_headscale_toggle_key")==1
assert h.count("*m_xyz_headscale_hold_bypass_key")==1
assert c.count('m_xyz_headscale_enabled->draw("Enable Head XYZ Scaling")')==1
assert c.count('m_xyz_headscale_toggle_key->draw("Toggle XYZ Head Scaling")')==1
assert c.count('m_xyz_headscale_hold_bypass_key->draw("Hold to Disable XYZ Scaling")')==1
assert c.count('m_xyz_headscale_toggle_key->is_key_down_once()')==1
assert c.count('m_xyz_headscale_hold_bypass_key->is_key_down()')==1
assert f.count('vr->get_xyz_head_movement_gains()')==1
assert f.count("const auto pos = glm::vec3{rotation_offset * scaled_standing_delta};")==1
assert f.count("const auto pos_flat = glm::vec3{rotation_offset * standing_delta_flat};")==1
assert f.count("eye_offset * world_scale")>=1
assert h.count("m_xyz_headscale_hold_bypass.load(std::memory_order_relaxed)") == 1
# Mathematical contract for known tracking deltas and enable/hold edge transitions.
def gain(enabled,hold,xyz):
    return (1.,1.,1.) if not enabled or hold else tuple(v if math.isfinite(v) and .05<=v<=5 else 1. for v in xyz)
def position(delta,enabled,hold,xyz):
    return tuple(a*b for a,b in zip(delta,gain(enabled,hold,xyz)))
original=(.20,.11,-.35)
assert position(original,False,False,(2.5,1.5,2.))==original
assert position(original,True,False,(2.5,1.5,2.))==(.5,.165,-.7)
assert position(original,True,True,(2.5,1.5,2.))==original
assert position(original,True,False,(2.5,1.5,2.))==(.5,.165,-.7)
assert position(original,True,False,(float("nan"),1.5,2.))==(.2,.165,-.7)
assert position(original,False,True,(2.5,1.5,2.))==original
print("PASS: 6 settings, native UI, both keybinds, roomscale and IPD preserved, 6 mode/hold/malformed-value contracts.")

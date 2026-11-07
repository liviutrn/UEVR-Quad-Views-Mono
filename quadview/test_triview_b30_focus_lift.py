#!/usr/bin/env python3
"""Final focus-lift source wiring; executable/WARP tests verify its behavior."""
from pathlib import Path
import sys

root=Path(sys.argv[1])/'src/mods'
h=(root/'VR.hpp').read_text()
v=(root/'VR.cpp').read_text()
d=(root/'vr/QuadViewD3D12.hpp').read_text()
s=Path(__file__).with_name('QuadViewComposite.hlsl').read_text()
for field in ('focus_lift_enabled','focus_brightness','focus_lift_strength','focus_corner_gain','focus_lift_onset','focus_lift_power'):
    assert 'requested.'+field+'=' in v, field
    assert '*m_quadview_'+field in h, field
assert 'FocusLiftEnabled"), true)' in h, 'Shipping UI must start with the calibrated correction enabled'
assert (root/'vr/QuadViewFocusLift.hpp').read_text()==Path(__file__).with_name('QuadViewFocusLift.hpp').read_text()
assert 'sizeof(ShaderConstants) == 784' in d and 'sizeof(ShaderConstants) <= 1024' in d
assert 'range.NumDescriptors = 6;' in d and 'heap.NumDescriptors = 7;' in d
assert 'commands->Dispatch(2, 1, 1)' in d
assert 'focus.rgb = CorrectFocusColor(focus.rgb, focusUv)' in s
assert s.count('CorrectFocusColor(')==3 # definition, display, adaptive reference
assert 'gain *= 1.0+FocusLift.z*FocusProfile.y*pow(t,FocusProfile.x);' in s
assert 'r2 > FocusLift.w && FocusLift.z*FocusProfile.y > 0.0' in s
assert 'Compositor command slot has not retired' in d
assert 'if (owner_) return fail("Cannot recreate an in-flight compositor")' in d
print('B30 focus-only integration: enabled shipping preset, frozen controls, corrected adaptive reference, bounded slot-local resources, 784/1024-byte constants')

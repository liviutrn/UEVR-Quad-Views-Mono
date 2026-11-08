#!/usr/bin/env python3
"""B30 final generated seam integration and resource-order contracts."""
from pathlib import Path
import sys

root=Path(sys.argv[1])/'src/mods'
vr=(root/'VR.cpp').read_text()
vh=(root/'VR.hpp').read_text()
settings=(root/'vr/QuadViewSettings.hpp').read_text()
dx=(root/'vr/QuadViewD3D12.hpp').read_text()
shader=Path(__file__).with_name('QuadViewComposite.hlsl').read_text()
for field in ('mode','strength','max_gain','brightness_ev','color_strength','transition_px','debug','local_strength','radius_px'):
    assert f'requested.seam_{field}=' in vr, field
    assert f'*m_quadview_seam_{field}' in vh, field
for field in ('focus_lift_enabled','focus_brightness','focus_lift_strength','focus_corner_gain','focus_lift_onset','focus_lift_power'):
    assert 'requested.'+field+'=' in vr, field
assert 's_quadview_seam_mode_names, 2)' in vh, 'Shipping seam mode must start Adaptive'
assert 'sizeof(ShaderConstants) == 480' in dx and 'sizeof(ShaderConstants) <= 512' in dx
assert 'heap.NumDescriptors = 7;' in dx and 'range.NumDescriptors = 6;' in dx
assert 'match_srv.Buffer.NumElements = 18;' in dx and 'match_uav.Buffer.NumElements = 18;' in dx
assert 'owner_) return fail("Cannot recreate an in-flight compositor")' in dx
assert 'Compositor command slot has not retired' in dx
assert 'D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE' in dx
dispatch=dx.index('commands->Dispatch(2, 1, 1)')
assert dx.index('SetComputeRootDescriptorTable(2, uav)')<dispatch
assert dispatch<dx.index('D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE',dispatch)<dx.index('commands->DrawInstanced(',dispatch)
assert 'ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,3,' in dx
assert 'settings.seam_mode >= 2 &&' in dx and 'settings.diagnostic_view == 0 &&' in dx
assert '(settings.seam_strength > 0.f || settings.seam_debug)' in dx
assert 'StructuredBuffer<float4> SeamMatch : register(t5)' in shader
assert '[numthreads(128, 1, 1)]' in shader and 'SeamOutput[eye * 9u]' in shader
assert 'SeamOutput[eye * 9u + 1u + lane / 16u]' in shader
assert 'GroupMemoryBarrierWithGroupSync()' in shader
assert 'if (SeamOptions.w <= 0.5)' in shader and 'fill == 0.0' in shader
assert 'if (lane < 9u) SeamOutput[eye * 9u + lane]' in shader
assert 'if (Seam.x < 0.5) return FocusWeight(uv, crop)' in shader
assert 'if (width <= 0.0) return 1.0' in shader
assert shader.count('CorrectFocusColor(')==3 # function, displayed focus, analysis reference
assert 'FocusProfile.x' in shader and 'if (FocusLift.x > 0.5)' in shader
assert 'return ReadContext(eye, contextSource, contextRect, eyeUv);' in shader
print('B30 final seam integration passed: persisted frozen controls, slot-local bounded buffers, compute/raster ordering, diagnostics and OFF path')

#!/usr/bin/env python3
"""B41 contracts: shader/compositor/settings identical to B40; hold window,
queue pin 4-6, split rejection log, blend distance UI, build log."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
h = (root / 'QuadViewD3D12.hpp').read_text()
assert 'constants.edge_v2[3]=settings.edge_hysteresis;' in h
assert 'edge_shape' not in (root / 'QuadViewSettings.hpp').read_text()
s = (root / 'QuadViewComposite.hlsl').read_text()
assert 'EdgeFadeShaped' not in s and 'float3 stable=valid ? target : 0.0;' in s  # B40 shader

if len(sys.argv) > 1:
    mods = Path(sys.argv[1]) / 'src/mods'
    xr = (mods / 'vr/runtimes/OpenXR.cpp').read_text()
    xh = (mods / 'vr/runtimes/OpenXR.hpp').read_text()
    assert 'uevr::quadview::TriViewHold quadview_continuity;' in xh
    assert 'uevr::duoview::SubmitContinuity quadview_continuity' not in xh
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
    for name in ('QuadViewB41HoldMs', 'QuadViewB41BlendDistance'):
        assert name in vh, name
    assert 'QuadViewB41BlendShape' not in vh
    assert 'TriViewHold::set_window_ms(' in vr
    assert 'requested.edge_reach_px=std::min(m_quadview_edge_reach->value()*m_quadview_b41_reach_scale->value(),1024.f);' in vr
    assert '[TriView][Build] B41' in vr
    hk = (Path(sys.argv[1]) / 'src/hooks/D3D12Hook.cpp').read_text()
    assert 'swap_chain->GetDevice(IID_PPV_ARGS(&d3d12->m_device));' not in hk
    assert 'if (present_device != nullptr) d3d12->m_device = present_device;' in hk
print('B41: B40 shader kept, hold window, queue pin 4-6, split rejection log, blend distance, build log')

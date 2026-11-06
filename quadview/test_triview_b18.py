#!/usr/bin/env python3
"""Final generated production integration gate (supplements behavioral tests)."""
from pathlib import Path
import re
import sys
root=Path(sys.argv[1])/'src/mods'
overlay=Path(__file__).parent
read=lambda p:p.read_text(encoding='utf-8')
for actual,canonical in [('QuadViewNativeDelivery.hpp','QuadViewNativeDelivery.hpp'),
                         ('QuadViewDepthIdentity.hpp','QuadViewDepthIdentity.hpp'),
                         ('QuadViewNgxDepth.hpp','QuadViewNgxDepthB18.hpp'),
                         ('QuadViewResourceReuse.hpp','QuadViewResourceReuse.hpp'),
                         ('TriViewAdmission.hpp','TriViewAdmission.hpp')]:
    assert read(root/'vr'/actual)==read(overlay/canonical),f'Production/test source divergence: {actual}'
hook=read(root/'vr/FFakeStereoRenderingHook.cpp')
consumer=read(root/'vr/D3D12Component.cpp')
header=read(root/'vr/FFakeStereoRenderingHook.hpp')
vr=read(root/'VR.cpp')
assert 'BootstrapViewCount bootstrap_views{views.count}' in hook
assert 'qv_native_ready && native_callback &&' in hook
assert '(!qv_native_ready || native_callback)' not in hook
assert 'native_triview_publishable(frozen->layout.shared_context' in consumer
assert 'auto_snapshot_done' not in consumer
assert 'snapshot_requested().store(true)' not in consumer
assert 'uevr::quadview::dx12::snapshot_requested().store(true)' in vr
assert 'latest_approximate_since(packet->depth_not_before)' in consumer
assert 'PeripheryDepth::self().latest()' not in consumer
assert 'depth_not_before{std::chrono::steady_clock::now()}' in header
assert 'ImGuiWindowFlags_NoScrollWithMouse' in read(root/'vr/QuadViewStatusPanel.hpp')
assert 'triview_newest_pose_location' in read(root/'vr/runtimes/OpenXR.hpp')
for p in (root/'vr').glob('*'):
    if p.suffix not in ('.hpp','.cpp'):continue
    for name in re.findall(r'^\s*#include\s+"((?:QuadView|TriView)[^"/]+\.hpp)"',read(p),re.M):
        if name=='QuadViewShaderBytecode.hpp':continue # compiled immediately after this gate
        assert (root/'vr'/name).is_file(),f'Missing generated export {name}'
print('B18 final generated integration: canonical parity, native-only sources, B15 pose/UI and all exports verified')

#!/usr/bin/env python3
"""Final B29 wiring and unchanged depth-safety checks; not a hardware test."""
from pathlib import Path
import sys

root=Path(sys.argv[1])/'src/mods'
hook=(root/'vr/FFakeStereoRenderingHook.cpp').read_text()
depth=(root/'vr/QuadViewNgxDepth.hpp').read_text()
vr=(root/'VR.cpp').read_text()
assert hook.count('uevr::head_movement::scale_translation(')==1
assert 'rotation_offset, glm::vec3{standing_delta}, xyz_gains)' in hook
assert 'scaled_standing_delta' not in hook
assert 'const auto pos_flat = glm::vec3{rotation_offset * standing_delta_flat};' in hook
assert 'eye_offset * world_scale' in hook
assert 'Turning your head does not rotate the scaling axes.' in vr
assert (root/'vr/HeadMovementScaling.hpp').read_bytes()==Path(__file__).with_name('HeadMovementScaling.hpp').read_bytes()
enabled=depth.split('    void set_enabled(bool on) {',1)[1].split('\n    }',1)[0]
assert enabled.index('if (on) return;')<enabled.index('std::scoped_lock lock(mutex_)')
assert 'prune_locked(want_w_.load(),want_h_.load(),true);' in enabled
assert 'now < next_install_retry_' in depth
assert 'next_install_retry_ = now + std::chrono::seconds(1);' in depth
inspect=depth.split('    std::shared_ptr<DepthSnapshot> inspect(',1)[1].split('    void submitted(',1)[0]
assert inspect.index('!matches_periphery(')<inspect.index('install_reset(cmd)')<inspect.index('cmd->CopyTextureRegion(')
assert depth.count('if (!install_reset(cmd))')==1
assert 'now - slot->submitted_at < std::chrono::milliseconds(250)' in depth
assert '(!slot->foreign_queue || depth_copy_complete(completed, slot->producer_fence_value))' in depth
assert 'depth_slot_reusable(candidate->pending,candidate->submitted,completed,' in depth
assert 'if (pool_.size() >= MaxSlots)' in depth and 'MaxSlots = 12' in depth
for name in ('reset_list(', 'execute_commands('):
    body=depth.split('static '+('HRESULT __stdcall ' if name=='reset_list(' else 'void __stdcall ')+name,1)[1]
    assert body.index('submission_sequence_.acquire()')<body.index('unsafe_call')<body.index('std::scoped_lock lock(s.mutex_)')
print('B29 generated checks: recentered axes, unchanged roomscale/IPD, bounded hook discovery, unchanged depth age/fence/pool safety')

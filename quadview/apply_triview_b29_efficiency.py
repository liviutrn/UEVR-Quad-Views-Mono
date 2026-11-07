#!/usr/bin/env python3
"""B29: axis-correct head translation and bounded depth housekeeping.

Apply after every B28 overlay. Does not change crop, ownership, depth-age or
queue completion rules. Validate all anchors before writing generated files.
"""
from pathlib import Path
import sys


def once(s, old, new):
    if s.count(old) != 1:
        raise RuntimeError(f'B29: expected one anchor, got {s.count(old)}: {old[:100]!r}')
    return s.replace(old, new, 1)


def patch_hook(s):
    s = '#include "HeadMovementScaling.hpp"\n' + s
    return once(s, '''        const glm::vec3 scaled_standing_delta{
            standing_delta.x * xyz_gains.x,
            standing_delta.y * xyz_gains.y,
            standing_delta.z * xyz_gains.z
        };
        const auto pos = glm::vec3{rotation_offset * scaled_standing_delta};''', '''        const auto pos = uevr::head_movement::scale_translation(
            rotation_offset, glm::vec3{standing_delta}, xyz_gains);''')


def patch_ui(s):
    return once(s,
        'Scales only HMD translation relative to the existing standing origin. Rotation, eye separation, controller poses and World Scale are unchanged. Set toggle and hold-bypass keys in Keybinds.',
        'Scales HMD translation along recentered player axes: X left/right, Y up/down, Z forward/back. Recenter while facing forward. Turning your head does not rotate the scaling axes. Rotation, eye separation, controller poses and World Scale are unchanged. Set toggle and hold-bypass keys in Keybinds.')


def patch_depth(s):
    s = once(s, '''        enabled_.store(on && capture_supported(), std::memory_order_release);
        std::scoped_lock lock(mutex_);
        prune_locked(want_w_.load(),want_h_.load(),!on);''', '''        enabled_.store(on && capture_supported(), std::memory_order_release);
        // Active capture already prunes on the recording path. Avoid a
        // duplicate pool/fence scan on every Present while capture is on.
        if (on) return;
        std::scoped_lock lock(mutex_);
        prune_locked(want_w_.load(),want_h_.load(),true);''')
    s = once(s, '''        std::scoped_lock install_lock(hook_install_mutex_);
        if (!queue_ && queue->GetDesc().Type''', '''        std::scoped_lock install_lock(hook_install_mutex_);
        const auto now = std::chrono::steady_clock::now();
        // Missing/delayed NGX exports still retry. Once queue/fence tracking
        // exists, DLL/export discovery need not take the loader lock every
        // Present. This gate never delays recording/submission bookkeeping.
        if (queue_ && execute_ok_ && fence_ && now < next_install_retry_) return;
        next_install_retry_ = now + std::chrono::seconds(1);
        if (!queue_ && queue->GetDesc().Type''')
    s = once(s, '    std::vector<std::shared_ptr<DepthSnapshot>> pool_{};',
        '    std::chrono::steady_clock::time_point next_install_retry_{}; // hook_install_mutex_\n'
        '    std::vector<std::shared_ptr<DepthSnapshot>> pool_{};')
    # Foveal DLSS evaluations cannot record an owned peripheral copy. Avoid
    # their reset-hook lock entirely; matching evaluations retain the check.
    s = once(s, '        if (!install_reset(cmd)) { reject(RecordingHookUnavailable); return {}; }\n', '')
    return once(s, '''        {
            std::scoped_lock lock(mutex_);
            const auto found = feature_kind_.find''', '''        if (!install_reset(cmd)) { reject(RecordingHookUnavailable); return {}; }
        {
            std::scoped_lock lock(mutex_);
            const auto found = feature_kind_.find''')


def main():
    root = Path(sys.argv[1]) / 'src/mods'
    transforms = {
        root/'vr/FFakeStereoRenderingHook.cpp': patch_hook,
        root/'VR.cpp': patch_ui,
        root/'vr/QuadViewNgxDepth.hpp': patch_depth,
    }
    changed = {p: fn(p.read_text(encoding='utf-8')) for p, fn in transforms.items()}
    helper = Path(__file__).with_name('HeadMovementScaling.hpp').read_text(encoding='utf-8')
    for path, content in changed.items():
        path.write_text(content, encoding='utf-8', newline='\n')
    (root/'vr/HeadMovementScaling.hpp').write_text(helper, encoding='utf-8', newline='\n')
    print('B29: recentered XYZ scaling; reduced repeated depth housekeeping; fence/age/lifetime rules unchanged')


if __name__ == '__main__':
    main()

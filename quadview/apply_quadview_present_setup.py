#!/usr/bin/env python3
"""Separate presentation reset fences from mode-transition engine drainage.

Apply after every Build50 overlay. Engine source leases and mode-transition
retirement stay unchanged. This patch never clears the engine delivery ledger.
"""
from pathlib import Path
import shutil
import sys


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Build51 expected one source anchor: {old[:100]!r}")
    return text.replace(old, new, 1)


def main():
    root = Path(sys.argv[1])
    source = Path(__file__).resolve().parent
    base = root / 'src/mods/vr'
    hp = base / 'D3D12Component.hpp'
    cp = base / 'D3D12Component.cpp'
    h, c = hp.read_text(), cp.read_text()
    if 'RetirementScope scope' in h:
        raise RuntimeError('Build51 overlay already applied')
    h = once(h, '#include "Stalker2NativeD3D12.hpp"',
             '#include "Stalker2NativeD3D12.hpp"\n#include "QuadViewRetirement.hpp"')
    h = once(h, '    bool mono_consumers_retired();',
             '    bool mono_consumers_retired(uevr::quadview::RetirementScope scope =\n'
             '        uevr::quadview::RetirementScope::mode_transition);')
    c = once(c, 'bool D3D12Component::mono_consumers_retired() {',
             'bool D3D12Component::mono_consumers_retired(uevr::quadview::RetirementScope scope) {')
    c = once(c, '''    const auto vr=VR::get();
    if (vr && vr->is_quadview_mode_selected()) {''', '''    const auto vr=VR::get();
    // Engine target leases are independent of the presentation allocations
    // rebuilt by setup(). Waiting for an active producer here starves setup.
    // Mode changes still close admission and drain every engine owner.
    if (uevr::quadview::requires_engine_retirement(scope) && vr && vr->is_quadview_mode_selected()) {''')
    start = c.index('vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {')
    end = c.index('\nvoid D3D12Component::reset_frame_timing_stats()', start)
    frame = c[start:end]
    if frame.count('!mono_consumers_retired()') != 2:
        raise RuntimeError('Expected exactly two presentation setup fence polls')
    frame = frame.replace('!mono_consumers_retired()',
        '!mono_consumers_retired(uevr::quadview::RetirementScope::presentation)')
    frame = once(frame, '    const auto ui_alpha_allowed = [vr] {', '''    const char* qv_present_stage="entered";
    if (vr->is_quadview_mode_selected()) {
        uevr::quadview::HookTraceRecord r{};
        r.event="PRESENT_ENTER";r.reason="d3d12_on_frame";
        r.generation=vr->mono_generation();r.owner_generation=m_mono_generation;r.mode=7;
        r.frame=static_cast<uint32_t>(vr->m_frame_count);
        r.result=m_force_reset?1:0;uevr::quadview::emit_hook_trace(29,r);
    }
    utility::ScopeGuard qv_present_exit{[&]() {
        if (!vr->is_quadview_mode_selected()) return;
        uevr::quadview::HookTraceRecord r{};
        r.event="PRESENT_RETURN";r.reason=qv_present_stage;
        r.generation=vr->mono_generation();r.owner_generation=m_mono_generation;r.mode=7;
        r.frame=static_cast<uint32_t>(vr->m_frame_count);
        r.result=m_force_reset?1:0;uevr::quadview::emit_hook_trace(30,r);
    }};
    const auto ui_alpha_allowed = [vr] {''')
    frame = once(frame, '    if (m_mono_generation != vr->mono_generation()) {',
        '    qv_present_stage="generation_presentation_fences";\n    if (m_mono_generation != vr->mono_generation()) {')
    frame = once(frame, '    if (m_force_reset || m_last_afr_state != vr->is_using_afr()) {',
        '    qv_present_stage="reset_presentation_fences";\n    if (m_force_reset || m_last_afr_state != vr->is_using_afr()) {')
    frame = once(frame, '        if (!setup()) {',
        '        qv_present_stage="setup_failed";\n        if (!setup()) {')
    frame = once(frame, '    if (vr->mono_frame_gate_required() && !vr->is_duoview_renderer_active()) {',
        '    qv_present_stage="mono_pose_gate";\n    if (vr->mono_frame_gate_required() && !vr->is_duoview_renderer_active()) {')
    frame = once(frame, '    hook->set_next_present_interval(0);',
        '    qv_present_stage="scene_resources";\n    hook->set_next_present_interval(0);')
    frame = once(frame, '                    if (vr->is_quadview_mode_selected()) {',
        '                    qv_present_stage="quadview_source_selection";\n                    if (vr->is_quadview_mode_selected()) {')
    # Covers gates between source acquisition and copy without changing them.
    frame = once(frame, '    m_mono_block_post_present = false;',
        '    qv_present_stage="presentation_initialized";\n    m_mono_block_post_present = false;')
    c = c[:start] + frame + c[end:]
    c = once(c, '''    if (vr->mono_generation() != 0 && !mono_consumers_retired()) { return false; }
    on_reset(vr.get(), true);''', '''    if (vr->mono_generation() != 0 &&
        !mono_consumers_retired(uevr::quadview::RetirementScope::presentation)) { return false; }
    on_reset(vr.get(), true);''')
    # A shared native tail may complete a quartet. Report the actual result,
    # rather than interpreting unpopulated scalar mask fields as failure.
    fp = base / 'FFakeStereoRenderingHook.cpp'
    f = fp.read_text()
    f = once(f, '''                    qv_emit_rhi(14,"NATIVE_EXECUTION","executed_tail",0,execution.accepted?1:0);''', '''                    qv_emit_rhi(14,"NATIVE_EXECUTION","executed_tail",0,execution.accepted?1:0);
                    {
                        auto trace=qv_rhi;trace.event="NATIVE_COMPLETION";
                        trace.reason=execution.quarantined?"quarantined":"eligible";
                        trace.result=execution.accepted?1:0;trace.pending=execution.completed_quartets;
                        trace.canonical_frame=execution.sync_frame;
                        uevr::quadview::emit_hook_trace(31,trace);
                    }''')
    hp.write_text(h)
    cp.write_text(c)
    fp.write_text(f)
    shutil.copyfile(source / 'QuadViewRetirement.hpp', base / 'QuadViewRetirement.hpp')
    print('Applied Build51 presentation retirement scope and output-path diagnostics.')


if __name__ == '__main__':
    main()

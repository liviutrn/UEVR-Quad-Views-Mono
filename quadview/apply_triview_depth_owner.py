#!/usr/bin/env python3
"""B10 conservative NGX owner wiring. Run after B9 bootstrap/stability.

This scope authenticates evaluations actually observed inside one retained RHI
callback. It does not assign preceding or parallel RDG commands to that owner.
Mixed-role tails deliberately produce no capture identity.
"""
from pathlib import Path
import shutil
import sys


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Depth owner anchor count {text.count(old)}: {old[:100]!r}')
    return text.replace(old, new, 1)


def hook(text):
    text=once(text, '#include "FFakeStereoRenderingHook.hpp"',
        '#include "FFakeStereoRenderingHook.hpp"\n#include "QuadViewDepthIdentity.hpp"')
    anchor='        auto call_orig = [=]() {\n'
    text=once(text, anchor, '''        // This identity belongs only to the actual retained original callback.
        // Earlier commands and parallel RDG tasks cannot inherit it by timing.
        const auto qv_depth_owner=[&]() {
            uevr::quadview::ngx::DepthOwner identity{};
            if (N!=correct_execute_index || !quad_native || quad_drain.count ||
                !quad_native_record.owner_count) return identity;
            const auto& first=quad_native_record.owners[0];
            if (!first || first.view!=0 || !first.source.engine_frame_bound ||
                first.source.generation!=vr->mono_generation()) return identity;
            for (size_t i=0;i<quad_native_record.owner_count;++i) {
                const auto& owner=quad_native_record.owners[i];
                if (!owner || owner.view!=0 || !owner.source.same_owner(first.source) ||
                    !owner.engine.same_owner(first.engine) || owner.target_set!=first.target_set ||
                    owner.target!=first.target) return identity;
            }
            if ((quad_engine && !quad_engine.same_owner(first.engine)) ||
                (quad_source && !quad_source.same_owner(first.source))) return identity;
            const auto frozen=first.source.packet->producer;
            if (!frozen || !frozen->layout.shared_context ||
                frozen->key.generation!=first.source.generation || frozen->key.draw_serial!=first.source.serial ||
                first.source.packet->native_target_set_generation!=first.target_set) return identity;
            identity.generation=first.source.generation;
            identity.serial=first.source.serial;
            identity.engine_frame=first.source.engine_frame;
            identity.target_set=first.target_set;
            identity.role=0;
            identity.output_width=frozen->layout.views[0].width;
            identity.output_height=frozen->layout.views[0].height;
            identity.projection=frozen->projections[0];
            identity.unambiguous=true;
            return identity;
        }();

'''+anchor)
    line='            const auto result = func(cmd, cmd_list, debug_context, r9, stack_1, stack_2, stack_3, stack_4, stack_5, stack_6, stack_7, stack_8);'
    text=once(text,line,'''            const auto result = [&]() {
                const uevr::quadview::ngx::DepthOwnerScope depth_scope{qv_depth_owner};
                return func(cmd, cmd_list, debug_context, r9, stack_1, stack_2, stack_3, stack_4, stack_5, stack_6, stack_7, stack_8);
            }();''')
    return text


def consumer(text):
    line='                                if (const auto snapshot=uevr::quadview::ngx::PeripheryDepth::self().latest()) {'
    text=once(text,
        '                                    depth_input.srv_format=snapshot->srv_format;',
        '                                    depth_input.srv_format=snapshot->srv_format;\n'
        '                                    depth_input.jitter_uv[0]=snapshot->jitter_uv[0];\n'
        '                                    depth_input.jitter_uv[1]=snapshot->jitter_uv[1];\n'
        '                                    depth_input.jitter_valid=snapshot->jitter_valid;')
    return once(text,line,'''                                uevr::quadview::ngx::DepthOwner expected_depth{};
                                expected_depth.generation=source->generation;
                                expected_depth.serial=source->serial;
                                expected_depth.engine_frame=source->engine_frame;
                                expected_depth.target_set=packet->native_target_set_generation;
                                expected_depth.role=0;
                                expected_depth.output_width=frozen->layout.views[0].width;
                                expected_depth.output_height=frozen->layout.views[0].height;
                                expected_depth.projection=frozen->projections[0];
                                expected_depth.unambiguous=source->engine_frame_bound;
                                if (const auto snapshot=uevr::quadview::ngx::PeripheryDepth::self().for_source(expected_depth)) {''')


def main():
    if len(sys.argv)!=3:
        raise SystemExit('Usage: apply_triview_depth_owner.py <backend> <quadview-dir>')
    root,overlay=map(Path,sys.argv[1:])
    h=root/'src/mods/vr/FFakeStereoRenderingHook.cpp'
    c=root/'src/mods/vr/D3D12Component.cpp'
    # Transform both before publishing either to avoid a partial anchor replay.
    hs,cs=hook(h.read_text()),consumer(c.read_text())
    shutil.copy2(overlay/'QuadViewDepthIdentity.hpp',root/'src/mods/vr/QuadViewDepthIdentity.hpp')
    h.write_text(hs);c.write_text(cs)
    print('B10 exact role-0 owner scope and exact-source depth lookup applied (coverage unverified).')

if __name__=='__main__': main()

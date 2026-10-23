#!/usr/bin/env python3
"""Build53: alternate the first actual native renderer call, never history IDs.

Apply after Build52 shading. This intentionally does NOT reorder earlier UE
view construction or rewrite StereoViewIndex/FSceneViewState pointers.
"""
from pathlib import Path
import shutil
import sys


def once(s, old, new):
    if s.count(old) != 1:
        raise RuntimeError(f'Render-order overlay expected one anchor: {old[:110]!r}')
    return s.replace(old, new, 1)


def main():
    root=Path(sys.argv[1]); source=Path(__file__).parent
    paths={name:root/name for name in ('src/mods/VR.hpp','src/mods/VR.cpp',
        'src/mods/vr/FFakeStereoRenderingHook.hpp','src/mods/vr/FFakeStereoRenderingHook.cpp')}
    text={name:p.read_text(encoding='utf-8-sig') for name,p in paths.items()}
    h=text['src/mods/VR.hpp']; v=text['src/mods/VR.cpp']
    hh=text['src/mods/vr/FFakeStereoRenderingHook.hpp']; c=text['src/mods/vr/FFakeStereoRenderingHook.cpp']
    if 'm_quadview_render_order' in h: raise RuntimeError('Render-order overlay already applied')
    h=once(h,'    const ModToggle::Ptr m_quadview_primary_pass{',
        '    const ModInt32::Ptr m_quadview_render_order{ModSliderInt32::create(generate_name("QuadViewRenderOrder"), 0, 3, 3)};\n'
        '    const ModToggle::Ptr m_quadview_primary_pass{')
    h=once(h,'            *m_quadview_primary_pass,','            *m_quadview_render_order,\n            *m_quadview_primary_pass,')
    v=once(v,'            requested.gpu_timing=m_quadview_gpu_timing->value();',
        '            requested.render_order_mode=static_cast<uint32_t>(m_quadview_render_order->value());\n'
        '            requested.gpu_timing=m_quadview_gpu_timing->value();')
    anchor='                m_quadview_primary_pass->draw("Consistent source shading pass (STALKER 2)");\n'
    v=once(v,anchor,anchor+'''                m_quadview_render_order->draw("Fovea-first rendering test");
                ImGui::TextWrapped("0: Original order; 1: Left fovea first; 2: Right fovea first; 3: Alternate fovea first. Both eyes are rendered every source frame. This tests lighting updates; four-view CPU work remains.");
''')
    hh=once(hh,'#include "QuadViewNativeDelivery.hpp"',
        '#include "QuadViewNativeDelivery.hpp"\n#include "QuadViewRenderOrder.hpp"')
    hh=once(hh,'        bool active{},source_registered{}; uint32_t current_slot{},original_count{},engine_frame{0xffffffffu};',
        '        bool active{},source_registered{}; uint32_t current_slot{},first_slot{},last_slot{3},original_count{},engine_frame{0xffffffffu};')
    hh=once(hh,'    static thread_local QuadViewNativeBuildContext quadview_native_build_context;',
        '    static thread_local QuadViewNativeBuildContext quadview_native_build_context;\n'
        '    uevr::quadview::RenderOrderSequence quadview_render_order_sequence{};')
    anchor='        const bool qv_cpu_timing=qv_snapshot->settings.gpu_timing;'
    c=once(c,anchor,'''        const auto qv_order_plan=g_hook->quadview_render_order_sequence.prepare(
            qv_key.generation,qv_key.draw_serial,qv_snapshot->settings.render_order_mode);
        if (!qv_order_plan) {
            vr->set_quadview_status("Native render order rejected a stale or repeated source draw");
            return;
        }
        SPDLOG_INFO_EVERY_N_SEC(2,"[QuadViews][RenderOrder] generation={} draw={} completed_quartets={} mode={} order={},{},{},{} canonical_roles=LC,RC,LF,RF construction_order_unchanged=true",
            qv_key.generation,qv_key.draw_serial,qv_order_plan.sequence,qv_order_plan.mode,
            qv_order_plan.order[0],qv_order_plan.order[1],qv_order_plan.order[2],qv_order_plan.order[3]);
'''+anchor)
    c=once(c,'        native_context={}; native_context.active=true; native_context.current_slot=0;',
        '        native_context={}; native_context.active=true;\n'
        '        native_context.first_slot=static_cast<uint32_t>(qv_order_plan.order.front());\n'
        '        native_context.last_slot=static_cast<uint32_t>(qv_order_plan.order.back());\n'
        '        native_context.current_slot=native_context.first_slot;')
    anchor='        const auto qv_dispatch_result=uevr::quadview::dispatch_main_views('
    c=once(c,anchor,'        size_t qv_dispatch_ordinal{};\n'+anchor)
    c=once(c,'                if (slot!=0) reinterpret_cast<sdk::FScene*>(qv_scene)->decrement_frame_count();',
        '                if (qv_dispatch_ordinal!=0) reinterpret_cast<sdk::FScene*>(qv_scene)->decrement_frame_count();\n'
        '                { uevr::quadview::HookTraceRecord r{};r.event="ORDER_ROLE";r.reason="native_renderer_invocation";\n'
        '                  r.generation=qv_key.generation;r.serial=qv_key.draw_serial;r.role=static_cast<unsigned>(slot);\n'
        '                  r.mode=7;r.index=static_cast<int>(qv_dispatch_ordinal);r.expected_index=static_cast<int>(native_context.first_slot);\n'
        '                  r.target=reinterpret_cast<uintptr_t>(native_context.render_targets[slot]);\n'
        '                  r.root=reinterpret_cast<uintptr_t>(qv_snapshot->views[slot].state);\n'
        '                  uevr::quadview::emit_hook_trace(44+slot,r); }\n'
        '                ++qv_dispatch_ordinal;')
    anchor='''                    view_family->get_render_target()==native_context.render_targets[slot];
            });'''
    c=once(c,anchor,'''                    view_family->get_render_target()==native_context.render_targets[slot];
            },qv_order_plan.order);''')
    anchor='        SPDLOG_INFO_EVERY_N_SEC(2,"[QuadViews][NativeRole][GT] serial={} canonical={} roles={},{},{},{} mask={}",'
    c=once(c,anchor,'''        if (!g_hook->quadview_render_order_sequence.complete(qv_order_plan))
            SPDLOG_ERROR("[QuadViews][RenderOrder] completed source plan identity changed unexpectedly generation={} draw={}",
                qv_key.generation,qv_key.draw_serial);
'''+anchor)
    c=once(c,'                native_context.current_slot!=0) return;',
        '                native_context.current_slot!=native_context.first_slot) return;')
    # Both usable and drain-only packets preserve the same actual last-role
    # cadence boundary. Default mode zero still uses canonical role three.
    anchor='native_context.target_set_generation,native_targets,true);'
    if c.count(anchor)!=2: raise RuntimeError('Expected live and drain-only native bind sites')
    c=c.replace(anchor,'native_context.target_set_generation,native_targets,true,static_cast<uint8_t>(native_context.last_slot));')
    text['src/mods/VR.hpp']=h; text['src/mods/VR.cpp']=v
    text['src/mods/vr/FFakeStereoRenderingHook.hpp']=hh
    text['src/mods/vr/FFakeStereoRenderingHook.cpp']=c
    for name,path in paths.items(): path.write_text(text[name],encoding='utf-8',newline='')
    shutil.copyfile(source/'QuadViewRenderOrder.hpp',root/'src/mods/vr/QuadViewRenderOrder.hpp')
    print('Applied Build53 actual native render-order test; canonical eyes/histories and last-dispatch XR cadence retained.')


if __name__=='__main__': main()

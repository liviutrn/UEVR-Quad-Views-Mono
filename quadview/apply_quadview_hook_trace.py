#!/usr/bin/env python3
"""Build50: bounded observation of the actual production hook adapter.

Apply after Build49 role-frame overlay. No owner admission/retirement, vtable
mutation, synchronization decision or original callback call is changed.
"""
from pathlib import Path
import re
import shutil
import sys
from apply_quadview_native_delivery import replace


RETURNS = [
    'duo_generation_or_mode', 'source_generation', 'engine_generation', 'native_generation',
    'quad_without_owner', 'duo_unowned_recorded_root', 'quad_root_invalid', 'quad_tail_not_found',
    'engine_duplicate_owner', 'engine_foreign_recorded_tail', 'engine_drain_attach_failed',
    'engine_drain_attached', 'native_foreign_recorded_tail', 'native_recovery_attach_failed',
    'native_recovery_attached', 'native_shared_retain_failed', 'recorded_tail_return',
    'duo_root_invalid', 'duo_tail_not_found', 'duo_shared_return', 'tail_vtable_invalid',
    'preserved_pending_return', 'generic_duplicate_return', 'engine_drain_first_attach_failed',
    'engine_source_latch_failed', 'native_first_attach_failed', 'native_owner_lease_failed',
]
NORMAL_RETURNS = {8, 11, 14, 16, 19, 21, 22}


def main():
    root=Path(sys.argv[1]); here=Path(__file__).resolve().parent
    hpath=root/'src/mods/vr/FFakeStereoRenderingHook.hpp'
    h=replace(hpath.read_text(), '#include "QuadViewNativeDelivery.hpp"',
              '#include "QuadViewNativeDelivery.hpp"\n#include "QuadViewHookTrace.hpp"')
    path=root/'src/mods/vr/FFakeStereoRenderingHook.cpp'; s=path.read_text()
    s=replace(s,'namespace {', (here/'hook_trace_runtime.inc').read_text()+'\nnamespace {') if s.count('namespace {')==1 else s.replace('namespace {',(here/'hook_trace_runtime.inc').read_text()+'\nnamespace {',1)
    map_anchor='    static inline std::unordered_map<sdk::FRHICommandBase_New*,QuadDrainBatch> quad_drain_commands{};'
    s=replace(s,map_anchor,map_anchor+'\n    static inline std::atomic_uintptr_t quad_trace_hook_vtable{};')
    begin=s.index('    static void hook_new_rhi_command('); end=s.index('    static void hook_old_rhi_command(',begin)
    p=s[begin:end]
    found=list(re.finditer(r'\breturn;',p))
    if len(found)!=len(RETURNS):raise RuntimeError(f'Expected {len(RETURNS)} return guards, got {len(found)}')
    for i,m in reversed(list(enumerate(found))):
        event='HOOK_RETURN' if i in NORMAL_RETURNS else 'HOOK_REJECT'
        detail='root_rejection' if i in (6,17) else 'rejection_reason' if i==20 else 'vr->quadview_status()'
        p=p[:m.start()]+f'{{ qv_trace({60+i},"{event}","{RETURNS[i]}",{detail}); return; }}'+p[m.end():]
    p=replace(p,'        auto runtime = vr->get_runtime();','''        auto runtime = vr->get_runtime();
        const auto qv_initial_root=reinterpret_cast<uintptr_t>(last_command);
        auto qv_trace=[&](size_t site,const char* event,const char* reason,const char* detail="none",int result=-1) {
            uevr::quadview::HookTraceRecord r{};
            r.event=event;r.reason=reason;r.detail=detail;r.result=result;
            r.generation=vr->mono_generation();r.mode=uevr::quadview::hook_trace_mode();r.frame=frame_count;
            r.serial=quad_native?quad_native.source.serial:quad_engine?quad_engine.serial:quad_source?quad_source.serial:
                duo_source.packet?duo_source.packet->serial:0;
            r.owner_generation=quad_native?quad_native.source.generation:quad_engine?quad_engine.generation:
                quad_source?quad_source.generation:duo_source?duo_source.generation:0;
            r.owner_serial=r.serial;r.role=quad_native?unsigned(quad_native.view):255;
            r.engine=bool(quad_engine);r.native=bool(quad_native);r.source=bool(quad_source);r.duo=bool(duo_source);
            r.root=qv_initial_root;r.tail=reinterpret_cast<uintptr_t>(last_command);
            r.vtables=original_vtables.size();r.engines=quad_command_engines.size();
            r.natives=quad_native_commands.size();r.drains=quad_drain_commands.size();
            const auto recorded=original_vtables.find(last_command);r.recorded=recorded!=original_vtables.end();
            if(r.recorded) r.original_vtable=reinterpret_cast<uintptr_t>(recorded->second);
            const auto old_frame=cmd_frame_counts.find(last_command);
            if(old_frame!=cmd_frame_counts.end()) r.recorded_frame=old_frame->second;
            if(is_readable_process_range(r.tail,sizeof(uintptr_t))) std::memcpy(&r.vtable,last_command,sizeof(uintptr_t));
            const auto ours=quad_trace_hook_vtable.load(std::memory_order_relaxed);
            r.ours_known=ours!=0;r.ours=ours && r.vtable==ours;
            const auto drain=uevr::quadview::NativeDrainScope::current();r.drain=drain.id;r.list=drain.immediate_list;
            uevr::quadview::emit_hook_trace(site,r);
        };
        qv_trace(1,"HOOK_ENTER","entry");''')
    p=replace(p,'            last_command=reinterpret_cast<sdk::FRHICommandBase_New*>(*tail);',
              '            last_command=reinterpret_cast<sdk::FRHICommandBase_New*>(*tail);\n            qv_trace(2,"HOOK_TAIL","quad_tail_selected");')
    # Observe every native attach outcome, including quarantined/overflow.
    attach='reinterpret_cast<uintptr_t>(last_command),drain.id,drain.immediate_list,frame_count);'
    if p.count(attach)!=3:raise RuntimeError('Expected all three native attach sites')
    pieces=p.split(attach);p=pieces[0]
    for i,part in enumerate(pieces[1:]):
        p+=attach+f'\n                        qv_trace({3+i},"NATIVE_ATTACH","hook_batch","none",static_cast<int>(attached.status));'+part
    array_end='''            (uintptr_t)&hooked_command_fn<6>
        };'''
    p=replace(p,array_end,array_end+'\n        quad_trace_hook_vtable.store(reinterpret_cast<uintptr_t>(new_vtable.data()),std::memory_order_relaxed);')
    p=replace(p,'        *(void***)last_command = (void**)new_vtable.data();',
              '        *(void***)last_command = (void**)new_vtable.data();\n        qv_trace(6,"HOOK_INSTALLED","vtable_replaced");')
    s=s[:begin]+p+s[end:]
    # Callback entry is logged before the shared mutex; owner-qualified entry
    # follows under the existing lock, before worker/XR/original execution.
    begin=s.index('    template<int N>\n    static void* hooked_command_fn(');end=s.index('    static void hook_new_rhi_command(',begin)
    p=s[begin:end]
    p=replace(p,'        std::scoped_lock _{vtable_mutex};','''        uevr::quadview::HookTraceRecord qv_pre{};
        qv_pre.event="RHI_ENTRY";qv_pre.reason="pre_lock";qv_pre.tail=reinterpret_cast<uintptr_t>(cmd);
        qv_pre.list=reinterpret_cast<uintptr_t>(cmd_list);qv_pre.index=N;
        if(const auto& current=VR::get();current) qv_pre.generation=current->mono_generation();
        qv_pre.mode=uevr::quadview::hook_trace_mode();
        uevr::quadview::emit_hook_trace(7,qv_pre);
        const auto qv_lock_start=std::chrono::steady_clock::now();
        std::scoped_lock _{vtable_mutex};
        const auto qv_lock_acquired=std::chrono::steady_clock::now();''')
    anchor='        FFakeStereoRenderingHook::QuadViewNativeDelivery::RuntimeEvent quad_native_runtime_event{};'
    p=replace(p,anchor,'''        uevr::quadview::HookTraceRecord qv_rhi{};
        const auto* qv_native_owner=quad_native_record.owner_count?&quad_native_record.owners[0]:nullptr;
        qv_rhi.generation=vr->mono_generation();qv_rhi.mode=uevr::quadview::hook_trace_mode();
        qv_rhi.frame=frame_count;qv_rhi.tail=reinterpret_cast<uintptr_t>(cmd);qv_rhi.list=reinterpret_cast<uintptr_t>(cmd_list);
        qv_rhi.index=N;qv_rhi.expected_index=correct_execute_index;
        qv_rhi.serial=quad_engine?quad_engine.serial:quad_source?quad_source.serial:qv_native_owner?qv_native_owner->source.serial:
            quad_drain.count?quad_drain.tickets[0].serial:duo_source.packet?duo_source.packet->serial:0;
        qv_rhi.owner_generation=quad_engine?quad_engine.generation:quad_source?quad_source.generation:
            qv_native_owner?qv_native_owner->source.generation:quad_drain.count?quad_drain.tickets[0].generation:
            duo_source?duo_source.generation:0;
        qv_rhi.owner_serial=qv_rhi.serial;qv_rhi.role=qv_native_owner?unsigned(qv_native_owner->view):255;
        qv_rhi.engine=bool(quad_engine);qv_rhi.native=bool(quad_native);qv_rhi.source=bool(quad_source);qv_rhi.duo=bool(duo_source);
        qv_rhi.vtables=original_vtables.size();qv_rhi.engines=quad_command_engines.size();
        qv_rhi.natives=quad_native_commands.size();qv_rhi.drains=quad_drain_commands.size();
        qv_rhi.original_vtable=reinterpret_cast<uintptr_t>(original_vtable);
        auto qv_emit_rhi=[qv_rhi](size_t site,const char* event,const char* reason,uint64_t us=0,int result=-1) {
            auto r=qv_rhi;r.event=event;r.reason=reason;r.elapsed_us=us;r.result=result;
            uevr::quadview::emit_hook_trace(site,r);
        };
        qv_emit_rhi(8,"RHI_ENTRY","owner_bound");
        qv_emit_rhi(9,"RHI_LOCKED","lock_wait",static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::microseconds>(qv_lock_acquired-qv_lock_start).count()));
        auto qv_sync_frame=[&](uint32_t frame,VRRuntime::SyncFrameCallsite callsite) {
            qv_emit_rhi(10,"XR_SYNC_ENTER","synchronize_frame");
            const auto started=std::chrono::steady_clock::now();
            const auto result=runtime->synchronize_frame(frame,callsite);
            qv_emit_rhi(11,"XR_SYNC_RETURN","synchronize_frame",static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-started).count()),static_cast<int>(result));
            return result;
        };
''' + anchor)
    p=p.replace('runtime->synchronize_frame(runtime_frame_count,','qv_sync_frame(runtime_frame_count,')
    original='            const auto result = func(cmd, cmd_list, debug_context, r9, stack_1, stack_2, stack_3, stack_4, stack_5, stack_6, stack_7, stack_8);'
    p=replace(p,original,'''            qv_emit_rhi(12,"ORIGINAL_ENTER","engine_callback");
            const auto qv_original_started=std::chrono::steady_clock::now();
'''+original+'''
            qv_emit_rhi(13,"ORIGINAL_RETURN","engine_callback",static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-qv_original_started).count()));''')
    execution='                    const auto execution=g_hook->quadview_native_delivery.executed_tail(quad_native,GetCurrentThreadId());'
    p=replace(p,execution,execution+'''
                    qv_emit_rhi(14,"NATIVE_EXECUTION","executed_tail",0,execution.accepted?1:0);''')
    p=replace(p,'            return result;', '''            qv_emit_rhi(15,"RHI_COMPLETE",N==correct_execute_index?"correct_index":"other_index",
                static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(
                    std::chrono::steady_clock::now()-qv_lock_acquired).count()));
            return result;''') if p.count('            return result;')==1 else p
    # qv_sync_frame also returns a result; target the callback's final return by context.
    if '"RHI_COMPLETE"' not in p:
        p=replace(p,'''            return result;
        };

        if (N != correct_execute_index)''','''            qv_emit_rhi(15,"RHI_COMPLETE",N==correct_execute_index?"correct_index":"other_index",
                static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(
                    std::chrono::steady_clock::now()-qv_lock_acquired).count()));
            return result;
        };

        if (N != correct_execute_index)''')
    p=replace(p,'        RHIThreadWorker::get().execute();','''        qv_emit_rhi(16,"WORKER_ENTER","rhi_worker");
        RHIThreadWorker::get().execute();
        qv_emit_rhi(17,"WORKER_RETURN","rhi_worker");''')
    s=s[:begin]+p+s[end:]
    # GT and RT: capture identities before the live hook adapter, and report
    # exact native matcher outcomes instead of inferring them from later misses.
    gt='            const auto registration=g_hook->quadview_delivery.register_engine_family_detailed(ticket);'
    s=replace(s,gt,gt+'''
            { uevr::quadview::HookTraceRecord r{};r.event="GT_REGISTER";r.reason="engine_registration";
              r.generation=ticket.generation;r.serial=ticket.serial;r.frame=ticket.engine_frame;r.mode=7;
              r.family=ticket.family;r.target=ticket.target;r.scene=ticket.scene;r.result=static_cast<int>(registration.status);
              r.pending=registration.pending;uevr::quadview::emit_hook_trace(18,r); }''')
    bind='''            if (bound) {
                native_context.roles_bound|=uint8_t(1u<<slot);'''
    s=replace(s,bind,'''            { uevr::quadview::HookTraceRecord r{};r.event="ROLE_GT_BOUND";r.reason=bound?"accepted":"rejected";
              r.generation=vr->mono_generation();r.serial=native_context.packet->serial;r.frame=frame_count;r.role=slot;r.mode=7;
              r.family=reinterpret_cast<uintptr_t>(&view_family);r.target=reinterpret_cast<uintptr_t>(view_family.get_render_target());
              r.scene=reinterpret_cast<uintptr_t>(view_family.get_scene_interface());r.canonical_frame=native_context.engine_frame;
              uevr::quadview::emit_hook_trace(19,r); }
''' + bind)
    native_views_anchor='        const auto* native_views=view_family.get_views();'
    s=replace(s,native_views_anchor,native_views_anchor+'''
        { uevr::quadview::HookTraceRecord r{};r.event="RT_ROLE_GATE";
          r.reason=native_views && native_views->count==1?"singleton":"not_singleton";
          r.generation=vr->mono_generation();r.frame=frame_count;r.mode=7;
          r.result=native_views?static_cast<int>(native_views->count):-1;
          r.family=reinterpret_cast<uintptr_t>(&view_family);
          uevr::quadview::emit_hook_trace(28,r); }''')
    native='''            const auto native=g_hook->quadview_native_delivery.render(vr->mono_generation(),frame_count,
                reinterpret_cast<uintptr_t>(view_family.get_render_target()),
                reinterpret_cast<uintptr_t>(view_family.get_scene_interface()));'''
    s=replace(s,native,'''            FFakeStereoRenderingHook::QuadViewNativeDelivery::RenderTrace native_trace{};
            const auto native=g_hook->quadview_native_delivery.render(vr->mono_generation(),frame_count,
                reinterpret_cast<uintptr_t>(view_family.get_render_target()),
                reinterpret_cast<uintptr_t>(view_family.get_scene_interface()),&native_trace);
            { uevr::quadview::HookTraceRecord r{};r.event="RT_MATCH";r.reason=native?"native_accepted":"native_rejected";
              r.generation=vr->mono_generation();r.serial=native_trace.serial;r.frame=frame_count;r.role=native_trace.role;r.mode=7;
              r.family=reinterpret_cast<uintptr_t>(&view_family);r.target=reinterpret_cast<uintptr_t>(view_family.get_render_target());
              r.scene=reinterpret_cast<uintptr_t>(view_family.get_scene_interface());r.result=static_cast<int>(native_trace.reason);
              r.engine=native_trace.engine_claim;r.source=native_trace.source_claim;r.canonical_frame=native_trace.canonical_frame;
              r.rendered=native_trace.rendered;r.hooked=native_trace.hooked;r.executed=native_trace.executed;r.written=native_trace.written;
              uevr::quadview::emit_hook_trace(20,r); }''')
    anchor='    const auto quad_engine=quad_engine_opt.value_or(FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket{});'
    s=replace(s,anchor,anchor+'''
    auto qv_route_trace=[=](size_t site,const char* event,const char* reason,uintptr_t list) {
        uevr::quadview::HookTraceRecord r{};r.event=event;r.reason=reason;r.generation=vr->mono_generation();
        r.mode=uevr::quadview::hook_trace_mode();r.frame=frame_count;r.list=list;
        r.serial=quad_native?quad_native.source.serial:quad_engine?quad_engine.serial:quad_source?quad_source.serial:
            duo_source.packet?duo_source.packet->serial:0;
        r.role=quad_native?unsigned(quad_native.view):255;r.native=bool(quad_native);r.engine=bool(quad_engine);
        r.source=bool(quad_source);r.duo=bool(duo_source);
        uevr::quadview::emit_hook_trace(site,r);
    };
    qv_route_trace(21,"RT_ENTER","owner_selection_complete",reinterpret_cast<uintptr_t>(cmd_list));''')
    anchor='''    auto enqueue_poses_on_slate_thread = [&]() {
        g_hook->get_slate_thread_worker()->enqueue([=](FRHICommandListImmediate* command_list) {'''
    s=replace(s,anchor,'''    auto enqueue_poses_on_slate_thread = [&]() {
        qv_route_trace(22,"SLATE_QUEUED","fallback",reinterpret_cast<uintptr_t>(cmd_list));
        g_hook->get_slate_thread_worker()->enqueue([=](FRHICommandListImmediate* command_list) {
            qv_route_trace(23,"SLATE_ENTER","worker_callback",reinterpret_cast<uintptr_t>(command_list));''')
    # One exit event from each queued Slate task, even on root-discovery failure.
    s=replace(s,'            static bool once_slate = true;', '''            utility::ScopeGuard qv_slate_exit{[&]{qv_route_trace(24,"SLATE_RETURN","worker_callback",reinterpret_cast<uintptr_t>(command_list));}};
            static bool once_slate = true;''')
    for name in ('QuadViewHookTrace.hpp','QuadViewNativeDelivery.hpp'):
        shutil.copy2(here/name,root/'src/mods/vr'/name)
    hpath.write_text(h);path.write_text(s)
    print('Applied Build50 bounded production-adapter observation (27 return guards).')


if __name__=='__main__':main()

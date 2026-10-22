#!/usr/bin/env python3
"""Build49: bind every singleton's real GT frame before its renderer copy."""
from pathlib import Path
import sys
from apply_quadview_native_delivery import replace


def main():
    root = Path(sys.argv[1])
    header = root / 'src/mods/vr/FFakeStereoRenderingHook.hpp'
    h = header.read_text()
    h = replace(h, '        bool active{},source_registered{}; uint32_t current_slot{},original_count{},engine_frame{0xffffffffu};',
        '        bool active{},source_registered{}; uint32_t current_slot{},original_count{},engine_frame{0xffffffffu};\n'
        '        uint8_t roles_bound{}; std::array<uint32_t,4> role_frames{};')
    path = root / 'src/mods/vr/FFakeStereoRenderingHook.cpp'
    s = path.read_text()
    # Both publishable and drain-only quartets require observed per-role keys.
    if s.count('native_context.target_set_generation,native_targets);') != 2:
        raise RuntimeError('Expected both native source binding sites')
    s = s.replace('native_context.target_set_generation,native_targets);',
                  'native_context.target_set_generation,native_targets,true);')
    s = replace(s, '''    }();
    if (const auto packet = duoview_build_packet; packet && packet->duoview_frame) {''', '''    }();
    // This runs for EVERY singleton, including callbacks whose quartet was
    // already created by role zero. The callback's own frame is authoritative.
    {
        auto& native_context=g_hook->quadview_native_build_context;
        if (native_context.active && native_context.source_registered && native_context.packet &&
            native_context.family==reinterpret_cast<uintptr_t>(&view_family) && native_context.current_slot<4) {
            const auto slot=native_context.current_slot;
            const bool bound=g_hook->quadview_native_delivery.bind_role(vr->mono_generation(),
                native_context.packet->serial,slot,frame_count,
                reinterpret_cast<uintptr_t>(view_family.get_render_target()),
                reinterpret_cast<uintptr_t>(view_family.get_scene_interface()));
            if (bound) {
                native_context.roles_bound|=uint8_t(1u<<slot);
                native_context.role_frames[slot]=frame_count;
            } else {
                vr->set_quadview_status("Native singleton GT frame identity rejected; publication held closed");
                SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][NativeRole][GT] rejected serial={} slot={} frame={}",
                    native_context.packet->serial,slot,frame_count);
            }
        }
    }
    if (const auto packet = duoview_build_packet; packet && packet->duoview_frame) {''')
    s = replace(s, '''                    (slot!=0 || native_context.source_registered) &&
                    view_family->get_render_target()==native_context.render_targets[slot];''', '''                    native_context.source_registered && (native_context.roles_bound & (1u<<slot)) &&
                    view_family->get_render_target()==native_context.render_targets[slot];''')
    s = replace(s, '''        vr->set_quadview_status("Four isolated native source renders completed; waiting for exact quartet RHI tails");''', '''        SPDLOG_INFO_EVERY_N_SEC(2,"[QuadViews][NativeRole][GT] serial={} canonical={} roles={},{},{},{} mask={}",
            qv_key.draw_serial,native_context.engine_frame,native_context.role_frames[0],native_context.role_frames[1],
            native_context.role_frames[2],native_context.role_frames[3],native_context.roles_bound);
        vr->set_quadview_status("Four isolated native source renders completed; waiting for exact quartet RHI tails");''')
    s = replace(s, '''            else vr->set_quadview_status("Rejected a native singleton without an exact quartet owner");''', '''            else {
                vr->set_quadview_status("Rejected a native singleton without an exact quartet owner");
                SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][NativeRole][RT] unmatched generation={} frame={} target={:x} scene={:x}",
                    vr->mono_generation(),frame_count,reinterpret_cast<uintptr_t>(view_family.get_render_target()),
                    reinterpret_cast<uintptr_t>(view_family.get_scene_interface()));
            }''')
    s = replace(s, '''            if (g_hook->quadview_delivery.register_engine_family(ticket)) qv_engine_ticket=ticket;
            else vr->set_quadview_status("Engine render-family ownership ledger is full; mode transition will remain blocked");''', '''            const auto registration=g_hook->quadview_delivery.register_engine_family_detailed(ticket);
            using Registration=FFakeStereoRenderingHook::QuadViewDelivery::EngineRegistrationStatus;
            if (registration.status==Registration::accepted || registration.status==Registration::duplicate_same_owner)
                qv_engine_ticket=ticket;
            else {
                vr->set_quadview_status("Engine render-family registration rejected; inspect EngineRegistration diagnostics");
                SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][EngineRegistration] reason={} generation={} serial={} frame={} family={:x} target={:x} scene={:x} pending={} capacity={} oldest={}",
                    static_cast<unsigned>(registration.status),ticket.generation,ticket.serial,ticket.engine_frame,
                    ticket.family,ticket.target,ticket.scene,registration.pending,registration.capacity,registration.oldest_serial);
            }''')
    s = replace(s, '''                    if (!g_hook->quadview_native_delivery.executed_tail(quad_native,GetCurrentThreadId()).accepted)
                        vr->set_quadview_status("Native quartet RHI execution did not match its exact target owner");''', '''                    const auto execution=g_hook->quadview_native_delivery.executed_tail(quad_native,GetCurrentThreadId());
                    SPDLOG_INFO_EVERY_N_SEC(2,"[QuadViews][RHI] native tail executed tail={} accepted={}",quad_native.id,execution.accepted);
                    if (!execution.accepted)
                        vr->set_quadview_status("Native quartet RHI execution did not match its exact target owner");''')
    header.write_text(h)
    path.write_text(s)
    print('Applied exact per-role GT frame binding and liveness diagnostics.')


if __name__ == '__main__':
    main()

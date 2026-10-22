#!/usr/bin/env python3
"""Build 48: engine-only bootstrap recovery after the native/retirement overlays."""
from pathlib import Path
import sys
from apply_quadview_native_delivery import replace


def main():
    root = Path(sys.argv[1])
    path = root / 'src/mods/vr/FFakeStereoRenderingHook.cpp'
    s = path.read_text()
    s = replace(s, '''                vr->set_quadview_status("Native main family lacks a complete frozen identity; batch held closed");
                return;''', '''                const auto drain_route=uevr::quadview::route_drain_family(candidates,partial);
                if (identity_storage_valid && drain_route) {
                    vr->set_quadview_status("Incomplete native snapshot: draining original engine family without publication");
                    SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][Recovery] drain-only generation={} serial={} views={}",
                        key.generation,key.draw_serial,identities[drain_route.index].view_count);
                    call_original(); return;
                }
                vr->set_quadview_status("Incomplete main family lacks an authenticated drain identity");
                return;''')
    # Authenticate ordinary engine ownership for two-view startup and four-view
    # recovery independently of source eligibility. Source registration below
    # still requires all four views, pose, native ownership and producer checks.
    s = replace(s, '''        if (qv_family_readable && qv_target && qv_target==qv_expected_target && qv_scene) {''', '''        const bool qv_engine_family_readable=views_ptr && views_ptr->count>0 && views_ptr->count<=4 &&
            views_ptr->capacity>=views_ptr->count && views_ptr->data &&
            is_readable_process_range(reinterpret_cast<uintptr_t>(views_ptr->data),sizeof(void*)*views_ptr->count);
        bool qv_engine_views_valid=qv_engine_family_readable;
        if (qv_engine_views_valid) for(int32_t i=0;i<views_ptr->count;++i) {
            if (!views_ptr->data[i]) qv_engine_views_valid=false;
            for(int32_t j=0;j<i;++j) if(views_ptr->data[i]==views_ptr->data[j]) qv_engine_views_valid=false;
        }
        if (qv_engine_views_valid && qv_target && qv_target==qv_expected_target && qv_scene) {''')
    anchor = '    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::QuadViewNativeDelivery::TailOwnerBatch> quad_native_commands{};'
    s = replace(s, anchor, anchor + '''
    using QuadDrainBatch=uevr::quadview::EngineDrainBatch<FFakeStereoRenderingHook::QuadViewDelivery>;
    static inline std::unordered_map<sdk::FRHICommandBase_New*,QuadDrainBatch> quad_drain_commands{};''')
    anchor = '        const auto quad_native=quad_native_record.ticket;'
    s = replace(s, anchor, anchor + '''
        const auto quad_drain_it=quad_drain_commands.find(cmd);
        const auto quad_drain=quad_drain_it!=quad_drain_commands.end() ? quad_drain_it->second : QuadDrainBatch{};''')
    s = replace(s, '        quad_native_commands.erase(cmd);',
        '        quad_native_commands.erase(cmd);\n        quad_drain_commands.erase(cmd);')
    anchor = '                if (quad_native && g_hook != nullptr) {'
    s = replace(s, anchor, '''                if (quad_drain.count && g_hook &&
                    !quad_drain.execute(g_hook->quadview_delivery,reinterpret_cast<uintptr_t>(cmd),
                        GetCurrentThreadId(),vr->mono_generation()))
                    vr->set_quadview_status("Recovery tail failed to retire every authenticated engine owner");
''' + anchor)
    anchor = '''            if (original_vtables.contains(last_command)) {
                if (quad_native) {'''
    s = replace(s, anchor, '''            if (original_vtables.contains(last_command)) {
                if (quad_engine && !quad_native) {
                    const auto primary=quad_command_engines.find(last_command);
                    if (primary!=quad_command_engines.end() && primary->second.same_owner(quad_engine)) return;
                    const bool known_tail=quad_drain_commands.contains(last_command) ||
                        quad_native_commands.contains(last_command) || primary!=quad_command_engines.end();
                    if (!known_tail) {
                        vr->set_quadview_status("Recovery engine owner encountered an unrelated hooked tail"); return;
                    }
                    auto& drain=quad_drain_commands[last_command];
                    const auto prior_serial=drain.newest_serial;
                    if (!drain.attach(g_hook->quadview_delivery,quad_engine,
                            reinterpret_cast<uintptr_t>(last_command),quad_source)) {
                        vr->set_quadview_status("Recovery tail owner capacity or identity rejected; transition remains blocked"); return;
                    }
                    // Mixed legacy atlas writes have no ordered content proof.
                    // Revoke publication while map records retain packet leases
                    // through the actual original CPU callback.
                    if (quad_source) g_hook->quadview_delivery.retire(quad_source.generation,quad_source.serial);
                    const auto previous_source=quad_command_sources.find(last_command);
                    if (previous_source!=quad_command_sources.end())
                        g_hook->quadview_delivery.retire(previous_source->second.generation,previous_source->second.serial);
                    if (!quad_native_commands.contains(last_command) && quad_engine.serial>prior_serial)
                        cmd_frame_counts[last_command]=frame_count;
                    return;
                }
                if (quad_native) {''')
    anchor = '''        if (quad_engine) {
            if (!g_hook->quadview_delivery.tail_hooked_engine_family(quad_engine,quad_source,'''
    s = replace(s, anchor, '''        if (quad_engine && !quad_source && !quad_native) {
            QuadDrainBatch batch{};
            if (!batch.attach(g_hook->quadview_delivery,quad_engine,reinterpret_cast<uintptr_t>(last_command))) {
                original_vtables.erase(last_command); return;
            }
            quad_drain_commands.emplace(last_command,std::move(batch));
        } else if (quad_engine) {
            if (!g_hook->quadview_delivery.tail_hooked_engine_family(quad_engine,quad_source,''')
    s = replace(s, '''                    const auto existing=quad_native_commands.find(last_command);
                    if (existing==quad_native_commands.end()) {
                        vr->set_quadview_status("Shared native command tail has no retained owner ticket");
                        return;
                    }
                    const auto drain=uevr::quadview::NativeDrainScope::current();''', '''                    auto existing=quad_native_commands.find(last_command);
                    if (existing==quad_native_commands.end()) {
                        if (!quad_drain_commands.contains(last_command) && !quad_command_engines.contains(last_command)) {
                            vr->set_quadview_status("Shared native command tail has no authenticated recovery owner"); return;
                        }
                        const auto drain=uevr::quadview::NativeDrainScope::current();
                        const auto attached=g_hook->quadview_native_delivery.hook_batch(quad_native,
                            reinterpret_cast<uintptr_t>(last_command),drain.id,drain.immediate_list,frame_count);
                        FFakeStereoRenderingHook::QuadViewNativeDelivery::TailOwnerBatch batch{};
                        if (!attached || !batch.retain(quad_native,attached.tail)) {
                            vr->set_quadview_status("Native role could not join the authenticated recovery tail"); return;
                        }
                        quad_native_commands.emplace(last_command,std::move(batch));
                        const auto legacy=quad_command_sources.find(last_command);
                        if (legacy!=quad_command_sources.end())
                            g_hook->quadview_delivery.retire(legacy->second.generation,legacy->second.serial);
                        return;
                    }
                    const auto drain=uevr::quadview::NativeDrainScope::current();''')
    s = replace(s, '''g_hook->quadview_delivery.executed_engine_family(quad_engine,quad_source,
                            reinterpret_cast<uintptr_t>(cmd),GetCurrentThreadId())''',
        '''g_hook->quadview_delivery.executed_engine_family(quad_engine,
                            (quad_drain.count || quad_native) ? FFakeStereoRenderingHook::QuadViewDelivery::Source{} : quad_source,
                            reinterpret_cast<uintptr_t>(cmd),GetCurrentThreadId())''')
    s = replace(s, '        result.tracked_engine_records = SceneViewExtensionAnalyzer::quad_command_engines.size();',
        '''        result.tracked_engine_records = SceneViewExtensionAnalyzer::quad_command_engines.size();
        for (const auto& [command,batch]:SceneViewExtensionAnalyzer::quad_drain_commands)
            result.tracked_engine_records+=batch.count;''')
    path.write_text(s)
    print('Applied engine-only bootstrap admission and shared recovery-tail drainage.')


if __name__ == '__main__':
    main()

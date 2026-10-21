#!/usr/bin/env python3
"""Four-target GT/RT/RHI ownership integration, after the guarded ID7 overlays."""
from pathlib import Path
import sys, shutil, re

def replace(s, old, new):
    n=s.count(old)
    if n!=1: raise RuntimeError(f'Native delivery expected one anchor, found {n}: {old[:100]!r}')
    return s.replace(old,new,1)

def main():
    root=Path(sys.argv[1]); src=Path(__file__).parent
    hp=root/'src/mods/vr/FFakeStereoRenderingHook.hpp'
    cp=root/'src/mods/vr/FFakeStereoRenderingHook.cpp'
    h=hp.read_text(); s=cp.read_text()
    h=replace(h, '#include "QuadViewDelivery.hpp"', '#include "QuadViewDelivery.hpp"\n#include "QuadViewFamilyRouting.hpp"\n#include "QuadViewNativeDelivery.hpp"')
    h=replace(h, '    mutable QuadViewDelivery quadview_delivery{};', '''    mutable QuadViewDelivery quadview_delivery{};
    using QuadViewNativeDelivery = uevr::quadview::NativeDelivery<QuadViewDelivery>;
    mutable QuadViewNativeDelivery quadview_native_delivery{quadview_delivery};''')
    h=replace(h, '        quadview_delivery.retire_all();', '        quadview_delivery.retire_all();\n        quadview_native_delivery.reset();')
    provenance_declaration='''struct QuadViewNativeRhiQueueSnapshot {
    uint64_t tail_owner_records{};
    uint64_t tracked_engine_records{};
    uint64_t hooked_command_records_all_modes{};
    bool observed{};
    bool busy{};
};
QuadViewNativeRhiQueueSnapshot sample_quadview_native_rhi_queue();

'''
    s=replace(s,'std::string FFakeStereoRenderingHook::build_hook_provenance_json() {',
        provenance_declaration+'std::string FFakeStereoRenderingHook::build_hook_provenance_json() {')
    s=replace(s,'        result["native_frame_diagnostics"] = uevr::native_frame::export_json(m_native_frame_diagnostics);', '''        result["native_frame_diagnostics"] = uevr::native_frame::export_json(m_native_frame_diagnostics);

        // Independent best-effort samples; busy means this component was dropped.
        result["quadview_diagnostics_snapshot"] = {
            {"observation_only", true}, {"components_sampled_independently", true},
            {"cross_component_atomic", false},
            {"no_gpu_or_queue_work", true},
        };
        const auto& quad_vr = VR::get();
        const uint64_t quad_generation = quad_vr ? quad_vr->mono_generation() : 0;
        const auto quad_delivery = quadview_delivery.diagnostics_snapshot(quad_generation);
        nlohmann::json quad_delivery_json{
            {"observed", !quad_delivery.busy}, {"busy", quad_delivery.busy},
            {"requested_generation", quad_generation ? nlohmann::json(quad_generation) : nlohmann::json(nullptr)},
            {"generation_scope", quad_generation ? "active generation filter" : "all generations (unfiltered)"},
        };
        if (!quad_delivery.busy) {
            quad_delivery_json["source_slots"] = quad_delivery.source_slots;
            quad_delivery_json["incomplete_source_slots"] = quad_delivery.incomplete_source_slots;
            quad_delivery_json["pending_engine_tickets"] = quad_delivery.pending_engine_tickets;
            quad_delivery_json["engine_tracking_overflowed"] = quad_delivery.engine_tracking_overflowed;
        }
        result["quadview_delivery"] = std::move(quad_delivery_json);

        const auto quad_native = quadview_native_delivery.diagnostics_snapshot(quad_generation);
        nlohmann::json quad_native_json{
            {"observed", !quad_native.busy}, {"busy", quad_native.busy},
            {"requested_generation", quad_generation ? nlohmann::json(quad_generation) : nlohmann::json(nullptr)},
            {"generation_scope", quad_generation ? "active generation filter" : "all generations (unfiltered)"},
        };
        if (!quad_native.busy) {
            quad_native_json["occupied_slots"] = quad_native.occupied_slots;
            quad_native_json["active_tails"] = quad_native.active_tails;
            quad_native_json["shared_tails"] = quad_native.shared_tails;
            quad_native_json["ambiguous_tails"] = quad_native.ambiguous_tails;
            quad_native_json["oldest_retained_found"] = quad_native.oldest_retained_found;
        }
        if (!quad_native.busy && quad_native.oldest_retained_found) {
            quad_native_json["oldest_retained_owner"] = {
                {"generation", quad_native.oldest_retained_generation}, {"serial", quad_native.oldest_retained_serial},
                {"rendered_mask", quad_native.oldest_retained_rendered}, {"hooked_mask", quad_native.oldest_retained_hooked},
                {"executed_mask", quad_native.oldest_retained_executed}, {"written_mask", quad_native.oldest_retained_written},
                {"pending_count", quad_native.oldest_retained_pending_count},
                {"completion_latched", quad_native.oldest_retained_completion_latched},
                {"publish", quad_native.oldest_retained_publish}, {"overwritten", quad_native.oldest_retained_overwritten},
            };
        } else if (!quad_native.busy) {
            quad_native_json["oldest_retained_owner"] = nullptr;
        }
        result["quadview_native_delivery"] = std::move(quad_native_json);

        const auto quad_rhi = sample_quadview_native_rhi_queue();
        nlohmann::json quad_rhi_json{
            {"observed", quad_rhi.observed}, {"busy", quad_rhi.busy},
            {"requested_generation", nullptr},
            {"generation_scope", "process-global map records; includes entries across generation resets"},
        };
        if (quad_rhi.observed && !quad_rhi.busy) {
            quad_rhi_json["tail_owner_records"] = quad_rhi.tail_owner_records;
            quad_rhi_json["tail_owner_record_semantics"] = "retained map records; not unique quartets";
            quad_rhi_json["tracked_engine_records"] = quad_rhi.tracked_engine_records;
            quad_rhi_json["hooked_command_records_all_modes"] = quad_rhi.hooked_command_records_all_modes;
            quad_rhi_json["scope"] = "native tail and engine maps are Quad Views; original vtable map spans all tracked RHI hook modes";
        }
        result["quadview_native_rhi_queue"] = std::move(quad_rhi_json);

        if (auto* manager = get_render_target_manager()) {
            const auto retire = manager->get_quadview_native_retirement_diagnostics();
            nlohmann::json retire_json{
                {"observed", retire.observed}, {"busy", retire.busy},
                {"requested_generation", nullptr},
                {"generation_scope", "process-global retirement queue across resets"},
            };
            if (!retire.observed) retire_json["status"] = "not_observed";
            if (retire.observed && !retire.busy) {
                retire_json["pending"] = {{"count", retire.pending.count}, {"truncated", retire.pending.truncated}};
                retire_json["staged"] = {{"count", retire.staged.count}, {"truncated", retire.staged.truncated}};
                retire_json["in_flight"] = {{"count", retire.in_flight.count}, {"truncated", retire.in_flight.truncated}};
                retire_json["ready"] = {{"count", retire.ready.count}, {"truncated", retire.ready.truncated}};
                retire_json["count_is_lower_bound_when_truncated"] = true;
                retire_json["per_list_walk_cap"] = uevr::quadview::native_retirement_list_walk_cap;
                retire_json["last_successful_signal_observed"] = retire.last_successful_signal_observed;
                retire_json["last_successful_queue"] = retire.last_successful_queue ? nlohmann::json(fmt::format("0x{:x}", retire.last_successful_queue)) : nlohmann::json(nullptr);
                retire_json["last_successful_device"] = retire.last_successful_device ? nlohmann::json(fmt::format("0x{:x}", retire.last_successful_device)) : nlohmann::json(nullptr);
                retire_json["last_successful_fence"] = retire.last_successful_fence ? nlohmann::json(fmt::format("0x{:x}", retire.last_successful_fence)) : nlohmann::json(nullptr);
                retire_json["last_successful_signal_value"] = retire.last_successful_signal_observed
                    ? nlohmann::json(retire.last_successful_signal_value) : nlohmann::json(nullptr);
                retire_json["last_poll_state"] = uevr::quadview::to_string(retire.last_poll_state);
                retire_json["last_poll_fence"] = retire.last_poll_fence ? nlohmann::json(fmt::format("0x{:x}", retire.last_poll_fence)) : nlohmann::json(nullptr);
                retire_json["last_poll_device"] = retire.last_poll_device ? nlohmann::json(fmt::format("0x{:x}", retire.last_poll_device)) : nlohmann::json(nullptr);
                retire_json["last_poll_completed_value"] = retire.last_poll_state != uevr::quadview::NativeRetirementPollState::unobserved
                    ? nlohmann::json(retire.last_poll_completed_value) : nlohmann::json(nullptr);
                retire_json["last_poll_target_value"] = retire.last_poll_state != uevr::quadview::NativeRetirementPollState::unobserved
                    ? nlohmann::json(retire.last_poll_target_value) : nlohmann::json(nullptr);
                retire_json["signal_and_poll_values_are_compared"] = false;
                retire_json["queue_identity_proves_ordered_execution"] = false;
                retire_json["poll_target_is_for_last_polled_fence_only"] = true;
                retire_json["cross_fence_epoch_progress_is_inferred"] = false;
            }
            result["quadview_native_retirement"] = std::move(retire_json);
        } else {
            result["quadview_native_retirement"] = {{"observed", false}, {"busy", false}, {"status", "manager_unavailable"}};
        }''')
    # The ID7 router authenticates all readable candidates itself. Keep the
    # existing blanket vtable gate scoped to its original consumers so a valid
    # derived auxiliary family remains eligible for exact ID7 pass-through.
    s=replace(s,'    if (strict_candidate_validation) {\n        for (const auto family : view_families) {',
        '    if (strict_candidate_validation && !quadview_active) {\n        for (const auto family : view_families) {')
    # The first engine callback supplies the initialized engine frame number.
    route_anchor='    if (view_family == nullptr) {\n        call_original();\n        return;\n    }\n'
    route_block='''    if (quadview_active) {
        std::array<uevr::quadview::FamilyIdentity,max_sane_view_families> identities{};
        bool identity_storage_valid=true;
        for (size_t index=0;index<view_families.size();++index) {
            const auto family=view_families[index];
            auto& identity=identities[index];
            if (!family || !is_readable_process_range(reinterpret_cast<uintptr_t>(family),sizeof(*family))) {
                identity_storage_valid=false; identity.readable=false; continue;
            }
            identity.family=reinterpret_cast<uintptr_t>(family);
            identity.scene=reinterpret_cast<uintptr_t>(family->get_scene_interface());
            identity.target=reinterpret_cast<uintptr_t>(family->get_render_target());
            const auto family_views=family->get_views();
            if (!family_views || !is_readable_process_range(reinterpret_cast<uintptr_t>(family_views),sizeof(*family_views)) ||
                family_views->count<0 || family_views->count>16 || family_views->capacity<family_views->count ||
                (family_views->count!=0 && (!family_views->data || !is_readable_process_range(
                    reinterpret_cast<uintptr_t>(family_views->data),sizeof(void*)*family_views->count)))) {
                identity_storage_valid=false; identity.readable=false; continue;
            }
            identity.view_count=static_cast<uint8_t>(family_views->count);
            identity.readable=true;
            for (size_t view=0;view<identity.view_count;++view) {
                identity.views[view]=reinterpret_cast<uintptr_t>(family_views->data[view]);
                if (!family_views->data[view] || !is_readable_process_range(identity.views[view],sizeof(void*)))
                    identity.readable=false;
            }
            if (!identity.readable) identity_storage_valid=false;
        }
        const std::span<const uevr::quadview::FamilyIdentity> candidates{identities.data(),view_families.size()};
        auto& native_context=g_hook->quadview_native_build_context;
        uevr::quadview::FamilyRoute route{};
        if (native_context.active) {
            if (native_context.current_slot>=4) {
                vr->set_quadview_status("Rejected an invalid nested native source slot"); return;
            }
            uevr::quadview::FamilyIdentity expected_singleton{};
            expected_singleton.family=native_context.family;
            expected_singleton.scene=native_context.scene;
            expected_singleton.target=reinterpret_cast<uintptr_t>(native_context.render_targets[native_context.current_slot]);
            expected_singleton.views[0]=reinterpret_cast<uintptr_t>(native_context.original_views[native_context.current_slot]);
            expected_singleton.view_count=1; expected_singleton.readable=true;
            route=uevr::quadview::route_current_main_family(candidates,expected_singleton);
        } else {
            const auto key=vr->quadview_producer_key();
            const auto snapshot=vr->quadview_producer().snapshot(key);
            if (snapshot && snapshot->construction_complete() && snapshot->family && snapshot->scene && snapshot->target) {
                uevr::quadview::FrozenFamilyIdentity expected{};
                expected.family=snapshot->family; expected.scene=snapshot->scene; expected.target=snapshot->target;
                for (size_t view=0;view<4;++view) expected.views[view]=snapshot->views[view].view;
                route=uevr::quadview::route_main_family(candidates,expected);
            } else {
                uevr::quadview::PartialFamilyIdentity partial{};
                partial.target=snapshot ? snapshot->target : reinterpret_cast<uintptr_t>(
                    rtm ? rtm->get_view_family_render_target() : nullptr);
                if (snapshot) {
                    partial.family=snapshot->family; partial.scene=snapshot->scene;
                    for (size_t view=0;view<snapshot->views.size();++view) if (snapshot->views[view].view)
                        partial.views[partial.view_count++]=snapshot->views[view].view;
                }
                const auto partial_route=uevr::quadview::classify_partial_main_family(candidates,partial);
                if (partial_route==uevr::quadview::PartialFamilyRouteStatus::auxiliary_only) {
                    call_original(); return;
                }
                vr->set_quadview_status("Native main family lacks a complete frozen identity; batch held closed");
                return;
            }
        }
        if (!identity_storage_valid || route.status==uevr::quadview::FamilyRouteStatus::malformed_batch) {
            vr->set_quadview_status("Native view-family batch contains an unreadable family or view array"); return;
        }
        if (route.status==uevr::quadview::FamilyRouteStatus::auxiliary_only) {
            call_original(); return;
        }
        if (route.status!=uevr::quadview::FamilyRouteStatus::main_family) {
            vr->set_quadview_status(route.status==uevr::quadview::FamilyRouteStatus::ambiguous_main
                ? "Native main family is ambiguous in the TArrayView batch"
                : "Native main family does not match its frozen target, scene, family and view identity");
            return;
        }
        view_family=view_families[route.index];
    }

'''+route_anchor
    s=replace(s,route_anchor,route_block)
    s=replace(s,
        '        const bool qv_family_valid=qv_target_set && qv_target_set->complete() && qv_snapshot && qv_snapshot->construction_complete() &&',
        '''        bool qv_snapshot_views_match=qv_snapshot && qv_snapshot->views.size()==4 &&
            views.count==4 && views.capacity>=4 && views.data &&
            is_readable_process_range(reinterpret_cast<uintptr_t>(views.data),sizeof(void*)*4);
        if (qv_snapshot_views_match) for(size_t i=0;i!=4;++i)
            qv_snapshot_views_match=qv_snapshot_views_match &&
                qv_snapshot->views[i].view==reinterpret_cast<uintptr_t>(views.data[i]);
        const bool qv_snapshot_identity_match=qv_snapshot_views_match &&
            qv_snapshot->family==reinterpret_cast<uintptr_t>(view_family) &&
            qv_snapshot->scene==reinterpret_cast<uintptr_t>(qv_scene) &&
            qv_snapshot->target==reinterpret_cast<uintptr_t>(qv_expected_target);
        const bool qv_family_valid=qv_target_set && qv_target_set->complete() && qv_snapshot && qv_snapshot->construction_complete() &&
            qv_snapshot_identity_match &&''')
    dispatch_start=s.index('        const int32_t qv_original_count=views.count;')
    dispatch_end=s.index('        vr->set_quadview_status("Four isolated native source renders completed; waiting for exact quartet RHI tails");',dispatch_start)
    dispatch='''        utility::ScopeGuard restore_qv_dispatch{[&]() {
            native_context=std::move(previous_context);
        }};
        const auto qv_dispatch_result=uevr::quadview::dispatch_main_views(
            views.data,views.capacity,views.count,*view_family,native_context.original_views,
            native_context.render_targets,
            [](sdk::FSceneViewFamily& family) { return family.get_render_target(); },
            [](sdk::FSceneViewFamily& family,auto* target) { family.set_render_target(target); },
            [&](size_t slot) {
                if (slot!=0) reinterpret_cast<sdk::FScene*>(qv_scene)->decrement_frame_count();
                native_context.current_slot=static_cast<uint8_t>(slot);
                return true;
            },
            [&]() { call_original(); },
            [&]() {
                if (uses_tarrayview) {
                    TArrayViewViewFamily one_family{&view_family,1};
                    g_hook->m_render_module_begin_render_viewfamily_hook.unsafe_call<void>(render_module,canvas,
                        reinterpret_cast<sdk::FSceneViewFamily*>(&one_family));
                } else {
                    g_hook->m_render_module_begin_render_viewfamily_hook.unsafe_call<void>(render_module,canvas,view_family);
                }
            },
            [&](size_t slot) {
                return views.count==1 && views.data[0]==native_context.original_views[slot] &&
                    (slot!=0 || native_context.source_registered) &&
                    view_family->get_render_target()==native_context.render_targets[slot];
            });
        if (!qv_dispatch_result) {
            vr->set_quadview_status("Native four-view dispatch failed validation; original family was restored");
            return;
        }
'''
    s=s[:dispatch_start]+dispatch+s[dispatch_end:]
    # Restore the quartet only around its original GT source registration, then
    # restore the singleton before Unreal copies it into its renderer.
    func=s.index('void FFakeStereoRenderingHook::begin_render_viewfamily(ISceneViewExtension*')
    start=s.index('    if (vr->is_quadview_layout_active()) {',func)
    end=s.index('    if (const auto packet = duoview_build_packet;',start)
    block=s[start:end]
    block=replace(block, '                    qv_packet->atlas=qv_native;', '''                    qv_packet->atlas=qv_native;
                    if (native_callback) {
                        qv_packet->native_sources=native_context.native_sources;
                        qv_packet->native_target_owners=native_context.target_owners;
                        qv_packet->native_target_set_generation=native_context.target_set_generation;
                        qv_packet->native_target_set_owner=native_context.target_set;
                    }''')
    block=replace(block, 'const bool registered=g_hook->quadview_delivery.register_bound(std::move(qv_source));', '''bool native_owned=true;
                        if (native_callback) {
                            std::array<uintptr_t,4> native_targets{};
                            for (size_t i=0;i!=4;++i) native_targets[i]=reinterpret_cast<uintptr_t>(native_context.render_targets[i]);
                            native_owned=g_hook->quadview_native_delivery.bind(qv_source,*qv_engine_ticket,
                                native_context.target_set_generation,native_targets);
                            native_context.packet=qv_packet;
                            native_context.engine_frame=frame_count;
                            native_context.source_registered=native_owned;
                        }
                        const bool registered=native_owned && g_hook->quadview_delivery.register_bound(qv_source);
                        if (native_callback && native_owned && !registered)
                            vr->set_quadview_status("Native quartet will drain without publishing: source ledger is full");''')
    block=replace(block,
        '        const auto qv_valid=qv_family_readable && qv_engine_ticket && qv_snapshot &&',
        '''        const bool qv_native_ready=bool(vr->quadview_native_target_set(qv_key));
        const auto qv_valid=qv_family_readable && qv_engine_ticket && qv_snapshot &&
            (!qv_native_ready || native_callback) &&''')
    block=replace(block, 'qv_packet->source_state=is_ue_5_5_runtime()',
        'qv_packet->source_state=!native_callback && is_ue_5_5_runtime()')
    # Even a missing/changed pose must retain engine ownership until the four
    # singleton commands drain. Such a packet is never registered for output.
    if not block.endswith('    }\n'): raise RuntimeError('Unexpected GT registration block ending')
    block=block[:-6]+'''        if (native_callback && !native_context.source_registered && qv_engine_ticket && qv_snapshot) {
            auto discard_packet=std::make_shared<FFakeStereoRenderingHook::QuadViewSourcePacket>();
            discard_packet->native_sources=native_context.native_sources;
            discard_packet->native_target_owners=native_context.target_owners;
            discard_packet->native_target_set_owner=native_context.target_set;
            discard_packet->native_target_set_generation=native_context.target_set_generation;
            discard_packet->serial=qv_key.draw_serial;
            FFakeStereoRenderingHook::QuadViewDelivery::Source discard_source{
                discard_packet,qv_key.generation,qv_key.draw_serial,frame_count,0,
                reinterpret_cast<uintptr_t>(&view_family),reinterpret_cast<uintptr_t>(qv_target),
                reinterpret_cast<uintptr_t>(qv_scene),qv_view_ids};
            std::array<uintptr_t,4> native_targets{};
            for(size_t i=0;i!=4;++i) native_targets[i]=reinterpret_cast<uintptr_t>(native_context.render_targets[i]);
            native_context.source_registered=g_hook->quadview_native_delivery.bind(discard_source,*qv_engine_ticket,
                native_context.target_set_generation,native_targets);
            native_context.packet=discard_packet;
            native_context.engine_frame=frame_count;
            vr->set_quadview_status("Native quartet has no valid pose/source; draining four engine owners without publication");
        }
'''+block[-6:]
    wrapped='''    [&]() {
        auto& native_context=g_hook->quadview_native_build_context;
        const bool native_callback=native_context.active &&
            native_context.family==reinterpret_cast<uintptr_t>(&view_family);
        if (native_callback && native_context.source_registered) return;
        auto* const native_views=view_family.get_views();
        const auto native_saved_count=native_views ? native_views->count : 0;
        auto* const native_saved_target=view_family.get_render_target();
        std::array<sdk::FSceneView*,4> native_saved_views{};
        if (native_callback) {
            if (!native_views || !native_views->data || native_views->capacity<4 ||
                native_context.current_slot!=0) return;
            for(size_t i=0;i!=4;++i) {
                native_saved_views[i]=native_views->data[i];
                native_views->data[i]=native_context.original_views[i];
            }
            native_views->count=4;
            view_family.set_render_target(native_context.original_target);
        }
        utility::ScopeGuard restore_native_registration{[&]() {
            if (!native_callback) return;
            for(size_t i=0;i!=4;++i) native_views->data[i]=native_saved_views[i];
            native_views->count=native_saved_count;
            view_family.set_render_target(native_saved_target);
        }};
'''+block+'''    }();
'''
    s=s[:start]+wrapped+s[end:]
    # Match copied renderer families by one of the four exact owned targets.
    start=s.index('    if (vr->is_quadview_mode_selected()) {',s.index('    std::optional<FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket> quad_engine_opt;'))
    end=s.index('    const auto quad_source=quad_source_opt.value_or',start)
    legacy=s[start:end]
    s=s[:start]+'''    FFakeStereoRenderingHook::QuadViewNativeDelivery::Command quad_native{};
    if (vr->is_quadview_mode_selected()) {
        const auto* native_views=view_family.get_views();
        if (native_views && native_views->count==1) {
            const auto native=g_hook->quadview_native_delivery.render(vr->mono_generation(),frame_count,
                reinterpret_cast<uintptr_t>(view_family.get_render_target()),
                reinterpret_cast<uintptr_t>(view_family.get_scene_interface()));
            if (native) quad_native=*native;
            else vr->set_quadview_status("Rejected a native singleton without an exact quartet owner");
        }
    }
    if (!quad_native) {
'''+legacy+'''    }
'''+s[end:]
    # Every hooked native tail keeps its source/target owner alive.
    anchor='    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket> quad_command_engines{};'
    s=replace(s,anchor,anchor+'\n    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::QuadViewNativeDelivery::TailOwnerBatch> quad_native_commands{};')
    anchor='''        const auto quad_engine=quad_engine_it != quad_command_engines.end()
            ? quad_engine_it->second : FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket{};'''
    s=replace(s,anchor,anchor+'''
        const auto quad_native_it=quad_native_commands.find(cmd);
        // Keep this local lease alive through RHIThreadWorker::execute() and
        // the original command callback. Ledger reset cannot prove that a
        // queued CPU command has drained.
        const auto quad_native_record=quad_native_it != quad_native_commands.end()
            ? quad_native_it->second : FFakeStereoRenderingHook::QuadViewNativeDelivery::TailOwnerBatch{};
        const auto quad_native=quad_native_record.ticket;''')
    s=replace(s,'        quad_command_engines.erase(cmd);','        quad_command_engines.erase(cmd);\n        quad_native_commands.erase(cmd);')
    s=replace(s,'                if (quad_engine && g_hook != nullptr && quad_engine.generation==vr->mono_generation()) {','''                if (quad_native && g_hook != nullptr) {
                    if (!g_hook->quadview_native_delivery.executed_tail(quad_native,GetCurrentThreadId()).accepted)
                        vr->set_quadview_status("Native quartet RHI execution did not match its exact target owner");
                }
                if (quad_engine && g_hook != nullptr && quad_engine.generation==vr->mono_generation()) {''')
    s=replace(s,'        const FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket& quad_engine = {}) {','''        const FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket& quad_engine = {},
        const FFakeStereoRenderingHook::QuadViewNativeDelivery::Command& quad_native = {}) {''')
    s=replace(s,'        if (quad_engine && quad_engine.generation!=vr->mono_generation()) return;', '''        if (quad_engine && quad_engine.generation!=vr->mono_generation()) return;
        if (quad_native && quad_native.source.generation!=vr->mono_generation()) return;''')
    s=replace(s,'        if (quad_native && quad_native.source.generation!=vr->mono_generation()) return;',
        '        if (quad_native && quad_native.source.generation!=vr->mono_generation()) return;\n'
        '        if (vr->is_quadview_mode_selected() && !quad_native && !quad_engine && !quad_source) return;')
    s=replace(s,'        if (quad_engine) {\n            const char* root_rejection{};', '        if (quad_engine || quad_native) {\n            const char* root_rejection{};')
    s=replace(s,'''            if (original_vtables.contains(last_command)) {
                const auto owner=quad_command_engines.find(last_command);
                if (owner == quad_command_engines.end() || !owner->second.same_owner(quad_engine))
                    vr->set_quadview_status("RHI command tail is already owned by a different family");
                return;
            }''','''            if (original_vtables.contains(last_command)) {
                if (quad_native) {
                    const auto existing=quad_native_commands.find(last_command);
                    if (existing==quad_native_commands.end()) {
                        vr->set_quadview_status("Shared native command tail has no retained owner ticket");
                        return;
                    }
                    const auto drain=uevr::quadview::NativeDrainScope::current();
                    const auto attached=g_hook->quadview_native_delivery.hook_batch(quad_native,
                        reinterpret_cast<uintptr_t>(last_command),drain.id,drain.immediate_list,frame_count);
                    if (!attached || attached.tail.id!=existing->second.ticket.id ||
                        !existing->second.retain(quad_native,attached.tail)) {
                        vr->set_quadview_status("Could not retain every owner attached to a shared native tail");
                        return;
                    }
                    if (!attached.publishable())
                        vr->set_quadview_status("Shared native tail is drain-only because its owner order is ambiguous");
                }
                const auto owner=quad_command_engines.find(last_command);
                if (quad_engine && (owner == quad_command_engines.end() || !owner->second.same_owner(quad_engine)))
                    vr->set_quadview_status("RHI command tail also contains a different tracked engine-family owner");
                return;
            }''')
    s=replace(s,'        if (quad_source) {\n            quad_command_sources.emplace(last_command, quad_source);', '''        if (quad_native) {
            const auto drain=uevr::quadview::NativeDrainScope::current();
            const auto attached=g_hook->quadview_native_delivery.hook_batch(quad_native,
                reinterpret_cast<uintptr_t>(last_command),drain.id,drain.immediate_list,frame_count);
            if (!attached) {
                vr->set_quadview_status("Native quartet command could not attach to its exact RHI tail; engine owner remains tracked");
                original_vtables.erase(last_command); return;
            }
            if (!attached.publishable())
                vr->set_quadview_status("Native quartet command tail is drain-only because its owner order is ambiguous");
            FFakeStereoRenderingHook::QuadViewNativeDelivery::TailOwnerBatch owner_batch{};
            if (!owner_batch.retain(quad_native,attached.tail)) {
                vr->set_quadview_status("Native quartet tail could not retain its packet owner");
                original_vtables.erase(last_command); return;
            }
            quad_native_commands.emplace(last_command,owner_batch);
        }
        if (quad_source) {
            quad_command_sources.emplace(last_command, quad_source);''')
    # Only the final singleton advances runtime pose/synchronization work.
    s=replace(s,'                if (!duo_source || (vr->is_duoview_renderer_active() && duo_source.generation==vr->mono_generation()))\n                    runtime->enqueue_render_poses(frame_count);','''                if ((!quad_native || quad_native_runtime_claimed) &&
                    (!duo_source || (vr->is_duoview_renderer_active() && duo_source.generation==vr->mono_generation())))
                    runtime->enqueue_render_poses(quad_native_runtime_claimed ? quad_native_runtime_event.frame : frame_count);''')
    s=replace(s,'        if (vr->get_synchronize_stage() == VR::SynchronizeStage::EARLY &&\n            (!duo_source', '        if ((!quad_native || quad_native_runtime_claimed) &&\n            vr->get_synchronize_stage() == VR::SynchronizeStage::EARLY &&\n            (!duo_source')
    hook_begin=s.index('    template<int N>\n    static void* hooked_command_fn(')
    hook_end=s.index('    static void hook_new_rhi_command(',hook_begin)
    hook_part=s[hook_begin:hook_end]
    hook_part=replace(hook_part,'        auto runtime = vr->get_runtime();\n\n        auto call_orig = [=]() {','''        auto runtime = vr->get_runtime();
        FFakeStereoRenderingHook::QuadViewNativeDelivery::RuntimeEvent quad_native_runtime_event{};
        const bool quad_native_runtime_claimed=N==correct_execute_index && quad_native && g_hook &&
            g_hook->quadview_native_delivery.claim_runtime_event(quad_native,quad_native_runtime_event);
        const auto runtime_frame_count=quad_native_runtime_claimed ? quad_native_runtime_event.frame : frame_count;

        auto call_orig = [=]() {''')
    hook_part=replace(hook_part,'        RHIThreadWorker::get().execute();','''        if (quad_native_runtime_claimed)
            runtime->on_pre_render_render_thread(runtime_frame_count);
        RHIThreadWorker::get().execute();''')
    hook_part=hook_part.replace('runtime->synchronize_frame(frame_count,','runtime->synchronize_frame(runtime_frame_count,')
    s=s[:hook_begin]+hook_part+s[hook_end:]
    # There are two on_pre_render calls in hook_new_rhi_command; other methods
    # retain their ordinary source handling.
    begin=s.index('    static void hook_new_rhi_command('); finish=s.index('\n    static ',begin+20)
    part=s[begin:finish]
    part=part.replace('runtime->on_pre_render_render_thread(frame_count);','if (!quad_native) runtime->on_pre_render_render_thread(frame_count);')
    part=part.replace('            runtime->enqueue_render_poses(frame_count);','            if (!quad_native) runtime->enqueue_render_poses(frame_count);')
    s=s[:begin]+part+s[finish:]
    for anchor in [
        'reinterpret_cast<sdk::FRHICommandBase_New*>(*root), frame_count + compensation, duo_source, quad_source, quad_engine);',
        'hook_new_rhi_command(root, frame_count + compensation, duo_source, quad_source, quad_engine);',
        'hook_new_rhi_command((sdk::FRHICommandBase_New*)l->root, frame_count + compensation, duo_source, quad_source, quad_engine);',
        'hook_new_rhi_command((sdk::FRHICommandBase_New*)cmd_list->root, frame_count + compensation, duo_source, quad_source, quad_engine);']:
        s=replace(s,anchor,anchor.replace('quad_engine);','quad_engine, quad_native);'))
    worker_drain=re.compile(r'(?m)^(?P<indent>[ \t]*)g_hook->get_slate_thread_worker\(\)->execute\((?P<arg>[^;]+)\);$')
    def scope_worker_drain(match):
        indent=match.group('indent'); arg=match.group('arg')
        return (f'{indent}{{ uevr::quadview::NativeDrainScope qv_drain_scope'
            f'{{reinterpret_cast<uintptr_t>({arg})}}; '
            f'g_hook->get_slate_thread_worker()->execute({arg}); }}')
    s,worker_drain_count=worker_drain.subn(scope_worker_drain,s)
    if worker_drain_count != 6:
        raise RuntimeError(f'Expected six validated Slate worker execute sites, found {worker_drain_count}')
    s=replace(s,'''\n};

template<int N>
void SceneViewExtensionAnalyzer::FillVtable<N>::fill''','''\n};

QuadViewNativeRhiQueueSnapshot sample_quadview_native_rhi_queue() {
    QuadViewNativeRhiQueueSnapshot result{};
    try {
        std::unique_lock lock{SceneViewExtensionAnalyzer::vtable_mutex, std::try_to_lock};
        if (!lock.owns_lock()) { result.busy = true; return result; }
        result.observed = true;
        result.tail_owner_records = SceneViewExtensionAnalyzer::quad_native_commands.size();
        result.tracked_engine_records = SceneViewExtensionAnalyzer::quad_command_engines.size();
        result.hooked_command_records_all_modes = SceneViewExtensionAnalyzer::original_vtables.size();
    } catch (...) { result.busy = true; }
    return result;
}

template<int N>
void SceneViewExtensionAnalyzer::FillVtable<N>::fill''')
    h=replace(h, '        quadview_native_delivery.reset();',
        '        quadview_native_delivery.reset();\n        if (auto* manager=get_render_target_manager()) manager->retire_quadview_native_target_set();')
    vp=root/'src/mods/VR.cpp'; v=vp.read_text()
    v=replace(v, '        m_fake_stereo_hook->quadview_delivery.retire_generation(retired_generation);',
        '        m_fake_stereo_hook->quadview_delivery.retire_generation(retired_generation);\n'
        '        m_fake_stereo_hook->quadview_native_delivery.reset();\n'
        '        if (auto* manager=m_fake_stereo_hook->get_render_target_manager()) manager->retire_quadview_native_target_set();')
    v=replace(v, '    m_quadview.retire_generation(retired_generation);',
        '    m_quadview.retire_generation(retired_generation);\n'
        '    { std::scoped_lock lock{m_quadview_layout_mutex}; if (m_quadview_draw_config) {\n'
        '        m_quadview_draw_config->native_target_set.reset();\n'
        '        m_quadview_draw_config->native_target_set_ready=false;\n'
        '        m_quadview_draw_config->native_target_set_generation=0;\n    } }')
    vp.write_text(v)
    hp.write_text(h);cp.write_text(s)
    shutil.copyfile(src/'QuadViewNativeDelivery.hpp',root/'src/mods/vr/QuadViewNativeDelivery.hpp')
    shutil.copyfile(src/'QuadViewFamilyRouting.hpp',root/'src/mods/vr/QuadViewFamilyRouting.hpp')
    print('Applied exact four-target native GT/RT/RHI ownership adapter.')
if __name__=='__main__':main()

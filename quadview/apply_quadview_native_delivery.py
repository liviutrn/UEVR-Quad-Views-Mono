#!/usr/bin/env python3
"""Four-target GT/RT/RHI ownership integration, after the guarded ID7 overlays."""
from pathlib import Path
import sys, shutil

def replace(s, old, new):
    n=s.count(old)
    if n!=1: raise RuntimeError(f'Native delivery expected one anchor, found {n}: {old[:100]!r}')
    return s.replace(old,new,1)

def main():
    root=Path(sys.argv[1]); src=Path(__file__).parent
    hp=root/'src/mods/vr/FFakeStereoRenderingHook.hpp'
    cp=root/'src/mods/vr/FFakeStereoRenderingHook.cpp'
    h=hp.read_text(); s=cp.read_text()
    h=replace(h, '#include "QuadViewDelivery.hpp"', '#include "QuadViewDelivery.hpp"\n#include "QuadViewNativeDelivery.hpp"')
    h=replace(h, '    mutable QuadViewDelivery quadview_delivery{};', '''    mutable QuadViewDelivery quadview_delivery{};
    using QuadViewNativeDelivery = uevr::quadview::NativeDelivery<QuadViewDelivery>;
    mutable QuadViewNativeDelivery quadview_native_delivery{quadview_delivery};''')
    h=replace(h, '        quadview_delivery.retire_all();', '        quadview_delivery.retire_all();\n        quadview_native_delivery.reset();')
    # The first engine callback supplies the initialized engine frame number.
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
    s=replace(s,anchor,anchor+'\n    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::QuadViewNativeDelivery::Command> quad_native_commands{};')
    anchor='''        const auto quad_engine=quad_engine_it != quad_command_engines.end()
            ? quad_engine_it->second : FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket{};'''
    s=replace(s,anchor,anchor+'''
        const auto quad_native_it=quad_native_commands.find(cmd);
        const auto quad_native=quad_native_it != quad_native_commands.end()
            ? quad_native_it->second : FFakeStereoRenderingHook::QuadViewNativeDelivery::Command{};''')
    s=replace(s,'        quad_command_engines.erase(cmd);','        quad_command_engines.erase(cmd);\n        quad_native_commands.erase(cmd);')
    s=replace(s,'                if (quad_engine && g_hook != nullptr && quad_engine.generation==vr->mono_generation()) {','''                if (quad_native && g_hook != nullptr) {
                    if (!g_hook->quadview_native_delivery.executed(quad_native,
                            reinterpret_cast<uintptr_t>(cmd),GetCurrentThreadId()))
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
    s=replace(s,'        if (quad_source) {\n            quad_command_sources.emplace(last_command, quad_source);', '''        if (quad_native) {
            if (!g_hook->quadview_native_delivery.hook(quad_native,reinterpret_cast<uintptr_t>(last_command))) {
                vr->set_quadview_status("Native quartet command tail was aliased, duplicated or unowned");
                original_vtables.erase(last_command); return;
            }
            quad_native_commands.emplace(last_command,quad_native);
        }
        if (quad_source) {
            quad_command_sources.emplace(last_command, quad_source);''')
    # Only the final singleton advances runtime pose/synchronization work.
    s=replace(s,'                if (!duo_source || (vr->is_duoview_renderer_active() && duo_source.generation==vr->mono_generation()))\n                    runtime->enqueue_render_poses(frame_count);','''                if ((!quad_native || quad_native.view==3) &&
                    (!duo_source || (vr->is_duoview_renderer_active() && duo_source.generation==vr->mono_generation())))
                    runtime->enqueue_render_poses(frame_count);''')
    s=replace(s,'        if (vr->get_synchronize_stage() == VR::SynchronizeStage::EARLY &&\n            (!duo_source', '        if ((!quad_native || quad_native.view==3) &&\n            vr->get_synchronize_stage() == VR::SynchronizeStage::EARLY &&\n            (!duo_source')
    # There are two on_pre_render calls in hook_new_rhi_command; other methods
    # retain their ordinary source handling.
    begin=s.index('    static void hook_new_rhi_command('); finish=s.index('\n    static ',begin+20)
    part=s[begin:finish]
    part=part.replace('runtime->on_pre_render_render_thread(frame_count);','if (!quad_native || quad_native.view==3) runtime->on_pre_render_render_thread(frame_count);')
    s=s[:begin]+part+s[finish:]
    for anchor in [
        'reinterpret_cast<sdk::FRHICommandBase_New*>(*root), frame_count + compensation, duo_source, quad_source, quad_engine);',
        'hook_new_rhi_command(root, frame_count + compensation, duo_source, quad_source, quad_engine);',
        'hook_new_rhi_command((sdk::FRHICommandBase_New*)l->root, frame_count + compensation, duo_source, quad_source, quad_engine);',
        'hook_new_rhi_command((sdk::FRHICommandBase_New*)cmd_list->root, frame_count + compensation, duo_source, quad_source, quad_engine);']:
        s=replace(s,anchor,anchor.replace('quad_engine);','quad_engine, quad_native);'))
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
    print('Applied exact four-target native GT/RT/RHI ownership adapter.')
if __name__=='__main__':main()

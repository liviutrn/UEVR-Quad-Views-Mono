#!/usr/bin/env python3
"""B28: retire publication on real world replacement without dropping CPU leases.

Run after B26 and B28 pose repair. Draw serials are monotonic across worlds;
old renderer callbacks may drain, but cannot affect the new world's XR frame.
"""
from pathlib import Path
import shutil
import sys


def one(s, old, new):
    if s.count(old) != 1:
        raise RuntimeError(f'B28 world anchor count {s.count(old)}: {old[:100]!r}')
    return s.replace(old, new, 1)


def main():
    root=Path(sys.argv[1])/'src/mods'
    p=root/'VR.hpp'; s=p.read_text(encoding='utf-8')
    s='#include "vr/TriViewEpochGate.hpp"\n'+s
    s=one(s, '    std::atomic<uint64_t> m_quadview_draw_serial{};', '''    std::atomic<uint64_t> m_quadview_draw_serial{};
    std::atomic<uint64_t> m_triview_world_first_serial{};
    uevr::triview::EpochGate m_triview_world_epoch_gate{};''')
    s=one(s, '    int triview_restart_phase() const noexcept {', '''    // Public query for RHI and presentation adapters; the cutoff remains private.
    bool triview_source_epoch_accepts(uint64_t serial) const {
        return serial && serial>=m_triview_world_first_serial.load(std::memory_order_acquire);
    }
    auto triview_epoch_read() const { return m_triview_world_epoch_gate.read(); }
    bool triview_world_epoch_closed() const { return m_triview_world_epoch_gate.closed(); }
    int triview_restart_phase() const noexcept {''')
    p.write_text(s,encoding='utf-8',newline='\n')
    p=root/'VR.cpp';s=p.read_text(encoding='utf-8')
    s=one(s, '''void VR::service_mono_transition_game_thread() {
    auto& selection = m_rendering_method->selection();''', '''void VR::service_mono_transition_game_thread() {
    auto& selection = m_rendering_method->selection();
    // GT is the authoritative observer of UWorld identity. Address equality
    // alone is insufficient: Unreal can reuse the address after a save load.
    {
        static uintptr_t observed_world{};
        static std::optional<sdk::object_liveness::Identity> observed_identity{};
        static bool dirty_world{}; // Survives a canceled request to leave ID7.
        auto* engine=sdk::UGameEngine::get();
        auto* world=engine ? engine->get_world() : nullptr;
        const bool identity_valid=observed_identity && sdk::is_current_object(*observed_identity);
        const bool changed=reinterpret_cast<uintptr_t>(world)!=observed_world ||
            (world && !identity_valid);
        std::optional<sdk::object_liveness::Identity> new_identity{};
        if (changed && world) {
            if (const auto observed=sdk::observe_uobject(static_cast<sdk::UObjectBase*>(world)))
                new_identity=observed->identity;
        }
        if (changed && is_quadview_mode_selected()) dirty_world=true;
        const bool recovery_pending=m_triview_world_epoch_gate.closed() || dirty_world;
        const bool leaving_triview=selection.pending() && selection.requested()!=RenderingMethod::QUAD_VIEWS_STEREO;
        if (recovery_pending && (!is_quadview_mode_selected() || leaving_triview)) {
            // A user may switch modes or a transient world may revert while
            // recovery is waiting. Do not leave a closed gate latched forever.
            if (!m_triview_world_epoch_gate.try_close()) return;
            m_triview_world_epoch_gate.open();
        }
        if ((changed || recovery_pending) && is_quadview_mode_selected() && !leaving_triview) {
            if (!changed && identity_valid) new_identity=observed_identity;
            // Keep every engine/RHI ledger and packet lease until its actual
            // callback. Only revoke old publication and cached world assumptions.
            m_triview_world_first_serial.store(m_quadview_draw_serial.load(std::memory_order_acquire)+1,
                std::memory_order_release);
            // Close admission first. Never block GT on an RHI/XR callback:
            // retry this boundary at the next draw after old readers drain.
            if (!m_triview_world_epoch_gate.try_close()) {
                set_quadview_status("World recovery: draining the previous XR transaction");
                return;
            }
            if (world && !new_identity) {
                // Keep admission closed, but do not retire/recreate targets on
                // every failed identity probe. Retry the identity next GT tick.
                set_quadview_status("World recovery: waiting for a valid Unreal world identity");
                return;
            }
            utility::ScopeGuard reopen_world_epoch{[this]() { m_triview_world_epoch_gate.open(); }};
            if (m_openxr) {
                m_openxr->invalidate_quadview_located_pose();
                m_openxr->invalidate_quadview_scene();
            }
            if (m_fake_stereo_hook) if (auto* manager=m_fake_stereo_hook->get_render_target_manager())
                manager->retire_quadview_native_target_set();
            m_triview_hold_set.reset();
            m_triview_resize_gate.reset();
            m_triview_resize_world_identity=0;
            m_triview_pending_extents_valid=false;
            m_quadview_candidate_key.store(nullptr,std::memory_order_release);
            {
                std::scoped_lock layout_lock{m_quadview_layout_mutex};
                m_quadview_draw_config.reset();
            }
            {
                std::scoped_lock pose_lock{m_quadview_pose_mutex};
                m_quadview_pose.reset(); m_quadview_pose_eye_mask=0;
            }
            spdlog::info("[TriView][B28][World] world epoch changed; first_serial={} old callbacks drain without publication",
                m_triview_world_first_serial.load(std::memory_order_acquire));
            dirty_world=false;
        }
        if ((changed || recovery_pending) && (!is_quadview_mode_selected() || !leaving_triview)) {
            observed_world=reinterpret_cast<uintptr_t>(world);
            observed_identity=new_identity;
        }
        if (!is_quadview_mode_selected()) dirty_world=false; // Actual mode commit retired the previous world.
    }''')
    s=one(s, '''std::optional<uevr::quadview::Snapshot> VR::quadview_begin_frame() {
    const bool renderer_active=is_quadview_renderer_active();''',
        '''std::optional<uevr::quadview::Snapshot> VR::quadview_begin_frame() {
    if (m_triview_world_epoch_gate.closed()) {
        set_quadview_status("World recovery: source admission closed until XR callbacks and world identity are ready");
        return {};
    }
    const bool renderer_active=is_quadview_renderer_active();''')
    p.write_text(s,encoding='utf-8',newline='\n')
    p=root/'vr/FFakeStereoRenderingHook.cpp';s=p.read_text(encoding='utf-8')
    s=one(s, '''        FFakeStereoRenderingHook::QuadViewNativeDelivery::RuntimeEvent quad_native_runtime_event{};''',
        '''        // Hold admission through the actual XR side effects, not just
        // their serial check. GT closes nonblockingly and retries while we drain.
        const bool quad_epoch_needed=bool(quad_native) || bool(quad_source) || bool(quad_engine) || quad_drain.count!=0;
        auto quad_epoch_lease=quad_epoch_needed ? vr->triview_epoch_read() : uevr::triview::EpochGate::Read{};
        const bool quad_epoch_admitted=!quad_epoch_needed || bool(quad_epoch_lease);
        FFakeStereoRenderingHook::QuadViewNativeDelivery::RuntimeEvent quad_native_runtime_event{};''')
    s=one(s, '''        const bool quad_native_runtime_claimed=N==correct_execute_index && quad_native && g_hook &&
            g_hook->quadview_native_delivery.claim_runtime_event(quad_native,quad_native_runtime_event);''',
        '''        const bool quad_native_runtime_claimed=N==correct_execute_index && quad_native && g_hook && quad_epoch_admitted &&
            vr->triview_source_epoch_accepts(quad_native.source.serial) &&
            g_hook->quadview_native_delivery.claim_runtime_event(quad_native,quad_native_runtime_event);''')
    cadence='quad_drain.allows_runtime(vr->mono_generation(),quad_engine)'
    if s.count(cadence)!=2: raise RuntimeError('B28 world: expected both recovery XR cadence sites')
    s=s.replace(cadence,'''(quad_epoch_admitted &&
                    (!quad_source || vr->triview_source_epoch_accepts(quad_source.serial)) &&
                    (!quad_engine || vr->triview_source_epoch_accepts(quad_engine.serial)) &&
                    (!quad_drain.count || vr->triview_source_epoch_accepts(quad_drain.newest_serial)) &&
                    quad_drain.allows_runtime(vr->mono_generation(),quad_engine))''')
    s=one(s, '''    auto* engine=sdk::UGameEngine::get();
    auto* world=engine ? engine->get_world() : nullptr;
    auto* kismet=sdk::UKismetRenderingLibrary::get();''',
        '''    if (vr->triview_world_epoch_closed()) return false;
    auto* engine=sdk::UGameEngine::get();
    auto* world=engine ? engine->get_world() : nullptr;
    auto* kismet=sdk::UKismetRenderingLibrary::get();''')
    s=one(s, '''    worker->enqueue_conditional([this,build](FRHICommandListImmediate*) {
        {''',
        '''    worker->enqueue_conditional([this,build](FRHICommandListImmediate*) {
        auto quad_build_epoch_lease=VR::get()->triview_epoch_read();
        if (!quad_build_epoch_lease) return false;
        {''')
    p.write_text(s,encoding='utf-8',newline='\n')
    p=root/'vr/D3D12Component.cpp';s=p.read_text(encoding='utf-8')
    s=one(s, '''                    if (vr->is_quadview_mode_selected()) {
                        const auto& stereo=vr->get_fake_stereo_hook();''',
        '''                    if (vr->is_quadview_mode_selected()) {
                        auto quad_epoch_lease=vr->triview_epoch_read();
                        const auto& stereo=vr->get_fake_stereo_hook();''')
    s=one(s, '''                        const auto source=stereo && vr->is_quadview_renderer_active()''',
        '''                        const auto source=quad_epoch_lease && stereo && vr->is_quadview_renderer_active()''')
    s=one(s, '''                        if (source && source->packet && source->packet->producer && source->packet->atlas) {''',
        '''                        if (source && vr->triview_source_epoch_accepts(source->serial) &&
                            source->packet && source->packet->producer && source->packet->atlas) {''')
    p.write_text(s,encoding='utf-8',newline='\n')
    p=root/'vr/runtimes/OpenXR.cpp';s=p.read_text(encoding='utf-8')
    s=one(s, '''    uevr::ui_composition::Compositor* ui_composition) {
    std::scoped_lock _{sync_mtx};''',
        '''    uevr::ui_composition::Compositor* ui_composition) {
    const bool quad_epoch_needed=VR::get()->is_quadview_mode_selected();
    auto quad_epoch_lease=quad_epoch_needed ? VR::get()->triview_epoch_read() : uevr::triview::EpochGate::Read{};
    if (quad_epoch_needed && !quad_epoch_lease) return XR_ERROR_SESSION_NOT_READY;
    std::scoped_lock _{sync_mtx};''')
    s=one(s, '''        if (vr->is_quadview_renderer_active() && quadview_pose_generation==vr->mono_generation()) {
            if (quadview_pending_pose) {''',
        '''        if (vr->is_quadview_renderer_active() && quadview_pose_generation==vr->mono_generation()) {
            if (quadview_pending_pose && !vr->triview_source_epoch_accepts(quadview_pending_pose->quadview_serial))
                quadview_pending_pose.reset();
            if (quadview_submitted_pose && !vr->triview_source_epoch_accepts(quadview_submitted_pose->quadview_serial)) {
                quadview_submitted_pose.reset(); quadview_continuity.reset();
            }
            if (quadview_pending_pose) {''')
    anchor='''void OpenXR::note_quadview_copy(PipelineState pose, uint64_t generation) {
    std::scoped_lock lock{this->sync_assignment_mtx};'''
    s=one(s,anchor,anchor+'''
    // Recheck under the same mutex used by GT world invalidation. A world
    // change can occur after Present selected its source but before GPU copy.
    if (!VR::get()->triview_source_epoch_accepts(pose.quadview_serial)) return;''')
    p.write_text(s,encoding='utf-8',newline='\n')
    shutil.copyfile(Path(__file__).with_name('TriViewEpochGate.hpp'),root/'vr/TriViewEpochGate.hpp')
    print('B28: real world identity invalidates cached state; old CPU owners drain without new-world XR side effects')


if __name__=='__main__': main()

#!/usr/bin/env python3
"""Final generated-source integration checks, in addition to executable tests.

These verify overlay ordering/wiring; they are not a Windows compile or a
headset/driver lifetime proof. Run after the last B28 overlay.
"""
from pathlib import Path
import sys

root=Path(sys.argv[1])/'src/mods'
vrh=(root/'VR.hpp').read_text()
vr=(root/'VR.cpp').read_text()
hook=(root/'vr/FFakeStereoRenderingHook.cpp').read_text()
xr=(root/'vr/runtimes/OpenXR.cpp').read_text()
dx=(root/'vr/D3D12Component.cpp').read_text()


def require(condition,message):
    if not condition: raise RuntimeError('B28 integration: '+message)


def block(text,start,end):
    a=text.index(start); return text[a:text.index(end,a)]


owner=block(hook,'struct VRRenderTargetManager_Base::QuadViewNativeTargetOwner {',
    '\nbool VRRenderTargetManager_Base::create_ue58_ui_texture()')
require('const std::array<uintptr_t,100>* hooked_vtable' in owner,'target owner still owns destructible virtual table')
require('PersistentGammaTables<100>' in owner,'permanent bounded table not installed')
require('=owner->original_vtable_address' not in owner and '=prior->original_vtable_address' not in owner,
    'retirement/cancellation can still write into a stale render target')
require(owner.count('if (i==1) continue')>=3,'three physical sources contract changed')
gamma=block(hook,'float VRRenderTargetManager_Base::quadview_native_capture_display_gamma(',
    '\nvoid VRRenderTargetManager_Base::service_quadview_native_target_retirements_after_present')
require('quadview_cached_display_gamma.load' in gamma and 'g_hook' not in gamma and 'get_viewport' not in gamma,
    'permanent gamma callback still follows transient engine/plugin pointers')
for reader in ['capture_quadview_pose(uint32_t frame)','capture_quadview_current_pose()']:
    fn=block(xr,'OpenXR::'+reader,'\n}')
    require('pipeline_states[' not in fn,'pose getter trusts a relabeled scene-role ring slot')
require('quadview_latest_located_pose.publish(pipeline_state)' in xr,'locate snapshot never published')
require('quadview_head_view_count==2' in xr and 'quadview_head_views={this->views[0],this->views[1]}' in xr,
    'snapshot does not authenticate/copy head-space eyes')
camera=block(hook,'__forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(',
    '__forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_matrix(')
require('qv_pose->view_space_location.pose' in camera and 'qv_pose->quadview_head_views' in camera,
    'camera still mixes a live head/eye state with the submitted snapshot')
require('const auto eye_translation_rotation = (mono || qv_pose)' in camera,'canted head-space translation is wrong')
eye=block(vrh,'    bool quadview_note_eye_pose(','    std::optional<runtimes::OpenXR::PipelineState> quadview_frozen_pose')
require('located_serial!=m_quadview_pose->quadview_locate_serial' in eye,'camera proof is not tied to frozen locate')
require('capture_quadview_current_pose' not in eye,'new asynchronous locate can starve a correctly frozen draw')
query_pos=vrh.index('    bool triview_source_epoch_accepts(')
access=vrh[:query_pos]
require(access.rfind('public:')>access.rfind('private:'),'adapter epoch query is private and cannot compile')
world=block(vr,'void VR::service_mono_transition_game_thread() {','    // TriView B24:')
require('sdk::is_current_object' in world and 'sdk::observe_uobject' in world,'world address reuse is not checked')
require('m_quadview_draw_serial.load(std::memory_order_acquire)+1' in world,'already issued serial can survive epoch closure')
require(world.index('try_close()')<world.index('invalidate_quadview_located_pose()'),'state invalidated underneath active readers')
require('engine_commands_retired' not in world and 'quadview_delivery.retire' not in world,
    'world change drops outstanding CPU/RHI owners instead of letting them drain')
require('quad_epoch_lease' in hook and 'quad_epoch_admitted' in hook,'RHI check is not leased through side effects')
require('auto quad_epoch_lease=vr->triview_epoch_read();' in dx,'Present copy/publication has no epoch lease')
endframe=block(xr,'XrResult OpenXR::end_frame(', '    emit_openxr_state_probes')
require(endframe.index('triview_epoch_read()')<endframe.index('sync_mtx'),'XR submit gate has inverted lock order')
reset=block(vrh,'    std::optional<std::string> reinitialize_openxr()', '\n    float m_nearz')
require(reset.index('if (!m_d3d12.openxr().destroy_swapchains())')<reset.index('m_openxr.reset()'),
    'runtime destroyed even though swapchain teardown vetoed')
require('std::atomic<uint64_t> m_triview_restart_previous_native_serial' in vrh,
    'old session native pair can satisfy restart readiness')
require('static bool dirty_world' in world and 'dirty_world=false' in world,
    'canceled leave request can lose an unfinished world recovery')
require('bool(quad_source)' in hook and 'quad_build_epoch_lease' in hook,
    'source-only callbacks or asynchronous target builds bypass world admission')
claim=block(hook,'        const bool quad_native_runtime_claimed=', '        const auto runtime_frame_count=')
require('quad_native.source' not in claim,
    'RHI TailTicket has no source member; use the authenticated RuntimeEvent serial')
require(claim.index('claim_runtime_event(')<claim.index('triview_source_epoch_accepts(quad_native_runtime_event.serial)'),
    'world cutoff must validate the real serial returned by the successful runtime event claim')
print('B28 final generated integration checks passed (not a Windows build or BSOD certification)')

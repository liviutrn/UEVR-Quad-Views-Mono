#!/usr/bin/env python3
"""Generated-source contracts for goal D switch 1 (fovea depth grid 1024 / 4096). No GPU.

Off (1024) must keep the baseline PSOs, the baseline field and an unchanged constant
buffer; 4096 code exists only in DUOVIEW_GOALD_GRID blocks and separate m4g_* PSOs."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_duoview_goald import strip_goald  # noqa: E402

backend, shaders = map(Path, sys.argv[1:3])
vr = backend / 'src/mods/vr'
hlsl = (shaders / 'DuoViewM1Stereo.hlsl').read_text(encoding='utf-8')
m1 = (vr / 'DuoViewM1D3D12.hpp').read_text(encoding='utf-8')
comp = (vr / 'DuoViewD3D12.hpp').read_text(encoding='utf-8')
cfg = (vr / 'DuoViewConfig.hpp').read_text(encoding='utf-8')
vrcpp = (backend / 'src/mods/VR.cpp').read_text(encoding='utf-8')
log = (vr / 'D3D12Component.cpp').read_text(encoding='utf-8')
fails = []


def need(cond, what):
    if not cond:
        fails.append(what)


off = strip_goald(hlsl)
for token in ('CSConditionM4G', 'GDRow', 'DUOVIEW_GOALD_GRID'):
    need(token not in off, f'Off shader text contains {token}')
need(hlsl.count('#ifdef DUOVIEW_GOALD_GRID') == 7, 'goal D shader blocks: conditioning + raster helper + raster root choice + fast raster read + warp bypass + search steps (2)')
need('(M6PreviousRect.y&128u)!=0u' in hlsl and 'gfEdge>=max(M4Flags.w,.0001)' in hlsl, 'fast raster: fovea-only read only where the crop blend is 1')
need('void CSConditionM4G(' in hlsl and 'void CSConditionM4GVertical(' in hlsl, 'goal D kernels present')
# Groupshared budget of the new kernels: one 4096-float row only (16 KiB).
block = hlsl.split('#ifdef DUOVIEW_GOALD_GRID', 1)[1].split('#endif', 1)[0]
shared = re.findall(r'groupshared\s+float\s+(\w+)\[(\d+)\]', block)
need(shared == [('GDRow', '4096')], f'goal D groupshared {shared}')
need('void CSGoalDHistory(' in block and 'void CSConditionM4GH(' in block, 'switch 2 kernels present')
need('RWTexture2DArray<uint> GDHistory : register(u6);' in block, 'history on the reserved u6 slot')
need('M4FoveaConditioned[uint3(x,row,eye)]' in block, 'switch 3 per-eye slices')
# Constant buffer unchanged: no new cbuffer members.
cb = hlsl.split('cbuffer DuoViewM1', 1)[1].split('};', 1)[0]
need('Goal' not in cb and 'GD' not in cb, 'cbuffer DuoViewM1 unchanged')
need('sizeof(M1Constants) == ' in m1 and 'goald' not in m1.split('struct M1Constants', 1)[1].split('};', 1)[0],
     'M1Constants unchanged')
# Off path: baseline PSOs and field whenever the 4096 field is not active.
need('(m1_.goald_hist_active ? m1_.m4g_condition_h.Get() : m1_.m4g_condition.Get()) : m1_.m4_condition.Get();' in comp, 'condition PSO select')
need(comp.index('goald_bind_history(device);') < comp.index('cmd->SetComputeRootDescriptorTable(8,m4_table);'), 'u6 bound before tables')
need('if (m4_active && m4_hi_active && focus) {' in m1, 'switches 2-4 constants only on the 4096 path')
need('bool goald_history{0}' not in cfg and 'goald_history{0}' in cfg, 'switch 2 default off')
need('m1_.m4_hi_active ? m1_.m4g_vertical.Get() : m1_.m4_vertical.Get()' in comp, 'vertical PSO select')
need('return m4_hi_active && m4_depth_hi ? m4_depth_hi.Get() : m4_depth.Get();' in m1, 'field select')
need(m1.count('m4_hi_active=true;') == 1, 'single activation site')
need('if(edge_reach_px<10.f || m3_edges) goald_grid_reason=1u;' in m1, 'V2-only eligibility')
need('uint32_t depth_grid=1024u' in m1, 'default 1024')
need('goald_bound_key_=0u;' in comp and 'if (key==goald_bound_key_' in comp, 'descriptor rebinding keyed')
need(comp.index('goald_bind_m4_field(device);') < comp.index('cmd->SetComputeRootDescriptorTable(7,m4_table);'),
     'descriptors rebound before tables are set')
need('out.goald_depth_grid=requested.goald_depth_grid>=4096u ? 4096u : 1024u;' in cfg, 'settings sanitize')
need('uint32_t goald_depth_grid{1024};' in cfg, 'settings default 1024')
need('m_duo_goald_grid->value()==1 ? 4096u : 1024u' in vrcpp, 'menu maps to grid')
need('current.goald_depth_grid==candidate.goald_depth_grid' in vrcpp, 'menu change detection')
need('[DuoView][GoalD] grid requested=' in log, 'log line')
need('q.Count = 8;' in comp and 'goald_stamp(cmd,timed,2u);' in comp and 'goald_stamp(cmd,timed,3u);' in comp, 'M4 GPU timestamps')
# Review #368 fixes (11-18 pm).
need('s.parity^=1u' not in m1 and 'const uint32_t next_parity=s.parity^1u;' in m1, 'history parity not advanced in write_constants')
need(comp.count('m1_.goald_commit_history();') == 1 and
     comp.index('m1_.goald_commit_history();') > comp.index('void note_fine_depth_enqueued() {'),
     'history committed only when the XR caller reports the list submitted (review #372 R1)')
need('{ m1_.goald_drop_frame(); error_=reason; return false; }' in comp and
     'if (!m1_active || !m1_.goald_pending.active) m1_.goald_drop_frame();' in comp and
     'm1_.goald_drop_frame(); // goal D: gather never runs the history pass' in comp,
     'history dropped on reject, gather and frames without a history pass (R2)')
need('const bool same_mode=s.type==hist_type && s.jitter_negative==goald_jitter_negative;' in m1 and
     'p.type=hist_type;' in m1 and '(mv_mode ? 16u : 0u)' in m1,
     'history type / jitter sign change starts fresh (R2)')
need('if (s.fresh_counters) return;' in comp and 's.fresh_counters=false;' in m1, 'counters valid only after a submitted pass (R7)')
need('if(float(a+1u)<M6PreviousJitter.y) { best=h; bestAge=a; }' in hlsl and 'bestC' not in hlsl,
     'age tested per candidate before max (R3)')
need('if (!goald_hist_active && goald_history_state().have_previous) goald_drop_shared();' in m1, 'history reset when Off')
need('goald_halo_bg=raster_true && !goald_true_depth;' in m1, 'halo off with true depth')
need('data.m8_effects[2]=data.m8_effects[3]=0.f;' in m1, 'legacy M8 fill zero in halo mode')
need('s.commits-r.first>=16u' in m1, 'retired history textures released')
# After #373 headset (11-18 evening): Thin removed, no camera-locked range, head-still gate.
need('thinOnly' not in hlsl and 'GDLockedCell' not in hlsl and 'GDThinAt' not in hlsl and
     m1.count('64u')==1 and '(mv_mode ? 64u : 0u)' in m1,
     'history: All only, no screen-locked window (#373 lag with head yaw)')
need('m_duo_goald_history->value(),0,1' in vrcpp and 'requested.goald_history,1u' in cfg, 'history menu Off/On')
need('still=mv_mode || (std::isfinite(shift) && (goald_motion_limit>=32.f || shift<=goald_motion_limit));' in m1 and 'const bool use=valid && still;' in m1 and
     'goald_flags|=2u|(use ? 1u : 0u)|' in m1, 'history used only while the head moves <= the limit (32 = no limit); MV mode ungated')
need('data.m6_previous_jitter[3]=mv_mode ? .75f : .5f;' in m1, 'accept radius .5 field texel (pose), .75 (MV own-motion test)')
# Motion-vector history (research 62_, 2026-11-18).
ngx = (backend / 'src/mods/vr/QuadViewNgxDepth.hpp').read_text(encoding='utf-8', errors='replace')
need('ngx_resource(p,"MotionVectors")' in ngx and 'goald_capture_mv(cmd,p,*slot,m25_role==2u,in_w,in_h,desc,dev.Get());' in ngx,
     'MV copied in the fine depth slot of the same Evaluate')
need('if (uint64_t(bx)+in_w>d.Width || uint64_t(by)+in_h>d.Height) { fail(3u); return; }' in ngx and 'd.Width!=depth_desc.Width' not in ngx, 'render-res MV subrect in any MV texture size (#377: 2436x2150 pooled texture)')
need('goald_read_copy_time(*slot);' in ngx and 'ResolveQueryData(goald_ts_heap_.Get()' in ngx and 'GetTimestampFrequency(&goald_f)' in ngx,
     'NGX depth/MV copy GPU timestamps, read after slot reuse')
need('Texture2D<float2> GDMotion : register(t9);' in block and 'abs(float2(c)-s-float2(id.xy))<=radius' in block,
     'MV history: t9 motion, own-motion acceptance test')
need('GDHistory[uint3(id.xy,5u+2u*parity)]' in block and 'u.Texture2DArray.ArraySize=9;' in comp and 't.DepthOrArraySize=9;' in m1,
     'history motion slices 5..8')
need('goald_bind_motion(device);' in comp and comp.index('goald_bind_motion(device);') < comp.index('cmd->SetComputeRootDescriptorTable(7,m4_table);'),
     't9 motion bound before the M4 tables')
need('fine_depth->mv=focus->mv_texture.Get();' in comp_cpp if (comp_cpp := (backend / 'src/mods/vr/D3D12Component.cpp').read_text(encoding='utf-8', errors='replace')) else False,
     'caller passes MV with the fine depth (same lease)')
need('uint32_t goald_motion_source{1};' in cfg and 'requested.goald_motion_source,2u' in cfg, 'motion source default DLSS MVs, sanitized')
need('if (!mv_mode) {'+chr(10)+'                            std::memcpy(data.m6_view' in m1, 'MV mode keeps its own M6View row 0 (head pose rows only without MVs)')
need('(m1_.goald_true_depth || m1_.goald_halo_bg || m1_.goald_fast_raster_on || m1_.goald_raster_variant_on) ? m1_.m4g_raster.Get()' in (backend / 'src/mods/vr/DuoViewD3D12.hpp').read_text(encoding='utf-8', errors='replace'), 'fast raster selects the separate m4g_raster PSO (m1_raster DXBC unchanged)')
need('[DuoView][GoalD] motion mv_frames=' in comp_cpp, 'MV log line')
need('m_duo_goald_motion->draw(' in vrcpp and '.goald_motion_limit=m_duo_goald_motion->value()' in vrcpp and
     'current.goald_motion_limit==candidate.goald_motion_limit' in vrcpp, 'head-still limit in the menu')
need('moving_frames=' in log, 'log counts gated frames')
# Switch 3 removed from the menu; switch 4 distances.
need('m_duo_goald_one_sided' not in vrcpp and 'out.goald_one_sided=0u;' in cfg, 'switch 3 removed')
need('m_duo_goald_halo_near->draw(' in vrcpp and 'm_duo_goald_halo_fade->draw(' in vrcpp and
     'std::memcpy(&data.m6_previous_rect[2],&hn,sizeof(float));' in m1 and
     '(1.0-smoothstep(hbNear,hbFar,hbDist))' in hlsl, 'switch 4 halo near/fade distances')
# Confirm gate + per-stage GPU timing (after #373, Liviu).
need('const int confirmR=int((GDFlags()>>8)&15u);' in hlsl and '((goald_confirm_texels&15u)<<8u)' in m1 and
     'm_duo_goald_confirm->draw(' in vrcpp and 'current.goald_confirm_texels==candidate.goald_confirm_texels' in vrcpp,
     'history confirm distance in the menu')
need('q.Count = 8;' in comp and 'goald_stamp(cmd,timed,4u);' in comp and 'goald_stamp(cmd,timed,5u);' in comp and
     'goald_stamp(cmd,timed,6u);' in comp and 'goald_note_stages(data);' in comp and '[DuoView][Timing] mode=' in log,
     'per-stage GPU timing')
# Review #373 F1/F2/F4.
need('p.seq=++s.record_seq;' in m1 and 'if (p.seq!=s.record_seq) { goald_drop_frame(); return; }' in m1,
     'F1: only the latest recorded history pass is committed')
need('if (m1_.goald_pending.active) m1_.goald_drop_frame();' in comp and
     'uevr::duoview::dx12::M1Resources::goald_drop_shared();' in log, 'F2: unsubmitted / skipped frames drop history')
need('goald_hist_permille.store(0u,std::memory_order_relaxed);' in m1 and
     'if (goald_counter_epoch!=goald_history_state().epoch)' in m1 and 'm1_.goald_counter_epoch=s.epoch;' in comp,
     'F4: % reset on drop, stale readbacks ignored')
need('hbBlend*smoothstep' in hlsl and 'GDReadFineEye(' in hlsl, 'K1: fine vs fine, crop blend weight')
need('duo_goald_modes()' in vrcpp, 'menu shows mode fallbacks')

# Colour path speed-up (2026-11-19): periphery choice is a real branch in m4g_raster only.
native = (shaders / 'DuoViewNativeCompositeRaster.hlsl').read_text(encoding='utf-8')
native_off = strip_goald(native)
need('[branch] if ((SharpenFlags & 8u) != 0u && weight < 1.0)' in native and
     '[branch] if ((SharpenFlags & 8u) != 0u && weight < 1.0)' not in native_off and
     '? SamplePeripheryCatmullRom(' in native_off, 'periphery branch only in goal D; Off keeps the original ternary')

# Raster cost test (65_, 2026-11-19).
need('[branch] if((M6PreviousRect.y&0x100000u)!=0u) return saturate(base); // warp bypass' in hlsl, 'warp bypass returns the homography base (m4g_raster)')
need('const uint gsSteps=8u-((M6PreviousRect.y>>(gsFovea ? 12u : 16u))&7u);' in hlsl and 'if(iteration>=gsSteps) break;' in hlsl,
     'fovea / periphery search steps (0 bits = 8 = today)')
need('const bool gsFovea=all(base>M2Crop.xy) && all(base<M2Crop.zw);' in hlsl, 'fovea test on the homography base')
need('((8u-gs_fovea)<<12u)|((8u-gs_periphery)<<16u)|(goald_warp_bypass ? 0x100000u : 0u)' in m1 and
     '(std::clamp)(goald_fovea_steps,2u,8u)' in m1, 'step bits only on the 4096 path, steps 2..8')
need('uint32_t goald_fovea_steps{8}, goald_periphery_steps{8};' in cfg and 'uint32_t goald_vrs_rate{};' in cfg and
     'uint32_t goald_warp_bypass{};' in cfg, 'raster test defaults = today')
need('if (!goald_vrs_draw(device,cmd,settings.goald_vrs_rate,m1_active && settings.synthetic_stereo,direct_width))' in comp and
     'if (!rate_index) { report(); return false; }' in comp and comp.count('cl5->RSSetShadingRate(D3D12_SHADING_RATE_1X1,nullptr); // restore')==1,
     'VRS Off = the single baseline draw; rate restored after the VRS draws')
need('effective=rate_index>=4u && !goald_vrs_additional_ ? 3u : rate_index;' in comp, 'rates above 2x2 only with AdditionalShadingRatesSupported')
need('[DuoView][GoalD] vrs requested=' in log and 'warp_bypass={} fovea_steps={} periphery_steps={}' in log, 'raster test log lines')
need('m_duo_goald_vrs->draw(' in vrcpp and 'current.goald_vrs_rate==candidate.goald_vrs_rate' in vrcpp and
     'current.goald_fovea_steps==candidate.goald_fovea_steps' in vrcpp, 'raster test menu + change detection')

if fails:
    print('GOALD CONTRACT FAIL:', *fails, sep='\n  ')
    sys.exit(1)
print('GOALD CONTRACTS PASS: Off text/PSOs/field/cbuffer unchanged; switches 1-4 isolated in m4g_* kernels + 4096 path')

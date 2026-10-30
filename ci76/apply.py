"""CI76: exclusive surface composition, explicit NGX resize/recovery, MPC readback.
Apply after CI75; preserve physical cameras, NGX jitter and reconstruction strategies.
"""
from pathlib import Path
import shutil,sys

def replace(p,old,new):
 s=p.read_text()
 if s.count(old)!=1:raise RuntimeError(f'CI76 anchor drift {p.name}: {old[:90]!r}: {s.count(old)}')
 p.write_text(s.replace(old,new))

def apply(root):
 root=Path(root);vr=root/'src/mods/vr';ci=Path(__file__).resolve().parent
 for f in ['DuoViewStereoCompositeRaster.hlsl','DuoViewNgxGuide.hpp']:
  shutil.copyfile(ci/f,vr/f)
 shutil.copyfile(ci/'NgxPairRecovery.hpp',vr/'d3d12/NgxPairRecovery.hpp')
 depth=vr/'d3d12/StockDibrDepth.hpp'
 replace(depth,'class DepthCapture final : public D3D12DepthStencilObserver {','class DepthCapture final : public D3D12DepthStencilObserver {') # verify expected class
 replace(depth,'#pragma once','#pragma once\n#include "NgxPairRecovery.hpp"')
 replace(depth,'    ::duoview::depthpin::RecoveryGate manual_recovery{};',
 '''    ::duoview::depthpin::RecoveryGate manual_recovery{};
    uevr::duoview::ngx::recovery::PairRecovery ngx_recovery{};''')
 replace(depth,'        duoview_source_sizes=requested;',
 '''        duoview_source_sizes=requested;
        // Preserve only the explicitly pinned feature; require fresh copies
        // at the new dimensions before recovery can re-enable stereo.
        uevr::duoview::ngx::manual_registry().set_outputs(requested);
        ngx_recovery.reset();''')
 replace(depth,'                if(wait_foreign(left) && wait_foreign(right)) {',
 '''                if(wait_foreign(left) && wait_foreign(right)) {
                    namespace recovery=uevr::duoview::ngx::recovery;
                    const recovery::Observation recovery_observation{true,
                        {uint64_t(left.ngx_guide.feature),left.ngx_out_width,left.ngx_out_height,
                         uint64_t(right.ngx_guide.feature),right.ngx_out_width,right.ngx_out_height},
                        epoch,{left.serial,right.serial},
                        {left.ngx_guide.evaluation,right.ngx_guide.evaluation}};
                    const auto recovered=ngx_recovery.observe(recovery_observation);
                    if(!recovered.allow) {
                        std::ostringstream status;
                        status<<"CI76_NGX_RECOVERY "<<unsigned(recovered.consecutive_fresh_pairs)
                              <<"/8 fresh pairs; "<<recovery::reason_name(recovered.reason)
                              <<" expected L="<<left_width<<"x"<<left_height
                              <<" R="<<right_width<<"x"<<right_height;
                        r.label=status.str();r.decision=r.label;selection_trace=r.label;
                        return r; // no retained depth; deliberate current-source mono
                    }''')
 replace(depth,'            ++ngx_one_sided;','            ngx_recovery.reject();\n            ++ngx_one_sided;')
 replace(depth,'NGX_MANUAL_PINNED_PAIR_NEARBY_EVALUATIONS_CAMERA_FRAME_UNVERIFIED',
 'CI76_NGX_FRESH_PAIR_8of8_MANUAL_CAMERA_FRAME_UNVERIFIED')
 replace(depth,'            r.label="DLSS-SR pair missing for color packet="+std::to_string(color_packet)+"; keep compositor mono";',
 '''            r.label="CI76 DLSS pair missing for packet="+std::to_string(color_packet)+
                "; current-source mono, expected L="+std::to_string(left_width)+"x"+std::to_string(left_height)+
                " R="+std::to_string(right_width)+"x"+std::to_string(right_height)+
                "; same-feature pins follow resize; a released/replaced feature requires re-pin";''')
 ui=root/'src/mods/VR.cpp';h=root/'src/mods/VR.hpp';cpp=vr/'D3D12Component.cpp'
 replace(h,'    bool duoview_conservative_stereo() const { return m_duo_conservative_stereo->value(); }',
 '''    bool duoview_conservative_stereo() const { return m_duo_conservative_stereo->value(); }
    std::array<float,2> duoview_foreground_mpc_values() const {
        return {m_duo_mpc_enabled.load(),m_duo_mpc_depth.load()};
    }
    bool duoview_foreground_mpc_verified() const {return m_duo_mpc_verified.load();}''')
 replace(h,'    const ModToggle::Ptr m_duo_conservative_stereo{',
 '''    std::atomic<uint64_t> m_duo_periphery_edit_ms{0};
    std::atomic<float> m_duo_mpc_enabled{0.f},m_duo_mpc_depth{0.f};
    std::atomic<bool> m_duo_mpc_verified{false};
    const ModToggle::Ptr m_duo_conservative_stereo{''')
 replace(ui,'        const auto reconcile_foreground = [&]() {',
 '        const auto reconcile_foreground = [&]() {\n            m_duo_mpc_verified.store(false);')
 replace(ui,'            if (!enabled_ok || !depth_ok) {',
 '''            // Verify writes by actual getter values. When no write was
            // needed the values already read are the confirmation.
            float verified_enabled=current_enabled,verified_depth=current_depth;
            const bool reread_enabled=std::abs(current_enabled-wanted_enabled)<=epsilon ||
                read(L"IsFOVEnabled",verified_enabled);
            const bool reread_depth=std::abs(current_depth-wanted_depth)<=epsilon ||
                read(L"DepthScale",verified_depth);
            const bool verified=enabled_ok && depth_ok && reread_enabled && reread_depth &&
                std::abs(verified_enabled-wanted_enabled)<=epsilon &&
                std::abs(verified_depth-wanted_depth)<=epsilon;
            m_duo_mpc_enabled.store(verified_enabled);m_duo_mpc_depth.store(verified_depth);
            m_duo_mpc_verified.store(requested && verified);
            if (!verified) {''')
 replace(ui,'"[DuoView][Foreground] MPC_FOV reconciliation failed; preserving baseline"',
 '"[DuoView][Foreground] MPC_FOV readback verification failed; foreground projection remains unverified"')
 replace(ui,'"other valid controls continue; active quality width={:.3f} height={:.3f} periphery={:.3f} density={:.3f}",\n            checked.rejected,candidate.crop_width,candidate.crop_height,\n            candidate.peripheral_scale,candidate.foveal_density);',
 '''"requested periphery={:.6f}, density={:.6f}; active width={:.3f} height={:.3f} periphery={:.6f} density={:.3f}",
            checked.rejected,m_duo_periphery->value(),m_duo_density->value(),candidate.crop_width,candidate.crop_height,
            candidate.peripheral_scale,candidate.foveal_density);''')
 replace(ui,'                m_duo_periphery->draw("Peripheral resolution scale");',
 '''                m_duo_periphery->draw("Peripheral resolution scale");
                 if(ImGui::IsItemActive() || ImGui::IsItemDeactivatedAfterEdit())
                     m_duo_periphery_edit_ms.store(GetTickCount64());
                 ImGui::TextWrapped("Peripheral resizing applies after editing settles; selected DLSS features are preserved where possible.");''')
 replace(ui,'    const auto current = m_duoview.settings();',
 '''    const auto current = m_duoview.settings();
     const auto peripheral_edit=m_duo_periphery_edit_ms.load();
     const bool peripheral_editing=peripheral_edit && GetTickCount64()-peripheral_edit<250;''')
 replace(ui,'.peripheral_scale=(std::min)(m_duo_periphery->value(),.499f),',
 '.peripheral_scale=peripheral_editing?current.peripheral_scale:(std::min)(m_duo_periphery->value(),.499f),')
 replace(cpp,'                            if(m_stock_dibr_scope && (preview_mode || stereo_mode)) {',
 '''                            bool sequence_needs_depth=false;
                             {std::lock_guard lock(m_duo_sequence_mutex);
                              sequence_needs_depth=m_duo_sequence&&m_duo_sequence->wants_guides();}
                             if(m_stock_dibr_scope && (preview_mode || stereo_mode || sequence_needs_depth)) {''')
 replace(cpp,',.5f,.5f,320,true,false,192);',',.5f,.5f,320,bool(depths.left),false,192);')
 replace(cpp,',gaze_u,gaze_v,192,true,false,128);',',gaze_u,gaze_v,192,bool(depths.right),false,128);')
 # During stereo recovery, mixing physical LEFT fovea and RIGHT periphery
 # into a nominal mono image still produces mismatched near silhouettes.
 replace(cpp,'                                    recorded = compositor.record_native(device, commands.cmd_list.Get(),',
 '''                                    auto composition_frame=*packet_frame;
                                     if(stereo_mode && !effective_stereo_mode)
                                         composition_frame.config.settings.diagnostic_view=1; // current RIGHT full field
                                     recorded = compositor.record_native(device, commands.cmd_list.Get(),''')
 replace(cpp,'D3D12_RESOURCE_STATE_RENDER_TARGET, *packet_frame,',
 'D3D12_RESOURCE_STATE_RENDER_TARGET, composition_frame,')
 replace(cpp,'                                        recorded=compositor.record_native(device,commands.cmd_list.Get(),',
 '''                                        composition_frame.config.settings.diagnostic_view=1;
                                         recorded=compositor.record_native(device,commands.cmd_list.Get(),''')
 replace(cpp,'                                            *packet_frame,std::static_pointer_cast<const void>(packet),0);',
 '                                            composition_frame,std::static_pointer_cast<const void>(packet),0);')
 replace(ui,'Pins follow the DLSS feature+output-size signature; no automatic switching. Re-pin after a DLSS restart.',
 'Pins preserve the selected feature across resolution changes; a released/replaced DLSS feature needs a re-pin. Stereo resumes after 8 fresh compatible pairs.')
 replace(ui,'Stability-first mode 5: research target-depth geometry, mutually exclusive per-eye ownership, near-field mono protection and hard geometry-aware crop seam. It intentionally sacrifices some local stereo/disocclusion detail. OFF = original CI71/CI72 unchanged.',
 'CI73 selects conservative target-depth geometry. CI76 uses exclusive current-frame composition and near-field protection for every surface strategy; no coarse RIGHT-edge sharpness veto. This is not temporal history stabilization.')
 replace(ui,'                if(m_duo_conservative_stereo->value()) {\n                }\n','')
 replace(ui,'                ImGui::TextUnformatted("Fovea fixed: 0.50 x 0.50 of each eye FOV");',
 '''                ImGui::TextUnformatted("Fovea fixed: 0.50 x 0.50 of each eye FOV");
                ImGui::TextWrapped("CI76: one image owner per stereo pixel; fresh-pair recovery after resize/dropout. Foreground MPC readback: %s",duoview_foreground_mpc_verified()?"verified":"unverified");''')
 replace(cpp,'                                    <<",\\\"world_to_meters\\\":"',
 '''                                    <<",\\\"composition\\\":"<<cap::quote(!recorded?"NO_VALID_OUTPUT":stereo_recorded&&effective_stereo_mode>=4u?"CI76_EXCLUSIVE_CURRENT_FRAME":stereo_mode&&!stereo_recorded?"CI76_CURRENT_RIGHT_MONO":"BASELINE_MONO_OR_LEGACY")
                                    <<",\\\"foreground_mpc_verified\\\":"<<(vr->duoview_foreground_mpc_verified()?"true":"false")
                                    <<",\\\"foreground_mpc_values\\\":["<<cap::number(vr->duoview_foreground_mpc_values()[0])
                                    <<","<<cap::number(vr->duoview_foreground_mpc_values()[1])<<"]"
                                    <<",\\\"world_to_meters\\\":"''')
 print('CI76 integrated: exclusive surface ownership, same-feature resize pins, 8-pair recovery, actual MPC readback')

if __name__=='__main__':
 if len(sys.argv)!=2:raise SystemExit('usage: ci76/apply.py BACKEND')
 apply(Path(sys.argv[1]).resolve())

#!/usr/bin/env python3
"""V1: attach R5 depth candidate diagnostics to DuoView ID6 without synthesizing unsafe stereo.
DuoView normal OFF path and stock DIBR modes 3/4 are independent.
"""
import pathlib,sys
root=pathlib.Path(sys.argv[1])
def edit(rel,old,new):
 p=root/rel;s=p.read_text(encoding="utf-8-sig")
 if s.count(old)!=1:raise RuntimeError(f"R5 bridge v1 refused ambiguous anchor {rel}: {s.count(old)} hits: {old[:100]}")
 p.write_text(s.replace(old,new,1),encoding="utf-8",newline="")
dc="src/mods/vr/D3D12Component.cpp"
edit(dc,
 "m_stock_dibr_scope = is_stalker2_current_game() && vr->is_dibr_depth_trace_requested() &&",
 "m_stock_dibr_scope = is_stalker2_current_game() &&\n            (vr->is_dibr_depth_trace_requested() || vr->is_duoview_renderer_active()) &&")
# Pre-arm using the matched source extent for subsequent producer frames.
# Never read or bind this depth to a synthesized eye until RGB/DSV provenance is proven.
edit(dc,
 '''                        } else {
                            bool recorded = false;
                            bool callback_attempted = false;
                            bool compositor_fault = false;''',
 '''                        } else {
                            if (m_stock_dibr_scope) {
                                const auto duo_depth_extent = m_game_tex.texture->GetDesc();
                                m_stock_dibr_depth->configure(device,
                                    g_framework->get_d3d12_hook()->get_command_queue(),
                                    duo_depth_extent.Width, duo_depth_extent.Height, true);
                            }
                            bool recorded = false;
                            bool callback_attempted = false;
                            bool compositor_fault = false;''')
edit(dc,
 '''                            if (compositor_fault) {
                                vr->duoview_abort("Validated Native Stereo Fix pair failed DuoView composition");''',
 '''                            if (m_stock_dibr_scope) {
                                if (submitted && recorded && callback_attempted)
                                    m_stock_dibr_depth->finish_frame();
                                SPDLOG_INFO_EVERY_N_SEC(2, "[DuoView][R5DepthBridge] mode=diagnostics-only {}", m_stock_dibr_depth->summary());
                            }
                            if (compositor_fault) {
                                vr->duoview_abort("Validated Native Stereo Fix pair failed DuoView composition");''')
vc="src/mods/VR.cpp"
edit(vc,
 '''                ImGui::TextWrapped("Settings are frozen once per new UE frame. The original Joey Mono ID5 is untouched.");''',
 '''                ImGui::TextWrapped("Settings are frozen once per new UE frame. The original Joey Mono ID5 is untouched.");
                ImGui::Separator();
                ImGui::TextUnformatted("R5 DIBR depth bridge V1 (diagnostic only)");
                ImGui::TextWrapped("Enable DSV/RDG capture below, then re-enter DuoView ID6. R5 producer depth counters appear in the log as [DuoView][R5DepthBridge]. Mono output stays unchanged: DO NOT interpret valid depth candidates as stereo.");
                m_dibr_ue5_rdg_depth_capture->draw("R5 DSV/RDG capture in DuoView (experimental, opt-in)");''')
print("R5 live depth capture installed alongside DuoView ID6; stereoscopic synthesis intentionally disabled until per-frame depth lineage validation.")

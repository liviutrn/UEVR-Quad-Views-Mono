"""CI70: fail-closed independent DLSS depth diagnostic preview.
Apply after CI69. All replacements require a single exact anchor.
No legacy DSV candidate selection is re-enabled.
"""
from pathlib import Path
import sys

def replace(path, old, new):
    s=path.read_text(encoding="utf-8")
    n=s.count(old)
    if n!=1:raise RuntimeError(f"CI70 exact source anchor failed: {path.name} occurrences={n}: {old[:65]}")
    path.write_text(s.replace(old,new,1),encoding="utf-8")
def apply(root):
    v=Path(root)/"src/mods/vr"
    f=v/"d3d12/StockDibrDepth.hpp"
    replace(f,"uint64_t color_packet=0,uint64_t color_generation=0) {\n        std::scoped_lock lock{mutex};",
              "uint64_t color_packet=0,uint64_t color_generation=0,\n                               unsigned debug_preview_mode=0u) {\n        std::scoped_lock lock{mutex};")
    replace(f,"            if(l!=Capacity && rr!=Capacity && l!=rr &&",
"""            // CI70 independent debug preview: no nearby-evaluation stereo
            // assumptions. A single valid manually pinned NGX depth is enough.
            if(debug_preview_mode>=1u && debug_preview_mode<=3u) {
                const auto accepted=[&](size_t i,unsigned role) -> bool {
                    if(i==Capacity)return false;
                    auto& slot=slots[i];
                    if(slot.ngx_role!=role || slot.ngx_guide.output_width!=
                        (role==1?left_width:right_width) || slot.ngx_guide.output_height!=
                        (role==1?left_height:right_height))return false;
                    if(slot.foreign_fence && (!queue || FAILED(queue->Wait(slot.foreign_fence.Get(),1))))return false;
                    slot.leased=true;snapshot_leases[i]=true;
                    return true;
                };
                const bool left_ok=debug_preview_mode!=2u && accepted(l,1u);
                const bool right_ok=debug_preview_mode!=1u && accepted(rr,2u);
                if(left_ok) {
                    auto& s=slots[l];r.left=s.texture;r.left_serial=s.serial;r.left_epoch=s.epoch;
                    r.left_pass=1u;r.left_viewport=s.viewport;r.ngx_guides[0]=s.ngx_guide;
                }
                if(right_ok) {
                    auto& s=slots[rr];r.right=s.texture;r.right_serial=s.serial;r.right_epoch=s.epoch;
                    r.right_pass=2u;r.right_viewport=s.viewport;r.ngx_guides[1]=s.ngx_guide;
                }
                const bool success=(debug_preview_mode==1u?left_ok:
                                   debug_preview_mode==2u?right_ok:(left_ok&&right_ok));
                r.decision=success?"NGX_INDEPENDENT_DEPTH_PREVIEW_NO_STEREO_PROVENANCE":"NGX_PREVIEW_SOURCE_MISSING";
                r.label=r.decision+" L="+std::to_string(r.left_serial)+" R="+std::to_string(r.right_serial);
                selection_trace=r.label;r.count=ids.size();return r;
            }
            if(l!=Capacity && rr!=Capacity && l!=rr &&""")
    f=v/"D3D12Component.hpp"
    replace(f,"    uint32_t duoview_preview_mode() const {return m_duo_preview_mode.load();}",
"""    uint32_t duoview_preview_mode() const {return m_duo_preview_mode.load();}
    void duoview_allow_unverified_stereo(bool enabled) {
        m_duo_unverified_stereo_opt_in.store(enabled,std::memory_order_release);
    }
    bool duoview_unverified_stereo_opt_in() const {
        return m_duo_unverified_stereo_opt_in.load(std::memory_order_acquire);
    }""")
    replace(f,"    std::atomic<uint32_t> m_duo_preview_mode{0};",
"""    std::atomic<uint32_t> m_duo_preview_mode{0};
    std::atomic<bool> m_duo_unverified_stereo_opt_in{false};""")
    f=v/"D3D12Component.cpp"
    replace(f,"packet_frame->config.layout.periphery.height,stereo_mode<4u,packet->serial,packet_frame->config.key.generation);",
"""packet_frame->config.layout.periphery.height,stereo_mode<4u,packet->serial,
                                    packet_frame->config.key.generation,
                                    stereo_mode==0u?preview_mode:0u);""")
    replace(f,"if((preview_mode||stereo_mode) && (!depths.left||!depths.right)) {",
"""const bool missing_for_preview=preview_mode==1u?!depths.left:
                                preview_mode==2u?!depths.right:
                                preview_mode==3u?(!depths.left||!depths.right):false;
                            if(missing_for_preview || (stereo_mode && (!depths.left||!depths.right))) {""")
    replace(f,"const uint32_t effective_stereo_mode=depths.left && depths.right &&\n                                packet_frame->split_eye && packet_frame->config.settings.fovea_view==0\n                                    ? stereo_mode : 0u;",
"""const bool unsafe_manual_stereo=m_duo_unverified_stereo_opt_in.load(std::memory_order_acquire);
                            const uint32_t effective_stereo_mode=unsafe_manual_stereo &&
                                depths.left && depths.right && packet_frame->split_eye &&
                                packet_frame->config.settings.fovea_view==0 ? stereo_mode : 0u;
                            if(stereo_mode && !unsafe_manual_stereo)
                                SPDLOG_WARNING_EVERY_N_SEC(3,
                                    "[DuoView][Safety] Synthetic stereo blocked: NGX camera/frame identity unverified. Opt in explicitly only for experimental testing.");""")
    f=v/"DuoViewD3D12.hpp"
    replace(f,"""        const bool depth_compatible=leftDepth!=rightDepth &&
            depth_resource_valid(leftDepth) && depth_resource_valid(rightDepth);
        // An active stereo request must never be silently replaced by the
        // depth-preview PSO while reporting last_true_stereo=true.
        const bool depthPreview=!requested_stereo && previewMode>=1u && previewMode<=3u &&
            depth_compatible && depth_pipeline_;
        const bool stereoReady=requested_stereo && depth_compatible && stereo_pipeline_;""",
"""        const bool left_depth_valid=depth_resource_valid(leftDepth);
        const bool right_depth_valid=depth_resource_valid(rightDepth);
        const bool depth_compatible=leftDepth!=rightDepth && left_depth_valid && right_depth_valid;
        // CI70: only the selected depth is required in modes 1/2.
        // Bind it to both SRV slots: shader samples only that chosen resource.
        const bool depthPreview=!requested_stereo && depth_pipeline_ &&
            (previewMode==1u?left_depth_valid:
             previewMode==2u?right_depth_valid:
             previewMode==3u?(left_depth_valid&&right_depth_valid):false);
        const bool stereoReady=requested_stereo && depth_compatible && stereo_pipeline_;
        auto* preview_left=(depthPreview && !left_depth_valid)?rightDepth:leftDepth;
        auto* preview_right=(depthPreview && !right_depth_valid)?leftDepth:rightDepth;
        const DepthViewport preview_left_viewport=(depthPreview && !left_depth_valid)?rightViewport:leftViewport;
        const DepthViewport preview_right_viewport=(depthPreview && !right_depth_valid)?leftViewport:rightViewport;""")
    replace(f,'return reject("Stereo source pair missing/invalid: choose another foveal or peripheral DSV");',
              'return reject("NGX stereo depth pair missing/invalid; no unverified source substitution");')
    replace(f,"""(!depth_viewport_valid(leftViewport,leftDepth->GetDesc().Width,leftDepth->GetDesc().Height) ||
            !depth_viewport_valid(rightViewport,rightDepth->GetDesc().Width,rightDepth->GetDesc().Height)))""",
"""(!depth_viewport_valid(preview_left_viewport,preview_left->GetDesc().Width,preview_left->GetDesc().Height) ||
            !depth_viewport_valid(preview_right_viewport,preview_right->GetDesc().Width,preview_right->GetDesc().Height)))""")
    replace(f,"const DepthViewport views[]{leftViewport,rightViewport};",
              "const DepthViewport views[]{preview_left_viewport,preview_right_viewport};")
    replace(f,"if(depthPreview || stereoReady) ensure_depth_srvs(device,leftDepth,rightDepth);",
              "if(depthPreview || stereoReady) ensure_depth_srvs(device,preview_left,preview_right);")
    f=v/"DuoViewNgxGuide.hpp"
    replace(f,"    std::vector<ManualCandidate> browse() const {",
"""    uint64_t age_ms(const ManualCandidate& candidate) const {
        const auto t=now();return t>=candidate.last_seen_ms?t-candidate.last_seen_ms:0;
    }
    std::vector<ManualCandidate> browse() const {""")
    f=Path(root)/"src/mods/VR.cpp"
    replace(f,"""                        if(ImGui::Button("Use as LEFT (fovea)"))
                            uevr::duoview::ngx::manual_registry().pin(0,candidate.feature,candidate.output_width,candidate.output_height);
                        ImGui::SameLine();
                        if(ImGui::Button("Use as RIGHT (periphery)"))
                            uevr::duoview::ngx::manual_registry().pin(1,candidate.feature,candidate.output_width,candidate.output_height);""",
"""                        const auto age=uevr::duoview::ngx::manual_registry().age_ms(candidate);
                        const bool fresh=age<=3000u;
                        ImGui::Text("Age %llu ms | %s | feature class %u %s",
                            static_cast<unsigned long long>(age),fresh?"LIVE":"STALE - cannot pin",
                            candidate.kind,candidate.create_observed?"create verified":"kind uncertain");
                        if(!fresh)ImGui::BeginDisabled();
                        if(ImGui::Button("Use as LEFT (fovea)")) {
                            if(!uevr::duoview::ngx::manual_registry().pin(0,candidate.feature,candidate.output_width,candidate.output_height))
                                SPDLOG_WARN("[DuoView][ManualNGX] LEFT pin rejected; stale or duplicate source");
                        }
                        ImGui::SameLine();
                        if(ImGui::Button("Use as RIGHT (periphery)")) {
                            if(!uevr::duoview::ngx::manual_registry().pin(1,candidate.feature,candidate.output_width,candidate.output_height))
                                SPDLOG_WARN("[DuoView][ManualNGX] RIGHT pin rejected; stale or duplicate source");
                        }
                        if(!fresh)ImGui::EndDisabled();""")
    replace(f,"""                    if(ImGui::Combo("Display pinned DLSS depth",&preview_mode,preview_labels,4))
                        m_d3d12.duoview_select_candidates(0,0,uint32_t(preview_mode));""",
"""                    if(ImGui::Combo("Display pinned DLSS depth",&preview_mode,preview_labels,4)) {
                        if(preview_mode!=0)m_d3d12.duoview_stereo_config(0,false);
                        m_d3d12.duoview_select_candidates(0,0,uint32_t(preview_mode));
                    }
                    bool unsafe_stereo=m_d3d12.duoview_unverified_stereo_opt_in();
                    if(ImGui::Checkbox("Allow UNVERIFIED manual stereo (experimental only)",&unsafe_stereo))
                        m_d3d12.duoview_allow_unverified_stereo(unsafe_stereo);
                    ImGui::TextWrapped("OFF by default. Nearby DLSS evaluations do NOT prove a shared Unreal frame or physical eye. Avoid extended headset use in experimental mode.");""")
    print("CI70 NGX single-depth preview, stereo safety gate and fresh-pin UI applied",flush=True)
if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: apply.py BACKEND_ROOT")
    apply(Path(sys.argv[1]).resolve())

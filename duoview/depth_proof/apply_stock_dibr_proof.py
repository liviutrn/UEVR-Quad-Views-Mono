#!/usr/bin/env python3
"""Build118-only frozen-depth test using Joey's stock DIBRPreview.

This is a deliberate FIRST PIPELINE PROOF, not real-time stereo:
- Uses only finished GPU snapshots from the exact Build118 depth observer.
- Uses stock DIBRPreview::synthesize(), not custom DIBR shaders.
- Applies after the original Build49+Build118 patch.
- Changes only experimental DuoView ID6; default off, Mono fallback.
- The original captured Z does not follow subsequent head/game movement.
"""
from pathlib import Path
import argparse

def edit(root, relative, old, new):
    f = root/relative
    s = f.read_text(encoding="utf-8-sig")
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f"STOCK DIBR BRIDGE: expected exactly one anchor in {relative}, got {n}: {old[:80]}")
    f.write_text(s.replace(old,new,1),encoding="utf-8",newline="\n")

def apply(root):
    # Make variable-resolution R32 proof depth opt-in. Stock DIBR otherwise
    # rejects valid Build118 344x276 and 860x684 buffers against the eye image.
    # Its HLSL already samples depth using normalized UVs; the proof tests
    # geometry alignment separately. The stock strict check remains default.
    header = "src/mods/vr/d3d12/DIBRPreview.hpp"
    cpp = "src/mods/vr/d3d12/DIBRPreview.cpp"
    edit(root,header,
        "        bool reversed_depth{true};",
        "        bool reversed_depth{true};\n        bool allow_depth_resolution_mismatch_for_proof{false};")
    edit(root,header,
        "bool validate_inputs(ID3D12Resource* color, ID3D12Resource* depth, std::string& reason) const;",
        "bool validate_inputs(ID3D12Resource* color, ID3D12Resource* depth, std::string& reason, bool allow_proof_scaling) const;")
    edit(root,cpp,
        "bool DIBRPreview::validate_inputs(ID3D12Resource* color, ID3D12Resource* depth, std::string& reason) const {",
        "bool DIBRPreview::validate_inputs(ID3D12Resource* color, ID3D12Resource* depth, std::string& reason, bool allow_proof_scaling) const {")
    edit(root,cpp,
        "    if (depth_desc.Height != color_desc.Height ||\n        (depth_desc.Width != color_desc.Width && depth_desc.Width != color_desc.Width / 2)) {",
        "    if (!allow_proof_scaling && (depth_desc.Height != color_desc.Height ||\n        (depth_desc.Width != color_desc.Width && depth_desc.Width != color_desc.Width / 2))) {")
    edit(root,cpp,
        "!validate_inputs(color, depth, validation_reason)",
        "!validate_inputs(color, depth, validation_reason, parameters.allow_depth_resolution_mismatch_for_proof)")

    # Expose a tiny explicit selection that doesn't share the troubled Build123
    # UI. No depth capture or stereo can start merely by opening the menu.
    header = "src/mods/vr/D3D12Component.hpp"
    edit(root,header,
        "    std::atomic<bool> m_depth_proof_request{false};",
        "    std::atomic<bool> m_depth_proof_request{false};\n"
        "    std::atomic<int> m_stock_dibr_proof_candidate{-1};")
    edit(root,header,
        "    std::string depth_proof_status() const { return m_depth_proof->session.status(); }",
        "    std::string depth_proof_status() const { return m_depth_proof->session.status(); }\n"
        "    void set_stock_dibr_proof_candidate(int id) { m_stock_dibr_proof_candidate.store(id, std::memory_order_release); }\n"
        "    int stock_dibr_proof_candidate() const { return m_stock_dibr_proof_candidate.load(std::memory_order_acquire); }\n"
        "    bool stock_dibr_proof_depth_ready(int id) const { return id>=0 && !!m_depth_proof->session.completed_gpu_snapshot((size_t)id); }")
    edit(root,header,
        "        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;",
        "        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;\n"
        "        // Joey stock DIBRPreview is owned per retired XR command slot.\n"
        "        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<d3d12::DIBRPreview>> stock_dibr_proof_slots;")

    vr = "src/mods/VR.cpp"
    edit(root,vr,
        '                    ImGui::TextWrapped("Saves anonymous candidate PGM images, raw float32 Z and a rejection manifest beside the UEVR logs in depth_proof. Output remains Mono. No stereo/view pairing claim.");',
        '''                    ImGui::TextWrapped("Saves anonymous candidate PGM images, raw float32 Z and a rejection manifest beside the UEVR logs in depth_proof. Output remains Mono until a finished captured depth is explicitly selected below.");
                    ImGui::Separator();
                    ImGui::TextWrapped("STOCK DIBR TEST: FROZEN single-frame depth. Stand still and do not judge VR comfort. Legacy displacement only; this proves depth -> stock shader -> XR eyes, NOT live RGB-D.");
                    for (const int id : {1,4,5,6,9}) {
                        ImGui::PushID(id);
                        const bool ready=d3d12().stock_dibr_proof_depth_ready(id);
                        ImGui::Text("Candidate %d: %s",id,ready?"GPU ready":"not captured");
                        ImGui::SameLine();
                        if (ImGui::SmallButton("Test Joey DIBR") && ready)
                            d3d12().set_stock_dibr_proof_candidate(id);
                        ImGui::PopID();
                    }
                    if (ImGui::Button("STOP stock DIBR test / MONO"))
                        d3d12().set_stock_dibr_proof_candidate(-1);
                    const int chosen=d3d12().stock_dibr_proof_candidate();
                    ImGui::Text("Selected frozen depth: %d (%s)",chosen,
                        d3d12().stock_dibr_proof_depth_ready(chosen)?"ready":"OFF/NOT READY");''')

    cpp = "src/mods/vr/D3D12Component.cpp"
    # The accepted DuoView copy already renders same Mono color to both XR
    # halves. Invoke stock Joey DIBR only after this successfully records.
    # DIBRPreview stages that left half and returns a doublewide output.
    edit(root,cpp,
        '''                                    if (compositor.recorded_commands()) commands.has_commands = true;''',
        '''                                    if (compositor.recorded_commands()) commands.has_commands = true;
                                    // Build118 frozen-depth proof: stock Joey DIBR
                                    // shader over the just-composited DuoView
                                    // double-wide color. Disabled by default.
                                    const int proof_id=m_stock_dibr_proof_candidate.load(std::memory_order_acquire);
                                    if (recorded && proof_id>=0 && proof_id<24) {
                                        auto proof_z=m_depth_proof->session.completed_gpu_snapshot(
                                            static_cast<size_t>(proof_id));
                                        if (proof_z && destination) {
                                            auto& slot=m_openxr.stock_dibr_proof_slots[&commands];
                                            if (!slot) slot=std::make_unique<d3d12::DIBRPreview>();
                                            d3d12::DIBRPreview::Parameters params{};
                                            params.reversed_depth=true;
                                            params.disparity_pixels=18.0f;
                                            params.use_true_reprojection=false; // frozen diagnostic only
                                            params.allow_depth_resolution_mismatch_for_proof=true;
                                            const bool synthesized=slot->synthesize(
                                                device,commands.cmd_list.Get(),destination,
                                                D3D12_RESOURCE_STATE_RENDER_TARGET,proof_z.Get(),
                                                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                                                nullptr,params);
                                            if (synthesized && slot->output().texture) {
                                                auto* stereo=slot->output().texture.Get();
                                                const auto target_desc=destination->GetDesc();
                                                const auto stereo_desc=stereo->GetDesc();
                                                const bool compatible =
                                                    target_desc.Width==stereo_desc.Width &&
                                                    target_desc.Height==stereo_desc.Height &&
                                                    (target_desc.Format==stereo_desc.Format ||
                                                     (target_desc.Format==DXGI_FORMAT_B8G8R8A8_TYPELESS &&
                                                      stereo_desc.Format==DXGI_FORMAT_B8G8R8A8_UNORM));
                                                if (compatible) {
                                                    D3D12_RESOURCE_BARRIER b[2]{};
                                                    for (auto& item:b) {
                                                        item.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
                                                        item.Transition.Subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
                                                    }
                                                    b[0].Transition={destination,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                                                        D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_DEST};
                                                    b[1].Transition={stereo,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                                                        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE};
                                                    commands.cmd_list->ResourceBarrier(2,b);
                                                    commands.cmd_list->CopyResource(destination,stereo);
                                                    for (auto& item:b)
                                                        std::swap(item.Transition.StateBefore,item.Transition.StateAfter);
                                                    commands.cmd_list->ResourceBarrier(2,b);
                                                    commands.has_commands=true;
                                                    SPDLOG_INFO_EVERY_N_SEC(2,
                                                        "[DepthProof118][StockDIBR] RECORDED candidate={} frozen depth={}x{} stereo={}x{}",
                                                        proof_id,proof_z->GetDesc().Width,proof_z->GetDesc().Height,
                                                        stereo_desc.Width,stereo_desc.Height);
                                                } else {
                                                    SPDLOG_WARN_EVERY_N_SEC(2,
                                                        "[DepthProof118][StockDIBR] REJECT output format/extent mismatch");
                                                }
                                            } else {
                                                SPDLOG_WARN_EVERY_N_SEC(2,
                                                    "[DepthProof118][StockDIBR] REJECT synthesize: {}",
                                                    slot->failure_reason());
                                            }
                                        } else {
                                            SPDLOG_INFO_EVERY_N_SEC(2,
                                                "[DepthProof118][StockDIBR] MONO fallback candidate={} depth not GPU-complete",
                                                proof_id);
                                        }
                                    }''')
    # Slot resets happen after retirement with the existing DuoView gating.
    edit(root,cpp,
        '''    vr->get_openxr_runtime()->invalidate_duoview_scene();
    this->duoview_compositors.clear();''',
        '''    vr->get_openxr_runtime()->invalidate_duoview_scene();
    this->stock_dibr_proof_slots.clear();
    this->duoview_compositors.clear();''')
    edit(root,cpp,
        '''    this->duoview_compositors.clear();
    this->contexts.clear();''',
        '''    this->stock_dibr_proof_slots.clear();
    this->duoview_compositors.clear();
    this->contexts.clear();''')
    print("Build118 frozen GPU depth -> Joey stock DIBRPreview after stable DuoView copy: patched")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("backend",type=Path)
    apply(p.parse_args().backend)

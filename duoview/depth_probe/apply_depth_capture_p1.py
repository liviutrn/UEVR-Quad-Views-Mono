#!/usr/bin/env python3
"""P1 GPU depth snapshots integrated into Build49 DuoView without new UE views."""
import argparse
from pathlib import Path

def edit(root,path,old,new):
    fp=root/path
    text=fp.read_text(encoding="utf-8-sig")
    if text.count(old)!=1:
        raise RuntimeError(f"P1 source drift {path}: {text.count(old)} matches for {old[:70]}")
    fp.write_text(text.replace(old,new,1),encoding="utf-8",newline="\n")

def main(backend):
    edit(backend,"src/mods/vr/D3D12Component.hpp",
        '#include "d3d12/DIBRPreview.hpp"',
        '#include "d3d12/DIBRPreview.hpp"\n#include "DuoDepthPairP1.hpp"')
    edit(backend,"src/mods/vr/D3D12Component.hpp",
        '    void arm_duoview_depth_discovery() {',
        '''    bool arm_duoview_p1(VR* vr);
    unsigned duoview_p1_captured() const { return m_duoview_p1.captured(); }
    bool duoview_p1_gpu_ready() const { return m_duoview_p1.gpu_ready(); }
    std::string duoview_p1_status() const { return m_duoview_p1.status(); }
    void arm_duoview_depth_discovery() {''')
    edit(backend,"src/mods/vr/D3D12Component.hpp",
        '    d3d12::DIBRPreview m_dibr_depth_capture{};',
        '''    d3d12::DIBRPreview m_dibr_depth_capture{};
    uevr::duoview::dx12::DepthPairP1 m_duoview_p1{};''')
    edit(backend,"src/mods/VR.cpp",
        '                        if (ImGui::Button("Log next 200 DuoView source frames")) {',
        '''                        if (ImGui::Button("Capture TWO owned P1 depth snapshots (one shot)")) {
                            if (!d3d12().arm_duoview_p1(this))
                                SPDLOG_WARN("[DuoDepthP1] Arm failed: {}",d3d12().duoview_p1_status());
                        }
                        ImGui::Text("P1 depth GPU copies: %u / 2, GPU queue complete: %s",
                            d3d12().duoview_p1_captured(),d3d12().duoview_p1_gpu_ready()?"yes":"no");
                        const auto p1_status=d3d12().duoview_p1_status();
                        ImGui::TextWrapped("P1: %s",p1_status.c_str());
                        ImGui::TextWrapped("These are raw SceneDepthZ snapshots, NOT yet verified as paired view0/view1, linear metres or color-frame matched.");
                        if (ImGui::Button("Log next 200 DuoView source frames")) {''')
    edit(backend,"src/mods/vr/D3D12Component.cpp",
        "void D3D12Component::reset_dibr_preview() {",
        '''bool D3D12Component::arm_duoview_p1(VR* vr) {
    if (!vr || !vr->is_duoview_depth_discovery_enabled()) return false;
    const auto hook=g_framework->get_d3d12_hook();
    if (!hook || !hook->get_device()) return false;
    auto scene=vr->get_render_target_pool_hook()->get_texture<ID3D12Resource>(L"SceneDepthZ");
    const bool armed=m_duoview_p1.arm(hook->get_device(),scene.Get());
    SPDLOG_INFO("[DuoDepthP1] arm={} scene_depth=0x{:X} state={}",
        armed,reinterpret_cast<uintptr_t>(scene.Get()),m_duoview_p1.status());
    return armed;
}
void D3D12Component::reset_dibr_preview() {''')
    edit(backend,"src/mods/vr/D3D12Component.cpp",
        '''        hook->set_depth_stencil_observer(
            (duo_depth_discovery ||''',
        '''        hook->set_depth_stencil_observer(
            (duo_depth_discovery && m_duoview_p1.armed()) ? &m_duoview_p1 :
            (duo_depth_discovery ||''')
    edit(backend,"src/mods/vr/D3D12Component.cpp",
        '''                                runtimes::OpenXR::PipelineState pose{};''',
        '''                                // Only AFTER the validated color transaction reached
                                // the owning submit path, enqueue a nonblocking GPU
                                // fence marker for one-shot P1 depth copies.
                                if (m_duoview_p1.captured()==2 && !m_duoview_p1.gpu_ready()) {
                                    if (auto queue=g_framework->get_d3d12_hook()->get_command_queue())
                                        m_duoview_p1.signal_after_source_submit(queue);
                                }
                                runtimes::OpenXR::PipelineState pose{};''')
    (backend/"src/mods/vr/DuoDepthPairP1.hpp").write_text(
        (Path(__file__).with_name("DuoDepthPairP1.hpp")).read_text(encoding="utf-8"),
        encoding="utf-8",newline="\n")
    print("P1 GPU depth copies integrated, UI armed explicitly, verified Mono compositor untouched")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("backend",type=Path);main(p.parse_args().backend)

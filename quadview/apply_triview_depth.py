#!/usr/bin/env python3
"""Tri-view B7: periphery depth reprojection from the DLSS depth input.

Run AFTER apply_triview_compact.py. Portable parts live in quadview/:
  QuadViewNgxSelect.hpp  matches_periphery() (which DLSS output is the periphery)
  QuadViewNgxDepth.hpp   NGX Evaluate/Create/Release + ExecuteCommandLists hooks,
                         per-frame depth copy on the game's command list
  QuadViewGeometry.hpp   Layout::depth_shift, periphery_depth_shift()
  QuadViewD3D12.hpp      t4 depth SRV, 512-byte constants, DepthInput
  QuadViewComposite.hlsl symmetric half-IPD backward warp + "show depth" view
This script copies the two NGX headers into the backend and wires them:
- the depth shift is computed before the layout freeze (frozen with the draw);
- each draw publishes the expected periphery size (0 when a fovea has the same
  size, so a fovea depth can never be taken for the periphery);
- hooks are installed lazily from D3D12Component::on_frame while ID7 depth is on;
- the compositor gets the newest submitted periphery depth (<= 250 ms old) or
  nothing (then the periphery is exactly B6).
Menu: "Periphery depth reprojection" (default ON), strength slider (default 1,
negative flips the direction), "Show periphery depth" debug view, counters.
"""
from pathlib import Path
import shutil
import sys

if len(sys.argv) != 3:
    raise SystemExit("Usage: apply_triview_depth.py <backend> <quadview-dir>")
root, overlay = Path(sys.argv[1]), Path(sys.argv[2])
for name in ("QuadViewNgxSelect.hpp", "QuadViewNgxDepth.hpp"):
    shutil.copy2(overlay / name, root / "src/mods/vr" / name)


def edit(rel, pairs):
    path = root / rel
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{rel}: expected exactly one anchor, found {count}:\n{old[:240]}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


edit("src/mods/VR.hpp", [
    ('    const ModToggle::Ptr m_quadview_compact_targets{ModToggle::create(generate_name("QuadViewCompactSources"), true)};\n',
     '    const ModToggle::Ptr m_quadview_compact_targets{ModToggle::create(generate_name("QuadViewCompactSources"), true)};\n'
     '    const ModToggle::Ptr m_quadview_depth_reproject{ModToggle::create(generate_name("QuadViewPeripheryDepth"), true)};\n'
     '    const ModSlider::Ptr m_quadview_depth_strength{ModSlider::create(generate_name("QuadViewPeripheryDepthStrength"), -2.f, 2.f, 1.f)};\n'
     '    const ModToggle::Ptr m_quadview_depth_show{ModToggle::create(generate_name("QuadViewShowPeripheryDepth"), false)};\n'),
    ("            *m_quadview_compact_targets,\n",
     "            *m_quadview_compact_targets, *m_quadview_depth_reproject, *m_quadview_depth_strength,\n"),
    ("    std::atomic<uint64_t> m_triview_vram_used{0}, m_triview_vram_budget{0}, m_triview_vram_system{0};\n",
     "    std::atomic<uint64_t> m_triview_vram_used{0}, m_triview_vram_budget{0}, m_triview_vram_system{0};\n"
     "    // Tri-view B7 periphery depth (read by D3D12Component on the present thread).\n"
     "    bool quadview_depth_reproject() const { return m_quadview_depth_reproject->value(); }\n"
     "    bool quadview_depth_show() const { return m_quadview_depth_show->value(); }\n"),
])

edit("src/mods/VR.cpp", [
    ('#include "VR.hpp"\n', '#include "VR.hpp"\n#include "vr/QuadViewNgxDepth.hpp"\n'),
    ("            // Tri-view B6: use compact per-role targets for this draw only when a\n",
     "            // Tri-view B7: periphery depth reprojection shift, frozen with the draw.\n"
     "            // near = UE near plane (projection m[3][2], cm); IPD from the runtime eye offsets\n"
     "            // (metres) x 100 (UE world-to-meters) x UEVR World Scale.\n"
     "            candidate->depth_shift=uevr::quadview::periphery_depth_shift(*candidate,\n"
     "                draw_config.base_projection_valid ? double(draw_config.projections[0][14]) : 0.0,\n"
     "                0.5*std::abs(double(get_eye_offset(VRRuntime::Eye::RIGHT).x)-double(get_eye_offset(VRRuntime::Eye::LEFT).x))*\n"
     "                    100.0*double(m_world_scale->value()),\n"
     "                double(m_quadview_depth_strength->value()));\n"
     "            // Tri-view B6: use compact per-role targets for this draw only when a\n"),
    ("    if (layout->native_local && !native_target_ready)\n",
     "    {   // Tri-view B7: which DLSS output is the periphery (0 = unknown or a fovea has the same size).\n"
     "        const auto& c=layout->views[0]; const auto& f=layout->views[2];\n"
     "        const bool usable=layout->shared_context && !uevr::quadview::ngx::matches_periphery(f.width,f.height,c.width,c.height);\n"
     "        uevr::quadview::ngx::PeripheryDepth::self().set_expected(usable ? c.width : 0u, usable ? c.height : 0u);\n"
     "    }\n"
     "    if (layout->native_local && !native_target_ready)\n"),
    ('                m_quadview_compact_targets->draw("Compact source textures (saves video memory; OFF = B5 full-size textures)");\n',
     '                m_quadview_compact_targets->draw("Compact source textures (saves video memory; OFF = B5 full-size textures)");\n'
     '                m_quadview_depth_reproject->draw("Periphery depth reprojection (lines the periphery up with each eye using DLSS depth)");\n'
     '                m_quadview_depth_strength->draw("Periphery depth strength (1 = physical; -1 flips the direction)");\n'
     '                m_quadview_depth_show->draw("Show periphery depth (debug, grey = near is bright)");\n'
     '                {\n'
     '                    const auto s=uevr::quadview::ngx::PeripheryDepth::self().stats();\n'
     '                    ImGui::Text("Periphery depth: hooks %u/4, queue hook %s; DLSS calls %llu, periphery %llu, copied %llu, submitted %llu, used %llu, missing %llu, skipped %llu",\n'
     '                        s.hooks, s.queue_hook ? "on" : "off", (unsigned long long)s.evaluations, (unsigned long long)s.matches,\n'
     '                        (unsigned long long)s.captures, (unsigned long long)s.submits, (unsigned long long)s.used,\n'
     '                        (unsigned long long)s.missed, (unsigned long long)s.skips);\n'
     '                    ImGui::Text("Last periphery DLSS: output %ux%u, depth %ux%u", s.last_out_w, s.last_out_h, s.last_in_w, s.last_in_h);\n'
     '                }\n'),
])

edit("src/mods/vr/D3D12Component.cpp", [
    ('#include "D3D12Component.hpp"\n', '#include "D3D12Component.hpp"\n#include "QuadViewNgxDepth.hpp"\n'),
    ("vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {\n    sample_triview_vram(vr);\n",
     "vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {\n    sample_triview_vram(vr);\n"
     "    {   // Tri-view B7: periphery depth capture only while ID7 + depth (reproject or show) is on.\n"
     "        auto& depth=uevr::quadview::ngx::PeripheryDepth::self();\n"
     "        const bool want=vr->is_quadview_mode_selected() && (vr->quadview_depth_reproject() || vr->quadview_depth_show());\n"
     "        depth.set_enabled(want);\n"
     "        if (want) if (const auto& hook=g_framework->get_d3d12_hook(); hook) depth.install(hook->get_command_queue());\n"
     "    }\n"),
    ("                            bool recorded=false;\n"
     "                            ID3D12Resource* output=nullptr;\n"
     "                            uintptr_t command_list=0;\n",
     "                            bool recorded=false;\n"
     "                            ID3D12Resource* output=nullptr;\n"
     "                            uintptr_t command_list=0;\n"
     "                            uevr::quadview::dx12::DepthInput depth_input{};\n"
     "                            if (frozen->layout.shared_context && (vr->quadview_depth_reproject() || vr->quadview_depth_show())) {\n"
     "                                if (const auto snapshot=uevr::quadview::ngx::PeripheryDepth::self().latest()) {\n"
     "                                    depth_input.texture=snapshot->texture.Get();\n"
     "                                    for (size_t i=0; i!=4; ++i) { depth_input.rect[i]=snapshot->rect[i]; depth_input.shift[i]=frozen->layout.depth_shift[i]; }\n"
     "                                    depth_input.reproject=vr->quadview_depth_reproject();\n"
     "                                    depth_input.show=vr->quadview_depth_show();\n"
     "                                    depth_input.keepalive=snapshot;\n"
     "                                }\n"
     "                            }\n"),
    ("                                [this,packet,frozen,native_sources,timestamp_frequency,&recorded,&output,&command_list](d3d12::CommandContext& commands,ID3D12Resource* destination) {\n",
     "                                [this,packet,frozen,native_sources,timestamp_frequency,depth_input,&recorded,&output,&command_list](d3d12::CommandContext& commands,ID3D12Resource* destination) {\n"),
    ("                                        frozen->settings.gpu_timing ? timestamp_frequency : 0);\n",
     "                                        frozen->settings.gpu_timing ? timestamp_frequency : 0,\n"
     "                                        depth_input.texture ? &depth_input : nullptr);\n"),
])
print("Tri-view B7 periphery depth reprojection applied.")

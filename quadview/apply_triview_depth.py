#!/usr/bin/env python3
"""Tri-view B11: periphery depth reprojection from the DLSS depth input (ON by default).

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
- the periphery is recognised by its unique DLSS output size (make_layout keeps
  it distinct from the foveas); copies are used once their list was submitted;
- one compact [TriView][Depth] log line per second (proof from the game);
- the compositor receives the show request even when no texture is available.
Reprojection defaults ON (new setting key, old saved OFF values do not apply).
Show-depth renders a whole-eye magenta/black checker when unavailable, or
grayscale when real depth is bound.
"""
from pathlib import Path
import shutil
import sys

if len(sys.argv) != 3:
    raise SystemExit("Usage: apply_triview_depth.py <backend> <quadview-dir>")
root, overlay = Path(sys.argv[1]), Path(sys.argv[2])
for name in ("QuadViewNgxSelect.hpp", "QuadViewNgxDepth.hpp", "QuadViewSnapshot.hpp"):
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
     '    const ModToggle::Ptr m_quadview_depth_reproject{ModToggle::create(generate_name("TriViewPeripheryDepthB11"), true)};\n'
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
    ('#include "VR.hpp"\n', '#include "VR.hpp"\n#include "vr/QuadViewNgxDepth.hpp"\n#include "vr/QuadViewSnapshot.hpp"\n'),
    ("            // Tri-view B6: use compact per-role targets for this draw only when a\n",
     "            // Tri-view B7: periphery depth reprojection shift, frozen with the draw.\n"
     "            // near = UE near plane (projection m[3][2], cm); IPD from the runtime eye offsets\n"
     "            // (metres) x get_world_to_meters() (includes World Scale).\n"
     "            candidate->depth_shift=uevr::quadview::periphery_depth_shift(*candidate,\n"
     "                draw_config.base_projection_valid ? double(draw_config.projections[0][14]) : 0.0,\n"
     "                0.5*std::abs(double(get_eye_offset(VRRuntime::Eye::RIGHT).x)-double(get_eye_offset(VRRuntime::Eye::LEFT).x))*\n"
     "                    double(get_world_to_meters()),\n"
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
     '                m_quadview_depth_reproject->draw("Periphery depth reprojection (stereo periphery from DLSS depth)");\n'
     '                m_quadview_depth_strength->draw("Periphery depth strength (1 = physical; -1 flips the direction)");\n'
     '                m_quadview_depth_show->draw("Show depth diagnostic (grey = depth; magenta checker = unavailable)");\n'
     '                {\n'
     '                    const auto s=uevr::quadview::ngx::PeripheryDepth::self().stats();\n'
     '                    ImGui::Text("Periphery depth: %s", uevr::quadview::dx12::depth_state_name(uevr::quadview::dx12::last_depth_state().load()));\n'
     '                    ImGui::Text("hooks %u/6, queue hook %s; DLSS calls %llu, periphery %llu, copied %llu, submitted %llu, used %llu, missing %llu, skipped %llu",\n'
     '                        s.hooks, s.queue_hook ? "on" : "off", (unsigned long long)s.evaluations, (unsigned long long)s.matches,\n'
     '                        (unsigned long long)s.captures, (unsigned long long)s.submits, (unsigned long long)s.used,\n'
     '                        (unsigned long long)s.missed, (unsigned long long)s.skips);\n'
     '                    ImGui::Text("want %ux%u; periphery DLSS %ux%u (depth %ux%u, fmt %u); other DLSS %ux%u", s.want_w, s.want_h, s.last_out_w, s.last_out_h, s.last_in_w, s.last_in_h, s.last_format, s.other_w, s.other_h);\n'
     '                    ImGui::Text("last skip: %s", uevr::quadview::ngx::PeripheryDepth::reason_name(s.reason));\n'
     '                    if (ImGui::Button("Save TriView snapshot (images + numbers for Claude)")) {\n'
     '                        uevr::quadview::dx12::snapshot_requested().store(true);\n'
     '                        spdlog::info("[TriView][Snapshot] requested from the menu");\n'
     '                    }\n'
     '                    ImGui::TextUnformatted(("Last snapshot: " + uevr::quadview::dx12::last_snapshot_message()).c_str());\n'
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
     "        {   // Tri-view B11 proof: one automatic snapshot 25 s after ID7 is selected (+ menu button).\n"
     "            static bool snapshot_dir_set=false;\n"
     "            if (!snapshot_dir_set) { uevr::quadview::dx12::set_snapshot_directory(Framework::get_persistent_dir()/\"triview_snapshots\"); snapshot_dir_set=true; }\n"
     "            static auto id7_since=std::chrono::steady_clock::time_point{};\n"
     "            static bool auto_snapshot_done=false;\n"
     "            const auto now=std::chrono::steady_clock::now();\n"
     "            if (vr->is_quadview_mode_selected()) {\n"
     "                if (id7_since==std::chrono::steady_clock::time_point{}) id7_since=now;\n"
     "                if (!auto_snapshot_done && now-id7_since>std::chrono::seconds(25)) {\n"
     "                    auto_snapshot_done=true;\n"
     "                    uevr::quadview::dx12::snapshot_requested().store(true);\n"
     "                    spdlog::info(\"[TriView][Snapshot] automatic snapshot requested ({})\", uevr::quadview::dx12::snapshot_directory().string());\n"
     "                }\n"
     "            } else id7_since={};\n"
     "            static uint32_t snapshots_logged=0;\n"
     "            if (const auto n=uevr::quadview::dx12::snapshots_written().load(); n!=snapshots_logged) {\n"
     "                snapshots_logged=n;\n"
     "                spdlog::info(\"[TriView][Snapshot] {}\", uevr::quadview::dx12::last_snapshot_message());\n"
     "            }\n"
     "        }\n"
     "        static auto last_depth_log=std::chrono::steady_clock::time_point{};\n"
     "        if (want && std::chrono::steady_clock::now()-last_depth_log>std::chrono::seconds(1)) {\n"
     "            last_depth_log=std::chrono::steady_clock::now();\n"
     "            const auto s=depth.stats();\n"
     "            spdlog::info(\"[TriView][Depth] hooks={}/6 queue={} dlss={} periphery={} copied={} submitted={} used={} missing={} skipped={} want={}x{} out={}x{} in={}x{} fmt={} other={}x{} reason='{}' age_us={} slots={} jitter={}({:.3f},{:.3f}) foreign_queue={} warp='{}'\",\n"
     "                s.hooks, s.queue_hook, s.evaluations, s.matches, s.captures, s.submits, s.used, s.missed, s.skips, s.want_w, s.want_h,\n"
     "                s.last_out_w, s.last_out_h, s.last_in_w, s.last_in_h, s.last_format, s.other_w, s.other_h,\n"
     "                uevr::quadview::ngx::PeripheryDepth::reason_name(s.reason), s.used_age_us, s.slots, s.jitter_valid, s.jitter_x, s.jitter_y, s.foreign_queue_submits, uevr::quadview::dx12::depth_state_name(uevr::quadview::dx12::last_depth_state().load()));\n"
     "        }\n"
     "    }\n"),
    ("                            bool recorded=false;\n"
     "                            ID3D12Resource* output=nullptr;\n"
     "                            uintptr_t command_list=0;\n",
     "                            bool recorded=false;\n"
     "                            ID3D12Resource* output=nullptr;\n"
     "                            uintptr_t command_list=0;\n"
     "                            uevr::quadview::dx12::DepthInput depth_input{};\n"
     "                            depth_input.show=vr->quadview_depth_show();\n"
     "                            if (frozen->layout.shared_context && (vr->quadview_depth_reproject() || vr->quadview_depth_show())) {\n"
     "                                if (const auto snapshot=uevr::quadview::ngx::PeripheryDepth::self().latest()) {\n"
     "                                    depth_input.texture=snapshot->texture.Get();\n"
     "                                    depth_input.srv_format=snapshot->srv_format;\n"
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
     "                                        (depth_input.texture || depth_input.show) ? &depth_input : nullptr);\n"),
])
print("Tri-view B9 depth safety gate and whole-eye diagnostic applied.")

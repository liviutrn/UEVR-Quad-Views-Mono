#!/usr/bin/env python3
"""Tri-view B6: compact per-role source targets + VRAM readout for ID7.

Run AFTER apply_triview_parity.py. The geometry / compositor / validator parts
live in the quadview/ sources (copied by apply_quadviews.py):
  QuadViewGeometry.hpp   Layout::native_local, source_extents(), apply_native_local()
  QuadViewNativeTargets  valid_native_target_roles()
  QuadViewD3D12.hpp      per-role source size check, no overlap rule for local rects
  QuadViewComposite.hlsl each source normalised by its own texture size
This script wires the backend:
1. The four native targets are created at per-role extents (compact: context pair
   (cw+8) x (ch+8), focus pair (fw+8) x (fh+8); OFF: four 2W x H atlases = B5).
2. A draw switches to target-local rectangles ONLY when a matching, live compact
   set is already published, decided before the layout freeze, so the latch,
   the producer snapshot and the hook fallback all agree. Otherwise the draw
   keeps the atlas layout and today's legacy family path (warm-up behaviour).
3. Toggle "Compact source textures" (QuadViewCompactSources, default ON, saved).
4. VRAM readout (game process, DXGI) in the ID7 menu and in the log every 10 s.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_triview_compact.py <backend>")
root = Path(sys.argv[1])

EXT = "std::array<std::array<uint32_t,2>,4>"


def edit(rel, pairs):
    path = root / rel
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{rel}: expected exactly one anchor, found {count}:\n{old[:240]}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


# ------------------------------------------------------------ FFakeStereoRenderingHook.hpp
edit("src/mods/vr/FFakeStereoRenderingHook.hpp", [
    ("        uint32_t width{},height{};\n        bool complete() const {\n"
     "            std::array<uevr::quadview::NativeTargetIdentity,4> identities{};\n",
     "        uint32_t width{},height{}; // role 0 extent (logs)\n"
     f"        {EXT} extents{{}}; // Tri-view B6: per-role target extents\n"
     "        bool complete() const {\n"
     "            std::array<uevr::quadview::NativeTargetIdentity,4> identities{};\n"),
    ("            return generation && world_identity && width && height &&\n"
     "                std::all_of(identities.begin(),identities.end(),[&](const auto& value) {\n"
     "                    return value.width==width && value.height==height;\n"
     "                }) && uevr::quadview::valid_native_target_quartet(identities);\n",
     "            return generation && world_identity && width && height &&\n"
     "                uevr::quadview::valid_native_target_roles(identities,extents);\n"),
    ("    bool ensure_quadview_native_target_set(uint32_t width,uint32_t height);\n",
     f"    bool ensure_quadview_native_target_set(const {EXT}& extents);\n"),
])

# ------------------------------------------------------------ FFakeStereoRenderingHook.cpp
edit("src/mods/vr/FFakeStereoRenderingHook.cpp", [
    ("struct VRRenderTargetManager_Base::QuadViewNativeTargetBuild {\n"
     "    uint64_t generation{};\n"
     "    uintptr_t world_identity{};\n"
     "    uint32_t width{},height{};\n",
     "struct VRRenderTargetManager_Base::QuadViewNativeTargetBuild {\n"
     "    uint64_t generation{};\n"
     "    uintptr_t world_identity{};\n"
     "    uint32_t width{},height{};\n"
     f"    {EXT} extents{{}}; // Tri-view B6\n"),
    ("bool VRRenderTargetManager_Base::ensure_quadview_native_target_set(uint32_t width,uint32_t height) {\n",
     f"bool VRRenderTargetManager_Base::ensure_quadview_native_target_set(const {EXT}& extents) {{\n"
     "    // Tri-view B6: per-role extents (compact sources) or four equal 2W x H atlases.\n"
     "    const bool extents_valid=std::all_of(extents.begin(),extents.end(),[](const auto& e) {\n"
     "        return e[0] && e[1] && e[0]<=16384 && e[1]<=8192; });\n"
     "    const uint32_t width=extents_valid ? extents[0][0] : 0, height=extents_valid ? extents[0][1] : 0;\n"),
    ("            try { GameThreadWorker::get().enqueue([this,width,height]() {\n"
     "                quadview_native_target_creation_requested.store(false,std::memory_order_release);\n"
     "                (void)ensure_quadview_native_target_set(width,height);\n",
     "            try { GameThreadWorker::get().enqueue([this,extents]() {\n"
     "                quadview_native_target_creation_requested.store(false,std::memory_order_release);\n"
     "                (void)ensure_quadview_native_target_set(extents);\n"),
    ("        current && current->world_identity==world_identity && current->width==width &&\n"
     "        current->height==height && current->complete()) {\n",
     "        current && current->world_identity==world_identity && current->extents==extents &&\n"
     "        current->complete()) {\n"),
    ("            quadview_native_target_build->width==width && quadview_native_target_build->height==height) return false;\n",
     "            quadview_native_target_build->extents==extents) return false;\n"),
    ("        build->world_identity=world_identity; build->width=width; build->height=height;\n",
     "        build->world_identity=world_identity; build->width=width; build->height=height;\n"
     "        build->extents=extents;\n"),
    ("            auto* texture=kismet->create_render_target_2d(world,width,height,2,clear_color,false);\n",
     "            auto* texture=kismet->create_render_target_2d(world,build->extents[i][0],build->extents[i][1],2,clear_color,false);\n"),
    ("            const auto validated=validate_native_fix_texture_chain(owner->texture.get(),build->width,build->height,\n",
     "            const auto validated=validate_native_fix_texture_chain(owner->texture.get(),build->extents[i][0],build->extents[i][1],\n"),
    ("        target_set->width=build->width; target_set->height=build->height;\n",
     "        target_set->width=build->width; target_set->height=build->height;\n"
     "        target_set->extents=build->extents;\n"),
    ("            snapshot->generation=build->generation; snapshot->width=build->width; snapshot->height=build->height;\n",
     "            snapshot->generation=build->generation; snapshot->width=build->extents[i][0]; snapshot->height=build->extents[i][1];\n"),
    ('        SPDLOG_INFO("[QuadViews][NativeFix] Published four independent {}x{} UE5.5 source targets generation={}",\n'
     "            build->width,build->height,build->generation);\n",
     '        SPDLOG_INFO("[QuadViews][NativeFix] Published four independent UE5.5 source targets {}x{} {}x{} {}x{} {}x{} generation={}",\n'
     "            build->extents[0][0],build->extents[0][1],build->extents[1][0],build->extents[1][1],\n"
     "            build->extents[2][0],build->extents[2][1],build->extents[3][0],build->extents[3][1],build->generation);\n"),
    # native dispatch gate: per-role extents must match the frozen layout
    ("            qv_target_set->width==qv_snapshot->layout.atlas_width && qv_target_set->height==qv_snapshot->layout.atlas_height &&\n",
     "            qv_target_set->extents==uevr::quadview::source_extents(qv_snapshot->layout) &&\n"),
])

# ------------------------------------------------------------ VR.hpp
edit("src/mods/VR.hpp", [
    ("    bool is_duoview_or_triview_fov_active() const;\n",
     "    bool is_duoview_or_triview_fov_active() const;\n"
     "    // Tri-view B6: game-process video memory (DXGI), sampled by D3D12Component.\n"
     "    void note_triview_vram(uint64_t used, uint64_t budget, uint64_t system) {\n"
     "        m_triview_vram_used.store(used, std::memory_order_relaxed);\n"
     "        m_triview_vram_budget.store(budget, std::memory_order_relaxed);\n"
     "        m_triview_vram_system.store(system, std::memory_order_relaxed);\n"
     "    }\n"
     "    std::atomic<uint64_t> m_triview_vram_used{0}, m_triview_vram_budget{0}, m_triview_vram_system{0};\n"),
    ('    const ModSlider::Ptr m_quadview_sharpen_max{ModSlider::create(generate_name("QuadViewSharpenMaxChange"), 0.05f, 0.30f, 0.10f)};\n',
     '    const ModSlider::Ptr m_quadview_sharpen_max{ModSlider::create(generate_name("QuadViewSharpenMaxChange"), 0.05f, 0.30f, 0.10f)};\n'
     '    const ModToggle::Ptr m_quadview_compact_targets{ModToggle::create(generate_name("QuadViewCompactSources"), true)};\n'),
    ("            *m_quadview_sharpen, *m_quadview_sharpen_max, *m_quadview_eye_tracking,\n",
     "            *m_quadview_sharpen, *m_quadview_sharpen_max, *m_quadview_eye_tracking,\n"
     "            *m_quadview_compact_targets,\n"),
])

# ------------------------------------------------------------ VR.cpp
edit("src/mods/VR.cpp", [
    # decide compact rectangles before the layout freeze
    ("            layout=m_quadview_layout_latch.freeze(key.generation,key.draw_serial,*candidate);\n",
     "            // Tri-view B6: use compact per-role targets for this draw only when a\n"
     "            // matching live set is already published; otherwise keep the atlas layout.\n"
     "            if (m_quadview_compact_targets->value()) {\n"
     "                auto compact=*candidate;\n"
     "                const auto compact_rtm=m_fake_stereo_hook->get_render_target_manager();\n"
     "                if (uevr::quadview::apply_native_local(compact) && compact_rtm && is_quadview_supported_title()) {\n"
     "                    const auto compact_extents=uevr::quadview::source_extents(compact);\n"
     "                    if (compact_rtm->ensure_quadview_native_target_set(compact_extents)) {\n"
     "                        const auto set=compact_rtm->get_quadview_native_target_set();\n"
     "                        if (set && set->extents==compact_extents && set->complete()) *candidate=compact;\n"
     "                    }\n"
     "                }\n"
     "            }\n"
     "            layout=m_quadview_layout_latch.freeze(key.generation,key.draw_serial,*candidate);\n"),
    ("    if (rtm && is_quadview_supported_title() && rtm->ensure_quadview_native_target_set(layout->atlas_width,layout->atlas_height))\n"
     "        native_target_set=rtm->get_quadview_native_target_set();\n"
     "    const bool native_target_ready=native_target_set && native_target_set->width==layout->atlas_width &&\n"
     "        native_target_set->height==layout->atlas_height && native_target_set->complete();\n",
     "    // Tri-view B6: while compact sources are ON always request the compact set (no\n"
     "    // thrash between atlas and compact sizes); the draw follows its frozen layout.\n"
     "    auto requested_extents=uevr::quadview::source_extents(*layout);\n"
     "    if (m_quadview_compact_targets->value() && !layout->native_local) {\n"
     "        auto compact=*layout;\n"
     "        if (uevr::quadview::apply_native_local(compact)) requested_extents=uevr::quadview::source_extents(compact);\n"
     "    }\n"
     "    if (rtm && is_quadview_supported_title() && rtm->ensure_quadview_native_target_set(requested_extents))\n"
     "        native_target_set=rtm->get_quadview_native_target_set();\n"
     "    const bool native_target_ready=native_target_set &&\n"
     "        native_target_set->extents==uevr::quadview::source_extents(*layout) && native_target_set->complete();\n"
     "    if (layout->native_local && !native_target_ready)\n"
     "        SPDLOG_WARNING_EVERY_N_SEC(2,\"[QuadViews][Compact] compact layout frozen but its target set is no longer live (generation={} draw={})\",\n"
     "            key.generation,key.draw_serial);\n"),
    # menu: status lines + toggle
    ('            ImGui::TextWrapped("Quad Views status: %s", quadview_status());\n'
     '            if (ImGui::TreeNode("Quad Views Stereo',
     '            ImGui::TextWrapped("Quad Views status: %s", quadview_status());\n'
     '            {\n'
     '                const auto vram_used=m_triview_vram_used.load(std::memory_order_relaxed);\n'
     '                const auto vram_budget=m_triview_vram_budget.load(std::memory_order_relaxed);\n'
     '                const auto vram_system=m_triview_vram_system.load(std::memory_order_relaxed);\n'
     '                if (vram_budget)\n'
     '                    ImGui::Text("Video memory (whole game process): %.0f MB used / %.0f MB budget (%.0f%%); in system memory %.0f MB",\n'
     '                        vram_used/1048576.0, vram_budget/1048576.0, 100.0*vram_used/vram_budget, vram_system/1048576.0);\n'
     '                else ImGui::TextUnformatted("Video memory: waiting for the first DXGI reading");\n'
     '                const auto rtm_status=m_fake_stereo_hook ? m_fake_stereo_hook->get_render_target_manager() : nullptr;\n'
     '                const auto set_status=rtm_status ? rtm_status->get_quadview_native_target_set() : nullptr;\n'
     '                if (set_status) {\n'
     '                    const auto& e=set_status->extents;\n'
     '                    double source_mb=0.0;\n'
     '                    for (const auto& one : e) source_mb+=4.0*one[0]*one[1]/1048576.0;\n'
     '                    ImGui::Text("Source textures: %ux%u, %ux%u, %ux%u, %ux%u (%.0f MB colour)", e[0][0], e[0][1], e[1][0], e[1][1],\n'
     '                        e[2][0], e[2][1], e[3][0], e[3][1], source_mb);\n'
     '                } else ImGui::TextUnformatted("Source textures: not published yet");\n'
     '            }\n'
     '            if (ImGui::TreeNode("Quad Views Stereo'),
    ('                m_quadview_context_scale->draw("Context resolution scale");\n',
     '                m_quadview_context_scale->draw("Context resolution scale");\n'
     '                m_quadview_compact_targets->draw("Compact source textures (saves video memory; OFF = B5 full-size textures)");\n'),
])

# ------------------------------------------------------------ D3D12Component.cpp (VRAM sampler)
edit("src/mods/vr/D3D12Component.cpp", [
    ("#include <d3dcompiler.h>\n",
     "#include <d3dcompiler.h>\n#include <dxgi1_4.h>\n"),
    ("vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {\n"
     "    const char* qv_present_stage=\"entered\";\n",
     "// Tri-view B6: game-process video memory once per second while ID7 is selected.\n"
     "// Uses the game swap chain's own DXGI factory. The adapter reference is kept\n"
     "// as a raw pointer on purpose (no static ComPtr destructor at process exit).\n"
     "static void sample_triview_vram(VR* vr) {\n"
     "    if (vr == nullptr || !vr->is_quadview_mode_selected()) return;\n"
     "    static std::chrono::steady_clock::time_point next_sample{};\n"
     "    static IDXGIAdapter3* adapter = nullptr;\n"
     "    static LUID adapter_luid{};\n"
     "    const auto now = std::chrono::steady_clock::now();\n"
     "    if (now < next_sample) return;\n"
     "    next_sample = now + std::chrono::seconds(1);\n"
     "    auto& hook = g_framework->get_d3d12_hook();\n"
     "    if (hook == nullptr) return;\n"
     "    auto* device = hook->get_device();\n"
     "    auto* swap_chain = hook->get_swap_chain();\n"
     "    if (device == nullptr || swap_chain == nullptr) return;\n"
     "    const auto luid = device->GetAdapterLuid();\n"
     "    if (adapter == nullptr || luid.LowPart != adapter_luid.LowPart || luid.HighPart != adapter_luid.HighPart) {\n"
     "        if (adapter != nullptr) { adapter->Release(); adapter = nullptr; }\n"
     "        Microsoft::WRL::ComPtr<IDXGIFactory4> factory{};\n"
     "        Microsoft::WRL::ComPtr<IDXGIAdapter3> found{};\n"
     "        if (FAILED(swap_chain->GetParent(IID_PPV_ARGS(&factory))) || factory == nullptr ||\n"
     "            FAILED(factory->EnumAdapterByLuid(luid, IID_PPV_ARGS(&found))) || found == nullptr) {\n"
     "            SPDLOG_WARNING_EVERY_N_SEC(30, \"[QuadViews][VRAM] DXGI adapter query unavailable\");\n"
     "            return;\n"
     "        }\n"
     "        adapter = found.Detach();\n"
     "        adapter_luid = luid;\n"
     "    }\n"
     "    DXGI_QUERY_VIDEO_MEMORY_INFO local{}, system{};\n"
     "    if (FAILED(adapter->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_LOCAL, &local))) return;\n"
     "    if (FAILED(adapter->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_NON_LOCAL, &system))) system = {};\n"
     "    vr->note_triview_vram(local.CurrentUsage, local.Budget, system.CurrentUsage);\n"
     "    SPDLOG_INFO_EVERY_N_SEC(10, \"[QuadViews][VRAM] game process: {} MB used / {} MB budget; in system memory {} MB\",\n"
     "        local.CurrentUsage >> 20, local.Budget >> 20, system.CurrentUsage >> 20);\n"
     "}\n"
     "\n"
     "vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {\n"
     "    sample_triview_vram(vr);\n"
     "    const char* qv_present_stage=\"entered\";\n"),
])

print("Tri-view B6 compact sources + VRAM readout applied.")

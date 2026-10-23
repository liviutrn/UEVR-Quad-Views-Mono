#!/usr/bin/env python3
"""Opt-in passive depth discovery on validated v186.1 Build49.

NOT a depth texture capture or stereo reconstruction. Exact-anchor post-Build49
patch. OFF route preserves original DuoView color and Mono OpenXR path.
"""
import argparse
from pathlib import Path

def change(root, relative, before, after):
    path = root / relative
    old = path.read_text(encoding="utf-8-sig")
    n = old.count(before)
    if n != 1:
        raise RuntimeError(f"DepthDiscovery exact anchor mismatch {relative}: {n} occurrences: {before[:90]!r}")
    path.write_text(old.replace(before, after, 1), encoding="utf-8", newline="\n")

def apply(backend: Path):
    change(backend, "src/mods/VR.hpp",
        '    bool is_duoview_renderer_active() const;',
        '''    bool is_duoview_renderer_active() const;
    bool is_duoview_depth_discovery_enabled() const {
        return is_duoview_renderer_active() && m_duo_depth_discovery->value();
    }''')
    change(backend, "src/mods/VR.hpp",
        '    const ModInt32::Ptr m_duo_debug_source{ModSliderInt32::create(generate_name("DuoViewDebugSource"), 0, 2, 0)};',
        '''    const ModInt32::Ptr m_duo_debug_source{ModSliderInt32::create(generate_name("DuoViewDebugSource"), 0, 2, 0)};
    const ModToggle::Ptr m_duo_depth_discovery{ModToggle::create(generate_name("DuoViewDepthDiscoveryP0"), false)};''')
    change(backend, "src/mods/VR.hpp",
        '            *m_duo_feather, *m_duo_sharpen, *m_duo_gaze, *m_duo_border, *m_duo_debug_source,',
        '            *m_duo_feather, *m_duo_sharpen, *m_duo_gaze, *m_duo_border, *m_duo_debug_source, *m_duo_depth_discovery,')
    change(backend, "src/mods/VR.cpp",
        '                m_duo_debug_source->draw("Source diagnostic: 0 Blend / 1 Periphery / 2 Fovea");',
        '''                m_duo_debug_source->draw("Source diagnostic: 0 Blend / 1 Periphery / 2 Fovea");
                if (ImGui::TreeNode("Depth Discovery P0 (passive; NO depth copies)")) {
                    m_duo_depth_discovery->draw("Trace candidate depth DSV resources (opt-in)");
                    ImGui::TextWrapped("This traces potential DSV/RDG depth resources only. Captured depth: UNVERIFIED for both DuoView views. No stereo synthesis, GPU depth copy or change to normal HMD output.");
                    if (m_duo_depth_discovery->value()) {
                        if (ImGui::Button("Log next 200 DuoView source frames")) {
                            d3d12().arm_duoview_depth_discovery();
                        }
                        ImGui::Text("Source diagnostics remaining: %u", d3d12().duoview_depth_discovery_remaining());
                        const auto summary = d3d12().duoview_depth_discovery_summary();
                        ImGui::TextWrapped("DSV (not proven source-matched): %s", summary.c_str());
                    }
                    ImGui::TreePop();
                }''')
    change(backend, "src/mods/vr/D3D12Component.hpp",
        '    std::string get_dibr_preview_depth_trace_summary() const { return m_dibr_depth_capture.depth_trace_summary(); }',
        '''    std::string get_dibr_preview_depth_trace_summary() const { return m_dibr_depth_capture.depth_trace_summary(); }
    std::string duoview_depth_discovery_summary() const { return m_dibr_depth_capture.depth_trace_summary(); }
    void arm_duoview_depth_discovery() {
        m_duoview_depth_discovery_remaining.store(200, std::memory_order_release);
    }
    uint32_t duoview_depth_discovery_remaining() const {
        return m_duoview_depth_discovery_remaining.load(std::memory_order_acquire);
    }''')
    change(backend, "src/mods/vr/D3D12Component.hpp",
        '    d3d12::DIBRPreview m_dibr_depth_capture{};',
        '''    d3d12::DIBRPreview m_dibr_depth_capture{};
    std::atomic<uint32_t> m_duoview_depth_discovery_remaining{0};''')
    change(backend, "src/mods/vr/D3D12Component.cpp",
        '''        m_dibr_depth_capture.set_ue5_rdg_depth_capture_enabled(vr->is_dibr_ue5_rdg_depth_capture_enabled());
        hook->set_depth_stencil_observer(vr->is_dibr_depth_trace_requested() ? &m_dibr_depth_capture : nullptr);''',
        '''        // A single observer only. With DuoView P0 active it is used solely
        // for passive DSV discovery; disable old Joey DIBR depth copies.
        const bool duo_depth_discovery = vr->is_duoview_depth_discovery_enabled();
        m_dibr_depth_capture.set_ue5_rdg_depth_capture_enabled(
            !vr->is_duoview_renderer_active() && vr->is_dibr_ue5_rdg_depth_capture_enabled());
        hook->set_depth_stencil_observer(
            (duo_depth_discovery ||
             (!vr->is_duoview_renderer_active() && vr->is_dibr_depth_trace_requested()))
                 ? &m_dibr_depth_capture : nullptr);''')
    change(backend, "src/mods/vr/D3D12Component.cpp",
        '''    // DIBR consumes SceneDepthZ internally even when compositor depth submit
    // is disabled.''',
        '''    // DuoView depth discovery only: use the real Native primary scene
    // allocation, NOT the potentially unrelated desktop backbuffer. Never
    // claim that a size-compatible DSV belongs to either foveal view.
    if (vr->is_duoview_depth_discovery_enabled()) {
        auto primary = m_game_tex.texture.Get();
        auto secondary = m_scene_capture_tex.texture.Get();
        if (primary != nullptr) {
            const auto pd = primary->GetDesc();
            m_dibr_depth_capture.set_depth_trace_expected_extent(
                static_cast<uint32_t>(pd.Width), pd.Height);
            auto count = m_duoview_depth_discovery_remaining.load(std::memory_order_acquire);
            while (count > 0 && !m_duoview_depth_discovery_remaining.compare_exchange_weak(
                    count, count-1, std::memory_order_acq_rel)) {}
            if (count > 0) {
                const auto sd = secondary != nullptr ? secondary->GetDesc() : D3D12_RESOURCE_DESC{};
                // Pool texture identity alone is diagnostic, never accepted
                // as proof of this exact UE pass or as a usable GPU snapshot.
                auto pool_depth = vr->get_render_target_pool_hook()->get_texture<ID3D12Resource>(L"SceneDepthZ");
                const auto zd = pool_depth != nullptr ? pool_depth->GetDesc() : D3D12_RESOURCE_DESC{};
                const auto frozen = vr->duoview_state().snapshot(vr->duoview_producer_key());
                SPDLOG_INFO(
                    "[DuoDepthP0][UNVERIFIED] remaining={} frame={} producer={}:{} pose={} foveaUE={} primary=0x{:X} {}x{} fmt={} flags={} secondary=0x{:X} {}x{} fmt={} flags={} SceneDepthZpool=0x{:X} {}x{} fmt={} flags={} samples={} DSV_candidate={}",
                    count-1, vr->m_render_frame_count,
                    frozen ? frozen->config.key.generation : 0,
                    frozen ? frozen->config.key.frame : 0,
                    frozen && frozen->mono_source_frame ? *frozen->mono_source_frame : 0,
                    frozen ? frozen->config.settings.fovea_view : 0,
                    reinterpret_cast<uintptr_t>(primary), pd.Width, pd.Height,
                    static_cast<unsigned>(pd.Format), static_cast<unsigned>(pd.Flags),
                    reinterpret_cast<uintptr_t>(secondary), sd.Width, sd.Height,
                    static_cast<unsigned>(sd.Format), static_cast<unsigned>(sd.Flags),
                    reinterpret_cast<uintptr_t>(pool_depth.Get()), zd.Width, zd.Height,
                    static_cast<unsigned>(zd.Format), static_cast<unsigned>(zd.Flags),
                    zd.SampleDesc.Count,
                    m_dibr_depth_capture.depth_trace_summary());
            }
        }
    }
    // DIBR consumes SceneDepthZ internally even when compositor depth submit
    // is disabled.''')
    print("Depth Discovery P0 applied: opt-in observer only, no renderer output modifications")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", type=Path)
    apply(parser.parse_args().backend)

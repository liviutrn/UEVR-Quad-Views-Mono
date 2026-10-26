"""Apply the independent review corrections after the R3 overlays."""
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()


def edit(path, old, new):
    target = root / path
    source = target.read_text()
    if source.count(old) != 1:
        raise RuntimeError(f"{path}: expected one review anchor, got {source.count(old)}: {old[:100]}")
    target.write_text(source.replace(old, new))


shader = "src/mods/vr/d3d12/DIBRPreview.cpp"
edit(shader,
     "float2 ReprojectSourceUv(float2 source_uv, float raw_depth) {",
     "float2 ReprojectSourceUv(float2 source_uv, float raw_depth, float reprojection_strength) {")
edit(shader,
     "    return float2(target_ndc.x * 0.5f + 0.5f, 0.5f - target_ndc.y * 0.5f);",
     """    const float2 target_uv = float2(target_ndc.x * 0.5f + 0.5f, 0.5f - target_ndc.y * 0.5f);
    // Strength changes the mapping being solved, rather than the solver gain.
    // Multiplying each correction by strength made strength=2 undo the first
    // iteration on a constant-depth plane and collapse stereo back to zero.
    return lerp(source_uv, target_uv, reprojection_strength);""")
edit(shader,
     "ReprojectSourceUv(source_uv, source_depth)",
     "ReprojectSourceUv(source_uv, source_depth, reprojection_strength)")
edit(shader,
     "const float2 candidate = source_uv + correction * reprojection_strength;",
     "const float2 candidate = source_uv + correction;")
edit(shader,
     "    float2 synthesized_source_uv,\n    uint source_clamped,",
     "    float2 synthesized_source_uv,\n    float reprojection_strength,\n    uint source_clamped,")
edit(shader,
     "ReprojectSourceUv(synthesized_source_uv, source_depth)",
     "ReprojectSourceUv(synthesized_source_uv, source_depth, reprojection_strength)")
edit(shader,
     "            synthesized_source_uv,\n            source_clamped,",
     "            synthesized_source_uv,\n            reprojection_strength,\n            source_clamped,")

print("Applied independent review correction: monotonic DIBR strength and matching spatial-repair mapping")

hook = "src/mods/vr/FFakeStereoRenderingHook.cpp"
edit(hook,
     """        if (ready.preview_ready && ready.consecutive_ready_frames >= DIBR_SINGLE_VIEW_WARMUP_FRAMES) return 1;""",
     """        const auto expected_viewport = g_hook->get_render_target_manager()->get_viewport();
        const bool validated_main_family = ready.generation != 0 &&
            ready.generation == g_hook->m_dibr_single_view_generation &&
            expected_viewport != nullptr &&
            g_hook->m_dibr_single_view_target == reinterpret_cast<uintptr_t>(expected_viewport) &&
            g_hook->m_dibr_single_view_scene != 0 &&
            g_hook->m_dibr_single_view_stable_frames >= DIBR_SINGLE_VIEW_FAMILY_STABLE_FRAMES;
        if (is_stereo_enabled && g_hook->is_in_viewport_client_draw() &&
            validated_main_family && ready.preview_ready &&
            ready.consecutive_ready_frames >= DIBR_SINGLE_VIEW_WARMUP_FRAMES) return 1;""")
edit(hook,
     """            if (main_family && prev_count == 1 && readiness.preview_ready) {""",
     """            if (main_family) {
                const auto target = reinterpret_cast<uintptr_t>(view_family->get_render_target());
                const auto scene = reinterpret_cast<uintptr_t>(view_family->get_scene_interface());
                if (g_hook->m_dibr_single_view_target != target || g_hook->m_dibr_single_view_scene != scene) {
                    g_hook->m_dibr_single_view_target = target;
                    g_hook->m_dibr_single_view_scene = scene;
                    g_hook->m_dibr_single_view_stable_frames = 1;
                } else if (g_hook->m_dibr_single_view_stable_frames < DIBR_SINGLE_VIEW_FAMILY_STABLE_FRAMES) {
                    ++g_hook->m_dibr_single_view_stable_frames;
                }
                g_hook->m_dibr_single_view_family = reinterpret_cast<uintptr_t>(view_family);
            } else if (view_family->get_render_target() == rtm->get_viewport()) {
                // A malformed current main family invalidates the prior proof.
                // Unrelated scene captures never acquire or replace that proof.
                g_hook->m_dibr_single_view_stable_frames = 0;
                set_dibr_status(DIBR_SINGLE_VIEW_FALLBACK, "STALKER: current main family failed validation");
            }
            if (main_family && prev_count == 1 && readiness.preview_ready) {""")

edit("src/mods/vr/D3D12Component.cpp",
     """        m_dibr_single_view_preview_ready.store(false, std::memory_order_release);
        return;
    }

    const auto width = static_cast<uint32_t>""",
     """        m_dibr_single_view_preview_ready.store(false, std::memory_order_release);
        m_dibr_single_view_ready_frames.store(0, std::memory_order_release);
        return;
    }

    const auto width = static_cast<uint32_t>""")
print("Applied main Draw/validated family activation gate and consecutive-output warmup reset")

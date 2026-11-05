#!/usr/bin/env python3
"""Initialize ID7's existing engine dependencies before its early-return paths.

Run after apply_triview_stability.py and apply_triview_eye_sharpen.py,
before embed_shader.py. No new allocator, texture identity, or native ABI.
"""
from pathlib import Path
import sys

REL = Path("src/mods/vr/FFakeStereoRenderingHook.cpp")
PROJECTION = "__forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_matrix("
BOOT_START = "    bool ghosting_bootstrap_ready = false;\n"
BOOT_END = "    if (!g_framework->is_game_data_intialized()) {\n"


def replace_once(source, before, after):
    count = source.count(before)
    if count != 1:
        raise RuntimeError(f"bootstrap anchor count {count}: {before[:100]!r}")
    return source.replace(before, after, 1)


def transform(source):
    start = source.index(PROJECTION)
    block_start = source.index(BOOT_START, start)
    block_end = source.index(BOOT_END, block_start)
    bootstrap = source[block_start:block_end]
    bootstrap = replace_once(bootstrap,
        "    const bool native_needs_localplayer_bootstrap = vr->is_native_stereo_fix_enabled();\n",
        "    // ID7 needs the same existing two-eye LocalPlayer allocation before its projection return.\n"
        "    const bool qv_needs_localplayer_bootstrap =\n"
        "        (vr->is_quadview_mode_selected() ||\n"
        "         vr->requested_rendering_method() == VR::RenderingMethod::QUAD_VIEWS_STEREO) &&\n"
        "        vr->is_quadview_supported_title() && g_framework != nullptr && g_framework->is_dx12() &&\n"
        "        vr->get_runtime() != nullptr && vr->get_runtime()->is_openxr();\n"
        "    const bool native_needs_localplayer_bootstrap =\n"
        "        vr->is_native_stereo_fix_enabled() || qv_needs_localplayer_bootstrap;\n")
    # The entire original allocator/hook block moves unchanged except its admission predicate.
    source = source[:block_start] + source[block_end:]
    insert = source.index("    if (vr->is_quadview_layout_active()) {\n", start)
    readiness = (
        "    if (qv_needs_localplayer_bootstrap) {\n"
        "        SPDLOG_INFO_EVERY_N_SEC(2,\n"
        "            \"[QuadViews][Bootstrap] LocalPlayer attempted={} failed={} projection_hook={} entry_hook={} skip={} lazy={}\",\n"
        "            g_hook->m_fixed_localplayer_view_count,\n"
        "            g_hook->m_native_stereo_localplayer_bootstrap_failed.load(std::memory_order_acquire),\n"
        "            !!g_hook->m_calculate_stereo_projection_matrix_post_hook,\n"
        "            !!g_hook->m_get_projection_data_pre_hook, vr->should_skip_post_init_properties(),\n"
        "            stalker2_uses_lazy_synced_viewstates());\n"
        "    }\n\n")
    source = source[:insert] + bootstrap + readiness + source[insert:]
    before = (
        "        auto* qv_init_family=init_options->get_view_family();\n"
        "        auto* qv_init_views=qv_init_family ? qv_init_family->get_views() : nullptr;\n"
        "        auto* qv_constructor_rtm=g_hook->get_render_target_manager();\n")
    after = (
        "        auto* qv_init_family=init_options->get_view_family();\n"
        "        auto* qv_constructor_rtm=g_hook->get_render_target_manager();\n"
        "        // Resolve the family before any ID7 getter; later render callbacks may be withheld.\n"
        "        bool qv_family_layout_ready=qv_init_family != nullptr && sdk::FSceneViewFamily::has_offsets();\n"
        "        if (qv_init_family && !qv_family_layout_ready) {\n"
        "            qv_family_layout_ready=sdk::FSceneViewFamily::update_offsets(qv_init_family,\n"
        "                qv_constructor_rtm ? qv_constructor_rtm->get_viewport() : nullptr);\n"
        "        }\n"
        "        SPDLOG_INFO_EVERY_N_SEC(2,\n"
        "            \"[QuadViews][Bootstrap] family_layout={} family={:x} native_targets={}\",\n"
        "            qv_family_layout_ready,reinterpret_cast<uintptr_t>(qv_init_family),bool(qv_native_targets));\n"
        "        if (!qv_family_layout_ready) {\n"
        "            vr->set_quadview_status(\"Waiting for validated engine view-family layout\");\n"
        "            return g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view,init_options,a3,a4);\n"
        "        }\n"
        "        g_hook->note_scene_view_family_offsets_ready();\n"
        "        auto* qv_init_views=qv_init_family->get_views();\n")
    source = replace_once(source, before, after)
    before = (
        "        const auto expected_rhi_vtable = FRHITexture2D::get_vtable();\n"
        "        if (rhi_texture == nullptr || expected_rhi_vtable == nullptr ||\n")
    after = (
        "        const auto expected_rhi_vtable = FRHITexture2D::get_vtable();\n"
        "        if (const auto vr=VR::get(); vr && vr->is_quadview_mode_selected()) {\n"
        "            SPDLOG_INFO_EVERY_N_SEC(2,\n"
        "                \"[QuadViews][Bootstrap] RHI class_ready={} expected_vtable={:x} texture={:x}\",\n"
        "                expected_rhi_vtable != nullptr,reinterpret_cast<uintptr_t>(expected_rhi_vtable),\n"
        "                reinterpret_cast<uintptr_t>(rhi_texture));\n"
        "        }\n"
        "        if (rhi_texture == nullptr || expected_rhi_vtable == nullptr ||\n")
    return replace_once(source, before, after)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_triview_bootstrap.py <backend>")
    path = Path(sys.argv[1]) / REL
    path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied bounded ID7 family and LocalPlayer bootstrap")


if __name__ == "__main__":
    main()

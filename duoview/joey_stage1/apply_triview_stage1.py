#!/usr/bin/env python3
"""Tri-View Stage 1: rendering method ID 7 = Joey's Native Stereo + Native Fix + one centre periphery view.

Run AFTER the complete v207 patch chain (... apply_v207_auto_fov_after_load, verify_stage234).
Every edit is an exact anchor that must occur once. Modes 0-6 keep their code paths: every new branch is
gated by ID 7 (is_triview_active / is_triview_selected) or by Tri-View having requested a third view.
Design: research/2026-11-01-triview-stage1-decision.md.

  apply:   apply_triview_stage1.py BACKEND FRONTEND DUOVIEW_DIR EVIDENCE
  verify:  apply_triview_stage1.py --verify BACKEND EVIDENCE   (after the build: nothing changed)
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys

V207_EDITED = {
    "src/mods/vr/MonoRenderingPolicy.hpp", "src/mods/vr/CompatibilityPolicy.hpp",
    "src/mods/VR.hpp", "src/mods/VR.cpp",
    "src/mods/vr/OverlayComponent.hpp", "src/mods/vr/OverlayComponent.cpp",
    "src/mods/vr/FFakeStereoRenderingHook.cpp", "src/mods/vr/FFakeStereoRenderingHook.hpp",
    "src/mods/vr/runtimes/OpenXR.cpp", "src/mods/vr/runtimes/OpenXR.hpp",
    "src/mods/vr/D3D12Component.hpp", "src/mods/vr/D3D12Component.cpp", "tests/MonoRenderingTests.hpp",
    "tests/CadenceReplayTests.cpp",
}
V207_ADDED = {
    "src/mods/vr/DuoViewDelivery.hpp", "src/mods/vr/DuoViewGeometry.hpp", "src/mods/vr/DuoViewGaze.hpp",
    "src/mods/vr/DuoViewPSVR2Gaze.hpp", "src/mods/vr/DuoViewCropStability.hpp", "src/mods/vr/DuoViewFrame.hpp",
    "src/mods/vr/DuoViewConfig.hpp", "src/mods/vr/DuoViewState.hpp", "src/mods/vr/DuoViewD3D12.hpp",
    "src/mods/vr/DuoViewMonoCopyD3D12.hpp", "src/mods/vr/DuoViewShaderSource.hpp",
}
TRIVIEW_EDITED = {"src/mods/vr/RenderingMethodSetting.hpp"}
MODULE_FILES = ("TriViewGeometry.hpp", "TriViewD3D12.hpp")
TRIVIEW_ADDED = {"src/mods/vr/" + n for n in MODULE_FILES} | {"src/mods/vr/TriViewShaderSource.hpp"}
FRONTEND_EDITED = {"UEVR/RenderingModeOptions.cs", "tests/RenderingModes/Program.cs"}
FRONTEND_GENERATED = {"UEVR/FilteredExecutables.json"}

LABEL = "Tri-View (Experimental)"

BACKEND = {
 # ---- rendering method ID 7 ------------------------------------------------------------------
 "src/mods/vr/MonoRenderingPolicy.hpp": [
  ('inline constexpr int32_t duoview_method_id = 6;\n',
   'inline constexpr int32_t duoview_method_id = 6;\n'
   '// Tri-View Stage 1: Native Stereo + Native Fix + one centre periphery view (not a Mono-family method).\n'
   'inline constexpr int32_t triview_method_id = 7;\n'),
  ('    Choice{duoview_method_id, "DuoView Mono (Eye Tracked - Experimental)"},\n};',
   '    Choice{duoview_method_id, "DuoView Mono (Eye Tracked - Experimental)"},\n'
   '    Choice{triview_method_id, "' + LABEL + '"},\n};'),
  ('non_dibr_choices {choices[0], choices[1], choices[2], choices[5], choices[6]};',
   'non_dibr_choices {choices[0], choices[1], choices[2], choices[5], choices[6], choices[7]};'),
 ],
 "src/mods/vr/RenderingMethodSetting.hpp": [
  ('    int32_t value() const { return m_selection.active(); }',
   '    // Tri-View (ID 7) runs every existing Native Stereo (ID 0) code path unchanged;\n'
   '    // Tri-View code checks the raw ID through selection().active().\n'
   '    int32_t value() const {\n'
   '        const auto active = m_selection.active();\n'
   '        return active == uevr::mono::triview_method_id ? 0 : active;\n'
   '    }'),
 ],
 "tests/MonoRenderingTests.hpp": [
  ('    for (int id = 0; id != 7; ++id) {', '    for (int id = 0; id != 8; ++id) {'),
  ('(id < 3 || id == 5 || id == 6),', '(id < 3 || id == 5 || id == 6 || id == 7),'),
  ('    expect(!m::available(-1) && !m::available(7), "unsupported IDs are identified, never clamped into Mono");',
   '    expect(!m::available(-1) && !m::available(8), "unsupported IDs are identified, never clamped into Mono");\n'
   '    expect(m::triview_method_id == 7 && !m::is_mono_family(m::triview_method_id),\n'
   '        "Tri-View keeps serialized ID 7 and never enters the Mono lifecycle");'),
 ],
 # ---- VR state, settings and mode predicates ---------------------------------------------------
 "src/mods/VR.hpp": [
  ('#include "vr/DuoViewState.hpp"\n#include "vr/DuoViewPSVR2Gaze.hpp"',
   '#include "vr/DuoViewState.hpp"\n#include "vr/DuoViewPSVR2Gaze.hpp"\n#include "vr/TriViewGeometry.hpp"'),
  ('        if (is_duoview_renderer_active()) { return true; }\n\n        return m_native_stereo_fix->value() &&',
   '        if (is_duoview_renderer_active()) { return true; }\n'
   '        if (is_triview_active()) { return true; } // Tri-View ID7 forces Native Fix on\n\n'
   '        return m_native_stereo_fix->value() &&'),
  ('    bool is_duoview_renderer_active() const;\n',
   '    bool is_duoview_renderer_active() const;\n'
   '    // Tri-View Stage 1 (ID 7): Native Stereo + Native Fix + one centre periphery view.\n'
   '    bool is_triview_selected() const {\n'
   '        return m_rendering_method->selection().active() == uevr::mono::triview_method_id;\n'
   '    }\n'
   '    bool is_triview_active() const;\n'
   '    bool triview_third_view_enabled() const { return m_triview_third_view->value(); }\n'
   '    bool triview_debug_border() const { return m_triview_border->value(); }\n'
   '    int triview_flag_offset() const { return static_cast<int>(std::lround(m_triview_flag_offset->value())); }\n'
   '    std::optional<uevr::triview::Layout> triview_layout();\n'
   '    void triview_note_eye_pose(int32_t index, const double* rotation, const double* position);\n'
   '    bool triview_centre_pose(double* rotation, double* position) const;\n'
   '    void note_triview_views_demanded() { m_triview_owns_index_two.store(true, std::memory_order_release); }\n'
   '    void clear_triview_views_demanded() { m_triview_owns_index_two.store(false, std::memory_order_release); }\n'
   '    // View index 2 is ours while Tri-View is active, and for the frames still carrying a third view\n'
   '    // that Tri-View demanded. The latch is dropped by the first GetDesiredNumberOfViews call that no\n'
   '    // longer demands it, and is ignored once another rendering method is selected.\n'
   '    bool triview_owns_view_index_two() const {\n'
   '        return is_triview_active() ||\n'
   '            (is_triview_selected() && m_triview_owns_index_two.load(std::memory_order_acquire));\n'
   '    }\n'
   '    std::atomic<uint64_t> m_triview_third_renders{}, m_triview_pair_only{};\n'
   '    std::atomic<uint64_t> m_triview_composites{}, m_triview_composite_rejects{};\n'),
  ('    std::once_flag m_duoview_settings_once;\n',
   '    std::once_flag m_duoview_settings_once;\n'
   '    const ModToggle::Ptr m_triview_third_view{ModToggle::create(generate_name("TriViewThirdView"), true)};\n'
   '    const ModSlider::Ptr m_triview_periphery_scale{ModSlider::create(generate_name("TriViewPeripheryScale"), .25f, 1.f, .5f)};\n'
   '    const ModToggle::Ptr m_triview_border{ModToggle::create(generate_name("TriViewDebugBorder"), false)};\n'
   '    const ModSlider::Ptr m_triview_flag_offset{ModSlider::create(generate_name("TriViewFlagOffset"), -1.f, 300.f, 200.f)};\n'
   '    std::atomic<bool> m_triview_owns_index_two{false};\n'
   '    std::array<std::array<double, 6>, 2> m_triview_eye_pose{}; // game thread only\n'
   '    std::array<bool, 2> m_triview_eye_seen{};\n'),
  ('            *m_duo_sharp_periphery,',
   '            *m_duo_sharp_periphery,\n'
   '            *m_triview_third_view, *m_triview_periphery_scale, *m_triview_border, *m_triview_flag_offset,'),
 ],
 "src/mods/VR.cpp": [
  ('bool VR::should_force_native_stereo_fix_same_pass() const {\n    if (is_duoview_renderer_active()) {',
   'bool VR::should_force_native_stereo_fix_same_pass() const {\n'
   '    if (is_triview_active()) {\n'
   '        // Tri-View forces Native Fix on: keep Joey\'s validated STALKER 2 same-pass layout.\n'
   '        return stalker2_native_fix_requires_same_pass_cached();\n'
   '    }\n'
   '    if (is_duoview_renderer_active()) {'),
  ('    if (is_duoview_renderer_active()) { return false; }\n    if (!m_stalker2_native_pair_experiment->value()',
   '    if (is_duoview_renderer_active()) { return false; }\n'
   '    if (is_triview_active()) { return false; } // Tri-View composes from the generic Native Fix packet\n'
   '    if (!m_stalker2_native_pair_experiment->value()'),
  ('        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {',
   '        if (is_triview_selected()) {\n'
   '            if (ImGui::TreeNode("Tri-View (Stage 1) - settings and status")) {\n'
   '                ImGui::TextWrapped(is_triview_active()\n'
   '                    ? "Tri-View active: both eyes render their centre half (Native Fix), plus one low-res full-view periphery from the centre camera."\n'
   '                    : "Tri-View inactive (needs STALKER 2, D3D12, OpenXR, no AFR / 2D screen): rendering plain Native Stereo.");\n'
   '                m_triview_third_view->draw("Third view (periphery). OFF = cropped stereo windows only");\n'
   '                m_triview_periphery_scale->draw("Periphery resolution scale");\n'
   '                m_triview_border->draw("Fovea border highlight");\n'
   '                m_triview_flag_offset->draw("Experimental: engine flag byte offset (-1 = leave untouched)");\n'
   '                if (const auto layout = triview_layout()) {\n'
   '                    ImGui::Text("Fovea %ux%u per eye, periphery %ux%u", layout->fovea_width, layout->fovea_height,\n'
   '                        layout->periphery_width, layout->periphery_height);\n'
   '                }\n'
   '                ImGui::Text("Engine frames: %llu with third view, %llu eyes only",\n'
   '                    static_cast<unsigned long long>(m_triview_third_renders.load()),\n'
   '                    static_cast<unsigned long long>(m_triview_pair_only.load()));\n'
   '                ImGui::Text("Composited frames: %llu, rejected (Joey copy shown): %llu",\n'
   '                    static_cast<unsigned long long>(m_triview_composites.load()),\n'
   '                    static_cast<unsigned long long>(m_triview_composite_rejects.load()));\n'
   '                const auto q0 = glm::normalize(glm::quat{get_eye_transform(0)});\n'
   '                const auto q1 = glm::normalize(glm::quat{get_eye_transform(1)});\n'
   '                const float cant = glm::degrees(2.f * std::acos(std::clamp(std::abs(glm::dot(q0, q1)), 0.f, 1.f)));\n'
   '                ImGui::Text("Measured eye cant: %.2f deg (Stage 1 assumes parallel eyes)", cant);\n'
   '                ImGui::TreePop();\n'
   '            }\n'
   '        }\n'
   '        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {'),
 ],
 # ---- packet carries the per-frame layout ------------------------------------------------------
 "src/mods/vr/FFakeStereoRenderingHook.hpp": [
  ('#include "Stalker2NativePolicy.hpp"\n#include "DuoViewState.hpp"',
   '#include "Stalker2NativePolicy.hpp"\n#include "DuoViewState.hpp"\n#include "TriViewGeometry.hpp"'),
  ('        bool duoview_pose_valid{};',
   '        bool duoview_pose_valid{};\n'
   '        uevr::triview::PacketLayout triview{}; // Tri-View ID7: layout + whether view 2 was rendered'),
 ],
 # ---- engine side: view count, index-2 hooks, third render -------------------------------------
 "src/mods/vr/FFakeStereoRenderingHook.cpp": [
  # GetDesiredNumberOfViews: third engine view (only after all Native Fix readiness checks).
  ('        SPDLOG_INFO_EVERY_N_SEC(2, "[Avowed][NativeStereoFix] Returning two views for native stereo fix");\n'
   '    }\n\n    return 2;\n}',
   '        SPDLOG_INFO_EVERY_N_SEC(2, "[Avowed][NativeStereoFix] Returning two views for native stereo fix");\n'
   '    }\n\n'
   '    if (vr->is_triview_active() && vr->is_hmd_active() && vr->is_native_stereo_fix_enabled() &&\n'
   '        vr->triview_third_view_enabled() && g_hook->m_has_double_precision && vr->triview_layout().has_value()) {\n'
   '        // Tri-View: view 2 = centre periphery, built by the engine exactly like the two eyes.\n'
   '        vr->note_triview_views_demanded();\n'
   '        return 3;\n'
   '    }\n\n'
   '    if (!vr->is_triview_active()) { vr->clear_triview_views_demanded(); }\n\n'
   '    return 2;\n}'),
  # adjust_view_rect: index 2 before the legacy one-based heuristic.
  ('    if (!g_framework->is_game_data_intialized()) {\n        return;\n    }\n\n'
   '    static bool index_starts_from_one = true;\n    const bool medium_one_based_eye_pass = medium_is_current_game();',
   '    if (!g_framework->is_game_data_intialized()) {\n        return;\n    }\n\n'
   '    // Tri-View: index 2 is the centre periphery, placed in the free right half of the main\n'
   '    // target. Handled before the legacy "index 2 means one-based eyes" heuristic below.\n'
   '    if (index == 2 && VR::get()->triview_owns_view_index_two()) {\n'
   '        const auto layout = VR::get()->triview_layout();\n'
   '        *x = static_cast<int>(VR::get()->get_hmd_width());\n'
   '        *y = 0;\n'
   '        *w = layout ? layout->periphery_width : VR::get()->get_hmd_width() / 2;\n'
   '        *h = layout ? layout->periphery_height : VR::get()->get_hmd_height() / 2;\n'
   '        return;\n'
   '    }\n\n'
   '    static bool index_starts_from_one = true;\n    const bool medium_one_based_eye_pass = medium_is_current_game();'),
  # adjust_view_rect: eyes 0/1 = fovea at (0,0) of their Native Fix targets.
  ('    if (VR::get()->is_duoview_renderer_active() && g_hook->m_has_double_precision &&\n        (index == 0 || index == 1)) {',
   '    if (VR::get()->is_triview_active() && (index == 0 || index == 1)) {\n'
   '        if (const auto layout = VR::get()->triview_layout()) {\n'
   '            *x = 0;\n'
   '            *y = 0;\n'
   '            *w = layout->fovea_width;\n'
   '            *h = layout->fovea_height;\n'
   '            return;\n'
   '        }\n'
   '    }\n'
   '    if (VR::get()->is_duoview_renderer_active() && g_hook->m_has_double_precision &&\n        (index == 0 || index == 1)) {'),
  # calculate_stereo_view_offset: index 2 = centre camera, before the legacy statics and Lua callbacks.
  ('    auto vr = VR::get();\n    if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 1) {',
   '    auto vr = VR::get();\n'
   '    if (view_index == 2 && vr->triview_owns_view_index_two()) {\n'
   '        // Tri-View centre camera: midpoint of the two eye poses computed above for this frame,\n'
   '        // left-eye rotation. Never reaches the legacy index-2 heuristics below.\n'
   '        double rotation[3]{}, position[3]{};\n'
   '        if (g_hook->m_has_double_precision && vr->triview_centre_pose(rotation, position)) {\n'
   '            auto* rot = reinterpret_cast<Rotator<double>*>(view_rotation);\n'
   '            auto* pos = reinterpret_cast<Vector3d*>(view_location);\n'
   '            rot->pitch = rotation[0]; rot->yaw = rotation[1]; rot->roll = rotation[2];\n'
   '            pos->x = position[0]; pos->y = position[1]; pos->z = position[2];\n'
   '        }\n'
   '        return;\n'
   '    }\n'
   '    if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 1) {'),
  # calculate_stereo_view_offset: remember the final eye poses (after Joey's math and Lua mods).
  ('        if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 0) {',
   '        if (vr->is_triview_active() && has_double_precision && (view_index == 0 || view_index == 1)) {\n'
   '            const double rotation[3]{rot_d->pitch, rot_d->yaw, rot_d->roll};\n'
   '            const double position[3]{view_d->x, view_d->y, view_d->z};\n'
   '            vr->triview_note_eye_pose(view_index, rotation, position);\n'
   '        }\n'
   '        if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 0) {'),
  # projection: index 2 = union frustum, before the legacy statics.
  ('    static bool index_starts_from_one = true;\n    static bool index_was_ever_two = false;\n\n'
   '    const bool medium_one_based_projection_pass = medium_is_current_game();',
   '    // Tri-View: index 2 = centre periphery, the left-eye projection widened to the union of\n'
   '    // both eye frusta. Handled before the legacy index-2 heuristics below.\n'
   '    if (view_index == 2 && out != nullptr && vr->triview_owns_view_index_two()) {\n'
   '        if (g_hook->m_has_double_precision) {\n'
   '            auto& matrix = *(Matrix4x4d*)out;\n'
   '            matrix = vr->get_projection_matrix(VRRuntime::Eye::LEFT);\n'
   '            if (const auto layout = vr->triview_layout()) {\n'
   '                uevr::triview::apply_periphery_projection(matrix, *layout);\n'
   '            }\n'
   '        } else {\n'
   '            *out = vr->get_projection_matrix(VRRuntime::Eye::LEFT);\n'
   '        }\n'
   '        return out;\n'
   '    }\n\n'
   '    static bool index_starts_from_one = true;\n    static bool index_was_ever_two = false;\n\n'
   '    const bool medium_one_based_projection_pass = medium_is_current_game();'),
  # projection: eyes 0/1 cropped to the fixed centre fovea window.
  ('            double_matrix = fmat;\n        }\n        if (duo_fovea || duo_full) {',
   '            double_matrix = fmat;\n        }\n'
   '        if (vr->is_triview_active() && g_hook->m_has_double_precision && (view_index == 0 || view_index == 1)) {\n'
   '            if (const auto layout = vr->triview_layout()) {\n'
   '                uevr::triview::apply_fovea_projection(double_matrix, *layout);\n'
   '            }\n'
   '        }\n'
   '        if (duo_fovea || duo_full) {'),
  # BeginRenderingViewFamily: hide view 2 from every existing Native Fix path.
  ('    if (view_family == nullptr) {\n        call_original();\n        return;\n    }\n\n'
   '    using SceneViewsArrayPtr = decltype(view_family->get_views());',
   '    if (view_family == nullptr) {\n        call_original();\n        return;\n    }\n\n'
   '    // Tri-View ID7: the engine built a third (centre periphery) view. Hide it so Joey\'s proven\n'
   '    // pair logic below sees exactly its two eyes. It is rendered once after the validated\n'
   '    // secondary render; the engine\'s view count is restored on every exit.\n'
   '    sdk::FSceneView* triview_third_view{};\n'
   '    sdk::FSceneViewFamily* triview_family{};\n'
   '    bool triview_rendered{};\n'
   '    utility::ScopeGuard triview_restore_count{[&]() {\n'
   '        if (triview_family != nullptr) { triview_family->get_views()->count = 3; }\n'
   '    }};\n'
   '    if (native_stereo_fix_enabled) {\n'
   '        const auto triview_main_target = rtm != nullptr ? rtm->get_view_family_render_target() : nullptr;\n'
   '        for (const auto family : view_families) {\n'
   '            if (family == nullptr || triview_main_target == nullptr ||\n'
   '                family->get_render_target() != triview_main_target) { continue; }\n'
   '            auto* const family_views = family->get_views();\n'
   '            if (family_views == nullptr ||\n'
   '                !is_readable_process_range(reinterpret_cast<uintptr_t>(family_views), sizeof(*family_views)) ||\n'
   '                family_views->count != 3) { continue; }\n'
   '            // Fail closed: a Native Fix main family with three views is ALWAYS cut back to Joey\'s two\n'
   '            // eyes (count restored on exit), even when the third view cannot be identified or Tri-View\n'
   '            // was just switched off; then the third view is simply not rendered.\n'
   '            if (family_views->capacity >= 3 && family_views->data != nullptr &&\n'
   '                is_readable_process_range(reinterpret_cast<uintptr_t>(family_views->data), sizeof(void*) * 3)) {\n'
   '                auto* const third = family_views->data[2];\n'
   '                if (third != nullptr && third != family_views->data[0] && third != family_views->data[1]) {\n'
   '                    triview_third_view = third;\n'
   '                }\n'
   '            }\n'
   '            triview_family = family;\n'
   '            family_views->count = 2;\n'
   '            break;\n'
   '        }\n'
   '    }\n\n'
   '    using SceneViewsArrayPtr = decltype(view_family->get_views());'),
  # Third render: exactly like Joey's secondary, into the free right half of the main target.
  ('            render_secondary_view();\n        }\n    }\n    stalker_secondary_frame = stalker_family_frame();',
   '            render_secondary_view();\n        }\n    }\n'
   '    if (triview_third_view != nullptr && triview_family == view_family && vr->is_triview_active()) {\n'
   '        // Tri-View: render the hidden centre view exactly like the secondary above (frame-count\n'
   '        // decrement, singleton family), into the main target where adjust_view_rect placed it\n'
   '        // (x = W, the half Native Fix leaves unused). Joey\'s restore guard puts views/target back.\n'
   '        // UE may clear the whole family target before the first view of a family unless the family\n'
   '        // is marked additional (bAdditionalViewFamily), which would erase the left fovea already in\n'
   '        // this target. Headset log (UE 5.5.4, FrameNumber at +0xAC): the byte guessed from Joey\'s\n'
   '        // UE5.7 layout (FrameCounter + 8 = +0xB8) reads 4, so that guess is WRONG and is never\n'
   '        // written. Joey\'s NASCAR25 table (UE 5.5.4, "independently checked against the runtime image\n'
   '        // and source", NascarHookCompatibility.hpp layout25) puts family_additional_offset at +0xC8\n'
   '        // (family size 0x1B0); his UE5.6.1 table says +0xB0. Default = 0xC8 (200), set to 1 for this\n'
   '        // render only, restored afterwards, and only if the byte currently reads 0. The menu can name\n'
   '        // another absolute offset, or -1 to leave every byte untouched. A hex dump of the bytes around\n'
   '        // FrameNumber is logged once so the real layout can be checked against the log.\n'
   '        static bool triview_skip_decrement{}, triview_disabled{}, triview_last_rendered{}, triview_dumped{};\n'
   '        static uint32_t triview_last_frame{};\n'
   '        const size_t frame_offset = SceneViewExtensionAnalyzer::frame_count_offset;\n'
   '        const size_t dump_from = frame_offset >= 0x10 ? frame_offset - 0x10 : 0;\n'
   '        constexpr size_t dump_length = 0x90;\n'
   '        auto* const family_bytes = reinterpret_cast<uint8_t*>(view_family);\n'
   '        uint32_t frame_before{};\n'
   '        const bool layout_readable = frame_offset >= 0x10 && frame_offset < 0x1000 &&\n'
   '            is_writable_process_range(reinterpret_cast<uintptr_t>(family_bytes) + dump_from, dump_length);\n'
   '        if (layout_readable && !triview_dumped) {\n'
   '            triview_dumped = true;\n'
   '            for (size_t row = 0; row < dump_length; row += 16) {\n'
   '                char text[64]{};\n'
   '                for (size_t i = 0; i < 16; ++i) {\n'
   '                    const uint8_t byte = family_bytes[dump_from + row + i];\n'
   '                    text[i * 3] = "0123456789abcdef"[byte >> 4];\n'
   '                    text[i * 3 + 1] = "0123456789abcdef"[byte & 15];\n'
   '                    text[i * 3 + 2] = \' \';\n'
   '                }\n'
   '                SPDLOG_INFO("[TriView] family +0x{:x}: {}", dump_from + row, text);\n'
   '            }\n'
   '        }\n'
   '        if (layout_readable) {\n'
   '            std::memcpy(&frame_before, family_bytes + frame_offset, sizeof(frame_before));\n'
   '            // The eyes\' frame number must advance every frame. If it stalls after a frame with a third\n'
   '            // render, the engine did not undo our decrement (an additional family may not advance the\n'
   '            // scene frame): drop the decrement (one repeated frame number, once); if it still stalls, stop.\n'
   '            if (triview_last_rendered && frame_before == triview_last_frame) {\n'
   '                if (!triview_skip_decrement) {\n'
   '                    triview_skip_decrement = true;\n'
   '                    SPDLOG_INFO("[TriView] Frame number stalled after a third render; no decrement from now on");\n'
   '                } else if (!triview_disabled) {\n'
   '                    triview_disabled = true;\n'
   '                    SPDLOG_ERROR("[TriView] Frame number still stalls without decrement; third view disabled");\n'
   '                }\n'
   '            }\n'
   '            triview_last_frame = frame_before;\n'
   '            triview_last_rendered = false;\n'
   '        }\n'
   '        const int flag_choice = vr->triview_flag_offset();\n'
   '        const bool use_flag = flag_choice >= 0;\n'
   '        const size_t flag_offset = use_flag ? static_cast<size_t>(flag_choice) : 0;\n'
   '        const bool flag_ok = !use_flag || (layout_readable && flag_offset >= dump_from &&\n'
   '            flag_offset < dump_from + dump_length && family_bytes[flag_offset] == 0);\n'
   '        if (!layout_readable || !flag_ok || triview_disabled) {\n'
   '            SPDLOG_WARNING_EVERY_N_SEC(2, "[TriView] Third view skipped (readable={} flag_offset={} flag_ok={} disabled={})",\n'
   '                layout_readable, flag_choice, flag_ok, triview_disabled);\n'
   '        } else {\n'
   '            SPDLOG_INFO_ONCE("[TriView] Rendering the centre periphery view: FrameNumber +0x{:x}={} additional-flag offset {} (-1 = untouched)",\n'
   '                frame_offset, frame_before, flag_choice);\n'
   '            const uint8_t flag_original = use_flag ? family_bytes[flag_offset] : 0;\n'
   '            if (use_flag) { family_bytes[flag_offset] = 1; }\n'
   '            utility::ScopeGuard restore_additional{[&]() { if (use_flag) { family_bytes[flag_offset] = flag_original; } }};\n'
   '            view_family->set_render_target(original_target);\n'
   '            views.data[0] = triview_third_view;\n'
   '            views.count = 1;\n'
   '            if (auto* scene = reinterpret_cast<sdk::FScene*>(view_family_scene); scene != nullptr && !triview_skip_decrement) {\n'
   '                scene->decrement_frame_count();\n'
   '            }\n'
   '            render_secondary_view();\n'
   '            triview_rendered = true;\n'
   '            triview_last_rendered = true;\n'
   '        }\n'
   '    }\n'
   '    stalker_secondary_frame = stalker_family_frame();'),
  ('        if (!duo_packet_frame) {\n            packet->engine_frame = g_frame_count;\n'
   '            packet->render_frame = vr->m_render_frame_count;\n        }\n',
   '        if (!duo_packet_frame) {\n            packet->engine_frame = g_frame_count;\n'
   '            packet->render_frame = vr->m_render_frame_count;\n        }\n'
   '        if (vr->is_triview_active()) {\n'
   '            if (const auto layout = vr->triview_layout()) {\n'
   '                packet->triview = uevr::triview::PacketLayout{*layout, true, triview_rendered};\n'
   '                (triview_rendered ? vr->m_triview_third_renders : vr->m_triview_pair_only)\n'
   '                    .fetch_add(1, std::memory_order_relaxed);\n'
   '            }\n'
   '        }\n'),
 ],
 # ---- D3D12: compose instead of Joey's copy, only while ID 7 is active ----------------------------
 # v207 source-contract test counts D3D12 consume sites (4 -> 5: the Tri-View compositor is the new one).
 "tests/CadenceReplayTests.cpp": [
  ('copies == (std::string(backend) == "D3D11" ? 2 : 4) &&',
   'copies == (std::string(backend) == "D3D11" ? 2 : 5) &&'),
 ],
 "src/mods/vr/D3D12Component.hpp": [
  ('#include "d3d12/TextureContext.hpp"\n#include "DuoViewD3D12.hpp"',
   '#include "d3d12/TextureContext.hpp"\n#include "DuoViewD3D12.hpp"\n#include "TriViewD3D12.hpp"'),
  ('        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;',
   '        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;\n'
   '        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::triview::dx12::Compositor>> triview_compositors;'),
  ('    uint32_t m_scene_capture_height{};\n',
   '    uint32_t m_scene_capture_height{};\n'
   '    uevr::triview::PacketLayout m_triview_last{}; // Tri-View: layout of the last composed packet\n'),
 ],
 "src/mods/vr/D3D12Component.cpp": [
  ('    vr->get_openxr_runtime()->invalidate_duoview_scene();\n    this->duoview_compositors.clear();\n',
   '    vr->get_openxr_runtime()->invalidate_duoview_scene();\n    this->duoview_compositors.clear();\n'
   '    this->triview_compositors.clear();\n'),
  ('    this->duoview_compositors.clear();\n    this->contexts.clear();\n',
   '    this->duoview_compositors.clear();\n    this->triview_compositors.clear();\n    this->contexts.clear();\n'),
  ('                    } else if (stalker_exact) {\n                        copy_stalker_pair();\n'
   '                    } else if (native_stereo_packet == nullptr ||',
   '                    } else if (stalker_exact) {\n                        copy_stalker_pair();\n'
   '                    } else if (vr->is_triview_active() && m_game_tex.texture.Get() != nullptr &&\n'
   '                               m_scene_capture_tex.texture.Get() != nullptr &&\n'
   '                               (native_stereo_packet != nullptr ? native_stereo_packet->triview.valid : m_triview_last.valid)) {\n'
   '                        // Tri-View ID7: each eye = periphery underneath + own fovea on top, instead of\n'
   '                        // Joey\'s plain copy. A Present without a new engine packet recomposes the last\n'
   '                        // layout from the same two targets. Pose and submission stay Native Stereo.\n'
   '                        if (native_stereo_packet != nullptr) { m_triview_last = native_stereo_packet->triview; }\n'
   '                        const auto triview_frame = m_triview_last;\n'
   '                        bool triview_composed = false;\n'
   '                        m_openxr.copy((uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, nullptr,\n'
   '                            [&](d3d12::CommandContext& commands, ID3D12Resource* destination) {\n'
   '                                if (!commands.ready() || destination == nullptr) { return; }\n'
   '                                auto& slot = m_openxr.triview_compositors[&commands];\n'
   '                                if (!slot) { slot = std::make_unique<uevr::triview::dx12::Compositor>(); }\n'
   '                                triview_composed = slot->record(device, commands.cmd_list.Get(),\n'
   '                                    m_game_tex.texture.Get(), m_scene_capture_tex.texture.Get(), destination,\n'
   '                                    triview_frame, vr->triview_debug_border());\n'
   '                                if (triview_composed) {\n'
   '                                    commands.has_commands = true;\n'
   '                                    if (native_stereo_packet != nullptr && native_stereo_hook != nullptr) {\n'
   '                                        if (native_frame_ticket) {\n'
   '                                            native_stereo_hook->record_native_frame_stage(*native_stereo_packet, native_frame_ticket,\n'
   '                                                frame_diag::Backend::d3d12, frame_diag::Runtime::openxr, frame_diag::Stage::copy_recorded,\n'
   '                                                0, 2, 0, m_scene_capture_tex.texture.Get(), destination);\n'
   '                                        }\n'
   '                                        native_stereo_hook->note_native_stereo_frame_packet_consumed(native_stereo_packet->serial);\n'
   '                                    }\n'
   '                                } else {\n'
   '                                    SPDLOG_WARNING_EVERY_N_SEC(2, "[TriView] Composite rejected ({}); showing Joey\'s copy", slot->error());\n'
   '                                    pre_render(commands, destination);\n'
   '                                }\n'
   '                            }, std::nullopt, D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr);\n'
   '                        (triview_composed ? vr->m_triview_composites : vr->m_triview_composite_rejects)\n'
   '                            .fetch_add(1, std::memory_order_relaxed);\n'
   '                    } else if (native_stereo_packet == nullptr ||'),
 ],
}
# VR.cpp implementations, appended like DuoView's configure_duoview().
VR_CPP_APPEND = '''
// Tri-View Stage 1 (rendering method ID 7). STALKER 2 + D3D12 + OpenXR, same gate as DuoView ID6.
bool VR::is_triview_active() const {
    if (!is_triview_selected() || !m_is_d3d12 || is_using_afr() || is_using_2d_screen()) return false;
    const auto runtime = get_runtime();
    if (!runtime || !runtime->is_openxr()) return false;
    static const bool stalker2 = [] {
        const auto path = utility::get_module_pathw(utility::get_executable());
        return path && uevr::stalker2_native::is_executable(*path);
    }();
    return stalker2;
}

// Pure function of the current eye projections, HMD render size and the periphery setting.
std::optional<uevr::triview::Layout> VR::triview_layout() {
    if (!get_runtime()) return {};
    const auto left = uevr::triview::tans_from_projection(get_projection_matrix(VRRuntime::Eye::LEFT));
    const auto right = uevr::triview::tans_from_projection(get_projection_matrix(VRRuntime::Eye::RIGHT));
    if (!left || !right) return {};
    return uevr::triview::make_layout(get_hmd_width(), get_hmd_height(), *left, *right,
        m_triview_periphery_scale->value());
}

void VR::triview_note_eye_pose(int32_t index, const double* rotation, const double* position) {
    if (index != 0 && index != 1) return;
    // UE builds eye 0, then eye 1, then the centre view in one pass: eye 0 invalidates last frame's
    // eye 1, so the centre camera can only be built from poses noted in the same frame.
    if (index == 0) { m_triview_eye_seen[1] = false; }
    auto& pose = m_triview_eye_pose[index];
    for (int i = 0; i < 3; ++i) { pose[i] = rotation[i]; pose[3 + i] = position[i]; }
    m_triview_eye_seen[index] = true;
}

// UE builds view 2 right after views 0 and 1 in the same Draw, so these are this frame's eyes.
bool VR::triview_centre_pose(double* rotation, double* position) const {
    if (!m_triview_eye_seen[0] || !m_triview_eye_seen[1]) return false;
    for (int i = 0; i < 3; ++i) {
        rotation[i] = m_triview_eye_pose[0][i];
        position[i] = (m_triview_eye_pose[0][3 + i] + m_triview_eye_pose[1][3 + i]) * 0.5;
    }
    return true;
}
'''

FRONTEND = {
 "UEVR/RenderingModeOptions.cs": [
  ('        public const int DuoViewMono = 6;',
   '        public const int DuoViewMono = 6;\n        public const int TriView = 7;'),
  ('            result.Add(DuoViewMono.ToString(), "DuoView Mono (Eye Tracked - Experimental)");',
   '            result.Add(DuoViewMono.ToString(), "DuoView Mono (Eye Tracked - Experimental)");\n'
   '            result.Add(TriView.ToString(), "' + LABEL + '");'),
 ],
 "tests/RenderingModes/Program.cs": [
  ('for (int id = 0; id <= 6; ++id) {', 'for (int id = 0; id <= 7; ++id) {'),
  ('bool supported = id < 3 || id == 5 || id == 6 || dibr;',
   'bool supported = id < 3 || id == 5 || id == 6 || id == 7 || dibr;'),
  ('"4", "5", "6", "99", "-1"', '"4", "5", "6", "7", "99", "-1"'),
  ('    if (choices.ContainsKey("99")) {',
   '    if (choices["7"] != "' + LABEL + '") {\n'
   '        throw new Exception("Tri-View must keep serialized ID 7");\n'
   '    }\n'
   '    if (choices.ContainsKey("99")) {'),
 ],
}


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_edits(root, file_map):
    for rel, edits in file_map.items():
        path = root / rel
        text = path.read_text(encoding="utf-8-sig")
        for before, after in edits:
            count = text.count(before)
            if count != 1:
                raise RuntimeError(f"{rel}: expected one anchor, found {count}: {before[:110]!r}")
            text = text.replace(before, after, 1)
        path.write_text(text, encoding="utf-8", newline="")


def tracked_state(root):
    changed = set(git(root, "diff", "--name-only", "HEAD").splitlines())
    added = set(git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    return changed, added


def apply(args):
    backend, frontend, duoview, evidence = map(Path, args.paths)
    evidence.mkdir(parents=True, exist_ok=True)
    if git(backend, "rev-parse", "HEAD") != "5ac7edc207866569334175e4ed8a7517971547f6":
        raise RuntimeError("Unexpected Joey backend revision")
    if git(frontend, "rev-parse", "HEAD") != "60be4b0f9a646109fd9fdf448bacd41477234091":
        raise RuntimeError("Unexpected Joey frontend revision")
    changed, added = tracked_state(backend)
    if changed != V207_EDITED or added != V207_ADDED:
        raise RuntimeError(f"Backend is not the exact v207 state: {sorted((changed ^ V207_EDITED) | (added ^ V207_ADDED))}")

    vr = backend / "src/mods/vr"
    for name in MODULE_FILES + ("TriViewShaderSource.hpp",):
        if (vr / name).exists():
            raise RuntimeError(f"Refusing to overwrite {vr / name}")
    for name in MODULE_FILES:
        (vr / name).write_bytes((duoview / "triview" / name).read_bytes())
    subprocess.run([sys.executable, str(duoview / "triview" / "embed_triview_shader.py"),
                    str(vr / "TriViewShaderSource.hpp")], check=True)

    apply_edits(backend, BACKEND)
    cpp = backend / "src/mods/VR.cpp"
    cpp.write_text(cpp.read_text(encoding="utf-8") + VR_CPP_APPEND, encoding="utf-8", newline="")
    apply_edits(frontend, FRONTEND)

    changed, added = tracked_state(backend)
    expected_changed = V207_EDITED | TRIVIEW_EDITED
    expected_added = V207_ADDED | TRIVIEW_ADDED
    if changed != expected_changed or added != expected_added:
        raise RuntimeError(f"Unexpected backend paths: {sorted((changed ^ expected_changed) | (added ^ expected_added))}")
    fchanged, fadded = tracked_state(frontend)
    if fchanged - (FRONTEND_EDITED | FRONTEND_GENERATED) or not FRONTEND_EDITED <= fchanged or fadded:
        raise RuntimeError(f"Unexpected frontend paths: {sorted(fchanged | fadded)}")

    hashes = {"backend": {p: sha(backend / p) for p in sorted(expected_changed | expected_added)},
              "frontend": {p: sha(frontend / p) for p in sorted(FRONTEND_EDITED)}}
    (evidence / "triview-stage1-hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print("Tri-View Stage 1 applied: rendering method ID 7 (Native Fix + centre periphery); modes 0-6 gated off.")


def verify(args):
    backend, evidence = map(Path, args.paths)
    recorded = json.loads((evidence / "triview-stage1-hashes.json").read_text(encoding="utf-8"))
    for rel, digest in recorded["backend"].items():
        if sha(backend / rel) != digest:
            raise RuntimeError(f"{rel} changed during the build")
    print(f"Tri-View Stage 1 source unchanged after build ({len(recorded['backend'])} backend files).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("paths", nargs="+")
    a = parser.parse_args()
    if a.verify:
        if len(a.paths) != 2:
            sys.exit("usage: apply_triview_stage1.py --verify BACKEND EVIDENCE")
        verify(a)
    else:
        if len(a.paths) != 4:
            sys.exit("usage: apply_triview_stage1.py BACKEND FRONTEND DUOVIEW_DIR EVIDENCE")
        apply(a)

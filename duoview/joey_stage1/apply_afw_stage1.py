#!/usr/bin/env python3
"""DuoView AFW Stage 1: add PureDark's Alternate Frame Warping as rendering method ID 7.

Run AFTER the complete v207 patch chain (apply_stage1 ... apply_v207_auto_fov_after_load and
verify_stage234). Every edit is an exact anchor that must occur once. Modes 0-6 keep their code
paths; every new branch is gated by ID 7 being selected (is_afw_selected / is_using_afw).

  apply:   apply_afw_stage1.py BACKEND FRONTEND DUOVIEW_DIR PDAFWPLUGIN_H EVIDENCE
  verify:  apply_afw_stage1.py --verify BACKEND EVIDENCE   (after the build: nothing changed)

Credits: AFW, PDAFWPlugin.dll and PDAFWPlugin.h by PureDark (github.com/PureDark/UEVR, branch AFW,
commit fc8de10), used non-commercially with permission. The header is fetched by CI, checked
against the pinned SHA-256 below and never committed or packaged. The DLL is never touched.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys

PD_HEADER_SHA256 = "4479a454137907a03433c1b8b0e75516e85ba6f3860f142d61a118d150135636"  # LF-normalised
PD_HEADER_DEST = "dependencies/pd-afwmod/include/PDAFWPlugin.h"
MODULE_FILES = ("DuoViewAFW.hpp", "DuoViewAFW.cpp")

# v207 state (verify_stage234.py) plus this stage.
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
AFW_EDITED = {"src/mods/UObjectHook.cpp", "CMakeLists.txt"}
AFW_ADDED = {"src/mods/vr/DuoViewAFW.hpp", "src/mods/vr/DuoViewAFW.cpp", PD_HEADER_DEST}
FRONTEND_EDITED = {"UEVR/RenderingModeOptions.cs", "tests/RenderingModes/Program.cs"}
FRONTEND_GENERATED = {"UEVR/FilteredExecutables.json"}

AFW_LABEL = "Alternate Frame Warping (PureDark AFW)"

BACKEND = {
 # ---- rendering method ID 7 -------------------------------------------------------------
 "src/mods/vr/MonoRenderingPolicy.hpp": [
  ('inline constexpr int32_t duoview_method_id = 6;\n',
   'inline constexpr int32_t duoview_method_id = 6;\n'
   '// DuoView AFW Stage 1: PureDark Alternate Frame Warping (not a Mono-family method).\n'
   'inline constexpr int32_t afw_method_id = 7;\n'),
  ('    Choice{duoview_method_id, "DuoView Mono (Eye Tracked - Experimental)"},\n};',
   '    Choice{duoview_method_id, "DuoView Mono (Eye Tracked - Experimental)"},\n'
   '    Choice{afw_method_id, "' + AFW_LABEL + '"},\n};'),
  ('non_dibr_choices {choices[0], choices[1], choices[2], choices[5], choices[6]};',
   'non_dibr_choices {choices[0], choices[1], choices[2], choices[5], choices[6], choices[7]};'),
 ],
 "tests/MonoRenderingTests.hpp": [
  ('    for (int id = 0; id != 7; ++id) {', '    for (int id = 0; id != 8; ++id) {'),
  ('(id < 3 || id == 5 || id == 6),', '(id < 3 || id == 5 || id == 6 || id == 7),'),
  ('    expect(!m::available(-1) && !m::available(7), "unsupported IDs are identified, never clamped into Mono");',
   '    expect(!m::available(-1) && !m::available(8), "unsupported IDs are identified, never clamped into Mono");\n'
   '    expect(m::afw_method_id == 7 && !m::is_mono_family(m::afw_method_id),\n'
   '        "AFW keeps serialized ID 7 and never enters the Mono lifecycle");'),
 ],
 # ---- VR state, settings and mode predicates ----------------------------------------------
 "src/mods/VR.hpp": [
  ('        DUOVIEW_MONO = uevr::mono::duoview_method_id,\n    };',
   '        DUOVIEW_MONO = uevr::mono::duoview_method_id,\n'
   '        ALTERNATE_FRAMEWARP = uevr::mono::afw_method_id,\n    };'),
  ('               m_rendering_method->value() == RenderingMethod::SYNCHRONIZED ||\n'
   '               m_extreme_compat_mode->value() == true;\n    }\n\n    bool is_using_native_stereo() const {',
   '               m_rendering_method->value() == RenderingMethod::SYNCHRONIZED ||\n'
   '               m_rendering_method->value() == RenderingMethod::ALTERNATE_FRAMEWARP ||\n'
   '               m_extreme_compat_mode->value() == true;\n    }\n\n    bool is_using_native_stereo() const {'),
  ('        return m_rendering_method->value() == RenderingMethod::SYNCHRONIZED ||\n'
   '               (m_extreme_compat_mode->value() && m_rendering_method->value() == RenderingMethod::NATIVE_STEREO);\n    }\n',
   '        return m_rendering_method->value() == RenderingMethod::SYNCHRONIZED ||\n'
   '               (m_extreme_compat_mode->value() && m_rendering_method->value() == RenderingMethod::NATIVE_STEREO) ||\n'
   '               // AFW warm-up / unavailable: render both eyes like Synchronized Sequential (PureDark).\n'
   '               (is_afw_selected() && !is_using_afw());\n    }\n'
   '\n'
   '    // DuoView AFW Stage 1: PureDark Alternate Frame Warping, rendering method ID 7 (vr/DuoViewAFW.cpp).\n'
   '    bool is_afw_selected() const {\n'
   '        return m_rendering_method->value() == RenderingMethod::ALTERNATE_FRAMEWARP;\n'
   '    }\n'
   '\n'
   '    bool is_using_afw() const {\n'
   '        return is_afw_selected() && afw_plugin_ready.load(std::memory_order_acquire) &&\n'
   '               afw_since_inject_frame_count.load(std::memory_order_relaxed) >= 90 &&\n'
   '               afw_switching_skip_frames.load(std::memory_order_relaxed) == 0 &&\n'
   '               afw_resolution_change_skip_frames.load(std::memory_order_relaxed) <= 0 &&\n'
   '               !is_using_2d_screen() && get_runtime() != nullptr && get_runtime()->is_openxr();\n'
   '    }\n'
   '\n'
   '    struct AfwSettings {\n'
   '        int mode;\n'
   '        int shading_rate;\n'
   '        bool clear_before_warping;\n'
   '        bool debug;\n'
   '        bool sharpening;\n'
   '        float sharpness;\n'
   '        bool fix_object_motion;\n'
   '        float fix_object_motion_range;\n'
   '        bool fix_flicker;\n'
   '        float ignore_motion_threshold;\n'
   '    };\n'
   '\n'
   '    AfwSettings get_afw_settings() const {\n'
   '        return AfwSettings{m_afw_mode->value(), m_afw_shading_rate->value(), m_afw_clear_before->value(),\n'
   '            m_afw_debug->value(), m_afw_sharpening->value(), m_afw_sharpness->value(), m_afw_fix_object_mv->value(),\n'
   '            m_afw_fix_object_mv_range->value(), m_afw_fix_flicker->value(), m_afw_ignore_motion_threshold->value()};\n'
   '    }\n'
   '\n'
   '    int get_render_frame_count() const { return m_render_frame_count; }\n'
   '    int get_left_eye_interval() const { return m_left_eye_interval; }\n'
   '    void afw_update_camera_data(int frame_count);\n'
   '    void afw_draw_ui();\n'
   '\n'
   '    // Written by the stereo hook for PureDark AFW camera data: [eye][history] view-to-world and projections.\n'
   '    struct AfwMatrixPair {\n'
   '        Matrix4x4f curr{1.0f};\n'
   '        Matrix4x4f other{1.0f};\n'
   '    };\n'
   '    AfwMatrixPair render_view_inv_matrix[2][3]{};\n'
   '    AfwMatrixPair render_projection_matrix[2]{};\n'
   '    int last_update_matrix_frame_count[2]{0, 0};\n'
   '    std::atomic_bool afw_plugin_ready{false};\n'
   '    std::atomic<int> afw_since_inject_frame_count{0};\n'
   '    std::atomic<int> afw_switching_skip_frames{0};\n'
   '    std::atomic<int> afw_resolution_change_skip_frames{0};\n'
   '    std::atomic<int> afw_last_dlss_frame{-1000};\n'
   '    bool afw_was_selected{false};\n'),
  ('        if (uevr::nascar::is_target()) { return false; }\n        return m_ghosting_fix->value();\n    }',
   '        if (uevr::nascar::is_target()) { return false; }\n'
   '        if (is_afw_selected()) { return true; } // PureDark AFW needs one view state per eye\n'
   '        return m_ghosting_fix->value();\n    }'),
  ('        std::make_unique<RenderingMethodSetting>(generate_name("RenderingMethod"), uevr::mono::choices)};\n',
   '        std::make_unique<RenderingMethodSetting>(generate_name("RenderingMethod"), uevr::mono::choices)};\n'
   '    // DuoView AFW Stage 1 settings (PureDark AFW beta 6 defaults).\n'
   '    static const inline std::vector<std::string> s_afw_mode_names{\n'
   '        "None", "AlternateEyeWarping", "PreviousFrameWarping", "CombinedWarping"};\n'
   '    static const inline std::vector<std::string> s_afw_shading_rate_names{\n'
   '        "1 X 1 (Full Resolution)", "1 X 2 (Full Width x Half Height)", "1 X 4 (Full Width x Quarter Height)",\n'
   '        "2 X 1 (Half Width x Full Height)", "2 X 2 (Half Width x Half Height)", "2 X 4 (Half Width x Quarter Height)",\n'
   '        "4 X 1 (Quarter Width x Full Height)", "4 X 2 (Quarter Width x Half Height)", "4 X 4 (Quarter Width x Quarter Height)"};\n'
   '    const ModCombo::Ptr m_afw_mode{ModCombo::create(generate_name("AFW_FramewarpMode"), s_afw_mode_names, 3)};\n'
   '    const ModCombo::Ptr m_afw_shading_rate{ModCombo::create(generate_name("AFW_ShadingRate"), s_afw_shading_rate_names, 0)};\n'
   '    const ModToggle::Ptr m_afw_clear_before{ModToggle::create(generate_name("AFW_ClearBeforeFramewarp"), false)};\n'
   '    const ModToggle::Ptr m_afw_debug{ModToggle::create(generate_name("AFW_FramewarpDebug"), false)};\n'
   '    const ModToggle::Ptr m_afw_sharpening{ModToggle::create(generate_name("AFW_EnableSharpening"), false)};\n'
   '    const ModSlider::Ptr m_afw_sharpness{ModSlider::create(generate_name("AFW_Sharpness"), 0.0f, 1.0f, 0.6f)};\n'
   '    const ModToggle::Ptr m_afw_fix_object_mv{ModToggle::create(generate_name("AFW_FixObjectMotionVector"), true)};\n'
   '    const ModSlider::Ptr m_afw_fix_object_mv_range{ModSlider::create(generate_name("AFW_FixObjectMotionRange"), 0.0f, 10.0f, 3.0f)};\n'
   '    const ModToggle::Ptr m_afw_fix_flicker{ModToggle::create(generate_name("AFW_FixMovingObjectBrightnessFlickering"), false)};\n'
   '    const ModSlider::Ptr m_afw_ignore_motion_threshold{ModSlider::create(generate_name("AFW_IgnoreMotionThreshold"), 0.1f, 100.0f, 2.5f)};\n'),
  ('            *m_sync_mode,\n        };\n\n        add_components_vr();',
   '            *m_sync_mode,\n'
   '            *m_afw_mode,\n'
   '            *m_afw_shading_rate,\n'
   '            *m_afw_clear_before,\n'
   '            *m_afw_sharpening,\n'
   '            *m_afw_sharpness,\n'
   '            *m_afw_fix_object_mv,\n'
   '            *m_afw_fix_object_mv_range,\n'
   '            *m_afw_fix_flicker,\n'
   '            *m_afw_ignore_motion_threshold,\n'
   '        };\n\n        add_components_vr();'),
 ],
 # ---- VR frame pacing: AFW submits a full stereo pair every frame (PureDark VR.cpp) --------
 "src/mods/VR.cpp": [
  ('#include "VR.hpp"\n#include <cstring>\n',
   '#include "VR.hpp"\n#include "vr/DuoViewAFW.hpp"\n#include <cstring>\n'),
  ('        sdk::set_cvar_data_int(L"Engine", L"r.DefaultFeature.MotionBlur", 0);\n        return;\n    }',
   '        sdk::set_cvar_data_int(L"Engine", L"r.DefaultFeature.MotionBlur", 0);\n'
   '        if (!is_using_afw()) {\n            return;\n        } // AFW renders a fresh pose every frame\n    }'),
  ('        if (!is_using_afr() || (m_render_frame_count + 1) % 2 == m_left_eye_interval) {\n'
   '            SetEvent(m_present_finished_event);',
   '        if (!is_using_afr() || is_using_afw() || (m_render_frame_count + 1) % 2 == m_left_eye_interval) {\n'
   '            SetEvent(m_present_finished_event);'),
  ('    m_frame_count = get_runtime()->internal_render_frame_count;\n\n'
   '    if (!is_using_afr() || m_render_frame_count % 2 == m_left_eye_interval) {\n'
   '        ResetEvent(m_present_finished_event);\n    }',
   '    m_frame_count = get_runtime()->internal_render_frame_count;\n\n'
   '    // DuoView AFW Stage 1 warm-up counters (PureDark): 90 frames after injection, mode switch or DLSS resize.\n'
   '    if (afw_resolution_change_skip_frames > 0) {\n        --afw_resolution_change_skip_frames;\n    }\n'
   '    if (afw_switching_skip_frames > 0) {\n        --afw_switching_skip_frames;\n    }\n'
   '    {\n'
   '        const bool afw_selected_now = is_afw_selected() && !is_using_2d_screen();\n'
   '        if (afw_selected_now != afw_was_selected) {\n            afw_switching_skip_frames = 90;\n        }\n'
   '        afw_was_selected = afw_selected_now;\n'
   '        if (afw_selected_now && !afw_plugin_ready.load()) {\n'
   '            uevr::afw::initialize(); // loads PDAFWPlugin.dll and installs hooks only now, never for modes 0-6\n'
   '        }\n'
   '    }\n'
   '    if (afw_since_inject_frame_count < 1000000) {\n        ++afw_since_inject_frame_count;\n    }\n\n'
   '    if (!is_using_afr() || is_using_afw() || m_render_frame_count % 2 == m_left_eye_interval) {\n'
   '        ResetEvent(m_present_finished_event);\n    }'),
  ('    const auto is_left_eye_frame = is_using_afr() ? (m_render_frame_count % 2 == m_left_eye_interval) : true;\n\n'
   '    if (is_left_eye_frame && get_synchronize_stage() == VR::SynchronizeStage::LATE) {',
   '    const auto is_left_eye_frame = is_using_afr() ? (m_render_frame_count % 2 == m_left_eye_interval) : true;\n\n'
   '    if (is_using_afw()) {\n        afw_update_camera_data(m_render_frame_count);\n    }\n\n'
   '    if ((is_left_eye_frame || is_using_afw()) && get_synchronize_stage() == VR::SynchronizeStage::LATE) {'),
  ('    if (is_left_eye_frame) {\n        const auto should_defer_very_late_wait =',
   '    if (is_left_eye_frame || is_using_afw()) {\n        const auto should_defer_very_late_wait ='),
  ('        if (!uevr::nascar::is_target()) {\n            m_synced_afr_method->draw("Synced Sequential Method");\n        }\n',
   '        if (!uevr::nascar::is_target()) {\n            m_synced_afr_method->draw("Synced Sequential Method");\n        }\n'
   '        if (is_afw_selected()) {\n            afw_draw_ui();\n        }\n'),
 ],
 # ---- stereo hook: fresh pose per frame + AFW camera matrices (PureDark FFakeStereoRenderingHook.cpp)
 "src/mods/vr/FFakeStereoRenderingHook.cpp": [
  ('        true_index = g_frame_count % 2;\n\n        if (!vr->is_using_synchronized_afr()) {\n'
   '            if (g_hook->m_has_double_precision) {\n                if (true_index == 1) {\n'
   '                    *rot_d = g_hook->m_last_afr_rotation_double;',
   '        true_index = g_frame_count % 2;\n\n        if (!vr->is_using_synchronized_afr() && !vr->is_using_afw()) {\n'
   '            if (g_hook->m_has_double_precision) {\n                if (true_index == 1) {\n'
   '                    *rot_d = g_hook->m_last_afr_rotation_double;'),
  ('    if (true_index == 0 && !is_full_pass) {\n        if (has_double_precision) {\n'
   '            g_hook->m_last_pre_rotation_double = *rot_d;',
   '    if ((true_index == 0 || vr->is_using_afw()) && !is_full_pass) {\n        if (has_double_precision) {\n'
   '            g_hook->m_last_pre_rotation_double = *rot_d;'),
  ('        : true_index == 1;\n\n    std::optional<uevr::prospi::trace::Ticket> trace_view;',
   '        : (true_index == 1 || vr->is_using_afw());\n\n    std::optional<uevr::prospi::trace::Ticket> trace_view;'),
  ('    if (!vr->is_stereo_emulation_enabled()) {\n        const auto is_2d_screen = vr->is_using_2d_screen();\n\n'
   '        const auto rotation_offset = vr->get_rotation_offset();',
   '    // DuoView AFW Stage 1: this view\'s and the other eye\'s separation (PureDark AFW camera matrices).\n'
   '    bool afw_pose_valid = false;\n'
   '    glm::vec3 afw_eye_separation{};\n'
   '    glm::vec3 afw_eye_separation_other{};\n'
   '    glm::quat afw_new_rotation_other{1.0f, 0.0f, 0.0f, 0.0f};\n'
   '    if (!vr->is_stereo_emulation_enabled()) {\n        const auto is_2d_screen = vr->is_using_2d_screen();\n\n'
   '        const auto rotation_offset = vr->get_rotation_offset();'),
  ('        const auto eye_separation = quat_converter * (eye_translation_rotation * (eye_offset * world_scale));\n',
   '        const auto eye_separation = quat_converter * (eye_translation_rotation * (eye_offset * world_scale));\n'
   '        // Matrices are kept current while ID 7 is selected, so they are valid the frame warping starts.\n'
   '        if (vr->is_afw_selected() && !mono && !is_2d_screen && !is_full_pass) {\n'
   '            const auto afw_other_index = (true_index + 1) % 2;\n'
   '            const auto afw_other_eye_rotation_offset = glm::normalize(glm::quat{vr->get_eye_transform(afw_other_index)});\n'
   '            afw_new_rotation_other = glm::normalize(vqi_norm * current_hmd_rotation * afw_other_eye_rotation_offset);\n'
   '            const auto afw_eye_offset_other = glm::vec3{vr->get_eye_offset((VRRuntime::Eye)(afw_other_index))};\n'
   '            afw_eye_separation = eye_separation;\n'
   '            afw_eye_separation_other = quat_converter * (glm::normalize(afw_new_rotation_other) * (afw_eye_offset_other * world_scale));\n'
   '            afw_pose_valid = true;\n'
   '        }\n'),
  ('        if (true_index == 0) {\n            if (has_double_precision) {\n'
   '                g_hook->m_last_rotation_double = *rot_d;',
   '        if (true_index == 0 || vr->is_using_afw()) {\n            if (has_double_precision) {\n'
   '                g_hook->m_last_rotation_double = *rot_d;'),
  ('                g_hook->m_tracking_system_hook->manual_update_control_rotation();\n            }\n        }\n    }\n\n'
   '#ifdef FFAKE_STEREO_RENDERING_LOG_ALL_CALLS\n    SPDLOG_INFO("Finished calculating stereo view offset!");',
   '                g_hook->m_tracking_system_hook->manual_update_control_rotation();\n            }\n        }\n\n'
   '        // DuoView AFW Stage 1 (PureDark): inverse view matrices in meters for this eye and the other eye.\n'
   '        if (afw_pose_valid && (true_index == 0 || true_index == 1)) {\n'
   '            const auto afw_world_to_meters = vr->get_world_to_meters();\n'
   '            const auto afw_euler_other = glm::degrees(utility::math::euler_angles_from_steamvr(afw_new_rotation_other));\n'
   '            const auto afw_view_to_world_other = glm::yawPitchRoll(\n'
   '                glm::radians(-afw_euler_other.y), glm::radians(afw_euler_other.x), glm::radians(-afw_euler_other.z));\n'
   '            glm::mat4 afw_view_to_world{1.0f};\n'
   '            glm::vec3 afw_cam_pos{};\n'
   '            glm::vec3 afw_cam_pos_other{};\n'
   '            if (!has_double_precision) {\n'
   '                auto view_location_other = *view_location;\n'
   '                view_location_other += afw_eye_separation;\n'
   '                view_location_other -= afw_eye_separation_other;\n'
   '                afw_view_to_world = glm::yawPitchRoll(\n'
   '                    glm::radians(-view_rotation->yaw), glm::radians(view_rotation->pitch), glm::radians(-view_rotation->roll));\n'
   '                afw_cam_pos = (*view_location) / afw_world_to_meters;\n'
   '                afw_cam_pos_other = view_location_other / afw_world_to_meters;\n'
   '            } else {\n'
   '                auto view_d_other = *view_d;\n'
   '                view_d_other += afw_eye_separation;\n'
   '                view_d_other -= afw_eye_separation_other;\n'
   '                afw_view_to_world = glm::yawPitchRoll(\n'
   '                    glm::radians(-(float)rot_d->yaw), glm::radians((float)rot_d->pitch), glm::radians(-(float)rot_d->roll));\n'
   '                const auto afw_cam_pos_d = (*view_d) / double(afw_world_to_meters);\n'
   '                const auto afw_cam_pos_d_other = view_d_other / double(afw_world_to_meters);\n'
   '                afw_cam_pos = glm::vec3(afw_cam_pos_d);\n'
   '                afw_cam_pos_other = glm::vec3(afw_cam_pos_d_other);\n'
   '            }\n'
   '            afw_cam_pos = glm::vec3(afw_cam_pos.y, afw_cam_pos.z, -afw_cam_pos.x);\n'
   '            afw_cam_pos_other = glm::vec3(afw_cam_pos_other.y, afw_cam_pos_other.z, -afw_cam_pos_other.x);\n'
   '            glm::mat4 afw_translation{1.0f};\n'
   '            afw_translation[3] = glm::vec4(afw_cam_pos, 1.0f);\n'
   '            glm::mat4 afw_translation_other{1.0f};\n'
   '            afw_translation_other[3] = glm::vec4(afw_cam_pos_other, 1.0f);\n'
   '            vr->render_view_inv_matrix[true_index][2] = vr->render_view_inv_matrix[true_index][1];\n'
   '            vr->render_view_inv_matrix[true_index][1] = vr->render_view_inv_matrix[true_index][0];\n'
   '            vr->render_view_inv_matrix[true_index][0].curr = afw_translation * afw_view_to_world;\n'
   '            vr->render_view_inv_matrix[true_index][0].other = afw_translation_other * afw_view_to_world_other;\n'
   '            vr->last_update_matrix_frame_count[true_index] = static_cast<int>(g_frame_count);\n'
   '        }\n'
   '    }\n\n'
   '#ifdef FFAKE_STEREO_RENDERING_LOG_ALL_CALLS\n    SPDLOG_INFO("Finished calculating stereo view offset!");'),
  ('            const auto fmat = VR::get()->get_projection_matrix((VRRuntime::Eye)(true_index));\n'
   '            double_matrix = fmat;\n        }\n        if (duo_fovea || duo_full) {',
   '            const auto fmat = VR::get()->get_projection_matrix((VRRuntime::Eye)(true_index));\n'
   '            double_matrix = fmat;\n        }\n'
   '        if (vr->is_afw_selected() && true_index >= 0 && true_index <= 1) {\n'
   '            // DuoView AFW Stage 1 (PureDark): this eye\'s and the other eye\'s projection in AFW\'s convention.\n'
   '            const auto afw_world_to_meters = vr->get_world_to_meters();\n'
   '            const auto afw_convert = [afw_world_to_meters](Matrix4x4f m) {\n'
   '                m[2][0] *= -1.0f;\n'
   '                m[2][1] *= -1.0f;\n'
   '                m[2][2] = -1.0f;\n'
   '                m[2][3] = -1.0f;\n'
   '                m[3][2] *= -1.0f / afw_world_to_meters;\n'
   '                return m;\n'
   '            };\n'
   '            const auto afw_other_index = (true_index + 1) % 2;\n'
   '            vr->render_projection_matrix[true_index].curr = afw_convert(vr->get_projection_matrix((VRRuntime::Eye)(true_index)));\n'
   '            vr->render_projection_matrix[true_index].other = afw_convert(vr->get_projection_matrix((VRRuntime::Eye)(afw_other_index)));\n'
   '        }\n'
   '        if (duo_fovea || duo_full) {'),
 ],
 # ---- D3D12: warp the rendered eye, submit the warped eye, submit every frame -------------
 "src/mods/vr/D3D12Component.cpp": [
  ('#include "D3D12Component.hpp"\n#include "GalacticRacerRenderTargets.hpp"\n',
   '#include "D3D12Component.hpp"\n#include "DuoViewAFW.hpp"\n#include "GalacticRacerRenderTargets.hpp"\n'),
  ('    // If m_frame_count is even, we\'re rendering the left eye.\n    if (is_left_eye_frame) {\n'
   '        m_submitted_left_eye = true;',
   '    // DuoView AFW Stage 1 (PureDark AFW): warp the eye rendered this frame into the other eye.\n'
   '    if (vr->is_afw_selected() && vr->afw_plugin_ready.load()) {\n'
   '        uevr::afw::prepare_inputs();\n'
   '    }\n'
   '    const bool afw_active = is_afr && vr->is_using_afw() && runtime->is_openxr();\n'
   '    std::optional<uevr::afw::OtherEye> afw_other_eye{};\n'
   '    if (afw_active && !suppress_scene_copy && backbuffer.Get() != nullptr) {\n'
   '        const D3D12_BOX afw_eye_box{0, 0, 0,\n'
   '            vr->is_extreme_compatibility_mode_enabled() ? m_backbuffer_size[0] : m_backbuffer_size[0] / 2,\n'
   '            m_backbuffer_size[1], 1};\n'
   '        afw_other_eye = uevr::afw::evaluate(backbuffer.Get(), scene_source_state,\n'
   '            swapchain->GetCurrentBackBufferIndex(), static_cast<int>(frame_count), afw_eye_box);\n'
   '    }\n\n'
   '    // If m_frame_count is even, we\'re rendering the left eye.\n    if (is_left_eye_frame) {\n'
   '        m_submitted_left_eye = true;'),
  ('    if (is_right_eye_frame) {\n        if ((runtime->ready() && vr->get_synchronize_stage() == VR::SynchronizeStage::VERY_LATE) || !runtime->got_first_sync) {',
   '    if (afw_other_eye && runtime->is_openxr() && vr->m_openxr->can_run_frame_loop()) {\n'
   '        const auto afw_color_index = afw_other_eye->destination_is_left ?\n'
   '            runtimes::OpenXR::SwapchainIndex::AFR_LEFT_EYE : runtimes::OpenXR::SwapchainIndex::AFR_RIGHT_EYE;\n'
   '        const auto afw_depth_index = afw_other_eye->destination_is_left ?\n'
   '            runtimes::OpenXR::SwapchainIndex::AFR_DEPTH_LEFT_EYE : runtimes::OpenXR::SwapchainIndex::AFR_DEPTH_RIGHT_EYE;\n'
   '        D3D12_BOX afw_box = afw_other_eye->box;\n'
   '        m_openxr.copy((uint32_t)afw_color_index, afw_other_eye->color, ENGINE_SRC_COLOR, &afw_box);\n'
   '        if (scene_depth_tex != nullptr && !dead_island_2_afr_depth_disabled && afw_other_eye->depth != nullptr &&\n'
   '            copy_resource_depth_descriptors_compatible(afw_other_eye->depth->GetDesc(), scene_depth_tex->GetDesc())) {\n'
   '            m_openxr.copy((uint32_t)afw_depth_index, afw_other_eye->depth, ENGINE_SRC_COLOR, nullptr);\n'
   '        }\n'
   '    }\n\n'
   '    if (is_right_eye_frame) {\n        if ((runtime->ready() && vr->get_synchronize_stage() == VR::SynchronizeStage::VERY_LATE) || !runtime->got_first_sync) {'),
  ('    vr::EVRCompositorError e = vr::EVRCompositorError::VRCompositorError_None;\n\n    if (is_right_eye_frame) {\n'
   '        ////////////////////////////////////////////////////////////////////////////////\n'
   '        // OpenXR start ////',
   '    vr::EVRCompositorError e = vr::EVRCompositorError::VRCompositorError_None;\n\n'
   '    if (is_right_eye_frame || afw_active) { // AFW submits a full stereo pair every frame\n'
   '        ////////////////////////////////////////////////////////////////////////////////\n'
   '        // OpenXR start ////'),
 ],
 "src/mods/UObjectHook.cpp": [
  ('    if ((view_index + 1) % 2 == 0) {\n        return true;\n    }\n\n    auto& vr = VR::get();',
   '    if (VR::get()->is_using_afw() || (view_index + 1) % 2 == 0) { // AFW: every frame is a stereo frame\n'
   '        return true;\n    }\n\n    auto& vr = VR::get();'),
 ],
 # Belt and braces: cmkr regenerates this list from the src/**.cpp glob at configure time anyway.
 "CMakeLists.txt": [
  ('\t"src/mods/vr/D3D12Component.cpp"\n\t"src/mods/vr/FFakeStereoRenderingHook.cpp"\n',
   '\t"src/mods/vr/D3D12Component.cpp"\n\t"src/mods/vr/DuoViewAFW.cpp"\n\t"src/mods/vr/FFakeStereoRenderingHook.cpp"\n'),
 ],
}

FRONTEND = {
 "UEVR/RenderingModeOptions.cs": [
  ('        public const int DuoViewMono = 6;',
   '        public const int DuoViewMono = 6;\n        public const int AlternateFrameWarping = 7;'),
  ('            result.Add(DuoViewMono.ToString(), "DuoView Mono (Eye Tracked - Experimental)");',
   '            result.Add(DuoViewMono.ToString(), "DuoView Mono (Eye Tracked - Experimental)");\n'
   '            result.Add(AlternateFrameWarping.ToString(), "' + AFW_LABEL + '");'),
 ],
 "tests/RenderingModes/Program.cs": [
  ('for (int id = 0; id <= 6; ++id) {', 'for (int id = 0; id <= 7; ++id) {'),
  ('bool supported = id < 3 || id == 5 || id == 6 || dibr;',
   'bool supported = id < 3 || id == 5 || id == 6 || id == 7 || dibr;'),
  ('"4", "5", "6", "99", "-1"', '"4", "5", "6", "7", "99", "-1"'),
  ('    if (choices.ContainsKey("99")) {',
   '    if (choices["7"] != "' + AFW_LABEL + '") {\n'
   '        throw new Exception("AFW must keep serialized ID 7");\n'
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
    backend, frontend, duoview, header, evidence = args.paths
    backend, frontend, duoview, header, evidence = map(Path, (backend, frontend, duoview, header, evidence))
    evidence.mkdir(parents=True, exist_ok=True)
    if git(backend, "rev-parse", "HEAD") != "5ac7edc207866569334175e4ed8a7517971547f6":
        raise RuntimeError("Unexpected Joey backend revision")
    if git(frontend, "rev-parse", "HEAD") != "60be4b0f9a646109fd9fdf448bacd41477234091":
        raise RuntimeError("Unexpected Joey frontend revision")

    changed, added = tracked_state(backend)
    if changed != V207_EDITED or added != V207_ADDED:
        raise RuntimeError(f"Backend is not the exact v207 state: {sorted((changed ^ V207_EDITED) | (added ^ V207_ADDED))}")

    header_bytes = header.read_bytes()
    if hashlib.sha256(header_bytes.replace(b"\r\n", b"\n")).hexdigest() != PD_HEADER_SHA256:
        raise RuntimeError("PDAFWPlugin.h is not PureDark's fc8de10 header")

    for name in MODULE_FILES:
        target = backend / "src/mods/vr" / name
        if target.exists():
            raise RuntimeError(f"Refusing to overwrite {target}")
        target.write_bytes((duoview / "afw" / name).read_bytes())
    header_target = backend / PD_HEADER_DEST
    if header_target.exists():
        raise RuntimeError(f"Refusing to overwrite {header_target}")
    header_target.parent.mkdir(parents=True)
    header_target.write_bytes(header_bytes)

    apply_edits(backend, BACKEND)
    apply_edits(frontend, FRONTEND)

    changed, added = tracked_state(backend)
    expected_changed = V207_EDITED | AFW_EDITED
    expected_added = V207_ADDED | AFW_ADDED
    if changed != expected_changed or added != expected_added:
        raise RuntimeError(f"Unexpected backend paths: {sorted((changed ^ expected_changed) | (added ^ expected_added))}")
    fchanged, fadded = tracked_state(frontend)
    if fchanged - (FRONTEND_EDITED | FRONTEND_GENERATED) or not FRONTEND_EDITED <= fchanged or fadded:
        raise RuntimeError(f"Unexpected frontend paths: {sorted(fchanged | fadded)}")

    hashes = {"backend": {p: sha(backend / p) for p in sorted(expected_changed | expected_added)},
              "frontend": {p: sha(frontend / p) for p in sorted(FRONTEND_EDITED)}}
    (evidence / "duoview-afw-stage1-hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print("DuoView AFW Stage 1 applied: rendering method ID 7, PureDark AFW port; modes 0-6 gated off.")


def verify(args):
    backend, evidence = map(Path, args.paths)
    recorded = json.loads((evidence / "duoview-afw-stage1-hashes.json").read_text(encoding="utf-8"))
    for rel, digest in recorded["backend"].items():
        if sha(backend / rel) != digest:
            raise RuntimeError(f"{rel} changed during the build")
    print(f"DuoView AFW Stage 1 source unchanged after build ({len(recorded['backend'])} backend files).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("paths", nargs="+")
    a = parser.parse_args()
    if a.verify:
        if len(a.paths) != 2:
            sys.exit("usage: apply_afw_stage1.py --verify BACKEND EVIDENCE")
        verify(a)
    else:
        if len(a.paths) != 5:
            sys.exit("usage: apply_afw_stage1.py BACKEND FRONTEND DUOVIEW_DIR PDAFWPLUGIN_H EVIDENCE")
        apply(a)

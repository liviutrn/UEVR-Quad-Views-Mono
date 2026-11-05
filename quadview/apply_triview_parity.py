#!/usr/bin/env python3
"""Tri-view B5: DuoView v208 feature parity for ID7 (Quad Views / Tri-view).

Run AFTER apply_quadview_triview.py. The DuoView FOV/XYZ/hotkey scripts from
quadview/duoview_port/ (byte-identical copies of the v208d DuoView scripts) are
applied right after Stage 2-4, exactly where DuoView applies them. This script:

1. Adds VR::is_duoview_or_triview_fov_active(): DuoView renderer active, OR
   rendering method 7 committed on STALKER 2 + D3D12 + OpenXR.
2. Switches ONLY the ported FOV code (automatic MPC override, Reapply FOV
   button, FOV hotkey, auto reapply after load) from the DuoView-only gate to
   that helper. Head XYZ scaling is mode-agnostic already (it scales the HMD
   translation before Tri-view freezes its cameras) and is not touched.
3. Tri-view sharpening: strength 0..5 (was 0..2) and a max-change-per-pixel
   slider 0.05..0.30 (default 0.10 = exactly the previous fixed shader value).
4. Saves the ID7 menu settings to the UEVR config like the DuoView settings
   (before, every ID7 slider reset to its default at each game start). Debug
   view, debug border and GPU timing are NOT saved, so a debug view never sticks.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_triview_parity.py <backend>")
root = Path(sys.argv[1])


def edit(rel, pairs):
    path = root / rel
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{rel}: expected exactly one anchor, found {count}:\n{old[:200]}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


GATE = "is_duoview_or_triview_fov_active()"

# ---------------------------------------------------------------- VR.hpp
edit("src/mods/VR.hpp", [
    ("    bool is_duoview_renderer_active() const;\n",
     "    bool is_duoview_renderer_active() const;\n"
     "    // Tri-view B5: the DuoView FOV fix (MPC override, Reapply FOV, auto reapply) also runs in ID7.\n"
     "    bool is_duoview_or_triview_fov_active() const;\n"),
    ('    const ModSlider::Ptr m_quadview_sharpen{ModSlider::create(generate_name("QuadViewSharpen"), 0.f, 2.f, 1.f)};\n',
     '    const ModSlider::Ptr m_quadview_sharpen{ModSlider::create(generate_name("QuadViewSharpen"), 0.f, 5.f, 1.f)};\n'
     '    const ModSlider::Ptr m_quadview_sharpen_max{ModSlider::create(generate_name("QuadViewSharpenMaxChange"), 0.05f, 0.30f, 0.10f)};\n'),
    ("            *m_duo_micro_gain, *m_duo_breakout, *m_duo_stillness, *m_duo_relock,\n",
     "            *m_duo_micro_gain, *m_duo_breakout, *m_duo_stillness, *m_duo_relock,\n"
     "            *m_quadview_crop_width, *m_quadview_crop_height, *m_quadview_context_scale,\n"
     "            *m_quadview_tri_view, *m_quadview_foveal_density, *m_quadview_feather,\n"
     "            *m_quadview_sharpen, *m_quadview_sharpen_max, *m_quadview_eye_tracking,\n"
     "            *m_quadview_stabilize_crop, *m_quadview_guard, *m_quadview_gaze_quant,\n"
     "            *m_quadview_gaze_hold, *m_quadview_gaze_reacquire, *m_quadview_gaze_offset_u,\n"
     "            *m_quadview_gaze_offset_v, *m_quadview_gaze_micro_gain, *m_quadview_gaze_breakout,\n"
     "            *m_quadview_gaze_still, *m_quadview_gaze_relock,\n"),
])

# ---------------------------------------------------------------- VR.cpp
edit("src/mods/VR.cpp", [
    # 1. helper definition, right after the DuoView gate it extends
    ("        return path && uevr::stalker2_native::is_executable(*path);\n"
     "    }();\n"
     "    return stalker2;\n"
     "}\n"
     "\n"
     "std::optional<uevr::duoview::ViewFrame> VR::duoview_begin_frame() {\n",
     "        return path && uevr::stalker2_native::is_executable(*path);\n"
     "    }();\n"
     "    return stalker2;\n"
     "}\n"
     "\n"
     "bool VR::is_duoview_or_triview_fov_active() const {\n"
     "    if (is_duoview_renderer_active()) return true;\n"
     "    // ID7 committed (not merely requested). Same title/API/runtime limits as DuoView.\n"
     "    if (!is_quadview_mode_selected() || !m_is_d3d12) return false;\n"
     "    const auto runtime = get_runtime();\n"
     "    if (!runtime || !runtime->is_openxr()) return false;\n"
     "    static const bool stalker2 = [] {\n"
     "        const auto path = utility::get_module_pathw(utility::get_executable());\n"
     "        return path && uevr::stalker2_native::is_executable(*path);\n"
     "    }();\n"
     "    return stalker2;\n"
     "}\n"
     "\n"
     "std::optional<uevr::duoview::ViewFrame> VR::duoview_begin_frame() {\n"),
    # 2. ported gates (v205 deferred hotkey, v207 auto FOV, v165 MPC reconcile,
    #    v205 combined key, v205 FOV key, v165 button)
    ("                   is_duoview_renderer_active() && engine && engine->get_world()) {\n",
     f"                   {GATE} && engine && engine->get_world()) {{\n"),
    ("        if (!is_duoview_renderer_active() || auto_world == nullptr) {\n",
     f"        if (!{GATE} || auto_world == nullptr) {{\n"),
    ("            const bool requested = is_duoview_renderer_active();\n"
     "            if (!requested && !fg.active) return;\n",
     f"            const bool requested = {GATE};\n"
     "            if (!requested && !fg.active) return;\n"),
    ("                                  is_duoview_renderer_active();\n",
     f"                                  {GATE};\n"),
    ("    if (fov_pressed && !reset_pressed && is_duoview_renderer_active()) {\n",
     f"    if (fov_pressed && !reset_pressed && {GATE}) {{\n"),
    ("    ImGui::BeginDisabled(!is_duoview_renderer_active());\n"
     '    if (ImGui::Button("Reapply DuoView FOV")) {\n',
     f"    ImGui::BeginDisabled(!{GATE});\n"
     '    if (ImGui::Button("Reapply FOV (DuoView/Tri-view)")) {\n'),
    # keep Overlay/Runtime Keys (FOV + reset keys) open by default, as before the XYZ node was inserted
    ('            ImGui::TreePop();\n        }\n\n        if (ImGui::TreeNode("Overlay/Runtime Keys")) {\n',
     '            ImGui::TreePop();\n        }\n\n        ImGui::SetNextItemOpen(true, ImGuiCond_::ImGuiCond_Once);\n        if (ImGui::TreeNode("Overlay/Runtime Keys")) {\n'),
    ('            m_duoview_fov_reapply_key->draw("Reapply DuoView FOV Key");\n',
     '            m_duoview_fov_reapply_key->draw("Reapply FOV Key (DuoView/Tri-view)");\n'),
    # 3. sharpening UI + plumbing
    ('                m_quadview_sharpen->draw("Fused focus sharpening strength");\n',
     '                m_quadview_sharpen->draw("Fused focus sharpening strength (0-5, default 1)");\n'
     '                m_quadview_sharpen_max->draw("Sharpening max change per pixel (default 0.10; higher = stronger on hard edges, more halo risk)");\n'),
    ("            requested.sharpen_strength=m_quadview_sharpen->value();\n",
     "            requested.sharpen_strength=m_quadview_sharpen->value();\n"
     "            requested.sharpen_max_change=m_quadview_sharpen_max->value();\n"),
    ('                    if (rejected&uevr::quadview::reject_sharpen) ImGui::TextUnformatted("Sharpen strength rejected");\n',
     '                    if (rejected&uevr::quadview::reject_sharpen) ImGui::TextUnformatted("Sharpen strength rejected");\n'
     '                    if (rejected&uevr::quadview::reject_sharpen_max) ImGui::TextUnformatted("Sharpen max change rejected");\n'),
])

# ------------------------------------------------- QuadView settings + shader constant
edit("src/mods/vr/QuadViewSettings.hpp", [
    # new field LAST so no positional initialiser shifts
    ("    uint32_t gaze_relock_samples{3};\n};\n",
     "    uint32_t gaze_relock_samples{3};\n"
     "    float sharpen_max_change{.10f}; // Tri-view B5; .10 = previous fixed shader value\n};\n"),
    ("    reject_still=1u<<15, reject_relock=1u<<16\n};\n",
     "    reject_still=1u<<15, reject_relock=1u<<16, reject_sharpen_max=1u<<17\n};\n"),
    ("    scalar(requested.sharpen_strength,0.f,2.f,reject_sharpen,&Settings::sharpen_strength);\n",
     "    scalar(requested.sharpen_strength,0.f,5.f,reject_sharpen,&Settings::sharpen_strength);\n"
     "    scalar(requested.sharpen_max_change,.05f,.30f,reject_sharpen_max,&Settings::sharpen_max_change);\n"),
    ("a.sharpen_strength==b.sharpen_strength &&",
     "a.sharpen_strength==b.sharpen_strength && a.sharpen_max_change==b.sharpen_max_change &&"),
])
edit("src/mods/vr/QuadViewD3D12.hpp", [
    ("        constants.sharpen[2] = .10f;\n",
     "        constants.sharpen[2] = settings.sharpen_max_change;\n"),
])

# ---------------------------------------------------------------- self-check
vr_cpp = (root / "src/mods/VR.cpp").read_text(encoding="utf-8")
uses = vr_cpp.count(GATE)  # 1 definition + 6 ported gates
if uses != 7:
    raise SystemExit(f"Tri-view parity gate count is {uses}, expected 7")
print("Tri-view B5 parity applied: FOV gate in 6 places; sharpen 0..5 + max change; ID7 settings saved.")

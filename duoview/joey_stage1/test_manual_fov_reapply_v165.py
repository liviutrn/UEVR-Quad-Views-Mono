#!/usr/bin/env python3
"""Guard that manual FOV patch touches only UI and existing Build45 MPC tick code."""
from pathlib import Path
import sys
if len(sys.argv) != 2: raise SystemExit("usage: test_manual_fov_reapply_v165.py <backend>")
root = Path(sys.argv[1])
h = (root / "src/mods/VR.hpp").read_text(encoding="utf-8-sig")
c = (root / "src/mods/VR.cpp").read_text(encoding="utf-8-sig")
d = (root / "src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8-sig")
xr = (root / "src/mods/vr/runtimes/OpenXR.cpp").read_text(encoding="utf-8-sig")
xrh = (root / "src/mods/vr/runtimes/OpenXR.hpp").read_text(encoding="utf-8-sig")
start = c.index("    // STALKER 2 DuoView foreground parity.")
end = c.index("    // Some Supermassive camera paths rewrite crop/aspect state", start)
fg = c[start:end]
ui_start = c.index('    if (ImGui::Button("Reinitialize Runtime")) {')
ui_end = c.index("Vector4f VR::get_position(", ui_start)
ui = c[ui_start:ui_end]
for required in (
    "if (ImGui::Button(\"Reinitialize Runtime\"))",
    "if (ImGui::Button(\"Reapply DuoView FOV\"))",
    "ImGui::BeginDisabled(!is_duoview_renderer_active());",
    "m_duoview_manual_fov_requested.store(true",
    "m_duoview_manual_fov_status.store(1",
):
    assert required in ui, required
for required in (
    "m_duoview_manual_fov_requested.exchange(",
    "fg.manual_reapply_pending = true;",
    "validated current cached asset",
    "write(L\"IsFOVEnabled\", wanted_enabled)",
    "write(L\"DepthScale\", wanted_depth)",
    "m_duoview_manual_fov_status.store(confirmed ? 2 : 3",
    "[DuoView][ManualFOV] CONFIRMED IsFOVEnabled=0 DepthScale=1",
    "const float wanted_enabled = requested ? 0.0f : fg.original_enabled;",
    "const float wanted_depth = requested ? 1.0f : fg.original_depth;",
    "fg.original_enabled = current_enabled;",
    "fg.original_depth = current_depth;",
):
    assert required in fg, required
# Regression that made #201 ineffective: clearing the working asset on
# every click makes the original class-only discovery fail after load.
# V2 must KEEP that binding and rely on the original object-liveness guard.
assert "fg.collection = nullptr;" not in fg
assert "fg.library = nullptr;" not in fg
assert "fg.getter = nullptr;" not in fg
assert "fg.setter = nullptr;" not in fg
assert "fg.manual_reapply_pending = true;" in fg
assert fg.index("m_duoview_manual_fov_requested.exchange(") < fg.index("if (!fg.collection)")
assert fg.index("m_duoview_manual_fov_requested.exchange(") < fg.index("const auto read =")
assert fg.index("m_duoview_manual_fov_status.store(confirmed ? 2 : 3") > fg.index("const bool enabled_ok")
for forbidden in ("m_duoview.retire(", "configure_duoview(", "destroy_swapchains(",
                  "reinitialize_openxr(", "m_force_reset", "mono_generation()",
                  "m_rendering_method->value() =", "m_xyz_headscale_x->value() ="):
    assert forbidden not in fg, forbidden
for required in ("m_duoview_manual_fov_requested{false}",
                 "m_duoview_manual_fov_status{0}", "m_xyz_headscale_hold_bypass{ false }",
                 "get_xyz_head_movement_gains()"):
    assert required in h, required
assert "get_xyz_head_movement_gains()" in d
assert "mono_eye_alignment_enabled" in xr and "OpenXR_MonoEyeAlignmentPercent" in xrh
assert c.count('if (ImGui::Button("Reapply DuoView FOV"))') == 1
assert c.count("m_duoview_manual_fov_requested.exchange(") == 1
assert c.count("[DuoView][ManualFOV] CONFIRMED") == 1
print("PASS: v165 renderer/XYZ unchanged; no cache clearing on click, one-shot forced MPC write with readback.")

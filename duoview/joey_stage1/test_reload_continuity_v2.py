#!/usr/bin/env python3
"""Source-level no-regression guard for load and runtime-reset continuity V2.

CI also compiles full UEVR and runs real backend + GPU WARP tests.
No source test can substitute for STALKER 2 hardware save/quickload tests.
"""
import sys
from pathlib import Path
if len(sys.argv) != 2:
    raise SystemExit("Usage: test_reload_continuity_v2.py <backend>")
b = Path(sys.argv[1])
cpp = (b / "src/mods/VR.cpp").read_text(encoding="utf-8-sig")
hdr = (b / "src/mods/VR.hpp").read_text(encoding="utf-8-sig")
xr = (b / "src/mods/vr/runtimes/OpenXR.hpp").read_text(encoding="utf-8-sig")
overlay = (b / "src/mods/vr/OverlayComponent.hpp").read_text(encoding="utf-8-sig")
hook = (b / "src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8-sig")
a = cpp.index("    // DUOVIEW RELOAD V2:")
c = cpp.index("    // STALKER 2 DuoView foreground parity.", a)
rearm = cpp[a:c]
d = cpp.index("    // Some Supermassive camera paths rewrite crop/aspect state", c)
fg = cpp[c:d]
for token in (
    "xr->duoview_copy_submits.load",
    "recovery.proven_copies >= 12",
    "recovery.stable_playable_ticks >= 12",
    "std::chrono::milliseconds(350)",
    "get_acknowledged_pawn()",
    "recovery.attempted = true;",
    "m_duoview_quarantined.store(false",
    "without touching GPU compositor",
):
    assert token in rearm, token
for forbidden in (
    "m_duoview.retire", "m_duoview.configure", "configure_duoview(",
    "destroy_swapchains", "create_swapchains", "m_openxr.reset(",
    "invalidate_duoview_scene(", "m_rendering_method->value()",
    "m_xyz_headscale_enabled", "duoview_abort(",
):
    assert forbidden not in rearm, forbidden
for token in (
    "fg.force_reassert = true;", "const auto epoch = foreground_mpc_runtime_epoch();",
    "fg.runtime_epoch != epoch", "Long tick gap: refresh MPC_FOV",
    "Pawn changed: MPC cache refreshed", "MPC read failed; rebinding",
    "MPC write failed; retrying cached bindings",
    "fg.original_enabled = current_enabled;", "fg.original_depth = current_depth;",
    "const float wanted_enabled = requested ? 0.0f : fg.original_enabled;",
    "const float wanted_depth = requested ? 1.0f : fg.original_depth;",
):
    assert token in fg, token
assert "std::abs(current_enabled - wanted_enabled) <= epsilon" in fg
assert "std::abs(current_depth - wanted_depth) <= epsilon" in fg
assert "static_cast<sdk::UObjectBase*>(pawn)" not in cpp
assert "foreground_mpc_runtime_epoch.fetch_add(1, std::memory_order_acq_rel)" in hdr
assert "if (!e && is_using_duoview_mono()) {" in hdr
assert "Reset Runtime: ID6 quarantine cleared" in hdr
assert "Restored Mono Eye Alignment after runtime reset" in hdr
for option in ("DuoViewCropWidth","DuoViewCropHeight","DuoViewPeripheralScale",
               "DuoViewFovealDensity","DuoViewGlamaryeFoveaStrength",
               "DuoViewEyeTracking","DuoViewFoveaSourceView","DuoViewNativeFixSamePass",
               "DuoViewGazeOffsetX","DuoViewGazeOffsetY","XYZHeadScaleX",
               "XYZHeadScaleY","XYZHeadScaleZ","XYZHeadScalingEnabled",
               "XYZHeadScaleToggleKey","XYZHeadScaleHoldBypassKey"):
    assert option in hdr, option
assert "get_xyz_head_movement_gains()" in hook
assert "UI_MonoHudConvergence" in overlay and "UI_MonoHudOpticalDistance" in overlay
assert "mono_eye_alignment_enabled" in xr
print("PASS: V2 only re-arms quarantined ID6 after proved XR copies + stable playable world.")
print("PASS: No GPU/compositor mutation in reload logic; Build45 MPC targets preserved.")
print("PASS: Build49 calibration, HUD, gaze, sharpening, and original XYZ sliders/keys retained.")

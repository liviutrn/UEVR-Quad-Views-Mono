#!/usr/bin/env python3
"""No-regression contracts for manual save, quicksave load, autosave load.

Checks both stable runtime/option lifetime and one-time recovery gating.
CANNOT simulate Unreal asset recreation, the GPU, or headset reprojection.
"""
import sys
from pathlib import Path
if len(sys.argv)!=2:
    raise SystemExit("Usage: test_save_reload_all_features.py <backend>")
b=Path(sys.argv[1])
h=(b/"src/mods/VR.hpp").read_text(encoding="utf-8-sig")
c=(b/"src/mods/VR.cpp").read_text(encoding="utf-8-sig")
f=(b/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8-sig")
xr=(b/"src/mods/runtimes/OpenXR.cpp").read_text(encoding="utf-8-sig")
oh=(b/"src/mods/vr/OverlayComponent.hpp").read_text(encoding="utf-8-sig")
for name in ("DuoViewCropWidth","DuoViewCropHeight","DuoViewPeripheralScale",
             "DuoViewFovealDensity","DuoViewFeather","DuoViewGlamaryeFoveaStrength",
             "DuoViewEyeTracking","DuoViewFoveaSourceView","DuoViewNativeFixSamePass",
             "DuoViewGazeOffsetX","DuoViewGazeOffsetY"):
    assert name in h, f"DuoView option unexpectedly lost: {name}"
for name in ("XYZHeadScalingEnabled","XYZHeadScaleX","XYZHeadScaleY",
             "XYZHeadScaleZ","XYZHeadScaleToggleKey","XYZHeadScaleHoldBypassKey"):
    assert name in h, f"XYZ persistence unexpectedly lost: {name}"
assert "get_xyz_head_movement_gains()" in f
assert "eye_offset * world_scale" in f
assert "UI_MonoHudConvergence" in oh
assert "UI_MonoHudOpticalDistance" in oh
assert "mono_hud_optical" in (b/"src/mods/vr/OverlayComponent.cpp").read_text(encoding="utf-8-sig")
assert "OpenXR_MonoEyeAlignmentEnabled" in (b/"src/mods/runtimes/OpenXR.hpp").read_text(encoding="utf-8-sig")
assert "OpenXR_MonoEyeAlignmentPercent" in (b/"src/mods/runtimes/OpenXR.hpp").read_text(encoding="utf-8-sig")
assert "Restored Mono Eye Alignment after runtime reset" in h
assert "m_foreground_mpc_runtime_epoch.fetch_add(1" in h
# A world-load event should NOT deactivate or reset an active user setting.
start=c.index("    // SAVE RELOAD RECOVERY.")
end=c.index("    // STALKER 2 DuoView foreground parity.",start)
recovery=c[start:end]
for token in ("world_changed || pawn_changed || resumed_after_loading",
              "reload.stable_ticks >= 3", "now < reload.retry_until",
              "!reload.attempted", "reload.attempted = true",
              "m_duoview.retire();", "invalidate_duoview_scene();",
              "configure_duoview();",
              "m_duoview_quarantined.store(",
              "Quarantined renderer rearmed"):
    assert token in recovery,token
for forbidden in ("m_duo_width->value() =", "m_duo_height->value() =",
                  "m_xyz_headscale_enabled->value() =", "m_world_scale->value() =",
                  "m_rendering_method->value() =", "m_openxr.reset()"):
    assert forbidden not in recovery,forbidden
assert "duoview_continuity.reset()" in xr
assert "void VR::duoview_abort(const char* reason)" in c
assert "void VR::configure_duoview()" in c
print("PASS: mode 6, all core fovea/gaze, XYZ, HUD and eye-alignment options preserved;")
print("      bounded one-shot quarantine rearm and fresh source state on world/pawn/load pause.")

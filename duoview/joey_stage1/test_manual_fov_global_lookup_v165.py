#!/usr/bin/env python3
"""Build #165 is the verified reference, not any reload recovery experiment.

Fail CI if this manual-only patch touches GPU capture, compositor, pose,
eye alignment, native stereo fix, XYZ scaling, or changes the original MPC
conditional write outside the user-requested manual branch.
"""
from pathlib import Path
import hashlib, json, sys
if len(sys.argv) != 3:
    raise SystemExit("Usage: test_manual_fov_global_lookup_v165.py <backend> <prepatch-hashes.json>")
root = Path(sys.argv[1])
before = json.loads(Path(sys.argv[2]).read_text())
for path, expected in before.items():
    got = hashlib.sha256((root/path).read_bytes()).hexdigest()
    assert got == expected, f"#165 protected rendering file changed: {path}"
c = (root/"src/mods/VR.cpp").read_text(encoding="utf-8-sig")
h = (root/"src/mods/VR.hpp").read_text(encoding="utf-8-sig")
start = c.index("    // STALKER 2 DuoView foreground parity.")
end = c.index("    // Some Supermassive camera paths rewrite crop/aspect state", start)
fg = c[start:end]
ui = c[c.index('    if (ImGui::Button("Reinitialize Runtime")) {'):c.index("Vector4f VR::get_position(")]
for term in [
    "if (ImGui::Button(\"Reapply DuoView FOV\"))",
    "ImGui::BeginDisabled(!is_duoview_renderer_active());",
    "m_duoview_manual_fov_requested.store(true",
    "m_duoview_manual_fov_status.store(1",
    "FOV reapply: verified MPC 0 / 1 (check headset)",
    "FOV reapply: failed (see log; retry in gameplay)",
]:
    assert term in ui, term
assert 'get_runtime()->wants_reinitialize = true;' in ui
# Exact canonical MPC name must SURVIVE fg={} on world changes; re-find
# through full FUObjectArray ONLY for a click, not on healthy game ticks.
for term in (
    "static std::wstring known_mpc_full_name{};",
    "sdk::find_uobject<sdk::UObject>(",
    "known_mpc_full_name, false",
    "m_duoview_manual_fov_requested.load(std::memory_order_acquire)",
    "recovered->get_class() == expected_class",
    "recovered->get_full_name() == known_mpc_full_name",
    "sdk::is_current_object(observed_collection->identity)",
    "known_mpc_full_name = unique_collection->get_full_name();",
    'if (!world) {',
    "fail_manual(\"No active UWorld on game tick\")",
    "fail_manual(\"MPC_FOV absent from both live registry and global object array\")",
    "fail_manual(\"KismetMaterialLibrary method binding not available\")",
    "fail_manual(\"Cannot read current-world MPC_FOV scalar values\")",
    "fail_manual(\"Unreal SDK exception during manual MPC operation\")",
    "m_duoview_manual_fov_status.store(2, std::memory_order_release)",
    "m_duoview_manual_fov_status.store(3, std::memory_order_release)",
    "read(L\"IsFOVEnabled\", after_enabled)",
    "read(L\"DepthScale\", after_depth)",
    "std::abs(after_enabled) <= epsilon",
    "std::abs(after_depth - 1.0f) <= epsilon",
    "write(L\"IsFOVEnabled\", wanted_enabled)",
    "write(L\"DepthScale\", wanted_depth)",
    "const float wanted_enabled = requested ? 0.0f : fg.original_enabled;",
    "const float wanted_depth = requested ? 1.0f : fg.original_depth;",
    "fg.original_enabled = current_enabled;",
    "fg.original_depth = current_depth;",
):
    assert term in fg, term
assert fg.index("static std::wstring known_mpc_full_name{};") < fg.index("const auto reconcile_foreground =")
assert fg.index("m_duoview_manual_fov_requested.load(std::memory_order_acquire)") < fg.index("known_mpc_full_name, false")
assert fg.index("if (!unique_collection &&") < fg.index("known_mpc_full_name, false")
assert fg.index("m_duoview_manual_fov_status.store(2") > fg.index("read(L\"DepthScale\", after_depth)")
assert c.count("if (ImGui::Button(\"Reapply DuoView FOV\"))") == 1
assert c.count("m_duoview_manual_fov_requested.store(true") == 1
assert c.count("known_mpc_full_name, false") == 1
assert "m_duoview_manual_fov_requested{false}" in h
assert "m_duoview_manual_fov_status{0}" in h
assert "get_xyz_head_movement_gains()" in h
for forbidden in (
    "m_duoview.retire(", "configure_duoview(", "destroy_swapchains(",
    "reinitialize_openxr(", "mono_generation(", "m_force_reset",
    "m_rendering_method->value() =", "m_xyz_headscale_x->value() =",
    "m_duoview_abort(", "invalidate_duoview_scene(",
):
    assert forbidden not in fg, f"dangerous manual side-effect {forbidden}"
print("PASS: Manual-on-click authoritative FUObjectArray recovery, original fast path.")
print("PASS: Writes BOTH exact MPC scalar values, verifies world readback, never fabricates success.")
print("PASS: Producer, RHI compositor, optical alignment, HUD, projection, eye tracking and XYZ are byte-identical to #165.")

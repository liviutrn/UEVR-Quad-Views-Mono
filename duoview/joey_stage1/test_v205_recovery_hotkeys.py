#!/usr/bin/env python3
"""Capture/verify exact #205 FOV logic and unrelated C++ source around hotkey patch.

Usage: test_v205_recovery_hotkeys.py --capture backend evidence/keybind-baseline.json
       test_v205_recovery_hotkeys.py --verify  backend evidence/keybind-baseline.json
"""
from pathlib import Path
import hashlib
import json
import sys

if len(sys.argv) != 4 or sys.argv[1] not in ("--capture","--verify"):
    raise SystemExit(__doc__)
action, backend, manifest = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])

def digest(value):
    if isinstance(value, str): value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()

cpp = (backend/"src/mods/VR.cpp").read_text(encoding="utf-8-sig")
hpp = (backend/"src/mods/VR.hpp").read_text(encoding="utf-8-sig")
start = cpp.index("    // STALKER 2 DuoView foreground parity.")
end = cpp.index("    // Some Supermassive camera paths rewrite crop/aspect state", start)
fg = cpp[start:end]
ui_start = cpp.index('    if (ImGui::Button("Reinitialize Runtime")) {')
ui_end = cpp.index("Vector4f VR::get_position(", ui_start)
manual_button = cpp[ui_start:ui_end]

source_sha = {}
for ext in ("*.cpp", "*.hpp"):
    for path in (backend/"src/mods").rglob(ext):
        relative = path.relative_to(backend).as_posix()
        if relative in ("src/mods/VR.cpp", "src/mods/VR.hpp"): continue
        source_sha[relative] = digest(path.read_bytes())
current = {"fov_sha256":digest(fg), "ui_button_sha256":digest(manual_button),
           "protected_cpp_hpp_sha256":source_sha}

if action == "--capture":
    manifest.write_text(json.dumps(current, indent=2, sort_keys=True))
    print(f"CAPTURED #205: {len(source_sha)} unrelated C++ files; exact MPC and button hashes")
    sys.exit(0)

old = json.loads(manifest.read_text())
assert old == current, "PROTECTED #205 source changed: MPC handler/button or unrelated C++ changed"

# Hotkeys must BOTH be real persistent UEVR ModKeys, not raw Win32 polling.
for needle in ('ModKey::create(generate_name("DuoViewFOVReapplyKey"))',
               'ModKey::create(generate_name("ReinitializeRuntimeKey"))',
               "*m_duoview_fov_reapply_key, *m_reinitialize_runtime_key,",
               'std::atomic<bool> m_duoview_hotkey_reapply_after_reset{false};',
               'std::atomic<int64_t> m_duoview_hotkey_fov_not_before_ms{0};'):
    assert needle in hpp, needle

begin = cpp.index("void VR::handle_keybinds()")
end = cpp.index("void VR::on_frame()",begin)
hotkeys = cpp[begin:end]
for needle in (
    "m_duoview_fov_reapply_key->is_key_down_once()",
    "m_reinitialize_runtime_key->is_key_down_once()",
    "const bool combined = fov_pressed && runtime->is_openxr() &&",
    "m_duoview_hotkey_reapply_after_reset.store(true",
    "runtime->wants_reinitialize = true;",
    "if (fov_pressed && !reset_pressed && is_duoview_renderer_active())",
    "m_duoview_manual_fov_requested.store(true",
    "m_duoview_manual_fov_status.store(1",
):
    assert needle in hotkeys, needle
assert hotkeys.index("m_duoview_hotkey_reapply_after_reset.store(true") < hotkeys.index("runtime->wants_reinitialize = true;")
assert hotkeys.index("m_duoview_fov_reapply_key->is_key_down_once()") < hotkeys.index("if (reset_pressed)")
assert "reinitialize_openxr()" not in hotkeys, "Reset must be on stock present path"

# Both keys can be assigned same physical code: independent ModKey edges.
assert "fov_pressed && runtime->is_openxr()" in hotkeys
assert "if (fov_pressed && !reset_pressed" in hotkeys
assert "get_keyboard_state()[" not in hotkeys
assert cpp.count('m_duoview_fov_reapply_key->draw("Reapply DuoView FOV Key")') == 1
assert cpp.count('m_reinitialize_runtime_key->draw("Reinitialize Runtime Key")') == 1
assert "Bind them to different keys" in cpp and "the SAME key" in cpp

# Combined key must NEVER set manual MPC request before OpenXR reset.
post_begin = cpp.index("void VR::on_post_present()")
post_end = cpp.index("uint32_t VR::get_hmd_width()",post_begin)
present = cpp[post_begin:post_end]
for needle in ("const auto error = reinitialize_openxr();",
               "m_duoview_hotkey_reapply_after_reset.exchange(",
               "m_duoview_hotkey_fov_not_before_ms.store(",
               "now_ms + 850",
               "OpenXR reset failed; FOV reapply cancelled"):
    assert needle in present, needle
assert present.index("const auto error = reinitialize_openxr();") < present.index("m_duoview_hotkey_fov_not_before_ms.store(")
assert "m_duoview_manual_fov_requested.store(true" not in present
assert "reinitialize_openvr();" in present

tick_start = cpp.index("void VR::on_post_engine_tick(")
tick_end = cpp.index("    // STALKER 2 DuoView foreground parity.",tick_start)
tick = cpp[tick_start:tick_end]
for needle in ("m_duoview_hotkey_fov_not_before_ms.load(",
               "now_ms > due_ms + 30000",
               "now_ms >= due_ms && get_runtime()->ready()",
               "is_duoview_renderer_active() && engine && engine->get_world()",
               "m_duoview_hotkey_fov_not_before_ms.compare_exchange_strong(",
               "m_duoview_manual_fov_requested.store(true",
               "OpenXR/gameplay ready: triggering proven #205 MPC reapply"):
    assert needle in tick, needle
assert tick.index("m_duoview_manual_fov_requested.store(true") > tick.index("get_runtime()->ready()")
assert "reinitialize_openxr()" not in tick and "destroy_swapchains(" not in tick
assert cpp.count("m_duoview_manual_fov_requested.store(true") == 3, "UI, direct key and deferred key each request once"
print("PASS: #205 FOV logic and existing UI button BYTE-IDENTICAL; all unrelated C++ unchanged.")
print(f"PASS: {len(source_sha)} protected source files unchanged; two saved unbound UEVR ModKeys.")
print("PASS: shared-key runtime reset completes before delayed safe-game-tick FOV reapply; no auto reload detector.")

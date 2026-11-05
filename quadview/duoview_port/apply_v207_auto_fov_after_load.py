#!/usr/bin/env python3
"""v207: press the proven "Reapply DuoView FOV" request automatically after a load.

Applies AFTER apply_v205_manual_fov_runtime_hotkeys.py. Edits only src/mods/VR.cpp.
When the active UWorld changes while DuoView ID6 is active (save load, level
travel, first activation) and it stays the same world for 1.5 s with a ready
runtime, it raises exactly the same request flag as the #205 button. That path
(class-registry lookup, FUObjectArray fallback, forced write, readback) is NOT
modified. If the request reports failure it is retried up to 3 times, 3 s
apart. The manual button and both hotkeys keep working unchanged.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_v207_auto_fov_after_load.py <backend>")
source = Path(sys.argv[1]) / "src/mods/VR.cpp"
text = source.read_text(encoding="utf-8-sig")

ANCHOR = "    // STALKER 2 DuoView foreground parity. Automatic only while ID6 is active.\n"
BLOCK = r'''    // v207 automatic load recovery: issue the proven manual FOV request once
    // per new world, after it has been stable for 1.5 s. Retries on failure.
    {
        static uintptr_t auto_fov_world{};
        static std::optional<sdk::object_liveness::Identity> auto_fov_identity{};
        static int64_t auto_fov_due_ms{};
        static int auto_fov_attempts{};
        const auto auto_now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
        auto* auto_world = engine != nullptr ? engine->get_world() : nullptr;
        if (!is_duoview_renderer_active() || auto_world == nullptr) {
            auto_fov_world = 0;
            auto_fov_identity.reset();
            auto_fov_due_ms = 0;
            auto_fov_attempts = 0;
        } else if (reinterpret_cast<uintptr_t>(auto_world) != auto_fov_world ||
                   !auto_fov_identity || !sdk::is_current_object(*auto_fov_identity)) {
            // Identity, not only the address: a new UWorld can reuse a freed one.
            const auto observed = sdk::observe_uobject(static_cast<sdk::UObjectBase*>(auto_world));
            auto_fov_world = reinterpret_cast<uintptr_t>(auto_world);
            if (observed) auto_fov_identity = observed->identity;
            else auto_fov_identity.reset();
            auto_fov_due_ms = auto_now_ms + 1500;
            auto_fov_attempts = 0;
        } else if (auto_fov_due_ms != 0 && auto_now_ms >= auto_fov_due_ms &&
                   get_runtime()->ready() &&
                   !m_duoview_manual_fov_requested.load(std::memory_order_acquire)) {
            const int status = m_duoview_manual_fov_status.load(std::memory_order_acquire);
            if (auto_fov_attempts > 0 && status == 2) {
                auto_fov_due_ms = 0;
                SPDLOG_INFO("[DuoView][AutoFOV] Verified after world change ({} attempt(s))", auto_fov_attempts);
            } else if (auto_fov_attempts >= 3) {
                auto_fov_due_ms = 0;
                SPDLOG_WARN("[DuoView][AutoFOV] Gave up after 3 attempts; use Reapply DuoView FOV manually");
            } else {
                ++auto_fov_attempts;
                auto_fov_due_ms = auto_now_ms + 3000;
                m_duoview_manual_fov_status.store(1, std::memory_order_release);
                m_duoview_manual_fov_requested.store(true, std::memory_order_release);
                SPDLOG_INFO("[DuoView][AutoFOV] New world stable: requesting proven FOV reapply (attempt {})",
                    auto_fov_attempts);
            }
        }
    }

'''

if text.count(ANCHOR) != 1:
    raise RuntimeError(f"Expected one foreground-parity anchor, found {text.count(ANCHOR)}")
if "[DuoView][AutoFOV]" in text:
    raise RuntimeError("v207 automatic FOV recovery already applied")
if "m_duoview_manual_fov_requested" not in text or "m_duoview_manual_fov_status" not in text:
    raise RuntimeError("Proven #205 manual FOV request flags missing")
source.write_text(text.replace(ANCHOR, BLOCK + ANCHOR, 1), encoding="utf-8", newline="")
print("PASS: v207 automatic world-change FOV request added; #205 MPC handler unchanged.")

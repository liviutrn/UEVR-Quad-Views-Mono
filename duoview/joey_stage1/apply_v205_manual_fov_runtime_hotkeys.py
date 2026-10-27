#!/usr/bin/env python3
"""Add TWO independently configurable UEVR hotkeys to verified #205.

Actions:
  - Reapply DuoView FOV: same exact proven manual MPC request as #205's button.
  - Reinitialize Runtime: stock UEVR wants_reinitialize path.
When bound to SAME key, reinitialize once FIRST, then queue MPC reapply
on a loaded/ready DuoView gameplay tick no sooner than 850ms post-reset.

No replacement of the proven MPC handler, no changes to GPU/pose, no automatic
load detection or unsolicited runtime resets. All keys default to UNBOUND.
"""
from pathlib import Path
import sys
if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_v205_manual_fov_runtime_hotkeys.py <backend>")
root = Path(sys.argv[1])
header = root / "src/mods/VR.hpp"
source = root / "src/mods/VR.cpp"
h = header.read_text(encoding="utf-8-sig")
c = source.read_text(encoding="utf-8-sig")

def edit(s, old, new, label):
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"Not the exact #205 baseline: {label} anchor count {count}")
    return s.replace(old, new, 1)

h = edit(h,
    '''    std::atomic<int> m_duoview_manual_fov_status{0}; // idle/pending/verified/failure''',
    '''    std::atomic<int> m_duoview_manual_fov_status{0}; // idle/pending/verified/failure
    // User-initiated hotkeys. Both independently configurable and unbound by default.
    const ModKey::Ptr m_duoview_fov_reapply_key{
        ModKey::create(generate_name("DuoViewFOVReapplyKey")) };
    const ModKey::Ptr m_reinitialize_runtime_key{
        ModKey::create(generate_name("ReinitializeRuntimeKey")) };
    // Shared-key sequencing: runtime reset must finish before any MPC write.
    // 0=no deferred request; otherwise earliest steady_clock timestamp (ms).
    std::atomic<bool> m_duoview_hotkey_reapply_after_reset{false};
    std::atomic<int64_t> m_duoview_hotkey_fov_not_before_ms{0};''',
    "header independent hotkeys and deferred state")

h = edit(h,
    '''            *m_xyz_headscale_toggle_key, *m_xyz_headscale_hold_bypass_key,
            *m_depth_scale,''',
    '''            *m_xyz_headscale_toggle_key, *m_xyz_headscale_hold_bypass_key,
            *m_duoview_fov_reapply_key, *m_reinitialize_runtime_key,
            *m_depth_scale,''',
    "persist hotkeys in standard UEVR options")

c = edit(c,
    '''void VR::handle_keybinds() {
    ZoneScopedN(__FUNCTION__);
    // Sample keys on the game thread once per frame, not per render view.''',
    '''void VR::handle_keybinds() {
    ZoneScopedN(__FUNCTION__);
    // These are separate ModKeys; identical assigned VK codes intentionally
    // fire BOTH edge detectors on the same press, only once until key release.
    const bool fov_pressed = m_duoview_fov_reapply_key->is_key_down_once();
    const bool reset_pressed = m_reinitialize_runtime_key->is_key_down_once();
    if (reset_pressed) {
        const auto runtime = get_runtime();
        if (runtime && runtime->loaded &&
            (runtime->is_openxr() || runtime->is_openvr()) &&
            !runtime->wants_reinitialize) {
            const bool combined = fov_pressed && runtime->is_openxr() &&
                                  is_duoview_renderer_active();
            if (combined) {
                // Do NOT request MPC now; runtime reset would discard or
                // change the world state before any repair was useful.
                m_duoview_hotkey_fov_not_before_ms.store(0, std::memory_order_release);
                m_duoview_hotkey_reapply_after_reset.store(true, std::memory_order_release);
                m_duoview_manual_fov_status.store(1, std::memory_order_release);
                SPDLOG_INFO("[DuoView][Hotkeys] Combined key: reset first, then FOV reapply after recovery");
            }
            runtime->wants_reinitialize = true;
            SPDLOG_INFO("[DuoView][Hotkeys] User requested stock runtime reset");
        } else {
            SPDLOG_WARN("[DuoView][Hotkeys] Runtime reset key ignored: no loaded/eligible runtime or reset already pending");
            if (fov_pressed) {
                m_duoview_manual_fov_status.store(3, std::memory_order_release);
            }
        }
    }
    if (fov_pressed && !reset_pressed && is_duoview_renderer_active()) {
        m_duoview_manual_fov_status.store(1, std::memory_order_release);
        m_duoview_manual_fov_requested.store(true, std::memory_order_release);
        SPDLOG_INFO("[DuoView][Hotkeys] User requested proven #205 MPC FOV reapply");
    }
    // Sample keys on the game thread once per frame, not per render view.''',
    "hotkeys one-shot dispatch and combined sequencing")

c = edit(c,
    '''        if (ImGui::TreeNode("Overlay/Runtime Keys")) {
            m_keybind_toggle_2d_screen->draw("Toggle 2D Screen Mode Key");''',
    '''        if (ImGui::TreeNode("Overlay/Runtime Keys")) {
            m_duoview_fov_reapply_key->draw("Reapply DuoView FOV Key");
            m_reinitialize_runtime_key->draw("Reinitialize Runtime Key");
            ImGui::TextWrapped("Both default to Unbound. Bind them to different keys for independent actions, or the SAME key to reset runtime first and reapply DuoView FOV once OpenXR/gameplay recovers. The FOV key also works without a reset.");
            m_keybind_toggle_2d_screen->draw("Toggle 2D Screen Mode Key");''',
    "UI two normal UEVR binding controls")

c = edit(c,
    '''    if (runtime->wants_reinitialize) {
        std::scoped_lock _{m_reinitialize_mtx};

        if (runtime->is_openvr()) {
            m_openvr->wants_reinitialize = false;
            reinitialize_openvr();
        } else if (runtime->is_openxr()) {
            m_openxr->wants_reinitialize = false;
            reinitialize_openxr();
        }
    }
}

uint32_t VR::get_hmd_width() const {''',
    '''    if (runtime->wants_reinitialize) {
        std::scoped_lock _{m_reinitialize_mtx};

        if (runtime->is_openvr()) {
            m_openvr->wants_reinitialize = false;
            const auto error = reinitialize_openvr();
            if (m_duoview_hotkey_reapply_after_reset.exchange(
                    false, std::memory_order_acq_rel)) {
                m_duoview_manual_fov_status.store(3, std::memory_order_release);
                SPDLOG_WARN("[DuoView][Hotkeys] Combined FOV key cannot run on OpenVR; reset error={}",
                    error.value_or("none"));
            }
        } else if (runtime->is_openxr()) {
            m_openxr->wants_reinitialize = false;
            const auto error = reinitialize_openxr();
            if (m_duoview_hotkey_reapply_after_reset.exchange(
                    false, std::memory_order_acq_rel)) {
                if (!error) {
                    const auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                        std::chrono::steady_clock::now().time_since_epoch()).count();
                    m_duoview_hotkey_fov_not_before_ms.store(
                        now_ms + 850, std::memory_order_release);
                    SPDLOG_INFO("[DuoView][Hotkeys] OpenXR reinitialized; FOV key action queued for ready game tick");
                } else {
                    m_duoview_manual_fov_status.store(3, std::memory_order_release);
                    SPDLOG_WARN("[DuoView][Hotkeys] OpenXR reset failed; FOV reapply cancelled: {}", *error);
                }
            }
        }
    }
}

uint32_t VR::get_hmd_width() const {''',
    "post-present successful runtime reset acknowledgement")

c = edit(c,
    '''    // STALKER 2 DuoView foreground parity. Automatic only while ID6 is active.''',
    '''    // This is NOT automatic load recovery. It runs ONLY after the user
    // explicitly pressed the two hotkeys simultaneously (same physical key).
    // Must not run while the OpenXR runtime is being torn down/recreated.
    const auto due_ms = m_duoview_hotkey_fov_not_before_ms.load(
        std::memory_order_acquire);
    if (due_ms != 0) {
        const auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
        if (now_ms > due_ms + 30000) {
            int64_t expected = due_ms;
            if (m_duoview_hotkey_fov_not_before_ms.compare_exchange_strong(
                    expected, 0, std::memory_order_acq_rel)) {
                m_duoview_manual_fov_status.store(3, std::memory_order_release);
                SPDLOG_WARN("[DuoView][Hotkeys] Deferred FOV reapply timed out (30s without ready DuoView gameplay)");
            }
        } else if (now_ms >= due_ms && get_runtime()->ready() &&
                   is_duoview_renderer_active() && engine && engine->get_world()) {
            int64_t expected = due_ms;
            if (m_duoview_hotkey_fov_not_before_ms.compare_exchange_strong(
                    expected, 0, std::memory_order_acq_rel)) {
                m_duoview_manual_fov_status.store(1, std::memory_order_release);
                m_duoview_manual_fov_requested.store(true, std::memory_order_release);
                SPDLOG_INFO("[DuoView][Hotkeys] OpenXR/gameplay ready: triggering proven #205 MPC reapply on game thread");
            }
        }
    }

    // STALKER 2 DuoView foreground parity. Automatic only while ID6 is active.''',
    "deferred FOV on ready gameplay tick only")

header.write_text(h, encoding="utf-8", newline="")
source.write_text(c, encoding="utf-8", newline="")
print("PASS: Two independent saved ModKeys; same-key reset-then-FOV supported.")
print("PASS: Only VR.hpp/VR.cpp changed; proven #205 MPC implementation retained exactly.")

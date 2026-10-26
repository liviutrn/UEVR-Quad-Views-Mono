#!/usr/bin/env python3
"""On save reload, permit ONE quarantined DuoView rearm after a stable new scene.

Only edits VR.cpp after the pinned stable Stage234 and foreground MPC patches.
Never restarts a healthy compositor. Does not change any user preference, modes,
poses, shaders, view numbering, resolution, gaze settings or eye calibration.
"""
import sys
from pathlib import Path
if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_save_reload_duoview_recovery.py <backend>")
target=Path(sys.argv[1])/"src/mods/VR.cpp"
s=target.read_text(encoding="utf-8-sig")
anchor="    // STALKER 2 DuoView foreground parity. Automatic only while ID6 is active."
if s.count(anchor)!=1:
    raise RuntimeError("Expected exact foreground MPC insertion marker exactly once")
if "[DuoView][SaveReload] Quarantined renderer rearmed" in s:
    raise RuntimeError("Reload recovery already applied")
block=r'''    // SAVE RELOAD RECOVERY. A transient compositor fault during quickload
    // can quarantine ID6 permanently, which also disables the foreground FOV
    // override. Only rearm after a detected world/pawn/load-pause transition,
    // a stable new playable pawn, and only ONCE per transition.
    {
        struct SaveReloadRecovery {
            uintptr_t world_id{};
            uintptr_t pawn_id{};
            std::optional<sdk::object_liveness::Identity> world_identity{};
            std::chrono::steady_clock::time_point last_tick{};
            std::chrono::steady_clock::time_point retry_until{};
            uint32_t stable_ticks{};
            bool initialized{};
            bool attempted{};
        };
        static SaveReloadRecovery reload{};
        if (!is_using_duoview_mono()) {
            reload = {};
        } else if (engine != nullptr) {
            auto* world = engine->get_world();
            const auto now = std::chrono::steady_clock::now();
            if (world != nullptr) {
                auto* gameplay = sdk::UGameplayStatics::get();
                auto* controller = gameplay != nullptr ?
                    gameplay->get_player_controller(world, 0) : nullptr;
                auto* pawn = controller != nullptr ?
                    controller->get_acknowledged_pawn() : nullptr;
                const auto observed_world = sdk::observe_uobject(
                    static_cast<sdk::UObjectBase*>(world));
                // APawn is only forward-declared in this source unit.
                // We compare its opaque pointer identity without dereference.
                if (observed_world &&
                    sdk::is_current_object(observed_world->identity)) {
                    const auto world_id = reinterpret_cast<uintptr_t>(world);
                    const auto pawn_id = reinterpret_cast<uintptr_t>(pawn);
                    const bool world_changed = reload.initialized &&
                        (reload.world_id != world_id ||
                         (reload.world_identity &&
                          !sdk::is_current_object(*reload.world_identity)));
                    const bool pawn_changed = reload.initialized &&
                        reload.pawn_id != pawn_id;
                    const bool resumed_after_loading = reload.initialized &&
                        reload.last_tick.time_since_epoch().count() != 0 &&
                        now - reload.last_tick > std::chrono::seconds(1);
                    const bool transitioned =
                        world_changed || pawn_changed || resumed_after_loading;
                    if (transitioned) {
                        reload.retry_until = now + std::chrono::seconds(20);
                        reload.stable_ticks = 0;
                        reload.attempted = false;
                        SPDLOG_INFO("[DuoView][SaveReload] scene lifecycle changed; "
                                    "armed one-time recovery if ID6 quarantines");
                    }
                    reload.world_id = world_id;
                    reload.pawn_id = pawn_id;
                    reload.world_identity = observed_world->identity;
                    reload.initialized = true;
                    reload.last_tick = now;
                    // Three resumed playable game ticks, not transient load
                    // frames. Protect against repeated unsafe reactivation.
                    if (pawn != nullptr && !transitioned && reload.stable_ticks < 3)
                        ++reload.stable_ticks;

                    if (m_duoview_quarantined.load(std::memory_order_acquire) &&
                        !reload.attempted &&
                        reload.stable_ticks >= 3 &&
                        now < reload.retry_until &&
                        get_openxr_runtime() != nullptr) {
                        reload.attempted = true;
                        m_duoview.retire();
                        m_duoview_candidate_key.store(
                            nullptr, std::memory_order_release);
                        m_duoview_frozen_key.store(
                            nullptr, std::memory_order_release);
                        get_openxr_runtime()->invalidate_duoview_scene();
                        configure_duoview();
                        m_duoview_quarantined.store(
                            false, std::memory_order_release);
                        SPDLOG_INFO("[DuoView][SaveReload] Quarantined renderer rearmed "
                                    "once after stable new world/pawn; user settings retained");
                    }
                }
            }
        }
    }

'''
s=s.replace(anchor,block+anchor,1)
target.write_text(s,encoding="utf-8",newline="")
print("Added one-time ID6 compositor-quarantine rearm following save reload.")

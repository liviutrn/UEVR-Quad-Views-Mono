#!/usr/bin/env python3
"""DuoView 186.1 reload continuity V2: preserve the working producer and GPU compositor.

Patch is applied AFTER the exact stable Build45 MPC and Build49 eye alignment.
The only runtime interventions are:
  * Retry FOV collection/reflection resolution after a world, pawn, or XR reset
  * Reassert the two proven MPC_FOV scalars after a playable tick gap / rebinding
  * One bounded ID6 retry ONLY after an observed save/world/pawn transition and prior XR submissions
Never calls State::retire, configure_duoview or GPU device/swapchain operations.
"""
import sys
from pathlib import Path
if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_reload_continuity_v2.py <backend>")
p = Path(sys.argv[1]) / "src/mods/VR.cpp"
s = p.read_text(encoding="utf-8-sig")
def one(old, new):
    global s
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f"Unexpected pinned Build45 patch source anchor (count={n}): {old[:110]!r}")
    s = s.replace(old, new, 1)

# Local state exists entirely within the established Build45 on_post_engine_tick
# patch. Do not add a new callback, frame hook, or compositor operation.
one(
    '''            float original_depth{};
            bool active{};''',
    '''            float original_depth{};
            uintptr_t pawn_id{};
            uint64_t runtime_epoch{};
            std::chrono::steady_clock::time_point last_tick{};
            bool force_reassert{};
            bool active{};'''
)
one(
    '''            if (!requested && !fg.active) return;

            auto* world = engine != nullptr ? engine->get_world() : nullptr;''',
    '''            if (!requested && !fg.active) return;
            const auto now = std::chrono::steady_clock::now();
            // The original Build45 conditional writer stays unchanged for all
            // healthy frames. Only reassert after a real engine-tick pause.
            if (requested && fg.active &&
                fg.last_tick.time_since_epoch().count() != 0 &&
                now - fg.last_tick > std::chrono::seconds(1)) {
                // A save can replace the live MPC instance and reflected
                // functions while retaining the same UWorld and pawn. Avoid
                // using stale reflection pointers on the first resumed tick.
                // Only this detected pause triggers the extra collection
                // lookup; healthy frames keep the proven Build45 fast path.
                fg.collection = nullptr;
                fg.collection_identity.reset();
                fg.library = nullptr;
                fg.library_identity.reset();
                fg.getter = nullptr;
                fg.setter = nullptr;
                fg.force_reassert = true;
                SPDLOG_INFO("[DuoView][ReloadV3] Long tick gap: MPC bindings refreshed");
            }
            fg.last_tick = now;

            auto* world = engine != nullptr ? engine->get_world() : nullptr;'''
)
one(
    '''            if (!requested && !fg.active) return;

            // Revalidate cached UObject identity each tick:''',
    '''            if (!requested && !fg.active) return;
            // The OpenXR runtime is recreated on Reset Runtime. No DuoView
            // resource or render state is touched: only cached MPC objects.
            const auto epoch = foreground_mpc_runtime_epoch();
            if (requested && fg.active && fg.runtime_epoch != epoch) {
                fg.collection = nullptr;
                fg.collection_identity.reset();
                fg.library = nullptr;
                fg.library_identity.reset();
                fg.getter = nullptr;
                fg.setter = nullptr;
                fg.runtime_epoch = epoch;
                fg.force_reassert = true;
                SPDLOG_INFO("[DuoView][ReloadV2] OpenXR reset: MPC cache refreshed");
            }

            // In a fast quickload the tick gap can be short, but the player
            // pawn is usually replaced. Only compare opaque pointer values;
            // APawn is not defined in this translation unit.
            if (requested && fg.active) {
                if (auto* gameplay = sdk::UGameplayStatics::get()) {
                    auto* controller = gameplay->get_player_controller(world, 0);
                    auto* pawn = controller != nullptr ?
                        controller->get_acknowledged_pawn() : nullptr;
                    const auto pawn_id = reinterpret_cast<uintptr_t>(pawn);
                    if (fg.pawn_id != 0 && pawn_id != fg.pawn_id) {
                        fg.force_reassert = true;
                        fg.collection = nullptr;
                        fg.collection_identity.reset();
                        fg.library = nullptr;
                        fg.library_identity.reset();
                        fg.getter = nullptr;
                        fg.setter = nullptr;
                        SPDLOG_INFO("[DuoView][ReloadV2] Pawn changed: MPC cache refreshed");
                    }
                    fg.pawn_id = pawn_id;
                }
            }

            // Revalidate cached UObject identity each tick:'''
)
one(
    '''            if (requested && !fg.active) {
                // Preserve the live baseline for restoration on mode exit.
                fg.original_enabled = current_enabled;
                fg.original_depth = current_depth;
                fg.active = true;''',
    '''            if (requested && !fg.active) {
                // Preserve the live baseline for restoration on mode exit.
                fg.original_enabled = current_enabled;
                fg.original_depth = current_depth;
                fg.runtime_epoch = epoch;
                fg.active = true;'''
)
one(
    '''            const bool enabled_ok = std::abs(current_enabled - wanted_enabled) <= epsilon ||
                                    write(L"IsFOVEnabled", wanted_enabled);
            const bool depth_ok = std::abs(current_depth - wanted_depth) <= epsilon ||
                                  write(L"DepthScale", wanted_depth);''',
    '''            const bool enabled_ok =
                (!fg.force_reassert && std::abs(current_enabled - wanted_enabled) <= epsilon) ||
                write(L"IsFOVEnabled", wanted_enabled);
            const bool depth_ok =
                (!fg.force_reassert && std::abs(current_depth - wanted_depth) <= epsilon) ||
                write(L"DepthScale", wanted_depth);'''
)
one(
    '''            if (!enabled_ok || !depth_ok) {
                SPDLOG_WARNING_EVERY_N_SEC(5,
                    "[DuoView][Foreground] MPC_FOV reconciliation failed; preserving baseline");
                return;
            }
            if (!requested) {''',
    '''            if (!enabled_ok || !depth_ok) {
                // A save may invalidate reflected functions while preserving
                // the MPC asset pointer. Retry on the next tick, retaining
                // original values rather than resetting the user settings.
                fg.collection = nullptr;
                fg.collection_identity.reset();
                fg.library = nullptr;
                fg.library_identity.reset();
                fg.getter = nullptr;
                fg.setter = nullptr;
                fg.force_reassert = true;
                SPDLOG_WARNING_EVERY_N_SEC(5,
                    "[DuoView][ReloadV2] MPC write failed; retrying cached bindings");
                return;
            }
            if (fg.force_reassert) {
                SPDLOG_INFO("[DuoView][ReloadV2] MPC_FOV restored: IsFOVEnabled={}, DepthScale={}",
                    wanted_enabled, wanted_depth);
                fg.force_reassert = false;
            }
            if (!requested) {'''
)
one(
    '''            if (!read(L"IsFOVEnabled", current_enabled) ||
                !read(L"DepthScale", current_depth)) return;''',
    '''            if (!read(L"IsFOVEnabled", current_enabled) ||
                !read(L"DepthScale", current_depth)) {
                fg.collection = nullptr;
                fg.collection_identity.reset();
                fg.library = nullptr;
                fg.library_identity.reset();
                fg.getter = nullptr;
                fg.setter = nullptr;
                fg.force_reassert = true;
                SPDLOG_WARNING_EVERY_N_SEC(5, "[DuoView][ReloadV2] MPC read failed; rebinding");
                return;
            }'''
)

# This quarantine recovery is inactive unless there has already been proof
# that the headset received real DuoView frames during this runtime. The
# existing duoview_abort() already retired the logical producer packet. Re-arm
# by lifting ONLY its atomic quarantine flag after the playable world/pawn is
# stable. Never retire the producer twice, touch command slots, reconfigure the
# swapchains, or change the user's mode/XYZ/eye preferences from game tick.
marker = '    // STALKER 2 DuoView foreground parity. Automatic only while ID6 is active.'
recovery = r'''    // DUOVIEW RELOAD V3: ONLY recover after an observed scene/load transition.
    // Known-good source producer, GPU compositor, and all user settings remain
    // completely untouched. Original fault handler already retired bad packet.
    {
        struct DuoReloadV2 {
            uint64_t last_copied{};
            uint32_t proven_copies{};
            uint32_t stable_playable_ticks{};
            uintptr_t observed_world{};
            uintptr_t observed_pawn{};
            uintptr_t stable_world{};
            uintptr_t stable_pawn{};
            bool initialized{};
            bool attempted{};
            std::chrono::steady_clock::time_point last_tick{};
            std::chrono::steady_clock::time_point reload_deadline{};
            std::chrono::steady_clock::time_point quarantine_since{};
        };
        static DuoReloadV2 recovery{};
        if (!is_using_duoview_mono()) {
            recovery = {};
        } else {
            const auto now = std::chrono::steady_clock::now();
            const auto xr = get_openxr_runtime();
            const uint64_t copied = xr != nullptr ?
                xr->duoview_copy_submits.load(std::memory_order_acquire) : 0;
            if (copied < recovery.last_copied) {
                // XR reset or user reset of delivery counters. Never retain
                // a retry authorization across a different counter lifetime.
                recovery = {};
            }

            auto* world = engine != nullptr ? engine->get_world() : nullptr;
            auto* gameplay = world != nullptr ? sdk::UGameplayStatics::get() : nullptr;
            auto* controller = gameplay != nullptr ?
                gameplay->get_player_controller(world, 0) : nullptr;
            auto* pawn = controller != nullptr ?
                controller->get_acknowledged_pawn() : nullptr;
            const auto world_id = reinterpret_cast<uintptr_t>(world);
            const auto pawn_id = reinterpret_cast<uintptr_t>(pawn);

            // A compositor fault alone NEVER authorizes automatic reactivation.
            // Only an observed world/pawn transition or prolonged load pause
            // opens a short window for one stable-scene retry.
            const bool world_changed = recovery.initialized &&
                recovery.observed_world != world_id;
            const bool pawn_changed = recovery.initialized &&
                recovery.observed_pawn != pawn_id;
            const bool resumed_after_loading = recovery.initialized &&
                recovery.last_tick.time_since_epoch().count() != 0 &&
                now - recovery.last_tick > std::chrono::seconds(1);
            const bool load_transition =
                world_changed || pawn_changed || resumed_after_loading;
            if (load_transition) {
                recovery.reload_deadline = now + std::chrono::seconds(15);
                recovery.attempted = false;
                recovery.stable_playable_ticks = 0;
                recovery.stable_world = 0;
                recovery.stable_pawn = 0;
                recovery.quarantine_since = {};
                SPDLOG_INFO("[DuoView][ReloadV3] Scene/load transition observed; "
                            "one-time rearm window opened");
            }
            recovery.observed_world = world_id;
            recovery.observed_pawn = pawn_id;
            recovery.initialized = true;
            recovery.last_tick = now;

            const bool quarantined =
                m_duoview_quarantined.load(std::memory_order_acquire);
            if (!quarantined && copied > recovery.last_copied) {
                const uint64_t delta = copied - recovery.last_copied;
                recovery.proven_copies = static_cast<uint32_t>(
                    std::min<uint64_t>(
                        static_cast<uint64_t>(recovery.proven_copies) + delta,
                        30));
            }
            recovery.last_copied = copied;
            if (!quarantined) {
                recovery.stable_playable_ticks = 0;
                recovery.stable_world = 0;
                recovery.stable_pawn = 0;
                recovery.quarantine_since = {};
            } else if (xr != nullptr && recovery.proven_copies >= 12 &&
                       !recovery.attempted &&
                       now < recovery.reload_deadline &&
                       world != nullptr && pawn != nullptr) {
                // Stable pointer identity for 12 playable ticks AND 350 ms.
                // Do not repeatedly rearm an actual GPU/producer failure.
                if (recovery.stable_world != world_id ||
                    recovery.stable_pawn != pawn_id) {
                    recovery.stable_playable_ticks = 0;
                    recovery.quarantine_since = now;
                }
                recovery.stable_world = world_id;
                recovery.stable_pawn = pawn_id;
                if (recovery.stable_playable_ticks < 12)
                    ++recovery.stable_playable_ticks;
                if (recovery.stable_playable_ticks >= 12 &&
                    now - recovery.quarantine_since >=
                        std::chrono::milliseconds(350)) {
                    recovery.attempted = true;
                    recovery.proven_copies = 0;
                    m_duoview_quarantined.store(false, std::memory_order_release);
                    SPDLOG_INFO("[DuoView][ReloadV3] Post-load recovery authorized: "
                                "rearmed ID6 without touching GPU or user options");
                }
            } else if (quarantined &&
                       (world == nullptr || pawn == nullptr)) {
                recovery.stable_playable_ticks = 0;
                recovery.stable_world = 0;
                recovery.stable_pawn = 0;
                recovery.quarantine_since = {};
            }
        }
    }

'''
one(marker, recovery + marker)
p.write_text(s, encoding="utf-8", newline="")
print("PASS: Build45 MPC refresh, reset epoch, post-load ONLY ID6 rearm with no GPU mutation.")

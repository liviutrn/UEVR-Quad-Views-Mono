#!/usr/bin/env python3
"""#165-only manual MPC_FOV recovery. NO automatic load handling or GPU changes.

Fixes the known #201 failure mechanism: after a load the UObjectHook class
registry can be incomplete. Preserve the last VALIDATED MPC asset full name;
only on user click, fall back to sdk::find_uobject(..., cached=false), which
enumerates the authoritative FUObjectArray. Do not invalidate a valid cache.
Give explicit failure or verified readback after EVERY manual attempt.
"""
from pathlib import Path
import sys
if len(sys.argv) != 2: raise SystemExit("Usage: apply_manual_fov_global_lookup_v165.py <backend>")
root = Path(sys.argv[1])
hpp = root / "src/mods/VR.hpp"
cpp = root / "src/mods/VR.cpp"
h = hpp.read_text(encoding="utf-8-sig")
s = cpp.read_text(encoding="utf-8-sig")

def once(source, old, new, label):
    count = source.count(old)
    if count != 1: raise RuntimeError(f"#165 anchor {label}: expected once, got {count}")
    return source.replace(old, new, 1)

h = once(h,
    '    std::atomic<bool> m_xyz_headscale_hold_bypass{ false };',
    '''    std::atomic<bool> m_xyz_headscale_hold_bypass{ false };
    // User-initiated MPC_FOV repair only; deliberately never drives a runtime reset.
    std::atomic<bool> m_duoview_manual_fov_requested{false};
    std::atomic<int> m_duoview_manual_fov_status{0}; // idle/pending/verified/failure
'''.rstrip(), "private UI event flags")

s = once(s,
    '''    if (ImGui::Button("Reinitialize Runtime")) {
        get_runtime()->wants_reinitialize = true;
    }
}''',
    '''    if (ImGui::Button("Reinitialize Runtime")) {
        get_runtime()->wants_reinitialize = true;
    }
    ImGui::SameLine();
    ImGui::BeginDisabled(!is_duoview_renderer_active());
    if (ImGui::Button("Reapply DuoView FOV")) {
        m_duoview_manual_fov_status.store(1, std::memory_order_release);
        m_duoview_manual_fov_requested.store(true, std::memory_order_release);
        SPDLOG_INFO("[DuoView][ManualFOV] Button clicked: requesting FOV refresh");
    }
    ImGui::EndDisabled();
    switch (m_duoview_manual_fov_status.load(std::memory_order_acquire)) {
    case 1: ImGui::TextDisabled("FOV reapply: pending game tick"); break;
    case 2: ImGui::TextUnformatted("FOV reapply: verified MPC 0 / 1 (check headset)"); break;
    case 3: ImGui::TextUnformatted("FOV reapply: failed (see log; retry in gameplay)"); break;
    }
}''', "runtime UI")

s = once(s,
    '''        static ForegroundMPCState fg{};
        const auto reconcile_foreground = [&]() {''',
    '''        static ForegroundMPCState fg{};
        // Retained across world changes, but ONLY used for an explicit click.
        // The original #165 live-object path is untouched on healthy frames.
        static std::wstring known_mpc_full_name{};
        const auto fail_manual = [&](const char* reason) {
            if (!m_duoview_manual_fov_requested.exchange(
                    false, std::memory_order_acq_rel)) return;
            m_duoview_manual_fov_status.store(3, std::memory_order_release);
            SPDLOG_WARN("[DuoView][ManualFOV] FAILED: {}", reason);
        };
        const auto reconcile_foreground = [&]() {''',
    "independent manual request outside disposable foreground state")

s = once(s,
    '''            if (!world) { fg = {}; return; }''',
    '''            if (!world) {
                fg = {};
                fail_manual("No active UWorld on game tick");
                return;
            }''', "missing world explicit failure")

s = once(s,
    '''                        if (unique_collection) {
                            SPDLOG_WARNING_EVERY_N_SEC(5,
                                "[DuoView][Foreground] ambiguous MPC_FOV asset; refusing override");
                            return;
                        }''',
    '''                        if (unique_collection) {
                            fail_manual("More than one MPC_FOV asset in live class registry");
                            SPDLOG_WARNING_EVERY_N_SEC(5,
                                "[DuoView][Foreground] ambiguous MPC_FOV asset; refusing override");
                            return;
                        }''', "ambiguous MPC explicitly failed")

s = once(s,
    '''                if (!unique_collection) return;
                const auto observed_world = sdk::observe_uobject(''',
    '''                if (!unique_collection &&
                    m_duoview_manual_fov_requested.load(std::memory_order_acquire) &&
                    !known_mpc_full_name.empty()) {
                    // The stock UObjectHook get_objects_by_class() may not
                    // include package assets loaded before or during travel.
                    // sdk::find_uobject(..., false) scans FUObjectArray and
                    // does NOT reuse its static name->object cache.
                    auto* recovered = sdk::find_uobject<sdk::UObject>(
                        known_mpc_full_name, false);
                    auto* expected_class = sdk::find_uobject<sdk::UClass>(
                        L"Class /Script/Engine.MaterialParameterCollection");
                    if (recovered && expected_class &&
                        recovered->get_class() == expected_class &&
                        recovered->get_full_name() == known_mpc_full_name) {
                        unique_collection = recovered;
                        SPDLOG_INFO("[DuoView][ManualFOV] Found MPC_FOV via global object array");
                    }
                }
                if (!unique_collection) {
                    fail_manual(known_mpc_full_name.empty()
                        ? "No MPC_FOV asset; no previously verified asset path"
                        : "MPC_FOV absent from both live registry and global object array");
                    return;
                }
                const auto observed_world = sdk::observe_uobject(''',
    "manual authoritative fallback only on class-cache miss")

s = once(s,
    '''                if (!observed_world || !observed_collection ||
                    !sdk::is_current_object(observed_world->identity) ||
                    !sdk::is_current_object(observed_collection->identity)) return;''',
    '''                if (!observed_world || !observed_collection ||
                    !sdk::is_current_object(observed_world->identity) ||
                    !sdk::is_current_object(observed_collection->identity)) {
                    fail_manual("New world or MPC_FOV asset failed SDK identity validation");
                    return;
                }''',
    "object-liveness negative reporting")

s = once(s,
    '''                fg.collection = unique_collection;
                fg.collection_identity = observed_collection->identity;''',
    '''                fg.collection = unique_collection;
                fg.collection_identity = observed_collection->identity;
                // MaterialParameterCollection is a package asset, not a
                // per-world instance. The SAME path can resolve a new live
                // object while the Kismet getter targets the current world.
                known_mpc_full_name = unique_collection->get_full_name();''',
    "remember exact canonical validated asset path")

s = once(s,
    '''                if (!library || !getter || !setter) return;''',
    '''                if (!library || !getter || !setter) {
                    fail_manual("KismetMaterialLibrary method binding not available");
                    return;
                }''',
    "binding error report")

s = once(s,
    '''                if (!observed || !sdk::is_current_object(observed->identity)) return;''',
    '''                if (!observed || !sdk::is_current_object(observed->identity)) {
                    fail_manual("KismetMaterialLibrary class default object failed validation");
                    return;
                }''',
    "class default object error report")

s = once(s,
    '''            if (!read(L"IsFOVEnabled", current_enabled) ||
                !read(L"DepthScale", current_depth)) return;''',
    '''            if (!read(L"IsFOVEnabled", current_enabled) ||
                !read(L"DepthScale", current_depth)) {
                fail_manual("Cannot read current-world MPC_FOV scalar values");
                return;
            }
            const bool manual = m_duoview_manual_fov_requested.load(
                std::memory_order_acquire);
            if (manual) {
                SPDLOG_INFO("[DuoView][ManualFOV] Before force write: enabled={} depth={} world={} asset={}",
                    current_enabled, current_depth, reinterpret_cast<uintptr_t>(world),
                    reinterpret_cast<uintptr_t>(fg.collection));
            }''',
    "pre-write telemetry and explicit read failure")

s = once(s,
    '''            const bool enabled_ok = std::abs(current_enabled - wanted_enabled) <= epsilon ||
                                    write(L"IsFOVEnabled", wanted_enabled);
            const bool depth_ok = std::abs(current_depth - wanted_depth) <= epsilon ||
                                  write(L"DepthScale", wanted_depth);''',
    '''            const bool enabled_ok =
                (!manual && std::abs(current_enabled - wanted_enabled) <= epsilon) ||
                write(L"IsFOVEnabled", wanted_enabled);
            const bool depth_ok =
                (!manual && std::abs(current_depth - wanted_depth) <= epsilon) ||
                write(L"DepthScale", wanted_depth);''',
    "manual force WRITE even if reads were already 0/1")

s = once(s,
    '''            if (!enabled_ok || !depth_ok) {
                SPDLOG_WARNING_EVERY_N_SEC(5,
                    "[DuoView][Foreground] MPC_FOV reconciliation failed; preserving baseline");
                return;
            }
            if (!requested) {''',
    '''            if (!enabled_ok || !depth_ok) {
                fail_manual("SetScalarParameterValue rejected a forced MPC_FOV write");
                SPDLOG_WARNING_EVERY_N_SEC(5,
                    "[DuoView][Foreground] MPC_FOV reconciliation failed; preserving baseline");
                return;
            }
            if (manual) {
                float after_enabled{}, after_depth{};
                const bool readback_ok =
                    read(L"IsFOVEnabled", after_enabled) &&
                    read(L"DepthScale", after_depth) &&
                    std::abs(after_enabled) <= epsilon &&
                    std::abs(after_depth - 1.0f) <= epsilon;
                if (readback_ok) {
                    if (m_duoview_manual_fov_requested.exchange(
                            false, std::memory_order_acq_rel)) {
                        m_duoview_manual_fov_status.store(2, std::memory_order_release);
                        SPDLOG_INFO("[DuoView][ManualFOV] VERIFIED: effective world MPC scalars 0 / 1");
                    }
                } else {
                    fail_manual("Post-write readback differs from 0 / 1");
                }
            }
            if (!requested) {''',
    "authoritative manual success only on readback")

s = once(s,
    '''        } catch (...) {
            SPDLOG_WARNING_EVERY_N_SEC(5,
                "[DuoView][Foreground] MPC access failed; refusing unsafe write");
        }
    }

    // Some Supermassive camera paths rewrite crop/aspect state during engine''',
    '''        } catch (...) {
            fail_manual("Unreal SDK exception during manual MPC operation");
            SPDLOG_WARNING_EVERY_N_SEC(5,
                "[DuoView][Foreground] MPC access failed; refusing unsafe write");
        }
    }

    // Some Supermassive camera paths rewrite crop/aspect state during engine''',
    "safe failure if SDK throws")

hpp.write_text(h, encoding="utf-8", newline="")
cpp.write_text(s, encoding="utf-8", newline="")
print("PASS: #165 exact source + manual world-MPC write/readback and FUObjectArray fallback; GPU/pose/XYZ untouched")

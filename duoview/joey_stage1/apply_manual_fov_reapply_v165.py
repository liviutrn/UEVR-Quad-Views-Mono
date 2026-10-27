#!/usr/bin/env python3
"""Only add manual MPC_FOV reapply to verified build #165.

Three narrow edits: two atomic UI flags in VR.hpp; an ImGui button alongside
Reinitialize Runtime in VR.cpp; manual on-post-engine-tick invalidation and
confirmation in the *unchanged* Build45 MPC_FOV handler. Neither reinitializes
OpenXR nor touches the DuoView compositor, rendering, HUD, eye alignment or XYZ.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_manual_fov_reapply_v165.py <backend>")
backend = Path(sys.argv[1])
h = backend / "src/mods/VR.hpp"
c = backend / "src/mods/VR.cpp"
header = h.read_text(encoding="utf-8-sig")
cpp = c.read_text(encoding="utf-8-sig")

def once(src, old, new, name):
    if src.count(old) != 1:
        raise RuntimeError(f"v165 manual FOV patch '{name}' anchor count {src.count(old)}")
    return src.replace(old, new, 1)

header = once(header,
    '    std::atomic<bool> m_xyz_headscale_hold_bypass{ false };',
    '''    std::atomic<bool> m_xyz_headscale_hold_bypass{ false };
    // Manual-only, non-destructive foreground FOV reapplication from UI.
    std::atomic<bool> m_duoview_manual_fov_requested{false};
    std::atomic<int> m_duoview_manual_fov_status{0}; // 0=idle, 1=pending, 2=verified, 3=failed
'''.rstrip(),
    "VR.hpp manual event")

cpp = once(cpp,
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
        SPDLOG_INFO("[DuoView][ManualFOV] User requested FOV reapply (no runtime reset)");
    }
    ImGui::EndDisabled();
    const auto manual_fov_status = m_duoview_manual_fov_status.load(std::memory_order_acquire);
    if (manual_fov_status == 1) ImGui::TextDisabled("DuoView FOV reapply: pending game tick");
    else if (manual_fov_status == 2) ImGui::TextUnformatted("DuoView FOV reapplied and verified: 0 / 1");
    else if (manual_fov_status == 3) ImGui::TextUnformatted("DuoView FOV could not be verified; retry after loading");
}''',
    "VR.cpp runtime UI button")

cpp = once(cpp,
    '''            float original_enabled{};
            float original_depth{};
            bool active{};''',
    '''            float original_enabled{};
            float original_depth{};
            bool manual_reapply_pending{};
            bool active{};''',
    "MPC manual flag")

cpp = once(cpp,
    '''            if (!requested && !fg.active) return;

            // Revalidate cached UObject identity each tick:''',
    '''            if (!requested && !fg.active) return;

            // ONLY a user click invalidates reflection bindings. Keep original
            // MPC scalar values so exiting ID6 still restores the old state.
            // This runs on the existing Unreal game tick, never the UI/render
            // thread, and never touches DuoView's GPU/pose/producer state.
            if (requested && m_duoview_manual_fov_requested.exchange(
                    false, std::memory_order_acq_rel)) {
                fg.collection = nullptr;
                fg.collection_identity.reset();
                fg.library = nullptr;
                fg.library_identity.reset();
                fg.getter = nullptr;
                fg.setter = nullptr;
                fg.manual_reapply_pending = true;
                SPDLOG_INFO("[DuoView][ManualFOV] Invalidated cached MPC bindings on game tick");
            }

            // Revalidate cached UObject identity each tick:''',
    "MPC manual cache invalidation")

cpp = once(cpp,
    '''            const bool enabled_ok = std::abs(current_enabled - wanted_enabled) <= epsilon ||
                                    write(L"IsFOVEnabled", wanted_enabled);
            const bool depth_ok = std::abs(current_depth - wanted_depth) <= epsilon ||
                                  write(L"DepthScale", wanted_depth);''',
    '''            const bool enabled_ok =
                (!fg.manual_reapply_pending && std::abs(current_enabled - wanted_enabled) <= epsilon) ||
                write(L"IsFOVEnabled", wanted_enabled);
            const bool depth_ok =
                (!fg.manual_reapply_pending && std::abs(current_depth - wanted_depth) <= epsilon) ||
                write(L"DepthScale", wanted_depth);''',
    "MPC force write only on manual request")

cpp = once(cpp,
    '''            if (!enabled_ok || !depth_ok) {
                SPDLOG_WARNING_EVERY_N_SEC(5,
                    "[DuoView][Foreground] MPC_FOV reconciliation failed; preserving baseline");
                return;
            }
            if (!requested) {''',
    '''            if (!enabled_ok || !depth_ok) {
                if (fg.manual_reapply_pending) {
                    fg.manual_reapply_pending = false;
                    m_duoview_manual_fov_status.store(3, std::memory_order_release);
                    SPDLOG_WARNING_EVERY_N_SEC(5,
                        "[DuoView][ManualFOV] Setter rejected manual FOV refresh");
                }
                SPDLOG_WARNING_EVERY_N_SEC(5,
                    "[DuoView][Foreground] MPC_FOV reconciliation failed; preserving baseline");
                return;
            }
            if (fg.manual_reapply_pending) {
                float confirmed_enabled{}, confirmed_depth{};
                const bool confirmed = read(L"IsFOVEnabled", confirmed_enabled) &&
                    read(L"DepthScale", confirmed_depth) &&
                    std::abs(confirmed_enabled - 0.0f) <= epsilon &&
                    std::abs(confirmed_depth - 1.0f) <= epsilon;
                fg.manual_reapply_pending = false;
                m_duoview_manual_fov_status.store(confirmed ? 2 : 3, std::memory_order_release);
                if (confirmed) {
                    SPDLOG_INFO("[DuoView][ManualFOV] CONFIRMED IsFOVEnabled=0 DepthScale=1");
                } else {
                    SPDLOG_WARNING_EVERY_N_SEC(5,
                        "[DuoView][ManualFOV] Verification failed after manual reapply");
                }
            }
            if (!requested) {''',
    "MPC manual readback confirmation")

cpp = once(cpp,
    '''        } catch (...) {
            SPDLOG_WARNING_EVERY_N_SEC(5,
                "[DuoView][Foreground] MPC access failed; refusing unsafe write");
        }
    }

    // Some Supermassive camera paths rewrite crop/aspect state during engine''',
    '''        } catch (...) {
            if (fg.manual_reapply_pending) {
                fg.manual_reapply_pending = false;
                m_duoview_manual_fov_status.store(3, std::memory_order_release);
                // Never retain reflected pointers after an exception.
                fg.collection = nullptr;
                fg.collection_identity.reset();
                fg.library = nullptr;
                fg.library_identity.reset();
                fg.getter = nullptr;
                fg.setter = nullptr;
            }
            SPDLOG_WARNING_EVERY_N_SEC(5,
                "[DuoView][Foreground] MPC access failed; refusing unsafe write");
        }
    }

    // Some Supermassive camera paths rewrite crop/aspect state during engine''',
    "MPC exception safety")

h.write_text(header, encoding="utf-8", newline="")
c.write_text(cpp, encoding="utf-8", newline="")
print("v165 ManualFOV: patched only VR.hpp and VR.cpp; original rendering and XYZ untouched.")

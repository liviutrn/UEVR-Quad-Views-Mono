#!/usr/bin/env python3
"""DuoView FOV load recovery (after #380 headset, 19 Nov 2026).

Symptom [headset #380]: after a savegame load / new game the hands+weapon FOV breaks; AutoFOV and the
"Reapply DuoView FOV" button both log "FAILED: Unreal SDK exception during manual MPC operation" on
every attempt, and "[Foreground] MPC access failed" repeats every 5 s until the game is closed.
Log: builds/380-evidence/log_380_headset.txt (first world verified 22:44:26; fault at the 22:56:57 load,
right after an "attempted dereference of null pointer"; never recovers).

Cause [source]: the foreground MPC state `fg` is a function-static cache (world, MPC_FOV asset,
KismetMaterialLibrary CDO + UFunctions, baseline scalars). The catch(...) around reconcile_foreground()
only logged; it never cleared `fg`. A fault during level travel therefore left the cache in whatever
state it had, and every later tick/click reused it and faulted again. "Reinitialize runtime" cannot
help: the cache lives in the mod, not in the OpenXR runtime.

Fix: (1) on any fault drop the whole cache (`fg = {}`) so the next tick/click rebuilds it from a fresh
lookup, exactly like the first world; (2) record the last stage reached and log it on a fault, so if a
fresh lookup still faults we know which step (world / registry / identity / library / read / write).
No change to the healthy path: same lookups, same writes, same verification.
"""
from pathlib import Path
import sys

FN_START = 'static std::wstring known_mpc_full_name{};'

EDITS = [
    # stage marker variable (declared before the lambdas that capture it by reference)
    (FN_START,
     FN_START + '\n'
     '        // Load recovery: last reconcile stage reached, logged if an SDK fault escapes.\n'
     '        const char* fg_stage = "start";'),
    ('            auto* world = engine != nullptr ? engine->get_world() : nullptr;\n'
     '            if (!world) {\n'
     '                fg = {};',
     '            fg_stage = "get_world";\n'
     '            auto* world = engine != nullptr ? engine->get_world() : nullptr;\n'
     '            if (!world) {\n'
     '                fg = {};'),
    ('            const uintptr_t world_id = reinterpret_cast<uintptr_t>(world);\n'
     '            if (fg.world_id != 0 &&',
     '            fg_stage = "validate_cache";\n'
     '            const uintptr_t world_id = reinterpret_cast<uintptr_t>(world);\n'
     '            if (fg.world_id != 0 &&'),
    ('                sdk::UObject* unique_collection{};\n'
     '                for (auto* object : get_live_objects_by_class_name(',
     '                fg_stage = "registry";\n'
     '                sdk::UObject* unique_collection{};\n'
     '                for (auto* object : get_live_objects_by_class_name('),
    ('                    auto* recovered = sdk::find_uobject<sdk::UObject>(\n'
     '                        known_mpc_full_name, false);',
     '                    fg_stage = "global_lookup";\n'
     '                    auto* recovered = sdk::find_uobject<sdk::UObject>(\n'
     '                        known_mpc_full_name, false);'),
    ('                const auto observed_world = sdk::observe_uobject(\n'
     '                    static_cast<sdk::UObjectBase*>(world));',
     '                fg_stage = "identity";\n'
     '                const auto observed_world = sdk::observe_uobject(\n'
     '                    static_cast<sdk::UObjectBase*>(world));'),
    ('            if (!fg.library || !fg.library_identity ||\n'
     '                !sdk::is_current_object(*fg.library_identity)) {',
     '            fg_stage = "library";\n'
     '            if (!fg.library || !fg.library_identity ||\n'
     '                !sdk::is_current_object(*fg.library_identity)) {'),
    ('            float current_enabled{}, current_depth{};\n',
     '            fg_stage = "read";\n'
     '            float current_enabled{}, current_depth{};\n'),
    ('            const bool enabled_ok =\n',
     '            fg_stage = "write";\n'
     '            const bool enabled_ok =\n'),
    ('            if (manual) {\n'
     '                float after_enabled{}, after_depth{};',
     '            fg_stage = "readback";\n'
     '            if (manual) {\n'
     '                float after_enabled{}, after_depth{};'),
    # the actual fix: drop the cache on a fault
    ('        try {\n'
     '            reconcile_foreground();\n'
     '        } catch (...) {\n'
     '            fail_manual("Unreal SDK exception during manual MPC operation");\n'
     '            SPDLOG_WARNING_EVERY_N_SEC(5,\n'
     '                "[DuoView][Foreground] MPC access failed; refusing unsafe write");\n'
     '        }',
     '        try {\n'
     '            reconcile_foreground();\n'
     '        } catch (...) {\n'
     '            if (m_duoview_manual_fov_requested.load(std::memory_order_acquire)) {\n'
     '                SPDLOG_WARN("[DuoView][ManualFOV] SDK fault at stage={}; clearing MPC cache", fg_stage);\n'
     '            }\n'
     '            fail_manual("Unreal SDK exception during manual MPC operation");\n'
     '            // A level load can leave a cached UObject/world stale. Never keep a cache that\n'
     '            // faulted: the next tick/click rebuilds it from a fresh lookup (as in the first world).\n'
     '            fg = {};\n'
     '            SPDLOG_WARNING_EVERY_N_SEC(5,\n'
     '                "[DuoView][Foreground] MPC access failed at stage={}; cache cleared, will rebuild", fg_stage);\n'
     '        }'),
]


def main() -> int:
    if len(sys.argv) != 2:
        print('usage: apply_fov_load_recovery.py <backend>')
        return 2
    path = Path(sys.argv[1]) / 'src' / 'mods' / 'VR.cpp'
    text = path.read_text(encoding='utf-8')
    if 'fg_stage' in text:
        print('FAIL: FOV load recovery already applied')
        return 1
    for old, new in EDITS:
        n = text.count(old)
        if n != 1:
            print(f'FAIL: anchor found {n}x (need 1): {old.splitlines()[0].strip()[:90]}')
            return 1
        text = text.replace(old, new)
    # contracts on the result
    checks = {
        'cache cleared in catch': text.count('            fg = {};\n            SPDLOG_WARNING_EVERY_N_SEC(5,\n'
                                             '                "[DuoView][Foreground] MPC access failed at stage={}') == 1,
        'stage markers': text.count('fg_stage = "') == 10,
        'old catch gone': 'MPC access failed; refusing unsafe write' not in text,
        'healthy path verify kept': text.count('[DuoView][ManualFOV] VERIFIED: effective world MPC scalars 0 / 1') == 1,
    }
    bad = [k for k, ok in checks.items() if not ok]
    if bad:
        print('FAIL: contracts: ' + ', '.join(bad))
        return 1
    path.write_text(text, encoding='utf-8', newline='')
    print('PASS: FOV load recovery (cache cleared on SDK fault, stage logged); healthy path unchanged')
    return 0


if __name__ == '__main__':
    sys.exit(main())

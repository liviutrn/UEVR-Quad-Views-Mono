#!/usr/bin/env python3
"""Apply ONLY the STALKER 2 DuoView foreground MPC override to v186.1 Glamarye.

This is intentionally separate from the existing, unchanged v186.1 Stage 1/2-4
patch. It edits precisely one generated Joey source file: src/mods/VR.cpp.
There are no UI, compositor, gaze, shader, overlay, or config modifications.
"""
import argparse
from pathlib import Path

ANCHOR = """    // Some Supermassive camera paths rewrite crop/aspect state during engine
"""

BLOCK = r'''    // STALKER 2 DuoView foreground parity. Automatic only while ID6 is active.
    // The game can overwrite MPC_FOV after a tick, so merely setting these
    // scalars once on entry is not robust. Read each tick but only WRITE on
    // observed drift. Resolve/capture the MPC only once per live UObject.
    // Both source views consume the same world MPC; no per-view FOV rewriting.
    {
        struct ForegroundMPCState {
            uintptr_t world_id{};
            std::optional<sdk::object_liveness::Identity> world_identity{};
            sdk::UObject* collection{};
            std::optional<sdk::object_liveness::Identity> collection_identity{};
            sdk::UObject* library{};
            std::optional<sdk::object_liveness::Identity> library_identity{};
            sdk::UFunction* getter{};
            sdk::UFunction* setter{};
            float original_enabled{};
            float original_depth{};
            bool active{};
        };
        static ForegroundMPCState fg{};
        const auto reconcile_foreground = [&]() {
            const bool requested = is_duoview_renderer_active();
            if (!requested && !fg.active) return;

            auto* world = engine != nullptr ? engine->get_world() : nullptr;
            if (!world) { fg = {}; return; }

            const uintptr_t world_id = reinterpret_cast<uintptr_t>(world);
            if (fg.world_id != 0 &&
                (fg.world_id != world_id || !fg.world_identity ||
                 !sdk::is_current_object(*fg.world_identity))) {
                // Never write saved scalars into another game world.
                fg = {};
            }
            if (!requested && !fg.active) return;

            // Revalidate cached UObject identity each tick: cached pointers
            // must never be used after GC, including an in-world asset reload.
            if (fg.collection &&
                (!fg.collection_identity ||
                 !sdk::is_current_object(*fg.collection_identity))) {
                fg = {};
            }
            if (!requested && !fg.active) return;
            if (!fg.collection) {
                sdk::UObject* unique_collection{};
                for (auto* object : get_live_objects_by_class_name(
                         L"Class /Script/Engine.MaterialParameterCollection")) {
                    if (object && object->get_full_name().ends_with(L".MPC_FOV")) {
                        if (unique_collection) {
                            SPDLOG_WARNING_EVERY_N_SEC(5,
                                "[DuoView][Foreground] ambiguous MPC_FOV asset; refusing override");
                            return;
                        }
                        unique_collection = object;
                    }
                }
                if (!unique_collection) return;
                const auto observed_world = sdk::observe_uobject(
                    static_cast<sdk::UObjectBase*>(world));
                const auto observed_collection = sdk::observe_uobject(
                    static_cast<sdk::UObjectBase*>(unique_collection));
                if (!observed_world || !observed_collection ||
                    !sdk::is_current_object(observed_world->identity) ||
                    !sdk::is_current_object(observed_collection->identity)) return;
                fg.world_id = world_id;
                fg.world_identity = observed_world->identity;
                fg.collection = unique_collection;
                fg.collection_identity = observed_collection->identity;
            }

            // Reflection method lookups are also cached per activation;
            // only cheap UObject identity checks remain on the fast path.
            if (!fg.library || !fg.library_identity ||
                !sdk::is_current_object(*fg.library_identity)) {
                auto* klass = sdk::find_uobject<sdk::UClass>(
                    L"Class /Script/Engine.KismetMaterialLibrary");
                auto* library = klass != nullptr ? klass->get_class_default_object() : nullptr;
                auto* getter = klass != nullptr ? klass->find_function(L"GetScalarParameterValue") : nullptr;
                auto* setter = klass != nullptr ? klass->find_function(L"SetScalarParameterValue") : nullptr;
                if (!library || !getter || !setter) return;
                const auto observed = sdk::observe_uobject(
                    static_cast<sdk::UObjectBase*>(library));
                if (!observed || !sdk::is_current_object(observed->identity)) return;
                fg.library = library;
                fg.library_identity = observed->identity;
                fg.getter = getter;
                fg.setter = setter;
            }

            const auto read = [&](std::wstring_view parameter, float& value) {
                sdk::ReflectedNameCall call{fg.getter};
                if (!call.write(L"WorldContextObject", static_cast<sdk::UObject*>(world)) ||
                    !call.write(L"Collection", fg.collection) ||
                    !call.write_name(L"ParameterName", sdk::OwnedFName{parameter}) ||
                    !call.field(L"ReturnValue", sizeof(float)) ||
                    !call.invoke(fg.library)) return false;
                value = call.read<float>(L"ReturnValue");
                return std::isfinite(value);
            };
            const auto write = [&](std::wstring_view parameter, float value) {
                sdk::ReflectedNameCall call{fg.setter};
                return call.write(L"WorldContextObject", static_cast<sdk::UObject*>(world)) &&
                    call.write(L"Collection", fg.collection) &&
                    call.write_name(L"ParameterName", sdk::OwnedFName{parameter}) &&
                    call.write(L"ParameterValue", value) && call.invoke(fg.library);
            };

            float current_enabled{}, current_depth{};
            if (!read(L"IsFOVEnabled", current_enabled) ||
                !read(L"DepthScale", current_depth)) return;

            if (requested && !fg.active) {
                // Preserve the live baseline for restoration on mode exit.
                fg.original_enabled = current_enabled;
                fg.original_depth = current_depth;
                fg.active = true;
                SPDLOG_INFO("[DuoView][Foreground] MPC_FOV activated; cached asset; "
                            "conditional updates only (original IsFOVEnabled={}, DepthScale={})",
                            fg.original_enabled, fg.original_depth);
            }
            const float wanted_enabled = requested ? 0.0f : fg.original_enabled;
            const float wanted_depth = requested ? 1.0f : fg.original_depth;
            constexpr float epsilon = 0.0001f;

            // No setter calls once the game values are already correct.
            // If STALKER 2 rewrites either value every tick, correct it in
            // this SAME tick to preserve the proven v186.1 foreground fix.
            const bool enabled_ok = std::abs(current_enabled - wanted_enabled) <= epsilon ||
                                    write(L"IsFOVEnabled", wanted_enabled);
            const bool depth_ok = std::abs(current_depth - wanted_depth) <= epsilon ||
                                  write(L"DepthScale", wanted_depth);
            if (!enabled_ok || !depth_ok) {
                SPDLOG_WARNING_EVERY_N_SEC(5,
                    "[DuoView][Foreground] MPC_FOV reconciliation failed; preserving baseline");
                return;
            }
            if (!requested) {
                fg = {};
                SPDLOG_INFO("[DuoView][Foreground] restored original MPC_FOV scalars");
            }
        };
        try {
            reconcile_foreground();
        } catch (...) {
            SPDLOG_WARNING_EVERY_N_SEC(5,
                "[DuoView][Foreground] MPC access failed; refusing unsafe write");
        }
    }

'''
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", type=Path)
    args = parser.parse_args()
    file = args.backend / "src/mods/VR.cpp"
    original = file.read_text(encoding="utf-8-sig")
    if original.count(ANCHOR) != 1:
        raise RuntimeError("Not the exact pinned Joey baseline, or already patched")
    if "[DuoView][Foreground] MPC_FOV activated" in original:
        raise RuntimeError("Foreground patch already present")
    result = original.replace(ANCHOR, BLOCK + ANCHOR, 1)
    file.write_text(result, encoding="utf-8", newline="")
    print("Applied minimal STALKER 2 DuoView MPC parity to src/mods/VR.cpp only.")

if __name__ == "__main__":
    main()

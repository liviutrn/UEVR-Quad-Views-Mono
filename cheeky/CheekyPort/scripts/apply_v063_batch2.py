#!/usr/bin/env python3
"""Cheeky 0.6.3 Batch 2; apply AFTER every pinned #84 patcher.

No direct edits to OpenNR #84 or other programs. Fail closed on every anchor,
stage changes in memory, then write together. C2 ABI header copied unmodified.
"""
from pathlib import Path
from shutil import copyfile
import sys

root=Path(sys.argv[1]).resolve()
here=Path(__file__).resolve().parents[1]
paths=("src/settings.hpp","src/settings.cpp","src/hooks.cpp",
       "src/dlss_nr.cpp","uevr/settings_fields.inc","uevr/runtime.cpp",
       "uevr/scripts/cheeky_foveated_dlss.lua","src/nr_probe_capture.hpp")
files={name:(root/name).read_text(encoding="utf-8") for name in paths}
def change(path,old,new,label):
    if path not in files: raise RuntimeError("Unstaged path "+path)
    n=files[path].count(old)
    if n!=1: raise RuntimeError(f"Batch2 {label}: anchor {n}, expected 1; NOTHING written")
    files[path]=files[path].replace(old,new,1)
def change_range(path,begin,end,rewrite,label):
    source=files[path];a=source.find(begin)
    b=source.find(end,a+len(begin)) if a>=0 else -1
    if a<0 or b<0 or source.find(begin,a+1)>=0:
        raise RuntimeError(f"Batch2 {label}: non-unique range; NOTHING written")
    old=source[a:b]
    new=rewrite(old)
    files[path]=source[:a]+new+source[b:]

# All three safety/behavior switches default ON per Claude's explicit
# exceptions. Other experimental mode changes remain off by default.
change("src/settings.hpp",
       "    std::uint32_t nr_vram_guard_mib{1536U};",
       """    std::uint32_t nr_vram_guard_mib{1536U};
    bool nr_use_source_roles{true};
    bool nr_alloc_admission{true};
    bool nr_feature_reuse{true};""","persisted safety switches")
change("src/settings.cpp",
       "std::atomic<std::uint32_t> nr_vram_guard_mib{1536U};",
       """std::atomic<std::uint32_t> nr_vram_guard_mib{1536U};
std::atomic<bool> nr_use_source_roles{true}, nr_alloc_admission{true}, nr_feature_reuse{true};""",
       "atomic safety switches")
change("src/settings.cpp",
       "    settings.nr_vram_guard_mib = nr_vram_guard_mib.load(std::memory_order_acquire);",
       """    settings.nr_vram_guard_mib = nr_vram_guard_mib.load(std::memory_order_acquire);
    settings.nr_use_source_roles = nr_use_source_roles.load(std::memory_order_acquire);
    settings.nr_alloc_admission = nr_alloc_admission.load(std::memory_order_acquire);
    settings.nr_feature_reuse = nr_feature_reuse.load(std::memory_order_acquire);""",
       "current safety settings")
change("src/settings.cpp",
       """    nr_vram_guard_mib.store((std::clamp)(settings.nr_vram_guard_mib, 512U, 4096U),
        std::memory_order_release);""",
       """    nr_vram_guard_mib.store((std::clamp)(settings.nr_vram_guard_mib, 512U, 4096U),
        std::memory_order_release);
    nr_use_source_roles.store(settings.nr_use_source_roles, std::memory_order_release);
    nr_alloc_admission.store(settings.nr_alloc_admission, std::memory_order_release);
    nr_feature_reuse.store(settings.nr_feature_reuse, std::memory_order_release);""",
       "publish safety settings")
change("uevr/settings_fields.inc",
       'CHEEKY_SETTING("NrVramGuardMiB", nr_vram_guard_mib)',
       '''CHEEKY_SETTING("NrVramGuardMiB", nr_vram_guard_mib)
CHEEKY_SETTING("NrUseSourceRoles", nr_use_source_roles)
CHEEKY_SETTING("NrAllocAdmission", nr_alloc_admission)
CHEEKY_SETTING("NrFeatureReuse", nr_feature_reuse)''',
       "persist 3 fields in UEVR")
change("uevr/runtime.cpp",
       'std::string_view(name) != "NrDuoFoveaSizeHint" && std::string_view(name) != "NrVramGuardMiB") settings.field = stored.field;',
       'std::string_view(name) != "NrDuoFoveaSizeHint" && std::string_view(name) != "NrVramGuardMiB" && std::string_view(name) != "NrUseSourceRoles" && std::string_view(name) != "NrAllocAdmission" && std::string_view(name) != "NrFeatureReuse") settings.field = stored.field;',
       "protect preferences from NR templates")
change("uevr/scripts/cheeky_foveated_dlss.lua",
       '        slider("Max VRAM admission reserve (MiB)", "NrVramGuardMiB", 512, 4096, true)',
       '''        slider("Max VRAM admission reserve (MiB)", "NrVramGuardMiB", 512, 4096, true)
        if draft.NrUseSourceRoles ~= nil then
            checkbox("Use UEVR source roles (C2; automatic fallback)", "NrUseSourceRoles")
            checkbox("Admission guard before NGX allocation", "NrAllocAdmission")
            checkbox("Reuse retired NGX model for 10 s (2 slots)", "NrFeatureReuse")
        end''',
       "safety UI")

# C2 ABI copied verbatim, not reinterpreted or changed in Cheeky.
change("src/settings.cpp",
       '#include "settings.hpp"',
       '''#include "settings.hpp"
#include "runtime.hpp"
#include "uevr_source_roles_consumer_v1.hpp"''',
       "source role consumer includes")
def splice_c2(old):
    anchor="    const auto role = cheeky_nr_source_role_for(settings, view_id);"
    if old.count(anchor)!=1: raise RuntimeError("C2 selection missing role anchor")
    replacement="""    // No stale UEVR handle guess: C2 V1 is indexed by the physical
    // NVSDK_NGX_Handle*, with legacy geometry as an intentional fallback.
    const auto c2 = settings.nr_use_source_roles
        ? c2_roles().Query(view_id & ~(1ULL << 63U)) : C2RoleDecision{};
    if (settings.nr_use_source_roles && c2_roles().DueForLog())
        trace_event("[CheekyNR][C2] version=1 used=%llu fallback=%llu gen=%llu",
            static_cast<unsigned long long>(c2_roles().Used()),
            static_cast<unsigned long long>(c2_roles().Fallback()),
            static_cast<unsigned long long>(c2_roles().Generation()));
    if (c2.transition) return {}; // retire old family on collector before any reallocation
    if (c2.authoritative &&
        ((settings.nr_target_mode < 2U && c2.method != 6U) ||
         (settings.nr_target_mode >= 2U && c2.method != 7U)))
        return {}; // do not run TriView policy on a DuoView source or vice versa
    const auto role = c2.authoritative ? c2.role_mask :
        cheeky_nr_source_role_for(settings, view_id);"""
    return old.replace(anchor,replacement,1)
change_range("src/settings.cpp","CheekyNrSelection cheeky_nr_selection(",
             "std::uint32_t cheeky_nr_selected_passes(",splice_c2,
             "authoritative C2 selection with fallback and transition")

# C5: never remove/disable MinHook NGX export detours once any other hooker
# may have chained them. The 'started' flag gates runtime behavior instead.
change("src/hooks.cpp",
       '''void shutdown_direct_export_hooks() noexcept {
    afw_note_warp_observer(false);
    if (!minhook_initialized.exchange(false, std::memory_order_acq_rel)) {
        return;
    }
    AcquireSRWLockExclusive(&direct_hook_lock);
    // Recorded marker work can outlive host detach. Keep its Execute/Reset
    // observer installed so retained GPU resources can still be retired safely.
    if (native_observer_status().ready) {
        for (std::size_t i = 0; i < direct_hook_count; ++i) {
            static_cast<void>(MH_DisableHook(direct_hook_targets[i]));
            static_cast<void>(MH_RemoveHook(direct_hook_targets[i]));
        }
    } else {
        static_cast<void>(MH_DisableHook(MH_ALL_HOOKS));
        static_cast<void>(MH_Uninitialize());
    }
    direct_hook_count = 0U;
    direct_hook_targets.fill(nullptr);
    direct_hook_originals.fill(nullptr);
    ReleaseSRWLockExclusive(&direct_hook_lock);

    AcquireSRWLockExclusive(&runtime_stability_lock);
    public_runtime_stability = {};
    core_runtime_stability = {};
    ReleaseSRWLockExclusive(&runtime_stability_lock);
}''',
       '''void shutdown_direct_export_hooks() noexcept {
    afw_note_warp_observer(false);
    // C5: detours are process-lifetime objects. DuoView/UEVR safetyhook may
    // already chain their prologues. Disabling/removing any MinHook target or
    // calling MH_Uninitialize would leave other trampolines dangling.
    // stop_interception() publishes started=false before this function.
    // Direct NGX hooks route straight to their retained original then.
    trace_event("[CheekyNR][C5] NGX export detours retained until process exit");
}''',
       "C5 process-lifetime NGX hooks")
# The first detour dispatch sites must pass through without touching Cheeky
# state after host stop. Preserve all original/trampoline function pointers.
change("src/hooks.cpp",
       '''    detect_afw_runtime();
    return dispatch_d3d12_ngx_evaluation(
        {
            D3D12NgxRoute::public_runtime,''',
       '''    if (!started.load(std::memory_order_acquire))
        return original ? original(command_list, handle, parameters, callback) : 0xBAD00007U;
    detect_afw_runtime();
    return dispatch_d3d12_ngx_evaluation(
        {
            D3D12NgxRoute::public_runtime,''',
       "D3D12 NGX public evaluate bypass")
change("src/hooks.cpp",
       '''    const auto original = real_core_evaluate_d3d12.load(
        std::memory_order_acquire
    );
    return dispatch_d3d12_ngx_evaluation(''',
       '''    const auto original = real_core_evaluate_d3d12.load(
        std::memory_order_acquire
    );
    if (!started.load(std::memory_order_acquire))
        return original ? original(command_list, handle, parameters, callback) : 0xBAD00007U;
    return dispatch_d3d12_ngx_evaluation(''',
       "D3D12 core evaluate bypass")
change("src/hooks.cpp",
       '''    if (original == nullptr) return 0xBAD00007U;
    detect_afw_runtime();
    if (!d3d12_ngx_interception_active() && !afw_claim_lower_evaluation()) {''',
       '''    if (original == nullptr) return 0xBAD00007U;
    if (!started.load(std::memory_order_acquire))
        return original(command_list, handle, parameters, callback);
    detect_afw_runtime();
    if (!d3d12_ngx_interception_active() && !afw_claim_lower_evaluation()) {''',
       "D3D12 NGX evaluate C bypass")
# No attempt to unpatch NGX create or release: they still forward to the
# retained trampolines. Work that modifies game feature registry is gated.
change("src/hooks.cpp",
       '''    if (original == nullptr) return 0xBAD00007U;
    detect_afw_runtime();
    D3D12NgxInterceptionScope scope;''',
       '''    if (original == nullptr) return 0xBAD00007U;
    if (!started.load(std::memory_order_acquire))
        return original(command_list, feature, parameters, handle);
    detect_afw_runtime();
    D3D12NgxInterceptionScope scope;''',
       "D3D12 NGX create bypass")
# D3D11 has an alternate pipeline; avoid its calibrator work when stopped.
change("src/hooks.cpp",
       '''        const auto& runtime = d3d11_runtimes[Slot];
        if (Slot != 0 || !calibration_evaluation_depth)
            diagnostic_note_dlss_source''',
       '''        const auto& runtime = d3d11_runtimes[Slot];
        if (!started.load(std::memory_order_acquire)) {
            const auto original = runtime.evaluate.load(std::memory_order_acquire);
            return original ? original(context, handle, parameters, callback) : 0xBAD00007U;
        }
        if (Slot != 0 || !calibration_evaluation_depth)
            diagnostic_note_dlss_source''',
       "D3D11 NGX evaluate bypass")

# Remaining sections for VRAM admission, bounded feature reuse and capture
# cleanups are appended by this batch before the generated tree is written.
# Batch script intentionally does not write until all admission anchors pass.
for name, data in files.items():
    (root/name).write_text(data, encoding="utf-8", newline="\n")
copyfile(here/"contracts/uevr_source_roles_v1.h", root/"src/uevr_source_roles_v1.h")
copyfile(here/"include/uevr_source_roles_consumer_v1.hpp",root/"src/uevr_source_roles_consumer_v1.hpp")
print("PASS Cheeky Batch 2 C2 contract, C5 permanent detours, settings")

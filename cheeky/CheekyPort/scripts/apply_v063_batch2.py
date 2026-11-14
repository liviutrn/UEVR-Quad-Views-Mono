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
       "uevr/scripts/cheeky_foveated_dlss.lua","src/nr_probe_capture.hpp",
       "src/nr_codec_shader.hpp","scripts/build-d3d-shaders.py")
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
       'std::string_view(name) != "NrVramGuardMiB" && std::string_view(name) != "NrDebugView"',
       'std::string_view(name) != "NrVramGuardMiB" && std::string_view(name) != "NrUseSourceRoles" && std::string_view(name) != "NrAllocAdmission" && std::string_view(name) != "NrFeatureReuse" && std::string_view(name) != "NrDebugView"',
       "protect preferences from NR templates")
change("uevr/scripts/cheeky_foveated_dlss.lua",
       '        slider("Max VRAM admission reserve (MiB)", "NrVramGuardMiB", 512, 4096, true)',
       '''        slider("Max VRAM admission reserve (MiB)", "NrVramGuardMiB", 512, 4096, true)
        if draft.NrUseSourceRoles ~= nil then
            check("Use UEVR source roles (C2; automatic fallback)", "NrUseSourceRoles")
            check("Admission guard before NGX allocation", "NrAllocAdmission")
            check("Reuse retired NGX model for 10 s (2 slots)", "NrFeatureReuse")
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
       '''    static NgxResult evaluate(ID3D11DeviceContext* context, const NgxHandle* handle,
        const NgxParameters* parameters, NgxProgressCallback callback) {
        const auto& runtime = d3d11_runtimes[Slot];
        if (Slot != 0 || !calibration_evaluation_depth)
            diagnostic_note_dlss_source''',
       '''    static NgxResult evaluate(ID3D11DeviceContext* context, const NgxHandle* handle,
        const NgxParameters* parameters, NgxProgressCallback callback) {
        const auto& runtime = d3d11_runtimes[Slot];
        if (!started.load(std::memory_order_acquire)) {
            const auto original = runtime.evaluate.load(std::memory_order_acquire);
            return original ? original(context, handle, parameters, callback) : 0xBAD00007U;
        }
        if (Slot != 0 || !calibration_evaluation_depth)
            diagnostic_note_dlss_source''',
       "D3D11 NGX evaluate bypass")

# C4/NR: allocation-point admission. Prior UEVR menu guard cannot protect a
# late NGX model creation, so query live DXGI budget exactly when creating it.
# The process-wide FeatureCost probe is approximate; a matching settled key
# improves its estimate, never subtracts guard headroom.
change("src/dlss_nr.cpp",
       '''struct NrFeatureCost {
    Microsoft::WRL::ComPtr<IDXGIAdapter3> adapter;''',
       '''struct NrFeatureCost {
    FeatureKey key{};
    Microsoft::WRL::ComPtr<IDXGIAdapter3> adapter;''',
       "key measured process-wide feature costs")
change("src/dlss_nr.cpp",
       '''std::mutex nr_mutex;
RuntimeState runtime;
std::deque<ViewState> views;''',
       '''std::mutex nr_mutex;
RuntimeState runtime;
std::deque<ViewState> views;
struct MeasuredFeatureCostBatch2 {
    FeatureKey key{};
    std::uint64_t bytes{};
};
std::deque<MeasuredFeatureCostBatch2> measured_feature_costs_batch2; // nr_mutex
''',
       "bounded measured model cost table")
change("src/dlss_nr.cpp",
       '''cost.preset=preset;cost.logical_pass=frame.logical_pass;''',
       '''cost.preset=preset;cost.logical_pass=view.pass+1U;
            cost.key=key; // pass-2 shared-chain FeatureCost must say pass 2''',
       "correct shared-chain pass label and remember feature key")
change("src/dlss_nr.cpp",
       '''cost.settled=info.CurrentUsage;
                    const auto delta=[&](std::uint64_t usage) {''',
       '''cost.settled=info.CurrentUsage;
                     if (cost.settled > cost.before) {
                         const auto delta_bytes = cost.settled - cost.before;
                         bool matched{};
                         for (auto& known : measured_feature_costs_batch2) {
                             if (known.key == cost.key) {
                                 known.bytes = (std::max)(known.bytes, delta_bytes);
                                 matched = true; break;
                             }
                         }
                         if (!matched) {
                             if (measured_feature_costs_batch2.size() >= 16)
                                 measured_feature_costs_batch2.pop_front();
                             measured_feature_costs_batch2.push_back({cost.key,delta_bytes});
                         }
                     }
                     const auto delta=[&](std::uint64_t usage) {''',
       "record settled FeatureCost against its complete key")
change("src/dlss_nr.cpp",
       '''    NgxParameters* parameters{};
    auto result = runtime.allocate_parameters(&parameters);''',
       '''    if (settings.nr_alloc_admission) {
        GpuMemory budget{};
        if (runtime.device) {
            budget.attach(1U,runtime.device,nullptr);
            budget.poll(GetTickCount64(),true);
        }
        constexpr std::uint64_t MiB=1048576ULL;
        const auto pixels=static_cast<std::uint64_t>(working_width)*working_height;
        // Conservative fallback until the matching model's process-wide
        // first-use/settled cost has been measured, never a guaranteed size.
        std::uint64_t feature_bytes=(std::max)(256ULL*MiB,pixels*32ULL);
        bool measured{};
        for (const auto& previous : measured_feature_costs_batch2) {
            if (previous.key == key) {
                feature_bytes=(std::max)(feature_bytes,previous.bytes);
                measured=true;break;
            }
        }
        const auto reserve=static_cast<std::uint64_t>(settings.nr_vram_guard_mib)*MiB;
        if (!nr_batch2_admit(budget.local.valid,budget.local.headroom,
                              feature_bytes,reserve)) {
            diagnostics.state=DlssNrState::input_preparation_failed;
            diagnostics.skip_reason="NR admission refused: free DXGI local VRAM below feature cost + guard";
            ++diagnostics.failed_calls;
            static ULONGLONG next_log{};
            const auto now=GetTickCount64();
            if (now>=next_log) {
                next_log=now+2000;
                trace_event("[CheekyNR][AllocAdmission] refused view=%llu freeMiB=%llu costMiB=%llu guardMiB=%u measured=%u",
                    static_cast<unsigned long long>(frame.view_id),
                    static_cast<unsigned long long>(budget.local.headroom/MiB),
                    static_cast<unsigned long long>(feature_bytes/MiB),
                    settings.nr_vram_guard_mib,measured?1U:0U);
            }
            // No new NGX object; caller uses original game colour.
            // Do not permanently mark feature_failed: free memory may recover.
            return false;
        }
    }
    NgxParameters* parameters{};
    auto result = runtime.allocate_parameters(&parameters);''',
       "admit each actual model allocation using live DXGI free memory")

# NGX reuse for a retired *physical source* must cross ViewState lifetimes.
# The original cache belongs to one view and cannot handle a recreated NGX
# handle. A global 2-slot pool is bounded and joined by role, family, device
# and full FeatureKey. It may reuse only AFTER the old GPU fence is complete.
change("src/dlss_nr.cpp",
       '''struct CachedFeature {
    FeatureKey key{};''',
       '''struct CachedFeature {
    FeatureKey key{};''',
       "existing cache model remains unchanged")
change("src/dlss_nr.cpp",
       '''    std::deque<CachedFeature> retired_features;
    std::deque<GpuResources> gpu_resources;''',
       '''    std::deque<CachedFeature> retired_features;
    bool feature_reuse_enabled{true};
    std::deque<GpuResources> gpu_resources;''',
       "source reuse preference stored with ViewState")
change("src/dlss_nr.cpp",
       '''std::deque<MeasuredFeatureCostBatch2> measured_feature_costs_batch2; // nr_mutex
''',
       '''std::deque<MeasuredFeatureCostBatch2> measured_feature_costs_batch2; // nr_mutex
struct ReusableModelBatch2 {
    CachedFeature feature;
    std::uint64_t retired_at_ms{};
    std::uint32_t role{}, family{};
    ID3D12Device* device{};
};
std::deque<ReusableModelBatch2> source_reuse_batch2; // nr_mutex, max TWO
void evict_reused_sources_batch2() noexcept {
    const auto now=GetTickCount64();
    for (auto it=source_reuse_batch2.begin();it!=source_reuse_batch2.end();) {
        it->feature.uses.collect();
        if (!it->feature.uses.empty() || now-it->retired_at_ms<=10000ULL) {
            ++it;continue;
        }
        if (it->feature.handle && runtime.release_feature)
            static_cast<void>(runtime.release_feature(it->feature.handle));
        if (it->feature.parameters && runtime.destroy_parameters)
            static_cast<void>(runtime.destroy_parameters(it->feature.parameters));
        it=source_reuse_batch2.erase(it);
    }
}
''',
       "global reuse cache fence-safe expiry")
change("src/dlss_nr.cpp",
       '''void collect_retired_views() noexcept {
    for (auto it = views.begin(); it != views.end();) {''',
       '''void collect_retired_views() noexcept {
    evict_reused_sources_batch2(); // called only under nr_mutex
    for (auto it = views.begin(); it != views.end();) {''',
       "collect pool expirations on existing cadence")
change("src/dlss_nr.cpp",
       '''        if (it->retired && complete) {
            release_feature(*it);''',
       '''        if (it->retired && complete) {
            // Retain only fenced, fully retired sources. If two models are
            // already cached, release this one as #84 did (never exceed 2).
            if (it->feature_reuse_enabled && it->handle && it->has_key &&
                it->source_role && source_reuse_batch2.size() < 2) {
                source_reuse_batch2.push_back({{it->key,it->parameters,it->handle,true,it->uses},
                    GetTickCount64(),it->source_role,
                    current_settings().nr_target_mode < 2U ? 6U : 7U,runtime.device});
                it->parameters=nullptr;
                it->handle=nullptr;
            }
            release_feature(*it);''',
       "stash completed retired source without exceeding 2")
# Do not read Settings while nr_mutex is held: the source role family is
# copied onto the view while its current feature is evaluated (same lock).
change("src/dlss_nr.cpp",
       '''    bool feature_reuse_enabled{true};
    std::deque<GpuResources> gpu_resources;''',
       '''    bool feature_reuse_enabled{true};
    std::uint32_t feature_source_family{0};
    std::deque<GpuResources> gpu_resources;''',
       "reuse source family field")
change("src/dlss_nr.cpp",
       '''                    current_settings().nr_target_mode < 2U ? 6U : 7U,runtime.device});''',
       '''                    it->feature_source_family,runtime.device});''',
       "no settings lock taken under nr_mutex")
change("src/dlss_nr.cpp",
       '''    if (view.handle != nullptr && view.has_key && view.key == key) return true;''',
       '''    view.feature_reuse_enabled=settings.nr_feature_reuse;
    view.feature_source_family=settings.nr_target_mode<2U?6U:7U;
    if (view.handle != nullptr && view.has_key && view.key == key) return true;
    if (settings.nr_feature_reuse) {
        evict_reused_sources_batch2();
        for (auto it=source_reuse_batch2.begin();it!=source_reuse_batch2.end();++it) {
            it->feature.uses.collect();
            if (!nr_batch2_reuse_eligible(settings.nr_feature_reuse,
                it->role==view.source_role,
                it->family==view.feature_source_family,
                it->feature.key==key,
                it->device==runtime.device,
                it->feature.uses.empty(),
                GetTickCount64(),it->retired_at_ms)) continue;
            view.parameters=it->feature.parameters;
            view.handle=it->feature.handle;
            view.key=key;view.has_key=true;view.feature_failed=false;
            view.was_enabled=false;view.settings_signature=0U;
            source_reuse_batch2.erase(it);
            trace_event("[CheekyNR][FeatureReuse] reused completed source view=%llu",
                static_cast<unsigned long long>(view.view_id));
            return true;
        }
    }''',
       "reuse a retired physical source, after fence and within 10 seconds")

# Capture source selection currently re-enters the classifier from within
# nr_mutex; compute only on explicit capture, before that lock is acquired.
change("src/dlss_nr.cpp",
       '''    AfwPrivateWorkScope private_work;
    std::lock_guard execution_lock(calibration12_execution_mutex());
    std::lock_guard lock(nr_mutex);
    collect_retired_views();''',
       '''    AfwPrivateWorkScope private_work;
    std::lock_guard execution_lock(calibration12_execution_mutex());
    const auto capture_source_mask_batch2 =
        nr_probe_busy.load(std::memory_order_acquire)
            ? cheeky_nr_selected_passes(settings, frame.view_id & ~(1ULL << 63U))
            : 0U;
    std::lock_guard lock(nr_mutex);
    collect_retired_views();''',
       "capture pass-selection moved before nr_mutex")
change("src/nr_probe_capture.hpp",
       '''    const auto source_mask=cheeky_nr_selected_passes(current_settings(),
        frame.view_id & ~(1ULL<<63U));''',
       '''    const auto source_mask=source_mask_batch2; // selected before nr_mutex''',
       "capture no classifier under NR lock")
change("src/nr_probe_capture.hpp",
       '''const NrRegion& codec,const Settings& settings,unsigned passes) noexcept {''',
       '''const NrRegion& codec,const Settings& settings,unsigned passes,
    unsigned source_mask_batch2) noexcept {''',
       "pass preclassified source mask to capture")
change("src/dlss_nr.cpp",
       '''nr_probe_capture_one(frame,*gpu,codec_region,settings,pass_count);''',
       '''nr_probe_capture_one(frame,*gpu,codec_region,settings,pass_count,capture_source_mask_batch2);''',
       "capture invocation uses preclassified mask")

# JSON must not output bare NaN, -inf, +inf: those are INVALID JSON numbers.
change("src/dlss_nr.cpp", '#include "../uevr/gpu_memory.hpp"',
       '#include "../uevr/gpu_memory.hpp"\n#include "nr_batch2_policy.hpp"\n#include <cmath>',
       "allocation/reuse policy and capture math included")
capture=files["src/nr_probe_capture.hpp"]
for field in ("intensity","tone","structure","skin","roundness","transition",
              "shape_w","shape_h","exposure_pre","exposure_scale",
              "exposure_ratio","exposure_multiplier"):
    needle="<< capture->"+field
    count=capture.count(needle)
    if count != 1:
        raise RuntimeError(f"capture JSON {field}: {count} stream values, expected 1")
    capture=capture.replace(needle,"<< (std::isfinite(capture->"+field+
        ") ? capture->"+field+" : 0.0f)",1)
files["src/nr_probe_capture.hpp"]=capture

# Preserve the commented HLSL source by splitting it into adjacent C++ raw
# string literals, each under MSVC's 16KiB limit. Never edit HLSL semantics.
# Shader extraction is extended only for the NR codec symbol.
original=(here/"precompact_nr_codec_shader.hlsl").read_text(encoding="utf-8")
chunks=[]; buf=""
for line in original.splitlines(keepends=True):
    if len(line.encode("utf-8")) > 8000:
        raise RuntimeError("NR HLSL line exceeds raw literal chunk budget")
    if buf and len((buf+line).encode("utf-8"))>8000:
        chunks.append(buf);buf=""
    buf+=line
if buf: chunks.append(buf)
if not chunks or any(len(c.encode("utf-8"))>8000 for c in chunks):
    raise RuntimeError("No valid NR raw shader chunks")
shader=files["src/nr_codec_shader.hpp"]
prefix='inline constexpr char nr_codec_shader[] = R"('
if shader.count(prefix)!=1:
    raise RuntimeError("Expected one compacted NR codec literal")
start=shader.index(prefix)
end=shader.index(')";',start)+3
replacement='inline constexpr char nr_codec_shader[] =\n'
for i,chunk in enumerate(chunks):
    delim='NRB'+str(i)
    if ')'+delim+'"' in chunk:
        raise RuntimeError("Raw HLSL delimiter collision")
    replacement+='    R"'+delim+'('+chunk+')'+delim+'"\n'
replacement=replacement.rstrip()+";"
files["src/nr_codec_shader.hpp"]=shader[:start]+replacement+shader[end:]

change("scripts/build-d3d-shaders.py",
       '''    text = path.read_text(encoding="utf-8")
    match = re.search(r"\\b" + re.escape(symbol) + r'\\[\\]\\s*=\\s*R"\\((.*?)\\)";', text, re.S)''',
       '''    text = path.read_text(encoding="utf-8")
    if symbol == "nr_codec_shader":
        token="nr_codec_shader[] ="
        if text.count(token)!=1: raise ValueError("Missing unique split NR codec")
        cursor=text.index(token)+len(token)
        pieces=[]
        while True:
            while cursor<len(text) and text[cursor].isspace(): cursor+=1
            match=re.match(r'R"([A-Za-z0-9_]*)\\((.*?)\\)\\1"',text[cursor:],re.S)
            if not match: break
            pieces.append(match.group(2))
            cursor+=match.end()
        if not pieces or text[cursor]!=";":
            raise ValueError("Invalid split NR codec C++ literals")
        return "".join(pieces)
    match = re.search(r"\\b" + re.escape(symbol) + r'\\[\\]\\s*=\\s*R"\\((.*?)\\)";', text, re.S)''',
       "extract all split NR shader literals without losing bytes")
print(f"BATCH2 NR shader: {len(original)} original bytes in {len(chunks)} raw literals, comments intact")

# Permanent hook target safety: pin the resident runtime DLL before any NGX
# detour is installed. Otherwise UEVR may unload the owner while another
# trampoline still jumps into it (fatal use-after-FreeLibrary).
change("src/hooks.cpp",
       '''    minhook_initialized.store(
        minhook_result == MH_OK ||
            minhook_result == MH_ERROR_ALREADY_INITIALIZED,
        std::memory_order_release
    );

    if (streamline_loaded()) {''',
       '''    minhook_initialized.store(
        minhook_result == MH_OK ||
            minhook_result == MH_ERROR_ALREADY_INITIALIZED,
        std::memory_order_release
    );
    // Process-lifetime code module: other NGX detours may be chained to ours.
    // A pinned DLL is released only by the Windows loader at process exit.
    static HMODULE pinned_runtime_batch2{};
    if (!pinned_runtime_batch2 &&
        !GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_PIN |
            GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS,
            reinterpret_cast<LPCWSTR>(&hook_evaluate_d3d12),
            &pinned_runtime_batch2)) {
        trace_event("[CheekyNR][C5] ERROR: cannot pin detour owner DLL");
        started.store(false,std::memory_order_release);
        return false;
    }
    trace_event("[CheekyNR][C5] detour owner DLL pinned until process exit");
    trace_event("[CheekyNR][C2] consumer ABI version=1 (optional UEVR export, 5s retry)");

    if (streamline_loaded()) {''',
       "pin Cheeky runtime DLL before permanent detours")
change("src/hooks.cpp",
       '''    if (streamline_hook_lock_ready.load(std::memory_order_acquire)) {
        uninstall_streamline_inline_hooks();
    }
    shutdown_direct_export_hooks();''',
       '''    // Retain Streamline MinHook trampolines too. They can be chained by
    // other plugins, so uninstallation at runtime detach is unsafe.
    if (streamline_hook_lock_ready.load(std::memory_order_acquire))
        trace_event("[CheekyNR][C5] Streamline inline hooks retained until process exit");
    shutdown_direct_export_hooks();''',
       "never dismantle another detour's trampoline at runtime detach")
change("src/hooks.cpp",
       '''        const auto& runtime = d3d11_runtimes[Slot];
        if (Slot != 0 || !calibration_evaluation_depth)
            diagnostic_note_dlss_source(DiagnosticApi::d3d11, Slot != 0);
        if (calibration_evaluation_depth) {''',
       '''        const auto& runtime = d3d11_runtimes[Slot];
        if (!started.load(std::memory_order_acquire)) {
            const auto original = runtime.evaluate_c.load(std::memory_order_acquire);
            return original ? original(context, handle, parameters, callback) : 0xBAD00007U;
        }
        if (Slot != 0 || !calibration_evaluation_depth)
            diagnostic_note_dlss_source(DiagnosticApi::d3d11, Slot != 0);
        if (calibration_evaluation_depth) {''',
       "D3D11 _C evaluation work disabled on detach")
change("src/hooks.cpp",
       '''    if (original == nullptr) return 0xBAD00007U;
    D3D12NgxInterceptionScope scope;
    if (!scope.outermost()) return original(handle);
    if (has_d3d12_game_view(handle)) forget_d3d12_game_view(handle);''',
       '''    if (original == nullptr) return 0xBAD00007U;
    if (!started.load(std::memory_order_acquire)) return original(handle);
    D3D12NgxInterceptionScope scope;
    if (!scope.outermost()) return original(handle);
    if (has_d3d12_game_view(handle)) forget_d3d12_game_view(handle);''',
       "D3D12 release detour is pass-through after host stop")
change("src/hooks.cpp",
       '''    const auto original = real_core_release_d3d12.load(
        std::memory_order_acquire
    );
    if (original == nullptr) return 0xBAD00007U;
    detect_afw_runtime();
    if (protected_ngx_core_enabled()) {''',
       '''    const auto original = real_core_release_d3d12.load(
        std::memory_order_acquire
    );
    if (original == nullptr) return 0xBAD00007U;
    if (!started.load(std::memory_order_acquire)) return original(handle);
    detect_afw_runtime();
    if (protected_ngx_core_enabled()) {''',
       "D3D12 core release detour is pass-through after host stop")

# C2 counters belong in the NGX interception TU, where trace_event links;
# settings.cpp is separately linked by standalone test targets without logging.
change("src/hooks.cpp", '#include "settings.hpp"',
       '#include "settings.hpp"\n#include "uevr_source_roles_consumer_v1.hpp"',
       "C2 logger header in intercepting module")
change("src/hooks.cpp",
       '''    if (!started.load(std::memory_order_acquire))
        return original ? original(command_list, handle, parameters, callback) : 0xBAD00007U;
    detect_afw_runtime();
    return dispatch_d3d12_ngx_evaluation(''',
       '''    if (!started.load(std::memory_order_acquire))
        return original ? original(command_list, handle, parameters, callback) : 0xBAD00007U;
    detect_afw_runtime();
    if (c2_roles().DueForLog())
        trace_event("[CheekyNR][C2] version=1 used=%llu fallback=%llu gen=%llu",
            static_cast<unsigned long long>(c2_roles().Used()),
            static_cast<unsigned long long>(c2_roles().Fallback()),
            static_cast<unsigned long long>(c2_roles().Generation()));
    return dispatch_d3d12_ngx_evaluation(''',
       "C2 log counters from runtime only")

# A cached NGX handle still owns the runtime's release callbacks. Never
# clear the D3D12 device / callback table until ALL pooled work retires.
change("src/dlss_nr.cpp",
       '''    if (views.empty()) { release(runtime.device); runtime = {}; }''',
       '''    // Pool eviction is GPU-fence-aware; destroy only completed cached
    // models and retain callbacks until every GPU use has retired.
    for (auto it=source_reuse_batch2.begin();it!=source_reuse_batch2.end();) {
        it->feature.uses.collect();
        if (!it->feature.uses.empty()) { ++it; continue; }
        if (it->feature.handle && runtime.release_feature)
            static_cast<void>(runtime.release_feature(it->feature.handle));
        if (it->feature.parameters && runtime.destroy_parameters)
            static_cast<void>(runtime.destroy_parameters(it->feature.parameters));
        it=source_reuse_batch2.erase(it);
    }
    if (views.empty() && source_reuse_batch2.empty()) {
        release(runtime.device); runtime = {};
    }''', "fence-safe full teardown of global NGX reuse pool")

# Process-lifetime NGX detours forward directly to the original callbacks on
# host detach across DX11 create/release and DX12 core create, too.
change("src/hooks.cpp",
       '''    static NgxResult create(ID3D11DeviceContext* context, std::uint32_t feature,
        NgxParameters* parameters, NgxHandle** handle) {
        return runtime_create_d3d11(d3d11_runtimes[Slot], context, feature, parameters, handle);
    }''',
       '''    static NgxResult create(ID3D11DeviceContext* context, std::uint32_t feature,
        NgxParameters* parameters, NgxHandle** handle) {
        if (!started.load(std::memory_order_acquire)) {
            const auto original = d3d11_runtimes[Slot].create.load(std::memory_order_acquire);
            return original ? original(context, feature, parameters, handle) : 0xBAD00007U;
        }
        return runtime_create_d3d11(d3d11_runtimes[Slot], context, feature, parameters, handle);
    }''', "C5 D3D11 create detach pass-through")
change("src/hooks.cpp",
       '''    static NgxResult release(NgxHandle* handle) {
        return runtime_release_d3d11(d3d11_runtimes[Slot], handle);
    }''',
       '''    static NgxResult release(NgxHandle* handle) {
        if (!started.load(std::memory_order_acquire)) {
            const auto original = d3d11_runtimes[Slot].release.load(std::memory_order_acquire);
            return original ? original(handle) : 0xBAD00007U;
        }
        return runtime_release_d3d11(d3d11_runtimes[Slot], handle);
    }''', "C5 D3D11 release detach pass-through")
change("src/hooks.cpp",
       '''    const auto original = real_core_create_d3d12.load(std::memory_order_acquire);
    if (original == nullptr) return 0xBAD00007U;
    detect_afw_runtime();''',
       '''    const auto original = real_core_create_d3d12.load(std::memory_order_acquire);
    if (original == nullptr) return 0xBAD00007U;
    if (!started.load(std::memory_order_acquire))
        return original(command_list, feature, parameters, handle);
    detect_afw_runtime();''', "C5 D3D12 core create detach pass-through")

# Remaining sections for VRAM admission, bounded feature reuse and capture
# cleanups are appended by this batch before the generated tree is written.
# Batch script intentionally does not write until all admission anchors pass.
for name, data in files.items():
    (root/name).write_text(data, encoding="utf-8", newline="\n")
copyfile(here/"contracts/uevr_source_roles_v1.h", root/"src/uevr_source_roles_v1.h")
copyfile(here/"include/uevr_source_roles_consumer_v1.hpp",root/"src/uevr_source_roles_consumer_v1.hpp")
copyfile(here/"include/nr_batch2_policy.hpp",root/"src/nr_batch2_policy.hpp")
print("PASS Cheeky Batch 2 C2 contract, C5 permanent detours, settings")

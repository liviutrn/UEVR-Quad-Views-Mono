# Part C - Generated changes to upstream Joey UEVR files (B42.1 tree vs 5ac7edc), unified diff -U6
Line numbers in @@ headers are the generated-tree line numbers (+side). Private UESDK code is not included.

diff --git a/src/hooks/D3D12Hook.cpp b/src/hooks/D3D12Hook.cpp
index 7ca5ee6d..9e25ab06 100644
--- a/src/hooks/D3D12Hook.cpp
+++ b/src/hooks/D3D12Hook.cpp
@@ -841,13 +841,18 @@ HRESULT D3D12Hook::present_internal(IDXGISwapChain3* swap_chain, UINT sync_inter
         d3d12->m_is_phase_1 = false;
     }
 
     d3d12->m_inside_present = true;
     d3d12->m_swap_chain = swap_chain;
 
-    swap_chain->GetDevice(IID_PPV_ARGS(&d3d12->m_device));
+    {
+        // B41.1: never let other threads observe a transient nullptr device.
+        ID3D12Device4* present_device{nullptr};
+        swap_chain->GetDevice(IID_PPV_ARGS(&present_device));
+        if (present_device != nullptr) d3d12->m_device = present_device;
+    }
 
     if (d3d12->m_device != nullptr) {
         if (d3d12->m_using_proton_swapchain) {
             const auto real_swapchain = *(uintptr_t*)((uintptr_t)swap_chain + d3d12->m_proton_swapchain_offset);
             d3d12->m_command_queue = *(ID3D12CommandQueue**)(real_swapchain + d3d12->m_command_queue_offset);
         } else {
diff --git a/src/mods/FrameworkConfig.hpp b/src/mods/FrameworkConfig.hpp
index ccfe5d8d..4ef60743 100644
--- a/src/mods/FrameworkConfig.hpp
+++ b/src/mods/FrameworkConfig.hpp
@@ -112,18 +112,18 @@ private:
         }
 
         return log_levels;
     };
     
     ModKey::Ptr m_menu_key{ ModKey::create(generate_name("MenuKey"), VK_INSERT) };
-    ModToggle::Ptr m_menu_open{ ModToggle::create(generate_name("MenuOpen"), true) };
+    ModToggle::Ptr m_menu_open{ ModToggle::create(generate_name("MenuOpen"), false) };
     ModToggle::Ptr m_remember_menu_state{ ModToggle::create(generate_name("RememberMenuState"), false) };
     ModToggle::Ptr m_enable_l3_r3_toggle{ ModToggle::create(generate_name("EnableL3R3Toggle"), true) };
     ModToggle::Ptr m_l3_r3_long_press{ ModToggle::create(generate_name("L3R3LongPress"), false) };
     ModToggle::Ptr m_always_show_cursor{ ModToggle::create(generate_name("AlwaysShowCursor"), false) };
-    ModToggle::Ptr m_advanced_mode{ ModToggle::create(generate_name("AdvancedMode"), false) };
+    ModToggle::Ptr m_advanced_mode{ ModToggle::create(generate_name("AdvancedMode"), true) };
     
     ModCombo::Ptr m_imgui_theme{ ModCombo::create(generate_name("ImGuiTheme"), s_imgui_themes, Framework::ImGuiThemes::DEFAULT_DARK) };
     ModCombo::Ptr m_log_level{ ModCombo::create(generate_name("LogLevel"), s_get_log_levels(), spdlog::level::info) };
     
     ModKey::Ptr m_show_cursor_key{ ModKey::create(generate_name("ShowCursorKey")) };
     ModInt32::Ptr m_font_size{ModInt32::create(generate_name("FontSize"), 16)};
diff --git a/src/mods/VR.cpp b/src/mods/VR.cpp
index a4ff6a90..b63d1bb0 100644
--- a/src/mods/VR.cpp
+++ b/src/mods/VR.cpp
@@ -54,13 +54,19 @@
 #include "Framework.hpp"
 #include "frameworkConfig.hpp"
 
 #include "utility/Logging.hpp"
 
 #include "VR.hpp"
+#include "vr/QuadViewStatusPanel.hpp"
+#include "vr/QuadViewNgxDepth.hpp"
+#include "vr/QuadViewSnapshot.hpp"
+#include <cstring>
 #include "vr/Stalker2NativePolicy.hpp"
+#include "vr/TriViewHold.hpp"
+#include "vr/TriViewVramGuard.hpp"
 #include "UObjectHook.hpp"
 #include "GameSpecific.hpp"
 #include "vr/KtjLOpenXRFactory.hpp"
 
 namespace {
 bool is_stalker2_executable_cached();
@@ -3989,12 +3995,18 @@ bool VR::should_ignore_native_stereo_fix_for_avowed_sync() const {
 
     SPDLOG_INFO_ONCE("[Avowed][NativeStereoFix] Ignoring Native Stereo Fix while Synced Sequential rendering is active");
     return true;
 }
 
 bool VR::should_force_native_stereo_fix_same_pass() const {
+    if (is_duoview_renderer_active()) {
+        if (!m_duoview.settings().native_fix_same_pass ||
+            is_using_afr() || !stalker2_native_fix_requires_same_pass_cached()) { return false; }
+        SPDLOG_INFO_ONCE("[DuoView][NativeStereoFix] Preserving the validated same-pass STALKER 2 layout");
+        return true;
+    }
     if (is_using_mono()) { return false; }
     if (!m_native_stereo_fix->value() || is_using_afr() || !stalker2_native_fix_requires_same_pass_cached()) {
         return false;
     }
 
     // Both validated Stalker2 layouts tear down renderer-owned allocations if
@@ -4003,12 +4015,13 @@ bool VR::should_force_native_stereo_fix_same_pass() const {
     // rendering remain unchanged.
     SPDLOG_INFO_ONCE("[Stalker2][NativeStereoFix] Forcing Same Stereo Pass for the validated runtime");
     return true;
 }
 
 bool VR::is_stalker2_native_fix_experiment_enabled() const {
+    if (is_duoview_renderer_active()) { return false; }
     if (!m_stalker2_native_pair_experiment->value() || !is_native_stereo_fix_enabled() ||
         !g_framework || !g_framework->is_dx12()) { return false; }
     static const bool target = [] {
         const auto path = utility::get_module_pathw(utility::get_executable());
         return path && uevr::stalker2_native::is_executable(*path) &&
             uevr::games::should_use_stalker2_ue55_native_fix_capture_layout(*path,
@@ -8743,12 +8756,315 @@ void VR::on_post_engine_tick(sdk::UGameEngine* engine, float delta) {
     ZoneScopedN(__FUNCTION__);
 
     if (!get_runtime()->loaded || !is_hmd_active()) {
         return;
     }
 
+    // This is NOT automatic load recovery. It runs ONLY after the user
+    // explicitly pressed the two hotkeys simultaneously (same physical key).
+    // Must not run while the OpenXR runtime is being torn down/recreated.
+    const auto due_ms = m_duoview_hotkey_fov_not_before_ms.load(
+        std::memory_order_acquire);
+    if (due_ms != 0) {
+        const auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
+            std::chrono::steady_clock::now().time_since_epoch()).count();
+        if (now_ms > due_ms + 30000) {
+            int64_t expected = due_ms;
+            if (m_duoview_hotkey_fov_not_before_ms.compare_exchange_strong(
+                    expected, 0, std::memory_order_acq_rel)) {
+                m_duoview_manual_fov_status.store(3, std::memory_order_release);
+                SPDLOG_WARN("[DuoView][Hotkeys] Deferred FOV reapply timed out (30s without ready DuoView gameplay)");
+            }
+        } else if (now_ms >= due_ms && get_runtime()->ready() &&
+                   is_duoview_or_triview_fov_active() && engine && engine->get_world()) {
+            int64_t expected = due_ms;
+            if (m_duoview_hotkey_fov_not_before_ms.compare_exchange_strong(
+                    expected, 0, std::memory_order_acq_rel)) {
+                m_duoview_manual_fov_status.store(1, std::memory_order_release);
+                m_duoview_manual_fov_requested.store(true, std::memory_order_release);
+                SPDLOG_INFO("[DuoView][Hotkeys] OpenXR/gameplay ready: triggering proven #205 MPC reapply on game thread");
+            }
+        }
+    }
+
+    // v207 automatic load recovery: issue the proven manual FOV request once
+    // per new world, after it has been stable for 1.5 s. Retries on failure.
+    {
+        static uintptr_t auto_fov_world{};
+        static std::optional<sdk::object_liveness::Identity> auto_fov_identity{};
+        static int64_t auto_fov_due_ms{};
+        static int auto_fov_attempts{};
+        const auto auto_now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
+            std::chrono::steady_clock::now().time_since_epoch()).count();
+        auto* auto_world = engine != nullptr ? engine->get_world() : nullptr;
+        if (!is_duoview_or_triview_fov_active() || auto_world == nullptr) {
+            auto_fov_world = 0;
+            auto_fov_identity.reset();
+            auto_fov_due_ms = 0;
+            auto_fov_attempts = 0;
+        } else if (reinterpret_cast<uintptr_t>(auto_world) != auto_fov_world ||
+                   !auto_fov_identity || !sdk::is_current_object(*auto_fov_identity)) {
+            // Identity, not only the address: a new UWorld can reuse a freed one.
+            const auto observed = sdk::observe_uobject(static_cast<sdk::UObjectBase*>(auto_world));
+            auto_fov_world = reinterpret_cast<uintptr_t>(auto_world);
+            if (observed) auto_fov_identity = observed->identity;
+            else auto_fov_identity.reset();
+            auto_fov_due_ms = auto_now_ms + 1500;
+            auto_fov_attempts = 0;
+        } else if (auto_fov_due_ms != 0 && auto_now_ms >= auto_fov_due_ms &&
+                   get_runtime()->ready() &&
+                   !m_duoview_manual_fov_requested.load(std::memory_order_acquire)) {
+            const int status = m_duoview_manual_fov_status.load(std::memory_order_acquire);
+            if (auto_fov_attempts > 0 && status == 2) {
+                auto_fov_due_ms = 0;
+                SPDLOG_INFO("[DuoView][AutoFOV] Verified after world change ({} attempt(s))", auto_fov_attempts);
+            } else if (auto_fov_attempts >= 3) {
+                auto_fov_due_ms = 0;
+                SPDLOG_WARN("[DuoView][AutoFOV] Gave up after 3 attempts; use Reapply DuoView FOV manually");
+            } else {
+                ++auto_fov_attempts;
+                auto_fov_due_ms = auto_now_ms + 3000;
+                m_duoview_manual_fov_status.store(1, std::memory_order_release);
+                m_duoview_manual_fov_requested.store(true, std::memory_order_release);
+                SPDLOG_INFO("[DuoView][AutoFOV] New world stable: requesting proven FOV reapply (attempt {})",
+                    auto_fov_attempts);
+            }
+        }
+    }
+
+    // STALKER 2 DuoView foreground parity. Automatic only while ID6 is active.
+    // The game can overwrite MPC_FOV after a tick, so merely setting these
+    // scalars once on entry is not robust. Read each tick but only WRITE on
+    // observed drift. Resolve/capture the MPC only once per live UObject.
+    // Both source views consume the same world MPC; no per-view FOV rewriting.
+    {
+        struct ForegroundMPCState {
+            uintptr_t world_id{};
+            std::optional<sdk::object_liveness::Identity> world_identity{};
+            sdk::UObject* collection{};
+            std::optional<sdk::object_liveness::Identity> collection_identity{};
+            sdk::UObject* library{};
+            std::optional<sdk::object_liveness::Identity> library_identity{};
+            sdk::UFunction* getter{};
+            sdk::UFunction* setter{};
+            float original_enabled{};
+            float original_depth{};
+            bool active{};
+        };
+        static ForegroundMPCState fg{};
+        // Retained across world changes, but ONLY used for an explicit click.
+        // The original #165 live-object path is untouched on healthy frames.
+        static std::wstring known_mpc_full_name{};
+        const auto fail_manual = [&](const char* reason) {
+            if (!m_duoview_manual_fov_requested.exchange(
+                    false, std::memory_order_acq_rel)) return;
+            m_duoview_manual_fov_status.store(3, std::memory_order_release);
+            SPDLOG_WARN("[DuoView][ManualFOV] FAILED: {}", reason);
+        };
+        const auto reconcile_foreground = [&]() {
+            const bool requested = is_duoview_or_triview_fov_active();
+            if (!requested && !fg.active) return;
+
+            auto* world = engine != nullptr ? engine->get_world() : nullptr;
+            if (!world) {
+                fg = {};
+                fail_manual("No active UWorld on game tick");
+                return;
+            }
+
+            const uintptr_t world_id = reinterpret_cast<uintptr_t>(world);
+            if (fg.world_id != 0 &&
+                (fg.world_id != world_id || !fg.world_identity ||
+                 !sdk::is_current_object(*fg.world_identity))) {
+                // Never write saved scalars into another game world.
+                fg = {};
+            }
+            if (!requested && !fg.active) return;
+
+            // Revalidate cached UObject identity each tick: cached pointers
+            // must never be used after GC, including an in-world asset reload.
+            if (fg.collection &&
+                (!fg.collection_identity ||
+                 !sdk::is_current_object(*fg.collection_identity))) {
+                fg = {};
+            }
+            if (!requested && !fg.active) return;
+            if (!fg.collection) {
+                sdk::UObject* unique_collection{};
+                for (auto* object : get_live_objects_by_class_name(
+                         L"Class /Script/Engine.MaterialParameterCollection")) {
+                    if (object && object->get_full_name().ends_with(L".MPC_FOV")) {
+                        if (unique_collection) {
+                            fail_manual("More than one MPC_FOV asset in live class registry");
+                            SPDLOG_WARNING_EVERY_N_SEC(5,
+                                "[DuoView][Foreground] ambiguous MPC_FOV asset; refusing override");
+                            return;
+                        }
+                        unique_collection = object;
+                    }
+                }
+                if (!unique_collection &&
+                    m_duoview_manual_fov_requested.load(std::memory_order_acquire) &&
+                    !known_mpc_full_name.empty()) {
+                    // The stock UObjectHook get_objects_by_class() may not
+                    // include package assets loaded before or during travel.
+                    // sdk::find_uobject(..., false) scans FUObjectArray and
+                    // does NOT reuse its static name->object cache.
+                    auto* recovered = sdk::find_uobject<sdk::UObject>(
+                        known_mpc_full_name, false);
+                    auto* expected_class = sdk::find_uobject<sdk::UClass>(
+                        L"Class /Script/Engine.MaterialParameterCollection");
+                    if (recovered && expected_class &&
+                        recovered->get_class() == expected_class &&
+                        recovered->get_full_name() == known_mpc_full_name) {
+                        unique_collection = recovered;
+                        SPDLOG_INFO("[DuoView][ManualFOV] Found MPC_FOV via global object array");
+                    }
+                }
+                if (!unique_collection) {
+                    fail_manual(known_mpc_full_name.empty()
+                        ? "No MPC_FOV asset; no previously verified asset path"
+                        : "MPC_FOV absent from both live registry and global object array");
+                    return;
+                }
+                const auto observed_world = sdk::observe_uobject(
+                    static_cast<sdk::UObjectBase*>(world));
+                const auto observed_collection = sdk::observe_uobject(
+                    static_cast<sdk::UObjectBase*>(unique_collection));
+                if (!observed_world || !observed_collection ||
+                    !sdk::is_current_object(observed_world->identity) ||
+                    !sdk::is_current_object(observed_collection->identity)) {
+                    fail_manual("New world or MPC_FOV asset failed SDK identity validation");
+                    return;
+                }
+                fg.world_id = world_id;
+                fg.world_identity = observed_world->identity;
+                fg.collection = unique_collection;
+                fg.collection_identity = observed_collection->identity;
+                // MaterialParameterCollection is a package asset, not a
+                // per-world instance. The SAME path can resolve a new live
+                // object while the Kismet getter targets the current world.
+                known_mpc_full_name = unique_collection->get_full_name();
+            }
+
+            // Reflection method lookups are also cached per activation;
+            // only cheap UObject identity checks remain on the fast path.
+            if (!fg.library || !fg.library_identity ||
+                !sdk::is_current_object(*fg.library_identity)) {
+                auto* klass = sdk::find_uobject<sdk::UClass>(
+                    L"Class /Script/Engine.KismetMaterialLibrary");
+                auto* library = klass != nullptr ? klass->get_class_default_object() : nullptr;
+                auto* getter = klass != nullptr ? klass->find_function(L"GetScalarParameterValue") : nullptr;
+                auto* setter = klass != nullptr ? klass->find_function(L"SetScalarParameterValue") : nullptr;
+                if (!library || !getter || !setter) {
+                    fail_manual("KismetMaterialLibrary method binding not available");
+                    return;
+                }
+                const auto observed = sdk::observe_uobject(
+                    static_cast<sdk::UObjectBase*>(library));
+                if (!observed || !sdk::is_current_object(observed->identity)) {
+                    fail_manual("KismetMaterialLibrary class default object failed validation");
+                    return;
+                }
+                fg.library = library;
+                fg.library_identity = observed->identity;
+                fg.getter = getter;
+                fg.setter = setter;
+            }
+
+            const auto read = [&](std::wstring_view parameter, float& value) {
+                sdk::ReflectedNameCall call{fg.getter};
+                if (!call.write(L"WorldContextObject", static_cast<sdk::UObject*>(world)) ||
+                    !call.write(L"Collection", fg.collection) ||
+                    !call.write_name(L"ParameterName", sdk::OwnedFName{parameter}) ||
+                    !call.field(L"ReturnValue", sizeof(float)) ||
+                    !call.invoke(fg.library)) return false;
+                value = call.read<float>(L"ReturnValue");
+                return std::isfinite(value);
+            };
+            const auto write = [&](std::wstring_view parameter, float value) {
+                sdk::ReflectedNameCall call{fg.setter};
+                return call.write(L"WorldContextObject", static_cast<sdk::UObject*>(world)) &&
+                    call.write(L"Collection", fg.collection) &&
+                    call.write_name(L"ParameterName", sdk::OwnedFName{parameter}) &&
+                    call.write(L"ParameterValue", value) && call.invoke(fg.library);
+            };
+
+            float current_enabled{}, current_depth{};
+            if (!read(L"IsFOVEnabled", current_enabled) ||
+                !read(L"DepthScale", current_depth)) {
+                fail_manual("Cannot read current-world MPC_FOV scalar values");
+                return;
+            }
+            const bool manual = m_duoview_manual_fov_requested.load(
+                std::memory_order_acquire);
+            if (manual) {
+                SPDLOG_INFO("[DuoView][ManualFOV] Before force write: enabled={} depth={} world={} asset={}",
+                    current_enabled, current_depth, reinterpret_cast<uintptr_t>(world),
+                    reinterpret_cast<uintptr_t>(fg.collection));
+            }
+
+            if (requested && !fg.active) {
+                // Preserve the live baseline for restoration on mode exit.
+                fg.original_enabled = current_enabled;
+                fg.original_depth = current_depth;
+                fg.active = true;
+                SPDLOG_INFO("[DuoView][Foreground] MPC_FOV activated; cached asset; "
+                            "conditional updates only (original IsFOVEnabled={}, DepthScale={})",
+                            fg.original_enabled, fg.original_depth);
+            }
+            const float wanted_enabled = requested ? 0.0f : fg.original_enabled;
+            const float wanted_depth = requested ? 1.0f : fg.original_depth;
+            constexpr float epsilon = 0.0001f;
+
+            // No setter calls once the game values are already correct.
+            // If STALKER 2 rewrites either value every tick, correct it in
+            // this SAME tick to preserve the proven v186.1 foreground fix.
+            const bool enabled_ok =
+                (!manual && std::abs(current_enabled - wanted_enabled) <= epsilon) ||
+                write(L"IsFOVEnabled", wanted_enabled);
+            const bool depth_ok =
+                (!manual && std::abs(current_depth - wanted_depth) <= epsilon) ||
+                write(L"DepthScale", wanted_depth);
+            if (!enabled_ok || !depth_ok) {
+                fail_manual("SetScalarParameterValue rejected a forced MPC_FOV write");
+                SPDLOG_WARNING_EVERY_N_SEC(5,
+                    "[DuoView][Foreground] MPC_FOV reconciliation failed; preserving baseline");
+                return;
+            }
+            if (manual) {
+                float after_enabled{}, after_depth{};
+                const bool readback_ok =
+                    read(L"IsFOVEnabled", after_enabled) &&
+                    read(L"DepthScale", after_depth) &&
+                    std::abs(after_enabled) <= epsilon &&
+                    std::abs(after_depth - 1.0f) <= epsilon;
+                if (readback_ok) {
+                    if (m_duoview_manual_fov_requested.exchange(
+                            false, std::memory_order_acq_rel)) {
+                        m_duoview_manual_fov_status.store(2, std::memory_order_release);
+                        SPDLOG_INFO("[DuoView][ManualFOV] VERIFIED: effective world MPC scalars 0 / 1");
+                    }
+                } else {
+                    fail_manual("Post-write readback differs from 0 / 1");
+                }
+            }
+            if (!requested) {
+                fg = {};
+                SPDLOG_INFO("[DuoView][Foreground] restored original MPC_FOV scalars");
+            }
+        };
+        try {
+            reconcile_foreground();
+        } catch (...) {
+            fail_manual("Unreal SDK exception during manual MPC operation");
+            SPDLOG_WARNING_EVERY_N_SEC(5,
+                "[DuoView][Foreground] MPC access failed; refusing unsafe write");
+        }
+    }
+
     // Some Supermassive camera paths rewrite crop/aspect state during engine
     // tick. Reapply the opt-in compatibility after game tick, but keep it to
     // the active camera only; broad object sweeps caused cadence/flicker issues.
     update_fullscreen_16x9_camera_compatibility(engine);
     if (m_prospi_camera_trace.active()) {
         m_prospi_camera_trace_probe.post_tick(m_prospi_camera_trace, GetCurrentThreadId());
@@ -13300,12 +13616,42 @@ void VR::on_pre_calculate_stereo_view_offset(void* stereo_device, const int32_t
             view_rotation->yaw = m_camera_freeze.rotation.y;
             view_rotation->roll = m_camera_freeze.rotation.z;
         }
     }
 }
 
+bool VR::is_quadview_supported_title() const {
+    // Hook installation occurs at startup, before ID7 is selected.
+    // Cache title support independently of the active rendering mode.
+    static const bool stalker2_ue55 = [] {
+        const auto path=utility::get_module_pathw(utility::get_executable());
+        const auto detected_version=sdk::search_for_version(utility::get_executable()).value_or(L"0.00");
+        const auto file_version=sdk::get_file_version_info();
+        return path && uevr::games::is_stalker2_ue55_runtime(*path,detected_version,file_version.dwFileVersionMS);
+    }();
+    return stalker2_ue55;
+}
+
+const char* VR::quadview_unavailable_reason() const {
+    if (!is_quadview_mode_selected() && requested_rendering_method() != RenderingMethod::QUAD_VIEWS_STEREO) return nullptr;
+    if (!m_is_d3d12 || g_framework == nullptr || !g_framework->is_dx12()) return "Quad Views requires DX12";
+    const auto runtime = get_runtime();
+    if (runtime == nullptr || !runtime->is_openxr()) return "Quad Views requires OpenXR";
+    if (!is_quadview_supported_title()) return "Quad Views currently supports STALKER 2 UE5.5 only";
+    if (!m_fake_stereo_hook || !m_fake_stereo_hook->quadview_view_extensions_ready())
+        return "Quad Views warming up: scene-view constructor hook is not ready";
+    // Stay in the previous working rendering mode until the real renderer
+    // entry callback has executed. ID7 OpenXR requires a four-view image.
+    if (!m_fake_stereo_hook || !m_fake_stereo_hook->quadview_outer_renderer_observed())
+        return "Quad Views warming up: outer renderer interception not observed";
+    if (m_extreme_compat_mode->value() || m_splitscreen_compatibility_mode->value() || m_2d_screen_mode->value() ||
+        m_sceneview_compatibility_mode->value() || m_stereo_emulation_mode) return "Quad Views requires Extreme Compatibility, split-screen, 2D Screen, SceneView compatibility and Stereo Emulation OFF";
+    if (uevr::nascar::is_target()) return "Quad Views is unavailable for this title's restricted rendering path";
+    return nullptr;
+}
+
 const char* VR::mono_unavailable_reason() const {
     const auto runtime = get_runtime();
     return uevr::mono::unavailable_reason({
         .dx11 = g_framework != nullptr && g_framework->get_renderer_type() == Framework::RendererType::D3D11,
         .dx12 = g_framework != nullptr && g_framework->is_dx12(),
         .openxr = runtime != nullptr && runtime->is_openxr(),
@@ -13321,13 +13667,13 @@ const char* VR::mono_unavailable_reason() const {
 bool VR::service_mono_transition_present() {
     auto& selection = m_rendering_method->selection();
     if (!m_rendering_method->is_available(selection.active()) && !selection.pending()) {
         set_mono_status("Unsupported rendering method ID; preserved in profile, select a supported method");
         return true;
     }
-    const bool entering = selection.requested() == RenderingMethod::MONO;
+    const bool entering = uevr::mono::is_mono_family(selection.requested());
     if (is_using_mono() || entering) {
         if (const auto reason = mono_unavailable_reason()) {
             set_mono_status(reason);
             // Rejected startup/live requests leave the previous method running.
             // An invalidated active Mono remains blocked until a safe exit.
             if (!is_using_mono()) { return false; }
@@ -13350,15 +13696,227 @@ bool VR::service_mono_transition_present() {
     m_openxr->end_mono_transition_frame();
     return true;
 }
 
 void VR::service_mono_transition_game_thread() {
     auto& selection = m_rendering_method->selection();
+    // GT is the authoritative observer of UWorld identity. Address equality
+    // alone is insufficient: Unreal can reuse the address after a save load.
+    {
+        static uintptr_t observed_world{};
+        static std::optional<sdk::object_liveness::Identity> observed_identity{};
+        static bool dirty_world{}; // Survives a canceled request to leave ID7.
+        auto* engine=sdk::UGameEngine::get();
+        auto* world=engine ? engine->get_world() : nullptr;
+        const bool identity_valid=observed_identity && sdk::is_current_object(*observed_identity);
+        const bool changed=reinterpret_cast<uintptr_t>(world)!=observed_world ||
+            (world && !identity_valid);
+        std::optional<sdk::object_liveness::Identity> new_identity{};
+        if (changed && world) {
+            if (const auto observed=sdk::observe_uobject(static_cast<sdk::UObjectBase*>(world)))
+                new_identity=observed->identity;
+        }
+        if (changed && is_quadview_mode_selected()) dirty_world=true;
+        const bool recovery_pending=m_triview_world_epoch_gate.closed() || dirty_world;
+        const bool leaving_triview=selection.pending() && selection.requested()!=RenderingMethod::QUAD_VIEWS_STEREO;
+        if (recovery_pending && (!is_quadview_mode_selected() || leaving_triview)) {
+            // A user may switch modes or a transient world may revert while
+            // recovery is waiting. Do not leave a closed gate latched forever.
+            if (!m_triview_world_epoch_gate.try_close()) return;
+            m_triview_world_epoch_gate.open();
+        }
+        if ((changed || recovery_pending) && is_quadview_mode_selected() && !leaving_triview) {
+            if (!changed && identity_valid) new_identity=observed_identity;
+            // Keep every engine/RHI ledger and packet lease until its actual
+            // callback. Only revoke old publication and cached world assumptions.
+            m_triview_world_first_serial.store(m_quadview_draw_serial.load(std::memory_order_acquire)+1,
+                std::memory_order_release);
+            // Close admission first. Never block GT on an RHI/XR callback:
+            // retry this boundary at the next draw after old readers drain.
+            if (!m_triview_world_epoch_gate.try_close()) {
+                set_quadview_status("World recovery: draining the previous XR transaction");
+                return;
+            }
+            if (world && !new_identity) {
+                // Keep admission closed, but do not retire/recreate targets on
+                // every failed identity probe. Retry the identity next GT tick.
+                set_quadview_status("World recovery: waiting for a valid Unreal world identity");
+                return;
+            }
+            utility::ScopeGuard reopen_world_epoch{[this]() { m_triview_world_epoch_gate.open(); }};
+            if (m_openxr) {
+                m_openxr->invalidate_quadview_located_pose();
+                m_openxr->invalidate_quadview_scene();
+            }
+            if (m_fake_stereo_hook) if (auto* manager=m_fake_stereo_hook->get_render_target_manager())
+                manager->retire_quadview_native_target_set();
+            m_triview_hold_set.reset();
+            m_triview_resize_gate.reset();
+            m_triview_resize_world_identity=0;
+            m_triview_pending_extents_valid=false;
+            m_quadview_candidate_key.store(nullptr,std::memory_order_release);
+            {
+                std::scoped_lock layout_lock{m_quadview_layout_mutex};
+                m_quadview_draw_config.reset();
+            }
+            {
+                std::scoped_lock pose_lock{m_quadview_pose_mutex};
+                m_quadview_pose.reset(); m_quadview_pose_eye_mask=0;
+            }
+            spdlog::info("[TriView][B28][World] world epoch changed; first_serial={} old callbacks drain without publication",
+                m_triview_world_first_serial.load(std::memory_order_acquire));
+            dirty_world=false;
+        }
+        if ((changed || recovery_pending) && (!is_quadview_mode_selected() || !leaving_triview)) {
+            observed_world=reinterpret_cast<uintptr_t>(world);
+            observed_identity=new_identity;
+        }
+        if (!is_quadview_mode_selected()) dirty_world=false; // Actual mode commit retired the previous world.
+    }
+    // TriView B24: use the EXISTING tracked ID7->Native transition as the
+    // producer quiesce. Never flip the view count within an active family.
+    const auto restart_phase=m_triview_restart_phase.load(std::memory_order_acquire);
+    if (restart_phase==1 && !selection.pending() &&
+        selection.active()==RenderingMethod::QUAD_VIEWS_STEREO) {
+        m_triview_restart_saved_native_fix=m_native_stereo_fix->value();
+        m_native_stereo_fix->value()=true;
+        m_rendering_method->set_save_override(RenderingMethod::QUAD_VIEWS_STEREO);
+        selection.request(RenderingMethod::NATIVE_STEREO);
+        m_triview_restart_phase.store(2,std::memory_order_release);
+        spdlog::info("[TriView][Restart] phase=2 native-mode retirement requested");
+    } else if (restart_phase==2 && !selection.pending() &&
+               selection.active()==RenderingMethod::NATIVE_STEREO) {
+        // The mode commit already checked the old generation's engine tails
+        // and retired its producer/target publication. GPU retirement follows.
+        m_triview_restart_phase.store(3,std::memory_order_release);
+        spdlog::info("[TriView][Restart] phase=3 awaiting native owner/depth/GPU retirement");
+    } else if (restart_phase==4) {
+        const auto now=std::chrono::steady_clock::now();
+        if (m_triview_restart_resume_since==std::chrono::steady_clock::time_point{})
+            m_triview_restart_resume_since=now;
+        if (!selection.pending() && selection.active()==RenderingMethod::NATIVE_STEREO &&
+            get_runtime() && get_runtime()->loaded) {
+            // Native Fix state 'PairReady' may be retained from the OLD
+            // OpenXR session. A new session requires fresh poses AND a newly
+            // published native stereo packet; old state is not sufficient.
+            const bool fresh_native_pair=m_fake_stereo_hook &&
+                m_fake_stereo_hook->native_stereo_publication_serial() >
+                    m_triview_restart_previous_native_serial.load(std::memory_order_acquire);
+            const bool ready=get_runtime()->got_first_poses && fresh_native_pair &&
+                m_fake_stereo_hook->is_native_stereo_fix_state_ready();
+            if (ready && m_triview_restart_ready_since==std::chrono::steady_clock::time_point{})
+                m_triview_restart_ready_since=now;
+            if (!ready) m_triview_restart_ready_since={};
+            // Only restore after the newly created XR runtime has a genuine
+            // Native Stereo Fix pair. Do not use an unconditional timeout.
+            if (ready && now-m_triview_restart_ready_since>=std::chrono::seconds(2)) {
+                selection.request(RenderingMethod::QUAD_VIEWS_STEREO);
+                m_triview_restart_phase.store(5,std::memory_order_release);
+                spdlog::info("[TriView][Restart] phase=5 new XR pose/pair ready; returning to TriView");
+            } else if (now-m_triview_restart_resume_since>std::chrono::seconds(25)) {
+                SPDLOG_WARNING_EVERY_N_SEC(5,"[TriView][Restart] New XR Native Fix pair not ready; preserving Native Stereo, no unsafe fallback to ID7");
+            }
+        }
+    } else if (restart_phase==5 && !selection.pending() &&
+               selection.active()==RenderingMethod::QUAD_VIEWS_STEREO) {
+        m_native_stereo_fix->value()=m_triview_restart_saved_native_fix;
+        m_rendering_method->set_save_override(-1);
+        m_triview_restart_ready_since={};
+        m_triview_restart_resume_since={};
+        m_triview_restart_phase.store(0,std::memory_order_release);
+        spdlog::info("[TriView][Restart] phase=0 TriView restored with new OpenXR session");
+    }
+    {   // Tri-view B12: automatic Native Stereo Fix warm-up before a saved ID7 start.
+        using clock = std::chrono::steady_clock;
+        const auto now = clock::now();
+        if (m_triview_autostart_stage == 0 && selection.generation() == 0 && selection.pending() &&
+            selection.requested() == RenderingMethod::QUAD_VIEWS_STEREO && selection.active() == RenderingMethod::NATIVE_STEREO) {
+            m_triview_autostart_stage = 1;
+            m_triview_autostart_user_fix = m_native_stereo_fix->value();
+            m_triview_autostart_since = now;
+            m_triview_autostart_active_since = {};
+            m_native_stereo_fix->value() = true;
+            m_rendering_method->set_save_override(RenderingMethod::QUAD_VIEWS_STEREO);
+            selection.request(RenderingMethod::NATIVE_STEREO);
+            spdlog::info("[TriView][Autostart] saved ID7: warming up Native Stereo + Native Stereo Fix first (user fix toggle was {})",
+                m_triview_autostart_user_fix);
+        } else if (m_triview_autostart_stage == 1) {
+            // B14: on STALKER 2 a working Native Fix stays PairReady (never Active).
+            const bool fix_active = m_fake_stereo_hook && m_fake_stereo_hook->is_native_stereo_fix_state_ready();
+            if (fix_active && m_triview_autostart_active_since == clock::time_point{}) m_triview_autostart_active_since = now;
+            if (!fix_active) m_triview_autostart_active_since = {};
+            const bool warm = fix_active && now - m_triview_autostart_active_since > std::chrono::seconds(2);
+            const bool timeout = now - m_triview_autostart_since > std::chrono::seconds(25);
+            if (selection.requested() != RenderingMethod::NATIVE_STEREO) {
+                m_native_stereo_fix->value() = m_triview_autostart_user_fix;
+                m_rendering_method->set_save_override(-1);
+                m_triview_autostart_stage = 3;
+                spdlog::info("[TriView][Autostart] user changed the rendering method during warm-up; autostart cancelled");
+            } else if (warm || timeout) {
+                m_triview_autostart_stage = 2;
+                selection.request(RenderingMethod::QUAD_VIEWS_STEREO);
+                spdlog::info("[TriView][Autostart] requesting ID7 ({})", warm ? "Native Fix pair ready for 2 s" : "25 s timeout");
+            }
+        } else if (m_triview_autostart_stage == 2 && !selection.pending()) {
+            m_native_stereo_fix->value() = m_triview_autostart_user_fix;
+            m_rendering_method->set_save_override(-1);
+            m_triview_autostart_stage = 3;
+            if (selection.active() == RenderingMethod::QUAD_VIEWS_STEREO) {
+                spdlog::info("[TriView][Autostart] ID7 committed; Native Stereo Fix toggle restored to {}",
+                    m_triview_autostart_user_fix);
+            } else {
+                spdlog::warn("[TriView][Autostart] transition settled WITHOUT ID7 (active={}, requested={}); no TriView success claimed",
+                    selection.active(), selection.requested());
+            }
+        }
+        static auto last_transition_log = clock::time_point{};
+        if ((selection.requested() == RenderingMethod::QUAD_VIEWS_STEREO || selection.active() == RenderingMethod::QUAD_VIEWS_STEREO) &&
+            selection.pending() && now - last_transition_log > std::chrono::seconds(2)) {
+            last_transition_log = now;
+            const char* reason = quadview_unavailable_reason();
+            spdlog::info("[TriView][Transition] requested={} active={} unavailable='{}' outer_renderer={} view_ext={} autostart={}",
+                selection.requested(), selection.active(), reason ? reason : "",
+                m_fake_stereo_hook && m_fake_stereo_hook->quadview_outer_renderer_observed(),
+                m_fake_stereo_hook && m_fake_stereo_hook->quadview_view_extensions_ready(), m_triview_autostart_stage);
+        }
+    }
     if (!selection.pending()) { return; }
-    if (selection.requested() == RenderingMethod::MONO && mono_unavailable_reason() != nullptr) { return; }
+    if (uevr::mono::is_mono_family(selection.requested()) && mono_unavailable_reason() != nullptr) { return; }
+    if (selection.requested() == RenderingMethod::QUAD_VIEWS_STEREO && quadview_unavailable_reason() != nullptr) return;
+    if (is_quadview_mode_selected() && (!quadview_transition_draw_closed() || !m_fake_stereo_hook ||
+        !m_fake_stereo_hook->quadview_delivery.engine_commands_retired(mono_generation()))) {
+        set_quadview_status(quadview_transition_draw_closed()
+            ? "Waiting for tracked render-thread/RHI owners to execute at mode commit"
+            : "Waiting for the active viewport draw to latch a closed ID7 admission boundary");
+        return;
+    }
     if (!selection.commit_at_game_frame_boundary()) { return; }
+    const auto retired_generation = mono_generation() - 1;
+    m_duoview.retire();
+    if (m_fake_stereo_hook) {
+        m_fake_stereo_hook->duoview_delivery.retire(mono_generation());
+        m_fake_stereo_hook->quadview_delivery.retire_generation(retired_generation);
+        m_fake_stereo_hook->quadview_native_delivery.reset();
+        if (auto* manager=m_fake_stereo_hook->get_render_target_manager()) manager->retire_quadview_native_target_set();
+    }
+    m_quadview.retire_generation(retired_generation);
+    m_triview_hold_set.reset();
+    m_triview_resize_gate.reset();
+    m_triview_resize_world_identity=0;
+    m_triview_pending_extents_valid=false;
+    { std::scoped_lock lock{m_quadview_layout_mutex}; if (m_quadview_draw_config) {
+        m_quadview_draw_config->native_target_set.reset();
+        m_quadview_draw_config->native_target_set_ready=false;
+        m_quadview_draw_config->native_target_set_generation=0;
+    } }
+    m_duoview_candidate_key.store(nullptr, std::memory_order_release);
+    m_duoview_frozen_key.store(nullptr, std::memory_order_release);
+    m_quadview_candidate_key.store(nullptr, std::memory_order_release);
+    m_duo_shading->value()=false;
+    configure_duoview();
+    if (selection.active() == RenderingMethod::DUOVIEW_MONO) m_duoview_quarantined.store(false, std::memory_order_release);
     m_mono_main_view_token = 0;
     m_mono_attachment_token = 0;
     m_openxr->reset_mono_projection_history();
     set_mono_status("Waiting for a current main-view projection and scene");
     spdlog::info("[Mono] Committed rendering method {} at viewport boundary, generation={}",
         selection.active(), selection.generation());
@@ -13692,12 +14250,24 @@ void VR::on_config_load(const utility::Config& cfg, bool set_defaults) {
         // Subnautica 2's UE5.6 native path can render SingleLayerWater black in the right eye.
         // Keep this game-specific guard enabled for fresh profiles, but let existing profiles override it.
         m_compatibility_subnautica2_native_water->value() = true;
         m_subnautica2_native_water_mode->value() = SUBNAUTICA2_NATIVE_WATER_SAFE_REFLECTIONS;
     }
 
+    // B42.1: a saved ID7 loads as a REQUEST (active stays Native Stereo until the
+    // autostart commits), so value() is not 7 here - check the request too.
+    if (m_first_config_load && m_triview_b42_low_start->value() &&
+        (m_rendering_method->value() == RenderingMethod::QUAD_VIEWS_STEREO ||
+         m_rendering_method->requested_value() == RenderingMethod::QUAD_VIEWS_STEREO)) {
+        // B42: TriView saved -> start the headset at a low resolution (before swapchains exist).
+        const float warm = std::clamp(m_triview_b42_low_start_scale->value(), .1f, 1.f);
+        if (warm < .999f && runtimes::OpenXR::triview_warmup_scale.exchange(warm) != warm) {
+            m_triview_b42_low_start_state.store(1, std::memory_order_relaxed);
+            spdlog::info("[TriView][LowStart] TriView saved: starting at resolution scale {:.2f} until TriView is loaded", warm);
+        }
+    }
     if (get_runtime() != nullptr && get_runtime()->loaded) {
         get_runtime()->on_config_load(cfg, set_defaults);
 
         // Run the rest of OpenXR initialization code here that depends on config values
         if (m_first_config_load) {
             m_first_config_load = false; // because the frontend can request config reloads
@@ -13718,12 +14288,13 @@ void VR::on_config_load(const utility::Config& cfg, bool set_defaults) {
     if (m_cvar_manager != nullptr) {
         m_cvar_manager->on_config_load(cfg, set_defaults);   
     }
 
     // Load camera offsets
     load_cameras();
+    configure_duoview();
     load_prospi_camera_calibrations();
     load_generic_camera_presets();
 }
 
 void VR::on_config_save(utility::Config& cfg) {
     ZoneScopedN(__FUNCTION__);
@@ -14695,12 +15266,51 @@ void VR::on_pre_imgui_frame() {
         m_overlay_component.on_pre_imgui_frame();
     }
 }
 
 void VR::handle_keybinds() {
     ZoneScopedN(__FUNCTION__);
+    // These are separate ModKeys; identical assigned VK codes intentionally
+    // fire BOTH edge detectors on the same press, only once until key release.
+    const bool fov_pressed = m_duoview_fov_reapply_key->is_key_down_once();
+    const bool reset_pressed = m_reinitialize_runtime_key->is_key_down_once();
+    if (reset_pressed) {
+        const auto runtime = get_runtime();
+        if (runtime && runtime->loaded &&
+            (runtime->is_openxr() || runtime->is_openvr()) &&
+            !runtime->wants_reinitialize) {
+            const bool combined = fov_pressed && runtime->is_openxr() &&
+                                  is_duoview_or_triview_fov_active();
+            if (combined) {
+                // Do NOT request MPC now; runtime reset would discard or
+                // change the world state before any repair was useful.
+                m_duoview_hotkey_fov_not_before_ms.store(0, std::memory_order_release);
+                m_duoview_hotkey_reapply_after_reset.store(true, std::memory_order_release);
+                m_duoview_manual_fov_status.store(1, std::memory_order_release);
+                SPDLOG_INFO("[DuoView][Hotkeys] Combined key: reset first, then FOV reapply after recovery");
+            }
+            runtime->wants_reinitialize = true;
+            SPDLOG_INFO("[DuoView][Hotkeys] User requested stock runtime reset");
+        } else {
+            SPDLOG_WARN("[DuoView][Hotkeys] Runtime reset key ignored: no loaded/eligible runtime or reset already pending");
+            if (fov_pressed) {
+                m_duoview_manual_fov_status.store(3, std::memory_order_release);
+            }
+        }
+    }
+    if (fov_pressed && !reset_pressed && is_duoview_or_triview_fov_active()) {
+        m_duoview_manual_fov_status.store(1, std::memory_order_release);
+        m_duoview_manual_fov_requested.store(true, std::memory_order_release);
+        SPDLOG_INFO("[DuoView][Hotkeys] User requested proven #205 MPC FOV reapply");
+    }
+    // Sample keys on the game thread once per frame, not per render view.
+    if (m_xyz_headscale_toggle_key->is_key_down_once()) {
+        m_xyz_headscale_enabled->toggle();
+    }
+    m_xyz_headscale_hold_bypass.store(
+        m_xyz_headscale_hold_bypass_key->is_key_down(), std::memory_order_relaxed);
 
     if (m_keybind_recenter->is_key_down_once()) {
         recenter_view();
     }
 
      if (m_keybind_recenter_horizon->is_key_down_once()) {
@@ -15001,13 +15611,14 @@ void VR::on_post_present() {
         m_d3d11.on_post_present(this);
     } else {
         m_d3d12.on_post_present(this);
     }
 
     bool native_openxr_async_wait_requested = false;
-    if (m_is_d3d12 && runtime->is_openxr() && is_native_openxr_async_wait_active()) {
+    if (m_is_d3d12 && runtime->is_openxr() && is_native_openxr_async_wait_active() &&
+        m_triview_restart_phase.load(std::memory_order_acquire)==0) {
         native_openxr_async_wait_requested = request_native_openxr_async_wait();
         if (native_openxr_async_wait_requested) {
             SPDLOG_INFO_ONCE("[OpenXR][native] Running opt-in xrWaitFrame asynchronously after D3D12 submit");
         }
     }
 
@@ -15043,20 +15654,144 @@ void VR::on_post_present() {
 
     if (runtime->wants_reinitialize) {
         std::scoped_lock _{m_reinitialize_mtx};
 
         if (runtime->is_openvr()) {
             m_openvr->wants_reinitialize = false;
-            reinitialize_openvr();
+            const auto error = reinitialize_openvr();
+            if (m_duoview_hotkey_reapply_after_reset.exchange(
+                    false, std::memory_order_acq_rel)) {
+                m_duoview_manual_fov_status.store(3, std::memory_order_release);
+                SPDLOG_WARN("[DuoView][Hotkeys] Combined FOV key cannot run on OpenVR; reset error={}",
+                    error.value_or("none"));
+            }
         } else if (runtime->is_openxr()) {
             m_openxr->wants_reinitialize = false;
-            reinitialize_openxr();
+            const auto error = [&]() -> std::optional<std::string> {
+                if (m_is_d3d12 && is_quadview_mode_selected() &&
+                    m_triview_restart_phase.load(std::memory_order_acquire)==0) {
+                    m_triview_restart_phase.store(1,std::memory_order_release);
+                    spdlog::info("[TriView][Restart] phase=1 queued via native-mode transition");
+                    return std::string{"TriView restart queued; engine owners must retire first"};
+                }
+                if (m_triview_restart_phase.load(std::memory_order_acquire)!=0) {
+                    spdlog::info("[TriView][Restart] duplicate request coalesced");
+                    return std::string{"TriView restart already pending"};
+                }
+                return reinitialize_openxr();
+            }();
+            if (m_duoview_hotkey_reapply_after_reset.exchange(
+                    false, std::memory_order_acq_rel)) {
+                if (!error) {
+                    const auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
+                        std::chrono::steady_clock::now().time_since_epoch()).count();
+                    m_duoview_hotkey_fov_not_before_ms.store(
+                        now_ms + 850, std::memory_order_release);
+                    SPDLOG_INFO("[DuoView][Hotkeys] OpenXR reinitialized; FOV key action queued for ready game tick");
+                } else {
+                    m_duoview_manual_fov_status.store(3, std::memory_order_release);
+                    SPDLOG_WARN("[DuoView][Hotkeys] OpenXR reset failed; FOV reapply cancelled: {}", *error);
+                }
+            }
+        }
+    }
+    if (m_is_d3d12 && m_triview_restart_phase.load(std::memory_order_acquire)==3 &&
+        runtime->is_openxr() && !is_quadview_mode_selected()) {
+        std::scoped_lock restart_lock{m_reinitialize_mtx};
+        // Missing manager is UNKNOWN, not proof of retired engine owners.
+        bool native_owners_retired=false;
+        if (m_fake_stereo_hook) if (auto* rtm=m_fake_stereo_hook->get_render_target_manager()) {
+            const auto d=rtm->get_quadview_native_retirement_diagnostics();
+            native_owners_retired=!d.busy && !d.pending.count && !d.pending.truncated &&
+                !d.staged.count && !d.staged.truncated &&
+                !d.in_flight.count && !d.in_flight.truncated &&
+                !d.ready.count && !d.ready.truncated;
+        }
+        // The periphery NGX copy pool can submit on a different DIRECT queue.
+        // Do not confuse the compositor's completed fence with its producer fence.
+        const bool depth_retired=m_d3d12.openxr().depth_quiescent_for_restart();
+        // No old-session xrWaitFrame callback may survive the session reset.
+        const bool async_xr_idle=!m_native_openxr_async_wait_inflight.load(std::memory_order_acquire);
+        if (!native_owners_retired || !depth_retired || !async_xr_idle) {
+            SPDLOG_INFO_EVERY_N_SEC(2,"[TriView][Restart] waiting native_owners={} depth_queues={} async_xr_idle={}",
+                native_owners_retired,depth_retired,async_xr_idle);
+        } else if (!m_d3d12.openxr().discard_completed_depth_on_restart()) {
+            // No old depth texture may become the first input in the new XR
+            // session, even when B21 permits latest submitted within 250 ms.
+            SPDLOG_WARNING_EVERY_N_SEC(2,"[TriView][Restart] depth snapshots still leased; postponing XR reset");
+        } else {
+            const uint64_t old_serial=m_fake_stereo_hook ?
+                m_fake_stereo_hook->native_stereo_publication_serial() : 0;
+            if (const auto error=reinitialize_openxr()) {
+                SPDLOG_WARNING_EVERY_N_SEC(2,"[TriView][Restart] checked swapchain teardown pending: {}",*error);
+            } else {
+                m_triview_restart_previous_native_serial.store(old_serial,std::memory_order_release);
+                m_triview_restart_phase.store(4,std::memory_order_release);
+                spdlog::info("[TriView][Restart] phase=4 new XR runtime created; waiting for a NEW native pair after serial {}",old_serial);
+            }
         }
     }
 }
 
+// B42: end the low-resolution start once TriView is loaded and VRAM allows it.
+void VR::service_triview_low_start() {
+    using clock = std::chrono::steady_clock;
+    const float warm = runtimes::OpenXR::triview_warmup_scale.load(std::memory_order_acquire);
+    if (warm <= 0.f || m_openxr == nullptr || get_runtime() == nullptr || !get_runtime()->loaded || !get_runtime()->is_openxr()) return;
+    static clock::time_point first{}, set_since{};
+    const auto now = clock::now();
+    if (first == clock::time_point{}) first = now;
+    const int stage = m_triview_autostart_stage;
+    const bool transitioning = stage == 1 || stage == 2 || is_mono_transition_pending();
+    const bool triview = is_quadview_mode_selected();
+    if (transitioning) { set_since = {}; return; }
+    if (!triview) {
+        if (stage == 3 || now - first > std::chrono::seconds(90)) {
+            if (m_openxr->finish_triview_warmup("TriView is not running"))
+                m_triview_b42_low_start_state.store(3, std::memory_order_relaxed);
+        }
+        return;
+    }
+    const auto rtm = m_fake_stereo_hook ? m_fake_stereo_hook->get_render_target_manager() : nullptr;
+    const auto set = rtm ? rtm->get_quadview_native_target_set() : nullptr;
+    if (!set || !set->complete()) { set_since = {}; return; }
+    if (set_since == clock::time_point{}) set_since = now;
+    if (now - set_since < std::chrono::seconds(3)) return;
+    namespace vram = uevr::quadview::vram;
+    const float full = m_openxr->resolution_scale->value();
+    const auto old_w = m_openxr->get_width_for_scale(warm), old_h = m_openxr->get_height_for_scale(warm);
+    const auto new_w = m_openxr->get_width_for_scale(full), new_h = m_openxr->get_height_for_scale(full);
+    const auto estimate = vram::resolution_switch_estimate(old_w, old_h, new_w, new_h,
+        vram::snap_fraction(m_quadview_crop_width->value(), .05f, 1.f), vram::snap_fraction(m_quadview_crop_height->value(), .05f, 1.f),
+        vram::snap_fraction(m_quadview_context_scale->value(), .05f, .50f), vram::snap_fraction(m_quadview_foveal_density->value(), .25f, 4.f));
+    const auto used = m_triview_vram_used.load(std::memory_order_relaxed);
+    const auto budget = m_triview_vram_budget.load(std::memory_order_relaxed);
+    const float limit_percent = m_triview_b42_vram_limit->value();
+    const auto mb = [](uint64_t b) { return static_cast<uint32_t>(b >> 20); };
+    if (budget == 0) return; // wait for the first DXGI reading
+    if (!vram::allows(used, budget, estimate, limit_percent)) {
+        m_triview_b42_low_start_state.store(2, std::memory_order_relaxed);
+        m_triview_b42_last_used_mb.store(mb(used), std::memory_order_relaxed);
+        m_triview_b42_last_need_mb.store(mb(estimate), std::memory_order_relaxed);
+        m_triview_b42_last_limit_mb.store(mb(vram::limit_bytes(budget, limit_percent)), std::memory_order_relaxed);
+        SPDLOG_WARNING_EVERY_N_SEC(10, "[TriView][LowStart] staying at {:.2f}: switch to {:.2f} needs ~{} MB, used {} MB, limit {} MB ({:.0f}% of {} MB)",
+            warm, full, mb(estimate), mb(used), mb(vram::limit_bytes(budget, limit_percent)), limit_percent, mb(budget));
+        return;
+    }
+    spdlog::info("[TriView][VRAM] before resolution switch: used {} MB / budget {} MB, estimate {} MB", mb(used), mb(budget), mb(estimate));
+    if (m_openxr->finish_triview_warmup("TriView loaded and VRAM allows it")) {
+        m_triview_b42_low_start_state.store(3, std::memory_order_relaxed);
+    } else if (runtimes::OpenXR::triview_warmup_scale.load(std::memory_order_relaxed) <= 0.f) {
+        // Live switch not allowed by UEVR for this engine: stay low now, and do not
+        // start low again next time (the user would otherwise be stuck low).
+        m_triview_b42_low_start->value() = false;
+        m_triview_b42_low_start_state.store(4, std::memory_order_relaxed);
+        spdlog::warn("[TriView][LowStart] live switch refused by UEVR; low-resolution start turned OFF for next starts");
+    }
+}
+
 uint32_t VR::get_hmd_width() const {
     if (m_2d_screen_mode->value()) {
         if (get_runtime()->is_openxr()) {
             return g_framework->get_rt_size().x * m_openxr->resolution_scale->value();
         }
 
@@ -15233,32 +15968,451 @@ void VR::on_draw_sidebar_entry(std::string_view name) {
         } else {
             rendering_method_changed = m_rendering_method->draw("Rendering Method");
         }
         if (has_unsupported_rendering_method()) {
             ImGui::TextWrapped("Unsupported rendering method ID %d is preserved; select an available method.", requested_rendering_method());
         }
-        if (is_using_mono() || requested_rendering_method() == RenderingMethod::MONO || is_mono_transition_pending()) {
-            ImGui::TextWrapped("Mono (Experimental): one centered, head-tracked scene for both eyes; no binocular scene depth. DX11/DX12 with OpenXR. Native Fix, Ghost Fix/bootstrap and depth submission are inactive in Mono; saved preferences are retained.");
+        if (is_using_mono() || uevr::mono::is_mono_family(requested_rendering_method()) ||
+            (is_mono_transition_pending() && uevr::mono::is_mono_family(m_rendering_method->value()))) {
+            if (!is_using_duoview_mono()) ImGui::TextWrapped("Mono (Experimental): one centered, head-tracked scene for both eyes; no binocular scene depth. DX11/DX12 with OpenXR. Native Fix, Ghost Fix/bootstrap and depth submission are inactive in Mono; saved preferences are retained.");
+            if (is_using_duoview_mono() || requested_rendering_method() == RenderingMethod::DUOVIEW_MONO) {
+                ImGui::TextWrapped(is_duoview_renderer_active() ? (duoview_gaze_active() ? "DuoView ID6: eye-tracked two-view Mono (PSVR2 Toolkit active)" : "DuoView ID6: held crop / center fallback (gaze unavailable)") : "DuoView ID6: original Joey Mono fallback / DuoView inactive");
+            }
             ImGui::TextWrapped("Mono: %s", mono_status());
             if (const auto reason = mono_unavailable_reason()) { ImGui::TextWrapped("Unavailable: %s", reason); }
             if (is_mono_transition_pending()) {
                 ImGui::TextWrapped("Requested: %s; still rendering: %s. Waiting for retired GPU copies and the next main viewport frame.",
                     uevr::mono::label(requested_rendering_method()), uevr::mono::label(m_rendering_method->value()));
             }
         }
+        if (is_using_duoview_mono() || requested_rendering_method() == RenderingMethod::DUOVIEW_MONO) {
+            if (ImGui::TreeNode("DuoView Mono — quality and diagnostics")) {
+                ImGui::TextWrapped("Settings are frozen once per new UE frame. The original Joey Mono ID5 is untouched.");
+                if (ImGui::Button("Restore old DuoView settings")) {
+                    m_duo_width->value()=.50f; m_duo_height->value()=.50f;
+                    m_duo_periphery->value()=.20f; m_duo_density->value()=1.f;
+                    m_duo_feather->value()=.08f; m_duo_gaze->value()=true;
+                    m_duo_border->value()=false; m_duo_fovea_view->value()=0;
+                    m_duo_debug_source->value()=0;
+                    m_duo_direct_xr->value()=false;
+                    m_duo_native_fix->value()=true; m_duo_quant->value()=2;
+                    m_duo_hold->value()=350; m_duo_reacquire->value()=2;
+                    m_duo_offset_x->value()=0.f; m_duo_offset_y->value()=0.f;
+                    m_duo_micro_gain->value()=0.f; m_duo_breakout->value()=.035f;
+                    m_duo_stillness->value()=.008f; m_duo_relock->value()=3;
+                }
+                m_duo_width->draw("Fovea width / full FOV");
+                m_duo_height->draw("Fovea height / full FOV");
+                m_duo_periphery->draw("Peripheral resolution scale");
+                m_duo_density->draw("Foveal pixel density");
+                m_duo_feather->draw("Blend feather width");
+                m_duo_gaze->draw("Eye tracking");
+                m_duo_border->draw("Blend border highlight");
+                m_duo_debug_source->draw("Source diagnostic: 0 Blend / 1 Periphery / 2 Fovea");
+                m_duo_fovea_view->draw("Fovea UE source view (0 or 1)");
+                m_duo_stabilize->draw("Stable gaze crop (OpenNR r10 policy)");
+                if (m_duo_stabilize->value()) m_duo_guard->draw("Crop centre guard (fraction of crop)");
+                m_duo_native_fix->draw("Native Stereo Fix shading (OFF = stock secondary-pass)");
+                ImGui::TextWrapped("Both choices keep Joey's proven two-texture DuoView capture. ON relabels the UE secondary pass as PRIMARY (Build 149). OFF preserves its stock SECONDARY label for a hybrid native-fix capture + stock-style lighting. Compare Lumen visually; this does not disable the underlying two-target capture.");
+                m_duo_quant->draw("Gaze quantization (0=off, 1-16 fovea pixels)");
+                m_duo_hold->draw("Blink / tracking-loss ray hold (milliseconds)");
+                m_duo_reacquire->draw("Consistent samples after large post-blink jump (1=instant)");
+                m_duo_offset_x->draw("Fovea horizontal offset (also in fixed mode)");
+                m_duo_offset_y->draw("Fovea vertical / height offset (also in fixed mode)");
+                ImGui::TextWrapped("Adaptive response: small gaze movement holds or follows slowly; large movement jumps 1:1 and follows at full speed; then automatically locks when steady. No heavy temporal smoothing.");
+                m_duo_micro_gain->draw("Small gaze movement gain (0=locked; 1=full)");
+                m_duo_breakout->draw("Fast 1:1 breakout (fraction of full view)");
+                m_duo_stillness->draw("Stillness threshold per gaze sample (fraction of view)");
+                m_duo_relock->draw("Quiet samples before fovea relocks");
+                if (m_duo_stillness->value() >= m_duo_breakout->value())
+                    ImGui::TextWrapped("Stillness must be below breakout; the conflicting setting is rejected, all other controls keep working.");
+                ImGui::Text("DuoView delivery: %llu copied / %llu held / %llu empty or failed",
+                    static_cast<unsigned long long>(m_openxr->duoview_copy_submits.load()),
+                    static_cast<unsigned long long>(m_openxr->duoview_hold_submits.load()),
+                    static_cast<unsigned long long>(m_openxr->duoview_empty_submits.load()));
+                if (m_fake_stereo_hook) {
+                    const auto d=m_fake_stereo_hook->duoview_delivery.counts();
+                    ImGui::TextWrapped("Transactions: %llu produced / %llu RHI pairs / %llu matched / %llu enqueued / %llu unique XR",
+                        (unsigned long long)d.produced, (unsigned long long)d.ready, (unsigned long long)d.matched,
+                        (unsigned long long)d.enqueued, (unsigned long long)d.submitted);
+                    ImGui::TextWrapped("Duplicate Presents: %llu / overwritten before XR: %llu / failures: %llu / unproven: %llu",
+                        (unsigned long long)d.duplicate_presents, (unsigned long long)d.overwritten,
+                        (unsigned long long)d.failed, (unsigned long long)d.blocked);
+                }
+                if (ImGui::Button("Reset DuoView delivery counters")) {
+                    if (m_fake_stereo_hook) m_fake_stereo_hook->duoview_delivery.reset_counts();
+                    m_openxr->duoview_copy_submits=0; m_openxr->duoview_hold_submits=0;
+                    m_openxr->duoview_empty_submits=0;
+                }
+                m_duo_direct_xr->draw("Direct XR output (experimental A/B)");
+                ImGui::TextWrapped("OFF composes once and copies to both eyes. ON blends both eye halves directly when formats match. Compare GPU timing in the same scene; either route may be faster.");
+                m_duo_timing->draw("GPU timing: DuoView raster/output (excludes UE and source gather)");
+                if (m_duo_timing->value()) {
+                    const float ms=m_duo_gpu_ms.load(std::memory_order_relaxed);
+                    if (ms >= 0.f) ImGui::Text("DuoView raster/output: %.3f ms GPU (last retired slot; excludes UE and source gather)", ms);
+                    else ImGui::TextUnformatted("GPU timing: waiting for a completed command slot");
+                }
+                const auto output_path=m_duoview_output_path.load(std::memory_order_relaxed);
+                if (output_path < 0) ImGui::TextUnformatted("XR output path: waiting for a submitted DuoView frame");
+                else ImGui::Text("Last submitted XR output path: %s",
+                    output_path ? "direct double-wide raster" : "composite and copy compatibility route");
+                const auto source_extents=m_duoview_source_extents.load(std::memory_order_relaxed);
+                const auto primary_width=static_cast<uint32_t>((source_extents>>48)&0xffffu);
+                const auto primary_height=static_cast<uint32_t>((source_extents>>32)&0xffffu);
+                const auto secondary_width=static_cast<uint32_t>((source_extents>>16)&0xffffu);
+                const auto secondary_height=static_cast<uint32_t>(source_extents&0xffffu);
+                if (primary_width && primary_height && secondary_width && secondary_height)
+                    ImGui::Text("Native source allocations: primary %ux%u, secondary %ux%u",
+                        primary_width,primary_height,secondary_width,secondary_height);
+                ImGui::TextWrapped("These are Native color-resource allocations. They do not prove the depth, G-buffer, Lumen, or other UE pass extents; measure those with a GPU capture.");
+                const auto counts=m_duoview_gaze.counters();
+                ImGui::Text("PSVR2 gaze: fresh=%llu held=%llu invalid=%llu expired=%llu unavailable=%llu",
+                    static_cast<unsigned long long>(counts.fresh),
+                    static_cast<unsigned long long>(counts.reused),
+                    static_cast<unsigned long long>(counts.invalid),
+                    static_cast<unsigned long long>(counts.expired),
+                    static_cast<unsigned long long>(counts.unavailable));
+                if (counts.age_ms == UINT32_MAX) ImGui::TextUnformatted("Last gaze sample: unavailable");
+                else ImGui::Text("Last gaze sample: %u ms", counts.age_ms);
+                configure_duoview();
+                const auto rejected=m_duo_ui_rejected_mask.load(std::memory_order_acquire);
+                if (rejected) {
+                    ImGui::TextWrapped("Control warning: one or more requested sliders are invalid; "
+                        "only those individual settings are rejected. All valid changes remain active.");
+                    const struct { uint32_t mask; const char* label; } conflicts[]={
+                        {uevr::duoview::reject_width,"Fovea width"},
+                        {uevr::duoview::reject_height,"Fovea height"},
+                        {uevr::duoview::reject_periphery,"Peripheral scale"},
+                        {uevr::duoview::reject_density,"Foveal density"},
+                        {uevr::duoview::reject_feather,"Feather"},
+                        {uevr::duoview::reject_fovea_view,"Fovea source view"},
+                        {uevr::duoview::reject_diagnostic,"Source diagnostic"},
+                        {uevr::duoview::reject_guard,"Crop guard"},
+                        {uevr::duoview::reject_quant,"Quantization"},
+                        {uevr::duoview::reject_hold,"Blink hold"},
+                        {uevr::duoview::reject_reacquire,"Reacquisition"},
+                        {uevr::duoview::reject_offset_u,"Horizontal offset"},
+                        {uevr::duoview::reject_offset_v,"Vertical offset"},
+                        {uevr::duoview::reject_micro,"Small movement gain"},
+                        {uevr::duoview::reject_breakout,"Fast breakout"},
+                        {uevr::duoview::reject_still,"Stillness threshold"},
+                        {uevr::duoview::reject_relock,"Relock samples"}};
+                    for (const auto& bad:conflicts) {
+                        if (rejected & bad.mask) ImGui::BulletText("Not applied: %s",bad.label);
+                    }
+                } else ImGui::TextUnformatted("DuoView controls: validated and accepted for next render frame");
+                const auto applied=m_duoview.settings();
+                ImGui::Text("Active Fovea W/H: %.3f / %.3f, density %.3f, periphery %.3f",
+                    applied.crop_width,applied.crop_height,applied.foveal_density,applied.peripheral_scale);
+                ImGui::Text("Active Eye Tracking: %s, Native shading: %s, fixed offsets X/Y: %.3f / %.3f",
+                    applied.eye_tracked ? "ON" : "OFF",
+                    applied.native_fix_same_pass ? "ON" : "OFF",
+                    applied.gaze_offset_u,applied.gaze_offset_v);
+                if (const auto snap=m_duoview.snapshot(duoview_producer_key())) {
+                    const auto& layout=snap->config.layout;
+                    ImGui::Text("Fovea %ux%u; peripheral %ux%u; output %ux%u",
+                        layout.fovea.width,layout.fovea.height,
+                        layout.periphery.width,layout.periphery.height,
+                        layout.atlas_width/2,layout.atlas_height);
+                    ImGui::Text("Fovea UE%u; periphery UE%u; gaze %s",
+                        snap->config.settings.fovea_view,1u-snap->config.settings.fovea_view,
+                        snap->gaze_valid ? "tracking" : "held crop / center fallback");
+                    ImGui::Text("View histories: %s; primary shading constructor: %s",
+                        snap->scene_states[0] && snap->scene_states[1]
+                            ? (snap->scene_states[0]!=snap->scene_states[1] ? "separate" : "shared") : "unobserved",
+                        snap->shading_applied ? "applied" :
+                            (snap->config.settings.independent_shading ? "requested / waiting for safe pair" : "OFF"));
+                    ImGui::Text("Applied crop centre (%.3f, %.3f), scene pixels: %.2f million",
+                        snap->config.gaze.u,snap->config.gaze.v,
+                        uevr::duoview::rendered_pixels(layout)/1000000.);
+                }
+                // Active/applied values and precise per-field rejections appear
+                // directly above; never claim the entire settings set is frozen.
+                ImGui::TextWrapped("Diagnostic 1 isolates the full-FOV peripheral pass. Diagnostic 2 isolates the foveal pass (dark outside crop). Compare shadows/lighting in the same scene.");
+                ImGui::TextWrapped("View 0 = FIRST Unreal pass (old prototype default), view 1 = SECOND pass (Build19 default). Identical frozen Mono camera. Switching may reset temporal history.");
+                ImGui::TreePop();
+            }
+        }
+        if (is_quadview_mode_selected() || requested_rendering_method() == RenderingMethod::QUAD_VIEWS_STEREO) {
+            const auto status_key=quadview_producer_key();
+            const auto status_source=quadview_producer().snapshot(status_key);
+            const bool status_triview=status_source ? status_source->layout.shared_context : true;
+            const auto status_reason=quadview_unavailable_reason();
+            const auto primary=m_quadview_display_status.state({mono_generation(),GetTickCount64(),
+                is_mono_transition_pending(),status_reason!=nullptr,quadview_native_target_set(status_key)!=nullptr});
+            uevr::quadview::draw_status_panel(primary,status_triview,[&] {
+                ImGui::TextWrapped(status_triview
+                    ? "TriView Stereo: one shared context and two real stereo focus views."
+                    : "QuadView Stereo: four engine views with independent per-eye gaze crops.");
+                if (status_reason) ImGui::TextWrapped("Unavailable: %s",status_reason);
+                ImGui::TextWrapped("Latest pipeline detail: %s",quadview_status());
+                const auto vram_used=m_triview_vram_used.load(std::memory_order_relaxed);
+                const auto vram_budget=m_triview_vram_budget.load(std::memory_order_relaxed);
+                const auto vram_system=m_triview_vram_system.load(std::memory_order_relaxed);
+                if (vram_budget)
+                    ImGui::Text("Video memory (whole game process): %.0f MB used / %.0f MB budget (%.0f%%); in system memory %.0f MB",
+                        vram_used/1048576.0, vram_budget/1048576.0, 100.0*vram_used/vram_budget, vram_system/1048576.0);
+                else ImGui::TextUnformatted("Video memory: waiting for the first DXGI reading");
+                const auto rtm_status=m_fake_stereo_hook ? m_fake_stereo_hook->get_render_target_manager() : nullptr;
+                const auto set_status=rtm_status ? rtm_status->get_quadview_native_target_set() : nullptr;
+                if (set_status) {
+                    const auto& e=set_status->extents;
+                    double source_mb=0.0;
+                    for (const auto& one : e) source_mb+=4.0*one[0]*one[1]/1048576.0;
+                    ImGui::Text("Source textures: %ux%u, %ux%u, %ux%u, %ux%u (%.0f MB colour)", e[0][0], e[0][1], e[1][0], e[1][1],
+                        e[2][0], e[2][1], e[3][0], e[3][1], source_mb);
+                } else ImGui::TextUnformatted("Source textures: not published yet");
+            });
+            if (ImGui::TreeNode(status_triview ? "TriView Stereo — focus controls and diagnostics###QuadViewControls" :
+                "QuadView Stereo — focus controls and diagnostics###QuadViewControls")) {
+                ImGui::TextWrapped("Each eye projects one calibrated head-space gaze ray through its own OpenXR eye rotation and full asymmetric frustum. Context and focus views keep independent histories; with Compact source textures each source texture is sized to its own view.");
+                m_quadview_crop_width->draw("Focus width / eye FOV");
+                m_quadview_crop_height->draw("Focus height / eye FOV");
+                m_quadview_context_scale->draw("Context resolution scale");
+                m_quadview_b41_hold_ms->draw("Hold last image on a missed frame (ms)");
+                ImGui::TextWrapped("If a frame is missing, keep showing the last image (it still follows your head) for up to this long instead of black. 250 = B41 default, 100 = B40.");
+                m_triview_b42_vram_limit->draw("VRAM limit for resizes (% of budget)");
+                ImGui::TextWrapped("A new focus/periphery size is only built while the game's video memory stays below this share of its budget. Higher = more freedom, closer to the crash point. Sizes snap to 0.05 steps.");
+                if (const auto refusals=m_triview_b42_refusals.load(std::memory_order_relaxed); refusals!=0)
+                    ImGui::TextWrapped("Resize refused %llu times (last: %u MB used + %u MB needed > %u MB limit). Lower the focus size or the resolution.",
+                        static_cast<unsigned long long>(refusals),m_triview_b42_last_used_mb.load(),m_triview_b42_last_need_mb.load(),m_triview_b42_last_limit_mb.load());
+                m_triview_b42_low_start->draw("Start TriView at low resolution");
+                m_triview_b42_low_start_scale->draw("Start resolution scale");
+                ImGui::TextWrapped("Takes effect at the next game start. Switches once to your normal resolution when TriView runs and the VRAM limit allows it. Your saved resolution is never changed.");
+                {
+                    const float warm=runtimes::OpenXR::triview_warmup_scale.load(std::memory_order_relaxed);
+                    const int state=m_triview_b42_low_start_state.load(std::memory_order_relaxed);
+                    if (warm>0.f && state==2)
+                        ImGui::TextWrapped("Low-resolution start: staying at %.2f (switch needs %u MB, used %u MB, limit %u MB)",
+                            warm,m_triview_b42_last_need_mb.load(),m_triview_b42_last_used_mb.load(),m_triview_b42_last_limit_mb.load());
+                    else if (warm>0.f) ImGui::TextWrapped("Low-resolution start: running at %.2f, waiting for TriView", warm);
+                    else if (state==4) ImGui::TextWrapped("Low-resolution start: UEVR could not switch the resolution live; staying low until restart. Low start is now OFF.");
+                    else if (state==3) ImGui::TextUnformatted("Low-resolution start: done, normal resolution in use");
+                }
+                ImGui::TextUnformatted("Compact sources: always on");
+                m_quadview_depth_reproject->draw("Periphery depth reprojection (approximate DLSS depth)");
+                if (ImGui::IsItemHovered()) ImGui::SetTooltip("B21: recent submitted periphery depth (B15 policy). Exact color/depth frame identity is not proven.");
+                m_quadview_depth_strength->draw("Periphery depth strength (1 = physical; -1 flips the direction)");
+                m_quadview_depth_show->draw("Show depth diagnostic (grey = depth; magenta checker = unavailable)");
+                {
+                    const auto s=uevr::quadview::ngx::PeripheryDepth::self().stats();
+                    ImGui::Text("Periphery depth: %s", uevr::quadview::dx12::depth_state_name(uevr::quadview::dx12::last_depth_state().load()));
+                    ImGui::Text("hooks %u/6, queue hook %s; DLSS calls %llu, periphery %llu, copied %llu, submitted %llu, used %llu, missing %llu, skipped %llu",
+                        s.hooks, s.queue_hook ? "on" : "off", (unsigned long long)s.evaluations, (unsigned long long)s.matches,
+                        (unsigned long long)s.captures, (unsigned long long)s.submits, (unsigned long long)s.used,
+                        (unsigned long long)s.missed, (unsigned long long)s.skips);
+                    ImGui::Text("want %ux%u; periphery DLSS %ux%u (depth %ux%u, fmt %u); other DLSS %ux%u", s.want_w, s.want_h, s.last_out_w, s.last_out_h, s.last_in_w, s.last_in_h, s.last_format, s.other_w, s.other_h);
+                    ImGui::Text("last skip: %s", uevr::quadview::ngx::PeripheryDepth::reason_name(s.reason));
+                    if (ImGui::Button("Save TriView snapshot (images + numbers for Claude)")) {
+                        uevr::quadview::dx12::snapshot_requested().store(true);
+                        spdlog::info("[TriView][Snapshot] requested from the menu");
+                    }
+                    ImGui::TextUnformatted(("Last snapshot: " + uevr::quadview::dx12::last_snapshot_message()).c_str());
+                }
+                ImGui::TextUnformatted("TriView: shared periphery + two stereo foveas (3 physical sources)");
+                m_quadview_foveal_density->draw("Focus pixel density");
+                m_quadview_feather->draw("Context/focus blend feather");
+                if (ImGui::TreeNode("Seam Matching")) {
+                    ImGui::TextWrapped("Off preserves the legacy feather blend. Manual applies a fixed exposure bias. Adaptive matches the periphery to each fovea using per-eye gain and an optional locally fitted boundary residual. Focus lift remains independent. Matching uses the full fovea crop when transition is zero and bypasses the feather blend while active.");
+                    m_quadview_edge_mode->draw("Edge matcher");
+                    if (m_quadview_edge_mode->value()==4) {
+                        m_quadview_edge_strength->draw("Correction strength");
+                        m_quadview_b40_stability->draw("Temporal stability");
+                        m_quadview_b41_reach_scale->draw("Colour blend distance (x B40)");
+                        ImGui::TextWrapped("How far into the periphery the colour/light match reaches (1 = B40, 3 = three times farther).");
+                        m_quadview_legacy_inward->draw("Original inward fovea feather (B27)");
+                        ImGui::TextWrapped("Motion-continuous ambient correction: 128 pooled points, 32 robust groups per eye. History holds through gaze/head motion and unusable samples. Longer presets intentionally allow trailing colors.");
+                    }
+                    if (m_quadview_edge_mode->value()!=0 && m_quadview_edge_mode->value()!=4) {
+                        ImGui::TextWrapped("Matches the displayed post-NR/SR focus edge. Temporal stabilizes the wider surrounding correction; the narrow edge responds immediately. Geometry/disocclusion differences remain possible.");
+                        m_quadview_edge_strength->draw("Edge match strength");
+                        m_quadview_edge_reach->draw("Outward reach (output pixels)");
+                        if (m_quadview_edge_mode->value()!=3)
+                            m_quadview_edge_fast->draw("Immediate edge reach (output pixels)");
+                        if (m_quadview_edge_mode->value()==3) {
+                            ImGui::TextWrapped("Ambient V3: average fifteen samples from groups of fovea pixels at three inward depths, then average the RGB correction across time. No live per-pixel mirroring at the exterior edge.");
+                            m_quadview_ambient_radius->draw("Ambient width along edge (pixels)");
+                            m_quadview_ambient_inside->draw("Ambient sampling inward (pixels)");
+                            m_quadview_ambient_time->draw("Ambient temporal average (ms)");
+                        }
+                        m_quadview_legacy_inward->draw("Original inward fovea feather (B27)");
+                        if (m_quadview_legacy_inward->value()) {
+                            m_quadview_legacy_anchor->draw("Inside seam continuity strip (pixels)");
+                            ImGui::TextWrapped("Original B27 soft periphery/focus crossfade inside the fovea; B37 corrected periphery outside. The short strip joins the colors at the crop edge. Disable for unchanged B37.");
+                        }
+                        ImGui::TextWrapped("Uses the original Context/focus blend feather. The fovea source and anti-vignette are preserved; matching corrects the context layer.");
+                        if (m_quadview_edge_mode->value()>=2) {
+                            m_quadview_edge_rate->draw("Response rate (RGB units/sec; lower = steadier)");
+                            m_quadview_edge_noise->draw("Hysteresis noise tolerance");
+                        }
+                        m_quadview_seam_debug->draw("Show edge correspondence diagnostic");
+                    }
+                    if (m_quadview_edge_mode->value()!=4) {
+                    m_quadview_seam_mode->draw("B31 mode (used when Edge matcher = B31)");
+                    if (m_quadview_seam_mode->value()==1)
+                        m_quadview_seam_brightness_ev->draw("Manual exposure bias (EV)");
+                    if (m_quadview_seam_mode->value()==2) {
+                        m_quadview_seam_strength->draw("Correction strength");
+                        m_quadview_seam_max_gain->draw("Adaptive relative gain cap (+/-)");
+                        m_quadview_seam_color_strength->draw("Color matching (0=luma, 1=chroma and luma)");
+                        m_quadview_seam_local_strength->draw("Local boundary residual strength (0=off)");
+                        m_quadview_seam_radius_px->draw("Local residual fade radius (pixels)");
+                        m_quadview_seam_debug->draw("Show adaptive confidence diagnostic");
+                    }
+                    if (m_quadview_seam_mode->value()!=0) {
+                        m_quadview_seam_transition_px->draw("Reserve existing rendered edge for transition (pixels)");
+                        ImGui::TextWrapped("A positive transition reserves part of the existing rendered fovea edge for blending and moves the sharp interior inward; it adds no rendered pixels.");
+                    }
+                    } // legacy B31 settings hidden in B40
+                    ImGui::TreePop();
+                }
+                if (ImGui::TreeNode("Fovea brightness / anti-vignette")) {
+                    ImGui::TextWrapped("Manual brightness compensation for the foveas. Edge and corner lift fades toward the center without blur. The preset is calibrated from screenshots and may not match every runtime exactly.");
+                    if (ImGui::Button("Restore calibrated focus lift preset")) {
+                        m_quadview_focus_lift_enabled->value()=true;
+                        m_quadview_focus_brightness->value()=1.f;
+                        m_quadview_focus_lift_strength->value()=1.f;
+                        m_quadview_focus_corner_gain->value()=uevr::quadview::focus_lift::default_corner_gain;
+                        m_quadview_focus_lift_onset->value()=uevr::quadview::focus_lift::default_onset;
+                        m_quadview_focus_lift_power->value()=uevr::quadview::focus_lift::default_power;
+                    }
+                    m_quadview_focus_lift_enabled->draw("Enable fovea brightness correction");
+                    if (ImGui::TreeNode("Advanced focus lift shape")) {
+                        m_quadview_focus_brightness->draw("Fovea brightness multiplier (0.8-1.3)");
+                        m_quadview_focus_lift_strength->draw("Edge and corner lift strength (0-2)");
+                        m_quadview_focus_corner_gain->draw("Corner gain (1-1.5)");
+                        m_quadview_focus_lift_onset->draw("Lift onset (0-0.9) ");
+                        m_quadview_focus_lift_power->draw("Lift curve power (0.5-3)");
+                        ImGui::TreePop();
+                    }
+                    ImGui::TreePop();
+                }
+                m_quadview_sharpen->draw("Left fovea sharpening strength (0-10)");
+                m_quadview_sharpen_max->draw("Left fovea max change per pixel (0.05-0.40; more halo risk at high values)");
+                m_quadview_sharpen_link->draw("Link right fovea sharpening to left (default ON)");
+                if (!m_quadview_sharpen_link->value()) {
+                    m_quadview_sharpen_right->draw("Right fovea sharpening strength (0-10)");
+                    m_quadview_sharpen_right_max->draw("Right fovea max change per pixel (0.05-0.40)");
+                }
+                m_quadview_gpu_timing->draw("GPU timing: QuadView raster (completed slot; excludes UE and source gather)");
+                if (m_quadview_gpu_timing->value()) {
+                    const float value=quadview_gpu_ms();
+                    if (value>=0.f) ImGui::Text("Last retired QuadView raster: %.3f ms",value);
+                    else ImGui::TextUnformatted("QuadView GPU timing: waiting for a completed command slot");
+                }
+                // B12: labels, help text, visibility and defaults button identical to DuoView v218.
+                if (ImGui::Button("Restore DuoView gaze defaults")) {
+                    m_quadview_eye_tracking->value()=true; m_quadview_stabilize_crop->value()=true; m_quadview_guard->value()=.05f;
+                    m_quadview_gaze_quant->value()=2; m_quadview_gaze_hold->value()=350; m_quadview_gaze_reacquire->value()=2;
+                    m_quadview_gaze_offset_u->value()=0.f; m_quadview_gaze_offset_v->value()=0.f;
+                    m_quadview_gaze_micro_gain->value()=0.f; m_quadview_gaze_breakout->value()=.035f;
+                    m_quadview_gaze_still->value()=.008f; m_quadview_gaze_relock->value()=3;
+                }
+                m_quadview_eye_tracking->draw("Eye tracking");
+                m_quadview_stabilize_crop->draw("Stable gaze crop (OpenNR r10 policy)");
+                if (m_quadview_stabilize_crop->value()) m_quadview_guard->draw("Crop centre guard (fraction of crop)");
+                m_quadview_gaze_quant->draw("Gaze quantization (0=off, 1-16 fovea pixels)");
+                m_quadview_gaze_hold->draw("Blink / tracking-loss ray hold (milliseconds)");
+                m_quadview_gaze_reacquire->draw("Consistent samples after large post-blink jump (1=instant)");
+                m_quadview_gaze_offset_u->draw("Fovea horizontal offset (also in fixed mode)");
+                m_quadview_gaze_offset_v->draw("Fovea vertical / height offset (also in fixed mode)");
+                ImGui::TextWrapped("Adaptive response: small gaze movement holds or follows slowly; large movement jumps 1:1 and follows at full speed; then automatically locks when steady. No heavy temporal smoothing.");
+                m_quadview_gaze_micro_gain->draw("Small gaze movement gain (0=locked; 1=full)");
+                m_quadview_gaze_breakout->draw("Fast 1:1 breakout (fraction of full view)");
+                m_quadview_gaze_still->draw("Stillness threshold per gaze sample (fraction of view)");
+                m_quadview_gaze_relock->draw("Quiet samples before fovea relocks");
+                if (m_quadview_gaze_still->value() >= m_quadview_gaze_breakout->value())
+                    ImGui::TextWrapped("Stillness must be below breakout; the conflicting setting is rejected, all other controls keep working.");
+                m_quadview_debug_border->draw("Show focus border");
+                m_quadview_debug_mode->draw("Compositor diagnostic: 0 blend / 1 context / 2 focus / 3 source colors");
+                const auto gaze=m_quadview_gaze.counters();
+                ImGui::Text("PSVR2 CAPI: %s; sample: %s",gaze.available ? "available" : "unavailable / not initialized",gaze.active ? "active" : "held or inactive");
+                if (gaze.age_ms==UINT32_MAX) ImGui::TextUnformatted("PSVR2 sample age: unknown / expired");
+                else ImGui::Text("PSVR2 sample age: %u ms",gaze.age_ms);
+                ImGui::Text("Reader totals: fresh %llu, reused %llu, invalid %llu, expired %llu, unavailable %llu",
+                    static_cast<unsigned long long>(gaze.fresh),static_cast<unsigned long long>(gaze.reused),
+                    static_cast<unsigned long long>(gaze.invalid),static_cast<unsigned long long>(gaze.expired),
+                    static_cast<unsigned long long>(gaze.unavailable));
+                const auto diagnostic_key=quadview_key();
+                if (const auto snapshot=quadview_producer().snapshot(diagnostic_key)) {
+                    ImGui::Text("Source generation %llu / draw %llu / engine frame %llu; revision %llu; histories 0x%02X; projections 0x%02X/0x%02X; context offsets 0x%02X",
+                        static_cast<unsigned long long>(snapshot->key.generation),
+                        static_cast<unsigned long long>(snapshot->key.draw_serial),
+                        static_cast<unsigned long long>(snapshot->engine_frame),
+                        static_cast<unsigned long long>(snapshot->settings_revision),
+                        snapshot->constructor_mask,snapshot->expected_projection_mask,snapshot->projection_matrix_mask,quadview_pose_mask());
+                    const auto& frame_gaze=snapshot->gaze;
+                    ImGui::Text("Frozen frame gaze: sampled %s, ray %s, CAPI %s, state %s",
+                        frame_gaze.sampled ? "yes" : "no (fixed center)",
+                        frame_gaze.ray_valid ? "valid" : "held / unavailable",
+                        frame_gaze.reader_available ? "available" : "unavailable",
+                        frame_gaze.reader_active ? "active" : "inactive");
+                    if (frame_gaze.age_ms==UINT32_MAX) ImGui::TextUnformatted("Frozen source sample age: unknown / expired");
+                    else ImGui::Text("Frozen source sample age: %u ms at tick %llu",frame_gaze.age_ms,static_cast<unsigned long long>(frame_gaze.sample_tick));
+                    ImGui::Text("Frozen source counters: fresh %llu, reused %llu, invalid %llu, expired %llu, unavailable %llu",
+                        static_cast<unsigned long long>(frame_gaze.fresh),static_cast<unsigned long long>(frame_gaze.reused),
+                        static_cast<unsigned long long>(frame_gaze.invalid),static_cast<unsigned long long>(frame_gaze.expired),
+                        static_cast<unsigned long long>(frame_gaze.unavailable));
+                    ImGui::Text("Applied focus %.3f x %.3f, context %.3f, density %.3f; tracking %s; sharpen %.2f",
+                        snapshot->settings.crop_width,snapshot->settings.crop_height,snapshot->settings.context_scale,
+                        snapshot->settings.foveal_density,snapshot->settings.eye_tracked ? "on" : "fixed center",
+                        snapshot->settings.sharpen_strength);
+                } else {
+                    ImGui::Text("Source generation %llu / draw %llu; waiting for a producer snapshot",
+                        static_cast<unsigned long long>(diagnostic_key.generation),
+                        static_cast<unsigned long long>(diagnostic_key.draw_serial));
+                }
+                const uint32_t rejected=m_quadview_rejected_settings.load(std::memory_order_acquire);
+                if (rejected || m_quadview_dimension_fallback.load(std::memory_order_acquire)) {
+                    ImGui::TextWrapped("Rejected saved controls are listed until their values are accepted:");
+                    if (rejected&uevr::quadview::reject_width) ImGui::TextUnformatted("Focus width rejected");
+                    if (rejected&uevr::quadview::reject_height) ImGui::TextUnformatted("Focus height rejected");
+                    if (rejected&uevr::quadview::reject_context) ImGui::TextUnformatted("Context scale rejected for current output dimensions");
+                    if (rejected&uevr::quadview::reject_density) ImGui::TextUnformatted("Focus density rejected for current output dimensions");
+                    if (rejected&uevr::quadview::reject_feather) ImGui::TextUnformatted("Blend feather rejected");
+                    if (rejected&uevr::quadview::reject_sharpen) ImGui::TextUnformatted("Sharpen strength rejected");
+                    if (rejected&uevr::quadview::reject_sharpen_max) ImGui::TextUnformatted("Left sharpen max change rejected");
+                    if (rejected&uevr::quadview::reject_sharpen_right) ImGui::TextUnformatted("Right sharpen strength rejected");
+                    if (rejected&uevr::quadview::reject_sharpen_right_max) ImGui::TextUnformatted("Right sharpen max change rejected");
+                    if (rejected&uevr::quadview::reject_focus_lift) ImGui::TextUnformatted("One or more focus brightness settings rejected");
+                    if (rejected&uevr::quadview::reject_seam) ImGui::TextUnformatted("One or more seam matching settings rejected");
+                    if (rejected&uevr::quadview::reject_focus_lift) ImGui::TextUnformatted("One or more focus brightness settings rejected");
+                    if (rejected&uevr::quadview::reject_diagnostic) ImGui::TextUnformatted("Diagnostic view rejected");
+                    if (rejected&uevr::quadview::reject_guard) ImGui::TextUnformatted("Gaze guard rejected");
+                    if (rejected&uevr::quadview::reject_quant) ImGui::TextUnformatted("Gaze quantization rejected");
+                    if (rejected&uevr::quadview::reject_hold) ImGui::TextUnformatted("Gaze hold duration rejected");
+                    if (rejected&uevr::quadview::reject_reacquire) ImGui::TextUnformatted("Gaze reacquisition count rejected");
+                    if (rejected&uevr::quadview::reject_offset_u) ImGui::TextUnformatted("Horizontal gaze offset rejected");
+                    if (rejected&uevr::quadview::reject_offset_v) ImGui::TextUnformatted("Vertical gaze offset rejected");
+                    if (rejected&uevr::quadview::reject_micro) ImGui::TextUnformatted("Small-motion gain rejected");
+                    if (rejected&uevr::quadview::reject_breakout) ImGui::TextUnformatted("Saccade breakout rejected");
+                    if (rejected&uevr::quadview::reject_still) ImGui::TextUnformatted("Saccade stillness rejected");
+                    if (rejected&uevr::quadview::reject_relock) ImGui::TextUnformatted("Saccade relock count rejected");
+                    if (m_quadview_dimension_fallback.load(std::memory_order_acquire)) ImGui::TextWrapped("Output dimensions changed; the applied fallback focus/context tuple matches this target.");
+                }
+                ImGui::TreePop();
+            }
+        }
         if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {
             // Method 4 owns a union projection while active. Rebuild the
             // runtime matrices when users switch into or out of it instead of
             // leaving a stale asymmetric/symmetric pair in flight.
             get_runtime()->should_recalculate_eye_projections = true;
         }
         if (!uevr::nascar::is_target()) {
             m_synced_afr_method->draw("Synced Sequential Method");
         }
 
         m_world_scale->draw("World Scale");
+        ImGui::Separator();
+        ImGui::TextUnformatted("Head Movement XYZ Scaling (independent of World Scale)");
+        m_xyz_headscale_enabled->draw("Enable Head XYZ Scaling");
+        m_xyz_headscale_x->draw("Head X - Left/Right");
+        m_xyz_headscale_y->draw("Head Y - Up/Down");
+        m_xyz_headscale_z->draw("Head Z - Forward/Back");
+        ImGui::TextWrapped("Scales HMD translation along recentered player axes: X left/right, Y up/down, Z forward/back. Recenter while facing forward. Turning your head does not rotate the scaling axes. Rotation, eye separation, controller poses and World Scale are unchanged. Set toggle and hold-bypass keys in Keybinds.");
         m_depth_scale->draw("Depth Scale");
 
         m_disable_hzbocclusion->draw("Disable HZBOcclusion");
         m_disable_instance_culling->draw("Disable Instance Culling");
         m_disable_hdr_compositing->draw("Disable HDR Composition");
         m_disable_blur_widgets->draw("Disable Blur Widgets");
@@ -16725,14 +17879,25 @@ void VR::on_draw_sidebar_entry(std::string_view name) {
             m_keybind_load_camera_1->draw("Load Camera 1 Key");
             m_keybind_load_camera_2->draw("Load Camera 2 Key");
 
             ImGui::TreePop();
         }
 
+        ImGui::SetNextItemOpen(true, ImGuiCond_::ImGuiCond_Once);
+        if (ImGui::TreeNode("Head Movement XYZ Keys")) {
+            m_xyz_headscale_toggle_key->draw("Toggle XYZ Head Scaling");
+            m_xyz_headscale_hold_bypass_key->draw("Hold to Disable XYZ Scaling");
+            ImGui::TextWrapped("Hold bypass temporarily restores normal 1x head translation; it never changes the saved enabled setting. Both bindings default to Unbound.");
+            ImGui::TreePop();
+        }
+
         ImGui::SetNextItemOpen(true, ImGuiCond_::ImGuiCond_Once);
         if (ImGui::TreeNode("Overlay/Runtime Keys")) {
+            m_duoview_fov_reapply_key->draw("Reapply FOV Key (DuoView/Tri-view)");
+            m_reinitialize_runtime_key->draw("Reinitialize Runtime Key");
+            ImGui::TextWrapped("Both default to Unbound. Bind them to different keys for independent actions, or the SAME key to reset runtime first and reapply DuoView FOV once OpenXR/gameplay recovers. The FOV key also works without a reset.");
             m_keybind_toggle_2d_screen->draw("Toggle 2D Screen Mode Key");
             m_keybind_toggle_gui->draw("Toggle In-Game UI Key");
             m_keybind_disable_vr->draw("Disable VR Key");
 
             ImGui::TreePop();
         }
@@ -16996,12 +18161,25 @@ void VR::on_draw_ui() {
         recenter_horizon();
     }
 	
     if (ImGui::Button("Reinitialize Runtime")) {
         get_runtime()->wants_reinitialize = true;
     }
+    ImGui::SameLine();
+    ImGui::BeginDisabled(!is_duoview_or_triview_fov_active());
+    if (ImGui::Button("Reapply FOV (DuoView/Tri-view)")) {
+        m_duoview_manual_fov_status.store(1, std::memory_order_release);
+        m_duoview_manual_fov_requested.store(true, std::memory_order_release);
+        SPDLOG_INFO("[DuoView][ManualFOV] Button clicked: requesting FOV refresh");
+    }
+    ImGui::EndDisabled();
+    switch (m_duoview_manual_fov_status.load(std::memory_order_acquire)) {
+    case 1: ImGui::TextDisabled("FOV reapply: pending game tick"); break;
+    case 2: ImGui::TextUnformatted("FOV reapply: verified MPC 0 / 1 (check headset)"); break;
+    case 3: ImGui::TextUnformatted("FOV reapply: failed (see log; retry in gameplay)"); break;
+    }
 }
 
 Vector4f VR::get_position(uint32_t index, bool grip) const {
     return get_transform(index, grip)[3];
 }
 
@@ -17714,6 +18892,585 @@ void VR::update_statistics_overlay(sdk::UGameEngine* engine) {
 
     if (m_show_statistics_state != m_show_statistics->value()) {
         engine->exec(L"stat unit");
         m_show_statistics_state = m_show_statistics->value();
     }
 }
+
+// Update the immutable state from persisted controls only on changes.
+void VR::configure_duoview() {
+    // Validate ALL independent settings separately. Do not let one invalid
+    // option veto any other valid controls. Latch the reconciled immutable
+    // Settings atomically on the next UE frame; never alter native source size.
+    const auto current = m_duoview.settings();
+    uevr::duoview::Settings candidate{
+        .crop_width=m_duo_width->value(), .crop_height=m_duo_height->value(),
+        .peripheral_scale=m_duo_periphery->value(), .foveal_density=m_duo_density->value(),
+        .feather_fraction=m_duo_feather->value(), .debug_border=m_duo_border->value(),
+        .eye_tracked=m_duo_gaze->value(), .fovea_view=static_cast<uint32_t>(m_duo_fovea_view->value()),
+        .diagnostic_view=static_cast<uint32_t>(m_duo_debug_source->value()),
+        .gpu_timing=m_duo_timing->value(), .direct_xr_output=m_duo_direct_xr->value(), .stabilize_crop=m_duo_stabilize->value(),
+        .guard_fraction=m_duo_guard->value(), .independent_shading=false,
+        .native_fix_same_pass=m_duo_native_fix->value(),
+        .gaze_quant_pixels=static_cast<uint32_t>(m_duo_quant->value()),
+        .gaze_hold_ms=m_duo_hold->value(), .gaze_reacquire_samples=m_duo_reacquire->value(),
+        .gaze_offset_u=m_duo_offset_x->value(), .gaze_offset_v=m_duo_offset_y->value(),
+        .gaze_micro_gain=m_duo_micro_gain->value(),
+        .gaze_breakout_radius=m_duo_breakout->value(),
+        .gaze_still_radius=m_duo_stillness->value(),
+        .gaze_relock_samples=static_cast<uint32_t>(m_duo_relock->value())};
+    const auto checked=uevr::duoview::reconcile_ui_settings(candidate,current);
+    candidate=checked.settings;
+    m_duo_ui_rejected_mask.store(checked.rejected,std::memory_order_release);
+    if (checked.rejected) {
+        SPDLOG_WARNING_EVERY_N_SEC(5,
+            "[DuoView][Controls] Rejected invalid UI fields mask=0x{:X}; "
+            "other valid controls continue; active quality width={:.3f} height={:.3f} periphery={:.3f} density={:.3f}",
+            checked.rejected,candidate.crop_width,candidate.crop_height,
+            candidate.peripheral_scale,candidate.foveal_density);
+    }
+    if (current.crop_width==candidate.crop_width && current.crop_height==candidate.crop_height &&
+        current.peripheral_scale==candidate.peripheral_scale && current.foveal_density==candidate.foveal_density &&
+        current.feather_fraction==candidate.feather_fraction && current.debug_border==candidate.debug_border &&
+        current.eye_tracked==candidate.eye_tracked && current.fovea_view==candidate.fovea_view &&
+        current.diagnostic_view==candidate.diagnostic_view && current.gpu_timing==candidate.gpu_timing &&
+        current.direct_xr_output==candidate.direct_xr_output &&
+        current.stabilize_crop==candidate.stabilize_crop && current.guard_fraction==candidate.guard_fraction &&
+        current.independent_shading==candidate.independent_shading &&
+        current.native_fix_same_pass==candidate.native_fix_same_pass &&
+        current.gaze_quant_pixels==candidate.gaze_quant_pixels &&
+        current.gaze_hold_ms==candidate.gaze_hold_ms &&
+        current.gaze_reacquire_samples==candidate.gaze_reacquire_samples &&
+        current.gaze_offset_u==candidate.gaze_offset_u &&
+        current.gaze_offset_v==candidate.gaze_offset_v &&
+        current.gaze_micro_gain==candidate.gaze_micro_gain &&
+        current.gaze_breakout_radius==candidate.gaze_breakout_radius &&
+        current.gaze_still_radius==candidate.gaze_still_radius &&
+        current.gaze_relock_samples==candidate.gaze_relock_samples) return;
+    if (!m_duoview.configure(candidate))
+        SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView][Controls] Internal validated settings rejected; retaining prior frame and reporting for diagnosis");
+}
+
+// Stage 5: sample native PSVR2 gaze ONCE per immutable source frame.
+ // CAPI unavailable or invalid => fixed center. Never adjust mid-frame.
+bool VR::is_quadview_renderer_active() const {
+    return is_quadview_layout_active() && quadview_unavailable_reason() == nullptr;
+}
+
+bool VR::is_quadview_layout_active() const {
+    const auto key=quadview_key();
+    const auto demand=m_quadview_draw_demand.get(key.generation,key.draw_serial);
+    return demand && demand->source_admission;
+}
+
+bool VR::is_duoview_renderer_active() const {
+    if (!is_using_duoview_mono() || !m_is_d3d12 || m_duoview_quarantined.load(std::memory_order_acquire)) return false;
+    const auto runtime = get_runtime();
+    if (!runtime || !runtime->is_openxr()) return false;
+    static const bool stalker2 = [] {
+        const auto path = utility::get_module_pathw(utility::get_executable());
+        return path && uevr::stalker2_native::is_executable(*path);
+    }();
+    return stalker2;
+}
+
+bool VR::is_duoview_or_triview_fov_active() const {
+    if (is_duoview_renderer_active()) return true;
+    // ID7 committed (not merely requested). Same title/API/runtime limits as DuoView.
+    if (!is_quadview_mode_selected() || !m_is_d3d12) return false;
+    const auto runtime = get_runtime();
+    if (!runtime || !runtime->is_openxr()) return false;
+    static const bool stalker2 = [] {
+        const auto path = utility::get_module_pathw(utility::get_executable());
+        return path && uevr::stalker2_native::is_executable(*path);
+    }();
+    return stalker2;
+}
+
+std::optional<uevr::duoview::ViewFrame> VR::duoview_begin_frame() {
+    if (!is_duoview_renderer_active() || !m_fake_stereo_hook ||
+        !m_fake_stereo_hook->is_in_viewport_client_draw()) return {};
+    std::call_once(m_duoview_settings_once, [this] { configure_duoview(); });
+    const auto runtime = get_runtime();
+    if (const auto candidate=m_duoview_candidate_key.load(std::memory_order_acquire)) {
+        if (candidate->generation==mono_generation()) {
+            if (const auto found=m_duoview.snapshot(*candidate)) return found;
+        }
+    }
+    const auto source_frame = runtime->internal_frame_count;
+    if (!get_openxr_runtime() || !get_openxr_runtime()->has_mono_pose(source_frame)) {
+        set_mono_status("Waiting: DuoView has no exact OpenXR Mono pose token yet");
+        return {};
+    }
+    const auto key = duoview_key();
+    auto projection = get_projection_matrix(VRRuntime::Eye::LEFT);
+    const float near_plane=sdk::globals::get_near_clipping_plane();
+    if (!std::isfinite(near_plane) || near_plane<=0.f) return {};
+    projection[3][2]=near_plane;
+    std::array<float, 16> frozen{};
+    std::memcpy(frozen.data(), &projection[0][0], sizeof(frozen));
+    const auto eye=get_eye_transform(0);
+    const std::array<float,9> optical{
+        eye[0][0],eye[0][1],eye[0][2],
+        eye[1][0],eye[1][1],eye[1][2],
+        eye[2][0],eye[2][1],eye[2][2]};
+    const auto settings=m_duoview.settings();
+    m_duoview_gaze.set_recovery_controls(static_cast<uint32_t>(settings.gaze_hold_ms),
+        static_cast<uint32_t>(settings.gaze_reacquire_samples));
+    auto frame=m_duoview.begin(key, get_hmd_width(), get_hmd_height(), frozen,
+        [this, frozen, optical]() -> std::optional<uevr::duoview::UV> {
+            return m_duoview_gaze.read_uv(frozen,optical);
+        }, GetTickCount64(), source_frame);
+    if (frame) m_duoview_candidate_key.store(
+        std::make_shared<const uevr::duoview::FrameKey>(key), std::memory_order_release);
+    return frame;
+}
+
+std::optional<uevr::quadview::Snapshot> VR::quadview_begin_frame() {
+    if (m_triview_world_epoch_gate.closed()) {
+        set_quadview_status("World recovery: source admission closed until XR callbacks and world identity are ready");
+        return {};
+    }
+    const bool renderer_active=is_quadview_renderer_active();
+    const bool hook_available=m_fake_stereo_hook!=nullptr;
+    const bool viewport_draw=hook_available && m_fake_stereo_hook->is_in_viewport_client_draw();
+    if (!renderer_active || !viewport_draw) {
+        const char* reason=!is_quadview_mode_selected() ? "mode_not_selected" :
+            !hook_available ? "fake_stereo_hook_unavailable" :
+            !renderer_active ? "renderer_not_active" : "not_viewport_draw";
+        SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][GTBegin][per-call-throttled] reason={} unavailable={} generation={} draw={} frame={}",
+            reason,quadview_unavailable_reason() ? quadview_unavailable_reason() : "none",
+            mono_generation(),m_quadview_draw_serial.load(std::memory_order_acquire),m_render_frame_count);
+        return {};
+    }
+    const auto key = quadview_key();
+    if (key.generation == 0 || key.draw_serial == 0) {
+        SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][GTBegin][per-call-throttled] reason=invalid_key generation={} draw={} frame={}",
+            key.generation,key.draw_serial,m_render_frame_count);
+        return {};
+    }
+    if (const auto candidate = m_quadview_candidate_key.load(std::memory_order_acquire);
+        candidate && *candidate == key) {
+        if (const auto snapshot = m_quadview.snapshot(key)) return snapshot;
+        SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][GTBegin][per-call-throttled] reason=duplicate_candidate_without_snapshot generation={} draw={} frame={}",
+            key.generation,key.draw_serial,m_render_frame_count);
+        return {};
+    }
+    std::optional<uevr::quadview::Layout> layout;
+    QuadViewDrawConfig draw_config{};
+    {
+        std::scoped_lock lock{m_quadview_layout_mutex};
+        if (m_quadview_draw_config_key==key && m_quadview_draw_config) {
+            draw_config=*m_quadview_draw_config;
+            layout=m_quadview_layout_latch.get(key.generation,key.draw_serial);
+        } else {
+            const auto width=get_hmd_width(), height=get_hmd_height();
+            uevr::quadview::Settings requested{};
+            // B42: snap to 0.05 steps -> few distinct view sizes for Unreal to allocate.
+            requested.crop_width=uevr::quadview::vram::snap_fraction(m_quadview_crop_width->value(),.05f,1.f);
+            requested.crop_height=uevr::quadview::vram::snap_fraction(m_quadview_crop_height->value(),.05f,1.f);
+            requested.context_scale=uevr::quadview::vram::snap_fraction(m_quadview_context_scale->value(),.05f,.50f);
+            requested.foveal_density=uevr::quadview::vram::snap_fraction(m_quadview_foveal_density->value(),.25f,4.f);
+            requested.focus_lift_enabled=m_quadview_focus_lift_enabled->value();
+            requested.focus_brightness=m_quadview_focus_brightness->value();
+            requested.focus_lift_strength=m_quadview_focus_lift_strength->value();
+            requested.focus_corner_gain=m_quadview_focus_corner_gain->value();
+            requested.focus_lift_onset=m_quadview_focus_lift_onset->value();
+            requested.focus_lift_power=m_quadview_focus_lift_power->value();
+            requested.seam_mode=static_cast<uint32_t>(m_quadview_seam_mode->value());
+            requested.seam_strength=m_quadview_seam_strength->value();
+            requested.seam_max_gain=m_quadview_seam_max_gain->value();
+            requested.seam_brightness_ev=m_quadview_seam_brightness_ev->value();
+            requested.seam_color_strength=m_quadview_seam_color_strength->value();
+            requested.seam_local_strength=m_quadview_seam_local_strength->value();
+            requested.seam_radius_px=m_quadview_seam_radius_px->value();
+            requested.seam_transition_px=m_quadview_seam_transition_px->value();
+            requested.seam_debug=m_quadview_seam_debug->value();
+            requested.edge_reach_px=m_quadview_edge_reach->value();
+            requested.edge_fast_px=m_quadview_edge_fast->value();
+            requested.edge_rate=m_quadview_edge_rate->value();
+            requested.edge_hysteresis=m_quadview_edge_noise->value();
+            requested.legacy_inward_feather=m_quadview_legacy_inward->value();
+            requested.legacy_inward_anchor_px=m_quadview_legacy_anchor->value();
+            requested.ambient_radius_px=m_quadview_ambient_radius->value();
+            requested.ambient_inside_px=m_quadview_ambient_inside->value();
+            requested.ambient_time_ms=m_quadview_edge_mode->value()==4
+                ? (m_quadview_b40_stability->value()==0 ? 75u :
+                   m_quadview_b40_stability->value()==1 ? 200u :
+                   m_quadview_b40_stability->value()==2 ? 350u : 600u)
+                : static_cast<uint32_t>(m_quadview_ambient_time->value());
+            uevr::quadview::TriViewHold::set_window_ms(static_cast<uint32_t>(m_quadview_b41_hold_ms->value()));
+            if (m_quadview_edge_mode->value()==4) {
+                // B41: B40 blend distance multiplier (x1..x3).
+                requested.edge_reach_px=std::min(m_quadview_edge_reach->value()*m_quadview_b41_reach_scale->value(),1024.f);
+            }
+            {
+                static std::once_flag b41_build_logged;
+                std::call_once(b41_build_logged,[]{ spdlog::info("[TriView][Build] B42.1 (B41.1 + VRAM guard, size snapping, rebuild pause, low-resolution start fixed for saved ID7, VRAM logs)"); });
+            }
+            if (m_quadview_edge_mode->value()!=0) {
+                requested.seam_mode=static_cast<uint32_t>(m_quadview_edge_mode->value()+2);
+                requested.seam_strength=m_quadview_edge_strength->value();
+            }
+            requested.feather_fraction=m_quadview_feather->value();
+            requested.sharpen_strength=m_quadview_sharpen->value();
+            requested.sharpen_max_change=m_quadview_sharpen_max->value();
+            requested.sharpen_link_right=m_quadview_sharpen_link->value();
+            requested.sharpen_right_strength=m_quadview_sharpen_right->value();
+            requested.sharpen_right_max_change=m_quadview_sharpen_right_max->value();
+            requested.gpu_timing=m_quadview_gpu_timing->value();
+            requested.debug_border=m_quadview_debug_border->value();
+            requested.eye_tracked=m_quadview_eye_tracking->value();
+            requested.diagnostic_view=static_cast<uint32_t>(m_quadview_debug_mode->value());
+            requested.stabilize_crop=m_quadview_stabilize_crop->value();
+            requested.guard_fraction=m_quadview_guard->value();
+            requested.gaze_quant_pixels=static_cast<uint32_t>(m_quadview_gaze_quant->value());
+            requested.gaze_hold_ms=m_quadview_gaze_hold->value();
+            requested.gaze_reacquire_samples=m_quadview_gaze_reacquire->value();
+            requested.gaze_offset_u=m_quadview_gaze_offset_u->value();
+            requested.gaze_offset_v=m_quadview_gaze_offset_v->value();
+            requested.gaze_micro_gain=m_quadview_gaze_micro_gain->value();
+            requested.gaze_breakout_radius=m_quadview_gaze_breakout->value();
+            requested.gaze_still_radius=m_quadview_gaze_still->value();
+            requested.gaze_relock_samples=static_cast<uint32_t>(m_quadview_gaze_relock->value());
+            const auto reconciled=uevr::quadview::reconcile_settings(requested,m_quadview_applied_settings,width,height);
+            m_quadview_rejected_settings.store(reconciled.rejected,std::memory_order_release);
+            m_quadview_dimension_fallback.store(reconciled.dimension_fallback,std::memory_order_release);
+            if (reconciled.rejected) set_quadview_status("One or more saved Quad Views controls are rejected; see the per-field status below");
+            if (!uevr::quadview::same_settings(reconciled.settings,m_quadview_applied_settings)) {
+                m_quadview_applied_settings=reconciled.settings; ++m_quadview_settings_revision;
+            }
+            draw_config.settings=m_quadview_applied_settings;
+            draw_config.settings_revision=m_quadview_settings_revision;
+            if (!width || !height || width>8192 || height>8192) {
+                set_quadview_status("Unsupported output dimensions; gaze sampling skipped for this draw");
+                SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][GTBegin][per-call-throttled] reason=unsupported_dimensions width={} height={} generation={} draw={}",
+                    width,height,key.generation,key.draw_serial);
+                m_quadview_draw_config_key=key; m_quadview_draw_config=draw_config;
+                return {};
+            }
+            std::optional<runtimes::OpenXR::PipelineState> pose;
+            if (m_openxr) pose=m_openxr->capture_quadview_current_pose();
+            std::optional<uevr::duoview::Ray> head_ray;
+            draw_config.gaze={};
+            draw_config.gaze.sampled=draw_config.settings.eye_tracked;
+            draw_config.gaze.sample_tick=draw_config.gaze.sampled ? GetTickCount64() : 0;
+            if (draw_config.settings.eye_tracked) {
+                m_quadview_gaze.set_recovery_controls(static_cast<uint32_t>(draw_config.settings.gaze_hold_ms),
+                    static_cast<uint32_t>(draw_config.settings.gaze_reacquire_samples));
+                head_ray=m_quadview_gaze.read_ray();
+            }
+            const auto gaze_counts=m_quadview_gaze.counters();
+            draw_config.gaze.ray_valid=head_ray.has_value();
+            draw_config.gaze.reader_available=gaze_counts.available;
+            draw_config.gaze.reader_active=gaze_counts.active;
+            draw_config.gaze.age_ms=gaze_counts.age_ms;
+            draw_config.gaze.fresh=gaze_counts.fresh; draw_config.gaze.reused=gaze_counts.reused;
+            draw_config.gaze.invalid=gaze_counts.invalid; draw_config.gaze.expired=gaze_counts.expired;
+            draw_config.gaze.unavailable=gaze_counts.unavailable;
+            std::optional<std::array<uevr::duoview::UV,2>> eye_uv;
+            bool projection_valid=true;
+            for (size_t eye=0;eye!=2;++eye) {
+                const auto matrix=get_projection_matrix(static_cast<VRRuntime::Eye>(eye));
+                std::memcpy(draw_config.projections[eye].data(),&matrix[0][0],sizeof(draw_config.projections[eye]));
+                projection_valid=projection_valid && uevr::quadview::gaze::valid_perspective_projection(draw_config.projections[eye]);
+            }
+            draw_config.base_projection_valid=projection_valid;
+            if (pose && pose->stage_views.size()==2) {
+                const auto& h=pose->view_space_location.pose.orientation;
+                const uevr::quadview::gaze::Quaternion head{static_cast<float>(h.x),static_cast<float>(h.y),static_cast<float>(h.z),static_cast<float>(h.w)};
+                std::array<uevr::quadview::gaze::Quaternion,2> eyes{};
+                for (size_t eye=0; eye!=2; ++eye) {
+                    const auto& q=pose->stage_views[eye].pose.orientation;
+                    eyes[eye]={static_cast<float>(q.x),static_cast<float>(q.y),static_cast<float>(q.z),static_cast<float>(q.w)};
+                }
+                if (draw_config.base_projection_valid && head_ray) eye_uv=uevr::quadview::gaze::project_stereo_head_ray(*head_ray,head,eyes,draw_config.projections);
+            }
+            uevr::duoview::Settings stability{};
+            stability.crop_width=draw_config.settings.crop_width; stability.crop_height=draw_config.settings.crop_height;
+            stability.peripheral_scale=draw_config.settings.context_scale; stability.foveal_density=draw_config.settings.foveal_density;
+            stability.stabilize_crop=draw_config.settings.stabilize_crop; stability.guard_fraction=draw_config.settings.guard_fraction;
+            stability.gaze_quant_pixels=draw_config.settings.gaze_quant_pixels; stability.gaze_hold_ms=draw_config.settings.gaze_hold_ms;
+            stability.gaze_reacquire_samples=draw_config.settings.gaze_reacquire_samples;
+            stability.gaze_offset_u=draw_config.settings.gaze_offset_u; stability.gaze_offset_v=draw_config.settings.gaze_offset_v;
+            stability.gaze_micro_gain=draw_config.settings.gaze_micro_gain;
+            stability.gaze_breakout_radius=draw_config.settings.gaze_breakout_radius;
+            stability.gaze_still_radius=draw_config.settings.gaze_still_radius;
+            stability.gaze_relock_samples=draw_config.settings.gaze_relock_samples;
+            stability.eye_tracked=draw_config.settings.eye_tracked;
+            const uint64_t now=GetTickCount64();
+            std::array<uevr::quadview::FocusPoint,2> focus{};
+            for (uint32_t eye=0; eye!=2; ++eye) {
+                auto eye_settings=stability; eye_settings.fovea_view=eye;
+                const auto uv=m_quadview_crop_stability[eye].update({key.generation,key.draw_serial},width,height,eye_settings,
+                    eye_uv ? std::optional<uevr::duoview::UV>{(*eye_uv)[eye]} : std::nullopt,now);
+                focus[eye]={uv.u,uv.v};
+            }
+            draw_config.gaze_valid=eye_uv.has_value();
+            // Tri-view B12 make-before-break: while new sizes have no published target
+            // set yet, draw with the last live sizes and only request the new extents.
+            m_triview_pending_extents_valid=false;
+            m_triview_hold_set.reset();
+            if (true) {
+                // Tri-view B14: ONE read of the published set for this whole draw.
+                const auto live_rtm=m_fake_stereo_hook->get_render_target_manager();
+                m_triview_hold_set=live_rtm ? live_rtm->get_quadview_native_target_set() : nullptr;
+                if (m_triview_hold_set && !m_triview_hold_set->complete()) m_triview_hold_set.reset();
+                const uintptr_t new_world=m_triview_hold_set ? m_triview_hold_set->world_identity : 0;
+                if (new_world!=m_triview_resize_world_identity) {
+                    m_triview_resize_world_identity=new_world;
+                    m_triview_resize_gate.reset();
+                    m_triview_b42_inflight.reset(); // B42
+                    SPDLOG_INFO("[TriView][Resize] published world identity changed; discard prior-size cache");
+                }
+                auto wanted=uevr::quadview::make_layout(width,height,draw_config.settings.crop_width,
+                    draw_config.settings.crop_height,draw_config.settings.context_scale,draw_config.settings.foveal_density,focus);
+                if (wanted && uevr::quadview::apply_native_local(*wanted)) {
+                    const uevr::quadview::ResizeSizes wanted_sizes{draw_config.settings.crop_width,draw_config.settings.crop_height,
+                        draw_config.settings.context_scale,draw_config.settings.foveal_density};
+                    m_triview_resize_gate.set_cooldown_ms(1500); // B42: pause after each new set
+                    const auto decision=m_triview_resize_gate.update(
+                        m_triview_hold_set ? std::optional<uevr::quadview::SourceExtents>{m_triview_hold_set->extents} : std::nullopt,
+                        uevr::quadview::triview_source_extents(*wanted),wanted_sizes,now);
+                    if (decision.request) {
+                        // B42 VRAM guard: build the new set only if VRAM stays below the limit.
+                        namespace vram=uevr::quadview::vram;
+                        const auto used=m_triview_vram_used.load(std::memory_order_relaxed);
+                        const auto budget=m_triview_vram_budget.load(std::memory_order_relaxed);
+                        const float limit_percent=m_triview_b42_vram_limit->value();
+                        const auto estimate=vram::build_estimate(decision.request_extents);
+                        const auto live_px=m_triview_hold_set ? vram::source_pixels(m_triview_hold_set->extents) : 0;
+                        // A smaller set may still be built up to 95 % (it lowers what stays alive).
+                        const bool shrinks=live_px!=0 && vram::source_pixels(decision.request_extents)<live_px;
+                        const std::array<uint32_t,2> eye{static_cast<uint32_t>(width),static_cast<uint32_t>(height)};
+                        if (m_triview_b42_guard_eye[0]==0) m_triview_b42_guard_eye=eye;
+                        // Headset resolution changed (low-res start switch, checked there; or the
+                        // user's menu slider): the set must follow the new eye size, so no refusal.
+                        const bool eye_changed=m_triview_b42_guard_eye!=eye;
+                        // The gate re-requests an in-flight build every 2 s: already allowed, its own
+                        // allocations raise "used", so it must not be judged (and cancelled) again.
+                        if (m_triview_b42_inflight && m_triview_hold_set && m_triview_hold_set->extents==*m_triview_b42_inflight)
+                            m_triview_b42_inflight.reset();
+                        if (m_triview_b42_inflight && now-m_triview_b42_inflight_ms>uevr::quadview::ResizeGate::latch_timeout_ms)
+                            m_triview_b42_inflight.reset();
+                        const bool retry=m_triview_b42_inflight && *m_triview_b42_inflight==decision.request_extents;
+                        const bool allowed=retry || eye_changed || vram::allows(used,budget,estimate,limit_percent) ||
+                            (shrinks && (budget==0 || used<=vram::limit_bytes(budget,95.f)));
+                        const auto mb=[](uint64_t b) { return static_cast<uint32_t>(b>>20); };
+                        if (allowed && retry) {
+                            m_triview_pending_extents=decision.request_extents;
+                            m_triview_pending_extents_valid=true;
+                        } else if (allowed) {
+                            m_triview_b42_guard_eye=eye;
+                            m_triview_b42_inflight=decision.request_extents;
+                            m_triview_b42_inflight_ms=now;
+                            m_triview_pending_extents=decision.request_extents;
+                            m_triview_pending_extents_valid=true;
+                            SPDLOG_INFO("[TriView][VRAM] build allowed {}x{} / {}x{}: used {} MB + estimate {} MB, limit {} MB ({:.0f}% of {} MB budget){}",
+                                decision.request_extents[0][0],decision.request_extents[0][1],
+                                decision.request_extents[2][0],decision.request_extents[2][1],
+                                mb(used),mb(estimate),mb(vram::limit_bytes(budget,limit_percent)),limit_percent,mb(budget),
+                                eye_changed ? " (headset resolution changed: guard skipped)" : shrinks && !vram::allows(used,budget,estimate,limit_percent) ? " (smaller set, allowed up to 95%)" : "");
+                        } else {
+                            m_triview_resize_gate.cancel_latch();
+                            m_triview_b42_refusals.fetch_add(1,std::memory_order_relaxed);
+                            m_triview_b42_last_used_mb.store(mb(used),std::memory_order_relaxed);
+                            m_triview_b42_last_need_mb.store(mb(estimate),std::memory_order_relaxed);
+                            m_triview_b42_last_limit_mb.store(mb(vram::limit_bytes(budget,limit_percent)),std::memory_order_relaxed);
+                            SPDLOG_WARNING_EVERY_N_SEC(2,"[TriView][VRAM] resize REFUSED {}x{} / {}x{}: used {} MB + estimate {} MB > limit {} MB ({:.0f}% of {} MB budget); keeping the live set (refusals {})",
+                                decision.request_extents[0][0],decision.request_extents[0][1],
+                                decision.request_extents[2][0],decision.request_extents[2][1],
+                                mb(used),mb(estimate),mb(vram::limit_bytes(budget,limit_percent)),limit_percent,mb(budget),
+                                m_triview_b42_refusals.load(std::memory_order_relaxed));
+                        }
+                    }
+                    if (decision.hold) {
+                        draw_config.settings.crop_width=decision.draw.crop_width;
+                        draw_config.settings.crop_height=decision.draw.crop_height;
+                        draw_config.settings.context_scale=decision.draw.context_scale;
+                        draw_config.settings.foveal_density=decision.draw.foveal_density;
+                        SPDLOG_INFO_EVERY_N_SEC(1,"[TriView][Resize] new sizes wanted; drawing with the live set ({}). Build in flight: {}x{} / {}x{}",
+                            decision.request ? "one build requested" : "waiting until the sizes stop changing",
+                            m_triview_pending_extents[0][0],m_triview_pending_extents[0][1],m_triview_pending_extents[2][0],m_triview_pending_extents[2][1]);
+                    }
+                }
+            }
+            auto candidate=uevr::quadview::make_layout(width,height,draw_config.settings.crop_width,
+                draw_config.settings.crop_height,draw_config.settings.context_scale,draw_config.settings.foveal_density,focus);
+            if (!candidate) {
+                set_quadview_status("No valid four-view layout for this output extent; frame source rejected");
+                SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][GTBegin][per-call-throttled] reason=layout_rejected width={} height={} crop={}x{} context={} density={} generation={} draw={}",
+                    width,height,draw_config.settings.crop_width,draw_config.settings.crop_height,draw_config.settings.context_scale,
+                    draw_config.settings.foveal_density,key.generation,key.draw_serial);
+                m_quadview_draw_config_key=key; m_quadview_draw_config=draw_config;
+                { std::scoped_lock pose_lock{m_quadview_pose_mutex}; m_quadview_pose_key=key; m_quadview_pose=std::move(pose); m_quadview_pose_eye_mask=0; }
+                return {};
+            }
+            if (true && !is_stereo_emulation_enabled() &&
+                !(draw_config.base_projection_valid &&
+                  [&]() {
+                      if (!pose || pose->stage_views.size()!=2) return false;
+                      std::array<std::array<float,4>,2> q{};
+                      for (size_t eye=0; eye!=2; ++eye) {
+                          const auto& o=pose->stage_views[eye].pose.orientation;
+                          q[eye]={static_cast<float>(o.x),static_cast<float>(o.y),static_cast<float>(o.z),static_cast<float>(o.w)};
+                      }
+                      return uevr::quadview::apply_shared_context(*candidate,draw_config.projections[0],
+                          draw_config.projections[1],&q[0],&q[1]);
+                  }()))
+                set_quadview_status("Tri-view could not derive the shared context frustum; using four views");
+            // Tri-view B7: periphery depth reprojection shift, frozen with the draw.
+            // near = UE near plane (projection m[3][2], cm); IPD from the runtime eye offsets
+            // (metres) x get_world_to_meters() (includes World Scale).
+            candidate->depth_shift=uevr::quadview::periphery_depth_shift(*candidate,
+                draw_config.base_projection_valid ? double(draw_config.projections[0][14]) : 0.0,
+                0.5*std::abs(pose
+                    ? double(pose->quadview_head_views[1].pose.position.x)-double(pose->quadview_head_views[0].pose.position.x)
+                    : double(get_eye_offset(VRRuntime::Eye::RIGHT).x)-double(get_eye_offset(VRRuntime::Eye::LEFT).x))*
+                    double(get_world_to_meters()),
+                double(m_quadview_depth_strength->value()));
+            // B10: exact eye origins in the rendered left-optical context basis.
+            if (candidate->shared_context && pose && pose->stage_views.size()==2 && draw_config.base_projection_valid) {
+                const auto& q=pose->stage_views[0].pose.orientation;
+                const double x=q.x,y=q.y,z=q.z,w=q.w;
+                const double norm=x*x+y*y+z*z+w*w;
+                const double units=get_world_to_meters();
+                if (std::isfinite(norm) && std::abs(norm-1.)<1.e-3 && std::isfinite(units) && units>0.) {
+                    const double r[3][3]{{1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)},
+                        {2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)},
+                        {2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)}};
+                    const auto& l=pose->stage_views[0].pose.position;
+                    const auto& rr=pose->stage_views[1].pose.position;
+                    const double center[3]{(l.x+rr.x)*.5,(l.y+rr.y)*.5,(l.z+rr.z)*.5};
+                    std::array<std::array<double,3>,2> origins{};
+                    for (size_t eye=0;eye<2;++eye) {
+                        const auto& t=pose->stage_views[eye].pose.position;
+                        const double delta[3]{t.x-center[0],t.y-center[1],t.z-center[2]};
+                        for(size_t axis=0;axis<3;++axis) for(size_t j=0;j<3;++j)
+                            origins[eye][axis]+=r[j][axis]*delta[j]*units*(axis==2 ? -1. : 1.);
+                    }
+                    std::array<double,16> context{};
+                    for(size_t i=0;i<16;++i) context[i]=draw_config.projections[0][i];
+                    context[0]=candidate->context_projection[0];context[8]=candidate->context_projection[1];
+                    context[5]=candidate->context_projection[2];context[9]=candidate->context_projection[3];
+                    (void)uevr::quadview::configure_depth_geometry(*candidate,context,origins,double(m_quadview_depth_strength->value()));
+                }
+            }
+            // Tri-view B6: use compact per-role targets for this draw only when a
+            // matching live set is already published; otherwise keep the atlas layout.
+            // Only READ the published set here (lock-free): ensure() may spawn actors and
+            // flush rendering and must not run under m_quadview_layout_mutex. The request
+            // and the liveness check happen after the freeze, outside the lock.
+            if (true) {
+                auto compact=*candidate;
+                const auto compact_rtm=m_fake_stereo_hook->get_render_target_manager();
+                if (uevr::quadview::apply_native_local(compact) && compact_rtm && is_quadview_supported_title()) {
+                    // Tri-view B14: the same snapshot the size hold looked at.
+                    const auto set=m_triview_hold_set;
+                    if (set && set->extents==uevr::quadview::triview_source_extents(compact) && set->complete()) {
+                        *candidate=compact;
+                        m_triview_resize_gate.confirm_live(set->extents,{draw_config.settings.crop_width,draw_config.settings.crop_height,
+                            draw_config.settings.context_scale,draw_config.settings.foveal_density});
+                    }
+                }
+            }
+            layout=m_quadview_layout_latch.freeze(key.generation,key.draw_serial,*candidate);
+            m_quadview_draw_config_key=key; m_quadview_draw_config=draw_config;
+            {
+                std::scoped_lock pose_lock{m_quadview_pose_mutex};
+                m_quadview_pose_key=key; m_quadview_pose=std::move(pose); m_quadview_pose_eye_mask=0;
+            }
+        }
+    }
+    if (!layout) {
+        set_quadview_status("No frozen structural layout is available for this draw");
+        SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][GTBegin][per-call-throttled] reason=frozen_layout_unavailable generation={} draw={} frame={}",
+            key.generation,key.draw_serial,m_render_frame_count);
+        return {};
+    }
+    if (!layout->shared_context) {
+        set_quadview_status("TriView requires a valid shared periphery pose; skipping this draw (QuadView fallback disabled)");
+        return {};
+    }
+    const auto rtm = m_fake_stereo_hook->get_render_target_manager();
+    std::shared_ptr<const VRRenderTargetManager_Base::QuadViewNativeTargetSetSnapshot> native_target_set{};
+    // Tri-view B6: while compact sources are ON always request the compact set (no
+    // thrash between atlas and compact sizes); the draw follows its frozen layout.
+    auto requested_extents=uevr::quadview::triview_source_extents(*layout);
+    if (true && !layout->native_local) {
+        auto compact=*layout;
+        if (uevr::quadview::apply_native_local(compact)) requested_extents=uevr::quadview::triview_source_extents(compact);
+    }
+    if (true && m_triview_pending_extents_valid) requested_extents=m_triview_pending_extents;
+    if (rtm && is_quadview_supported_title() && rtm->ensure_quadview_native_target_set(requested_extents))
+        native_target_set=rtm->get_quadview_native_target_set();
+    // Tri-view B14: this draw's sizes were chosen against m_triview_hold_set. If a
+    // build published (or is still building) in between, keep drawing from that
+    // held set: it is still owned here and retires through the fenced owner path.
+    // Same world only; with no published set (world change) the old rule applies.
+    if (rtm && m_triview_hold_set &&
+        (!native_target_set || native_target_set->extents!=uevr::quadview::triview_source_extents(*layout))) {
+        const auto published=rtm->get_quadview_native_target_set();
+        const auto& hold=m_triview_hold_set;
+        if (published && published->world_identity==hold->world_identity && hold->complete() &&
+            hold->extents==uevr::quadview::triview_source_extents(*layout) && rtm->quadview_native_targets_live(*hold)) {
+            if (published.get()!=hold.get())
+                SPDLOG_INFO_EVERY_N_SEC(1,"[TriView][Resize] new set published during this draw; drawing it from the held set");
+            native_target_set=hold;
+        }
+    }
+    m_triview_hold_set.reset();
+    const bool native_target_ready=native_target_set &&
+        native_target_set->extents==uevr::quadview::triview_source_extents(*layout) && native_target_set->complete();
+    {   // Tri-view B7: which DLSS output is the periphery (0 = unknown or a fovea has the same size).
+        const auto& c=layout->views[0]; const auto& f=layout->views[2];
+        const bool usable=layout->shared_context && !uevr::quadview::ngx::matches_periphery(f.width,f.height,c.width,c.height);
+        uevr::quadview::ngx::PeripheryDepth::self().set_expected(usable ? c.width : 0u, usable ? c.height : 0u);
+    }
+    if (layout->native_local && !native_target_ready)
+        SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][Compact] compact layout frozen but its target set is no longer live (generation={} draw={})",
+            key.generation,key.draw_serial);
+    draw_config.native_target_set_ready=native_target_ready;
+    draw_config.native_target_set_generation=native_target_ready ? native_target_set->generation : 0;
+    draw_config.native_target_set=native_target_ready ? native_target_set : nullptr;
+    { std::scoped_lock lock{m_quadview_layout_mutex}; if (m_quadview_draw_config_key==key && m_quadview_draw_config) {
+        m_quadview_draw_config->native_target_set_ready=draw_config.native_target_set_ready;
+        m_quadview_draw_config->native_target_set_generation=draw_config.native_target_set_generation;
+        m_quadview_draw_config->native_target_set=draw_config.native_target_set; } }
+    if (!native_target_ready) set_quadview_status("Four-source native targets are warming up; this draw keeps the complete legacy family");
+    const auto target = rtm != nullptr ? rtm->get_view_family_render_target() : nullptr;
+    if (!m_quadview.begin(key, 0, reinterpret_cast<uintptr_t>(target), 0, *layout,draw_config.settings,draw_config.settings_revision,draw_config.gaze)) {
+        if (const auto snapshot = m_quadview.snapshot(key)) return snapshot;
+        set_quadview_status("Waiting for a fresh four-view producer transaction");
+        SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][GTBegin][per-call-throttled] reason=producer_begin_rejected generation={} draw={} frame={} target={:x} revision={}",
+            key.generation,key.draw_serial,m_render_frame_count,reinterpret_cast<uintptr_t>(target),draw_config.settings_revision);
+        return {};
+    }
+    m_quadview_candidate_key.store(std::make_shared<const uevr::quadview::Key>(key), std::memory_order_release);
+    set_quadview_status("Waiting for four engine view histories and main-family raster");
+    return m_quadview.snapshot(key);
+}
+
+std::optional<uevr::quadview::Layout> VR::quadview_layout_for_hooks() {
+    const auto key=quadview_key();
+    if (is_quadview_renderer_active() && m_fake_stereo_hook && m_fake_stereo_hook->is_in_viewport_client_draw())
+        (void)quadview_begin_frame();
+    {
+        std::scoped_lock lock{m_quadview_layout_mutex};
+        if (const auto layout=m_quadview_layout_latch.get(key.generation,key.draw_serial)) return layout;
+    }
+    const auto fallback=uevr::quadview::make_layout(get_hmd_width(),get_hmd_height(),.50f,.50f,.20f,1.0f,.50f,.50f);
+    if (!fallback) return {};
+    std::scoped_lock lock{m_quadview_layout_mutex};
+    return m_quadview_layout_latch.freeze(key.generation,key.draw_serial,*fallback);
+}
+
+void VR::duoview_abort(const char* reason) {
+    if (!is_using_duoview_mono()) return;
+    SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] Quarantining two-view path; continuing original Mono inside ID6: {}", reason);
+    m_duoview_quarantined.store(true, std::memory_order_release);
+    m_duoview.retire();
+    if (m_fake_stereo_hook) m_fake_stereo_hook->duoview_delivery.retire(mono_generation());
+    m_duoview_candidate_key.store(nullptr, std::memory_order_release);
+    m_duoview_frozen_key.store(nullptr, std::memory_order_release);
+    set_mono_status("DuoView fault: rendering original Mono inside ID6; reselect ID6 to retry");
+}
diff --git a/src/mods/VR.hpp b/src/mods/VR.hpp
index 6bb961a9..6a1f4461 100644
--- a/src/mods/VR.hpp
+++ b/src/mods/VR.hpp
@@ -1,7 +1,9 @@
+#include "vr/TriViewEpochGate.hpp"
 #pragma once
+#include "vr/QuadViewStatus.hpp"
 
 #define NOMINMAX
 
 #include <memory>
 #include <string>
 #include <string_view>
@@ -31,12 +33,20 @@
 #include "vr/FFakeStereoRenderingHook.hpp"
 #include "vr/RenderTargetPoolHook.hpp"
 #include "vr/CVarManager.hpp"
 
 #include "Mod.hpp"
 #include "vr/RenderingMethodSetting.hpp"
+#include "vr/DuoViewState.hpp"
+#include "vr/QuadViewProducer.hpp"
+#include "vr/QuadViewViewDemand.hpp"
+#include "vr/QuadViewSettings.hpp"
+#include "vr/QuadViewGaze.hpp"
+#include "vr/QuadViewPSVR2Gaze.hpp"
+#include "vr/DuoViewCropStability.hpp"
+#include "vr/DuoViewPSVR2Gaze.hpp"
 #include "vr/SteamFrameInput.hpp"
 #include "vr/GamepadRecovery.hpp"
 #include "vr/ProSpiCameraProbe.hpp"
 #include "vr/ProSpiCameraFraming.hpp"
 #include "vr/ProSpiCelebrationFraming.hpp"
 #include "vr/ProSpiCameraCutGuard.hpp"
@@ -54,12 +64,14 @@ public:
         NATIVE_STEREO = 0,
         SYNCHRONIZED = 1,
         ALTERNATING = 2,
         SYNTHETIC_DIBR = 3,
         SYNTHETIC_DIBR_SINGLE_VIEW = 4,
         MONO = uevr::mono::method_id,
+        DUOVIEW_MONO = uevr::mono::duoview_method_id,
+        QUAD_VIEWS_STEREO = uevr::mono::quadview_method_id,
     };
 
     enum SynchronizeStage {
         EARLY = 0,
         LATE = 1,
         VERY_LATE = 2,
@@ -178,12 +190,14 @@ public:
     void on_frame() override;
 
     void on_present() override;
     void on_post_present() override;
 
     void on_device_reset() override {
+        m_duoview.retire();
+        m_quadview.retire_all();
         get_runtime()->on_device_reset();
 
         if (m_fake_stereo_hook != nullptr) {
             m_fake_stereo_hook->on_device_reset();
         }
 
@@ -455,12 +469,26 @@ public:
     CameraViewOffsets get_camera_view_offsets(const uevr::prospi::trace::Pose& input) const;
 
     auto get_world_scale() const {
         return m_world_scale->value();
     }
 
+    // Tracking-space movement only; no origin/reference resets or eye changes.
+    glm::vec3 get_xyz_head_movement_gains() const {
+        if (!m_xyz_headscale_enabled->value() ||
+            m_xyz_headscale_hold_bypass.load(std::memory_order_relaxed)) {
+            return {1.0f, 1.0f, 1.0f};
+        }
+        const auto valid_gain = [](float v) {
+            return std::isfinite(v) && v >= 0.05f && v <= 5.0f ? v : 1.0f;
+        };
+        return {valid_gain(m_xyz_headscale_x->value()),
+                valid_gain(m_xyz_headscale_y->value()),
+                valid_gain(m_xyz_headscale_z->value())};
+    }
+
     auto is_stereo_emulation_enabled() const {
         return m_stereo_emulation_mode;
     }
 
     void reset_present_event() {
         ResetEvent(m_present_finished_event);
@@ -484,40 +512,195 @@ public:
     }
 
     auto& get_vr_mutex() {
         return m_openvr_mtx;
     }
 
-    bool is_using_mono() const { return m_rendering_method->value() == RenderingMethod::MONO; }
+    bool is_using_mono() const { return uevr::mono::is_mono_family(m_rendering_method->value()); }
+    bool is_using_duoview_mono() const { return m_rendering_method->value() == RenderingMethod::DUOVIEW_MONO; }
+    bool is_quadview_mode_selected() const { return m_rendering_method->value() == RenderingMethod::QUAD_VIEWS_STEREO; }
+    // Public query for RHI and presentation adapters; the cutoff remains private.
+    bool triview_source_epoch_accepts(uint64_t serial) const {
+        return serial && serial>=m_triview_world_first_serial.load(std::memory_order_acquire);
+    }
+    auto triview_epoch_read() const { return m_triview_world_epoch_gate.read(); }
+    bool triview_world_epoch_closed() const { return m_triview_world_epoch_gate.closed(); }
+    int triview_restart_phase() const noexcept {
+        return m_triview_restart_phase.load(std::memory_order_acquire);
+    }
+    bool is_quadview_layout_active() const;
+    bool is_quadview_supported_title() const;
+    bool is_quadview_renderer_active() const;
+    const char* quadview_unavailable_reason() const;
+    bool is_duoview_renderer_active() const;
+    // Tri-view B5: the DuoView FOV fix (MPC override, Reapply FOV, auto reapply) also runs in ID7.
+    bool is_duoview_or_triview_fov_active() const;
+    // Tri-view B6: game-process video memory (DXGI), sampled by D3D12Component.
+    void note_triview_vram(uint64_t used, uint64_t budget, uint64_t system) {
+        m_triview_vram_used.store(used, std::memory_order_relaxed);
+        m_triview_vram_budget.store(budget, std::memory_order_relaxed);
+        m_triview_vram_system.store(system, std::memory_order_relaxed);
+    }
+    std::atomic<uint64_t> m_triview_vram_used{0}, m_triview_vram_budget{0}, m_triview_vram_system{0};
+    // B42 VRAM guard / low-resolution start state (MB values for the menu and logs).
+    std::atomic<uint64_t> m_triview_b42_refusals{0};
+    std::atomic<uint32_t> m_triview_b42_last_used_mb{0}, m_triview_b42_last_need_mb{0}, m_triview_b42_last_limit_mb{0};
+    std::atomic<int> m_triview_b42_low_start_state{0}; // 0 unused, 1 waiting, 2 refused by guard, 3 switched
+    void service_triview_low_start(); // present thread, every frame
+    // Tri-view B7 periphery depth (read by D3D12Component on the present thread).
+    bool quadview_depth_reproject() const { return m_quadview_depth_reproject->value(); }
+    bool quadview_depth_show() const { return m_quadview_depth_show->value(); }
+    uevr::duoview::State& duoview_state() { return m_duoview; }
+    void duoview_start_draw() {
+        m_duoview_draw_serial.fetch_add(1, std::memory_order_acq_rel);
+        m_duoview_candidate_key.store(nullptr, std::memory_order_release);
+        m_duoview_frozen_key.store(nullptr, std::memory_order_release);
+        m_quadview_draw_serial.fetch_add(1, std::memory_order_acq_rel);
+        m_quadview_candidate_key.store(nullptr, std::memory_order_release);
+        { std::scoped_lock lock{m_quadview_layout_mutex}; m_quadview_draw_config.reset(); m_quadview_draw_config_key={}; }
+        { std::scoped_lock lock{m_quadview_pose_mutex}; m_quadview_pose.reset(); m_quadview_pose_key={}; m_quadview_pose_eye_mask=0; }
+        const auto key=quadview_key();
+        m_quadview_draw_demand.begin(key.generation,key.draw_serial,is_quadview_mode_selected(),is_mono_transition_pending(),
+            m_rendering_method->selection().request_token());
+    }
+    uevr::quadview::Key quadview_key() const {
+        return {mono_generation(), m_quadview_draw_serial.load(std::memory_order_acquire)};
+    }
+    uevr::quadview::Key quadview_producer_key() const {
+        const auto candidate=m_quadview_candidate_key.load(std::memory_order_acquire);
+        return candidate && candidate->generation==mono_generation() ? *candidate : quadview_key();
+    }
+    uevr::quadview::Producer& quadview_producer() { return m_quadview; }
+    const uevr::quadview::Producer& quadview_producer() const { return m_quadview; }
+    std::optional<uevr::quadview::Layout> quadview_layout_for_hooks();
+    std::optional<uevr::quadview::Snapshot> quadview_begin_frame();
+    std::optional<uevr::quadview::gaze::Projection> quadview_base_projection(uevr::quadview::Key key,uint32_t eye) const {
+        std::scoped_lock lock{m_quadview_layout_mutex};
+        return eye<2 && m_quadview_draw_config_key==key && m_quadview_draw_config && m_quadview_draw_config->base_projection_valid
+            ? std::optional<uevr::quadview::gaze::Projection>{m_quadview_draw_config->projections[eye]} : std::nullopt;
+    }
+    std::shared_ptr<const VRRenderTargetManager_Base::QuadViewNativeTargetSetSnapshot> quadview_native_target_set(uevr::quadview::Key key) const {
+        std::scoped_lock lock{m_quadview_layout_mutex};
+        return m_quadview_draw_config_key==key && m_quadview_draw_config && m_quadview_draw_config->native_target_set_ready
+            ? m_quadview_draw_config->native_target_set : nullptr;
+    }
+    unsigned quadview_desired_view_count() const {
+        const auto key=quadview_key();
+        const auto demand=m_quadview_draw_demand.get(key.generation,key.draw_serial);
+        return demand ? demand->view_count : 2u;
+    }
+    bool quadview_transition_draw_closed() const {
+        const auto& selection=m_rendering_method->selection();
+        const auto key=quadview_key();
+        return m_quadview_draw_demand.transition_closed(key.generation,key.draw_serial,
+            selection.request_token(),is_quadview_mode_selected(),selection.pending());
+    }
+    // Available before either context eye is marked complete. Used only by
+    // the current ID7 draw's camera calculation, never by general HMD queries.
+    struct QuadViewCameraPose {
+        XrSpaceLocation view_space_location{XR_TYPE_SPACE_LOCATION};
+        std::array<XrView,2> quadview_head_views{};
+        uint64_t quadview_locate_serial{};
+    };
+    std::optional<QuadViewCameraPose> quadview_camera_pose() const {
+        const auto key=quadview_key();
+        std::scoped_lock lock{m_quadview_pose_mutex};
+        if (m_quadview_pose_key!=key || !m_quadview_pose) return std::nullopt;
+        return QuadViewCameraPose{m_quadview_pose->view_space_location,
+            m_quadview_pose->quadview_head_views,m_quadview_pose->quadview_locate_serial};
+    }
+    bool quadview_note_eye_pose(uint32_t eye, uint64_t located_serial) {
+        if (eye > 1 || !is_quadview_renderer_active() || m_openxr == nullptr) return false;
+        const auto key=quadview_key();
+        std::scoped_lock lock{m_quadview_pose_mutex};
+        if (m_quadview_pose_key != key || !m_quadview_pose || m_quadview_pose->stage_views.size()!=2 ||
+            m_quadview_pose->frame_state.predictedDisplayTime<=0 || m_quadview_pose->frame_state.shouldRender!=XR_TRUE) return false;
+        if (!located_serial || located_serial!=m_quadview_pose->quadview_locate_serial) return false;
+        m_quadview_pose_eye_mask |= static_cast<uint8_t>(1u << eye);
+        return true;
+    }
+    std::optional<runtimes::OpenXR::PipelineState> quadview_frozen_pose(uevr::quadview::Key key) const {
+        std::scoped_lock lock{m_quadview_pose_mutex};
+        return m_quadview_pose_key == key && m_quadview_pose_eye_mask == 0x03 ? m_quadview_pose : std::nullopt;
+    }
+    uint8_t quadview_pose_mask() const { std::scoped_lock lock{m_quadview_pose_mutex}; return m_quadview_pose_eye_mask; }
+    void set_quadview_status(const char* text) { m_quadview_status.store(text, std::memory_order_release); }
+    const char* quadview_status() const { return m_quadview_status.load(std::memory_order_acquire); }
+    void note_quadview_xr_submit(uint64_t generation, uint64_t serial, uint64_t tick) {
+        if (generation == mono_generation()) m_quadview_display_status.submitted(generation, serial, tick);
+    }
+    uevr::quadview::StatusTracker m_quadview_display_status;
+    void note_quadview_gpu_ms(float value) { if (std::isfinite(value)) m_quadview_gpu_ms.store(value,std::memory_order_release); }
+    float quadview_gpu_ms() const { return m_quadview_gpu_ms.load(std::memory_order_acquire); }
+    uevr::duoview::FrameKey duoview_key() const {
+        return {mono_generation(), m_duoview_draw_serial.load(std::memory_order_acquire)};
+    }
+    uevr::duoview::FrameKey duoview_producer_key() const {
+        if (m_fake_stereo_hook && m_fake_stereo_hook->is_in_viewport_client_draw()) {
+            const auto candidate = m_duoview_candidate_key.load(std::memory_order_acquire);
+            if (candidate && candidate->generation == mono_generation()) return *candidate;
+        }
+        const auto frozen = m_duoview_frozen_key.load(std::memory_order_acquire);
+        if (frozen && frozen->generation == mono_generation()) return *frozen;
+        const auto candidate = m_duoview_candidate_key.load(std::memory_order_acquire);
+        if (candidate && candidate->generation == mono_generation()) return *candidate;
+        return duoview_key();
+    }
+    bool duoview_note_main_family(uint32_t, bool main, uint32_t count) {
+        const auto candidate = m_duoview_candidate_key.load(std::memory_order_acquire);
+        if (!candidate || candidate->generation != mono_generation() ||
+            !m_duoview.family(*candidate, main, count)) return false;
+        const auto frame = m_duoview.snapshot(*candidate);
+        if (!frame || !frame->mono_source_frame || !get_openxr_runtime() ||
+            !get_openxr_runtime()->has_mono_pose(*frame->mono_source_frame)) return false;
+        m_duoview_frozen_key.store(candidate, std::memory_order_release);
+        return true;
+    }
+    std::optional<uint32_t> duoview_mono_source_frame() const {
+        const auto frame = m_duoview.snapshot(duoview_producer_key());
+        return frame ? frame->mono_source_frame : std::optional<uint32_t>{};
+    }
+    bool duoview_gaze_active() const { return m_duoview.settings().eye_tracked && m_duoview_gaze.active(); }
+    void configure_duoview();
+    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }
+    void note_duoview_output_path(bool direct_xr) {
+        m_duoview_output_path.store(direct_xr ? 1 : 0, std::memory_order_relaxed);
+    }
+    void note_duoview_source_extents(uint64_t packed) {
+        m_duoview_source_extents.store(packed,std::memory_order_relaxed);
+    }
+    std::optional<uevr::duoview::ViewFrame> duoview_begin_frame();
+    void duoview_abort(const char* reason);
     bool is_mono_transition_pending() const { return m_rendering_method->selection().pending(); }
     bool is_mono_transition_waiting() const {
         return m_mono_ready_generation.load(std::memory_order_acquire) != mono_generation();
     }
     bool is_mono_transition_quiescing() const {
         return is_mono_transition_pending() &&
-            (requested_rendering_method() != RenderingMethod::MONO || mono_unavailable_reason() == nullptr);
+            (!uevr::mono::is_mono_family(requested_rendering_method()) || mono_unavailable_reason() == nullptr);
     }
     uint64_t mono_generation() const { return m_rendering_method->selection().generation(); }
     uint64_t mono_request_token() const { return m_rendering_method->selection().request_token(); }
     int32_t requested_rendering_method() const { return m_rendering_method->requested_value(); }
     bool has_unsupported_rendering_method() const { return !m_rendering_method->is_available(requested_rendering_method()); }
     const char* mono_unavailable_reason() const;
     bool service_mono_transition_present();
     void service_mono_transition_game_thread();
     bool mono_frame_gate_required() const {
+        if (is_quadview_mode_selected()) return false;
         const auto state = m_rendering_method->selection().snapshot();
         return uevr::mono::needs_frame_gate(state.method, state.generation, m_mono_ready_generation.load(std::memory_order_acquire));
     }
     void note_mono_frame_ready(uint64_t generation) { m_mono_ready_generation.store(generation, std::memory_order_release); }
     bool take_mono_main_view_update(uint32_t frame);
     bool take_mono_attachment_update(uint32_t frame);
     const char* mono_status() const { return m_mono_status.load(std::memory_order_acquire); }
     void set_mono_status(const char* status) { m_mono_status.store(status, std::memory_order_release); }
 
     bool is_using_afr() const {
-        if (is_using_mono()) { return false; }
+        if (is_using_mono() || is_quadview_mode_selected()) { return false; }
         return m_rendering_method->value() == RenderingMethod::ALTERNATING || 
                m_rendering_method->value() == RenderingMethod::SYNCHRONIZED ||
                m_extreme_compat_mode->value() == true;
     }
 
     bool is_using_native_stereo() const {
@@ -571,14 +754,20 @@ public:
     }
 
     float get_depth_scale() const {
         return m_depth_scale->value();
     }
 
+    // Tri-view B12: TriView (active, requested or warming up) never submits XR depth.
+    bool triview_skips_xr_depth() const {
+        return is_quadview_mode_selected() || requested_rendering_method() == RenderingMethod::QUAD_VIEWS_STEREO ||
+            m_triview_autostart_stage == 1 || m_triview_autostart_stage == 2;
+    }
+
     bool is_depth_enabled() const {
-        return !is_using_mono() && m_enable_depth->value();
+        return !is_using_mono() && !is_quadview_mode_selected() && m_enable_depth->value();
     }
 
     bool is_openxr_afr_depth_target_stability_enabled() const {
         const auto runtime = get_runtime();
         return m_openxr_afr_depth_target_stability->value() &&
             m_enable_depth->value() &&
@@ -668,50 +857,53 @@ public:
 
     bool wants_blueprint_load() const {
         return m_load_blueprint_code->value();
     }
 
     bool is_splitscreen_compatibility_enabled() const {
-        if (is_using_mono()) { return false; }
+        if (is_using_mono() || is_quadview_mode_selected()) { return false; }
         if (uevr::nascar::is_target()) { return false; }
         return m_splitscreen_compatibility_mode->value();
     }
 
     uint32_t get_requested_splitscreen_index() const {
         return m_splitscreen_view_index->value();
     }
 
     bool is_sceneview_compatibility_enabled() const {
-        if (is_using_mono()) { return false; }
+        if (is_using_mono() || is_quadview_mode_selected()) { return false; }
         if (uevr::nascar::is_target()) { return false; }
         return m_sceneview_compatibility_mode->value();
     }
 
     bool is_native_stereo_fix_enabled() const {
-        if (is_mono_transition_quiescing()) { return false; }
+        if (is_quadview_mode_selected() || is_mono_transition_quiescing()) { return false; }
         if (uevr::nascar::is_target()) {
             return is_nascar_native_stereo_fix_requested() && m_fake_stereo_hook && m_fake_stereo_hook->is_nascar_native_ready();
         }
         if (should_ignore_native_stereo_fix_for_avowed_sync()) {
             return false;
         }
+        if (is_duoview_renderer_active()) { return true; }
 
         return m_native_stereo_fix->value() &&
             m_rendering_method->value() == RenderingMethod::NATIVE_STEREO &&
             !is_using_afr();
     }
 
     bool is_native_stereo_fix_same_pass_enabled() const {
+        if (is_duoview_renderer_active()) return m_duoview.settings().native_fix_same_pass;
         if (should_force_native_stereo_fix_same_pass()) {
             return true;
         }
 
         return m_native_stereo_fix_same_pass->value();
     }
 
     bool is_native_stereo_fix_preserve_secondary_pass_enabled() const {
+        if (is_duoview_renderer_active() && !m_duoview.settings().native_fix_same_pass) return true;
         return m_native_stereo_fix_preserve_secondary_pass->value();
     }
 
     bool is_native_stereo_fix_texture_array_submit_enabled() const {
         if (uevr::nascar::is_target()) { return false; }
         const auto runtime = get_runtime();
@@ -954,13 +1146,13 @@ public:
     bool request_native_openxr_async_wait();
     void ensure_native_openxr_async_wait_worker();
     void stop_native_openxr_async_wait_worker();
     void native_openxr_async_wait_worker_loop(std::stop_token stop_token);
 
     bool is_ghosting_fix_enabled() const {
-        if (is_using_mono() || is_mono_transition_quiescing()) { return false; }
+        if (is_using_mono() || is_quadview_mode_selected() || is_mono_transition_quiescing()) { return false; }
         if (uevr::nascar::is_target()) { return false; }
         return m_ghosting_fix->value();
     }
 
     bool is_nascar_native_stereo_fix_requested() const {
         return uevr::nascar::is_validated_build() && m_native_stereo_fix->value() &&
@@ -972,13 +1164,13 @@ public:
         return uevr::nascar::is_target() && m_ghosting_fix->value() &&
             is_nascar_code_preserving_mode() && is_using_strict_synchronized_afr() &&
             !is_stereo_emulation_enabled();
     }
 
     bool is_ghosting_fix_bootstrap_enabled() const {
-        return !is_using_mono() && !is_mono_transition_quiescing() && m_ghosting_fix_bootstrap_view_states->value();
+        return !is_using_mono() && !is_quadview_mode_selected() && !is_mono_transition_quiescing() && m_ghosting_fix_bootstrap_view_states->value();
     }
 
     auto& get_fake_stereo_hook() {
         return m_fake_stereo_hook;
     }
 
@@ -990,13 +1182,13 @@ public:
     auto get_pre_flattened_rotation() const {
         std::shared_lock _{m_decoupled_pitch_data.mtx};
         return m_decoupled_pitch_data.pre_flattened_rotation;
     }
 
     bool is_using_2d_screen() const {
-        return m_2d_screen_mode->value();
+        return !is_quadview_mode_selected() && m_2d_screen_mode->value();
     }
 
     bool is_mixtape_auto_2d_active() const {
         return m_mixtape_auto_2d_active.load(std::memory_order_relaxed);
     }
 
@@ -1059,13 +1251,13 @@ public:
     
     bool should_skip_uobjectarray_init() const {
         return m_compatibility_skip_uobjectarray_init->value();
     }
 
     bool is_extreme_compatibility_mode_enabled() const {
-        return m_extreme_compat_mode->value();
+        return !is_quadview_mode_selected() && m_extreme_compat_mode->value();
     }
 
     int32_t get_horizontal_projection_override() const {
         if (is_using_mono()) { return static_cast<int32_t>(HORIZONTAL_SYMMETRIC); }
         if (is_dibr_single_view_projection_configured()) {
             return static_cast<int32_t>(HORIZONTAL_SYMMETRIC);
@@ -1166,25 +1358,32 @@ private:
 
     std::optional<std::string> reinitialize_openxr() {
         spdlog::info("Reinitializing OpenXR");
         std::scoped_lock _{m_openvr_mtx};
 
         if (m_is_d3d12) {
-            m_d3d12.openxr().destroy_swapchains();
+            // The old void path could refuse GPU teardown but still destroy
+            // XrSession. Never advance after a veto or partial destruction.
+            if (!m_d3d12.openxr().destroy_swapchains()) {
+                spdlog::warn("[TriView][Restart] XR resource retirement refused; preserving old runtime");
+                return std::string{"OpenXR teardown unsafe/pending; old session retained"};
+            }
         } else {
             m_d3d11.openxr().destroy_swapchains();
         }
 
         m_openxr.reset();
         m_runtime.reset();
         m_runtime = std::make_shared<VRRuntime>();
         
         m_controllers.clear();
         m_controllers_set.clear();
 
         auto e = initialize_openxr();
+        if (!e && (!m_openxr || !m_openxr->loaded || !m_runtime || !m_runtime->loaded))
+            e = std::string{"New OpenXR runtime did not become loaded after restart"};
 
         if (e) {
             spdlog::error("Failed to reinitialize OpenXR: {}", *e);
         }
 
         return e;
@@ -1540,12 +1739,14 @@ private:
 
     enum DesktopMirrorMode : int32_t {
         DESKTOP_MIRROR_FULL = 0,
         DESKTOP_MIRROR_SCENE_ONLY = 1,
     };
 
+    static const inline std::vector<std::string> s_quadview_edge_mode_names{ "B31", "Edge V2 Instant", "Edge V2 Temporal", "Edge V3 Ambient Temporal", "B40 Continuous Ambient" };
+    static const inline std::vector<std::string> s_quadview_seam_mode_names{ "Off", "Manual", "Adaptive" };
     static const inline std::vector<std::string> s_desktop_mirror_mode_names{
         "Full",
         "Scene Only",
     };
 
     enum Subnautica2NativeWaterMode : int32_t {
@@ -1595,12 +1796,140 @@ private:
         "Learned Assist",
         "Calibrated Framing (Experimental)",
     };
 
     const std::unique_ptr<RenderingMethodSetting> m_rendering_method{
         std::make_unique<RenderingMethodSetting>(generate_name("RenderingMethod"), uevr::mono::choices)};
+    // Legacy-style persistent options; never sampled by the XR compositor.
+    std::atomic<uint32_t> m_duo_ui_rejected_mask{0};
+    const ModSlider::Ptr m_duo_width{ModSlider::create(generate_name("DuoViewCropWidth"), .10f, 1.f, .50f)};
+    const ModSlider::Ptr m_duo_height{ModSlider::create(generate_name("DuoViewCropHeight"), .10f, 1.f, .50f)};
+    const ModSlider::Ptr m_duo_periphery{ModSlider::create(generate_name("DuoViewPeripheralScale"), .05f, .50f, .20f)};
+    const ModSlider::Ptr m_duo_density{ModSlider::create(generate_name("DuoViewFovealDensity"), .25f, 4.0f, 1.f)};
+    const ModSlider::Ptr m_duo_feather{ModSlider::create(generate_name("DuoViewFeather"), 0.f, .45f, .08f)};
+    const ModToggle::Ptr m_duo_gaze{ModToggle::create(generate_name("DuoViewEyeTracking"), true)};
+    const ModToggle::Ptr m_duo_border{ModToggle::create(generate_name("DuoViewDebugBorder"), false)};
+    const ModInt32::Ptr m_duo_debug_source{ModSliderInt32::create(generate_name("DuoViewDebugSource"), 0, 2, 0)};
+    const ModInt32::Ptr m_duo_fovea_view{ModSliderInt32::create(generate_name("DuoViewFoveaSourceView"), 0, 1, 0)};
+    const ModToggle::Ptr m_duo_stabilize{ModToggle::create(generate_name("DuoViewCropStability"), true)};
+    const ModSlider::Ptr m_duo_guard{ModSlider::create(generate_name("DuoViewCropGuard"), 0.f, .05f, .05f)};
+    const ModToggle::Ptr m_duo_shading{ModToggle::create(generate_name("DuoViewIndependentShading"), false)};
+    const ModToggle::Ptr m_duo_native_fix{ModToggle::create(generate_name("DuoViewNativeFixSamePass"), true)};
+    const ModInt32::Ptr m_duo_quant{ModSliderInt32::create(generate_name("DuoViewQuantizationPixels"), 0, 16, 2)};
+    const ModInt32::Ptr m_duo_hold{ModSliderInt32::create(generate_name("DuoViewGazeHoldMs"), 50, 2000, 350)};
+    const ModInt32::Ptr m_duo_reacquire{ModSliderInt32::create(generate_name("DuoViewGazeReacquireSamples"), 1, 4, 2)};
+    const ModSlider::Ptr m_duo_offset_x{ModSlider::create(generate_name("DuoViewGazeOffsetX"), -.25f, .25f, 0.f)};
+    const ModSlider::Ptr m_duo_offset_y{ModSlider::create(generate_name("DuoViewGazeOffsetY"), -.25f, .25f, 0.f)};
+    // Nonlinear response: stillness lock / instantaneous full-speed saccade.
+    const ModSlider::Ptr m_duo_micro_gain{ModSlider::create(generate_name("DuoViewGazeMicroGain"), 0.f, 1.f, 0.f)};
+    const ModSlider::Ptr m_duo_breakout{ModSlider::create(generate_name("DuoViewGazeBreakout"), .005f, .25f, .035f)};
+    const ModSlider::Ptr m_duo_stillness{ModSlider::create(generate_name("DuoViewGazeStillness"), 0.f, .05f, .008f)};
+    const ModInt32::Ptr m_duo_relock{ModSliderInt32::create(generate_name("DuoViewGazeRelockSamples"), 1, 10, 3)};
+    const ModSlider::Ptr m_quadview_crop_width{ModSlider::create(generate_name("QuadViewFocusWidth"), .05f, 1.f, .60f)};
+    const ModSlider::Ptr m_quadview_crop_height{ModSlider::create(generate_name("QuadViewFocusHeight"), .05f, 1.f, .60f)};
+    const ModSlider::Ptr m_quadview_context_scale{ModSlider::create(generate_name("QuadViewContextScale"), .05f, .50f, .30f)};
+    const ModToggle::Ptr m_quadview_tri_view{ModToggle::create(generate_name("QuadViewTriView"), true)};
+    const ModSlider::Ptr m_quadview_foveal_density{ModSlider::create(generate_name("QuadViewFovealDensity"), .25f, 4.f, 1.f)};
+    const ModSlider::Ptr m_quadview_feather{ModSlider::create(generate_name("QuadViewFeather"), 0.f, .45f, .10f)};
+    const ModCombo::Ptr m_quadview_seam_mode{ModCombo::create(generate_name("QuadViewSeamMode"), s_quadview_seam_mode_names, 2)};
+    const ModSlider::Ptr m_quadview_seam_strength{ModSlider::create(generate_name("QuadViewSeamStrength"), 0.f, 1.f, .85f)};
+    const ModSlider::Ptr m_quadview_seam_max_gain{ModSlider::create(generate_name("QuadViewSeamMaxGain"), .01f, .5f, .20f)};
+    const ModSlider::Ptr m_quadview_seam_brightness_ev{ModSlider::create(generate_name("QuadViewSeamBrightnessEV"), -.5f, .5f, 0.f)};
+    const ModSlider::Ptr m_quadview_seam_color_strength{ModSlider::create(generate_name("QuadViewSeamColorStrength"), 0.f, 1.f, .5f)};
+    const ModSlider::Ptr m_quadview_seam_local_strength{ModSlider::create(generate_name("QuadViewSeamLocalStrength"), 0.f, 1.f, .5f)};
+    const ModSlider::Ptr m_quadview_seam_radius_px{ModSlider::create(generate_name("QuadViewSeamRadiusPixels"), 16.f, 512.f, 120.f)};
+    const ModSlider::Ptr m_quadview_seam_transition_px{ModSlider::create(generate_name("QuadViewSeamTransitionPixels"), 0.f, 64.f, 0.f)};
+    const ModCombo::Ptr m_quadview_edge_mode{ModCombo::create(generate_name("QuadViewEdgeV2Mode"), s_quadview_edge_mode_names, 4)};
+    const ModSlider::Ptr m_quadview_edge_strength{ModSlider::create(generate_name("QuadViewEdgeV2Strength"), 0.f, 1.f, 1.f)};
+    const ModSlider::Ptr m_quadview_edge_reach{ModSlider::create(generate_name("QuadViewEdgeV2Reach"), 16.f, 1024.f, 240.f)};
+    const ModSlider::Ptr m_quadview_edge_fast{ModSlider::create(generate_name("QuadViewEdgeV2Fast"), 1.f, 256.f, 32.f)};
+    const ModSlider::Ptr m_quadview_edge_rate{ModSlider::create(generate_name("QuadViewEdgeV2Rate"), .001f, 4.f, .15f)};
+    const ModSlider::Ptr m_quadview_edge_noise{ModSlider::create(generate_name("QuadViewEdgeV2Noise"), 0.f, .05f, .004f)};
+    const ModToggle::Ptr m_quadview_legacy_inward{ModToggle::create(generate_name("QuadViewLegacyInwardFeather"), false)};
+    const ModSlider::Ptr m_quadview_legacy_anchor{ModSlider::create(generate_name("QuadViewLegacyInwardAnchorPx"), 2.f, 64.f, 12.f)};
+    const ModSlider::Ptr m_quadview_ambient_radius{ModSlider::create(generate_name("QuadViewAmbientRadiusPx"), 8.f, 128.f, 48.f)};
+    const ModSlider::Ptr m_quadview_ambient_inside{ModSlider::create(generate_name("QuadViewAmbientInsidePx"), 8.f, 96.f, 32.f)};
+    static const inline std::vector<std::string> s_quadview_b40_presets{ "Fast (75 ms)", "Balanced (200 ms)", "High (350 ms)", "Maximum (600 ms)" };
+    const ModSlider::Ptr m_quadview_b41_hold_ms{ModSlider::create(generate_name("QuadViewB41HoldMs"), 100.f, 1000.f, 250.f)};
+    const ModSlider::Ptr m_quadview_b41_reach_scale{ModSlider::create(generate_name("QuadViewB41BlendDistance"), 1.f, 3.f, 1.f)};
+    const ModSlider::Ptr m_triview_b42_vram_limit{ModSlider::create(generate_name("QuadViewB42VramLimitPercent"), 60.f, 95.f, 85.f)};
+    const ModToggle::Ptr m_triview_b42_low_start{ModToggle::create(generate_name("QuadViewB42LowResStart"), true)};
+    const ModSlider::Ptr m_triview_b42_low_start_scale{ModSlider::create(generate_name("QuadViewB42LowResStartScale"), .1f, 1.f, .3f)};
+    std::array<uint32_t,2> m_triview_b42_guard_eye{};
+    std::optional<uevr::quadview::SourceExtents> m_triview_b42_inflight{}; // allowed build not yet published
+    uint64_t m_triview_b42_inflight_ms{}; // when it was allowed (expires with the gate latch)
+    const ModCombo::Ptr m_quadview_b40_stability{ModCombo::create(generate_name("QuadViewB40Stability"), s_quadview_b40_presets, 2)};
+    const ModSlider::Ptr m_quadview_ambient_time{ModSlider::create(generate_name("QuadViewAmbientTimeMs"), 50.f, 1500.f, 350.f)};
+    const ModToggle::Ptr m_quadview_seam_debug{ModToggle::create(generate_name("QuadViewSeamDebug"), false)};
+    const ModToggle::Ptr m_quadview_focus_lift_enabled{ModToggle::create(generate_name("QuadViewFocusLiftEnabled"), true)};
+    const ModSlider::Ptr m_quadview_focus_brightness{ModSlider::create(generate_name("QuadViewFocusBrightness"), .8f, 1.3f, 1.f)};
+    const ModSlider::Ptr m_quadview_focus_lift_strength{ModSlider::create(generate_name("QuadViewFocusLiftStrength"), 0.f, 2.f, 1.f)};
+    const ModSlider::Ptr m_quadview_focus_corner_gain{ModSlider::create(generate_name("QuadViewFocusCornerGain"), 1.f, 1.5f, uevr::quadview::focus_lift::default_corner_gain)};
+    const ModSlider::Ptr m_quadview_focus_lift_onset{ModSlider::create(generate_name("QuadViewFocusLiftOnset"), 0.f, .9f, uevr::quadview::focus_lift::default_onset)};
+    const ModSlider::Ptr m_quadview_focus_lift_power{ModSlider::create(generate_name("QuadViewFocusLiftPower"), .5f, 3.f, uevr::quadview::focus_lift::default_power)};
+    const ModSlider::Ptr m_quadview_sharpen{ModSlider::create(generate_name("QuadViewSharpen"), 0.f, 10.f, 1.f)};
+    const ModSlider::Ptr m_quadview_sharpen_max{ModSlider::create(generate_name("QuadViewSharpenMaxChange"), 0.05f, 0.40f, 0.10f)};
+    const ModToggle::Ptr m_quadview_sharpen_link{ModToggle::create(generate_name("QuadViewSharpenLinkEyes"), false)};
+    const ModSlider::Ptr m_quadview_sharpen_right{ModSlider::create(generate_name("QuadViewSharpenRight"), 0.f, 10.f, 10.f)};
+    const ModSlider::Ptr m_quadview_sharpen_right_max{ModSlider::create(generate_name("QuadViewSharpenRightMaxChange"), 0.05f, 0.40f, .40f)};
+    const ModToggle::Ptr m_quadview_compact_targets{ModToggle::create(generate_name("QuadViewCompactSources"), true)};
+    const ModToggle::Ptr m_quadview_depth_reproject{ModToggle::create(generate_name("TriViewPeripheryDepthB11"), true)};
+    const ModSlider::Ptr m_quadview_depth_strength{ModSlider::create(generate_name("QuadViewPeripheryDepthStrength"), -2.f, 2.f, 1.f)};
+    const ModToggle::Ptr m_quadview_depth_show{ModToggle::create(generate_name("QuadViewShowPeripheryDepth"), false)};
+    const ModToggle::Ptr m_quadview_gpu_timing{ModToggle::create(generate_name("QuadViewGpuTiming"), false)};
+    const ModToggle::Ptr m_quadview_eye_tracking{ModToggle::create(generate_name("QuadViewEyeTracking"), true)};
+    const ModToggle::Ptr m_quadview_debug_border{ModToggle::create(generate_name("QuadViewDebugBorder"), false)};
+    const ModInt32::Ptr m_quadview_debug_mode{ModSliderInt32::create(generate_name("QuadViewDebugMode"), 0, 3, 0)};
+    const ModToggle::Ptr m_quadview_stabilize_crop{ModToggle::create(generate_name("QuadViewCropStabilization"), true)};
+    const ModSlider::Ptr m_quadview_guard{ModSlider::create(generate_name("QuadViewGazeGuard"), 0.f, .05f, .05f)};
+    const ModInt32::Ptr m_quadview_gaze_quant{ModSliderInt32::create(generate_name("QuadViewGazeQuantization"), 0, 16, 2)};
+    const ModInt32::Ptr m_quadview_gaze_hold{ModSliderInt32::create(generate_name("QuadViewGazeHoldMs"), 50, 2000, 350)};
+    const ModInt32::Ptr m_quadview_gaze_reacquire{ModSliderInt32::create(generate_name("QuadViewGazeReacquireSamples"), 1, 4, 2)};
+    const ModSlider::Ptr m_quadview_gaze_offset_u{ModSlider::create(generate_name("QuadViewGazeOffsetU"), -.25f, .25f, 0.f)};
+    const ModSlider::Ptr m_quadview_gaze_offset_v{ModSlider::create(generate_name("QuadViewGazeOffsetV"), -.25f, .25f, 0.f)};
+    const ModSlider::Ptr m_quadview_gaze_micro_gain{ModSlider::create(generate_name("QuadViewGazeMicroGain"), 0.f, 1.f, .25f)};
+    const ModSlider::Ptr m_quadview_gaze_breakout{ModSlider::create(generate_name("QuadViewGazeBreakout"), .005f, .25f, .25f)};
+    const ModSlider::Ptr m_quadview_gaze_still{ModSlider::create(generate_name("QuadViewGazeStillRadius"), 0.f, .05f, .008f)};
+    const ModInt32::Ptr m_quadview_gaze_relock{ModSliderInt32::create(generate_name("QuadViewGazeRelockSamples"), 1, 10, 3)};
+    const ModToggle::Ptr m_duo_direct_xr{ModToggle::create(generate_name("DuoViewDirectXROutput"), false)};
+    const ModToggle::Ptr m_duo_timing{ModToggle::create(generate_name("DuoViewGpuTiming"), false)};
+    std::atomic<float> m_duo_gpu_ms{-1.f};
+    std::atomic<int32_t> m_duoview_output_path{-1};
+    std::atomic<uint64_t> m_duoview_source_extents{0};
+    uevr::duoview::State m_duoview;
+    std::atomic<uint64_t> m_duoview_draw_serial{};
+    std::atomic<std::shared_ptr<const uevr::duoview::FrameKey>> m_duoview_candidate_key{};
+    std::atomic<std::shared_ptr<const uevr::duoview::FrameKey>> m_duoview_frozen_key{};
+    uevr::duoview::psvr2::Reader m_duoview_gaze;
+    std::atomic<bool> m_duoview_quarantined{false};
+    std::once_flag m_duoview_settings_once;
+    uevr::quadview::Producer m_quadview;
+    struct QuadViewDrawConfig { uevr::quadview::Settings settings{}; uint64_t settings_revision{}; bool gaze_valid{},base_projection_valid{},native_target_set_ready{}; uint64_t native_target_set_generation{};
+        std::shared_ptr<const VRRenderTargetManager_Base::QuadViewNativeTargetSetSnapshot> native_target_set{}; uevr::quadview::GazeEvidence gaze{};
+        std::array<uevr::quadview::gaze::Projection,2> projections{}; };
+    std::atomic<uint64_t> m_quadview_draw_serial{};
+    std::atomic<uint64_t> m_triview_world_first_serial{};
+    uevr::triview::EpochGate m_triview_world_epoch_gate{};
+    uevr::quadview::DrawDemandLatch m_quadview_draw_demand{};
+    std::atomic<std::shared_ptr<const uevr::quadview::Key>> m_quadview_candidate_key{};
+    mutable std::mutex m_quadview_layout_mutex{};
+    uevr::quadview::LayoutLatch m_quadview_layout_latch{};
+    uevr::quadview::Key m_quadview_draw_config_key{};
+    std::optional<QuadViewDrawConfig> m_quadview_draw_config{};
+    uevr::quadview::Settings m_quadview_applied_settings{};
+    uint64_t m_quadview_settings_revision{1};
+    std::atomic<uint32_t> m_quadview_rejected_settings{};
+    std::atomic<bool> m_quadview_dimension_fallback{};
+    std::atomic<float> m_quadview_gpu_ms{-1.f};
+    uevr::quadview::psvr2::Reader m_quadview_gaze{};
+    std::array<uevr::duoview::CropStability,2> m_quadview_crop_stability{};
+    mutable std::mutex m_quadview_pose_mutex{};
+    uevr::quadview::Key m_quadview_pose_key{};
+    std::optional<runtimes::OpenXR::PipelineState> m_quadview_pose{};
+    uint8_t m_quadview_pose_eye_mask{};
+    std::atomic<const char*> m_quadview_status{"Waiting for four engine view histories"};
     std::atomic<const char*> m_mono_status{"Not selected"};
     std::atomic<uint64_t> m_mono_ready_generation{};
     std::atomic<uint64_t> m_mono_main_view_token{}, m_mono_attachment_token{};
     const ModCombo::Ptr m_synced_afr_method{ ModCombo::create(generate_name("SyncedSequentialMethod"), s_synced_afr_method_names, 1) };
     const ModToggle::Ptr m_extreme_compat_mode{ ModToggle::create(generate_name("ExtremeCompatibilityMode"), false, true) };
     const ModToggle::Ptr m_uncap_framerate{ ModToggle::create(generate_name("UncapFramerate"), true) };
@@ -1612,13 +1941,13 @@ private:
     const ModCombo::Ptr m_desktop_mirror_mode{ ModCombo::create(generate_name("DesktopSpectatorViewMode"), s_desktop_mirror_mode_names, DESKTOP_MIRROR_FULL) };
     const ModToggle::Ptr m_enable_gui{ ModToggle::create(generate_name("EnableGUI"), true) };
     const ModToggle::Ptr m_enable_depth{ ModToggle::create(generate_name("PassDepthToRuntime"), false, true) };
     const ModToggle::Ptr m_openxr_afr_depth_target_stability{ ModToggle::create(generate_name("OpenXRAFRDepthTargetStability"), false, true) };
     const ModToggle::Ptr m_enable_hitch_diagnostics{ ModToggle::create(generate_name("EnableHitchDiagnostics"), false, true) };
     const ModToggle::Ptr m_ktjl_openxr_factory_repair{ ModToggle::create(generate_name("KTJLOpenXRFactoryRepair"), false, true) };
-    const ModToggle::Ptr m_decoupled_pitch{ ModToggle::create(generate_name("DecoupledPitch"), false) };
+    const ModToggle::Ptr m_decoupled_pitch{ ModToggle::create(generate_name("DecoupledPitch"), true) };
     const ModToggle::Ptr m_decoupled_pitch_ui_adjust{ ModToggle::create(generate_name("DecoupledPitchUIAdjust"), true) };
     const ModToggle::Ptr m_load_blueprint_code{ ModToggle::create(generate_name("LoadBlueprintCode"), false, true) };
     const ModToggle::Ptr m_2d_screen_mode{ ModToggle::create(generate_name("2DScreenMode"), false) };
     const ModToggle::Ptr m_roomscale_movement{ ModToggle::create(generate_name("RoomscaleMovement"), false) };
     const ModToggle::Ptr m_roomscale_sweep{ ModToggle::create(generate_name("RoomscaleMovementSweep"), true) };
     const ModToggle::Ptr m_swap_controllers{ ModToggle::create(generate_name("SwapControllerInputs"), false) };
@@ -1681,15 +2010,15 @@ private:
     } m_dpad_gesture_state{};
 
     //const ModToggle::Ptr m_headlocked_aim{ ModToggle::create(generate_name("HeadLockedAim"), false) };
     //const ModToggle::Ptr m_headlocked_aim_controller_based{ ModToggle::create(generate_name("HeadLockedAimControllerBased"), false) };
     const ModSlider::Ptr m_motion_controls_inactivity_timer{ ModSlider::create(generate_name("MotionControlsInactivityTimer"), 30.0f, 100.0f, 30.0f) };
     const ModSlider::Ptr m_joystick_deadzone{ ModSlider::create(generate_name("JoystickDeadzone"), 0.01f, 0.9f, 0.2f) };
-    const ModSlider::Ptr m_camera_forward_offset{ ModSlider::create(generate_name("CameraForwardOffset"), -4000.0f, 4000.0f, 0.0f) };
+    const ModSlider::Ptr m_camera_forward_offset{ ModSlider::create(generate_name("CameraForwardOffset"), -4000.0f, 4000.0f, 15.0f) };
     const ModSlider::Ptr m_camera_right_offset{ ModSlider::create(generate_name("CameraRightOffset"), -4000.0f, 4000.0f, 0.0f) };
-    const ModSlider::Ptr m_camera_up_offset{ ModSlider::create(generate_name("CameraUpOffset"), -4000.0f, 4000.0f, 0.0f) };
+    const ModSlider::Ptr m_camera_up_offset{ ModSlider::create(generate_name("CameraUpOffset"), -4000.0f, 4000.0f, 10.0f) };
     const ModToggle::Ptr m_match_game_fov{ ModToggle::create(generate_name("MatchGameFOV"), false) };
     const ModToggle::Ptr m_match_game_fov_dolly{ ModToggle::create(generate_name("MatchGameFOVDolly"), false) };
     const ModSlider::Ptr m_match_game_fov_multiplier{ ModSlider::create(generate_name("MatchGameFOVMultiplier"), 0.1f, 3.0f, 1.0f) };
     const ModSlider::Ptr m_match_game_fov_dolly_distance{ ModSlider::create(generate_name("MatchGameFOVDollyDistance"), 10.0f, 50000.0f, 3000.0f) };
     const ModToggle::Ptr m_match_game_fov_min_enabled{ ModToggle::create(generate_name("MatchGameFOVMinEnabled"), false) };
     const ModSlider::Ptr m_match_game_fov_min{ ModSlider::create(generate_name("MatchGameFOVMin"), 5.0f, 120.0f, 40.0f) };
@@ -1894,18 +2223,59 @@ private:
     const ModToggle::Ptr m_match_game_fov_prospi_generic_telephoto_dolly_override{ ModToggle::create(generate_name("MatchGameFOVProSpiGenericTelephotoDollyOverride"), false) };
     const ModSlider::Ptr m_match_game_fov_prospi_generic_telephoto_dolly_distance{ ModSlider::create(generate_name("MatchGameFOVProSpiGenericTelephotoDollyDistance"), 10.0f, 50000.0f, 3000.0f) };
     const ModToggle::Ptr m_match_game_fov_prospi_camera_calibration_auto{ ModToggle::create(generate_name("MatchGameFOVProSpiCameraCalibrationAuto"), false) };
     const ModToggle::Ptr m_match_game_fov_prospi_field_map_flip_x{ ModToggle::create(generate_name("MatchGameFOVProSpiFieldMapFlipX"), false) };
     const ModToggle::Ptr m_match_game_fov_prospi_field_map_flip_y{ ModToggle::create(generate_name("MatchGameFOVProSpiFieldMapFlipY"), false) };
     const ModSlider::Ptr m_camera_fov_distance_multiplier{ ModSlider::create(generate_name("CameraFOVDistanceMultiplier"), 0.00f, 1000.0f, 0.0f) };
-    const ModSlider::Ptr m_world_scale{ ModSlider::create(generate_name("WorldScale"), 0.01f, 10.0f, 1.0f) };
+    const ModSlider::Ptr m_world_scale{ ModSlider::create(generate_name("WorldScale"), 0.01f, 10.0f, 0.85f) };
+    // Opt-in XYZ translation scaling; never affects the stock World Scale or IPD.
+    const ModToggle::Ptr m_xyz_headscale_enabled{ ModToggle::create(generate_name("XYZHeadScalingEnabled"), true) };
+    const ModSlider::Ptr m_xyz_headscale_x{ ModSlider::create(generate_name("XYZHeadScaleX"), 0.05f, 5.0f, 3.0f) };
+    const ModSlider::Ptr m_xyz_headscale_y{ ModSlider::create(generate_name("XYZHeadScaleY"), 0.05f, 5.0f, 1.0f) };
+    const ModSlider::Ptr m_xyz_headscale_z{ ModSlider::create(generate_name("XYZHeadScaleZ"), 0.05f, 5.0f, 1.5f) };
+    const ModKey::Ptr m_xyz_headscale_toggle_key{ ModKey::create(generate_name("XYZHeadScaleToggleKey")) };
+    const ModKey::Ptr m_xyz_headscale_hold_bypass_key{ ModKey::create(generate_name("XYZHeadScaleHoldBypassKey")) };
+    std::atomic<bool> m_xyz_headscale_hold_bypass{ false };
+    // User-initiated MPC_FOV repair only; deliberately never drives a runtime reset.
+    std::atomic<bool> m_duoview_manual_fov_requested{false};
+    std::atomic<int> m_duoview_manual_fov_status{0}; // idle/pending/verified/failure
+    // User-initiated hotkeys. Both independently configurable and unbound by default.
+    const ModKey::Ptr m_duoview_fov_reapply_key{
+        ModKey::create(generate_name("DuoViewFOVReapplyKey")) };
+    const ModKey::Ptr m_reinitialize_runtime_key{
+        ModKey::create(generate_name("ReinitializeRuntimeKey")) };
+    // Shared-key sequencing: runtime reset must finish before any MPC write.
+    // 0=no deferred request; otherwise earliest steady_clock timestamp (ms).
+    std::atomic<bool> m_duoview_hotkey_reapply_after_reset{false};
+    std::atomic<int64_t> m_duoview_hotkey_fov_not_before_ms{0};
     const ModSlider::Ptr m_depth_scale{ ModSlider::create(generate_name("DepthScale"), 0.01f, 1.0f, 1.0f) };
 
     const ModToggle::Ptr m_ghosting_fix{ ModToggle::create(generate_name("GhostingFix"), false) };
     const ModToggle::Ptr m_ghosting_fix_bootstrap_view_states{ ModToggle::create(generate_name("GhostingFixBootstrapViewStates"), false) };
     const ModToggle::Ptr m_native_stereo_fix{ ModToggle::create(generate_name("NativeStereoFix"), false) };
+    // Tri-view B12 autostart: 0 idle, 1 Native Fix warm-up, 2 ID7 requested, 3 done.
+    int m_triview_autostart_stage{0};
+    // 0=idle, 1=requested, 2=Native Stereo transition, 3=drain/restart,
+    // 4=XR re-created and Native Stereo warming, 5=TriView return requested.
+    std::atomic<int> m_triview_restart_phase{0};
+    uintptr_t m_triview_resize_world_identity{}; // B25 world reload invalidates B14 resize cache.
+    // Native Stereo Fix MUST publish a frame newer than the final old XR session.
+    std::atomic<uint64_t> m_triview_restart_previous_native_serial{0};
+    bool m_triview_restart_saved_native_fix{false};
+    std::chrono::steady_clock::time_point m_triview_restart_ready_since{};
+    std::chrono::steady_clock::time_point m_triview_restart_resume_since{};
+    // Tri-view B12 make-before-break resize (game thread only).
+    struct TriViewLiveSizes { float crop_width{}, crop_height{}, context_scale{}, foveal_density{}; bool valid{}; } m_triview_live_sizes{};
+    std::array<std::array<uint32_t,2>,4> m_triview_pending_extents{};
+    bool m_triview_pending_extents_valid{false};
+    // Tri-view B14 (game thread only): settled resize + one published-set read per draw.
+    uevr::quadview::ResizeGate m_triview_resize_gate{};
+    std::shared_ptr<const VRRenderTargetManager_Base::QuadViewNativeTargetSetSnapshot> m_triview_hold_set{};
+    bool m_triview_autostart_user_fix{false};
+    std::chrono::steady_clock::time_point m_triview_autostart_since{};
+    std::chrono::steady_clock::time_point m_triview_autostart_active_since{};
     const ModToggle::Ptr m_native_stereo_fix_same_pass{ ModToggle::create(generate_name("NativeStereoFixSamePass"), true) };
     const ModToggle::Ptr m_native_stereo_fix_preserve_secondary_pass{ ModToggle::create(generate_name("NativeStereoFixPreserveSecondaryPass"), true) };
     const ModToggle::Ptr m_native_stereo_fix_texture_array_submit{ ModToggle::create(generate_name("NativeStereoFixTextureArraySubmit"), false) };
     const ModToggle::Ptr m_native_stereo_fix_async_openxr_wait{ ModToggle::create(generate_name("NativeStereoFixAsyncOpenXRWait"), false) };
     const ModToggle::Ptr m_stalker2_native_pair_experiment{ ModToggle::create(generate_name("Stalker2NativePairExperiment"), false) };
     const ModToggle::Ptr m_stalker2_sharpen_priority{ ModToggle::create(generate_name("Stalker2SharpenExistingPriority"), false) };
@@ -1949,27 +2319,27 @@ private:
         std::chrono::steady_clock::time_point last_apply{};
         std::chrono::steady_clock::time_point last_log{};
         std::chrono::steady_clock::time_point burst_until{};
     } m_fullscreen_16x9_camera_compat{};
 
     // Keybinds
-    const ModKey::Ptr m_keybind_recenter{ ModKey::create(generate_name("RecenterViewKey")) };
+    const ModKey::Ptr m_keybind_recenter{ ModKey::create(generate_name("RecenterViewKey"), 226) };
     const ModKey::Ptr m_keybind_recenter_horizon{ ModKey::create(generate_name("RecenterHorizonKey")) };
-    const ModKey::Ptr m_keybind_set_standing_origin{ ModKey::create(generate_name("ResetStandingOriginKey")) };
+    const ModKey::Ptr m_keybind_set_standing_origin{ ModKey::create(generate_name("ResetStandingOriginKey"), 226) };
 
     const ModKey::Ptr m_keybind_load_camera_0{ ModKey::create(generate_name("LoadCamera0Key")) };
     const ModKey::Ptr m_keybind_load_camera_1{ ModKey::create(generate_name("LoadCamera1Key")) };
     const ModKey::Ptr m_keybind_load_camera_2{ ModKey::create(generate_name("LoadCamera2Key")) };
 
     const ModKey::Ptr m_keybind_toggle_2d_screen{ ModKey::create(generate_name("Toggle2DScreenKey")) };
     const ModKey::Ptr m_keybind_disable_vr{ ModKey::create(generate_name("DisableVRKey")) };
     bool m_disable_vr{false}; // definitely should not be persistent
 
     const ModKey::Ptr m_keybind_toggle_gui{ ModKey::create(generate_name("ToggleSlateGUIKey")) };
     
-    const ModString::Ptr m_requested_runtime_name{ ModString::create("Frontend_RequestedRuntime", "unset") };
+    const ModString::Ptr m_requested_runtime_name{ ModString::create("Frontend_RequestedRuntime", "openxr_loader.dll") };
 
     const ModToggle::Ptr m_lerp_camera_pitch{ ModToggle::create(generate_name("LerpCameraPitch"), false) };
     const ModToggle::Ptr m_lerp_camera_yaw{ ModToggle::create(generate_name("LerpCameraYaw"), false) };
     const ModToggle::Ptr m_lerp_camera_roll{ ModToggle::create(generate_name("LerpCameraRoll"), false) };
     const ModSlider::Ptr m_lerp_camera_speed{ ModSlider::create(generate_name("LerpCameraSpeed"), 0.01f, 10.0f, 1.0f) };
 
@@ -2145,12 +2515,39 @@ private:
     float get_game_fov_dolly_offset() const;
     auto get_desktop_mirror_mode() const { return static_cast<DesktopMirrorMode>(m_desktop_mirror_mode->value()); }
 
 public:
     VR() {
         m_options = {
+            *m_duo_width, *m_duo_height, *m_duo_periphery, *m_duo_density,
+            *m_duo_feather, *m_duo_gaze, *m_duo_border, *m_duo_debug_source,
+            *m_duo_fovea_view, *m_duo_timing, *m_duo_direct_xr, *m_duo_stabilize, *m_duo_guard,
+            *m_duo_native_fix, *m_duo_quant, *m_duo_hold, *m_duo_reacquire,
+            *m_duo_offset_x, *m_duo_offset_y,
+            *m_duo_micro_gain, *m_duo_breakout, *m_duo_stillness, *m_duo_relock,
+            *m_quadview_crop_width, *m_quadview_crop_height, *m_quadview_context_scale,
+            *m_quadview_tri_view, *m_quadview_foveal_density, *m_quadview_feather,
+            *m_quadview_edge_mode, *m_quadview_edge_strength, *m_quadview_edge_reach,
+            *m_quadview_edge_fast, *m_quadview_edge_rate, *m_quadview_edge_noise,
+            *m_quadview_legacy_inward, *m_quadview_legacy_anchor,
+            *m_quadview_ambient_radius, *m_quadview_ambient_inside, *m_quadview_ambient_time,
+            *m_quadview_b40_stability, *m_quadview_b41_hold_ms, *m_quadview_b41_reach_scale,
+            *m_triview_b42_vram_limit, *m_triview_b42_low_start, *m_triview_b42_low_start_scale,
+            *m_quadview_seam_mode, *m_quadview_seam_strength, *m_quadview_seam_max_gain,
+            *m_quadview_seam_brightness_ev, *m_quadview_seam_color_strength,
+            *m_quadview_seam_local_strength, *m_quadview_seam_radius_px,
+            *m_quadview_seam_transition_px, *m_quadview_seam_debug,
+            *m_quadview_focus_lift_enabled, *m_quadview_focus_brightness, *m_quadview_focus_lift_strength,
+            *m_quadview_focus_corner_gain, *m_quadview_focus_lift_onset, *m_quadview_focus_lift_power,
+            *m_quadview_sharpen, *m_quadview_sharpen_max, *m_quadview_sharpen_link,
+            *m_quadview_sharpen_right, *m_quadview_sharpen_right_max, *m_quadview_eye_tracking,
+            *m_quadview_compact_targets, *m_quadview_depth_reproject, *m_quadview_depth_strength,
+            *m_quadview_stabilize_crop, *m_quadview_guard, *m_quadview_gaze_quant,
+            *m_quadview_gaze_hold, *m_quadview_gaze_reacquire, *m_quadview_gaze_offset_u,
+            *m_quadview_gaze_offset_v, *m_quadview_gaze_micro_gain, *m_quadview_gaze_breakout,
+            *m_quadview_gaze_still, *m_quadview_gaze_relock,
             *m_rendering_method,
             *m_synced_afr_method,
             *m_extreme_compat_mode,
             *m_uncap_framerate,
             *m_disable_hdr_compositing,
             *m_disable_hzbocclusion,
@@ -2378,12 +2775,16 @@ public:
             *m_match_game_fov_prospi_generic_telephoto_dolly_override,
             *m_match_game_fov_prospi_generic_telephoto_dolly_distance,
             *m_match_game_fov_prospi_camera_calibration_auto,
             *m_match_game_fov_prospi_field_map_flip_x,
             *m_match_game_fov_prospi_field_map_flip_y,
             *m_world_scale,
+            *m_xyz_headscale_enabled,
+            *m_xyz_headscale_x, *m_xyz_headscale_y, *m_xyz_headscale_z,
+            *m_xyz_headscale_toggle_key, *m_xyz_headscale_hold_bypass_key,
+            *m_duoview_fov_reapply_key, *m_reinitialize_runtime_key,
             *m_depth_scale,
             *m_custom_z_near,
             *m_custom_z_near_enabled,
             *m_ghosting_fix,
             *m_ghosting_fix_bootstrap_view_states,
             *m_native_stereo_fix,
diff --git a/src/mods/vr/CompatibilityPolicy.hpp b/src/mods/vr/CompatibilityPolicy.hpp
index 2e03b544..a3eca31f 100644
--- a/src/mods/vr/CompatibilityPolicy.hpp
+++ b/src/mods/vr/CompatibilityPolicy.hpp
@@ -9,12 +9,14 @@ enum class RenderingMethod : int32_t {
     NativeStereo = 0,
     Synchronized = 1,
     Alternating = 2,
     SyntheticDibr = 3,
     SyntheticDibrSingleView = 4,
     Mono = 5,
+    DuoViewMono = 6,
+    QuadViewsStereo = 7,
 };
 
 constexpr bool should_preserve_mafia_pending_rhi_identity(
     bool exact_mafia_ue544, bool native_stereo, bool native_fix_enabled) noexcept {
     return exact_mafia_ue544 && native_stereo && native_fix_enabled;
 }
@@ -326,13 +328,14 @@ struct ModeMatrix {
     bool dibr_preview_active{};
     bool dibr_single_view_requested{};
     bool dibr_single_view_eligible{};
 };
 
 constexpr bool is_using_afr(RenderingMethod method, bool extreme_compatibility) noexcept {
-    if (method == RenderingMethod::Mono) { return false; }
+    if (method == RenderingMethod::Mono || method == RenderingMethod::DuoViewMono ||
+        method == RenderingMethod::QuadViewsStereo) { return false; }
     return method == RenderingMethod::Alternating ||
         method == RenderingMethod::Synchronized ||
         extreme_compatibility;
 }
 
 constexpr bool is_using_native_stereo(RenderingMethod method, bool using_afr) noexcept {
diff --git a/src/mods/vr/D3D12Component.cpp b/src/mods/vr/D3D12Component.cpp
index d1179738..068cb8d1 100644
--- a/src/mods/vr/D3D12Component.cpp
+++ b/src/mods/vr/D3D12Component.cpp
@@ -1,7 +1,8 @@
 #include <d3dcompiler.h>
+#include <dxgi1_4.h>
 
 #include <openvr.h>
 #include <utility/Module.hpp>
 #include <utility/Scan.hpp>
 #include <utility/String.hpp>
 #include <utility/ScopeGuard.hpp>
@@ -31,12 +32,14 @@
 #include "shaders/Compiled/alpha_luminance_sprite_ps_SpritePixelShader.inc"
 #include "shaders/Compiled/alpha_luminance_sprite_ps_SpriteVertexShader.inc"
 
 #include "d3d12/DirectXTK.hpp"
 
 #include "D3D12Component.hpp"
+#include "QuadViewNgxDepth.hpp"
+#include "TriViewAdmission.hpp"
 #include "GalacticRacerRenderTargets.hpp"
 #include "MonoD3D12.hpp"
 
 //#define AFR_DEPTH_TEMP_DISABLED
 
 constexpr auto ENGINE_SRC_DEPTH = D3D12_RESOURCE_STATE_DEPTH_READ | D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
@@ -1545,13 +1548,40 @@ bool D3D12Component::shf_scene_consumers_retired(bool include_stable_copy_produc
             if (texture != nullptr && !texture->commands.references_retired()) { return false; }
         }
     }
     return true;
 }
 
-bool D3D12Component::mono_consumers_retired() {
+bool D3D12Component::mono_consumers_retired(uevr::quadview::RetirementScope scope) {
+    const auto vr=VR::get();
+    // Engine target leases are independent of the presentation allocations
+    // rebuilt by setup(). Waiting for an active producer here starves setup.
+    // Mode changes still close admission and drain every engine owner.
+    if (uevr::quadview::requires_engine_retirement(scope) && vr && vr->is_quadview_mode_selected()) {
+        if (vr->is_mono_transition_pending() && !vr->quadview_transition_draw_closed()) {
+            vr->set_quadview_status("Waiting for the active viewport draw to latch a closed ID7 admission boundary");
+            return false;
+        }
+        const auto& stereo=vr->get_fake_stereo_hook();
+        if (!stereo || !stereo->quadview_delivery.engine_commands_retired(vr->mono_generation())) {
+            vr->set_quadview_status(stereo && stereo->quadview_delivery.engine_tracking_overflowed(vr->mono_generation())
+                ? "ID7 engine ownership tracking overflowed; transition remains blocked"
+                : "Waiting for tracked ID7 render-thread/RHI owners to execute before transition");
+            return false;
+        }
+    }
+    {
+        std::scoped_lock lock{m_openxr.mtx};
+        for (auto& [commands, compositor] : m_openxr.quadview_compositors) {
+            if (!commands || !commands->references_retired()) return false;
+            if (compositor) {
+                compositor->on_slot_retired();
+                if (vr) vr->note_quadview_gpu_ms(compositor->gpu_milliseconds());
+            }
+        }
+    }
     if (m_ue58_converted_ui_consumer_fence && m_ue58_converted_ui_consumer_fence_value != 0) {
         const auto completed = m_ue58_converted_ui_consumer_fence->GetCompletedValue();
         if (completed == UINT64_MAX || completed < m_ue58_converted_ui_consumer_fence_value) { return false; }
     }
     for (auto& slot : m_ue58_ui_source_slots) {
         if (!slot.texture.commands.references_retired()) { return false; }
@@ -2521,13 +2551,111 @@ void D3D12Component::sync_depth_target_stability_guard_state(VR* vr) {
     clear_depth_target_stability_candidates(true);
     SPDLOG_INFO(
         "[OPENXR_DEPTH_STABILITY] Guard {}; candidate history cleared",
         active ? "enabled" : "disabled");
 }
 
+// Tri-view B6: game-process video memory once per second while ID7 is selected.
+// Uses the game swap chain's own DXGI factory. The adapter reference is kept
+// as a raw pointer on purpose (no static ComPtr destructor at process exit).
+static void sample_triview_vram(VR* vr) {
+    if (vr == nullptr || !vr->is_quadview_mode_selected()) return;
+    static std::chrono::steady_clock::time_point next_sample{};
+    static IDXGIAdapter3* adapter = nullptr;
+    static LUID adapter_luid{};
+    const auto now = std::chrono::steady_clock::now();
+    if (now < next_sample) return;
+    next_sample = now + std::chrono::seconds(1);
+    auto& hook = g_framework->get_d3d12_hook();
+    if (hook == nullptr) return;
+    auto* device = hook->get_device();
+    auto* swap_chain = hook->get_swap_chain();
+    if (device == nullptr || swap_chain == nullptr) return;
+    const auto luid = device->GetAdapterLuid();
+    if (adapter == nullptr || luid.LowPart != adapter_luid.LowPart || luid.HighPart != adapter_luid.HighPart) {
+        if (adapter != nullptr) { adapter->Release(); adapter = nullptr; }
+        Microsoft::WRL::ComPtr<IDXGIFactory4> factory{};
+        Microsoft::WRL::ComPtr<IDXGIAdapter3> found{};
+        if (FAILED(swap_chain->GetParent(IID_PPV_ARGS(&factory))) || factory == nullptr ||
+            FAILED(factory->EnumAdapterByLuid(luid, IID_PPV_ARGS(&found))) || found == nullptr) {
+            SPDLOG_WARNING_EVERY_N_SEC(30, "[QuadViews][VRAM] DXGI adapter query unavailable");
+            return;
+        }
+        adapter = found.Detach();
+        adapter_luid = luid;
+    }
+    DXGI_QUERY_VIDEO_MEMORY_INFO local{}, system{};
+    if (FAILED(adapter->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_LOCAL, &local))) return;
+    if (FAILED(adapter->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_NON_LOCAL, &system))) system = {};
+    vr->note_triview_vram(local.CurrentUsage, local.Budget, system.CurrentUsage);
+    {   // B42: every 2 s, with the periphery depth snapshot pool.
+        const auto depth_usage = uevr::quadview::ngx::PeripheryDepth::self().pool_usage();
+        SPDLOG_INFO_EVERY_N_SEC(2, "[QuadViews][VRAM] game process: {} MB used / {} MB budget ({:.0f}%); in system memory {} MB; depth pool {} slots {} MB",
+            local.CurrentUsage >> 20, local.Budget >> 20, local.Budget ? 100.0 * double(local.CurrentUsage) / double(local.Budget) : 0.0,
+            system.CurrentUsage >> 20, depth_usage.first, depth_usage.second >> 20);
+    }
+}
+
 vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
+    sample_triview_vram(vr);
+    if (vr != nullptr) vr->service_triview_low_start(); // B42
+    {   // Tri-view B7: periphery depth capture only while ID7 + depth (reproject or show) is on.
+        auto& depth=uevr::quadview::ngx::PeripheryDepth::self();
+        const bool want=vr->is_quadview_mode_selected() && (vr->quadview_depth_reproject() || vr->quadview_depth_show());
+        depth.set_enabled(want);
+        if (want) if (const auto& hook=g_framework->get_d3d12_hook(); hook) depth.install(hook->get_command_queue());
+        // B18: GPU readback is manual-only. No automatic allocation/copy spike
+        // during normal play or a performance comparison.
+        {
+            static bool snapshot_dir_set=false;
+            if (!snapshot_dir_set) {
+                uevr::quadview::dx12::set_snapshot_directory(Framework::get_persistent_dir()/"triview_snapshots");
+                snapshot_dir_set=true;
+            }
+            static uint32_t snapshots_logged=0;
+            if (const auto n=uevr::quadview::dx12::snapshots_written().load(); n!=snapshots_logged) {
+                snapshots_logged=n;
+                spdlog::info("[TriView][Snapshot] {}",uevr::quadview::dx12::last_snapshot_message());
+            }
+        }
+        {   // Tri-view B11 startup proof: every 2 s while ID7 is selected, what it is waiting for.
+            static auto last_state_log=std::chrono::steady_clock::time_point{};
+            if (vr->is_quadview_mode_selected() && std::chrono::steady_clock::now()-last_state_log>std::chrono::seconds(2)) {
+                last_state_log=std::chrono::steady_clock::now();
+                const char* unavailable=vr->quadview_unavailable_reason();
+                const char* status=vr->quadview_status();
+                spdlog::info("[TriView][Startup] selected renderer_active={} unavailable='{}' status='{}' native_fix_reported={}",
+                    vr->is_quadview_renderer_active(), unavailable ? unavailable : "", status ? status : "", vr->is_native_stereo_fix_enabled());
+            }
+        }
+        static auto last_depth_log=std::chrono::steady_clock::time_point{};
+        if (want && std::chrono::steady_clock::now()-last_depth_log>std::chrono::seconds(1)) {
+            last_depth_log=std::chrono::steady_clock::now();
+            const auto s=depth.stats();
+            spdlog::info("[TriView][Depth] hooks={}/6 queue={} dlss={} periphery={} copied={} submitted={} used={} missing={} skipped={} want={}x{} out={}x{} in={}x{} fmt={} other={}x{} reason='{}' age_us={} slots={} jitter={}({:.3f},{:.3f}) foreign_queue={} warp='{}'",
+                s.hooks, s.queue_hook, s.evaluations, s.matches, s.captures, s.submits, s.used, s.missed, s.skips, s.want_w, s.want_h,
+                s.last_out_w, s.last_out_h, s.last_in_w, s.last_in_h, s.last_format, s.other_w, s.other_h,
+                uevr::quadview::ngx::PeripheryDepth::reason_name(s.reason), s.used_age_us, s.slots, s.jitter_valid, s.jitter_x, s.jitter_y, s.foreign_queue_submits, uevr::quadview::dx12::depth_state_name(uevr::quadview::dx12::last_depth_state().load()));
+        }
+    }
+    const char* qv_present_stage="entered";
+    if (vr->is_quadview_mode_selected()) {
+        uevr::quadview::HookTraceRecord r{};
+        r.event="PRESENT_ENTER";r.reason="d3d12_on_frame";
+        r.generation=vr->mono_generation();r.owner_generation=m_mono_generation;r.mode=7;
+        r.frame=static_cast<uint32_t>(vr->m_frame_count);
+        r.result=m_force_reset?1:0;uevr::quadview::emit_hook_trace(29,r);
+    }
+    utility::ScopeGuard qv_present_exit{[&]() {
+        if (!vr->is_quadview_mode_selected()) return;
+        uevr::quadview::HookTraceRecord r{};
+        r.event="PRESENT_RETURN";r.reason=qv_present_stage;
+        r.generation=vr->mono_generation();r.owner_generation=m_mono_generation;r.mode=7;
+        r.frame=static_cast<uint32_t>(vr->m_frame_count);
+        r.result=m_force_reset?1:0;uevr::quadview::emit_hook_trace(30,r);
+    }};
     const auto ui_alpha_allowed = [vr] {
         return uevr::ui_alpha::eligible(vr->get_runtime()->is_openxr(), vr->is_using_mono(),
             vr->is_dibr_rendering_method_selected(), vr->is_mono_transition_pending(), vr->is_using_2d_screen());
     };
     const auto ui_composition_request = ui_alpha_allowed() ? vr->get_overlay_component().get_ui_composition_request() : 0;
     m_openxr.ui_composition.begin_frame(ui_composition_request);
@@ -2586,56 +2714,62 @@ vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
     }
 
     if (!is_dead_island_2_ue425_current_game() || !vr->is_using_strict_synchronized_afr()) {
         m_dead_island_2_synced_eye_rebase_pending = false;
     }
 
+    qv_present_stage="generation_presentation_fences";
     if (m_mono_generation != vr->mono_generation()) {
         // Native <-> Mono retains the allocation shape, but never its queued
         // captures/parity. GPU retirement is polled, not an unbounded new wait.
-        if (!mono_consumers_retired()) {
+        if (!mono_consumers_retired(uevr::quadview::RetirementScope::presentation)) {
             vr->m_openxr->end_mono_transition_frame();
             return vr::VRCompositorError_None;
         }
         m_mono_generation = vr->mono_generation();
         m_last_rendered_frame = 0;
         m_submitted_left_eye = false;
         m_force_reset = true;
     }
 
+    qv_present_stage="reset_presentation_fences";
     if (m_force_reset || m_last_afr_state != vr->is_using_afr()) {
-        if (vr->mono_generation() != 0 && !mono_consumers_retired()) {
+        if (vr->mono_generation() != 0 && !mono_consumers_retired(uevr::quadview::RetirementScope::presentation)) {
             vr->m_openxr->end_mono_transition_frame();
             return vr::VRCompositorError_None;
         }
+        qv_present_stage="setup_failed";
         if (!setup()) {
             SPDLOG_ERROR_EVERY_N_SEC(1, "[D3D12 VR] Could not set up, trying again next frame");
             close_openxr_setup_failure_frame();
             m_force_reset = true;
             return vr::VRCompositorError_None;
         }
 
         m_last_afr_state = vr->is_using_afr();
     }
 
-    if (vr->mono_frame_gate_required()) {
+    qv_present_stage="mono_pose_gate";
+    if (vr->mono_frame_gate_required() && !vr->is_duoview_renderer_active()) {
         if (!vr->m_openxr->has_mono_frame(static_cast<uint32_t>(vr->m_frame_count))) {
             vr->set_mono_status("Waiting for a current main-view pose and validated common projection");
             vr->m_openxr->end_mono_transition_frame();
             return vr::VRCompositorError_None;
         }
         vr->note_mono_frame_ready(m_mono_generation);
     }
+    qv_present_stage="presentation_initialized";
     m_mono_block_post_present = false;
 
     auto& hook = g_framework->get_d3d12_hook();
     if (hook != nullptr) {
         m_dibr_depth_capture.set_ue5_rdg_depth_capture_enabled(vr->is_dibr_ue5_rdg_depth_capture_enabled());
         hook->set_depth_stencil_observer(vr->is_dibr_depth_trace_requested() ? &m_dibr_depth_capture : nullptr);
     }
 
+    qv_present_stage="scene_resources";
     hook->set_next_present_interval(0); // disable vsync for vr
     
     // get device
     auto device = hook->get_device();
 
     // get command queue
@@ -2999,12 +3133,14 @@ vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
         return ui_target ? static_cast<ID3D12Resource*>(ui_target->get_native_resource()) : nullptr;
     };
 
     // Mono copies this Present's producer, not the preceding Present counter
     // used by the historical Native Fix/AFR capture contracts.
     const auto frame_count = vr->is_using_mono() ? vr->m_frame_count : vr->m_render_frame_count;
+    const bool duo_native_active = vr->is_duoview_renderer_active();
+    const auto native_packet_frame_count = duo_native_active ? vr->m_render_frame_count : frame_count;
     namespace frame_diag = uevr::native_frame;
     frame_diag::Ticket native_frame_ticket{};
     namespace stalker = uevr::stalker2_native;
     const bool stalker_requested = vr->is_stalker2_native_fix_experiment_enabled();
     ffsr->sync_stalker2_native_experiment(stalker_requested);
     if (stalker_requested || m_stalker2_pair_was_enabled) {
@@ -3037,22 +3173,22 @@ vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
             stalker_exact = has_rhi_frame &&
                 stalker::pair_sources(device, m_game_tex.texture.Get(), right.Get(), stalker_output_desc,
                     m_backbuffer_size[0] / 2, m_backbuffer_size[1]);
         }
     }
     if (!stalker_exact && stalker_requested) { m_stalker2_pair_cache.invalidate(); m_stalker2_established_epoch = 0; }
-    auto native_stereo_packet = ffsr != nullptr && !vr->is_using_mono()
-        ? stalker_exact ? ffsr->get_stalker2_native_packet(stalker_frame, &native_frame_ticket)
-            : ffsr->get_native_stereo_frame_packet_for_submit(frame_count, frame_diag::Backend::d3d12, &native_frame_ticket)
+    auto native_stereo_packet = ffsr != nullptr && (!vr->is_using_mono() || duo_native_active)
+        ? stalker_exact && !duo_native_active ? ffsr->get_stalker2_native_packet(stalker_frame, &native_frame_ticket)
+            : ffsr->get_native_stereo_frame_packet_for_submit(native_packet_frame_count, frame_diag::Backend::d3d12, &native_frame_ticket)
         : nullptr;
     if (stalker_exact && !native_stereo_packet && m_stalker2_established_epoch != ffsr->stalker2_native_epoch()) {
         // Do not activate a new acceptance policy until one exact transaction
         // has actually submitted. Unsupported/unproven cadence stays unchanged.
         stalker_exact = false;
         native_stereo_packet = ffsr->get_native_stereo_frame_packet_for_submit(
-            frame_count, frame_diag::Backend::d3d12, &native_frame_ticket);
+            native_packet_frame_count, frame_diag::Backend::d3d12, &native_frame_ticket);
     }
     auto* const native_stereo_hook = ffsr.get();
     const auto record_native_submit = [&](frame_diag::Runtime api, frame_diag::Stage stage,
         int32_t result = 0, uint8_t eye = 2, uint8_t call = 0) {
         if (native_frame_ticket && native_stereo_packet != nullptr && native_stereo_hook != nullptr) {
             native_stereo_hook->record_native_frame_stage(*native_stereo_packet, native_frame_ticket,
@@ -3666,13 +3802,14 @@ vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
                 scene_capture_desc.MipLevels,
                 scene_capture_desc.DepthOrArraySize,
                 scene_capture_desc.SampleDesc.Count);
         }
     }
 
-    if (native_stereo_packet != nullptr && !scene_capture_packet_ready && native_stereo_hook != nullptr) {
+    if (!vr->is_duoview_renderer_active() && native_stereo_packet != nullptr &&
+        !scene_capture_packet_ready && native_stereo_hook != nullptr) {
         if (stalker_exact) {
             native_stereo_hook->reject_stalker2_native_packet(native_stereo_packet,
                 "Stalker exact transaction rejected by D3D12 descriptors");
             m_stalker2_pair_cache.invalidate();
         } else {
             native_stereo_hook->reject_native_stereo_frame_packet(
@@ -5249,13 +5386,270 @@ vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
                 } else {
                     const auto native_stereo_array_swapchain = (uint32_t)runtimes::OpenXR::SwapchainIndex::NATIVE_STEREO_ARRAY;
                     const auto use_native_array_submit =
                         vr->is_native_stereo_fix_texture_array_submit_enabled() &&
                         vr->m_openxr->swapchains.contains(native_stereo_array_swapchain);
 
-                    if (vr->is_using_mono()) {
+                    qv_present_stage="quadview_source_selection";
+                    if (vr->is_quadview_mode_selected()) {
+                        auto quad_epoch_lease=vr->triview_epoch_read();
+                        const auto& stereo=vr->get_fake_stereo_hook();
+                        const auto source=quad_epoch_lease && stereo && vr->is_quadview_renderer_active()
+                            ? stereo->quadview_delivery.select(vr->mono_generation(),GetCurrentThreadId())
+                            : std::optional<FFakeStereoRenderingHook::QuadViewDelivery::Source>{};
+                        {
+                            uevr::quadview::HookTraceRecord trace{};
+                            trace.event="SOURCE_SELECT";
+                            trace.reason=source ? "selected" : "no_executed_source";
+                            trace.generation=source ? source->generation : vr->mono_generation();
+                            trace.serial=source ? source->serial : 0;
+                            trace.owner_generation=source ? source->generation : 0;
+                            trace.owner_serial=trace.serial;
+                            trace.frame=frame_count;
+                            trace.canonical_frame=source ? source->engine_frame : 0;
+                            trace.mode=7;
+                            trace.source=static_cast<bool>(source);
+                            trace.result=source ? 1 : 0;
+                            if (source) { trace.target=source->target; trace.scene=source->scene; }
+                            uevr::quadview::emit_hook_trace(25,trace);
+                        }
+                        if (source && vr->triview_source_epoch_accepts(source->serial) &&
+                            source->packet && source->packet->producer && source->packet->atlas) {
+                          [&]() {
+                            const auto packet=source->packet;
+                            const auto frozen=packet->producer;
+                            if (!uevr::quadview::native_triview_publishable(frozen->layout.shared_context,
+                                    frozen->layout.native_local,packet->native_target_set_generation)) {
+                                vr->set_quadview_status("Waiting for three authenticated native TriView sources");
+                                return;
+                            }
+                            UINT64 timestamp_frequency{};
+                            if (frozen->settings.gpu_timing) {
+                                if (const auto& hook=g_framework->get_d3d12_hook(); hook) {
+                                    if (const auto queue=hook->get_command_queue(); queue)
+                                        queue->GetTimestampFrequency(&timestamp_frequency);
+                                }
+                            }
+                            std::array<ID3D12Resource*,4> native_sources{};
+                            const bool isolated=packet->native_target_set_generation!=0;
+                            bool sources_valid=true;
+                            for (size_t i=0; i!=4; ++i) {
+                                // Slot 1 is a shader descriptor alias only. It is NOT a fourth UE target.
+                                native_sources[i]=isolated
+                                    ? (frozen->layout.shared_context && i==1
+                                        ? packet->native_sources[0].Get() : packet->native_sources[i].Get())
+                                    : packet->atlas.Get();
+                                if (!native_sources[i]) sources_valid=false;
+                                if (isolated && i!=1) for (size_t j=0; j<i; ++j)
+                                    if (j!=1 && native_sources[i]==native_sources[j]) sources_valid=false;
+                            }
+                            if (!sources_valid) {
+                                vr->set_quadview_status("Rejected an incomplete or aliased Native Stereo Fix quartet");
+                                return;
+                            }
+                            m_openxr.prepare_quadview_compositors(device,uevr::quadview::dx12::Compositor::sampling_format(
+                                native_sources[0]->GetDesc().Format),timestamp_frequency);
+                            bool recorded=false;
+                            ID3D12Resource* output=nullptr;
+                            uintptr_t command_list=0;
+                            uevr::quadview::dx12::DepthInput depth_input{};
+                            depth_input.show=vr->quadview_depth_show();
+                            if (frozen->layout.shared_context && (vr->quadview_depth_reproject() || vr->quadview_depth_show())) {
+                                if (const auto snapshot=uevr::quadview::ngx::PeripheryDepth::self().latest_recent_submitted()) {
+                                    depth_input.texture=snapshot->texture.Get();
+                                    depth_input.srv_format=snapshot->srv_format;
+                                    depth_input.jitter_uv[0]=snapshot->jitter_uv[0];
+                                    depth_input.jitter_uv[1]=snapshot->jitter_uv[1];
+                                    depth_input.jitter_valid=snapshot->jitter_valid;
+                                    for (size_t i=0; i!=4; ++i) { depth_input.rect[i]=snapshot->rect[i]; depth_input.shift[i]=frozen->layout.depth_shift[i]; }
+                                    depth_input.reproject=vr->quadview_depth_reproject();
+                                    depth_input.show=vr->quadview_depth_show();
+                                    depth_input.keepalive=snapshot;
+                                }
+                            }
+                            const bool accepted=m_openxr.copy(
+                                (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE,nullptr,
+                                [this,packet,frozen,native_sources,timestamp_frequency,depth_input,&recorded,&output,&command_list](d3d12::CommandContext& commands,ID3D12Resource* destination) {
+                                    if (!commands.ready() || frozen->key.generation!=VR::get()->mono_generation()) return;
+                                    if (!commands.references_retired()) {
+                                        VR::get()->set_quadview_status("Waiting for the selected GPU command slot to retire before reuse");
+                                        return;
+                                    }
+                                    const auto found=m_openxr.quadview_compositors.find(&commands);
+                                    if (found==m_openxr.quadview_compositors.end() || !found->second) return;
+                                    auto& comp=*found->second;
+                                    // Temporal history is updated only on its retained queue.
+                                    // Other seam modes preserve the original dynamic queue path.
+                                    const auto seam_queue=(frozen->settings.seam_mode>=4 && frozen->settings.seam_mode<=6) ? comp.edge_submission_queue() : nullptr;
+                                    comp.on_slot_retired();
+                                    VR::get()->note_quadview_gpu_ms(comp.gpu_milliseconds());
+                                    recorded=comp.record_sources(commands.cmd_list.Get(),native_sources,destination,
+                                        frozen->layout,frozen->settings,
+                                        packet->source_state,D3D12_RESOURCE_STATE_RENDER_TARGET,
+                                        std::static_pointer_cast<const void>(packet),
+                                        frozen->settings.gpu_timing ? timestamp_frequency : 0,
+                                        (depth_input.texture || depth_input.show) ? &depth_input : nullptr, frozen->key.generation);
+                                    if (comp.commands_recorded()) {
+                                        commands.has_commands=true;
+                                        if (seam_queue) commands.seam_submission_queue=seam_queue;
+                                    }
+                                    if (recorded) { output=destination; command_list=reinterpret_cast<uintptr_t>(commands.cmd_list.Get()); }
+                                    else SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadView][Composite] {}",comp.error());
+                                },std::nullopt,packet->source_state,nullptr,std::nullopt,packet->atlas.Get());
+                            if (accepted && recorded && output &&
+                                stereo->quadview_delivery.submitted(*source,reinterpret_cast<uintptr_t>(output))) {
+                                {
+                                    uevr::quadview::HookTraceRecord trace{};
+                                    trace.event="COPY_ENQUEUED";
+                                    trace.reason="composite_recorded_and_swapchain_released";
+                                    trace.generation=source->generation;
+                                    trace.serial=source->serial;
+                                    trace.owner_generation=source->generation;
+                                    trace.owner_serial=source->serial;
+                                    trace.frame=frame_count;
+                                    trace.canonical_frame=source->engine_frame;
+                                    trace.mode=7;
+                                    trace.source=true;
+                                    trace.result=1;
+                                    trace.target=reinterpret_cast<uintptr_t>(output);
+                                    trace.list=command_list;
+                                    uevr::quadview::emit_hook_trace(26,trace);
+                                }
+                                auto pose=packet->pose;
+                                pose.quadview_serial=source->serial;
+                                vr->m_openxr->note_quadview_copy(std::move(pose),source->generation);
+                                // Shared mode-transition readiness also gates post-present GPU memory retirement.
+                                vr->note_mono_frame_ready(source->generation);
+                                SPDLOG_INFO_EVERY_N_SEC(2,"[QuadView][CopyEnqueued] serial={} histories={} source={:x} output={:x}",
+                                    source->serial,static_cast<unsigned>(frozen->constructor_mask),
+                                    reinterpret_cast<uintptr_t>(packet->atlas.Get()),reinterpret_cast<uintptr_t>(output));
+                                vr->quadview_producer().note_compositor_record(frozen->key,
+                                    reinterpret_cast<uintptr_t>(packet->atlas.Get()),command_list);
+                                // Packet and snapshot stay owned by the fence-bound compositor.
+                                vr->quadview_producer().retire(frozen->key);
+                                stereo->quadview_delivery.retire(source->generation,source->serial);
+                            } else {
+                                vr->set_quadview_status("Waiting for a reusable QuadView output slot");
+                                SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadView][CopyRejected] serial={} accepted={} recorded={} output={:x} generation={}/{}",
+                                    source->serial,accepted,recorded,reinterpret_cast<uintptr_t>(output),
+                                    source->generation,vr->mono_generation());
+                            }
+                          }();
+                        } else {
+                            vr->set_quadview_status("Waiting for four distinct main-family views and executed source");
+                            SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadView][OutputWaiting] no executed source generation={} thread={}",
+                                vr->mono_generation(),GetCurrentThreadId());
+                        }
+                    } else if (vr->is_duoview_renderer_active()) {
+                        const auto packet = native_stereo_packet;
+                        const auto packet_source = packet && packet->duoview_mono_source_valid
+                            ? std::optional<uint32_t>{packet->duoview_mono_source_frame}
+                            : std::optional<uint32_t>{};
+                        const auto packet_frame = packet ? packet->duoview_frame : nullptr;
+                        const auto packet_binding = packet_frame
+                            ? uevr::duoview::native_frame_binding(*packet_frame)
+                            : std::optional<uevr::duoview::NativeFrameBinding>{};
+                        const bool packet_pair_valid = packet && packet_frame && packet_source &&
+                            packet_frame->mono_source_frame &&
+                            *packet_frame->mono_source_frame == *packet_source && packet_binding &&
+                            packet_binding->key == packet_frame->config.key &&
+                            packet_frame->config.key.generation == vr->mono_generation() &&
+                            packet_binding->mono_source_frame == *packet_source &&
+                            scene_capture_packet_ready && m_game_tex.texture.Get() != nullptr &&
+                            m_scene_capture_tex.texture.Get() != nullptr &&
+                            packet->duoview_pose_valid && packet->duoview_primary_resource.Get()!=nullptr &&
+                            packet->duoview_primary_resource.Get()==m_game_tex.texture.Get();
+                        if (!packet_pair_valid) {
+                            SPDLOG_WARNING_EVERY_N_SEC(2,
+                                "[DuoView][Pair] Waiting serial={} pose_valid={} binding={} capture_ready={} source={}",
+                                packet ? packet->serial : 0,packet && packet->duoview_pose_valid,
+                                packet_binding.has_value(),scene_capture_packet_ready,packet_source.value_or(0));
+                            vr->set_mono_status("Waiting for a complete Native Stereo Fix DuoView source pair");
+                        } else {
+                            bool recorded = false;
+                            bool callback_attempted = false;
+                            bool compositor_fault = false;
+                            bool output_direct = false;
+                            uint64_t source_extents = 0;
+                            ID3D12Resource* recorded_secondary=nullptr;
+                            ID3D12Resource* recorded_target=nullptr;
+                            const bool submitted = m_openxr.copy(
+                                (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, nullptr,
+                                [this, packet, packet_frame, source=m_game_tex.texture,
+                                 secondary=m_scene_capture_tex.texture, device,
+                                 &recorded, &callback_attempted, &compositor_fault,
+                                 &output_direct, &source_extents, &recorded_secondary, &recorded_target](
+                                    d3d12::CommandContext& commands, ID3D12Resource* destination) {
+                                    if (!commands.ready()) return;
+                                    callback_attempted = true;
+                                    const auto vr = VR::get();
+                                    if (packet_frame->config.key.generation != vr->mono_generation() ||
+                                        packet_frame->mono_source_frame !=
+                                            std::optional<uint32_t>{packet->duoview_mono_source_frame} ||
+                                        !uevr::duoview::native_frame_binding(*packet_frame)) {
+                                        compositor_fault = true;
+                                        return;
+                                    }
+                                    const auto found = m_openxr.duoview_compositors.find(&commands);
+                                    if (found == m_openxr.duoview_compositors.end() || !found->second) {
+                                        SPDLOG_WARNING_EVERY_N_SEC(2,
+                                            "[DuoView][Activation] Missing prewarmed compositor for XR command slot");
+                                        compositor_fault = true;
+                                        return;
+                                    }
+                                    auto& compositor = *found->second;
+                                    recorded = compositor.record_native(device, commands.cmd_list.Get(),
+                                        source.Get(), secondary.Get(), destination,
+                                        D3D12_RESOURCE_STATE_RENDER_TARGET,
+                                        D3D12_RESOURCE_STATE_RENDER_TARGET, *packet_frame,
+                                        std::static_pointer_cast<const void>(packet),
+                                        packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0);
+                                    if (recorded) {
+                                        recorded_secondary=secondary.Get(); recorded_target=destination;
+                                        output_direct=compositor.last_native_direct_xr();
+                                        source_extents=compositor.last_native_source_extents();
+                                    }
+                                    if (compositor.recorded_commands()) commands.has_commands = true;
+                                    if (packet_frame->config.settings.gpu_timing)
+                                        vr->note_duoview_gpu_ms(compositor.gpu_milliseconds());
+                                    if (!recorded) {
+                                        SPDLOG_WARNING_EVERY_N_SEC(2,
+                                            "[DuoView][Activation] Native compositing rejected: {}", compositor.error());
+                                        compositor_fault = true;
+                                    }
+                                }, std::nullopt, D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr,
+                                std::nullopt, m_game_tex.texture.Get());
+                            if (submitted && recorded && callback_attempted) {
+                                native_stereo_hook->duoview_delivery.result(uevr::duoview::DeliveryEvent::copy,
+                                    packet->serial, true, GetCurrentThreadId());
+                                runtimes::OpenXR::PipelineState pose{};
+                                pose.duoview_serial=packet->serial;
+                                pose.frame_count=*packet_source;
+                                pose.stage_views.assign(packet->duoview_views.begin(),packet->duoview_views.end());
+                                pose.frame_state=packet->duoview_frame_state;
+                                pose.view_space_location=packet->duoview_view_location;
+                                vr->m_openxr->note_duoview_copy(std::move(pose),packet_frame->config.key.generation);
+                            }
+                            if (submitted && recorded && callback_attempted) {
+                                if (native_frame_ticket) {
+                                    native_stereo_hook->record_native_frame_stage(*native_stereo_packet, native_frame_ticket,
+                                        frame_diag::Backend::d3d12, frame_diag::Runtime::openxr, frame_diag::Stage::copy_recorded,
+                                        0, 2, 0, recorded_secondary, recorded_target);
+                                }
+                                native_stereo_hook->note_native_stereo_frame_packet_consumed(packet->serial);
+                                vr->note_duoview_output_path(output_direct);
+                                vr->note_duoview_source_extents(source_extents);
+                                vr->note_mono_frame_ready(m_mono_generation);
+                            }
+                            if (compositor_fault) {
+                                vr->duoview_abort("Validated Native Stereo Fix pair failed DuoView composition");
+                            } else if (!submitted || !recorded || !callback_attempted) {
+                                vr->set_mono_status("Waiting for a retired OpenXR command slot for DuoView composition");
+                            }
+                        }
+                    } else if (vr->is_using_mono()) {
                         bool recorded = false;
                         vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), false);
                         const bool submitted = m_openxr.copy(
                             (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, nullptr,
                             [source = backbuffer, scene_source_state, device, &recorded](
                                 d3d12::CommandContext& commands, ID3D12Resource* destination) {
@@ -6386,14 +6780,23 @@ void D3D12Component::clear_backbuffer() {
     const float clear_color[] = { 0.0f, 0.0f, 0.0f, 0.0f };
     backbuffer_ctx.commands.clear_rtv(backbuffer_ctx.texture.Get(), backbuffer_ctx.get_rtv(), clear_color, D3D12_RESOURCE_STATE_PRESENT);
     backbuffer_ctx.commands.execute();
 }
 
 void D3D12Component::on_post_present(VR* vr) {
+    if (vr != nullptr && g_framework != nullptr) {
+        const auto& d3d12_hook=g_framework->get_d3d12_hook();
+        const auto& stereo=vr->get_fake_stereo_hook();
+        if (d3d12_hook && stereo) {
+            if (auto* manager=stereo->get_render_target_manager())
+                manager->service_quadview_native_target_retirements_after_present(d3d12_hook->get_command_queue());
+        }
+    }
     if (vr->is_mono_transition_quiescing()) { return; }
-    if (vr->is_mono_transition_waiting() || m_mono_block_post_present) {
+    // Quad owns separate source proof; retire UI allocations even while its first scene is pending.
+    if ((vr->is_mono_transition_waiting() && !vr->is_quadview_mode_selected()) || m_mono_block_post_present) {
         // A rejected scene must not suppress backbuffer clearing indefinitely.
         // Never add queue work while retiring/replacing Mono resources.
         if (vr->is_hmd_active() && uevr::mono::clear_waiting_backbuffer(vr->is_using_mono(),
             vr->is_mono_transition_quiescing(), !m_force_reset, m_mono_generation, vr->mono_generation())) {
             clear_backbuffer();
         }
@@ -6437,12 +6840,14 @@ void D3D12Component::on_reset(VR* vr, bool mono_retired) {
 
     auto runtime = vr->get_runtime();
 
     // OpenXR copy contexts can still reference the borrowed Native Fix source.
     // Drain them before releasing any source or descriptor wrappers below.
     if (runtime->is_openxr() && runtime->loaded) {
+        vr->get_openxr_runtime()->invalidate_duoview_scene();
+        vr->get_openxr_runtime()->invalidate_quadview_scene();
         m_openxr.wait_for_all_copies();
     }
     if (m_stalker2_pair_was_enabled) {
         m_stalker2_pair_cache.invalidate();
         if (vr->m_fake_stereo_hook) { vr->m_fake_stereo_hook->sync_stalker2_native_experiment(false); }
         vr->get_openxr_runtime()->set_stalker2_pair_submit(std::nullopt);
@@ -6620,13 +7025,14 @@ void D3D12Component::on_reset(VR* vr, bool mono_retired) {
 }
 
 bool D3D12Component::setup() {
     SPDLOG_INFO_EVERY_N_SEC(1, "[VR] Setting up d3d12 textures...");
 
     auto vr = VR::get();
-    if (vr->mono_generation() != 0 && !mono_consumers_retired()) { return false; }
+    if (vr->mono_generation() != 0 &&
+        !mono_consumers_retired(uevr::quadview::RetirementScope::presentation)) { return false; }
     on_reset(vr.get(), true);
     
     m_prev_backbuffer.Reset();
 
     auto& hook = g_framework->get_d3d12_hook();
 
@@ -6837,18 +7243,74 @@ bool D3D12Component::setup() {
             alpha_luminance_sprite_ps_SpritePixelShader, 
             alpha_luminance_sprite_ps_SpriteVertexShader, 
             invert_alpha_in_place_pd
         );
     }
 
+    // DuoView may be activated long after OpenXR swapchains were created.
+    // Build GPU objects for the EXISTING XR command slots on the mode transition.
+    if (vr->is_duoview_renderer_active() && vr->get_runtime()->is_openxr()) {
+        auto it = m_openxr.contexts.find(
+            (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE);
+        if (it == m_openxr.contexts.end() || it->second.texture_contexts.empty()) {
+            spdlog::warn("[DuoView][Activation] Double-wide OpenXR command contexts not ready");
+        } else {
+            UINT64 frequency{};
+            if (auto queue = g_framework->get_d3d12_hook()->get_command_queue(); queue)
+                queue->GetTimestampFrequency(&frequency);
+            const bool srgb = false; // Existing Joey BGRA8 UNORM render source.
+            uint32_t prepared = 0;
+            for (auto& tc : it->second.texture_contexts) {
+                if (!tc) continue;
+                auto& comp = m_openxr.duoview_compositors[&tc->commands];
+                if (!comp) comp = std::make_unique<uevr::duoview::dx12::Compositor>();
+                if (comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), srgb, frequency))
+                    ++prepared;
+                else
+                    spdlog::warn("[DuoView][Activation] DX12 command-slot prewarm failed: {}", comp->error());
+            }
+            SPDLOG_INFO("[DuoView][Activation] Prepared {}/{} OpenXR command slots on ID6 entry",
+                prepared, it->second.texture_contexts.size());
+        }
+    }
     spdlog::info("[VR] d3d12 textures have been setup");
     m_force_reset = false;
 
     return true;
 }
 
+void D3D12Component::OpenXR::prepare_quadview_compositors(ID3D12Device* device, DXGI_FORMAT source_format,
+    UINT64 timestamp_frequency) {
+    // Prewarm outside copy(): no pipeline/heap/allocation creation in its callback.
+    std::scoped_lock lock{mtx};
+    auto it=contexts.find((uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE);
+    if (it==contexts.end()) return;
+    if (source_format==DXGI_FORMAT_B8G8R8A8_TYPELESS) source_format=DXGI_FORMAT_B8G8R8A8_UNORM;
+    if (source_format==DXGI_FORMAT_R8G8B8A8_TYPELESS) source_format=DXGI_FORMAT_R8G8B8A8_UNORM;
+    const auto& hook=g_framework->get_d3d12_hook();
+    ID3D12CommandQueue* const queue=hook ? hook->get_command_queue() : nullptr;
+    if (!quadview_edge_history || quadview_edge_history->device.Get()!=device || quadview_edge_history->queue.Get()!=queue)
+        quadview_edge_history=uevr::quadview::dx12::EdgeHistoryState::create(device,queue);
+    auto& context=it->second;
+    for (size_t i=0; i<context.texture_contexts.size() && i<context.textures.size(); ++i) {
+        auto& tc=context.texture_contexts[i];
+        if (!tc || !tc->commands.references_retired() || !context.textures[i].texture) continue;
+        auto& comp=quadview_compositors[&tc->commands];
+        if (!comp) comp=std::make_unique<uevr::quadview::dx12::Compositor>();
+        comp->on_slot_retired();
+        auto output_format=context.textures[i].texture->GetDesc().Format;
+        // The existing DOUBLE_WIDE swapchain is requested as BGRA8 sRGB;
+        // runtimes may expose its resource with a typeless family format.
+        if (output_format==DXGI_FORMAT_B8G8R8A8_TYPELESS) output_format=DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
+        if (output_format==DXGI_FORMAT_R8G8B8A8_TYPELESS) output_format=DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
+        if (!comp->prewarm(device,source_format,output_format,timestamp_frequency))
+            SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadView][Prewarm] {}",comp->error());
+        comp->set_edge_history(quadview_edge_history);
+    }
+}
+
 void D3D12Component::OpenXR::initialize(XrSessionCreateInfo& session_info) {
     std::scoped_lock _{this->mtx};
 
 	auto& hook = g_framework->get_d3d12_hook();
 
     auto device = hook->get_device();
@@ -6873,13 +7335,18 @@ void D3D12Component::OpenXR::initialize(XrSessionCreateInfo& session_info) {
 
 std::optional<std::string> D3D12Component::OpenXR::create_swapchains() {
     std::scoped_lock _{this->mtx};
 
     spdlog::info("[VR] Creating OpenXR swapchains for D3D12");
 
-    this->destroy_swapchains();
+    if (!this->destroy_swapchains())
+        return "OpenXR swapchain destruction postponed: resources still live";
+    if (!this->duoview_compositors.empty())
+        return "DuoView command-slot retirement pending; swapchains retained";
+    if (!this->quadview_compositors.empty())
+        return "QuadView command-slot retirement pending; swapchains retained";
     
     auto& hook = g_framework->get_d3d12_hook();
     auto device = hook->get_device();
     auto swapchain = hook->get_swap_chain();
 
     ComPtr<ID3D12Resource> backbuffer{};
@@ -6904,12 +7371,13 @@ std::optional<std::string> D3D12Component::OpenXR::create_swapchains() {
     heap_props.CPUPageProperty = D3D12_CPU_PAGE_PROPERTY_UNKNOWN;
     heap_props.MemoryPoolPreference = D3D12_MEMORY_POOL_UNKNOWN;
 
     auto backbuffer_desc = backbuffer->GetDesc();
     auto& openxr = vr->m_openxr;
 
+    this->duoview_compositors.clear();
     this->contexts.clear();
 
     auto create_swapchain = [&](uint32_t i, const XrSwapchainCreateInfo& swapchain_create_info, const D3D12_RESOURCE_DESC& desc) -> std::optional<std::string> {
         // Create the swapchain.
         runtimes::OpenXR::Swapchain swapchain{};
         swapchain.width = swapchain_create_info.width;
@@ -7025,12 +7493,30 @@ std::optional<std::string> D3D12Component::OpenXR::create_swapchains() {
         spdlog::info("[VR] Height: {}", vr->get_hmd_height());
 
         if (auto err = create_swapchain((uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, standard_swapchain_create_info, hmd_desc)) {
             return err;
         }
 
+        if (vr->is_duoview_renderer_active()) {
+            auto& duo_ctx = this->contexts[(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE];
+            const bool duo_srgb = backbuffer_desc.Format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
+                                  backbuffer_desc.Format == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
+            UINT64 duo_frequency{};
+            if (const auto queue=g_framework->get_d3d12_hook()->get_command_queue(); queue)
+                queue->GetTimestampFrequency(&duo_frequency);
+            for (auto& tc : duo_ctx.texture_contexts) {
+                if (!tc) continue;
+                auto& comp = this->duoview_compositors[&tc->commands];
+                if (!comp) comp = std::make_unique<uevr::duoview::dx12::Compositor>();
+                if (!comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), duo_srgb, duo_frequency)) {
+                    SPDLOG_WARNING_EVERY_N_SEC(2,
+                        "[DuoView] DX12 prewarm failed; guarded compositing/fallback remains available");
+                }
+            }
+        }
+
         if (vr->is_native_stereo_fix_texture_array_submit_enabled()) {
             auto native_array_create_info = standard_swapchain_create_info;
             auto native_array_desc = hmd_desc;
 
             native_array_create_info.width = vr->get_hmd_width();
             native_array_create_info.arraySize = 2;
@@ -7106,13 +7592,16 @@ std::optional<std::string> D3D12Component::OpenXR::create_swapchains() {
     // block as Native and create AFR depth swapchains at the end of setup.
     const bool create_afr_depth = vr->is_using_afr();
     const bool skip_dead_island_2_afr_depth =
         create_afr_depth && is_dead_island_2_ue425_current_game();
 
     // Depth textures
-    if (vr->get_openxr_runtime()->is_depth_allowed()) {
+    if (vr->triview_skips_xr_depth() && vr->get_openxr_runtime()->is_depth_allowed()) {
+        spdlog::info("[TriView][VRAM] OpenXR depth swapchain not created (TriView never submits depth)");
+    }
+    if (vr->get_openxr_runtime()->is_depth_allowed() && !vr->triview_skips_xr_depth()) {
         // Even when using AFR, the depth tex is always the size of a double wide.
         // That's kind of unfortunate in terms of how many copies we have to do but whatever.
         auto depth_swapchain_create_info = standard_swapchain_create_info;
         depth_swapchain_create_info.format = DXGI_FORMAT_D32_FLOAT_S8X24_UINT;
         depth_swapchain_create_info.createFlags = 0;
         depth_swapchain_create_info.usageFlags = XR_SWAPCHAIN_USAGE_SAMPLED_BIT | XR_SWAPCHAIN_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | XR_SWAPCHAIN_USAGE_MUTABLE_FORMAT_BIT;
@@ -7213,28 +7702,109 @@ std::optional<std::string> D3D12Component::OpenXR::create_swapchains() {
 
     this->last_resolution = {vr->get_hmd_width(), vr->get_hmd_height()};
 
     return std::nullopt;
 }
 
-void D3D12Component::OpenXR::destroy_swapchains() {
-    std::scoped_lock _{this->mtx};
-    const bool composition_retired = this->ui_composition.reset();
-    const bool game_alpha_retired = this->game_ui_alpha.reset();
-    const bool framework_alpha_retired = this->framework_ui_alpha.reset();
+bool D3D12Component::OpenXR::depth_quiescent_for_restart() const {
+    return uevr::quadview::ngx::PeripheryDepth::self().restart_quiescent();
+}
 
-    if (this->contexts.empty()) {
-        return;
+bool D3D12Component::OpenXR::discard_completed_depth_on_restart() {
+    return uevr::quadview::ngx::PeripheryDepth::self().discard_completed_for_new_xr_session();
+}
+
+bool D3D12Component::OpenXR::destroy_swapchains() {
+    std::scoped_lock _{this->mtx};
+    // The preflight must run before ANY UI/compositor/swapchain mutation.
+    if (restart_teardown_failed) return false;
+    // Only enter original wait_for_all_copies() with all D3D12 fences
+    // retired, so its inherited wait(INFINITE) is already satisfied. An
+    // XR image may still be acquired: the original helper releases it.
+    // New pre-acquisitions are blocked in restart phase 3.
+    for (const auto& [index,context]:this->contexts) {
+        for (const auto& slot:context.texture_contexts)
+            if (slot && !slot->commands.references_retired()) return false;
+    }
+    // Compositor-map keys are raw pointers; prove that the command context
+    // still belongs to the currently retained swapchain BEFORE dereferencing.
+    const auto slot_live=[&](const d3d12::CommandContext* command) {
+        if (!command) return false;
+        for (const auto& [index,context]:this->contexts) {
+            for (const auto& slot:context.texture_contexts) {
+                if (slot && &slot->commands==command) return true;
+            }
+        }
+        return false;
+    };
+    for (const auto& [commands, compositor] : this->quadview_compositors)
+        if (compositor && (!slot_live(commands) || commands->poisoned)) return false;
+    for (const auto& [commands, compositor] : this->duoview_compositors)
+        if (compositor && (!slot_live(commands) || commands->poisoned)) return false;
+    if (this->contexts.empty() && this->quadview_compositors.empty() &&
+        this->duoview_compositors.empty()) {
+        return this->ui_composition.reset() && this->game_ui_alpha.reset() &&
+            this->framework_ui_alpha.reset();
     }
     
     auto& vr = VR::get();
     std::scoped_lock __{vr->m_openxr->swapchain_mtx};
 
     spdlog::info("[VR] Destroying swapchains.");
 
+    for (const auto& [commands, compositor] : this->quadview_compositors) {
+        if (compositor && (!commands || commands->poisoned)) {
+            spdlog::error("[QuadView] Swapchain retirement is unproven"); return false;
+        }
+    }
+    for (const auto& [commands, compositor] : this->duoview_compositors) {
+        if (compositor && (!commands || commands->poisoned)) {
+            spdlog::error("[DuoView] Retaining swapchains: command-slot retirement is unproven");
+            return false;
+        }
+    }
     this->wait_for_all_copies();
+    // The original helper releases any XR images already acquired at the
+    // transaction boundary. An XR release failure must veto destruction.
+    for (const auto& [index,context]:this->contexts)
+        if (context.num_textures_acquired != 0 || context.pre_acquired)
+            return false;
+    // All acquired XR contexts must be released and every GPU command-slot
+    // fence proven complete before UI reset or compositor destruction.
+    for (const auto& [commands, compositor] : this->quadview_compositors)
+        if (compositor && (!slot_live(commands) || !commands->references_retired())) return false;
+    for (const auto& [commands, compositor] : this->duoview_compositors)
+        if (compositor && (!slot_live(commands) || !commands->references_retired())) return false;
+    const bool composition_retired=this->ui_composition.reset();
+    const bool game_alpha_retired=this->game_ui_alpha.reset();
+    const bool framework_alpha_retired=this->framework_ui_alpha.reset();
+    if (!composition_retired || !game_alpha_retired || !framework_alpha_retired) {
+        // UI reset can partially mutate state. Do not continue rendering with
+        // uncertain descriptors or pretend a successful XR restart.
+        restart_teardown_failed=true;
+        if (vr && vr->get_runtime()) vr->get_runtime()->loaded=false;
+        spdlog::error("[TriView][Restart] UI retirement incomplete; XR rendering stopped, restart game");
+        return false;
+    }
+    for (const auto& [commands, compositor] : this->duoview_compositors) {
+        if (compositor && !commands->references_retired()) {
+            spdlog::error("[DuoView] Retaining swapchains: GPU references have not retired");
+            return false;
+        }
+    }
+    for (auto& [commands, compositor] : this->quadview_compositors) {
+        if (compositor && !commands->references_retired()) {
+            spdlog::error("[QuadView] GPU references have not retired"); return false;
+        }
+        if (compositor) compositor->on_slot_retired();
+    }
+    vr->get_openxr_runtime()->invalidate_quadview_scene();
+    this->quadview_compositors.clear();
+    this->quadview_edge_history.reset();
+    vr->get_openxr_runtime()->invalidate_duoview_scene();
+    this->duoview_compositors.clear();
 
     for (auto& it : this->contexts) {
         auto& ctx = it.second;
         const auto i = it.first;
 
         //ctx.texture_contexts.clear();
@@ -7260,12 +7830,14 @@ void D3D12Component::OpenXR::destroy_swapchains() {
             spdlog::error("[UI Processing] Retaining original UI swapchain after unproven GPU retirement");
         } else if (vr->m_openxr->swapchains.contains(i)) {
             const auto result = xrDestroySwapchain(vr->m_openxr->swapchains[i].handle);
 
             if (result != XR_SUCCESS) {
                 spdlog::error("[VR] Failed to destroy swapchain {}.", i);
+                restart_teardown_failed=true;
+                if (vr && vr->get_runtime()) vr->get_runtime()->loaded=false;
             } else {
                 spdlog::info("[VR] Destroyed swapchain {}.", i);
             }
         } else {
             spdlog::error("[VR] Swapchain {} does not exist.", i);
         }
@@ -7280,18 +7852,21 @@ void D3D12Component::OpenXR::destroy_swapchains() {
         
         ctx.textures.clear();
     }
 
     this->contexts.clear();
     vr->m_openxr->swapchains.clear();
+    return !restart_teardown_failed;
 }
 
 bool D3D12Component::OpenXR::pre_acquire(uint32_t swapchain_idx) {
     std::scoped_lock _{this->mtx};
 
     auto vr = VR::get();
+    // During phase 3, no new async image acquisitions on the old XR session.
+    if (vr && vr->triview_restart_phase()==3) return false;
 
     if (vr == nullptr || vr->m_openxr == nullptr) {
         return false;
     }
 
     if (!vr->m_openxr->can_run_frame_loop() ||
@@ -7310,12 +7885,14 @@ bool D3D12Component::OpenXR::pre_acquire(uint32_t swapchain_idx) {
 
     if (ctx.num_textures_acquired > 0 || ctx.pre_acquired) {
         return false;
     }
 
     const auto& swapchain = vr->m_openxr->swapchains[swapchain_idx];
+    if (swapchain_idx==(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE &&
+        vr->is_using_duoview_mono()) vr->get_openxr_runtime()->invalidate_duoview_scene();
     XrSwapchainImageAcquireInfo acquire_info{XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};
 
     uint32_t texture_index{};
     auto result = xrAcquireSwapchainImage(swapchain.handle, &acquire_info, &texture_index);
 
     if (result != XR_SUCCESS) {
@@ -7378,12 +7955,15 @@ void D3D12Component::OpenXR::release_acquired(uint32_t swapchain_idx) {
 
     if (texture_index < ctx.texture_contexts.size() && ctx.texture_contexts[texture_index] != nullptr) {
         ctx.texture_contexts[texture_index]->commands.wait(INFINITE);
     }
 
     const auto& swapchain = vr->m_openxr->swapchains[swapchain_idx];
+    if (vr->is_quadview_mode_selected() &&
+        swapchain_idx==(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE)
+        vr->m_openxr->invalidate_quadview_scene();
     XrSwapchainImageReleaseInfo release_info{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
     auto result = xrReleaseSwapchainImage(swapchain.handle, &release_info);
 
     if (result == XR_ERROR_RUNTIME_FAILURE) {
         for (auto& texture_ctx : ctx.texture_contexts) {
             if (texture_ctx != nullptr) {
@@ -7765,12 +8345,14 @@ bool D3D12Component::OpenXR::copy(
                 static_cast<uint32_t>(dst_desc.Format));
             return false;
         }
     }
 
     uint32_t texture_index{};
+    if (swapchain_idx==(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE &&
+        vr->is_using_duoview_mono()) vr->get_openxr_runtime()->invalidate_duoview_scene();
     bool used_pre_acquired_image = false;
 
     if (ctx.pre_acquired && ctx.num_textures_acquired > 0) {
         texture_index = ctx.last_acquired_texture;
         ctx.pre_acquired = false;
         used_pre_acquired_image = true;
@@ -7840,12 +8422,15 @@ bool D3D12Component::OpenXR::copy(
         ctx.stalker_pairs[texture_index] = retained_stalker_pair;
     }
     if (retained_mono_source != nullptr) {
         if (!retired || !texture_ctx->commands.ready()) {
             // No new commands reference this acquired image. Keep the old
             // source owned; never reset an allocator or block on its fence.
+            if (vr->is_quadview_mode_selected() &&
+                swapchain_idx==(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE)
+                vr->m_openxr->invalidate_quadview_scene();
             XrSwapchainImageReleaseInfo release_info{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
             if (XR_SUCCEEDED(xrReleaseSwapchainImage(swapchain.handle, &release_info))) {
                 --ctx.num_textures_acquired;
                 ctx.pre_acquired = false;
             }
             return false;
@@ -7882,15 +8467,25 @@ bool D3D12Component::OpenXR::copy(
     }
 
     if (post_copy_commands) {
         (*post_copy_commands)(texture_ctx->commands, ctx.textures[texture_index].texture);
     }
 
+    const bool duo_copy=(vr->is_duoview_renderer_active() || vr->is_quadview_mode_selected()) &&
+        swapchain_idx==(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE;
+    const auto duo_fence_before=texture_ctx->commands.fence_value;
+    const bool duo_recorded=texture_ctx->commands.has_commands;
     const auto stalker_fence_before = retained_stalker_pair ? texture_ctx->commands.fence_value : 0;
     const bool stalker_recorded = retained_stalker_pair && texture_ctx->commands.has_commands;
     texture_ctx->commands.execute();
+    const bool duo_enqueued=!duo_copy || uevr::stalker2_native::SubmissionProof{
+        duo_fence_before, texture_ctx->commands.fence_value, duo_recorded,
+        !texture_ctx->commands.poisoned, texture_ctx->commands.waiting_for_fence,
+        texture_ctx->commands.fence!=nullptr,
+        binding.queue==g_framework->get_d3d12_hook()->get_command_queue(),
+        binding.device==g_framework->get_d3d12_hook()->get_device()}.confirmed();
     bool stalker_enqueued = false;
     if (retained_stalker_pair) {
         const auto& commands = texture_ctx->commands;
         const auto active_queue = g_framework->get_d3d12_hook()->get_command_queue();
         stalker_enqueued = uevr::stalker2_native::SubmissionProof{stalker_fence_before, commands.fence_value,
             stalker_recorded, !commands.poisoned, commands.waiting_for_fence, commands.fence != nullptr,
@@ -7914,12 +8509,18 @@ bool D3D12Component::OpenXR::copy(
         if (src_box == nullptr && !texture_ctx->commands.poisoned) { this->process_ui_alpha(swapchain_idx, texture_index); }
         else {
             (swapchain_idx == (uint32_t)runtimes::OpenXR::SwapchainIndex::UI ? game_ui_alpha : framework_ui_alpha).begin_frame();
             ui_composition.invalidate(swapchain_idx == (uint32_t)runtimes::OpenXR::SwapchainIndex::FRAMEWORK_UI);
         }
     }
+    // Invalidate the old image/pose only when publishing a replacement.
+    // A failed recording or enqueue still releases this acquired image, so it
+    // must not be submitted using the previous image's pose.
+    if (vr->is_quadview_mode_selected() &&
+        swapchain_idx==(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE)
+        vr->m_openxr->invalidate_quadview_scene();
     XrSwapchainImageReleaseInfo release_info{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
     auto result = xrReleaseSwapchainImage(swapchain.handle, &release_info);
 
     // SteamVR shenanigans.
     if (result == XR_ERROR_RUNTIME_FAILURE) {
         spdlog::error("[VR] xrReleaseSwapchainImage failed: {}", vr->m_openxr->get_result_string(result));
@@ -7953,13 +8554,13 @@ bool D3D12Component::OpenXR::copy(
 
     ctx.num_textures_acquired--;
     ctx.pre_acquired = false;
     ctx.last_acquired_texture = texture_index;
     ctx.last_acquired_frame = vr->get_frame_count();
     ctx.ever_acquired = true;
-    return !texture_ctx->commands.poisoned && (!retained_stalker_pair || stalker_enqueued);
+    return duo_enqueued && !texture_ctx->commands.poisoned && (!retained_stalker_pair || stalker_enqueued);
 }
 void D3D12Component::OpenXR::process_ui_alpha(uint32_t swapchain_idx, uint32_t texture_index) {
     const auto vr = VR::get();
     const bool framework = swapchain_idx == (uint32_t)runtimes::OpenXR::SwapchainIndex::FRAMEWORK_UI;
     auto& helper = framework ? framework_ui_alpha : game_ui_alpha;
     if (!vr || !vr->m_openxr || !vr->m_openxr->frame_began ||
diff --git a/src/mods/vr/D3D12Component.hpp b/src/mods/vr/D3D12Component.hpp
index b02a54eb..0d26f6d9 100644
--- a/src/mods/vr/D3D12Component.hpp
+++ b/src/mods/vr/D3D12Component.hpp
@@ -22,15 +22,18 @@
 #include <../../directxtk12-src/Inc/SpriteBatch.h>
 #include <../../directxtk12-src/Inc/DescriptorHeap.h>
 
 #include "d3d12/CommandContext.hpp"
 #include "d3d12/DIBRPreview.hpp"
 #include "d3d12/TextureContext.hpp"
+#include "DuoViewD3D12.hpp"
+#include "QuadViewD3D12.hpp"
 #include "UIAlpha.hpp"
 #include "UIComposition.hpp"
 #include "Stalker2NativeD3D12.hpp"
+#include "QuadViewRetirement.hpp"
 
 class VR;
 namespace render {
 class FrameResourceInspector;
 }
 
@@ -43,13 +46,14 @@ public:
 
     }
 
     vr::EVRCompositorError on_frame(VR* vr);
     void on_post_present(VR* vr);
     void on_reset(VR* vr, bool mono_retired = false);
-    bool mono_consumers_retired();
+    bool mono_consumers_retired(uevr::quadview::RetirementScope scope =
+        uevr::quadview::RetirementScope::mode_transition);
 
     void force_reset() { m_force_reset = true; }
 
     const auto& get_backbuffer_size() const { return m_backbuffer_size; }
 
     auto is_initialized() const { return m_openvr.left_eye_tex[0].texture != nullptr; }
@@ -417,13 +421,16 @@ private:
         friend class D3D12Component;
     } m_openvr;
 
     struct OpenXR {
         void initialize(XrSessionCreateInfo& session_info);
         std::optional<std::string> create_swapchains();
-        void destroy_swapchains();
+        bool destroy_swapchains();
+        bool depth_quiescent_for_restart() const;
+        bool discard_completed_depth_on_restart();
+        bool restart_teardown_failed{false};
         bool pre_acquire(uint32_t swapchain_idx);
         void release_acquired(uint32_t swapchain_idx);
         bool copy(uint32_t swapchain_idx, ID3D12Resource* src,
             std::optional<std::function<void(d3d12::CommandContext&, ID3D12Resource*)>> pre_commands = std::nullopt,
             std::optional<std::function<void(d3d12::CommandContext&)>> additional_commands = std::nullopt,
             D3D12_RESOURCE_STATES src_state = D3D12_RESOURCE_STATE_PRESENT,
@@ -504,12 +511,16 @@ private:
             uint32_t framework_ui_last_released_texture{0};
             uint32_t framework_ui_last_release_frame{0};
             uint64_t framework_ui_front_buffer_skip_count{0};
             uint64_t framework_ui_last_submitted_generation{0};
         };
 
+        void prepare_quadview_compositors(ID3D12Device* device, DXGI_FORMAT source_format, UINT64 timestamp_frequency);
+        std::shared_ptr<uevr::quadview::dx12::EdgeHistoryState> quadview_edge_history;
+        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::quadview::dx12::Compositor>> quadview_compositors;
+        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;
         std::unordered_map<uint32_t, SwapchainContext> contexts{};
         std::recursive_mutex mtx{};
         std::array<uint32_t, 2> last_resolution{};
         bool made_depth_with_null_defaults{false};
         D3D12_RESOURCE_DESC stable_depth_desc{};
         bool has_stable_depth_desc{};
diff --git a/src/mods/vr/FFakeStereoRenderingHook.cpp b/src/mods/vr/FFakeStereoRenderingHook.cpp
index 42858980..77ec9eb4 100644
--- a/src/mods/vr/FFakeStereoRenderingHook.cpp
+++ b/src/mods/vr/FFakeStereoRenderingHook.cpp
@@ -1,6 +1,9 @@
+#include "HeadMovementScaling.hpp"
+#include "TriViewGammaTables.hpp"
+#include <stdexcept>
 #define NOMINMAX
 
 #include <windows.h>
 #include <d3d11.h>
 #include <d3d12.h>
 #include <winternl.h>
@@ -117,12 +120,16 @@
 #include <sdk/threading/RHIThreadWorker.hpp>
 #include "../VR.hpp"
 #include "../../utility/Logging.hpp"
 #include "../../utility/BuildIdentity.hpp"
 
 #include "FFakeStereoRenderingHook.hpp"
+
+thread_local FFakeStereoRenderingHook::QuadViewNativeBuildContext FFakeStereoRenderingHook::quadview_native_build_context{};
+#include "DuoViewGeometry.hpp"
+#include "TriViewAdmission.hpp"
 #include "CompatibilityPolicy.hpp"
 #include "BodycamTextureLayout.hpp"
 #include "HellraiserCaptureLayout.hpp"
 #include "BreathedgeInventoryPolicy.hpp"
 #include "Borderlands4Slate.hpp"
 #include "UE58OwnedUITexture.hpp"
@@ -142,12 +149,47 @@ static_assert(static_cast<int32_t>(VR::ALTERNATING) ==
     static_cast<int32_t>(uevr::vr_compatibility::RenderingMethod::Alternating));
 static_assert(static_cast<int32_t>(VR::SYNTHETIC_DIBR) ==
     static_cast<int32_t>(uevr::vr_compatibility::RenderingMethod::SyntheticDibr));
 static_assert(static_cast<int32_t>(VR::SYNTHETIC_DIBR_SINGLE_VIEW) ==
     static_cast<int32_t>(uevr::vr_compatibility::RenderingMethod::SyntheticDibrSingleView));
 
+namespace uevr::quadview {
+int hook_trace_mode() {
+    const auto& vr=VR::get();
+    if(!vr) return -1;
+    return vr->is_quadview_mode_selected()?7:vr->is_duoview_renderer_active()?6:
+        vr->is_using_mono()?5:vr->is_using_native_stereo()?0:-1;
+}
+// B22: optional verbose diagnostics. HookTrace is observation only; retaining
+// it in the per-frame RHI path adds lock contention and large log writes.
+// Set UEVR_VERBOSE_HOOK_TRACE=1 BEFORE starting the game to restore the exact
+// existing detailed trace output for crash/provenance investigations.
+static bool hook_trace_enabled() {
+    static const bool enabled = [] {
+        char value[8]{};
+        const DWORD len = GetEnvironmentVariableA("UEVR_VERBOSE_HOOK_TRACE", value, DWORD(sizeof(value)));
+        return len == 1 && value[0] == '1';
+    }();
+    return enabled;
+}
+void emit_hook_trace(size_t site,const HookTraceRecord& r) {
+    if (!hook_trace_enabled()) return;
+    static HookTraceGate gate;
+    const auto now=std::chrono::steady_clock::now();
+    const auto ms=std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
+    const auto decision=gate.visit(site,r.generation,r.serial,static_cast<uint64_t>(ms));
+    if(!decision.emit) return;
+    SPDLOG_INFO("[QuadViews][HookTrace] event={} generation={} serial={} frame={} role={} mode={} reason={} site={} count={} thread={} root={:x} tail={:x} list={:x} family={:x} target={:x} scene={:x} recorded={} ours_known={} ours={} live_vtable={:x} original_vtable={:x} recorded_frame={} owner_generation={} owner_serial={} engine={} native={} source={} duo={} vtables={} engines={} natives={} drains={} drain={} index={} expected_index={} result={} elapsed_us={} pending={} canonical={} rendered={} hooked={} executed={} written={} detail=\"{}\"",
+        r.event,r.generation,r.serial,r.frame,r.role,r.mode,r.reason,site,decision.count,GetCurrentThreadId(),
+        r.root,r.tail,r.list,r.family,r.target,r.scene,r.recorded,r.ours_known,r.ours,r.vtable,r.original_vtable,
+        r.recorded_frame,r.owner_generation,r.owner_serial,r.engine,r.native,r.source,r.duo,
+        r.vtables,r.engines,r.natives,r.drains,r.drain,r.index,r.expected_index,r.result,r.elapsed_us,r.pending,
+        r.canonical_frame,r.rendered,r.hooked,r.executed,r.written,r.detail?r.detail:"none");
+}
+}
+
 namespace {
 bool is_writable_process_range(uintptr_t address, size_t size);
 bool is_readable_process_range(uintptr_t address, size_t size);
 bool is_executable_process_range(uintptr_t address, size_t size);
 bool halloween_ue574_dx12_runtime();
 bool looks_like_vtable_object(void* object);
@@ -6026,12 +6068,18 @@ std::optional<ValidatedNativeFixTextureChain> validate_native_fix_texture_chain(
             return std::nullopt;
         }
 
         auto* const rhi_texture = *reinterpret_cast<FRHITexture2D**>(
             reinterpret_cast<uintptr_t>(texture_resource) + layout.texture_rhi_offset);
         const auto expected_rhi_vtable = FRHITexture2D::get_vtable();
+        if (const auto vr=VR::get(); vr && vr->is_quadview_mode_selected()) {
+            SPDLOG_INFO_EVERY_N_SEC(2,
+                "[QuadViews][Bootstrap] RHI class_ready={} expected_vtable={:x} texture={:x}",
+                expected_rhi_vtable != nullptr,reinterpret_cast<uintptr_t>(expected_rhi_vtable),
+                reinterpret_cast<uintptr_t>(rhi_texture));
+        }
         if (rhi_texture == nullptr || expected_rhi_vtable == nullptr ||
             !is_readable_process_range(reinterpret_cast<uintptr_t>(rhi_texture), sizeof(uintptr_t)) ||
             *reinterpret_cast<void**>(rhi_texture) != expected_rhi_vtable)
         {
             return std::nullopt;
         }
@@ -13442,12 +13490,21 @@ void FFakeStereoRenderingHook::on_frame() {
     // we will fall back to doing it here.
     if (!uevr::nascar::is_target() && !m_hooked_game_engine_tick && m_attempted_hook_game_engine_tick) {
         attempt_hooking();
     }
 }
 
+struct QuadViewNativeRhiQueueSnapshot {
+    uint64_t tail_owner_records{};
+    uint64_t tracked_engine_records{};
+    uint64_t hooked_command_records_all_modes{};
+    bool observed{};
+    bool busy{};
+};
+QuadViewNativeRhiQueueSnapshot sample_quadview_native_rhi_queue();
+
 std::string FFakeStereoRenderingHook::build_hook_provenance_json() {
     try {
         nlohmann::json result{
             {"schema_version", 2},
             {"diagnostic_only", true},
             {"snapshot_note", "best-effort snapshot; refresh after hook installation stabilizes"},
@@ -13505,12 +13562,114 @@ std::string FFakeStereoRenderingHook::build_hook_provenance_json() {
                 {"instruction_limit", 32},
             };
         }
 
         result["native_frame_diagnostics"] = uevr::native_frame::export_json(m_native_frame_diagnostics);
 
+        // Independent best-effort samples; busy means this component was dropped.
+        result["quadview_diagnostics_snapshot"] = {
+            {"observation_only", true}, {"components_sampled_independently", true},
+            {"cross_component_atomic", false},
+            {"no_gpu_or_queue_work", true},
+        };
+        const auto& quad_vr = VR::get();
+        const uint64_t quad_generation = quad_vr ? quad_vr->mono_generation() : 0;
+        const auto quad_delivery = quadview_delivery.diagnostics_snapshot(quad_generation);
+        nlohmann::json quad_delivery_json{
+            {"observed", !quad_delivery.busy}, {"busy", quad_delivery.busy},
+            {"requested_generation", quad_generation ? nlohmann::json(quad_generation) : nlohmann::json(nullptr)},
+            {"generation_scope", quad_generation ? "active generation filter" : "all generations (unfiltered)"},
+        };
+        if (!quad_delivery.busy) {
+            quad_delivery_json["source_slots"] = quad_delivery.source_slots;
+            quad_delivery_json["incomplete_source_slots"] = quad_delivery.incomplete_source_slots;
+            quad_delivery_json["pending_engine_tickets"] = quad_delivery.pending_engine_tickets;
+            quad_delivery_json["engine_tracking_overflowed"] = quad_delivery.engine_tracking_overflowed;
+        }
+        result["quadview_delivery"] = std::move(quad_delivery_json);
+
+        const auto quad_native = quadview_native_delivery.diagnostics_snapshot(quad_generation);
+        nlohmann::json quad_native_json{
+            {"observed", !quad_native.busy}, {"busy", quad_native.busy},
+            {"requested_generation", quad_generation ? nlohmann::json(quad_generation) : nlohmann::json(nullptr)},
+            {"generation_scope", quad_generation ? "active generation filter" : "all generations (unfiltered)"},
+        };
+        if (!quad_native.busy) {
+            quad_native_json["occupied_slots"] = quad_native.occupied_slots;
+            quad_native_json["active_tails"] = quad_native.active_tails;
+            quad_native_json["shared_tails"] = quad_native.shared_tails;
+            quad_native_json["ambiguous_tails"] = quad_native.ambiguous_tails;
+            quad_native_json["oldest_retained_found"] = quad_native.oldest_retained_found;
+        }
+        if (!quad_native.busy && quad_native.oldest_retained_found) {
+            quad_native_json["oldest_retained_owner"] = {
+                {"generation", quad_native.oldest_retained_generation}, {"serial", quad_native.oldest_retained_serial},
+                {"rendered_mask", quad_native.oldest_retained_rendered}, {"hooked_mask", quad_native.oldest_retained_hooked},
+                {"executed_mask", quad_native.oldest_retained_executed}, {"written_mask", quad_native.oldest_retained_written},
+                {"pending_count", quad_native.oldest_retained_pending_count},
+                {"completion_latched", quad_native.oldest_retained_completion_latched},
+                {"publish", quad_native.oldest_retained_publish}, {"overwritten", quad_native.oldest_retained_overwritten},
+            };
+        } else if (!quad_native.busy) {
+            quad_native_json["oldest_retained_owner"] = nullptr;
+        }
+        result["quadview_native_delivery"] = std::move(quad_native_json);
+
+        const auto quad_rhi = sample_quadview_native_rhi_queue();
+        nlohmann::json quad_rhi_json{
+            {"observed", quad_rhi.observed}, {"busy", quad_rhi.busy},
+            {"requested_generation", nullptr},
+            {"generation_scope", "process-global map records; includes entries across generation resets"},
+        };
+        if (quad_rhi.observed && !quad_rhi.busy) {
+            quad_rhi_json["tail_owner_records"] = quad_rhi.tail_owner_records;
+            quad_rhi_json["tail_owner_record_semantics"] = "retained map records; not unique quartets";
+            quad_rhi_json["tracked_engine_records"] = quad_rhi.tracked_engine_records;
+            quad_rhi_json["hooked_command_records_all_modes"] = quad_rhi.hooked_command_records_all_modes;
+            quad_rhi_json["scope"] = "native tail and engine maps are Quad Views; original vtable map spans all tracked RHI hook modes";
+        }
+        result["quadview_native_rhi_queue"] = std::move(quad_rhi_json);
+
+        if (auto* manager = get_render_target_manager()) {
+            const auto retire = manager->get_quadview_native_retirement_diagnostics();
+            nlohmann::json retire_json{
+                {"observed", retire.observed}, {"busy", retire.busy},
+                {"requested_generation", nullptr},
+                {"generation_scope", "process-global retirement queue across resets"},
+            };
+            if (!retire.observed) retire_json["status"] = "not_observed";
+            if (retire.observed && !retire.busy) {
+                retire_json["pending"] = {{"count", retire.pending.count}, {"truncated", retire.pending.truncated}};
+                retire_json["staged"] = {{"count", retire.staged.count}, {"truncated", retire.staged.truncated}};
+                retire_json["in_flight"] = {{"count", retire.in_flight.count}, {"truncated", retire.in_flight.truncated}};
+                retire_json["ready"] = {{"count", retire.ready.count}, {"truncated", retire.ready.truncated}};
+                retire_json["count_is_lower_bound_when_truncated"] = true;
+                retire_json["per_list_walk_cap"] = uevr::quadview::native_retirement_list_walk_cap;
+                retire_json["last_successful_signal_observed"] = retire.last_successful_signal_observed;
+                retire_json["last_successful_queue"] = retire.last_successful_queue ? nlohmann::json(fmt::format("0x{:x}", retire.last_successful_queue)) : nlohmann::json(nullptr);
+                retire_json["last_successful_device"] = retire.last_successful_device ? nlohmann::json(fmt::format("0x{:x}", retire.last_successful_device)) : nlohmann::json(nullptr);
+                retire_json["last_successful_fence"] = retire.last_successful_fence ? nlohmann::json(fmt::format("0x{:x}", retire.last_successful_fence)) : nlohmann::json(nullptr);
+                retire_json["last_successful_signal_value"] = retire.last_successful_signal_observed
+                    ? nlohmann::json(retire.last_successful_signal_value) : nlohmann::json(nullptr);
+                retire_json["last_poll_state"] = uevr::quadview::to_string(retire.last_poll_state);
+                retire_json["last_poll_fence"] = retire.last_poll_fence ? nlohmann::json(fmt::format("0x{:x}", retire.last_poll_fence)) : nlohmann::json(nullptr);
+                retire_json["last_poll_device"] = retire.last_poll_device ? nlohmann::json(fmt::format("0x{:x}", retire.last_poll_device)) : nlohmann::json(nullptr);
+                retire_json["last_poll_completed_value"] = retire.last_poll_state != uevr::quadview::NativeRetirementPollState::unobserved
+                    ? nlohmann::json(retire.last_poll_completed_value) : nlohmann::json(nullptr);
+                retire_json["last_poll_target_value"] = retire.last_poll_state != uevr::quadview::NativeRetirementPollState::unobserved
+                    ? nlohmann::json(retire.last_poll_target_value) : nlohmann::json(nullptr);
+                retire_json["signal_and_poll_values_are_compared"] = false;
+                retire_json["queue_identity_proves_ordered_execution"] = false;
+                retire_json["poll_target_is_for_last_polled_fence_only"] = true;
+                retire_json["cross_fence_epoch_progress_is_inferred"] = false;
+            }
+            result["quadview_native_retirement"] = std::move(retire_json);
+        } else {
+            result["quadview_native_retirement"] = {{"observed", false}, {"busy", false}, {"status", "manager_unavailable"}};
+        }
+
         const auto executable = utility::get_executable();
         const auto executable_path = utility::get_module_pathw(executable);
         const auto file_version = sdk::get_file_version_info();
         const auto detected_version = utility::narrow(
             sdk::search_for_version(executable).value_or(L"unknown"));
 
@@ -14745,13 +14904,13 @@ void FFakeStereoRenderingHook::swgr_slate_output_hook(safetyhook::Context& ctx)
     if (!frame || !scene || ctx.r13 != scene->source_texture || ctx.r14 != scene->source_texture ||
         !vr || !vr->is_hmd_active() ||
         vr->is_stereo_emulation_enabled()) { return; }
     g_framework->notify_render_activity();
     g_hook->note_stable_slate_draw();
     get_swgr_ui_resource_worker().execute();
-    g_hook->get_slate_thread_worker()->execute(reinterpret_cast<FRHICommandListImmediate*>(frame->command_list));
+    { uevr::quadview::NativeDrainScope qv_drain_scope{reinterpret_cast<uintptr_t>(reinterpret_cast<FRHICommandListImmediate*>(frame->command_list))}; g_hook->get_slate_thread_worker()->execute(reinterpret_cast<FRHICommandListImmediate*>(frame->command_list)); }
     rtm->request_dedicated_ui_target(frame->width, frame->height);
     rtm->ensure_dedicated_ui_target(frame->command_list);
     auto lifetime = rtm->try_pin_swgr_ui_registration();
     if (!lifetime.owns_lock()) { return; }
     const auto ui = rtm->get_swgr_ui_snapshot();
     if (!ui || ui->desc.Width != frame->width || ui->desc.Height != frame->height ||
@@ -16070,13 +16229,15 @@ void FFakeStereoRenderingHook::attempt_hook_fsceneview_constructor() {
             return;
         }
     }
 
     auto& vr = VR::get();
 
-    if (!vr->is_ghosting_fix_enabled() && !vr->is_splitscreen_compatibility_enabled() && !vr->is_sceneview_compatibility_enabled() && !vr->is_native_stereo_fix_enabled()) {
+    if (!vr->is_ghosting_fix_enabled() && !vr->is_splitscreen_compatibility_enabled() && !vr->is_sceneview_compatibility_enabled() && !vr->is_native_stereo_fix_enabled() &&
+        !vr->is_quadview_supported_title() && !vr->is_quadview_mode_selected() &&
+        vr->requested_rendering_method() != VR::RenderingMethod::QUAD_VIEWS_STEREO) {
         return;
     }
 
     utility::ScopeGuard _{[&]() {
         m_attempted_hook_fsceneview_constructor = true;
     }};
@@ -20849,12 +21010,13 @@ void FFakeStereoRenderingHook::game_viewport_client_draw_hook(sdk::UGameViewport
         call_orig();
         return;
     }
 
     g_hook->m_in_viewport_client_draw = true;
     g_hook->m_was_in_viewport_client_draw = false;
+    VR::get()->duoview_start_draw();
     g_hook->get_render_target_manager()->set_viewport(viewport);
     if (viewport != nullptr) {
         shf_force_scene_viewport_separate_rt(*viewport, "UGameViewportClient::Draw");
         g_hook->attempt_hook_naruto_ue416_draw_stereo_predicate();
         g_hook->attempt_hook_naruto_ue416_projection_rect();
         g_hook->attempt_hook_naruto_ue416_init_dynamic_rhi(viewport);
@@ -21709,12 +21871,19 @@ struct SceneViewExtensionAnalyzer {
         return false;
     }
 
     static inline std::recursive_mutex vtable_mutex{};
     static inline std::unordered_map<sdk::FRHICommandBase_New*, void**> original_vtables{};
     static inline std::unordered_map<sdk::FRHICommandBase_New*, uint32_t> cmd_frame_counts{};
+    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::DuoDelivery::Command> duo_command_sources{};
+    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::QuadViewDelivery::Source> quad_command_sources{};
+    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket> quad_command_engines{};
+    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::QuadViewNativeDelivery::TailOwnerBatch> quad_native_commands{};
+    using QuadDrainBatch=uevr::quadview::EngineDrainBatch<FFakeStereoRenderingHook::QuadViewDelivery>;
+    static inline std::unordered_map<sdk::FRHICommandBase_New*,QuadDrainBatch> quad_drain_commands{};
+    static inline std::atomic_uintptr_t quad_trace_hook_vtable{};
 
     // Meant to be called after analysis has been completed
     static void setup_view_extension_hook() {
         std::scoped_lock _{dummy_mutex};
 
         SPDLOG_INFO("Setting up BeginRenderViewFamily hook...");
@@ -21782,13 +21951,21 @@ struct SceneViewExtensionAnalyzer {
     static inline std::unordered_set<int> tested_execute_indices{};
     static inline int correct_execute_index{0};
     static inline bool found_correct_execute{false};
 
     template<int N>
     static void* hooked_command_fn(sdk::FRHICommandBase_New* cmd, sdk::FRHICommandListBase* cmd_list, void* debug_context, void* r9, void* stack_1, void* stack_2, void* stack_3, void* stack_4, void* stack_5, void* stack_6, void* stack_7, void* stack_8) {
+        uevr::quadview::HookTraceRecord qv_pre{};
+        qv_pre.event="RHI_ENTRY";qv_pre.reason="pre_lock";qv_pre.tail=reinterpret_cast<uintptr_t>(cmd);
+        qv_pre.list=reinterpret_cast<uintptr_t>(cmd_list);qv_pre.index=N;
+        if(const auto& current=VR::get();current) qv_pre.generation=current->mono_generation();
+        qv_pre.mode=uevr::quadview::hook_trace_mode();
+        uevr::quadview::emit_hook_trace(7,qv_pre);
+        const auto qv_lock_start=std::chrono::steady_clock::now();
         std::scoped_lock _{vtable_mutex};
+        const auto qv_lock_acquired=std::chrono::steady_clock::now();
         //std::scoped_lock __{VR::get()->get_vr_mutex()};
 
         static bool once = true;
 
         if (once) {
             SPDLOG_INFO("[ISceneViewExtension] Successfully hijacked command list! {}", N);
@@ -21800,12 +21977,31 @@ struct SceneViewExtensionAnalyzer {
 
         const auto original_vtable = original_vtables[cmd];
         const auto original_func = original_vtable[N];
 
         const auto func = (decltype(hooked_command_fn<N>)*)original_func;
         const auto frame_count = cmd_frame_counts[cmd];
+        const auto source_it = duo_command_sources.find(cmd);
+        const auto duo_command = source_it != duo_command_sources.end()
+            ? source_it->second : FFakeStereoRenderingHook::DuoDelivery::Command{};
+        const auto duo_source = duo_command.owner();
+        const auto quad_source_it=quad_command_sources.find(cmd);
+        const auto quad_source=quad_source_it != quad_command_sources.end()
+            ? quad_source_it->second : FFakeStereoRenderingHook::QuadViewDelivery::Source{};
+        const auto quad_engine_it=quad_command_engines.find(cmd);
+        const auto quad_engine=quad_engine_it != quad_command_engines.end()
+            ? quad_engine_it->second : FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket{};
+        const auto quad_native_it=quad_native_commands.find(cmd);
+        // Keep this local lease alive through RHIThreadWorker::execute() and
+        // the original command callback. Ledger reset cannot prove that a
+        // queued CPU command has drained.
+        const auto quad_native_record=quad_native_it != quad_native_commands.end()
+            ? quad_native_it->second : FFakeStereoRenderingHook::QuadViewNativeDelivery::TailOwnerBatch{};
+        const auto quad_native=quad_native_record.ticket;
+        const auto quad_drain_it=quad_drain_commands.find(cmd);
+        const auto quad_drain=quad_drain_it!=quad_drain_commands.end() ? quad_drain_it->second : QuadDrainBatch{};
 
         if (once) {
             SPDLOG_INFO("[ISceneViewExtension] Command list frame count: {}", frame_count);
             SPDLOG_INFO("[ISceneViewExtension] Original vtable: {:x}", (uintptr_t)original_vtable);
             once = false;
         }
@@ -21822,91 +22018,351 @@ struct SceneViewExtensionAnalyzer {
                 SPDLOG_INFO("[ISceneViewExtension] Found correct execute index: {}", N);
             }
         }
 
         auto& vr = VR::get();
         auto runtime = vr->get_runtime();
+        uevr::quadview::HookTraceRecord qv_rhi{};
+        const auto* qv_native_owner=quad_native_record.owner_count?&quad_native_record.owners[0]:nullptr;
+        qv_rhi.generation=vr->mono_generation();qv_rhi.mode=uevr::quadview::hook_trace_mode();
+        qv_rhi.frame=frame_count;qv_rhi.tail=reinterpret_cast<uintptr_t>(cmd);qv_rhi.list=reinterpret_cast<uintptr_t>(cmd_list);
+        qv_rhi.index=N;qv_rhi.expected_index=correct_execute_index;
+        qv_rhi.serial=quad_engine?quad_engine.serial:quad_source?quad_source.serial:qv_native_owner?qv_native_owner->source.serial:
+            quad_drain.count?quad_drain.tickets[0].serial:duo_source.packet?duo_source.packet->serial:0;
+        qv_rhi.owner_generation=quad_engine?quad_engine.generation:quad_source?quad_source.generation:
+            qv_native_owner?qv_native_owner->source.generation:quad_drain.count?quad_drain.tickets[0].generation:
+            duo_source?duo_source.generation:0;
+        qv_rhi.owner_serial=qv_rhi.serial;qv_rhi.role=qv_native_owner?unsigned(qv_native_owner->view):255;
+        qv_rhi.engine=bool(quad_engine);qv_rhi.native=bool(quad_native);qv_rhi.source=bool(quad_source);qv_rhi.duo=bool(duo_source);
+        qv_rhi.vtables=original_vtables.size();qv_rhi.engines=quad_command_engines.size();
+        qv_rhi.natives=quad_native_commands.size();qv_rhi.drains=quad_drain_commands.size();
+        qv_rhi.original_vtable=reinterpret_cast<uintptr_t>(original_vtable);
+        auto qv_emit_rhi=[qv_rhi](size_t site,const char* event,const char* reason,uint64_t us=0,int result=-1) {
+            auto r=qv_rhi;r.event=event;r.reason=reason;r.elapsed_us=us;r.result=result;
+            uevr::quadview::emit_hook_trace(site,r);
+        };
+        qv_emit_rhi(8,"RHI_ENTRY","owner_bound");
+        qv_emit_rhi(9,"RHI_LOCKED","lock_wait",static_cast<uint64_t>(
+            std::chrono::duration_cast<std::chrono::microseconds>(qv_lock_acquired-qv_lock_start).count()));
+        auto qv_sync_frame=[&](uint32_t frame,VRRuntime::SyncFrameCallsite callsite) {
+            qv_emit_rhi(10,"XR_SYNC_ENTER","synchronize_frame");
+            const auto started=std::chrono::steady_clock::now();
+            const auto result=runtime->synchronize_frame(frame,callsite);
+            qv_emit_rhi(11,"XR_SYNC_RETURN","synchronize_frame",static_cast<uint64_t>(
+                std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-started).count()),static_cast<int>(result));
+            return result;
+        };
+        // Hold admission through the actual XR side effects, not just
+        // their serial check. GT closes nonblockingly and retries while we drain.
+        const bool quad_epoch_needed=bool(quad_native) || bool(quad_source) || bool(quad_engine) || quad_drain.count!=0;
+        auto quad_epoch_lease=quad_epoch_needed ? vr->triview_epoch_read() : uevr::triview::EpochGate::Read{};
+        const bool quad_epoch_admitted=!quad_epoch_needed || bool(quad_epoch_lease);
+        FFakeStereoRenderingHook::QuadViewNativeDelivery::RuntimeEvent quad_native_runtime_event{};
+        const bool quad_native_runtime_claimed=N==correct_execute_index && quad_native && g_hook && quad_epoch_admitted &&
+            g_hook->quadview_native_delivery.claim_runtime_event(quad_native,quad_native_runtime_event) &&
+            vr->triview_source_epoch_accepts(quad_native_runtime_event.serial);
+        const auto runtime_frame_count=quad_native_runtime_claimed ? quad_native_runtime_event.frame : frame_count;
 
         auto call_orig = [=]() {
+            qv_emit_rhi(12,"ORIGINAL_ENTER","engine_callback");
+            const auto qv_original_started=std::chrono::steady_clock::now();
             const auto result = func(cmd, cmd_list, debug_context, r9, stack_1, stack_2, stack_3, stack_4, stack_5, stack_6, stack_7, stack_8);
+            qv_emit_rhi(13,"ORIGINAL_RETURN","engine_callback",static_cast<uint64_t>(
+                std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-qv_original_started).count()));
 
             if (N == correct_execute_index) {
-                runtime->enqueue_render_poses(frame_count);
+                if ((quad_native ? quad_native_runtime_claimed : (quad_epoch_admitted &&
+                    (!quad_source || vr->triview_source_epoch_accepts(quad_source.serial)) &&
+                    (!quad_engine || vr->triview_source_epoch_accepts(quad_engine.serial)) &&
+                    (!quad_drain.count || vr->triview_source_epoch_accepts(quad_drain.newest_serial)) &&
+                    quad_drain.allows_runtime(vr->mono_generation(),quad_engine))) &&
+                    (!duo_source || (vr->is_duoview_renderer_active() && duo_source.generation==vr->mono_generation())))
+                    runtime->enqueue_render_poses(quad_native_runtime_claimed ? quad_native_runtime_event.frame : frame_count);
+                if (duo_source && vr->is_duoview_renderer_active() && g_hook != nullptr) {
+                    for (const auto& source : duo_command.sources) {
+                        if (source) g_hook->duoview_delivery.executed(source, reinterpret_cast<uintptr_t>(cmd), GetCurrentThreadId());
+                    }
+                }
+                if (quad_drain.count && g_hook &&
+                    !quad_drain.execute(g_hook->quadview_delivery,reinterpret_cast<uintptr_t>(cmd),
+                        GetCurrentThreadId(),vr->mono_generation()))
+                    vr->set_quadview_status("Recovery tail failed to retire every authenticated engine owner");
+                if (quad_native && g_hook != nullptr) {
+                    const auto execution=g_hook->quadview_native_delivery.executed_tail(quad_native,GetCurrentThreadId());
+                    qv_emit_rhi(14,"NATIVE_EXECUTION","executed_tail",0,execution.accepted?1:0);
+                    {
+                        auto trace=qv_rhi;trace.event="NATIVE_COMPLETION";
+                        trace.reason=execution.quarantined?"quarantined":"eligible";
+                        trace.result=execution.accepted?1:0;trace.pending=execution.completed_quartets;
+                        trace.canonical_frame=execution.sync_frame;
+                        uevr::quadview::emit_hook_trace(31,trace);
+                    }
+                    SPDLOG_INFO_EVERY_N_SEC(2,"[QuadViews][RHI] native tail executed tail={} accepted={}",quad_native.id,execution.accepted);
+                    if (!execution.accepted)
+                        vr->set_quadview_status("Native quartet RHI execution did not match its exact target owner");
+                }
+                if (quad_engine && g_hook != nullptr && quad_engine.generation==vr->mono_generation()) {
+                    if (!g_hook->quadview_delivery.executed_engine_family(quad_engine,
+                            (quad_drain.count || quad_native) ? FFakeStereoRenderingHook::QuadViewDelivery::Source{} : quad_source,
+                            reinterpret_cast<uintptr_t>(cmd),GetCurrentThreadId()))
+                        vr->set_quadview_status("Tracked engine family command did not match its RHI owner");
+                }
                 if (g_hook != nullptr) { g_hook->note_nascar25_render_pose_handoff(frame_count); }
                 if (g_hook != nullptr) { g_hook->note_stalker2_rhi_handoff(frame_count); }
             }
 
+            qv_emit_rhi(15,"RHI_COMPLETE",N==correct_execute_index?"correct_index":"other_index",
+                static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(
+                    std::chrono::steady_clock::now()-qv_lock_acquired).count()));
             return result;
         };
 
         if (N != correct_execute_index) {
             return call_orig();
         }
 
         // set the vtable back
         *(void**)cmd = original_vtable;
         original_vtables.erase(cmd);
         cmd_frame_counts.erase(cmd);
-
+        duo_command_sources.erase(cmd);
+        quad_command_sources.erase(cmd);
+        quad_command_engines.erase(cmd);
+        quad_native_commands.erase(cmd);
+        quad_drain_commands.erase(cmd);
+
+        if (quad_native_runtime_claimed)
+            runtime->on_pre_render_render_thread(runtime_frame_count);
+        qv_emit_rhi(16,"WORKER_ENTER","rhi_worker");
         RHIThreadWorker::get().execute();
-
-        if (vr->get_synchronize_stage() == VR::SynchronizeStage::EARLY) {
+        qv_emit_rhi(17,"WORKER_RETURN","rhi_worker");
+
+        if ((quad_native ? quad_native_runtime_claimed : (quad_epoch_admitted &&
+                    (!quad_source || vr->triview_source_epoch_accepts(quad_source.serial)) &&
+                    (!quad_engine || vr->triview_source_epoch_accepts(quad_engine.serial)) &&
+                    (!quad_drain.count || vr->triview_source_epoch_accepts(quad_drain.newest_serial)) &&
+                    quad_drain.allows_runtime(vr->mono_generation(),quad_engine))) &&
+            vr->get_synchronize_stage() == VR::SynchronizeStage::EARLY &&
+            (!duo_source || (vr->is_duoview_renderer_active() && duo_source.generation==vr->mono_generation()))) {
             if (runtime->is_openxr()) {
                 if (g_framework->get_renderer_type() == Framework::RendererType::D3D11) {
-                    if (!runtime->got_first_sync || runtime->synchronize_frame(frame_count, VRRuntime::SyncFrameCallsite::VREarlyRHICommand) != VRRuntime::Error::SUCCESS) {
+                    if (!runtime->got_first_sync || qv_sync_frame(runtime_frame_count, VRRuntime::SyncFrameCallsite::VREarlyRHICommand) != VRRuntime::Error::SUCCESS) {
                         return call_orig();
                     }  
-                } else if (runtime->synchronize_frame(frame_count, VRRuntime::SyncFrameCallsite::VREarlyRHICommand) != VRRuntime::Error::SUCCESS) {
+                } else if (qv_sync_frame(runtime_frame_count, VRRuntime::SyncFrameCallsite::VREarlyRHICommand) != VRRuntime::Error::SUCCESS) {
                     return call_orig();
                 }
 
                 vr->get_openxr_runtime()->begin_frame();
             } else {
-                if (runtime->synchronize_frame(frame_count, VRRuntime::SyncFrameCallsite::VREarlyRHICommand) != VRRuntime::Error::SUCCESS) {
+                if (qv_sync_frame(runtime_frame_count, VRRuntime::SyncFrameCallsite::VREarlyRHICommand) != VRRuntime::Error::SUCCESS) {
                     return call_orig();
                 }
             }
         }
 
         return call_orig();
     }
 
-    static void hook_new_rhi_command(sdk::FRHICommandBase_New* last_command, uint32_t frame_count) {
+    static void hook_new_rhi_command(sdk::FRHICommandBase_New* last_command, uint32_t frame_count,
+        const FFakeStereoRenderingHook::DuoDelivery::Source& duo_source = {},
+        const FFakeStereoRenderingHook::QuadViewDelivery::Source& quad_source = {},
+        const FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket& quad_engine = {},
+        const FFakeStereoRenderingHook::QuadViewNativeDelivery::Command& quad_native = {}) {
         std::scoped_lock __{vtable_mutex};
 
         auto& vr = VR::get();
         auto runtime = vr->get_runtime();
-        const bool preserve_pending_identity = uevr::vr_compatibility::should_preserve_mafia_pending_rhi_identity(
+        const auto qv_initial_root=reinterpret_cast<uintptr_t>(last_command);
+        auto qv_trace=[&](size_t site,const char* event,const char* reason,const char* detail="none",int result=-1) {
+            uevr::quadview::HookTraceRecord r{};
+            r.event=event;r.reason=reason;r.detail=detail;r.result=result;
+            r.generation=vr->mono_generation();r.mode=uevr::quadview::hook_trace_mode();r.frame=frame_count;
+            r.serial=quad_native?quad_native.source.serial:quad_engine?quad_engine.serial:quad_source?quad_source.serial:
+                duo_source.packet?duo_source.packet->serial:0;
+            r.owner_generation=quad_native?quad_native.source.generation:quad_engine?quad_engine.generation:
+                quad_source?quad_source.generation:duo_source?duo_source.generation:0;
+            r.owner_serial=r.serial;r.role=quad_native?unsigned(quad_native.view):255;
+            r.engine=bool(quad_engine);r.native=bool(quad_native);r.source=bool(quad_source);r.duo=bool(duo_source);
+            r.root=qv_initial_root;r.tail=reinterpret_cast<uintptr_t>(last_command);
+            r.vtables=original_vtables.size();r.engines=quad_command_engines.size();
+            r.natives=quad_native_commands.size();r.drains=quad_drain_commands.size();
+            const auto recorded=original_vtables.find(last_command);r.recorded=recorded!=original_vtables.end();
+            if(r.recorded) r.original_vtable=reinterpret_cast<uintptr_t>(recorded->second);
+            const auto old_frame=cmd_frame_counts.find(last_command);
+            if(old_frame!=cmd_frame_counts.end()) r.recorded_frame=old_frame->second;
+            if(is_readable_process_range(r.tail,sizeof(uintptr_t))) std::memcpy(&r.vtable,last_command,sizeof(uintptr_t));
+            const auto ours=quad_trace_hook_vtable.load(std::memory_order_relaxed);
+            r.ours_known=ours!=0;r.ours=ours && r.vtable==ours;
+            const auto drain=uevr::quadview::NativeDrainScope::current();r.drain=drain.id;r.list=drain.immediate_list;
+            uevr::quadview::emit_hook_trace(site,r);
+        };
+        qv_trace(1,"HOOK_ENTER","entry");
+        if (duo_source && (!vr->is_duoview_renderer_active() || duo_source.generation!=vr->mono_generation())) { qv_trace(60,"HOOK_REJECT","duo_generation_or_mode",vr->quadview_status()); return; }
+        if (quad_source && quad_source.generation!=vr->mono_generation()) { qv_trace(61,"HOOK_REJECT","source_generation",vr->quadview_status()); return; }
+        if (quad_engine && quad_engine.generation!=vr->mono_generation()) { qv_trace(62,"HOOK_REJECT","engine_generation",vr->quadview_status()); return; }
+        if (quad_native && quad_native.source.generation!=vr->mono_generation()) { qv_trace(63,"HOOK_REJECT","native_generation",vr->quadview_status()); return; }
+        if (vr->is_quadview_mode_selected() && !quad_native && !quad_engine && !quad_source) { qv_trace(64,"HOOK_REJECT","quad_without_owner",vr->quadview_status()); return; }
+        if (!duo_source && vr->is_duoview_renderer_active() && original_vtables.contains(last_command)) { qv_trace(65,"HOOK_REJECT","duo_unowned_recorded_root",vr->quadview_status()); return; }
+        if (quad_engine || quad_native) {
+            const char* root_rejection{};
+            if (!original_vtables.contains(last_command) && !is_probable_new_rhi_command(last_command, root_rejection)) {
+                vr->set_quadview_status("Rejected an unsafe main-family RHI command before tail ownership"); { qv_trace(66,"HOOK_REJECT","quad_root_invalid",root_rejection); return; }
+            }
+            uintptr_t readable_begin{}, readable_end{};
+            const auto tail=uevr::duoview::command_tail(reinterpret_cast<uintptr_t>(last_command),
+                [&](uintptr_t at) -> std::optional<uintptr_t> {
+                    if (at < readable_begin || at >= readable_end || readable_end-at < sizeof(sdk::FRHICommandBase_New)) {
+                        MEMORY_BASIC_INFORMATION region{};
+                        if (!is_readable_process_range(at, sizeof(sdk::FRHICommandBase_New)) ||
+                            !VirtualQuery(reinterpret_cast<void*>(at), &region, sizeof(region))) return {};
+                        readable_begin=reinterpret_cast<uintptr_t>(region.BaseAddress); readable_end=readable_begin+region.RegionSize;
+                    }
+                    return reinterpret_cast<uintptr_t>(reinterpret_cast<sdk::FRHICommandBase_New*>(at)->next);
+                });
+            if (!tail) { vr->set_quadview_status("Could not identify the exact main-family RHI command tail"); { qv_trace(67,"HOOK_REJECT","quad_tail_not_found",vr->quadview_status()); return; } }
+            last_command=reinterpret_cast<sdk::FRHICommandBase_New*>(*tail);
+            qv_trace(2,"HOOK_TAIL","quad_tail_selected");
+            if (original_vtables.contains(last_command)) {
+                if (quad_engine && !quad_native) {
+                    const auto primary=quad_command_engines.find(last_command);
+                    if (primary!=quad_command_engines.end() && primary->second.same_owner(quad_engine)) { qv_trace(68,"HOOK_RETURN","engine_duplicate_owner",vr->quadview_status()); return; }
+                    const bool known_tail=quad_drain_commands.contains(last_command) ||
+                        quad_native_commands.contains(last_command) || primary!=quad_command_engines.end();
+                    if (!known_tail) {
+                        vr->set_quadview_status("Recovery engine owner encountered an unrelated hooked tail"); { qv_trace(69,"HOOK_REJECT","engine_foreign_recorded_tail",vr->quadview_status()); return; }
+                    }
+                    auto& drain=quad_drain_commands[last_command];
+                    const auto prior_serial=drain.newest_serial;
+                    if (!drain.attach(g_hook->quadview_delivery,quad_engine,
+                            reinterpret_cast<uintptr_t>(last_command),quad_source)) {
+                        vr->set_quadview_status("Recovery tail owner capacity or identity rejected; transition remains blocked"); { qv_trace(70,"HOOK_REJECT","engine_drain_attach_failed",vr->quadview_status()); return; }
+                    }
+                    // Mixed legacy atlas writes have no ordered content proof.
+                    // Revoke publication while map records retain packet leases
+                    // through the actual original CPU callback.
+                    if (quad_source) g_hook->quadview_delivery.retire(quad_source.generation,quad_source.serial);
+                    const auto previous_source=quad_command_sources.find(last_command);
+                    if (previous_source!=quad_command_sources.end())
+                        g_hook->quadview_delivery.retire(previous_source->second.generation,previous_source->second.serial);
+                    if (!quad_native_commands.contains(last_command) && quad_engine.serial>prior_serial)
+                        cmd_frame_counts[last_command]=frame_count;
+                    { qv_trace(71,"HOOK_RETURN","engine_drain_attached",vr->quadview_status()); return; }
+                }
+                if (quad_native) {
+                    auto existing=quad_native_commands.find(last_command);
+                    if (existing==quad_native_commands.end()) {
+                        if (!quad_drain_commands.contains(last_command) && !quad_command_engines.contains(last_command)) {
+                            vr->set_quadview_status("Shared native command tail has no authenticated recovery owner"); { qv_trace(72,"HOOK_REJECT","native_foreign_recorded_tail",vr->quadview_status()); return; }
+                        }
+                        const auto drain=uevr::quadview::NativeDrainScope::current();
+                        const auto attached=g_hook->quadview_native_delivery.hook_batch(quad_native,
+                            reinterpret_cast<uintptr_t>(last_command),drain.id,drain.immediate_list,frame_count);
+                        qv_trace(3,"NATIVE_ATTACH","hook_batch","none",static_cast<int>(attached.status));
+                        FFakeStereoRenderingHook::QuadViewNativeDelivery::TailOwnerBatch batch{};
+                        if (!attached || !batch.retain(quad_native,attached.tail)) {
+                            vr->set_quadview_status("Native role could not join the authenticated recovery tail"); { qv_trace(73,"HOOK_REJECT","native_recovery_attach_failed",vr->quadview_status()); return; }
+                        }
+                        quad_native_commands.emplace(last_command,std::move(batch));
+                        const auto legacy=quad_command_sources.find(last_command);
+                        if (legacy!=quad_command_sources.end())
+                            g_hook->quadview_delivery.retire(legacy->second.generation,legacy->second.serial);
+                        { qv_trace(74,"HOOK_RETURN","native_recovery_attached",vr->quadview_status()); return; }
+                    }
+                    const auto drain=uevr::quadview::NativeDrainScope::current();
+                    const auto attached=g_hook->quadview_native_delivery.hook_batch(quad_native,
+                        reinterpret_cast<uintptr_t>(last_command),drain.id,drain.immediate_list,frame_count);
+                        qv_trace(4,"NATIVE_ATTACH","hook_batch","none",static_cast<int>(attached.status));
+                    if (!attached || attached.tail.id!=existing->second.ticket.id ||
+                        !existing->second.retain(quad_native,attached.tail)) {
+                        vr->set_quadview_status("Could not retain every owner attached to a shared native tail");
+                        { qv_trace(75,"HOOK_REJECT","native_shared_retain_failed",vr->quadview_status()); return; }
+                    }
+                    if (!attached.publishable())
+                        vr->set_quadview_status("Shared native tail is drain-only because its owner order is ambiguous");
+                }
+                const auto owner=quad_command_engines.find(last_command);
+                if (quad_engine && (owner == quad_command_engines.end() || !owner->second.same_owner(quad_engine)))
+                    vr->set_quadview_status("RHI command tail also contains a different tracked engine-family owner");
+                { qv_trace(76,"HOOK_RETURN","recorded_tail_return",vr->quadview_status()); return; }
+            }
+        }
+        if (duo_source) {
+            const char* root_rejection{};
+            if (!original_vtables.contains(last_command) && !is_probable_new_rhi_command(last_command, root_rejection)) {
+                g_hook->duoview_delivery.block(duo_source, reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());
+                { qv_trace(77,"HOOK_REJECT","duo_root_invalid",root_rejection); return; }
+            }
+            uintptr_t readable_begin{}, readable_end{};
+            const auto tail = uevr::duoview::command_tail(reinterpret_cast<uintptr_t>(last_command),
+                [&](uintptr_t at) -> std::optional<uintptr_t> {
+                    if (at < readable_begin || at >= readable_end || readable_end-at < sizeof(sdk::FRHICommandBase_New)) {
+                        MEMORY_BASIC_INFORMATION region{};
+                        if (!is_readable_process_range(at, sizeof(sdk::FRHICommandBase_New)) ||
+                            !VirtualQuery(reinterpret_cast<void*>(at), &region, sizeof(region))) return {};
+                        readable_begin=reinterpret_cast<uintptr_t>(region.BaseAddress);
+                        readable_end=readable_begin+region.RegionSize;
+                    }
+                    return reinterpret_cast<uintptr_t>(reinterpret_cast<sdk::FRHICommandBase_New*>(at)->next);
+                });
+            if (!tail) {
+                g_hook->duoview_delivery.block(duo_source, reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());
+                SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView][Delivery] Command tail unreadable/cyclic; source ownership not advanced");
+                { qv_trace(78,"HOOK_REJECT","duo_tail_not_found",vr->quadview_status()); return; }
+            }
+            last_command = reinterpret_cast<sdk::FRHICommandBase_New*>(*tail);
+            if (original_vtables.contains(last_command)) {
+                const auto owner = duo_command_sources.find(last_command);
+                using Attachment=FFakeStereoRenderingHook::DuoDelivery::Attachment;
+                const auto attached=owner!=duo_command_sources.end()
+                    ? owner->second.attach(duo_source) : Attachment::conflict;
+                g_hook->duoview_delivery.note(attached==Attachment::added ? uevr::duoview::DeliveryEvent::hook :
+                    attached==Attachment::duplicate ? uevr::duoview::DeliveryEvent::duplicate :
+                    uevr::duoview::DeliveryEvent::conflict, duo_source, *tail, GetCurrentThreadId());
+                if (attached==Attachment::conflict) g_hook->duoview_delivery.block(duo_source, *tail, GetCurrentThreadId());
+                if (attached==Attachment::conflict) SPDLOG_WARNING_EVERY_N_SEC(2,
+                    "[DuoView][Delivery] Pending tail ownership conflict command={:x} owner={} incoming={} frame={}",
+                    *tail, owner != duo_command_sources.end() && owner->second.owner().packet ? owner->second.owner().packet->serial : 0,
+                    duo_source.packet ? duo_source.packet->serial : 0, duo_source.frame);
+                { qv_trace(79,"HOOK_RETURN","duo_shared_return",vr->quadview_status()); return; }
+            }
+        }
+        const bool preserve_pending_identity = vr->is_duoview_renderer_active() || vr->is_quadview_mode_selected() ||
+            uevr::vr_compatibility::should_preserve_mafia_pending_rhi_identity(
             sdk::mafia::uses_ue544_discovery(), vr->is_using_native_stereo(), vr->is_native_stereo_fix_enabled());
         if (!preserve_pending_identity) {
-            runtime->on_pre_render_render_thread(frame_count);
+            if (!quad_native) runtime->on_pre_render_render_thread(frame_count);
         }
 
         const char* rejection_reason = nullptr;
         if (!is_probable_new_rhi_command(last_command, rejection_reason)) {
+            if (duo_source) g_hook->duoview_delivery.block(duo_source,
+                reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());
+            if (quad_engine) vr->set_quadview_status("Tracked engine family command failed RHI tail validation; transition remains blocked");
             if (preserve_pending_identity) {
-                runtime->on_pre_render_render_thread(frame_count);
+                if (!quad_native) runtime->on_pre_render_render_thread(frame_count);
             }
             SPDLOG_WARN_ONCE(
                 "[ISceneViewExtension] Rejected unsafe new RHI-command candidate before hijack ({}); "
                 "falling back to render-thread poses",
                 rejection_reason != nullptr ? rejection_reason : "unknown");
-            runtime->enqueue_render_poses(frame_count);
-            return;
+            if (!quad_native) runtime->enqueue_render_poses(frame_count);
+            { qv_trace(80,"HOOK_REJECT","tail_vtable_invalid",rejection_reason); return; }
         }
 
         // Whichever one gets called first is the winner winner chicken dinner
         static std::array<uintptr_t, 7> new_vtable{
             (uintptr_t)&hooked_command_fn<0>,
             (uintptr_t)&hooked_command_fn<1>,
             (uintptr_t)&hooked_command_fn<2>,
             (uintptr_t)&hooked_command_fn<3>,
             (uintptr_t)&hooked_command_fn<4>,
             (uintptr_t)&hooked_command_fn<5>,
             (uintptr_t)&hooked_command_fn<6>
         };
+        quad_trace_hook_vtable.store(reinterpret_cast<uintptr_t>(new_vtable.data()),std::memory_order_relaxed);
 
         if (preserve_pending_identity &&
             (original_vtables.contains(last_command) || *(void**)last_command == new_vtable.data())) {
             const auto pending = cmd_frame_counts.find(last_command);
             if (pending != cmd_frame_counts.end() && pending->second == frame_count && original_vtables.contains(last_command)) {
                 SPDLOG_INFO_ONCE("[Mafia][NativeFix][RHI] Reused pending same-frame command; retaining its original vtable/frame and pose enqueue");
@@ -21918,16 +22374,16 @@ struct SceneViewExtensionAnalyzer {
                         reinterpret_cast<uintptr_t>(last_command), pending != cmd_frame_counts.end() ? pending->second : 0, frame_count);
                     last_warning = now;
                 }
             }
             // The replayed family has not created another command. In particular,
             // do not relabel an already queued command or enqueue its poses twice.
-            return;
+            { qv_trace(81,"HOOK_RETURN","preserved_pending_return",vr->quadview_status()); return; }
         }
         if (preserve_pending_identity) {
-            runtime->on_pre_render_render_thread(frame_count);
+            if (!quad_native) runtime->on_pre_render_render_thread(frame_count);
         }
 
         if (shf_is_current_game() && shf_texture_diagnostics_enabled() &&
             (original_vtables.contains(last_command) || *(void**)last_command == new_vtable.data())) {
             const auto pending = cmd_frame_counts.find(last_command);
             SPDLOG_INFO_EVERY_N_SEC(2,
@@ -21952,17 +22408,62 @@ struct SceneViewExtensionAnalyzer {
             }
 
             if (auto vr = VR::get(); vr != nullptr) {
                 vr->note_stalker2_transition_stress("duplicate_rhi_command");
             }
 
-            return;
+            { qv_trace(82,"HOOK_RETURN","generic_duplicate_return",vr->quadview_status()); return; }
         }
 
         original_vtables[last_command] = *(void***)last_command;
+        if (duo_source) {
+            FFakeStereoRenderingHook::DuoDelivery::Command command{};
+            command.attach(duo_source);
+            duo_command_sources.emplace(last_command, std::move(command));
+            g_hook->duoview_delivery.note(uevr::duoview::DeliveryEvent::hook, duo_source,
+                reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());
+        }
+        if (quad_engine && !quad_source && !quad_native) {
+            QuadDrainBatch batch{};
+            if (!batch.attach(g_hook->quadview_delivery,quad_engine,reinterpret_cast<uintptr_t>(last_command))) {
+                original_vtables.erase(last_command); { qv_trace(83,"HOOK_REJECT","engine_drain_first_attach_failed",vr->quadview_status()); return; }
+            }
+            quad_drain_commands.emplace(last_command,std::move(batch));
+        } else if (quad_engine) {
+            if (!g_hook->quadview_delivery.tail_hooked_engine_family(quad_engine,quad_source,
+                    reinterpret_cast<uintptr_t>(last_command))) {
+                vr->set_quadview_status("Could not latch the tracked engine-family RHI tail; transition remains blocked");
+                original_vtables.erase(last_command); { qv_trace(84,"HOOK_REJECT","engine_source_latch_failed",vr->quadview_status()); return; }
+            }
+            quad_command_engines.emplace(last_command,quad_engine);
+        }
+        if (quad_native) {
+            const auto drain=uevr::quadview::NativeDrainScope::current();
+            const auto attached=g_hook->quadview_native_delivery.hook_batch(quad_native,
+                reinterpret_cast<uintptr_t>(last_command),drain.id,drain.immediate_list,frame_count);
+                        qv_trace(5,"NATIVE_ATTACH","hook_batch","none",static_cast<int>(attached.status));
+            if (!attached) {
+                vr->set_quadview_status("Native quartet command could not attach to its exact RHI tail; engine owner remains tracked");
+                original_vtables.erase(last_command); { qv_trace(85,"HOOK_REJECT","native_first_attach_failed",vr->quadview_status()); return; }
+            }
+            if (!attached.publishable())
+                vr->set_quadview_status("Native quartet command tail is drain-only because its owner order is ambiguous");
+            FFakeStereoRenderingHook::QuadViewNativeDelivery::TailOwnerBatch owner_batch{};
+            if (!owner_batch.retain(quad_native,attached.tail)) {
+                vr->set_quadview_status("Native quartet tail could not retain its packet owner");
+                original_vtables.erase(last_command); { qv_trace(86,"HOOK_REJECT","native_owner_lease_failed",vr->quadview_status()); return; }
+            }
+            quad_native_commands.emplace(last_command,owner_batch);
+        }
+        if (quad_source) {
+            quad_command_sources.emplace(last_command, quad_source);
+            SPDLOG_INFO_EVERY_N_SEC(2, "[QuadViews][RHI] tail hooked serial={} frame={} command={:x}",
+                quad_source.serial, quad_source.engine_frame, reinterpret_cast<uintptr_t>(last_command));
+        }
         *(void***)last_command = (void**)new_vtable.data();
+        qv_trace(6,"HOOK_INSTALLED","vtable_replaced");
     }
 
     static void hook_old_rhi_command(sdk::FRHICommandBase_Old* last_command, uint32_t frame_count) {
         static std::recursive_mutex func_mutex{};
         static std::unordered_map<sdk::FRHICommandBase_Old*, sdk::FRHICommandBase_Old::Func> original_funcs{};
         static std::unordered_map<sdk::FRHICommandBase_Old*, uint32_t> cmd_frame_counts{};
@@ -22062,12 +22563,26 @@ struct SceneViewExtensionAnalyzer {
 
         original_funcs[last_command] = last_command->func;
         last_command->func = func_override;
     }
 };
 
+QuadViewNativeRhiQueueSnapshot sample_quadview_native_rhi_queue() {
+    QuadViewNativeRhiQueueSnapshot result{};
+    try {
+        std::unique_lock lock{SceneViewExtensionAnalyzer::vtable_mutex, std::try_to_lock};
+        if (!lock.owns_lock()) { result.busy = true; return result; }
+        result.observed = true;
+        result.tail_owner_records = SceneViewExtensionAnalyzer::quad_native_commands.size();
+        result.tracked_engine_records = SceneViewExtensionAnalyzer::quad_command_engines.size();
+        result.tracked_engine_records+=SceneViewExtensionAnalyzer::quad_drain_commands.size();
+        result.hooked_command_records_all_modes = SceneViewExtensionAnalyzer::original_vtables.size();
+    } catch (...) { result.busy = true; }
+    return result;
+}
+
 template<int N>
 void SceneViewExtensionAnalyzer::FillVtable<N>::fill(std::array<uintptr_t, 50>& table) {
     table[N] = (uintptr_t)&SceneViewExtensionAnalyzer::analysis_dummy_stage1<N>;
     FillVtable<N - 1>::fill(table);
 }
 
@@ -22763,12 +23278,81 @@ sdk::FSceneView* FFakeStereoRenderingHook::sceneview_constructor(sdk::FSceneView
                 "[UE5.8][NativeStereoFix] Capturing passive FSceneView metadata outside UGameViewportClient::Draw");
         }
 
         return result;
     }
 
+    if (vr->is_quadview_renderer_active()) {
+        if (!inside_viewport_client_draw || !vr->is_hmd_active() || init_options == nullptr || !g_hook->m_has_double_precision)
+            return g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view, init_options, a3, a4);
+        update_init_offsets();
+        const auto qv_draw_key=vr->quadview_producer_key();
+        const auto qv_native_targets=vr->quadview_native_target_set(qv_draw_key);
+        auto* qv_init_family=init_options->get_view_family();
+        auto* qv_constructor_rtm=g_hook->get_render_target_manager();
+        // Resolve the family before any ID7 getter; later render callbacks may be withheld.
+        bool qv_family_layout_ready=qv_init_family != nullptr && sdk::FSceneViewFamily::has_offsets();
+        if (qv_init_family && !qv_family_layout_ready) {
+            qv_family_layout_ready=sdk::FSceneViewFamily::update_offsets(qv_init_family,
+                qv_constructor_rtm ? qv_constructor_rtm->get_viewport() : nullptr);
+        }
+        SPDLOG_INFO_EVERY_N_SEC(2,
+            "[QuadViews][Bootstrap] family_layout={} family={:x} native_targets={}",
+            qv_family_layout_ready,reinterpret_cast<uintptr_t>(qv_init_family),bool(qv_native_targets));
+        if (!qv_family_layout_ready) {
+            vr->set_quadview_status("Waiting for validated engine view-family layout");
+            return g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view,init_options,a3,a4);
+        }
+        g_hook->note_scene_view_family_offsets_ready();
+        auto* qv_init_views=qv_init_family->get_views();
+        const bool qv_constructor_main=qv_init_family && qv_constructor_rtm &&
+            qv_init_family->get_render_target()==qv_constructor_rtm->get_view_family_render_target();
+        const auto qv_original_pass=init_options->get_stereo_pass();
+        const int32_t qv_original_view_count=qv_init_views ? qv_init_views->count : 0;
+        const bool qv_native_constructor=qv_native_targets && qv_constructor_main && qv_init_views && qv_original_view_count>=0 &&
+            qv_original_view_count<=4 && qv_init_views->capacity>=qv_original_view_count &&
+            (qv_original_view_count==0 || (qv_init_views->data &&
+                is_readable_process_range(reinterpret_cast<uintptr_t>(qv_init_views->data),sizeof(void*)*qv_original_view_count)));
+        if (qv_native_targets && qv_constructor_main && !qv_native_constructor) {
+            vr->set_quadview_status("Rejected an unvalidated native constructor; incomplete quartet cannot render");
+            return g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view,init_options,a3,a4);
+        }
+        if (qv_native_constructor) {
+            init_options->set_stereo_pass(EStereoscopicPass::eSSP_PRIMARY);
+            qv_init_views->count=0;
+        }
+        utility::ScopeGuard qv_restore_constructor_discipline{[&]() {
+            if (!qv_native_constructor) return;
+            qv_init_views->count=qv_original_view_count;
+            init_options->set_stereo_pass(qv_original_pass);
+        }};
+        auto* family = init_options->get_view_family();
+        auto* state = init_options->get_scene_state();
+        auto* scene = family != nullptr ? family->get_scene_interface() : nullptr;
+        auto* target = family != nullptr ? family->get_render_target() : nullptr;
+        auto* result = g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view, init_options, a3, a4);
+        if (result == nullptr || family == nullptr || state == nullptr || scene == nullptr || target == nullptr ||
+            !result->has_view_family(family) || !is_readable_process_range(reinterpret_cast<uintptr_t>(state), sizeof(void*))) {
+            vr->set_quadview_status("Waiting for four valid engine scene histories"); return result;
+        }
+        auto* options = reinterpret_cast<sdk::FSceneViewInitOptionsUE5*>(init_options);
+        Matrix4x4d projection{}; std::memcpy(&projection, &options->projection_matrix, sizeof(projection));
+        std::array<double,16> values{};
+        for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) values[col*4+row]=projection[col][row];
+        uint64_t hash=1469598103934665603ull; const auto* bytes=reinterpret_cast<const uint8_t*>(values.data());
+        for (size_t i=0; i<sizeof(values); ++i) { hash ^= bytes[i]; hash *= 1099511628211ull; }
+        FIntRect actual_rect{}; std::memcpy(actual_rect.bounds, &options->view_rect, sizeof(actual_rect.bounds));
+        const uevr::quadview::Rect rect{static_cast<uint32_t>(actual_rect.bounds[0]), static_cast<uint32_t>(actual_rect.bounds[1]),
+            static_cast<uint32_t>(actual_rect.bounds[2]-actual_rect.bounds[0]), static_cast<uint32_t>(actual_rect.bounds[3]-actual_rect.bounds[1])};
+        const auto key=vr->quadview_producer_key();
+        if (!vr->quadview_producer().constructed(key, reinterpret_cast<uintptr_t>(family), reinterpret_cast<uintptr_t>(scene),
+            reinterpret_cast<uintptr_t>(target), reinterpret_cast<uintptr_t>(result), reinterpret_cast<uintptr_t>(state), rect, hash))
+            vr->set_quadview_status("Engine view/history did not match its frozen rectangle, projection, family or target");
+        return result;
+    }
+
     if (!inside_viewport_client_draw || !vr->is_hmd_active()) {
         return g_hook->m_sceneview_data.constructor_hook.unsafe_call<sdk::FSceneView*>(view, init_options, a3, a4);
     }
 
     const auto dune_manual_custom_present_pose =
         dune_awakening_is_current_game() &&
@@ -23183,12 +23767,34 @@ sdk::FSceneView* FFakeStereoRenderingHook::sceneview_constructor(sdk::FSceneView
         validate_projection(values);
         hash_projection(values, sizeof(init_options->projection_matrix));
     }
 
     native_projection_valid = native_projection_valid && native_projection_nonzero && native_projection_hash != 0;
 
+    if (vr->is_duoview_renderer_active() && g_hook->is_in_viewport_client_draw()) {
+        const auto family=init_options_view_family;
+        const auto rtm=g_hook->get_render_target_manager();
+        const auto views=family ? family->get_views() : nullptr;
+        const bool main=family && rtm && family->get_render_target()==rtm->get_view_family_render_target();
+        const bool source_pass=init_options_original_stereo_pass==EStereoscopicPass::eSSP_PRIMARY ||
+                               init_options_original_stereo_pass==EStereoscopicPass::eSSP_SECONDARY;
+        if (main && views && source_pass) {
+            const unsigned index=init_options_original_stereo_pass==EStereoscopicPass::eSSP_PRIMARY ? 0u : 1u;
+            const auto key=vr->duoview_producer_key();
+            const auto state=reinterpret_cast<uintptr_t>(init_options_scene_state);
+            bool applied=false;
+            if (index==1 && views->count==1 &&
+                is_readable_process_range(state,sizeof(uintptr_t)) &&
+                vr->duoview_state().can_independent_shading(key,state)) {
+                set_effective_stereo_pass(EStereoscopicPass::eSSP_PRIMARY);
+                restore_init_options_after_constructor=true;
+                applied=get_effective_stereo_pass()==EStereoscopicPass::eSSP_PRIMARY;
+            }
+            vr->duoview_state().scene(key,index,state,applied);
+        }
+    }
     std::optional<uint32_t> views_original_count{};
 
     if (vr->is_native_stereo_fix_enabled() && init_options_stereo_pass == EStereoscopicPass::eSSP_SECONDARY) {
         const auto rtm = g_hook->get_render_target_manager();
         const auto capture_snapshot = rtm != nullptr ? rtm->get_scene_capture_target_snapshot() : nullptr;
         const bool capture_generation_ready =
@@ -24632,12 +25238,13 @@ void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
     const auto dibr_single_view_eligible =
         uevr::vr_compatibility::is_dibr_single_view_eligible(
             dibr_single_view_requested,
             vr->is_dibr_preview_active());
     const auto native_stereo_fix_enabled = vr->is_native_stereo_fix_enabled();
     const bool split_screen_enabled = vr->is_splitscreen_compatibility_enabled();
+    const bool quadview_active = vr->is_quadview_renderer_active();
 
     const auto reset_dibr_single_view_state = [&]() {
         g_hook->m_dibr_single_view_status.store(DIBR_SINGLE_VIEW_DISABLED, std::memory_order_release);
         g_hook->m_dibr_single_view_generation = 0;
         g_hook->m_dibr_single_view_latched_generation = 0;
         g_hook->m_dibr_single_view_family = 0;
@@ -24654,13 +25261,13 @@ void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
             g_hook->m_dibr_single_view_generation != 0))
     {
         reset_dibr_single_view_state();
     }
 
     if (!vr->is_hmd_active() ||
-        (!native_stereo_fix_enabled && !dibr_single_view_eligible && !split_screen_enabled)) {
+        (!quadview_active && !native_stereo_fix_enabled && !dibr_single_view_eligible && !split_screen_enabled)) {
         avowed_native_fix_gate_reset("hmd inactive or native stereo fix disabled");
         if (!native_stereo_fix_enabled) {
             g_hook->invalidate_native_stereo_frame_packet(NativeStereoFixState::Off, nullptr);
             g_hook->m_native_stereo_ue57_capability_failure_generation.store(0, std::memory_order_release);
             std::scoped_lock lock{g_hook->m_sceneview_data.mtx};
             g_hook->m_sceneview_data.native_stereo_views.clear();
@@ -24751,13 +25358,13 @@ void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
         if (!view_families.try_push_back(view_family)) {
             reject_candidate("too many view families");
             return;
         }
     }
 
-    if (strict_candidate_validation) {
+    if (strict_candidate_validation && !quadview_active) {
         for (const auto family : view_families) {
             if (family == nullptr || !is_readable_process_range((uintptr_t)family, sizeof(void*))) {
                 reject_candidate("unreadable view family");
                 return;
             }
             if (sdk::FSceneViewFamily::has_vtable()) {
@@ -24791,12 +25398,101 @@ void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
         {
             call_original();
             return;
         }
     }
 
+    if (quadview_active) {
+        std::array<uevr::quadview::FamilyIdentity,max_sane_view_families> identities{};
+        bool identity_storage_valid=true;
+        for (size_t index=0;index<view_families.size();++index) {
+            const auto family=view_families[index];
+            auto& identity=identities[index];
+            if (!family || !is_readable_process_range(reinterpret_cast<uintptr_t>(family),sizeof(*family))) {
+                identity_storage_valid=false; identity.readable=false; continue;
+            }
+            identity.family=reinterpret_cast<uintptr_t>(family);
+            identity.scene=reinterpret_cast<uintptr_t>(family->get_scene_interface());
+            identity.target=reinterpret_cast<uintptr_t>(family->get_render_target());
+            const auto family_views=family->get_views();
+            if (!family_views || !is_readable_process_range(reinterpret_cast<uintptr_t>(family_views),sizeof(*family_views)) ||
+                family_views->count<0 || family_views->count>16 || family_views->capacity<family_views->count ||
+                (family_views->count!=0 && (!family_views->data || !is_readable_process_range(
+                    reinterpret_cast<uintptr_t>(family_views->data),sizeof(void*)*family_views->count)))) {
+                identity_storage_valid=false; identity.readable=false; continue;
+            }
+            identity.view_count=static_cast<uint8_t>(family_views->count);
+            identity.readable=true;
+            for (size_t view=0;view<identity.view_count;++view) {
+                identity.views[view]=reinterpret_cast<uintptr_t>(family_views->data[view]);
+                if (!family_views->data[view] || !is_readable_process_range(identity.views[view],sizeof(void*)))
+                    identity.readable=false;
+            }
+            if (!identity.readable) identity_storage_valid=false;
+        }
+        const std::span<const uevr::quadview::FamilyIdentity> candidates{identities.data(),view_families.size()};
+        auto& native_context=g_hook->quadview_native_build_context;
+        uevr::quadview::FamilyRoute route{};
+        if (native_context.active) {
+            if (native_context.current_slot>=4) {
+                vr->set_quadview_status("Rejected an invalid nested native source slot"); return;
+            }
+            uevr::quadview::FamilyIdentity expected_singleton{};
+            expected_singleton.family=native_context.family;
+            expected_singleton.scene=native_context.scene;
+            expected_singleton.target=reinterpret_cast<uintptr_t>(native_context.render_targets[native_context.current_slot]);
+            expected_singleton.views[0]=reinterpret_cast<uintptr_t>(native_context.original_views[native_context.current_slot]);
+            expected_singleton.view_count=1; expected_singleton.readable=true;
+            route=uevr::quadview::route_current_main_family(candidates,expected_singleton);
+        } else {
+            const auto key=vr->quadview_producer_key();
+            const auto snapshot=vr->quadview_producer().snapshot(key);
+            if (snapshot && snapshot->construction_complete() && snapshot->family && snapshot->scene && snapshot->target) {
+                uevr::quadview::FrozenFamilyIdentity expected{};
+                expected.family=snapshot->family; expected.scene=snapshot->scene; expected.target=snapshot->target;
+                for (size_t view=0;view<4;++view) expected.views[view]=snapshot->views[view].view;
+                route=uevr::quadview::route_main_family(candidates,expected);
+            } else {
+                uevr::quadview::PartialFamilyIdentity partial{};
+                partial.target=snapshot ? snapshot->target : reinterpret_cast<uintptr_t>(
+                    rtm ? rtm->get_view_family_render_target() : nullptr);
+                if (snapshot) {
+                    partial.family=snapshot->family; partial.scene=snapshot->scene;
+                    for (size_t view=0;view<snapshot->views.size();++view) if (snapshot->views[view].view)
+                        partial.views[partial.view_count++]=snapshot->views[view].view;
+                }
+                const auto partial_route=uevr::quadview::classify_partial_main_family(candidates,partial);
+                if (partial_route==uevr::quadview::PartialFamilyRouteStatus::auxiliary_only) {
+                    call_original(); return;
+                }
+                const auto drain_route=uevr::quadview::route_drain_family(candidates,partial);
+                if (identity_storage_valid && drain_route) {
+                    vr->set_quadview_status("Incomplete native snapshot: draining original engine family without publication");
+                    SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][Recovery] drain-only generation={} serial={} views={}",
+                        key.generation,key.draw_serial,identities[drain_route.index].view_count);
+                    call_original(); return;
+                }
+                vr->set_quadview_status("Incomplete main family lacks an authenticated drain identity");
+                return;
+            }
+        }
+        if (!identity_storage_valid || route.status==uevr::quadview::FamilyRouteStatus::malformed_batch) {
+            vr->set_quadview_status("Native view-family batch contains an unreadable family or view array"); return;
+        }
+        if (route.status==uevr::quadview::FamilyRouteStatus::auxiliary_only) {
+            call_original(); return;
+        }
+        if (route.status!=uevr::quadview::FamilyRouteStatus::main_family) {
+            vr->set_quadview_status(route.status==uevr::quadview::FamilyRouteStatus::ambiguous_main
+                ? "Native main family is ambiguous in the TArrayView batch"
+                : "Native main family does not match its frozen target, scene, family and view identity");
+            return;
+        }
+        view_family=view_families[route.index];
+    }
+
     if (view_family == nullptr) {
         call_original();
         return;
     }
 
     using SceneViewsArrayPtr = decltype(view_family->get_views());
@@ -25183,12 +25879,26 @@ void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
             call_original();
             return;
         }
     }
 
     if (native_stereo_fix_enabled) {
+        if (vr->is_duoview_renderer_active()) {
+            bool duo_main_target_present=false;
+            const auto expected=rtm->get_view_family_render_target();
+            for (const auto family:view_families) {
+                if (expected && family && family->get_render_target()==expected) {
+                    duo_main_target_present=true;
+                    break;
+                }
+            }
+            if (!duo_main_target_present) {
+                call_original();
+                return;
+            }
+        }
         if (g_hook->m_native_stereo_localplayer_bootstrap_failed.load(std::memory_order_acquire)) {
             g_hook->invalidate_native_stereo_frame_packet(
                 NativeStereoFixState::FailedClosed,
                 "source-validated LocalPlayer ViewStates bootstrap failed");
             call_original();
             return;
@@ -25616,12 +26326,127 @@ void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
         }
     }
 
     auto& views = *views_ptr;
     const auto prev_count = views.count;
 
+    if (quadview_active) {
+        auto& native_context=g_hook->quadview_native_build_context;
+        if (native_context.active) { call_original(); return; }
+        auto* qv_rtm=rtm;
+        const auto qv_key=vr->quadview_producer_key();
+        const auto qv_target_set=vr->quadview_native_target_set(qv_key);
+        const auto qv_snapshot=vr->quadview_producer().snapshot(qv_key);
+        auto* qv_scene=view_family->get_scene_interface();
+        const auto qv_expected_target=qv_rtm ? qv_rtm->get_view_family_render_target() : nullptr;
+        if (!qv_target_set) {
+            // B18: keep engine/RHI bootstrap moving without four atlas rasters.
+            // This family has no native target provenance and cannot publish.
+            uevr::quadview::BootstrapViewCount bootstrap_views{views.count};
+            call_original();
+            return;
+        }
+        bool qv_snapshot_views_match=qv_snapshot && qv_snapshot->views.size()==4 &&
+            views.count==4 && views.capacity>=4 && views.data &&
+            is_readable_process_range(reinterpret_cast<uintptr_t>(views.data),sizeof(void*)*4);
+        if (qv_snapshot_views_match) for(size_t i=0;i!=4;++i)
+            qv_snapshot_views_match=qv_snapshot_views_match &&
+                qv_snapshot->views[i].view==reinterpret_cast<uintptr_t>(views.data[i]);
+        const bool qv_snapshot_identity_match=qv_snapshot_views_match &&
+            qv_snapshot->family==reinterpret_cast<uintptr_t>(view_family) &&
+            qv_snapshot->scene==reinterpret_cast<uintptr_t>(qv_scene) &&
+            qv_snapshot->target==reinterpret_cast<uintptr_t>(qv_expected_target);
+        const bool qv_family_valid=qv_target_set && qv_target_set->complete() &&
+            qv_rtm && qv_rtm->quadview_native_targets_live(*qv_target_set) && qv_snapshot && qv_snapshot->construction_complete() &&
+            qv_snapshot_identity_match &&
+            qv_target_set->extents==uevr::quadview::triview_source_extents(qv_snapshot->layout) &&
+            views.count==4 && views.capacity>=4 && views.data &&
+            is_readable_process_range(reinterpret_cast<uintptr_t>(views.data),sizeof(void*)*4) &&
+            sdk::FSceneViewFamily::validate_views(view_family,views_ptr,4) && qv_scene &&
+            view_family->get_render_target()==qv_expected_target && qv_expected_target;
+        if (!qv_family_valid) {
+            vr->set_quadview_status("Frozen native target set or original four-view source family is no longer valid");
+            SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][NativeDispatch] rejected draw={} snapshot={} constructed={} family_registered={} views={} capacity={} target_match={}",
+                qv_key.draw_serial,bool(qv_snapshot),qv_snapshot ? qv_snapshot->construction_complete() : false,
+                qv_snapshot ? qv_snapshot->family_valid : false,views.count,views.capacity,
+                view_family->get_render_target()==qv_expected_target);
+            return;
+        }
+        FFakeStereoRenderingHook::QuadViewNativeBuildContext previous_context=std::move(native_context);
+        native_context={}; native_context.active=true; native_context.current_slot=0;
+        native_context.original_count=4; native_context.family=reinterpret_cast<uintptr_t>(view_family);
+        native_context.scene=reinterpret_cast<uintptr_t>(qv_scene); native_context.original_target=qv_expected_target;
+        native_context.target_set=qv_target_set; native_context.target_set_generation=qv_target_set->generation;
+        for (size_t i=0;i!=4;++i) {
+            native_context.original_views[i]=views.data[i];
+            native_context.render_targets[i]=qv_target_set->render_targets[i];
+            native_context.target_owners[i]=qv_target_set->target_owners[i];
+            native_context.native_sources[i]=qv_target_set->native_sources[i];
+        }
+        utility::ScopeGuard restore_qv_dispatch{[&]() {
+            native_context=std::move(previous_context);
+        }};
+        const auto qv_dispatch_result=uevr::quadview::dispatch_main_views(
+            views.data,views.capacity,views.count,*view_family,native_context.original_views,
+            native_context.render_targets,
+            [](sdk::FSceneViewFamily& family) { return family.get_render_target(); },
+            [](sdk::FSceneViewFamily& family,auto* target) { family.set_render_target(target); },
+            [&](size_t slot) {
+                if (!qv_rtm->quadview_native_targets_live(*qv_target_set)) {
+                    vr->set_quadview_status("Native source ownership changed; dispatch stopped before virtual call");
+                    return false;
+                }
+                if (slot!=0) reinterpret_cast<sdk::FScene*>(qv_scene)->decrement_frame_count();
+                native_context.current_slot=static_cast<uint8_t>(slot);
+                return true;
+            },
+            [&]() { call_original(); },
+            [&]() {
+                if (uses_tarrayview) {
+                    TArrayViewViewFamily one_family{&view_family,1};
+                    g_hook->m_render_module_begin_render_viewfamily_hook.unsafe_call<void>(render_module,canvas,
+                        reinterpret_cast<sdk::FSceneViewFamily*>(&one_family));
+                } else {
+                    g_hook->m_render_module_begin_render_viewfamily_hook.unsafe_call<void>(render_module,canvas,view_family);
+                }
+            },
+            [&](size_t slot) {
+                return views.count==1 && views.data[0]==native_context.original_views[slot] &&
+                    native_context.source_registered && (native_context.roles_bound & (1u<<slot)) &&
+                    view_family->get_render_target()==native_context.render_targets[slot];
+            },qv_snapshot && qv_snapshot->layout.shared_context ? uint8_t(0x02) : uint8_t(0));
+        if (!qv_dispatch_result) {
+            vr->set_quadview_status("Native four-view dispatch failed validation; original family was restored");
+            return;
+        }
+        SPDLOG_INFO_EVERY_N_SEC(2,"[QuadViews][NativeRole][GT] serial={} canonical={} roles={},{},{},{} mask={}",
+            qv_key.draw_serial,native_context.engine_frame,native_context.role_frames[0],native_context.role_frames[1],
+            native_context.role_frames[2],native_context.role_frames[3],native_context.roles_bound);
+        vr->set_quadview_status("Four isolated native source renders completed; waiting for exact quartet RHI tails");
+        SPDLOG_INFO_EVERY_N_SEC(2,"[QuadViews][NativeDispatch] rendered four sources draw={} target_set={} registered={} frame={}",
+            qv_key.draw_serial,native_context.target_set_generation,native_context.source_registered,native_context.engine_frame);
+        return;
+    }
+
+    // Observe Native Fix's original two-view main family before the fix
+    // splits it into one-view primary and secondary render callbacks.
+    const auto duo_target = view_family->get_render_target();
+    const auto duo_main_target = rtm ? rtm->get_view_family_render_target() : nullptr;
+    const bool duo_views_readable = vr->is_duoview_renderer_active() && prev_count == 2 &&
+        views.capacity >= 2 && views.data != nullptr &&
+        is_readable_process_range(reinterpret_cast<uintptr_t>(views.data), sizeof(void*) * 2);
+    const bool duo_original_main_pair = duo_views_readable &&
+        duo_target != nullptr && duo_target == duo_main_target &&
+        view_family->get_scene_interface() != nullptr && views.data[0] != nullptr &&
+        views.data[1] != nullptr && views.data[0] != views.data[1];
+    if (duo_original_main_pair && vr->duoview_note_main_family(0, true, prev_count)) {
+        const auto source_frame = vr->duoview_mono_source_frame();
+        if (source_frame && vr->get_openxr_runtime())
+            vr->get_openxr_runtime()->note_mono_main_family(*source_frame, true);
+    }
+
     if (auto view_family_target = view_family->get_render_target(); view_family_target != nullptr) {
         g_hook->try_adopt_scene_viewport_render_target(
             reinterpret_cast<sdk::FViewport*>(view_family_target),
             "BeginRenderingViewFamily RenderTarget");
     }
 
@@ -25946,27 +26771,51 @@ void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
         if (!stalker_experiment || offset == 0 || offset >= 0x1000 ||
             !is_readable_process_range(reinterpret_cast<uintptr_t>(view_family) + offset, sizeof(uint32_t))) { return std::nullopt; }
         uint32_t frame{};
         std::memcpy(&frame, reinterpret_cast<const uint8_t*>(view_family) + offset, sizeof(frame));
         return frame;
     };
-    const auto publish_native_packet = [&]() {
+    const auto duo_packet_frame = vr->is_duoview_renderer_active()
+        ? vr->duoview_state().snapshot(vr->duoview_producer_key())
+        : std::optional<uevr::duoview::ViewFrame>{};
+    const auto duo_packet_pose = duo_packet_frame && duo_packet_frame->mono_source_frame &&
+        uevr::duoview::native_frame_binding(*duo_packet_frame) && vr->get_openxr_runtime()
+        ? vr->get_openxr_runtime()->capture_duoview_pose(*duo_packet_frame->mono_source_frame)
+        : std::optional<runtimes::OpenXR::PipelineState>{};
+    const auto make_native_packet = [&]() -> std::shared_ptr<const NativeStereoFramePacket> {
         auto packet = std::make_shared<NativeStereoFramePacket>();
         packet->capture = native_capture_snapshot;
         packet->family = view_family;
         packet->left_view = native_left_view;
         packet->right_view = native_right_view;
         packet->left_state = native_left_metadata.state;
         packet->right_state = native_right_metadata.state;
         packet->main_target = original_target;
         packet->scene = view_family_scene;
         packet->serial = g_hook->m_native_stereo_packet_serial.fetch_add(1, std::memory_order_acq_rel) + 1;
         packet->capture_generation = native_capture_snapshot->generation;
         packet->d3d11_snapshot_transaction = daysgone_snapshot_transaction;
-        packet->engine_frame = g_frame_count;
-        packet->render_frame = vr->m_render_frame_count;
+        if (!duo_packet_frame) {
+            packet->engine_frame = g_frame_count;
+            packet->render_frame = vr->m_render_frame_count;
+        }
+        if (duo_packet_frame && duo_packet_pose) {
+            packet->duoview_frame=std::make_shared<const uevr::duoview::ViewFrame>(*duo_packet_frame);
+            packet->duoview_mono_source_frame=*duo_packet_frame->mono_source_frame;
+            packet->duoview_mono_source_valid=true;
+            std::copy_n(duo_packet_pose->stage_views.begin(),2,packet->duoview_views.begin());
+            packet->duoview_frame_state=duo_packet_pose->frame_state;
+            packet->duoview_view_location=duo_packet_pose->view_space_location;
+            packet->duoview_pose_valid=true;
+            packet->duoview_secondary_target=rtfrt;
+            if (const auto primary=rtm->get_render_target()) {
+                if (const auto native=static_cast<IUnknown*>(primary->get_native_resource())) {
+                    native->QueryInterface(IID_PPV_ARGS(&packet->duoview_primary_resource));
+                }
+            }
+        }
         packet->player_index = native_left_metadata.player_index;
         packet->left_pass = native_left_metadata.original_stereo_pass;
         packet->right_pass = native_right_metadata.original_stereo_pass;
         if (stalker_primary_frame && stalker_secondary_frame) {
             packet->stalker_key = uevr::stalker2_native::make_key(stalker_epoch,
                 *stalker_primary_frame, *stalker_secondary_frame, g_hook->get_frame_delay_compensation());
@@ -25974,13 +26823,20 @@ void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
             packet->stalker_pose_valid = stalker_pose_valid;
             packet->stalker_pose_frame = stalker_pose_frame;
         }
         if (const auto token = g_hook->m_native_frame_diagnostics.control()) {
             packet->diagnostic_clock = g_hook->m_native_frame_diagnostics.clock(token);
         }
-        g_hook->publish_native_stereo_frame_packet(std::move(packet));
+        return packet;
+    };
+    const auto duo_build_packet = duo_packet_frame && duo_packet_pose ? make_native_packet() : nullptr;
+    const auto previous_duo_build = duoview_build_packet;
+    duoview_build_packet = duo_build_packet;
+    utility::ScopeGuard restore_duo_build{[&] { duoview_build_packet = previous_duo_build; }};
+    const auto publish_native_packet = [&]() {
+        g_hook->publish_native_stereo_frame_packet(duo_build_packet ? duo_build_packet : make_native_packet());
         if (daysgone_snapshot_transaction != 0) {
             daysgone_snapshot_packet_published = true;
         }
     };
 
     if (use_ue58_linked_singleton_transaction) {
@@ -26795,18 +27651,235 @@ void FFakeStereoRenderingHook::begin_render_viewfamily(ISceneViewExtension* exte
         return;
     }
 
     const auto frame_count =
         *(uint32_t*)((uintptr_t)&view_family + SceneViewExtensionAnalyzer::frame_count_offset);
     auto views_ptr = view_family.get_views();
+    [&]() {
+        auto& native_context=g_hook->quadview_native_build_context;
+        const bool native_callback=native_context.active &&
+            native_context.family==reinterpret_cast<uintptr_t>(&view_family);
+        if (native_callback && native_context.source_registered) return;
+        auto* const native_views=view_family.get_views();
+        const auto native_saved_count=native_views ? native_views->count : 0;
+        auto* const native_saved_target=view_family.get_render_target();
+        std::array<sdk::FSceneView*,4> native_saved_views{};
+        if (native_callback) {
+            if (!native_views || !native_views->data || native_views->capacity<4 ||
+                native_context.current_slot!=0) return;
+            for(size_t i=0;i!=4;++i) {
+                native_saved_views[i]=native_views->data[i];
+                native_views->data[i]=native_context.original_views[i];
+            }
+            native_views->count=4;
+            view_family.set_render_target(native_context.original_target);
+        }
+        utility::ScopeGuard restore_native_registration{[&]() {
+            if (!native_callback) return;
+            for(size_t i=0;i!=4;++i) native_views->data[i]=native_saved_views[i];
+            native_views->count=native_saved_count;
+            view_family.set_render_target(native_saved_target);
+        }};
+    if (vr->is_quadview_layout_active()) {
+        auto* qv_rtm=g_hook->get_render_target_manager();
+        auto* qv_target=view_family.get_render_target();
+        auto* qv_scene=view_family.get_scene_interface();
+        auto* qv_expected_target=qv_rtm != nullptr ? qv_rtm->get_view_family_render_target() : nullptr;
+        const auto qv_key=vr->quadview_producer_key();
+        std::array<uintptr_t,4> qv_view_ids{};
+        const bool qv_family_readable=views_ptr && views_ptr->count==4 &&
+            views_ptr->capacity>=4 && views_ptr->data &&
+            is_readable_process_range(reinterpret_cast<uintptr_t>(views_ptr->data),sizeof(void*)*4);
+        if (qv_family_readable) {
+            for (size_t i=0; i!=4; ++i) qv_view_ids[i]=reinterpret_cast<uintptr_t>(views_ptr->data[i]);
+        }
+        std::optional<FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket> qv_engine_ticket;
+        const bool qv_engine_family_readable=views_ptr && views_ptr->count>0 && views_ptr->count<=4 &&
+            views_ptr->capacity>=views_ptr->count && views_ptr->data &&
+            is_readable_process_range(reinterpret_cast<uintptr_t>(views_ptr->data),sizeof(void*)*views_ptr->count);
+        bool qv_engine_views_valid=qv_engine_family_readable;
+        if (qv_engine_views_valid) for(int32_t i=0;i<views_ptr->count;++i) {
+            if (!views_ptr->data[i]) qv_engine_views_valid=false;
+            for(int32_t j=0;j<i;++j) if(views_ptr->data[i]==views_ptr->data[j]) qv_engine_views_valid=false;
+        }
+        if (qv_engine_views_valid && qv_target && qv_target==qv_expected_target && qv_scene) {
+            FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket ticket{qv_key.generation,qv_key.draw_serial,
+                frame_count,reinterpret_cast<uintptr_t>(&view_family),reinterpret_cast<uintptr_t>(qv_target),
+                reinterpret_cast<uintptr_t>(qv_scene)};
+            const auto registration=g_hook->quadview_delivery.register_engine_family_detailed(ticket);
+            { uevr::quadview::HookTraceRecord r{};r.event="GT_REGISTER";r.reason="engine_registration";
+              r.generation=ticket.generation;r.serial=ticket.serial;r.frame=ticket.engine_frame;r.mode=7;
+              r.family=ticket.family;r.target=ticket.target;r.scene=ticket.scene;r.result=static_cast<int>(registration.status);
+              r.pending=registration.pending;uevr::quadview::emit_hook_trace(18,r); }
+            using Registration=FFakeStereoRenderingHook::QuadViewDelivery::EngineRegistrationStatus;
+            if (registration.status==Registration::accepted || registration.status==Registration::duplicate_same_owner)
+                qv_engine_ticket=ticket;
+            else {
+                vr->set_quadview_status("Engine render-family registration rejected; inspect EngineRegistration diagnostics");
+                SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][EngineRegistration] reason={} generation={} serial={} frame={} family={:x} target={:x} scene={:x} pending={} capacity={} oldest={}",
+                    static_cast<unsigned>(registration.status),ticket.generation,ticket.serial,ticket.engine_frame,
+                    ticket.family,ticket.target,ticket.scene,registration.pending,registration.capacity,registration.oldest_serial);
+            }
+        }
+        const auto qv_snapshot=vr->quadview_producer().snapshot(qv_key);
+        const auto qv_pose=vr->quadview_frozen_pose(qv_key);
+        // The source must be published HERE, before a renderer-owned FViewInfo
+        // copy and before the RT callback has any opportunity to run.
+        const bool qv_native_ready=bool(vr->quadview_native_target_set(qv_key));
+        const auto qv_valid=qv_family_readable && qv_engine_ticket && qv_snapshot &&
+            qv_native_ready && native_callback &&
+            qv_target && qv_target==qv_expected_target && qv_scene && qv_pose &&
+            qv_pose->stage_views.size()==2 && qv_pose->frame_state.predictedDisplayTime>0 &&
+            qv_pose->frame_state.shouldRender==XR_TRUE;
+        if (qv_valid) {
+            auto* qv_source_rhi=qv_rtm->get_render_target();
+            auto* qv_native=qv_source_rhi ? static_cast<ID3D12Resource*>(qv_source_rhi->get_native_resource()) : nullptr;
+            if (qv_native) {
+                const auto desc=qv_native->GetDesc();
+                const bool atlas_valid=desc.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
+                    desc.Width==qv_snapshot->layout.atlas_width && desc.Height==qv_snapshot->layout.atlas_height &&
+                    desc.DepthOrArraySize==1 && desc.SampleDesc.Count==1 &&
+                    (desc.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE)==0;
+                if (atlas_valid && vr->quadview_producer().main_family(qv_key,frame_count,
+                        reinterpret_cast<uintptr_t>(&view_family),reinterpret_cast<uintptr_t>(qv_scene),
+                        reinterpret_cast<uintptr_t>(qv_target),qv_view_ids)) {
+                    auto qv_packet=std::make_shared<FFakeStereoRenderingHook::QuadViewSourcePacket>();
+                    qv_packet->producer=vr->quadview_producer().frozen(qv_key);
+                    qv_packet->atlas=qv_native;
+                    if (native_callback) {
+                        qv_packet->native_sources=native_context.native_sources;
+                        qv_packet->native_target_owners=native_context.target_owners;
+                        qv_packet->native_target_set_generation=native_context.target_set_generation;
+                        qv_packet->native_target_set_owner=native_context.target_set;
+                    }
+                    qv_packet->pose=*qv_pose;
+                    qv_packet->source_state=!native_callback && is_ue_5_5_runtime()
+                        ? (D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE)
+                        : D3D12_RESOURCE_STATE_RENDER_TARGET;
+                    qv_packet->runtime_frame=static_cast<uint64_t>(qv_pose->frame_state.predictedDisplayTime);
+                    qv_packet->serial=qv_key.draw_serial;
+                    if (qv_packet->producer) {
+                        FFakeStereoRenderingHook::QuadViewDelivery::Source qv_source{
+                            qv_packet,qv_key.generation,qv_key.draw_serial,frame_count,qv_packet->runtime_frame,
+                            reinterpret_cast<uintptr_t>(&view_family),reinterpret_cast<uintptr_t>(qv_target),
+                            reinterpret_cast<uintptr_t>(qv_scene),qv_view_ids
+                        };
+                        // The published source is frame-bound atomically, not
+                        // registered first and bound after the RT thread may run.
+                        bool native_owned=true;
+                        if (native_callback) {
+                            std::array<uintptr_t,4> native_targets{};
+                            for (size_t i=0;i!=4;++i) native_targets[i]=reinterpret_cast<uintptr_t>(native_context.render_targets[i]);
+                            native_owned=g_hook->quadview_native_delivery.bind(qv_source,*qv_engine_ticket,
+                                native_context.target_set_generation,native_targets,true,
+                qv_snapshot && qv_snapshot->layout.shared_context ? uint8_t(0x0d) : uint8_t(0x0f));
+                            native_context.packet=qv_packet;
+                            native_context.engine_frame=frame_count;
+                            native_context.source_registered=native_owned;
+                        }
+                        const bool registered=native_owned && g_hook->quadview_delivery.register_bound(qv_source);
+                        if (native_callback && native_owned && !registered)
+                            vr->set_quadview_status("Native quartet will drain without publishing: source ledger is full");
+                        if (registered) {
+                            vr->set_quadview_status("Four-view source registered before the renderer copies this family");
+                            SPDLOG_INFO_EVERY_N_SEC(2,"[QuadViews][GTProducer] BOUND serial={} frame={} family={:x} scene={:x} target={:x} views={:x},{:x},{:x},{:x} pose={}",
+                                qv_key.draw_serial,frame_count,reinterpret_cast<uintptr_t>(&view_family),
+                                reinterpret_cast<uintptr_t>(qv_scene),reinterpret_cast<uintptr_t>(qv_target),
+                                qv_view_ids[0],qv_view_ids[1],qv_view_ids[2],qv_view_ids[3],qv_packet->runtime_frame);
+                        } else {
+                            vr->set_quadview_status("Failed to register a valid game-thread source before renderer handoff");
+                            SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][GTProducer] BIND_FAIL serial={} frame={}",
+                                qv_key.draw_serial,frame_count);
+                        }
+                    }
+                } else {
+                    vr->set_quadview_status("Four-view engine scene roles or original source atlas are unvalidated");
+                    SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][GTProducer] main-family/atlas rejection serial={} frame={} atlas_valid={} views={:x},{:x},{:x},{:x}",
+                        qv_key.draw_serial,frame_count,atlas_valid,qv_view_ids[0],qv_view_ids[1],qv_view_ids[2],qv_view_ids[3]);
+                }
+            } else {
+                vr->set_quadview_status("Original Unreal main scene has no native D3D12 atlas resource");
+            }
+        } else {
+            vr->set_quadview_status("Waiting for complete four-view GT source and synchronized stereo pose");
+            const char* qv_reason=!qv_family_readable ? "view_family_unreadable" : !qv_engine_ticket ? "engine_ticket_rejected" :
+                !qv_snapshot ? "producer_snapshot_missing" : !qv_target || qv_target!=qv_expected_target ? "target_unavailable_or_mismatch" :
+                !qv_scene ? "scene_unavailable" : !qv_pose ? "coherent_pose_unavailable" :
+                qv_pose->stage_views.size()!=2 ? "pose_eye_count_invalid" :
+                qv_pose->frame_state.predictedDisplayTime<=0 ? "pose_display_time_invalid" : "pose_should_not_render";
+            SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][GTProducer][per-frame-throttled] NOT_READY reason={} serial={} frame={} readable={} ticket={} snap={} pose={} eyes={} target={:x} expected={:x} scene={:x}",
+                qv_reason,qv_key.draw_serial,frame_count,qv_family_readable,static_cast<bool>(qv_engine_ticket),
+                static_cast<bool>(qv_snapshot),static_cast<bool>(qv_pose),
+                qv_pose ? qv_pose->stage_views.size() : 0,
+                reinterpret_cast<uintptr_t>(qv_target),reinterpret_cast<uintptr_t>(qv_expected_target),reinterpret_cast<uintptr_t>(qv_scene));
+        }
+        if (native_callback && !native_context.source_registered && qv_engine_ticket && qv_snapshot) {
+            auto discard_packet=std::make_shared<FFakeStereoRenderingHook::QuadViewSourcePacket>();
+            discard_packet->native_sources=native_context.native_sources;
+            discard_packet->native_target_owners=native_context.target_owners;
+            discard_packet->native_target_set_owner=native_context.target_set;
+            discard_packet->native_target_set_generation=native_context.target_set_generation;
+            discard_packet->serial=qv_key.draw_serial;
+            FFakeStereoRenderingHook::QuadViewDelivery::Source discard_source{
+                discard_packet,qv_key.generation,qv_key.draw_serial,frame_count,0,
+                reinterpret_cast<uintptr_t>(&view_family),reinterpret_cast<uintptr_t>(qv_target),
+                reinterpret_cast<uintptr_t>(qv_scene),qv_view_ids};
+            std::array<uintptr_t,4> native_targets{};
+            for(size_t i=0;i!=4;++i) native_targets[i]=reinterpret_cast<uintptr_t>(native_context.render_targets[i]);
+            native_context.source_registered=g_hook->quadview_native_delivery.bind(discard_source,*qv_engine_ticket,
+                native_context.target_set_generation,native_targets,true,
+                qv_snapshot && qv_snapshot->layout.shared_context ? uint8_t(0x0d) : uint8_t(0x0f));
+            native_context.packet=discard_packet;
+            native_context.engine_frame=frame_count;
+            vr->set_quadview_status("Native quartet has no valid pose/source; draining four engine owners without publication");
+        }
+    }
+    }();
+    // This runs for EVERY singleton, including callbacks whose quartet was
+    // already created by role zero. The callback's own frame is authoritative.
+    {
+        auto& native_context=g_hook->quadview_native_build_context;
+        if (native_context.active && native_context.source_registered && native_context.packet &&
+            native_context.family==reinterpret_cast<uintptr_t>(&view_family) && native_context.current_slot<4) {
+            const auto slot=native_context.current_slot;
+            const bool bound=g_hook->quadview_native_delivery.bind_role(vr->mono_generation(),
+                native_context.packet->serial,slot,frame_count,
+                reinterpret_cast<uintptr_t>(view_family.get_render_target()),
+                reinterpret_cast<uintptr_t>(view_family.get_scene_interface()));
+            { uevr::quadview::HookTraceRecord r{};r.event="ROLE_GT_BOUND";r.reason=bound?"accepted":"rejected";
+              r.generation=vr->mono_generation();r.serial=native_context.packet->serial;r.frame=frame_count;r.role=slot;r.mode=7;
+              r.family=reinterpret_cast<uintptr_t>(&view_family);r.target=reinterpret_cast<uintptr_t>(view_family.get_render_target());
+              r.scene=reinterpret_cast<uintptr_t>(view_family.get_scene_interface());r.canonical_frame=native_context.engine_frame;
+              uevr::quadview::emit_hook_trace(19,r); }
+            if (bound) {
+                native_context.roles_bound|=uint8_t(1u<<slot);
+                native_context.role_frames[slot]=frame_count;
+            } else {
+                vr->set_quadview_status("Native singleton GT frame identity rejected; publication held closed");
+                SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][NativeRole][GT] rejected serial={} slot={} frame={}",
+                    native_context.packet->serial,slot,frame_count);
+            }
+        }
+    }
+    if (const auto packet = duoview_build_packet; packet && packet->duoview_frame) {
+        const auto target = view_family.get_render_target();
+        const auto role = target == packet->main_target ? uevr::duoview::SourceRole::primary :
+            target == packet->duoview_secondary_target ? uevr::duoview::SourceRole::secondary :
+            uevr::duoview::SourceRole::auxiliary;
+        if (role != uevr::duoview::SourceRole::auxiliary && !g_hook->duoview_delivery.family(
+                {packet, packet->duoview_frame->config.key.generation, reinterpret_cast<uintptr_t>(target),
+                 reinterpret_cast<uintptr_t>(view_family.get_scene_interface()), frame_count, role}, GetCurrentThreadId())) {
+            SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView][Delivery] Family registration conflict serial={} frame={}", packet->serial, frame_count);
+        }
+    }
 
     auto runtime = vr->get_runtime();
     runtime->internal_frame_count = frame_count;
     runtime->on_pre_render_game_thread(frame_count);
 
-    if (vr->mono_frame_gate_required() && runtime->is_openxr()) {
+    if (!vr->is_duoview_renderer_active() && vr->mono_frame_gate_required() && runtime->is_openxr()) {
         const bool main_family = view_family.get_render_target() != nullptr && view_family.get_render_target() ==
             reinterpret_cast<sdk::FRenderTarget*>(g_hook->get_render_target_manager()->get_viewport());
         vr->get_openxr_runtime()->note_mono_main_family(frame_count,
             main_family && views_ptr != nullptr && views_ptr->count > 0 &&
             (!vr->is_using_mono() || views_ptr->count == 1));
     }
@@ -27043,15 +28116,18 @@ void FFakeStereoRenderingHook::begin_render_viewfamily(ISceneViewExtension* exte
     static uint32_t resolver_attempts = 0;
     static uint32_t calls_until_retry = 0;
     static uint32_t callbacks_since_install = 0;
 
     // NASCAR uses its validated heap-object renderer adapter. Do not repeatedly
     // attempt an image hook that its code-preserving protection rejects.
-    const bool needs_begin_rendering_viewfamilies_hook = uevr::nascar::needs_generic_renderer_hook(
-        uevr::nascar::is_target(), vr->is_native_stereo_fix_enabled(),
-        vr->is_dibr_single_view_requested(), vr->is_splitscreen_compatibility_enabled());
+    const bool needs_begin_rendering_viewfamilies_hook = vr->is_quadview_supported_title() ||
+        vr->is_quadview_renderer_active() ||
+        (vr->is_quadview_mode_selected() && !vr->is_mono_transition_pending()) ||
+        uevr::nascar::needs_generic_renderer_hook(
+            uevr::nascar::is_target(), vr->is_native_stereo_fix_enabled(),
+            vr->is_dibr_single_view_requested(), vr->is_splitscreen_compatibility_enabled());
 
     if (begin_rendering_view_family_real_fn != nullptr &&
         needs_begin_rendering_viewfamilies_hook &&
         !g_hook->m_render_module_begin_render_viewfamily_observed.load(std::memory_order_acquire))
     {
         ++callbacks_since_install;
@@ -27368,13 +28444,17 @@ FFakeStereoRenderingHook::get_native_stereo_frame_packet_for_submit(int32_t rend
     const auto vr = VR::get();
     if (vr == nullptr || !vr->is_native_stereo_fix_enabled()) {
         record_outcome(frame_diag::Reason::feature_off);
         return nullptr;
     }
 
-    const auto packet = m_native_stereo_frame_packet.load(std::memory_order_acquire);
+    const bool duo_transaction = vr->is_duoview_renderer_active();
+    const auto packet = duo_transaction
+        ? duoview_delivery.select(vr->mono_generation(), GetCurrentThreadId())
+        : m_native_stereo_frame_packet.load(std::memory_order_acquire);
+    if (duo_transaction && !packet) dump_duoview_delivery();
     if (packet == nullptr || packet->capture == nullptr) {
         record_outcome(frame_diag::Reason::no_packet);
         return nullptr;
     }
 
     if (observation) {
@@ -27383,22 +28463,22 @@ FFakeStereoRenderingHook::get_native_stereo_frame_packet_for_submit(int32_t rend
         ticket.consumer_clock = observation->consumer_clock;
         ticket.packet_serial = packet->serial;
         if (diagnostic_ticket != nullptr) { *diagnostic_ticket = ticket; }
     }
 
     const auto render_frame_delta =
-        static_cast<int64_t>(render_frame) - static_cast<int64_t>(packet->render_frame);
+        duo_transaction ? 0 : static_cast<int64_t>(render_frame) - static_cast<int64_t>(packet->render_frame);
     const auto engine_frame_delta =
-        static_cast<uint32_t>(g_frame_count - packet->engine_frame);
+        duo_transaction ? 0u : static_cast<uint32_t>(g_frame_count - packet->engine_frame);
     const bool exact_render_frame = render_frame_delta == 0;
     const bool same_engine_frame_present_grace =
-        packet->engine_frame == g_frame_count;
+        !duo_transaction && packet->engine_frame == g_frame_count;
     const bool next_engine_frame_handoff =
         render_frame_delta == 1 && engine_frame_delta == 1;
     if (observation) {
-        observation->window_observed = true;
+        observation->window_observed = !duo_transaction;
         observation->render_delta = render_frame_delta;
         observation->engine_delta = engine_frame_delta;
         observation->legacy_same_engine = same_engine_frame_present_grace;
     }
 
     // A game can issue several Presents without another engine draw while the
@@ -27406,13 +28486,13 @@ FFakeStereoRenderingHook::get_native_stereo_frame_packet_for_submit(int32_t rend
     // that engine frame regardless of the counter delta. Generation and native
     // resource identity are still validated below, so this cannot carry a
     // right-eye source across a game tick or target transition.
     // The present thread can also observe the next engine frame immediately
     // after the render thread publishes a completed packet. Permit exactly
     // that one-frame pipeline handoff; wider cross-frame reuse remains closed.
-    if (!frame_diag::frame_window(render_frame_delta, engine_frame_delta, same_engine_frame_present_grace).accepted()) {
+    if (!duo_transaction && !frame_diag::frame_window(render_frame_delta, engine_frame_delta, same_engine_frame_present_grace).accepted()) {
         record_outcome(frame_diag::Reason::stale_frames);
         SPDLOG_WARNING_EVERY_N_SEC(
             2,
             "[NativeStereoFix] Refusing stale submit packet packet_render_frame={} submit_render_frame={} "
             "delta={} packet_engine_frame={} current_engine_frame={} engine_delta={} serial={} consumed_serial={}",
             packet->render_frame,
@@ -27423,13 +28503,13 @@ FFakeStereoRenderingHook::get_native_stereo_frame_packet_for_submit(int32_t rend
             engine_frame_delta,
             packet->serial,
             m_native_stereo_consumed_serial.load(std::memory_order_acquire));
         return nullptr;
     }
 
-    if (!exact_render_frame && (same_engine_frame_present_grace || next_engine_frame_handoff)) {
+    if (!duo_transaction && !exact_render_frame && (same_engine_frame_present_grace || next_engine_frame_handoff)) {
         SPDLOG_INFO_ONCE(
             "[NativeStereoFix] Accepting validated packet across asynchronous Present handoff "
             "(packet_render_frame={} submit_render_frame={} delta={} packet_engine_frame={} "
             "current_engine_frame={} engine_delta={})",
             packet->render_frame,
             render_frame,
@@ -27442,12 +28522,17 @@ FFakeStereoRenderingHook::get_native_stereo_frame_packet_for_submit(int32_t rend
     if (packet->capture_generation == m_native_stereo_rejected_capture_generation.load(std::memory_order_acquire)) {
         record_outcome(frame_diag::Reason::rejected_generation);
         return nullptr;
     }
 
     const auto rtm = const_cast<FFakeStereoRenderingHook*>(this)->get_render_target_manager();
+    if (vr->is_duoview_renderer_active() &&
+        (!rtm || packet->main_target!=rtm->get_view_family_render_target())) {
+        record_outcome(frame_diag::Reason::changed_resource);
+        return nullptr;
+    }
     const auto current_capture = rtm != nullptr ? rtm->get_scene_capture_target_snapshot() : nullptr;
     if (observation) {
         observation->resource_checks_ran = true;
         if (current_capture != nullptr) {
             observation->current_generation = current_capture->generation;
             observation->current_rhi = reinterpret_cast<uintptr_t>(current_capture->rhi_texture);
@@ -27470,12 +28555,27 @@ FFakeStereoRenderingHook::get_native_stereo_frame_packet_for_submit(int32_t rend
 
     record_outcome(exact_render_frame ? frame_diag::Reason::exact_frame :
         same_engine_frame_present_grace ? frame_diag::Reason::same_engine_frame : frame_diag::Reason::one_frame_handoff, true);
     return packet;
 }
 
+void FFakeStereoRenderingHook::dump_duoview_delivery() const {
+    static std::atomic<uint64_t> next_dump{};
+    const auto now = GetTickCount64();
+    auto expected = next_dump.load(std::memory_order_relaxed);
+    if (now < expected || !next_dump.compare_exchange_strong(expected, now + 5000)) return;
+    const auto events = duoview_delivery.recent();
+    spdlog::warn("[DuoView][Delivery] No same-transaction RHI source pair on Present; recent bounded trace follows");
+    for (size_t i=events.size()-24; i<events.size(); ++i) {
+        const auto& e=events[i];
+        if (e.sequence) spdlog::warn("[DuoView][Trace] seq={} us={} event={} gen={} serial={} family={} role={} thread={} command={:x} target={:x} draw={} pose={} capture_gen={}",
+            e.sequence, e.time_us, static_cast<uint32_t>(e.event), e.generation, e.serial,
+            e.frame, static_cast<uint32_t>(e.role), e.thread, e.command, e.target, e.draw, e.pose, e.capture_generation);
+    }
+}
+
 void FFakeStereoRenderingHook::sync_stalker2_native_experiment(bool enabled) {
     if (m_stalker2_native_experiment.exchange(enabled, std::memory_order_acq_rel) != enabled) {
         m_stalker2_native_packets.invalidate();
     }
 }
 
@@ -27927,12 +29027,102 @@ void FFakeStereoRenderingHook::pre_render_viewfamily_renderthread(ISceneViewExte
         }
 
         last_native_key = current_key;
     } else {
         last_native_key = {};
     }
+    const auto duo_source = vr->is_duoview_renderer_active()
+        ? g_hook->duoview_delivery.render(vr->mono_generation(), frame_count,
+            reinterpret_cast<uintptr_t>(view_family.get_render_target()),
+            reinterpret_cast<uintptr_t>(view_family.get_scene_interface()), GetCurrentThreadId())
+        : DuoDelivery::Source{};
+    std::optional<FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket> quad_engine_opt;
+    std::optional<FFakeStereoRenderingHook::QuadViewDelivery::Source> quad_source_opt;
+    FFakeStereoRenderingHook::QuadViewNativeDelivery::Command quad_native{};
+    if (vr->is_quadview_mode_selected()) {
+        const auto* native_views=view_family.get_views();
+        { uevr::quadview::HookTraceRecord r{};r.event="RT_ROLE_GATE";
+          r.reason=native_views && native_views->count==1?"singleton":"not_singleton";
+          r.generation=vr->mono_generation();r.frame=frame_count;r.mode=7;
+          r.result=native_views?static_cast<int>(native_views->count):-1;
+          r.family=reinterpret_cast<uintptr_t>(&view_family);
+          uevr::quadview::emit_hook_trace(28,r); }
+        if (native_views && native_views->count==1) {
+            FFakeStereoRenderingHook::QuadViewNativeDelivery::RenderTrace native_trace{};
+            const auto native=g_hook->quadview_native_delivery.render(vr->mono_generation(),frame_count,
+                reinterpret_cast<uintptr_t>(view_family.get_render_target()),
+                reinterpret_cast<uintptr_t>(view_family.get_scene_interface()),&native_trace);
+            { uevr::quadview::HookTraceRecord r{};r.event="RT_MATCH";r.reason=native?"native_accepted":"native_rejected";
+              r.generation=vr->mono_generation();r.serial=native_trace.serial;r.frame=frame_count;r.role=native_trace.role;r.mode=7;
+              r.family=reinterpret_cast<uintptr_t>(&view_family);r.target=reinterpret_cast<uintptr_t>(view_family.get_render_target());
+              r.scene=reinterpret_cast<uintptr_t>(view_family.get_scene_interface());r.result=static_cast<int>(native_trace.reason);
+              r.engine=native_trace.engine_claim;r.source=native_trace.source_claim;r.canonical_frame=native_trace.canonical_frame;
+              r.rendered=native_trace.rendered;r.hooked=native_trace.hooked;r.executed=native_trace.executed;r.written=native_trace.written;
+              uevr::quadview::emit_hook_trace(20,r); }
+            if (native) quad_native=*native;
+            else {
+                vr->set_quadview_status("Rejected a native singleton without an exact quartet owner");
+                SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][NativeRole][RT] unmatched generation={} frame={} target={:x} scene={:x}",
+                    vr->mono_generation(),frame_count,reinterpret_cast<uintptr_t>(view_family.get_render_target()),
+                    reinterpret_cast<uintptr_t>(view_family.get_scene_interface()));
+            }
+        }
+    }
+    if (!quad_native) {
+    if (vr->is_quadview_mode_selected()) {
+        quad_engine_opt=g_hook->quadview_delivery.render_engine_family(vr->mono_generation(),frame_count,
+            reinterpret_cast<uintptr_t>(view_family.get_render_target()),
+            reinterpret_cast<uintptr_t>(view_family.get_scene_interface()));
+        auto* qv_views=view_family.get_views();
+        bool valid_qv_family=qv_views != nullptr && qv_views->count == 4 && qv_views->capacity >= 4 &&
+            qv_views->data != nullptr && is_readable_process_range(reinterpret_cast<uintptr_t>(qv_views->data), sizeof(void*)*4);
+        std::array<uintptr_t,4> qv_render_view_ids{};
+        if (valid_qv_family) {
+            for (size_t i=0; i!=4; ++i) {
+                qv_render_view_ids[i]=reinterpret_cast<uintptr_t>(qv_views->data[i]);
+                if (!qv_render_view_ids[i]) valid_qv_family=false;
+                for (size_t j=0; j<i; ++j) if (qv_render_view_ids[i]==qv_render_view_ids[j]) valid_qv_family=false;
+            }
+        }
+        if (!valid_qv_family) {
+            vr->set_quadview_status("Render-thread family did not contain four readable distinct views");
+            SPDLOG_WARNING_EVERY_N_SEC(2, "[QuadViews][RenderFamily] rejected: count={} capacity={} data={:x} frame={}",
+                qv_views ? qv_views->count : 0, qv_views ? qv_views->capacity : 0,
+                qv_views ? reinterpret_cast<uintptr_t>(qv_views->data) : 0, frame_count);
+        } else if (quad_engine_opt) {
+            quad_source_opt=g_hook->quadview_delivery.render(vr->mono_generation(), frame_count,
+                reinterpret_cast<uintptr_t>(&view_family), reinterpret_cast<uintptr_t>(view_family.get_render_target()),
+                reinterpret_cast<uintptr_t>(view_family.get_scene_interface()));
+            if (quad_source_opt) {
+                SPDLOG_INFO_EVERY_N_SEC(2, "[QuadViews][RenderFamily] matched serial={} source_frame={} render_frame={} family_copy={:x}",
+                    quad_source_opt->serial, quad_source_opt->engine_frame, frame_count, reinterpret_cast<uintptr_t>(&view_family));
+            } else {
+                vr->set_quadview_status("Four-view render family has no unique bound engine-frame owner");
+                SPDLOG_WARNING_EVERY_N_SEC(2, "[QuadViews][RenderFamily] unmatched frame={} scene={:x} target={:x} family_copy={:x} views={:x},{:x},{:x},{:x}",
+                    frame_count, reinterpret_cast<uintptr_t>(view_family.get_scene_interface()),
+                    reinterpret_cast<uintptr_t>(view_family.get_render_target()),
+                    reinterpret_cast<uintptr_t>(&view_family),
+                    qv_render_view_ids[0], qv_render_view_ids[1], qv_render_view_ids[2], qv_render_view_ids[3]);
+            }
+        } else if (vr->is_quadview_renderer_active()) {
+            vr->set_quadview_status("Four-view render family has no tracked GT engine owner");
+        }
+    }
+    }
+    const auto quad_source=quad_source_opt.value_or(FFakeStereoRenderingHook::QuadViewDelivery::Source{});
+    const auto quad_engine=quad_engine_opt.value_or(FFakeStereoRenderingHook::QuadViewDelivery::EngineTicket{});
+    auto qv_route_trace=[=](size_t site,const char* event,const char* reason,uintptr_t list) {
+        uevr::quadview::HookTraceRecord r{};r.event=event;r.reason=reason;r.generation=vr->mono_generation();
+        r.mode=uevr::quadview::hook_trace_mode();r.frame=frame_count;r.list=list;
+        r.serial=quad_native?quad_native.source.serial:quad_engine?quad_engine.serial:quad_source?quad_source.serial:
+            duo_source.packet?duo_source.packet->serial:0;
+        r.role=quad_native?unsigned(quad_native.view):255;r.native=bool(quad_native);r.engine=bool(quad_engine);
+        r.source=bool(quad_source);r.duo=bool(duo_source);
+        uevr::quadview::emit_hook_trace(site,r);
+    };
+    qv_route_trace(21,"RT_ENTER","owner_selection_complete",reinterpret_cast<uintptr_t>(cmd_list));
 
     static bool is_ue5_rdg_builder = false;
     static uint32_t ue5_command_offset = 0;
     static bool analyzed_root_already = false;
     static bool is_old_command_base = false;
 
@@ -27951,13 +29141,16 @@ void FFakeStereoRenderingHook::pre_render_viewfamily_renderthread(ISceneViewExte
     // which *does* contain the command list in it, but for whatever reason I can't
     // seem to hook it properly, so I'm using the slate hook instead
     // ADDENDUM: For now, I'm only using the slate hook for UE5.0.3.
     // But I'll use it as a fallback as well for when the command list appears to be empty
     // Reason being the slate hook doesn't appear to run every frame, so it's not a perfect solution
     auto enqueue_poses_on_slate_thread = [&]() {
+        qv_route_trace(22,"SLATE_QUEUED","fallback",reinterpret_cast<uintptr_t>(cmd_list));
         g_hook->get_slate_thread_worker()->enqueue([=](FRHICommandListImmediate* command_list) {
+            qv_route_trace(23,"SLATE_ENTER","worker_callback",reinterpret_cast<uintptr_t>(command_list));
+            utility::ScopeGuard qv_slate_exit{[&]{qv_route_trace(24,"SLATE_RETURN","worker_callback",reinterpret_cast<uintptr_t>(command_list));}};
             static bool once_slate = true;
 
             if (once_slate) {
                 SPDLOG_INFO("Called enqueued function on the Slate thread for the first time! Frame count: {}", frame_count);
                 once_slate = false;
             }
@@ -27973,41 +29166,44 @@ void FFakeStereoRenderingHook::pre_render_viewfamily_renderthread(ISceneViewExte
                     reinterpret_cast<uintptr_t>(command_list),
                     uevr::nascar::title25::uses_validated_rhi_root(true,
                         uevr::nascar::is_validated_build(), true, layout_validated),
                     uevr::nascar::read_memory);
                 if (!root || !*root) {
                     SPDLOG_WARN_ONCE("[NASCAR25][UE5.5][RHICommandList] Exact command Root absent/unvalidated; using render-thread poses without scanning allocator memory");
+                    if (duo_source) g_hook->duoview_delivery.block(duo_source, 0, GetCurrentThreadId());
                     vr->get_runtime()->enqueue_render_poses(frame_count + compensation);
                     return;
                 }
                 SPDLOG_INFO_ONCE("[NASCAR25][UE5.5][RHICommandList] Using source/binary-validated Root at +0x28; legacy allocator scan bypassed");
                 SceneViewExtensionAnalyzer::hook_new_rhi_command(
-                    reinterpret_cast<sdk::FRHICommandBase_New*>(*root), frame_count + compensation);
+                    reinterpret_cast<sdk::FRHICommandBase_New*>(*root), frame_count + compensation, duo_source, quad_source, quad_engine, quad_native);
                 return;
             }
 
             // UE5.8's FRHICommandListBase begins with a 0x28-byte FMemStackBase.
             // Do not run the legacy speculative root scan here: a false positive
             // corrupts an RDG command vtable and crashes later in SetupPassInternals.
             if (is_ue_5_8()) {
                 constexpr size_t ue58_root_offset = 0x28;
                 const auto root_field = (uintptr_t)command_list + ue58_root_offset;
 
                 if (command_list == nullptr || IsBadReadPtr((void*)root_field, sizeof(void*))) {
                     SPDLOG_WARN_ONCE("[UE5.8][RHICommandList] Command list/root field is unreadable; using direct pose enqueue");
+                    if (duo_source) g_hook->duoview_delivery.block(duo_source, 0, GetCurrentThreadId());
                     vr->get_runtime()->enqueue_render_poses(frame_count + compensation);
                     return;
                 }
 
                 auto* root = *(sdk::FRHICommandBase_New**)root_field;
 
                 if (root == nullptr ||
                     ((uintptr_t)root & (sizeof(void*) - 1)) != 0 ||
                     IsBadReadPtr(root, sizeof(void*) * 2))
                 {
                     SPDLOG_WARN_ONCE("[UE5.8][RHICommandList] Root is absent or unreadable; using direct pose enqueue");
+                    if (duo_source) g_hook->duoview_delivery.block(duo_source, 0, GetCurrentThreadId());
                     vr->get_runtime()->enqueue_render_poses(frame_count + compensation);
                     return;
                 }
 
                 auto** vtable = *(void***)root;
                 const auto first_function =
@@ -28017,18 +29213,19 @@ void FFakeStereoRenderingHook::pre_render_viewfamily_renderthread(ISceneViewExte
                     first_function == nullptr ||
                     IsBadReadPtr(first_function, sizeof(void*)) ||
                     !utility::get_module_within(vtable) ||
                     !utility::get_module_within(first_function))
                 {
                     SPDLOG_WARN_ONCE("[UE5.8][RHICommandList] Root vtable failed validation; using direct pose enqueue");
+                    if (duo_source) g_hook->duoview_delivery.block(duo_source, 0, GetCurrentThreadId());
                     vr->get_runtime()->enqueue_render_poses(frame_count + compensation);
                     return;
                 }
 
                 SPDLOG_INFO_ONCE("[UE5.8][RHICommandList] Using source/PDB-validated Root offset 0x28");
-                SceneViewExtensionAnalyzer::hook_new_rhi_command(root, frame_count + compensation);
+                SceneViewExtensionAnalyzer::hook_new_rhi_command(root, frame_count + compensation, duo_source, quad_source, quad_engine, quad_native);
                 return;
             }
 
             // ES2's private UE5.5.4 symbols place FMemStackBase at the start of
             // FRHICommandListBase and Root immediately after it at +0x28.
             if (is_ue_5_5_runtime() && everspace2_is_current_game()) {
@@ -28077,19 +29274,21 @@ void FFakeStereoRenderingHook::pre_render_viewfamily_renderthread(ISceneViewExte
                 } catch(...) {
                     SPDLOG_ERROR("Failed to analyze FRHICommandBase");
                     analyzed_root_already = true;
                 }
 
                 if (!is_old_command_base) {
-                    SceneViewExtensionAnalyzer::hook_new_rhi_command((sdk::FRHICommandBase_New*)l->root, frame_count + compensation);
+                    SceneViewExtensionAnalyzer::hook_new_rhi_command((sdk::FRHICommandBase_New*)l->root, frame_count + compensation, duo_source, quad_source, quad_engine, quad_native);
                 } else {
+                    if (duo_source) g_hook->duoview_delivery.block(duo_source, 0, GetCurrentThreadId());
                     SceneViewExtensionAnalyzer::hook_old_rhi_command((sdk::FRHICommandBase_Old*)l->root, frame_count + compensation);
                 }
             } else {
                 // welp
-                vr->get_runtime()->enqueue_render_poses(frame_count + compensation);
+                if (duo_source) g_hook->duoview_delivery.block(duo_source, 0, GetCurrentThreadId());
+                    vr->get_runtime()->enqueue_render_poses(frame_count + compensation);
             }
         });
     };
 
     auto fall_back_to_slate_thread = [&]() {
         if (is_ue_5_7_or_newer()) {
@@ -28101,13 +29300,14 @@ void FFakeStereoRenderingHook::pre_render_viewfamily_renderthread(ISceneViewExte
             g_hook->get_render_target_manager()->try_schedule_dedicated_ui_creation();
         }
 
         if (g_hook->has_slate_hook()) {
             enqueue_poses_on_slate_thread();
         } else {
-            vr->get_runtime()->enqueue_render_poses(frame_count + compensation);
+            if (duo_source) g_hook->duoview_delivery.block(duo_source, 0, GetCurrentThreadId());
+                    vr->get_runtime()->enqueue_render_poses(frame_count + compensation);
         }
     };
 
     if (is_ue_5_7_or_newer() &&
         g_hook->has_slate_hook() &&
         g_hook->has_seen_stable_slate_draw() &&
@@ -28224,15 +29424,16 @@ void FFakeStereoRenderingHook::pre_render_viewfamily_renderthread(ISceneViewExte
         }
 
         if (g_hook->get_render_target_manager()->is_ue_5_0_3() && g_hook->has_slate_hook()) {
             enqueue_poses_on_slate_thread();
         } else try {
             if (!is_old_command_base) {
-                SceneViewExtensionAnalyzer::hook_new_rhi_command((sdk::FRHICommandBase_New*)cmd_list->root, frame_count + compensation);
+                SceneViewExtensionAnalyzer::hook_new_rhi_command((sdk::FRHICommandBase_New*)cmd_list->root, frame_count + compensation, duo_source, quad_source, quad_engine, quad_native);
             } else {
-                SceneViewExtensionAnalyzer::hook_old_rhi_command((sdk::FRHICommandBase_Old*)cmd_list->root, frame_count + compensation);
+                if (duo_source) g_hook->duoview_delivery.block(duo_source, 0, GetCurrentThreadId());
+                    SceneViewExtensionAnalyzer::hook_old_rhi_command((sdk::FRHICommandBase_Old*)cmd_list->root, frame_count + compensation);
             }
         } catch(...) {
             SPDLOG_INFO_ONCE("Failed to hook command list, falling back to Slate thread hook");
             fall_back_to_slate_thread();
         }
     } else {
@@ -29873,12 +31074,29 @@ void FFakeStereoRenderingHook::adjust_view_rect(FFakeStereoRendering* stereo, in
 #endif
 
     if (!g_framework->is_game_data_intialized()) {
         return;
     }
 
+    const auto vr = VR::get();
+    if (vr->is_quadview_layout_active()) {
+        if (index < 0 || index >= 4) return;
+        const auto frame=vr->is_quadview_renderer_active() ? vr->quadview_begin_frame() : std::optional<uevr::quadview::Snapshot>{};
+        const auto layout=frame ? std::optional<uevr::quadview::Layout>{frame->layout} : vr->quadview_layout_for_hooks();
+        if (!layout) { vr->set_quadview_status("No valid frozen four-view layout is available"); return; }
+        const auto& rect = layout->views[static_cast<size_t>(index)];
+        if (!rect.width || !rect.height || uint64_t(rect.x) + rect.width > layout->atlas_width ||
+            uint64_t(rect.y) + rect.height > layout->atlas_height) {
+            vr->set_quadview_status("Rejected an out-of-atlas engine view rectangle"); return;
+        }
+        *x = static_cast<int>(rect.x); *y = static_cast<int>(rect.y);
+        *w = rect.width; *h = rect.height;
+        if (frame) vr->quadview_producer().rectangle_call(vr->quadview_producer_key(), index);
+        return;
+    }
+
     static bool index_starts_from_one = true;
     const bool medium_one_based_eye_pass = medium_is_current_game();
 
     if (!medium_one_based_eye_pass) {
         if (index == 2) {
             index_starts_from_one = true;
@@ -29927,12 +31145,33 @@ void FFakeStereoRenderingHook::adjust_view_rect(FFakeStereoRendering* stereo, in
         : (index_starts_from_one ? ((index + 1) % 2) : (index % 2));
 
     if (medium_one_based_eye_pass) {
         SPDLOG_INFO_ONCE("[Medium][UE4.25Plus] Forcing one-based stereo eye passes (1=left, 2=right)");
     }
 
+    if (VR::get()->is_duoview_renderer_active() && g_hook->m_has_double_precision &&
+        (index == 0 || index == 1)) {
+        const auto vr = VR::get();
+        if (const auto frame = vr->duoview_begin_frame()) {
+            const auto& rect = static_cast<uint32_t>(index) == frame->config.settings.fovea_view
+                ? frame->config.layout.fovea : frame->config.layout.periphery;
+            if (rect.width && rect.height &&
+                uint64_t(rect.x) + rect.width <= frame->config.layout.atlas_width &&
+                uint64_t(rect.y) + rect.height <= frame->config.layout.atlas_height) {
+                // Native Fix renders each source into a separate single-eye target.
+                // Atlas placement is applied only after both sources are validated.
+                *x = 0;
+                *y = 0;
+                *w = rect.width;
+                *h = rect.height;
+                vr->duoview_state().rectangle(frame->config.key, static_cast<unsigned>(index));
+                return;
+            }
+        }
+        // Pair cannot pass frame validation. Original Mono fallback is guarded at submission.
+    }
     if (VR::get()->is_using_mono()) {
         *x = 0;
         *y = 0;
     } else if (!VR::get()->is_native_stereo_fix_enabled() || swgr_ue574_dx12_runtime()) {
         *x += *w * true_index;
     }
@@ -29953,21 +31192,48 @@ __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
 
     if (!g_framework->is_game_data_intialized()) {
         return;
     }
 
     auto vr = VR::get();
+    const bool quadview_active = vr->is_quadview_layout_active() && g_hook->m_has_double_precision;
+    if (quadview_active) {
+        if (view_index < 0 || view_index >= 4) return;
+        if (view_index >= 2) {
+            const auto pose = vr->quadview_producer().context_camera(vr->quadview_producer_key(), static_cast<uint32_t>(view_index & 1));
+            if (!pose) {
+                vr->set_quadview_status("Using the native eye offset while the matching context camera is unavailable");
+            } else {
+                auto* rot = reinterpret_cast<Rotator<double>*>(view_rotation);
+                auto* pos = reinterpret_cast<Vector3d*>(view_location);
+                rot->pitch=pose->rotation[0]; rot->yaw=pose->rotation[1]; rot->roll=pose->rotation[2];
+                pos->x=pose->position[0]; pos->y=pose->position[1]; pos->z=pose->position[2];
+                return;
+            }
+        }
+    }
+    if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 1) {
+        const auto key = vr->duoview_producer_key();
+        if (const auto pose = vr->duoview_state().camera(key, 1)) {
+            auto* rot = reinterpret_cast<Rotator<double>*>(view_rotation);
+            auto* pos = reinterpret_cast<Vector3d*>(view_location);
+            rot->pitch = pose->rotation[0]; rot->yaw = pose->rotation[1]; rot->roll = pose->rotation[2];
+            pos->x = pose->position[0]; pos->y = pose->position[1]; pos->z = pose->position[2];
+            if (vr->duoview_state().camera(key, 1, *pose)) return;
+        }
+        // A missing pose remains incomplete; the render submission gate will fall back.
+    }
     //std::scoped_lock _{vr->get_vr_mutex()};
 
     static bool index_starts_from_one = true;
     static bool index_was_ever_two = false;
     static bool index_was_ever_negative = false;
     const bool medium_one_based_eye_pass = medium_is_current_game();
 
     if (view_index == -1) {
-        index_was_ever_negative = true;
+        if (!quadview_active) index_was_ever_negative = true;
         SPDLOG_INFO_ONCE("calculate stereo view offset called with view index -1 (INDEX_NONE), ignoring.");
         return;
     }
 
     if (medium_one_based_eye_pass && (view_index < 1 || view_index > 2)) {
         vr->set_world_to_meters(world_to_meters);
@@ -29985,20 +31251,20 @@ __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
 
     if (synced_ue56_zero_view_is_eye) {
         SPDLOG_INFO_ONCE("[SyncedSequential][UE5.6+] Treating CalculateStereoViewOffset view_index 0 as the alternating AFR eye pass");
     }
 
     // This is eSSP_FULL, we don't care. It will cause the view to become monoscopic if we do anything.
-    if (index_was_ever_two && view_index == 0 && !synced_ue56_zero_view_is_eye) {
+    if (!quadview_active && index_was_ever_two && view_index == 0 && !synced_ue56_zero_view_is_eye) {
         SPDLOG_INFO_ONCE("calculate stereo view offset called with view index 0 after 2, ignoring.");
         return;
     }
 
     vr->set_world_to_meters(world_to_meters);
 
-    if (!medium_one_based_eye_pass) {
+    if (!medium_one_based_eye_pass && !quadview_active) {
         if (view_index == 2) {
             index_starts_from_one = true;
             index_was_ever_two = true;
         } else if (view_index == 0 && !index_was_ever_two) {
             index_starts_from_one = false;
         }
@@ -30010,15 +31276,15 @@ __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
         view_index == 0 &&
         !index_was_ever_two &&
         !index_was_ever_negative &&
         !g_hook->m_has_double_precision &&
         !synced_ue56_zero_view_is_eye;
 
-    auto true_index = medium_one_based_eye_pass
+    auto true_index = quadview_active ? (view_index & 1) : (medium_one_based_eye_pass
         ? view_index - 1
-        : (index_starts_from_one ? ((view_index + 1) % 2) : (view_index % 2));
+                : (index_starts_from_one ? ((view_index + 1) % 2) : (view_index % 2)));
     const auto has_double_precision = g_hook->m_has_double_precision;
     const auto rot_d = (Rotator<double>*)view_rotation;
 
     const bool mono = vr->is_using_mono();
     if (mono && !is_full_pass) { true_index = 0; }
     if (vr->is_using_afr() && !is_full_pass) {
@@ -30156,13 +31422,21 @@ __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
 
         for (auto& mod : mods) {
             mod->on_pre_calculate_stereo_view_offset(stereo, view_index, view_rotation, world_to_meters, view_location, g_hook->m_has_double_precision);
         }
     }
 
+    const auto qv_pose = quadview_active && view_index >= 0 && view_index <= 1
+        ? vr->quadview_camera_pose() : std::optional<VR::QuadViewCameraPose>{};
     const auto view_d = (Vector3d*)view_location;
+    const bool qv_center_context = view_index == 0 && g_hook->m_has_double_precision &&
+        vr->is_quadview_renderer_active() && [&]() {
+            const auto snapshot = vr->quadview_producer().snapshot(vr->quadview_producer_key());
+            return snapshot && snapshot->layout.shared_context;
+        }();
+    glm::vec3 qv_center_shift{};
 
     const auto view_mat = !has_double_precision ? 
         glm::yawPitchRoll(
             glm::radians(view_rotation->yaw),
             glm::radians(view_rotation->pitch),
             glm::radians(view_rotation->roll)) : 
@@ -30244,33 +31518,59 @@ __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
         v.assist_offset_status = (int32_t)camera_offsets.status;
     }
     if (!vr->is_stereo_emulation_enabled()) {
         const auto is_2d_screen = vr->is_using_2d_screen();
 
         const auto rotation_offset = vr->get_rotation_offset();
-        const auto current_hmd_rotation = glm::normalize(rotation_offset * glm::quat{vr->get_rotation(0)});
-        const auto current_eye_rotation_offset = glm::normalize(glm::quat{vr->get_eye_transform(true_index)});
+        const auto qv_eye_matrix = [&](uint32_t eye) {
+            const auto& p=qv_pose->quadview_head_views[eye].pose;
+            auto m=Matrix4x4f{runtimes::OpenXR::to_glm(p.orientation)};
+            m[3]=Vector4f{p.position.x,p.position.y,p.position.z,1.0f};
+            return m;
+        };
+        const auto head_rotation=qv_pose
+            ? glm::quat{runtimes::OpenXR::to_glm(qv_pose->view_space_location.pose.orientation)}
+            : glm::quat{vr->get_rotation(0)};
+        const auto current_hmd_rotation = glm::normalize(rotation_offset * head_rotation);
+        const auto current_eye_rotation_offset = glm::normalize(glm::quat{qv_pose
+            ? qv_eye_matrix(static_cast<uint32_t>(true_index)) : vr->get_eye_transform(true_index)});
 
         const auto new_rotation = glm::normalize(vqi_norm * current_hmd_rotation * current_eye_rotation_offset);
         const auto eye_offset = mono
             ? (glm::vec3{vr->get_eye_offset(VRRuntime::Eye::LEFT)} + glm::vec3{vr->get_eye_offset(VRRuntime::Eye::RIGHT)}) * 0.5f
-            : glm::vec3{vr->get_eye_offset((VRRuntime::Eye)(true_index))};
-
-
-        const auto standing_delta = vr->get_position(0) - vr->get_standing_origin();
+            : glm::vec3{qv_pose ? qv_eye_matrix(static_cast<uint32_t>(true_index))[3]
+                                : vr->get_eye_offset((VRRuntime::Eye)(true_index))};
+
+        const auto head_position=qv_pose
+            ? Vector4f{qv_pose->view_space_location.pose.position.x,qv_pose->view_space_location.pose.position.y,
+                       qv_pose->view_space_location.pose.position.z,1.0f}
+            : vr->get_position(0);
+        const auto standing_delta = head_position - vr->get_standing_origin();
         const auto standing_delta_flat = glm::vec3{standing_delta.x, 0, standing_delta.z};
 
-        const auto pos = glm::vec3{rotation_offset * standing_delta};
+        const auto xyz_gains = vr->get_xyz_head_movement_gains();
+        const auto pos = uevr::head_movement::scale_translation(
+            rotation_offset, glm::vec3{standing_delta}, xyz_gains);
         const auto pos_flat = glm::vec3{rotation_offset * standing_delta_flat};
 
         const auto head_offset = quat_converter * (vqi_norm * (pos * world_scale));
         const auto head_offset_flat = quat_converter * (vqi_norm * (pos_flat * world_scale));
         // Mono's center is expressed in head space; its optical rotation must
         // not rotate the translation a second time on calibrated/canted HMDs.
-        const auto eye_translation_rotation = mono ? glm::normalize(vqi_norm * current_hmd_rotation) : glm::normalize(new_rotation);
+        const auto eye_translation_rotation = (mono || qv_pose)
+            ? glm::normalize(vqi_norm * current_hmd_rotation) : glm::normalize(new_rotation);
         const auto eye_separation = quat_converter * (eye_translation_rotation * (eye_offset * world_scale));
+        if (qv_center_context) {
+            const auto center_offset = qv_pose
+                ? (glm::vec3{qv_eye_matrix(0)[3]} + glm::vec3{qv_eye_matrix(1)[3]}) * 0.5f
+                : (glm::vec3{vr->get_eye_offset(VRRuntime::Eye::LEFT)} +
+                   glm::vec3{vr->get_eye_offset(VRRuntime::Eye::RIGHT)}) * 0.5f;
+            // The midpoint is defined in head space (as UEVR Mono does), not along the left optical axis.
+            const auto center_separation = quat_converter * (glm::normalize(vqi_norm * current_hmd_rotation) * (center_offset * world_scale));
+            qv_center_shift = glm::vec3{eye_separation - center_separation};
+        }
 
         if (trace_view) {
             auto& v = trace_view->event.view;
             v.hmd_pose_valid = true;
             v.hmd_rotation = {current_hmd_rotation.x, current_hmd_rotation.y, current_hmd_rotation.z, current_hmd_rotation.w};
             v.eye_rotation = {current_eye_rotation_offset.x, current_eye_rotation_offset.y,
@@ -30387,12 +31687,35 @@ __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
                 g_hook->m_last_rotation_double = *rot_d;
             } else {
                 g_hook->m_last_rotation = *view_rotation;
             }
         }
 
+        if (vr->is_quadview_renderer_active() && g_hook->m_has_double_precision && view_index >= 0 && view_index <= 1) {
+            const auto* r = reinterpret_cast<const Rotator<double>*>(view_rotation);
+            const auto* p = reinterpret_cast<const Vector3d*>(view_location);
+            const uevr::quadview::CameraPose pose{{r->pitch,r->yaw,r->roll},{p->x,p->y,p->z},true};
+            if (!vr->quadview_producer().camera(vr->quadview_producer_key(), static_cast<uint32_t>(view_index), pose))
+                vr->set_quadview_status("Could not freeze the post-mod context camera");
+            if (!vr->quadview_note_eye_pose(static_cast<uint32_t>(view_index),
+                    qv_pose ? qv_pose->quadview_locate_serial : 0))
+                vr->set_quadview_status("Waiting for both context offsets to capture one exact OpenXR pose frame");
+        }
+        if (qv_center_context) {
+            view_d->x += qv_center_shift.x; view_d->y += qv_center_shift.y; view_d->z += qv_center_shift.z;
+        }
+        if (vr->is_duoview_renderer_active() && g_hook->m_has_double_precision && view_index == 0) {
+            const auto key = vr->duoview_producer_key();
+            const auto* r = reinterpret_cast<const Rotator<double>*>(view_rotation);
+            const auto* p = reinterpret_cast<const Vector3d*>(view_location);
+            const uevr::duoview::CameraPose pose{{r->pitch,r->yaw,r->roll},{p->x,p->y,p->z}};
+            vr->duoview_begin_frame();
+            if (!vr->duoview_state().camera(key, 0, pose))
+                SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] First scene pose not captured");
+        }
+
         // Modify Player Control Rotation
         const auto controller_camera_guard_active = vr->is_controller_camera_conflict_guard_active();
         const auto direct_aim_compatibility_fallback =
             vr->is_hmd_active() &&
             !controller_camera_guard_active &&
             (is_deadzone_ue56_executable() || is_payday3_aim_guard_enabled() || vr->is_direct_aim_compatibility_enabled()) &&
@@ -30425,13 +31748,12 @@ __forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_
     SPDLOG_INFO("calculate stereo projection matrix called! {} from {:x}", view_index, (uintptr_t)_ReturnAddress() - (uintptr_t)utility::get_module_within((uintptr_t)_ReturnAddress()).value_or(nullptr));
 #else
     SPDLOG_INFO_ONCE("calculate stereo projection matrix called! {} from {:x}", view_index, (uintptr_t)_ReturnAddress() - (uintptr_t)utility::get_module_within((uintptr_t)_ReturnAddress()).value_or(nullptr));
 #endif
 
     auto& vr = VR::get();
-
     bool ghosting_bootstrap_ready = false;
     {
         std::scoped_lock lock{g_hook->m_sceneview_data.mtx};
         ghosting_bootstrap_ready = g_hook->m_sceneview_data.ghosting_bootstrap_ready;
     }
 
@@ -30447,14 +31769,21 @@ __forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_
     // A valid GetDesiredNumberOfViews hook then cannot retroactively allocate
     // the missing right-eye ViewState. Preserve the established Native Fix
     // bootstrap on every supported engine, with source-validated handling for
     // the UE4.25/4.26 layouts below.
     const bool ue425_426_needs_localplayer_bootstrap =
         is_ue_4_25_runtime() || is_ue_4_26_runtime();
-    const bool native_needs_localplayer_bootstrap = vr->is_native_stereo_fix_enabled();
-    const bool wants_localplayer_bootstrap = !vr->is_using_mono() && (
+    // ID7 needs the same existing two-eye LocalPlayer allocation before its projection return.
+    const bool qv_needs_localplayer_bootstrap =
+        (vr->is_quadview_mode_selected() ||
+         vr->requested_rendering_method() == VR::RenderingMethod::QUAD_VIEWS_STEREO) &&
+        vr->is_quadview_supported_title() && g_framework != nullptr && g_framework->is_dx12() &&
+        vr->get_runtime() != nullptr && vr->get_runtime()->is_openxr();
+    const bool native_needs_localplayer_bootstrap =
+        vr->is_native_stereo_fix_enabled() || qv_needs_localplayer_bootstrap;
+    const bool wants_localplayer_bootstrap = (!vr->is_using_mono() || vr->is_duoview_renderer_active()) && (
         wants_ghosting_bootstrap ||
         ue425_426_needs_localplayer_bootstrap ||
         native_needs_localplayer_bootstrap ||
         vr->is_splitscreen_compatibility_enabled() ||
         vr->is_sceneview_compatibility_enabled() ||
         !g_hook->m_get_desired_number_of_views_hook);
@@ -30565,12 +31894,99 @@ __forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_
             SPDLOG_INFO("Removing midhook after CalculateStereoProjectionMatrix, job is done...");
             g_hook->m_calculate_stereo_projection_matrix_post_hook = {};
             g_hook->m_get_projection_data_pre_hook = {};
         }   
     }
 
+    if (qv_needs_localplayer_bootstrap) {
+        SPDLOG_INFO_EVERY_N_SEC(2,
+            "[QuadViews][Bootstrap] LocalPlayer attempted={} failed={} projection_hook={} entry_hook={} skip={} lazy={}",
+            g_hook->m_fixed_localplayer_view_count,
+            g_hook->m_native_stereo_localplayer_bootstrap_failed.load(std::memory_order_acquire),
+            !!g_hook->m_calculate_stereo_projection_matrix_post_hook,
+            !!g_hook->m_get_projection_data_pre_hook, vr->should_skip_post_init_properties(),
+            stalker2_uses_lazy_synced_viewstates());
+    }
+
+    if (vr->is_quadview_layout_active()) {
+        if (out == nullptr || view_index < 0 || view_index >= 4) {
+            vr->set_quadview_status("Quad Views projection output or eye index is unavailable"); return out;
+        }
+        if (!g_hook->m_has_double_precision || !g_framework->is_game_data_intialized()) {
+            if (g_hook->m_calculate_stereo_projection_matrix_hook)
+                g_hook->m_calculate_stereo_projection_matrix_hook.call<Matrix4x4f*>(stereo,out,static_cast<int32_t>(view_index & 1));
+            vr->set_quadview_status("Using the native eye projection while the four-view projection capture is unavailable"); return out;
+        }
+        const auto key = vr->quadview_producer_key();
+        const auto snapshot = vr->quadview_producer().snapshot(key);
+        const auto layout=snapshot ? std::optional<uevr::quadview::Layout>{snapshot->layout} : vr->quadview_layout_for_hooks();
+        if (!layout) { vr->set_quadview_status("No valid frozen four-view layout for projection"); return out; }
+        Matrix4x4d matrix{};
+        if (view_index < 2) {
+            // Legacy engine storage is a two-eye pair; focus callbacks only use the captured context projection.
+            float near_z{};
+            if (g_hook->m_calculate_stereo_projection_matrix_hook) {
+                g_hook->m_calculate_stereo_projection_matrix_hook.call<Matrix4x4f*>(stereo, out, view_index);
+                near_z = static_cast<float>((*reinterpret_cast<Matrix4x4d*>(out))[3][2]);
+            } else {
+                near_z = sdk::globals::get_near_clipping_plane();
+            }
+            const auto runtime=vr->get_runtime();
+            if (runtime && std::isfinite(near_z) && near_z>0.f) {
+                vr->m_nearz = near_z; runtime->update_matrices(near_z, 10000.0f);
+                matrix = vr->get_projection_matrix(static_cast<VRRuntime::Eye>(view_index));
+            } else {
+                for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) matrix[col][row]=(*reinterpret_cast<Matrix4x4d*>(out))[col][row];
+            }
+            if (const auto frozen=vr->quadview_base_projection(key,static_cast<uint32_t>(view_index))) {
+                for (int col=0; col!=4; ++col) {
+                    matrix[col][0]=(*frozen)[col*4+0]; matrix[col][1]=(*frozen)[col*4+1];
+                    matrix[col][3]=(*frozen)[col*4+3];
+                }
+            } else vr->set_quadview_status("Using the native context projection because its frozen OpenXR matrix was unavailable");
+            if (view_index == 0 && layout->shared_context) {
+                matrix[0][0]=layout->context_projection[0]; matrix[2][0]=layout->context_projection[1];
+                matrix[1][1]=layout->context_projection[2]; matrix[2][1]=layout->context_projection[3];
+            }
+        } else {
+            const auto eye=static_cast<uint32_t>(view_index & 1);
+            const auto base = vr->quadview_producer().projection_matrix(key, eye);
+            if (base) {
+                for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) matrix[col][row]=(*base)[col*4+row];
+                if (eye == 0 && layout->shared_context) {
+                    if (const auto left=vr->quadview_base_projection(key,0)) {
+                        matrix[0][0]=(*left)[0]; matrix[2][0]=(*left)[8];
+                        matrix[1][1]=(*left)[5]; matrix[2][1]=(*left)[9];
+                    } else vr->set_quadview_status("Tri-view left fovea lacks its frozen eye frustum");
+                }
+            } else {
+                float near_z=sdk::globals::get_near_clipping_plane();
+                if (g_hook->m_calculate_stereo_projection_matrix_hook) {
+                    g_hook->m_calculate_stereo_projection_matrix_hook.call<Matrix4x4f*>(stereo,out,static_cast<int32_t>(eye));
+                    near_z=static_cast<float>((*reinterpret_cast<Matrix4x4d*>(out))[3][2]);
+                }
+                if (std::isfinite(near_z) && near_z>0.f && vr->get_runtime()) {
+                    vr->m_nearz=near_z; vr->get_runtime()->update_matrices(near_z,10000.0f);
+                }
+                if (vr->get_runtime()) matrix=vr->get_projection_matrix(static_cast<VRRuntime::Eye>(eye));
+                else for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) matrix[col][row]=(*reinterpret_cast<Matrix4x4d*>(out))[col][row];
+                vr->set_quadview_status("Using a safe eye projection while the producer snapshot is unavailable");
+            }
+            uevr::quadview::apply_focus_crop(matrix, layout->focus_crops[eye]);
+        }
+        *reinterpret_cast<Matrix4x4d*>(out) = matrix;
+        std::array<double,16> values{};
+        for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) values[col*4+row]=matrix[col][row];
+        uint64_t hash=1469598103934665603ull;
+        const auto* bytes=reinterpret_cast<const uint8_t*>(values.data());
+        for (size_t i=0; i<sizeof(values); ++i) { hash ^= bytes[i]; hash *= 1099511628211ull; }
+        if (snapshot && !vr->quadview_producer().projection_call(key, view_index, hash, values))
+            vr->set_quadview_status("Could not freeze the expected Quad Views projection matrix");
+        return out;
+    }
+
     if (!g_framework->is_game_data_intialized()) {
         if (g_hook->m_nascar_stereo.original_address(12)) {
             return g_hook->m_nascar_stereo.call_slot<Matrix4x4f*>(12, stereo, out, view_index);
         }
         if (g_hook->m_calculate_stereo_projection_matrix_hook) {
             return g_hook->m_calculate_stereo_projection_matrix_hook.call<Matrix4x4f*>(stereo, out, view_index);
@@ -30653,12 +32069,18 @@ __forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_
             ? view_index - 1
             : (index_starts_from_one ? ((view_index + 1) % 2) : (view_index % 2));
     
         if (vr->is_using_afr()) {
             true_index = g_frame_count % 2;
         }
+        const bool duo_index=vr->is_duoview_renderer_active() && g_hook->m_has_double_precision &&
+            (view_index == 0 || view_index == 1);
+        const auto duo_frame=duo_index ? vr->duoview_begin_frame() :
+            std::optional<uevr::duoview::ViewFrame>{};
+        const bool duo_fovea=duo_frame && static_cast<uint32_t>(view_index) == duo_frame->config.settings.fovea_view;
+        const bool duo_full=duo_frame && !duo_fovea;
         if (vr->is_using_mono()) { true_index = 0; }
 
         auto& double_matrix = *(Matrix4x4d*)out;
 
         if (!g_hook->m_has_double_precision) {
             float old_znear = (*out)[3][2];
@@ -30673,13 +32095,24 @@ __forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_
         if (!g_hook->m_has_double_precision) {
             *out = VR::get()->get_projection_matrix((VRRuntime::Eye)(true_index));
         } else {
             const auto fmat = VR::get()->get_projection_matrix((VRRuntime::Eye)(true_index));
             double_matrix = fmat;
         }
-        if (vr->mono_frame_gate_required() && vr->get_runtime()->is_openxr()) {
+        if (duo_fovea || duo_full) {
+            if (const auto frame = vr->duoview_begin_frame()) {
+                uevr::duoview::apply_frame_projection(double_matrix,*frame,static_cast<unsigned>(view_index));
+                vr->duoview_state().projection(frame->config.key, static_cast<unsigned>(view_index));
+            } else {
+                SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView] Missing projection snapshot");
+            }
+        }
+        if (duo_frame && duo_frame->mono_source_frame && vr->mono_frame_gate_required() &&
+            vr->get_runtime()->is_openxr()) {
+            vr->get_openxr_runtime()->note_mono_projection(*duo_frame->mono_source_frame);
+        } else if (!duo_frame && vr->mono_frame_gate_required() && vr->get_runtime()->is_openxr()) {
             vr->get_openxr_runtime()->note_mono_projection();
         }
     } else {
         SPDLOG_ERROR("CalculateStereoProjectionMatrix returned nullptr!");
     }
 
@@ -30710,13 +32143,13 @@ __forceinline void FFakeStereoRenderingHook::render_texture_render_thread(FFakeS
         SPDLOG_INFO("Attempting to hook SlateRHIRenderer::DrawWindow_RenderThread using RenderTexture_RenderThread return address...");
         const auto return_address = (uintptr_t)_ReturnAddress();
         SPDLOG_INFO(" Return address: {:x}", return_address);
         g_hook->attempt_hook_slate_thread(return_address);
     }
 
-    g_hook->get_slate_thread_worker()->execute(rhi_command_list);
+    { uevr::quadview::NativeDrainScope qv_drain_scope{reinterpret_cast<uintptr_t>(rhi_command_list)}; g_hook->get_slate_thread_worker()->execute(rhi_command_list); }
 
     /*const auto return_address = (uintptr_t)_ReturnAddress();
     const auto slate_cvar_usage_location = sdk::vr::get_slate_draw_to_vr_render_target_usage_location();
 
     if (slate_cvar_usage_location) {
         const auto distance_from_usage = (intptr_t)(return_address - *slate_cvar_usage_location);
@@ -30844,12 +32277,18 @@ uint32_t FFakeStereoRenderingHook::get_desired_number_of_views_hook(FFakeStereoR
     }
 
     if (g_hook->m_sceneview_data.inside_post_init_properties) {
         return 2;
     }
 
+    if (vr->is_quadview_mode_selected()) {
+        const auto demanded=vr->quadview_desired_view_count();
+        if (demanded==4 && vr->is_quadview_renderer_active()) (void)vr->quadview_begin_frame();
+        return demanded;
+    }
+
     static const bool ktjl = [] {
         const auto path = utility::get_module_pathw(utility::get_executable());
         return path && sdk::ktjl::matches_executable(*path);
     }();
     if (ktjl && (!g_hook->m_ktjl_view_states_ready.load(std::memory_order_acquire) ||
                  !g_ktjl_fog_ready.load(std::memory_order_acquire) ||
@@ -30868,12 +32307,13 @@ uint32_t FFakeStereoRenderingHook::get_desired_number_of_views_hook(FFakeStereoR
         // Fix or the bounded Ghost bootstrap enters the repaired two-view path.
         return 1;
     }
 
     update_sifu_native_mesh_command_mode(is_stereo_enabled, vr->is_using_native_stereo());
 
+    if (vr->is_duoview_renderer_active()) { return 2; }
     if (vr->is_using_mono()) { return 1; }
 
     if (!is_stereo_enabled || (vr->is_using_afr() && !vr->is_splitscreen_compatibility_enabled())) {
         constexpr uint32_t BOOTSTRAP_PULSE_ENGINE_FRAMES = 2;
         constexpr uint32_t BOOTSTRAP_RETRY_COOLDOWN_ENGINE_FRAMES = 30;
         constexpr uint8_t BOOTSTRAP_MAX_ATTEMPTS = 3;
@@ -36643,13 +38083,13 @@ void FFakeStereoRenderingHook::nascar_render_texture(FFakeStereoRendering* stere
     }
     g_framework->notify_render_activity();
     // These are RDG textures, not FRHITexture*. Source is Slate's UI output once
     // routed; the scene comes only from the main viewport's render-thread ref.
     // The original fake-stereo pass unwraps Texture2DArray, which is invalid for
     // our packed Texture2D. UEVR's existing Present path composes the desktop.
-    g_hook->get_slate_thread_worker()->execute(reinterpret_cast<FRHICommandListImmediate*>(immediate));
+    { uevr::quadview::NativeDrainScope qv_drain_scope{reinterpret_cast<uintptr_t>(reinterpret_cast<FRHICommandListImmediate*>(immediate))}; g_hook->get_slate_thread_worker()->execute(reinterpret_cast<FRHICommandListImmediate*>(immediate)); }
 }
 
 void FFakeStereoRenderingHook::nascar25_render_texture(FFakeStereoRendering* stereo, FRHICommandListImmediate* immediate,
     FRHITexture2D* backbuffer, FRHITexture2D* source, uevr::nascar::WindowSize25 window_size) {
     // UE5.5 passes the immediate list directly and FVector2D as two doubles,
     // unlike NASCAR26's FRDGBuilder/float-vector overload. Never reinterpret it.
@@ -36658,13 +38098,13 @@ void FFakeStereoRenderingHook::nascar25_render_texture(FFakeStereoRendering* ste
         g_hook->get_render_target_manager()->invalidate_nascar_scene_target();
         return;
     }
     g_framework->notify_render_activity();
     // The getter routes Slate into the owned UI; Present composes the desktop.
     // Do not replay the game's array-texture fake-stereo draw on a packed 2D target.
-    g_hook->get_slate_thread_worker()->execute(immediate);
+    { uevr::quadview::NativeDrainScope qv_drain_scope{reinterpret_cast<uintptr_t>(immediate)}; g_hook->get_slate_thread_worker()->execute(immediate); }
     if (should_use_nascar25_ui_resource_worker()) {
         g_hook->m_nascar25_ui_render_callback_seen.store(true, std::memory_order_release);
         // Service UI completion only; do not pump unrelated RenderThreadWorker jobs.
         get_nascar25_ui_resource_worker().execute();
     }
 }
@@ -36722,13 +38162,13 @@ void* FFakeStereoRenderingHook::slate_draw_window_render_thread(void* renderer,
             SPDLOG_WARNING_EVERY_N_SEC(10,
                 "[Halloween][UE5.7][SlateUI] No validated stock input/command-list contract; preserving original draw");
             return g_hook->m_slate_thread_hook.call<void*>(renderer, a2, a3, a4, params, unk1, unk2);
         }
 
         // This is the engine's RHICmdList reference, not hidden sret storage.
-        g_hook->get_slate_thread_worker()->execute(reinterpret_cast<FRHICommandListImmediate*>(match->command_list));
+        { uevr::quadview::NativeDrainScope qv_drain_scope{reinterpret_cast<uintptr_t>(reinterpret_cast<FRHICommandListImmediate*>(match->command_list))}; g_hook->get_slate_thread_worker()->execute(reinterpret_cast<FRHICommandListImmediate*>(match->command_list)); }
         const auto vr = VR::get();
         auto* rtm = g_hook->get_render_target_manager();
         if (vr != nullptr && vr->is_hmd_active() && !vr->is_stereo_emulation_enabled() && rtm != nullptr) {
             g_hook->note_stable_slate_draw();
             g_hook->attempt_hook_ue55_slate_output_texture_register();
             rtm->request_dedicated_ui_target(match->width, match->height);
@@ -36972,13 +38412,13 @@ void* FFakeStereoRenderingHook::slate_draw_window_render_thread(void* renderer,
 
         return ret;
     }
 
     if (!a4_is_ue_5_5_variant) {
         // How are we going to fix this on UE5.5?
-        g_hook->get_slate_thread_worker()->execute((FRHICommandListImmediate*)a2);
+        { uevr::quadview::NativeDrainScope qv_drain_scope{reinterpret_cast<uintptr_t>((FRHICommandListImmediate*)a2)}; g_hook->get_slate_thread_worker()->execute((FRHICommandListImmediate*)a2); }
     } else if (!supports_ue55_dedicated_ui_target_for_current_game()) {
         const auto window = (uintptr_t)ue55_inputs.window;
 
         static std::optional<size_t> viewport_offset = [&]() -> std::optional<size_t> {
             std::optional<size_t> result{};
             const auto module_within = utility::get_module_within(g_hook->m_slate_thread_hook.target_address());
@@ -39967,12 +41407,654 @@ struct VRRenderTargetManager_Base::UE58UITextureOwner {
                 SPDLOG_WARNING_EVERY_N_SEC(5, "[UE5.8][SlateUI][Init] Could not retire a UI UObject safely");
             }
         }
     }
 };
 
+struct VRRenderTargetManager_Base::QuadViewNativeTargetOwner {
+    inline static std::atomic_bool servicing_enabled{};
+    // UPROPERTY ownership is essential: a weak UObjectReference and a retained
+    // ID3D12Resource do not own the engine's FTextureRenderTargetResource.
+    sdk::UObjectReference<sdk::AActor> holder_actor{nullptr};
+    sdk::UObjectReference<sdk::USceneCaptureComponent2D> holder_component{nullptr};
+    sdk::UObjectReference<sdk::UTexture> texture{nullptr};
+    uintptr_t texture_resource_identity{};
+    uintptr_t rhi_texture_identity{};
+    uint64_t resource_allocation_generation{}; // Set once before any engine allocation/publication.
+
+
+    bool live() const {
+        if (!holder_actor.valid() || !holder_component.valid() || !texture.valid()) return false;
+        constexpr uint32_t destroyed_flags=0x00008000u | 0x00010000u;
+        if ((texture->get_object_flags() & destroyed_flags) != 0 ||
+            (holder_actor->get_object_flags() & destroyed_flags) != 0 ||
+            (holder_component->get_object_flags() & destroyed_flags) != 0) return false;
+        auto** texture_slot=holder_component->get_texture_target();
+        if (!texture_slot || *texture_slot!=texture.get()) return false;
+        uintptr_t resource{},rhi{},vtable{};
+        return texture_resource_identity && rhi_texture_identity && render_target && gamma_hooked &&
+            safe_read_value(reinterpret_cast<uintptr_t>(texture.get())+STALKER2_UE55_UTEXTURE_PRIVATE_RESOURCE_OFFSET,resource) &&
+            resource==texture_resource_identity &&
+            safe_read_value(resource+STALKER2_UE55_FTEXTURE_RHI_OFFSET,rhi) && rhi==rhi_texture_identity &&
+            safe_read_value(reinterpret_cast<uintptr_t>(render_target),vtable) &&
+            hooked_vtable && vtable==reinterpret_cast<uintptr_t>(hooked_vtable->data());
+    }
+    sdk::FRenderTarget* render_target{};
+    uintptr_t original_vtable_address{};
+    std::array<uintptr_t,100> original_vtable{};
+    const std::array<uintptr_t,100>* hooked_vtable{}; // Process-lifetime immutable table.
+    Microsoft::WRL::ComPtr<ID3D12Resource> native_resource{};
+    bool rooted{}, gamma_hooked{};
+    QuadViewNativeTargetOwner* next_retired{};
+    Microsoft::WRL::ComPtr<ID3D12Fence> retire_fence{};
+    uint64_t retire_fence_value{};
+    uintptr_t retire_fence_device_identity{};
+
+    struct RetireQueue {
+        std::mutex mutex{};
+        QuadViewNativeTargetOwner *pending_head{}, *pending_tail{};
+        QuadViewNativeTargetOwner *staged_head{}, *staged_tail{};
+        QuadViewNativeTargetOwner* in_flight_head{};
+        QuadViewNativeTargetOwner *ready_head{}, *ready_tail{};
+        Microsoft::WRL::ComPtr<ID3D12Device> signal_device{};
+        Microsoft::WRL::ComPtr<ID3D12Fence> signal_fence{};
+        uint64_t next_fence_value{};
+        uintptr_t last_successful_queue{}, last_successful_device{}, last_successful_fence{};
+        uint64_t last_successful_signal_value{};
+        uintptr_t last_poll_fence{}, last_poll_device{};
+        uint64_t last_poll_completed_value{}, last_poll_target_value{};
+        uevr::quadview::NativeRetirementPollState last_poll_state{
+            uevr::quadview::NativeRetirementPollState::unobserved};
+        bool last_successful_signal_observed{};
+    };
+    inline static std::atomic<RetireQueue*> observed_queue{};
+    static RetireQueue& retire_queue() {
+        static auto* queue=[] { auto* value=new RetireQueue{}; observed_queue.store(value,std::memory_order_release); return value; }();
+        return *queue;
+    }
+
+    static uevr::quadview::NativeRetirementDiagnostics diagnostics_snapshot() {
+        uevr::quadview::NativeRetirementDiagnostics result{};
+        try {
+            auto* queue=observed_queue.load(std::memory_order_acquire);
+            if (!queue) return result; // Export does not initialize retirement state.
+            std::unique_lock lock{queue->mutex,std::try_to_lock};
+            if (!lock.owns_lock()) { result.observed=true; result.busy=true; return result; }
+            result.observed=true;
+            const auto next=[](const QuadViewNativeTargetOwner* owner) noexcept { return owner->next_retired; };
+            result.pending=uevr::quadview::count_native_retirement_list(queue->pending_head,next);
+            result.staged=uevr::quadview::count_native_retirement_list(queue->staged_head,next);
+            result.in_flight=uevr::quadview::count_native_retirement_list(queue->in_flight_head,next);
+            result.ready=uevr::quadview::count_native_retirement_list(queue->ready_head,next);
+            result.last_successful_queue=queue->last_successful_queue;
+            result.last_successful_device=queue->last_successful_device;
+            result.last_successful_fence=queue->last_successful_fence;
+            result.last_successful_signal_value=queue->last_successful_signal_value;
+            result.last_successful_signal_observed=queue->last_successful_signal_observed;
+            result.last_poll_fence=queue->last_poll_fence;
+            result.last_poll_device=queue->last_poll_device;
+            result.last_poll_completed_value=queue->last_poll_completed_value;
+            result.last_poll_target_value=queue->last_poll_target_value;
+            result.last_poll_state=queue->last_poll_state;
+        } catch (...) { result.observed=true; result.busy=true; }
+        return result;
+    }
+
+    static void append(QuadViewNativeTargetOwner*& head, QuadViewNativeTargetOwner*& tail,
+                       QuadViewNativeTargetOwner* owner) noexcept {
+        if (!owner) return;
+        owner->next_retired=nullptr;
+        if (tail) tail->next_retired=owner; else head=owner;
+        tail=owner;
+    }
+    static void append_list(QuadViewNativeTargetOwner*& head, QuadViewNativeTargetOwner*& tail,
+                            QuadViewNativeTargetOwner* list_head,
+                            QuadViewNativeTargetOwner* list_tail) noexcept {
+        if (!list_head) return;
+        if (tail) tail->next_retired=list_head; else head=list_head;
+        tail=list_tail;
+    }
+    static void retire(QuadViewNativeTargetOwner* owner) noexcept {
+        const bool unrendered=!owner->native_resource && !owner->gamma_hooked;
+        try {
+            auto& queue=retire_queue();
+            std::scoped_lock lock{queue.mutex};
+            if (unrendered)
+                append(queue.ready_head,queue.ready_tail,owner);
+            else
+                append(queue.pending_head,queue.pending_tail,owner);
+        } catch (...) {
+            // The actor/component property chain remains retained if retirement bookkeeping fails.
+        }
+        if (unrendered) {
+            try { GameThreadWorker::get().enqueue([] { QuadViewNativeTargetOwner::drain_retired(); }); }
+            catch (...) { /* A later GT target service drains unrendered owners. */ }
+        }
+    }
+
+    static void drain_retired() {
+        if (!GameThreadWorker::get().is_same_thread()) {
+            try { GameThreadWorker::get().enqueue([] { QuadViewNativeTargetOwner::drain_retired(); }); }
+            catch (...) { /* Retain the actor/property owners until GT can drain. */ }
+            return;
+        }
+        auto& queue=retire_queue();
+        QuadViewNativeTargetOwner* head{};
+        {
+            std::scoped_lock lock{queue.mutex};
+            head=std::exchange(queue.ready_head,nullptr);
+            queue.ready_tail=nullptr;
+        }
+        while (head) {
+            auto* owner=head;
+            head=owner->next_retired;
+            owner->next_retired=nullptr;
+            bool safe_to_delete=true;
+            try {
+                // The hook is a static pure gamma override, just like DuoView.
+                // Leave it installed until Unreal destroys its resource. Restoring
+                // a saved vptr here can write into a freed/recycled FRenderTarget.
+                // No hook table or callback ever refers back to this owner.
+                owner->gamma_hooked=false;
+                if (safe_to_delete && owner->rooted) {
+                    if (!owner->texture.valid()) {
+                        safe_to_delete=false;
+                    } else {
+                        unroot_dedicated_ui_texture(owner->texture.get());
+                        owner->rooted=false;
+                    }
+                }
+            } catch (...) {
+                safe_to_delete=false;
+                SPDLOG_WARNING_EVERY_N_SEC(5,"[QuadViews][NativeFix] Could not retire a fenced source target safely");
+            }
+            if (safe_to_delete) {
+                // This runs on GT only, after CPU leases and the existing GPU
+                // fence have retired. Keep the engine's property chain until then.
+                constexpr uint32_t destroyed_flags=0x00008000u | 0x00010000u;
+                if (owner->holder_component.valid() &&
+                    (owner->holder_component->get_object_flags() & destroyed_flags)==0)
+                    owner->holder_component->set_texture_target(nullptr);
+                if (owner->holder_actor.valid() &&
+                    (owner->holder_actor->get_object_flags() & destroyed_flags)==0)
+                    owner->holder_actor->destroy_actor();
+                owner->holder_component=nullptr;owner->holder_actor=nullptr;
+                owner->native_resource.Reset();
+                delete owner;
+            } else {
+                try {
+                    std::scoped_lock lock{queue.mutex};
+                    append(queue.ready_head,queue.ready_tail,owner);
+                } catch (...) {
+                    // Leave the still-rooted owner allocated if the retry list cannot grow.
+                }
+            }
+        }
+    }
+
+    static void service_after_present(ID3D12CommandQueue* command_queue) noexcept {
+        auto& queue=retire_queue();
+        bool queue_game_thread_drain{};
+        try {
+            std::scoped_lock lock{queue.mutex};
+
+            auto** link=&queue.in_flight_head;
+            while (*link) {
+                auto* owner=*link;
+                const auto completed=owner->retire_fence ? owner->retire_fence->GetCompletedValue() : 0;
+                if (owner->retire_fence) {
+                    queue.last_poll_fence=reinterpret_cast<uintptr_t>(owner->retire_fence.Get());
+                    queue.last_poll_device=owner->retire_fence_device_identity;
+                    queue.last_poll_completed_value=completed;
+                    queue.last_poll_target_value=owner->retire_fence_value;
+                    queue.last_poll_state=uevr::quadview::native_retirement_poll_state(true,completed);
+                }
+                if (owner->retire_fence && completed!=UINT64_MAX && completed>=owner->retire_fence_value) {
+                    *link=owner->next_retired;
+                    owner->next_retired=nullptr;
+                    owner->retire_fence.Reset();
+                    owner->retire_fence_value=0;
+                    owner->retire_fence_device_identity=0;
+                    append(queue.ready_head,queue.ready_tail,owner);
+                    queue_game_thread_drain=true;
+                } else {
+                    link=&owner->next_retired;
+                }
+            }
+
+            Microsoft::WRL::ComPtr<ID3D12Device> queue_device{};
+            if (queue.staged_head && command_queue && SUCCEEDED(command_queue->GetDevice(IID_PPV_ARGS(&queue_device))) && queue_device) {
+                QuadViewNativeTargetOwner *signal_head{}, *signal_tail{};
+                auto** staged_link=&queue.staged_head;
+                queue.staged_tail=nullptr;
+                while (*staged_link) {
+                    auto* owner=*staged_link;
+                    Microsoft::WRL::ComPtr<ID3D12Device> owner_device{};
+                    const bool same_device=owner->native_resource &&
+                        SUCCEEDED(owner->native_resource->GetDevice(IID_PPV_ARGS(&owner_device))) &&
+                        owner_device.Get()==queue_device.Get();
+                    if (same_device) {
+                        *staged_link=owner->next_retired;
+                        owner->next_retired=nullptr;
+                        append(signal_head,signal_tail,owner);
+                    } else {
+                        queue.staged_tail=owner;
+                        staged_link=&owner->next_retired;
+                    }
+                }
+
+                if (signal_head) {
+                    if (!queue.signal_fence || queue.signal_device.Get()!=queue_device.Get()) {
+                        Microsoft::WRL::ComPtr<ID3D12Fence> new_fence{};
+                        if (SUCCEEDED(queue_device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&new_fence))) && new_fence) {
+                            queue.signal_device=queue_device;
+                            queue.signal_fence=std::move(new_fence);
+                            queue.next_fence_value=0;
+                        }
+                    }
+                    const auto value=queue.next_fence_value+1;
+                    if (queue.signal_fence && queue.signal_device.Get()==queue_device.Get() &&
+                        SUCCEEDED(command_queue->Signal(queue.signal_fence.Get(),value))) {
+                        for (auto* owner=signal_head; owner; owner=owner->next_retired) {
+                            owner->retire_fence=queue.signal_fence;
+                            owner->retire_fence_value=value;
+                            owner->retire_fence_device_identity=reinterpret_cast<uintptr_t>(queue.signal_device.Get());
+                        }
+                        QuadViewNativeTargetOwner* flight_tail=signal_head;
+                        while (flight_tail && flight_tail->next_retired) flight_tail=flight_tail->next_retired;
+                        if (flight_tail) {
+                            flight_tail->next_retired=queue.in_flight_head;
+                            queue.in_flight_head=signal_head;
+                        }
+                        queue.next_fence_value=value;
+                        queue.last_successful_queue=reinterpret_cast<uintptr_t>(command_queue);
+                        queue.last_successful_device=reinterpret_cast<uintptr_t>(queue.signal_device.Get());
+                        queue.last_successful_fence=reinterpret_cast<uintptr_t>(queue.signal_fence.Get());
+                        queue.last_successful_signal_value=value;
+                        queue.last_successful_signal_observed=true;
+                    } else {
+                        QuadViewNativeTargetOwner* staged_tail=signal_head;
+                        while (staged_tail && staged_tail->next_retired) staged_tail=staged_tail->next_retired;
+                        append_list(queue.staged_head,queue.staged_tail,signal_head,staged_tail);
+                    }
+                }
+            }
+
+            // Owners are staged only after this present. The following present
+            // queues the fence after Unreal's complete intervening GPU work.
+            append_list(queue.staged_head,queue.staged_tail,queue.pending_head,queue.pending_tail);
+            queue.pending_head=nullptr;
+            queue.pending_tail=nullptr;
+        } catch (...) {
+            // Keep owners in their current rooted stage; no failure releases GPU resources.
+        }
+        if (queue_game_thread_drain) {
+            try { GameThreadWorker::get().enqueue([] { QuadViewNativeTargetOwner::drain_retired(); }); }
+            catch (...) { /* The next GT target service drains the completed list. */ }
+        }
+    }
+};
+struct VRRenderTargetManager_Base::QuadViewNativeTargetBuild {
+    uint64_t generation{};
+    uintptr_t world_identity{};
+    uint32_t width{},height{};
+    std::array<std::array<uint32_t,2>,4> extents{}; // Tri-view B6
+    std::array<std::shared_ptr<QuadViewNativeTargetOwner>,4> owners{}; // New allocations only.
+    std::array<std::shared_ptr<const SceneCaptureTargetSnapshot>,4> reused{};
+    uevr::quadview::NativeResourceReusePlan reuse_plan{};
+};
+
+float VRRenderTargetManager_Base::quadview_native_capture_display_gamma(const sdk::FRenderTarget*) {
+    // A table can outlive its owner/world. The callback never follows the
+    // viewport or manager pointer; GT refreshes the scalar for live targets.
+    return quadview_cached_display_gamma.load(std::memory_order_relaxed);
+}
+
+void VRRenderTargetManager_Base::service_quadview_native_target_retirements_after_present(ID3D12CommandQueue* command_queue) {
+    QuadViewNativeTargetOwner::service_after_present(command_queue);
+}
+
+uevr::quadview::NativeRetirementDiagnostics VRRenderTargetManager_Base::get_quadview_native_retirement_diagnostics() const {
+    return QuadViewNativeTargetOwner::diagnostics_snapshot();
+}
+
+bool VRRenderTargetManager_Base::quadview_native_targets_live(const QuadViewNativeTargetSetSnapshot& targets) const {
+    if (!GameThreadWorker::get().is_same_thread() || !targets.generation || !targets.world_identity) return false;
+    auto* engine=sdk::UGameEngine::get();
+    if (!engine || reinterpret_cast<uintptr_t>(engine->get_world())!=targets.world_identity) return false;
+    for (size_t i=0;i!=4;++i) {
+        if (i==1) continue; // No physical right periphery in TriView.
+        const auto& snapshot=targets.target_owners[i];
+        if (!snapshot || !snapshot->owner_lifetime) return false;
+        const auto owner=std::static_pointer_cast<const QuadViewNativeTargetOwner>(snapshot->owner_lifetime);
+        Microsoft::WRL::ComPtr<ID3D12Device> owner_device{};
+        const auto* hook=g_framework ? g_framework->get_d3d12_hook().get() : nullptr;
+        const bool current_device=owner && owner->native_resource && hook &&
+            SUCCEEDED(owner->native_resource->GetDevice(IID_PPV_ARGS(&owner_device))) &&
+            owner_device.Get()==hook->get_device();
+        // A single rejected native target must never be dispatched. Distinguish
+        // benign world reallocation from same-world resource identity changes.
+        const bool generation_matches=owner &&
+            owner->resource_allocation_generation==snapshot->resource_allocation_generation;
+        const bool render_target_matches=owner && owner->render_target==targets.render_targets[i];
+        const bool owner_live=generation_matches && current_device &&
+            render_target_matches && owner->live();
+        if (!owner_live) {
+            const char* reason=!owner ? "missing-owner" :
+                !generation_matches ? "allocation-generation-mismatch" :
+                !current_device ? "D3D12-device-mismatch" :
+                !render_target_matches ? "render-target-identity-mismatch" :
+                "Unreal-owner-property-resource-or-hook-mismatch";
+            static std::atomic<uint64_t> b41_rejections{0};
+            const auto rejection_count=b41_rejections.fetch_add(1,std::memory_order_relaxed)+1;
+            // B41: which part of the device check failed (no extra work on success).
+            const bool has_native=owner && owner->native_resource;
+            const auto* hook_device=hook ? hook->get_device() : nullptr;
+            Microsoft::WRL::ComPtr<ID3D12Device> probe_device{};
+            const HRESULT device_hr=has_native ? owner->native_resource->GetDevice(IID_PPV_ARGS(&probe_device)) : E_POINTER;
+            SPDLOG_ERROR_EVERY_N_SEC(1,"[TriView][TargetLifetime] rejected source role={} allocation={} publication={} reason={} target={:x} "
+                "native_resource={} hook={} hook_device={:x} get_device_hr={:#x} resource_device={:x} live={} rejections_total={}",
+                i, snapshot->resource_allocation_generation, targets.generation,
+                reason, reinterpret_cast<uintptr_t>(targets.render_targets[i]),
+                has_native, hook!=nullptr, reinterpret_cast<uintptr_t>(hook_device), static_cast<uint32_t>(device_hr),
+                reinterpret_cast<uintptr_t>(probe_device.Get()), owner && owner->live(), rejection_count);
+            return false;
+        }
+    }
+    return true;
+}
+
+bool VRRenderTargetManager_Base::ensure_quadview_native_target_set(const std::array<std::array<uint32_t,2>,4>& extents) {
+    // Tri-view B6: per-role extents (compact sources) or four equal 2W x H atlases.
+    constexpr std::array<size_t,3> tri_roles{0,2,3};
+    const bool extents_valid=extents[1][0]==0 && extents[1][1]==0 &&
+        std::all_of(tri_roles.begin(),tri_roles.end(),[&](size_t i) {
+            const auto& e=extents[i];
+            return e[0] && e[1] && e[0]<=16384 && e[1]<=8192;
+        });
+    const uint32_t width=extents_valid ? extents[0][0] : 0, height=extents_valid ? extents[0][1] : 0;
+    QuadViewNativeTargetOwner::servicing_enabled.store(true,std::memory_order_release);
+    if (GameThreadWorker::get().is_same_thread()) QuadViewNativeTargetOwner::drain_retired();
+    const auto vr=VR::get();
+    if (!width || !height || width>16384 || height>8192 || !g_framework || !g_framework->is_dx12() ||
+        !is_ue_5_5_runtime() || !stalker2_uses_ue55_draw_windows_array_layout() ||
+        !vr || !vr->is_quadview_mode_selected()) return false;
+    if (!GameThreadWorker::get().is_same_thread()) {
+        if (!quadview_native_target_creation_requested.exchange(true,std::memory_order_acq_rel)) {
+            try { GameThreadWorker::get().enqueue([this,extents]() {
+                quadview_native_target_creation_requested.store(false,std::memory_order_release);
+                (void)ensure_quadview_native_target_set(extents);
+            }); } catch (...) { quadview_native_target_creation_requested.store(false,std::memory_order_release); }
+        }
+        return false;
+    }
+    // This point is GT-only. Cache the current engine gamma, retaining
+    // the previous valid scalar while its viewport is temporarily unavailable.
+    if (auto* viewport=get_viewport()) {
+        const auto gamma=viewport->get_display_gamma();
+        if (std::isfinite(gamma) && gamma>0.0f)
+            quadview_cached_display_gamma.store(gamma,std::memory_order_relaxed);
+    }
+    if (vr->triview_world_epoch_closed()) return false;
+    auto* engine=sdk::UGameEngine::get();
+    auto* world=engine ? engine->get_world() : nullptr;
+    auto* kismet=sdk::UKismetRenderingLibrary::get();
+    if (!world) {
+        // GT observation invalidates publication/build admission; existing packet leases still retire normally.
+        retire_quadview_native_target_set();
+        SPDLOG_INFO_EVERY_N_SEC(2,"[TriView][Resources] No world; native publication invalidated, leased owners retained");
+        return false;
+    }
+    if (!kismet) {
+        SPDLOG_INFO_EVERY_N_SEC(2,"[QuadViews][NativeFix] Waiting for world/Kismet before creating four native source targets");
+        return false;
+    }
+    const auto world_identity=reinterpret_cast<uintptr_t>(world);
+    if (const auto current=quadview_native_target_set_snapshot.load(std::memory_order_acquire);
+        current && current->world_identity==world_identity && current->extents==extents &&
+        current->complete()) {
+        if (quadview_native_targets_live(*current)) return true;
+        retire_quadview_native_target_set();
+        return false;
+    }
+
+    const auto reuse_source=quadview_native_target_set_snapshot.load(std::memory_order_acquire);
+    const bool reuse_live=reuse_source && reuse_source->world_identity==world_identity &&
+        reuse_source->complete() && quadview_native_targets_live(*reuse_source);
+    const auto reuse_plan=uevr::quadview::plan_native_resource_reuse(
+        reuse_live,reuse_live,reuse_source ? reuse_source->extents : uevr::quadview::NativeResourceExtents{},extents);
+    std::shared_ptr<QuadViewNativeTargetBuild> build{};
+    {
+        std::scoped_lock lock{quadview_native_target_mutex};
+        if (quadview_native_target_build && quadview_native_target_build->world_identity==world_identity &&
+            quadview_native_target_build->extents==extents) return false;
+        build=std::make_shared<QuadViewNativeTargetBuild>();
+        build->generation=quadview_native_target_generation.fetch_add(1,std::memory_order_acq_rel)+1;
+        build->world_identity=world_identity; build->width=width; build->height=height;
+        build->extents=extents; build->reuse_plan=reuse_plan;
+        for (size_t i=0;i!=4;++i) if (reuse_plan.reuses(i)) build->reused[i]=reuse_source->target_owners[i];
+        quadview_native_target_build=build;
+        // Tri-view B12 make-before-break: same world -> keep drawing with the old
+        // set until this build publishes; another world -> its actors are gone.
+        if (const auto old=quadview_native_target_set_snapshot.load(std::memory_order_acquire);
+            !old || old->world_identity!=world_identity || !old->complete())
+            quadview_native_target_set_snapshot.store(nullptr,std::memory_order_release);
+    }
+
+    {   // B42: VRAM (last 1 s DXGI sample) at every set build.
+        const auto vr_vram=VR::get();
+        SPDLOG_INFO("[TriView][Resources] build={} reuse_mask={} new_color_mib={:.1f} (payload estimate) vram_used={} MB budget={} MB",
+            build->generation,unsigned(build->reuse_plan.reuse_mask),double(build->reuse_plan.new_color_bytes)/(1024.0*1024.0),
+            vr_vram ? vr_vram->m_triview_vram_used.load(std::memory_order_relaxed)>>20 : 0,
+            vr_vram ? vr_vram->m_triview_vram_budget.load(std::memory_order_relaxed)>>20 : 0);
+    }
+
+    // Use the same world actor -> component TextureTarget property chain as
+    // working DuoView Native Fix. Configure before registration so these
+    // holders never schedule independent scene-capture rendering.
+    auto* gameplay=sdk::UGameplayStatics::get();
+    auto* actor_class=sdk::AActor::static_class();
+    auto* capture_class=sdk::USceneCaptureComponent2D::static_class();
+    auto* capture_every=capture_class ? capture_class->find_property(L"bCaptureEveryFrame") : nullptr;
+    auto* capture_movement=capture_class ? capture_class->find_property(L"bCaptureOnMovement") : nullptr;
+    if (!gameplay || !actor_class || !capture_class || !capture_every || !capture_movement) {
+        std::scoped_lock lock{quadview_native_target_mutex};
+        if (quadview_native_target_build==build) quadview_native_target_build.reset();
+        return false;
+    }
+    // Kismet may flush rendering; the manager mutex is deliberately not held here.
+    const float clear_color[4]{0.0f,0.0f,0.0f,1.0f};
+    try {
+        for (size_t i=0;i!=4;++i) {
+            if (i==1) continue; // Do not spawn a holder or allocate a texture.
+            if (build->reused[i]) continue; // Keep the exact existing owner and gamma table.
+            auto owner=std::shared_ptr<QuadViewNativeTargetOwner>{new QuadViewNativeTargetOwner{},&QuadViewNativeTargetOwner::retire};
+            // Store immediately: partial creation follows the same GT cleanup.
+            build->owners[i]=owner;
+            owner->resource_allocation_generation=build->generation;
+            owner->holder_actor=gameplay->spawn_actor(world,actor_class,glm::vec3{0,0,0});
+            if (!owner->holder_actor.valid()) throw std::runtime_error("QuadView holder actor creation failed");
+            owner->holder_component=static_cast<sdk::USceneCaptureComponent2D*>(
+                owner->holder_actor->add_component_by_class(capture_class,true));
+            if (!owner->holder_component.valid()) throw std::runtime_error("QuadView holder component creation failed");
+            *capture_every->get_data<bool>(owner->holder_component.get())=false;
+            *capture_movement->get_data<bool>(owner->holder_component.get())=false;
+            owner->holder_component->set_visibility(false);
+            auto* texture=kismet->create_render_target_2d(world,build->extents[i][0],build->extents[i][1],2,clear_color,false);
+            if (!texture) {
+                std::scoped_lock lock{quadview_native_target_mutex};
+                if (quadview_native_target_build==build) quadview_native_target_build.reset();
+                SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][NativeFix] Kismet failed to create source target {}",i);
+                return false;
+            }
+            owner->texture=texture;
+            if (!owner->texture.valid()) throw std::runtime_error("QuadView texture identity invalid");
+            owner->holder_component->set_texture_target(texture);
+            auto** texture_slot=owner->holder_component->get_texture_target();
+            if (!texture_slot || *texture_slot!=texture)
+                throw std::runtime_error("QuadView TextureTarget property did not retain the source");
+            owner->holder_actor->finish_add_component(owner->holder_component.get());
+            SPDLOG_INFO("[QuadViews][TargetLifetime] role={} actor={:x} component={:x} texture={:x} property_owned=true capture_every=false capture_movement=false",
+                i,reinterpret_cast<uintptr_t>(owner->holder_actor.get()),
+                reinterpret_cast<uintptr_t>(owner->holder_component.get()),reinterpret_cast<uintptr_t>(texture));
+        }
+    } catch (...) {
+        { std::scoped_lock lock{quadview_native_target_mutex}; if (quadview_native_target_build==build) quadview_native_target_build.reset(); }
+        SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][NativeFix] Kismet target creation failed; the original family remains active");
+        return false;
+    }
+
+    auto* worker=g_hook ? g_hook->get_slate_thread_worker().get() : nullptr;
+    if (!worker) {
+        std::scoped_lock lock{quadview_native_target_mutex};
+        if (quadview_native_target_build==build) quadview_native_target_build.reset();
+        return false;
+    }
+    worker->enqueue_conditional([this,build](FRHICommandListImmediate*) {
+        auto quad_build_epoch_lease=VR::get()->triview_epoch_read();
+        if (!quad_build_epoch_lease) return false;
+        {
+            std::scoped_lock lock{quadview_native_target_mutex};
+            if (quadview_native_target_build!=build ||
+                build->generation!=quadview_native_target_generation.load(std::memory_order_acquire)) return true;
+        }
+        std::array<ValidatedNativeFixTextureChain,4> chains{};
+        for (size_t i=0;i!=4;++i) {
+            if (i==1) continue;
+            if (const auto& reused=build->reused[i]; reused) {
+                const auto owner=std::static_pointer_cast<const QuadViewNativeTargetOwner>(reused->owner_lifetime);
+                if (!owner || owner->resource_allocation_generation!=reused->resource_allocation_generation ||
+                    !owner->live() || !owner->native_resource) return false;
+                Microsoft::WRL::ComPtr<ID3D12Device> owner_device{};
+                const auto* hook=g_framework ? g_framework->get_d3d12_hook().get() : nullptr;
+                if (!hook || FAILED(owner->native_resource->GetDevice(IID_PPV_ARGS(&owner_device))) ||
+                    owner_device.Get()!=hook->get_device()) return false;
+                // The installed gamma vtable is ours, not module-owned: preserve its original validation/owner.
+                chains[i]={reinterpret_cast<sdk::FTextureRenderTargetResource*>(owner->texture_resource_identity),
+                    owner->render_target,reused->rhi_texture,owner->native_resource};
+                continue;
+            }
+            const auto& owner=build->owners[i];
+            if (!owner || !owner->texture.valid()) return false;
+            const auto validated=validate_native_fix_texture_chain(owner->texture.get(),build->extents[i][0],build->extents[i][1],
+                STALKER2_UE55_NATIVE_FIX_TEXTURE_LAYOUT);
+            if (!validated) return false;
+            chains[i]=*validated;
+            owner->native_resource=validated->native_resource;
+        }
+        const bool texture_offsets=build->reused[0] || sdk::UTexture::commit_validated_render_resource_offsets_texture2d(
+            build->reused[0] ? reinterpret_cast<sdk::UTexture*>(build->reused[0]->owner_texture) : build->owners[0]->texture.get(),
+            STALKER2_UE55_UTEXTURE_PRIVATE_RESOURCE_OFFSET,
+            STALKER2_UE55_FTEXTURE_RHI_OFFSET);
+        const bool render_target_offset=build->reused[0] || sdk::FTextureRenderTargetResource::commit_validated_render_target_vtable_offset(
+            chains[0].texture_resource,STALKER2_UE55_FRENDER_TARGET_OFFSET);
+        if (!texture_offsets || !render_target_offset) {
+            SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][NativeFix] Exact validated source chain changed before offset publication");
+            std::scoped_lock lock{quadview_native_target_mutex};
+            if (quadview_native_target_build==build) quadview_native_target_build.reset();
+            return true;
+        }
+        auto target_set=std::make_shared<QuadViewNativeTargetSetSnapshot>();
+        target_set->generation=build->generation; target_set->world_identity=build->world_identity;
+        target_set->width=build->width; target_set->height=build->height;
+        target_set->extents=build->extents;
+        if (!build->reused[0]) sdk::FRenderTarget::update_offsets(chains[0].render_target);
+        const auto gamma_index=sdk::FRenderTarget::get_display_gamma_index();
+        if (!gamma_index || *gamma_index>=std::tuple_size<decltype(QuadViewNativeTargetOwner::original_vtable)>::value) {
+            SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][NativeFix] Validated FRenderTarget gamma slot is unavailable");
+            std::scoped_lock lock{quadview_native_target_mutex};
+            if (quadview_native_target_build==build) quadview_native_target_build.reset();
+            return true;
+        }
+        for (size_t i=0;i!=4;++i) {
+            if (i==1) continue;
+            if (const auto& reused=build->reused[i]; reused) {
+                auto snapshot=uevr::quadview::republish_resource_snapshot(reused,build->generation);
+                if (!snapshot) return false; // Fail closed without mutating a live owner.
+                target_set->target_owners[i]=std::move(snapshot);
+                target_set->render_targets[i]=chains[i].render_target;
+                target_set->native_sources[i]=chains[i].native_resource;
+                continue;
+            }
+            auto& owner=*build->owners[i]; auto* frt=chains[i].render_target;
+            sdk::FRenderTarget::update_offsets(frt);
+            uintptr_t original_vtable{};
+            if (!safe_read_value(reinterpret_cast<uintptr_t>(frt),original_vtable) ||
+                !is_readable_process_range(original_vtable,sizeof(owner.original_vtable))) {
+                // B28: immutable gamma table remains valid through engine resource destruction.
+                std::scoped_lock lock{quadview_native_target_mutex};
+                if (quadview_native_target_build==build) quadview_native_target_build.reset();
+                return true;
+            }
+            owner.original_vtable_address=original_vtable;
+            std::memcpy(owner.original_vtable.data(),reinterpret_cast<const void*>(original_vtable),sizeof(owner.original_vtable));
+            // Deliberately process-lifetime, bounded to eight engine table variants.
+            static auto* gamma_tables=new uevr::quadview::PersistentGammaTables<100>{};
+            owner.hooked_vtable=gamma_tables->acquire(original_vtable,owner.original_vtable,*gamma_index,
+                reinterpret_cast<uintptr_t>(&VRRenderTargetManager_Base::quadview_native_capture_display_gamma));
+            if (!owner.hooked_vtable) {
+                std::scoped_lock lock{quadview_native_target_mutex};
+                if (quadview_native_target_build==build) quadview_native_target_build.reset();
+                SPDLOG_ERROR("[TriView][B28] Persistent gamma-table capacity or identity rejected");
+                return true;
+            }
+            owner.render_target=frt;
+            owner.texture_resource_identity=reinterpret_cast<uintptr_t>(chains[i].texture_resource);
+            owner.rhi_texture_identity=reinterpret_cast<uintptr_t>(chains[i].rhi_texture);
+            *reinterpret_cast<uintptr_t*>(frt)=reinterpret_cast<uintptr_t>(owner.hooked_vtable->data());
+            owner.gamma_hooked=true;
+            auto snapshot=std::make_shared<SceneCaptureTargetSnapshot>();
+            snapshot->native_resource=chains[i].native_resource.Get(); snapshot->rhi_texture=chains[i].rhi_texture;
+            snapshot->owner_texture=reinterpret_cast<uintptr_t>(owner.texture.get());
+            snapshot->generation=build->generation; snapshot->resource_allocation_generation=owner.resource_allocation_generation;
+            snapshot->width=build->extents[i][0]; snapshot->height=build->extents[i][1];
+            snapshot->owner_lifetime=build->owners[i];
+            target_set->target_owners[i]=std::move(snapshot); target_set->render_targets[i]=frt;
+            target_set->native_sources[i]=chains[i].native_resource;
+        }
+        if (!target_set->complete()) {
+                // B28: immutable gamma table remains valid through engine resource destruction.
+            std::scoped_lock lock{quadview_native_target_mutex};
+            if (quadview_native_target_build==build) quadview_native_target_build.reset();
+            SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][NativeFix] Four-source identity validation failed; no native set published");
+            return true;
+        }
+        {
+            std::scoped_lock lock{quadview_native_target_mutex};
+            if (quadview_native_target_build!=build ||
+                build->generation!=quadview_native_target_generation.load(std::memory_order_acquire)) {
+                // B28: immutable gamma table remains valid through engine resource destruction.
+                return true;
+            }
+            quadview_native_target_set_snapshot.store(std::move(target_set),std::memory_order_release);
+        }
+        {
+            const auto vr_vram=VR::get();
+            SPDLOG_INFO("[TriView][NativeFix] Published THREE independent UE5.5 source targets {}x{} (unused: {}x{}) {}x{} {}x{} generation={} vram_used={} MB budget={} MB",
+                build->extents[0][0],build->extents[0][1],build->extents[1][0],build->extents[1][1],
+                build->extents[2][0],build->extents[2][1],build->extents[3][0],build->extents[3][1],build->generation,
+                vr_vram ? vr_vram->m_triview_vram_used.load(std::memory_order_relaxed)>>20 : 0,
+                vr_vram ? vr_vram->m_triview_vram_budget.load(std::memory_order_relaxed)>>20 : 0);
+        }
+        return true;
+    },[this,build]() {
+        std::scoped_lock lock{quadview_native_target_mutex};
+        if (quadview_native_target_build==build) quadview_native_target_build.reset();
+        SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadViews][NativeFix] Four-source targets did not initialize; retaining legacy constructor/render discipline");
+    },std::chrono::seconds(30));
+    return false;
+}
+
+void VRRenderTargetManager_Base::retire_quadview_native_target_set() {
+    std::scoped_lock lock{quadview_native_target_mutex};
+    quadview_native_target_generation.fetch_add(1,std::memory_order_acq_rel);
+    quadview_native_target_build.reset();
+    quadview_native_target_creation_requested.store(false,std::memory_order_release);
+    quadview_native_target_set_snapshot.store(nullptr,std::memory_order_release);
+}
+
 bool VRRenderTargetManager_Base::create_ue58_ui_texture() {
     if (!should_harden_ue58_ui_initialization() || get_dedicated_ui_target() != nullptr ||
         dedicated_ui_texture != nullptr || in_flight_dedicated_ui_texture != nullptr || dedicated_ui_creation_pending)
     {
         return false;
     }
@@ -39993,12 +42075,13 @@ bool VRRenderTargetManager_Base::create_ue58_ui_texture() {
     SPDLOG_INFO("[UE5.8][SlateUI][Init] Queued generation {} [{}x{}], resource callback={}",
         ticket->generation, ticket->width, ticket->height, uevr::ue58_ui::to_string(source));
     return true;
 }
 
 void VRRenderTargetManager_Base::service_ue58_ui_game_thread() {
+    QuadViewNativeTargetOwner::drain_retired();
     if (!UE58UITextureOwner::servicing_enabled.load(std::memory_order_acquire)) {
         return;
     }
     UE58UITextureOwner::drain_retired();
     if (!ue58_ui_initialization_enabled.load(std::memory_order_acquire)) {
         return;
diff --git a/src/mods/vr/FFakeStereoRenderingHook.hpp b/src/mods/vr/FFakeStereoRenderingHook.hpp
index 78d3c502..e36eef5d 100644
--- a/src/mods/vr/FFakeStereoRenderingHook.hpp
+++ b/src/mods/vr/FFakeStereoRenderingHook.hpp
@@ -1,6 +1,7 @@
+#include "QuadViewResourceReuse.hpp"
 #pragma once
 
 #include <sdk/GalacticRacerRuntime.hpp>
 
 #include <memory>
 #include <array>
@@ -36,12 +37,23 @@
 #include "CompatibilityPolicy.hpp"
 #include "UE58UIInitialization.hpp"
 #include "UE58OwnedUITexture.hpp"
 #include "GalacticRacerOwnedTexture.hpp"
 #include "NativeFrameDiagnostics.hpp"
 #include "Stalker2NativePolicy.hpp"
+#include "DuoViewState.hpp"
+#include "DuoViewDelivery.hpp"
+#include "runtimes/OpenXR.hpp"
+#include "QuadViewDelivery.hpp"
+#include "QuadViewFamilyRouting.hpp"
+#include "QuadViewNativeDelivery.hpp"
+#include "QuadViewHookTrace.hpp"
+#include "QuadViewNativeRetirementDiagnostics.hpp"
+#include "QuadViewNativeTargets.hpp"
+#include "QuadViewFramePacket.hpp"
+#include "QuadViewViewDemand.hpp"
 #include "UE57SlateSymbols.hpp"
 #include "utility/NascarHookCompatibility.hpp"
 
 #include "Mod.hpp"
 
 struct FRHICommandListImmediate;
@@ -75,16 +87,48 @@ public:
         Microsoft::WRL::ComPtr<IUnknown> native_resource{};
         FRHITexture2D* rhi_texture{};
         uintptr_t owner_texture{};
         uint64_t generation{};
         uint32_t width{};
         uint32_t height{};
+        std::shared_ptr<const void> owner_lifetime{};
+        uint64_t resource_allocation_generation{}; // Native targets: immutable physical owner identity.
+
         std::optional<uevr::ue58_owned_ui::Resource> ue58_owned_resource{};
         std::optional<uevr::swgr_owned::Resource> swgr_owned_resource{};
     };
 
+    struct QuadViewNativeTargetSetSnapshot {
+        std::array<std::shared_ptr<const SceneCaptureTargetSnapshot>,4> target_owners{};
+        std::array<sdk::FRenderTarget*,4> render_targets{};
+        std::array<Microsoft::WRL::ComPtr<ID3D12Resource>,4> native_sources{};
+        uint64_t generation{};
+        uintptr_t world_identity{};
+        uint32_t width{},height{}; // role 0 extent (logs)
+        std::array<std::array<uint32_t,2>,4> extents{}; // Tri-view B6: per-role target extents
+        bool complete() const {
+            std::array<uevr::quadview::NativeTargetIdentity,4> identities{};
+            for (size_t i=0;i!=4;++i) {
+                if (i==1) {
+                    if (target_owners[i] || render_targets[i] || native_sources[i]) return false;
+                    continue;
+                }
+                const auto& owner=target_owners[i];
+                const auto& native=native_sources[i];
+                if (!owner || !native || !render_targets[i] || !owner->owner_lifetime ||
+                    !uevr::quadview::valid_resource_publication(generation,owner->generation,
+                        owner->resource_allocation_generation)) return false;
+                const auto desc=native->GetDesc();
+                identities[i]={owner->owner_texture,reinterpret_cast<uintptr_t>(render_targets[i]),
+                    reinterpret_cast<uintptr_t>(owner->rhi_texture),reinterpret_cast<uintptr_t>(native.Get()),
+                    generation,static_cast<uint32_t>(desc.Width),desc.Height,static_cast<uint32_t>(desc.Format)};
+            }
+            return generation && world_identity && width && height &&
+                uevr::quadview::valid_native_triview_targets(identities,extents);
+        }
+    };
     struct Everspace2D3D12SceneTargetSnapshot {
         Microsoft::WRL::ComPtr<ID3D12Resource> resource{};
         D3D12_RESOURCE_DESC desc{};
         uintptr_t source_texture{};
         uint64_t generation{};
         const char* source{};
@@ -336,12 +380,22 @@ public:
     const std::optional<size_t>& get_viewport_force_separate_rt_offset() const { 
         return m_viewport_force_separate_rt_offset; 
     }
 
     bool create_scene_capture();
     void destroy_scene_capture();
+    bool ensure_quadview_native_target_set(const std::array<std::array<uint32_t,2>,4>& extents);
+    bool quadview_native_targets_live(const QuadViewNativeTargetSetSnapshot& targets) const;
+    void retire_quadview_native_target_set();
+    void service_quadview_native_target_retirements_after_present(ID3D12CommandQueue* command_queue);
+    uevr::quadview::NativeRetirementDiagnostics get_quadview_native_retirement_diagnostics() const;
+    static float quadview_native_capture_display_gamma(const sdk::FRenderTarget* target);
+    inline static std::atomic<float> quadview_cached_display_gamma{2.2f};
+    std::shared_ptr<const QuadViewNativeTargetSetSnapshot> get_quadview_native_target_set() const {
+        return quadview_native_target_set_snapshot.load(std::memory_order_acquire);
+    }
 
     sdk::UTexture* get_scene_capture_utexture();
     
     sdk::FViewport* get_viewport() const {
         return last_viewport;
     }
@@ -366,12 +420,14 @@ public:
             set_view_family_render_target(reinterpret_cast<sdk::FRenderTarget*>(vp));
         }
     }
 
 protected:
     struct UE58UITextureOwner;
+    struct QuadViewNativeTargetOwner;
+    struct QuadViewNativeTargetBuild;
     bool create_ue58_ui_texture();
     void set_dedicated_ui_target_unlocked(FRHITexture2D* rt, uint32_t width, uint32_t height);
     uevr::ue58_ui::Initialization<UE58UITextureOwner> ue58_ui_initialization{};
     std::atomic_bool ue58_ui_initialization_enabled{};
 
     uint64_t invalidate_scene_capture_generation(const char* reason);
@@ -546,12 +602,17 @@ protected:
     std::atomic<uint64_t> stalker2_scene_target_generation{};
     std::atomic<std::shared_ptr<const NascarTextureSnapshot>> nascar_scene_target_snapshot{};
     std::atomic<std::shared_ptr<const NascarTextureSnapshot>> nascar_ui_target_snapshot{};
     uevr::nascar::SceneStability nascar_scene_stability{};
     std::atomic<uint64_t> sw_zero_company_desktop_extent{};
     std::atomic<std::shared_ptr<const SceneCaptureTargetSnapshot>> scene_capture_target_snapshot{};
+    std::atomic<std::shared_ptr<const QuadViewNativeTargetSetSnapshot>> quadview_native_target_set_snapshot{};
+    std::shared_ptr<QuadViewNativeTargetBuild> quadview_native_target_build{};
+    std::mutex quadview_native_target_mutex{};
+    std::atomic<uint64_t> quadview_native_target_generation{};
+    std::atomic_bool quadview_native_target_creation_requested{};
     std::atomic<uint64_t> scene_capture_generation{};
 };
 
 struct VRRenderTargetManager : IStereoRenderTargetManager, VRRenderTargetManager_Base {
 public:
     uint32_t GetNumberOfBufferedFrames() const override { return VRRenderTargetManager_Base::get_number_of_buffered_frames(); }
@@ -735,12 +796,21 @@ struct VRRenderTargetManager_Special : IStereoRenderTargetManager_Special, VRRen
         ETextureCreateFlags Flags, ETextureCreateFlags TargetableTextureFlags, FTexture2DRHIRef& OutTargetableTexture,
         FTexture2DRHIRef& OutShaderResourceTexture, uint32_t NumSamples = 1) override;
 };
 
 class FFakeStereoRenderingHook : public ModComponent {
 public:
+    // Tri-view B12 autostart: Native Stereo Fix has submitted a validated frame.
+    bool is_native_stereo_fix_state_active() const {
+        return m_native_stereo_fix_state.load(std::memory_order_acquire) == NativeStereoFixState::Active;
+    }
+    // Tri-view B14: Native Fix rendered its right eye (PairReady) or a pair was submitted (Active).
+    bool is_native_stereo_fix_state_ready() const {
+        const auto state = m_native_stereo_fix_state.load(std::memory_order_acquire);
+        return state == NativeStereoFixState::PairReady || state == NativeStereoFixState::Active;
+    }
     FFakeStereoRenderingHook();
 
     VRRenderTargetManager_Base* get_render_target_manager() {
         if (m_uses_ue58_rendertarget_manager) {
             if (m_ue58_rendertarget_manager_abi.load(std::memory_order_acquire) ==
                 UE58RenderTargetManagerABI::TransitionalDepthSlot)
@@ -848,12 +918,21 @@ public:
         uint32_t render_frame{};
         uint8_t eye{};
     };
 
     struct NativeStereoFramePacket {
         std::shared_ptr<const VRRenderTargetManager_Base::SceneCaptureTargetSnapshot> capture{};
+        std::shared_ptr<const uevr::duoview::ViewFrame> duoview_frame{};
+        uint32_t duoview_mono_source_frame{};
+        bool duoview_mono_source_valid{};
+        std::array<XrView,2> duoview_views{};
+        XrFrameState duoview_frame_state{XR_TYPE_FRAME_STATE};
+        XrSpaceLocation duoview_view_location{XR_TYPE_SPACE_LOCATION};
+        bool duoview_pose_valid{};
+        sdk::FRenderTarget* duoview_secondary_target{};
+        Microsoft::WRL::ComPtr<ID3D12Resource> duoview_primary_resource{};
         sdk::FSceneViewFamily* family{};
         sdk::FSceneView* left_view{};
         sdk::FSceneView* right_view{};
         sdk::FSceneViewStateInterface* left_state{};
         sdk::FSceneViewStateInterface* right_state{};
         sdk::FRenderTarget* main_target{};
@@ -871,21 +950,57 @@ public:
         bool stalker_pose_valid{};
         uint32_t stalker_pose_frame{};
         // Observation only; never used to accept a packet or retime a frame.
         uevr::native_frame::ClockStamp diagnostic_clock{};
     };
 
+    struct QuadViewSourcePacket {
+        // Temporal exclusion bound only; not proof of exact NGX source ownership.
+        std::chrono::steady_clock::time_point depth_not_before{std::chrono::steady_clock::now()};
+        std::shared_ptr<const uevr::quadview::Snapshot> producer{};
+        Microsoft::WRL::ComPtr<ID3D12Resource> atlas{};
+        std::array<Microsoft::WRL::ComPtr<ID3D12Resource>,4> native_sources{};
+        std::array<std::shared_ptr<const VRRenderTargetManager_Base::SceneCaptureTargetSnapshot>,4> native_target_owners{};
+        std::shared_ptr<const VRRenderTargetManager_Base::QuadViewNativeTargetSetSnapshot> native_target_set_owner{};
+        uint64_t native_target_set_generation{};
+        runtimes::OpenXR::PipelineState pose{};
+        D3D12_RESOURCE_STATES source_state{D3D12_RESOURCE_STATE_RENDER_TARGET};
+        uint64_t runtime_frame{}, serial{};
+    };
+    struct QuadViewNativeBuildContext {
+        bool active{},source_registered{}; uint32_t current_slot{},original_count{},engine_frame{0xffffffffu};
+        uint8_t roles_bound{}; std::array<uint32_t,4> role_frames{};
+        uintptr_t family{},scene{}; std::array<sdk::FSceneView*,4> original_views{};
+        std::array<sdk::FRenderTarget*,4> render_targets{}; sdk::FRenderTarget* original_target{};
+        std::shared_ptr<const VRRenderTargetManager_Base::QuadViewNativeTargetSetSnapshot> target_set{};
+        std::array<std::shared_ptr<const VRRenderTargetManager_Base::SceneCaptureTargetSnapshot>,4> target_owners{};
+        std::array<Microsoft::WRL::ComPtr<ID3D12Resource>,4> native_sources{}; uint64_t target_set_generation{};
+        std::shared_ptr<QuadViewSourcePacket> packet{};
+    };
+    static thread_local QuadViewNativeBuildContext quadview_native_build_context;
+    using DuoDelivery = uevr::duoview::Delivery<NativeStereoFramePacket>;
+    using QuadViewDelivery = uevr::quadview::Delivery<QuadViewSourcePacket>;
+    mutable DuoDelivery duoview_delivery{};
+    mutable QuadViewDelivery quadview_delivery{};
+    using QuadViewNativeDelivery = uevr::quadview::NativeDelivery<QuadViewDelivery>;
+    mutable QuadViewNativeDelivery quadview_native_delivery{quadview_delivery};
+    static inline thread_local std::shared_ptr<const NativeStereoFramePacket> duoview_build_packet{};
+    void dump_duoview_delivery() const;
+
     bool is_nascar_native_ready() const { return m_nascar_native_ready.load(std::memory_order_acquire); }
 
     std::shared_ptr<const NativeStereoFramePacket> get_native_stereo_frame_packet_for_submit(
         int32_t render_frame, uevr::native_frame::Backend backend = uevr::native_frame::Backend::unknown,
         uevr::native_frame::Ticket* diagnostic_ticket = nullptr) const;
     void note_native_stereo_frame_packet_consumed(uint64_t serial);
     void reject_native_stereo_frame_packet(uint64_t serial, const char* detail);
     void sync_stalker2_native_experiment(bool enabled);
     uint64_t stalker2_native_epoch() const { return m_stalker2_native_packets.epoch(); }
+    uint64_t native_stereo_publication_serial() const {
+        return m_native_stereo_packet_serial.load(std::memory_order_acquire);
+    }
     void note_stalker2_rhi_handoff(uint32_t frame);
     bool stalker2_native_capability() const;
     std::shared_ptr<const NativeStereoFramePacket> stalker2_latest_packet() const { return m_stalker2_native_packets.latest(); }
     std::shared_ptr<const NativeStereoFramePacket> get_stalker2_native_packet(uint32_t frame,
         uevr::native_frame::Ticket* ticket) const;
     void reject_stalker2_native_packet(const std::shared_ptr<const NativeStereoFramePacket>& packet, const char* detail);
@@ -1028,12 +1143,16 @@ public:
     void set_should_recreate_textures(bool recreate) {
         m_wants_texture_recreation = recreate;
         m_skip_next_adjust_view_rect = true;
     }
 
     void on_device_reset() override {
+        duoview_delivery.retire();
+        quadview_delivery.retire_all();
+        quadview_native_delivery.reset();
+        if (auto* manager=get_render_target_manager()) manager->retire_quadview_native_target_set();
         if (m_recreate_textures_on_reset->value()) {
             m_wants_texture_recreation = true;
         }
     }
 
     bool invalidate_ue57_resolution_dependent_state(
@@ -1136,12 +1255,19 @@ public:
     }
     const char* get_dibr_single_view_status_text() const;
     bool is_dibr_single_view_active() const;
     uint32_t get_dibr_single_view_suppressed_frames() const { return m_dibr_single_view_suppressed_frames.load(std::memory_order_acquire); }
     uint32_t get_dibr_single_view_fallback_frames() const { return m_dibr_single_view_fallback_frames.load(std::memory_order_acquire); }
     const char* get_splitscreen_compatibility_status_text();
+    bool quadview_outer_renderer_observed() const {
+        return m_render_module_begin_render_viewfamily_observed.load(std::memory_order_acquire);
+    }
+    bool quadview_view_extensions_ready() const {
+        return m_has_view_extensions_installed && !!m_sceneview_data.constructor_hook &&
+            m_has_double_precision && !!m_calculate_stereo_projection_matrix_hook;
+    }
 
 private:
     std::string build_hook_provenance_json();
     void draw_hook_provenance_diagnostics();
     void note_ue58_slate_ui_runtime_observation(
         uintptr_t original,
diff --git a/src/mods/vr/MonoRenderingPolicy.hpp b/src/mods/vr/MonoRenderingPolicy.hpp
index 78942fbf..3d726f79 100644
--- a/src/mods/vr/MonoRenderingPolicy.hpp
+++ b/src/mods/vr/MonoRenderingPolicy.hpp
@@ -11,20 +11,26 @@
 #include <string_view>
 
 namespace uevr::mono {
 
 // Serialized IDs are shared by the backend and injector, including non-DIBR builds.
 inline constexpr int32_t method_id = 5;
+inline constexpr int32_t duoview_method_id = 6;
+inline constexpr int32_t quadview_method_id = 7;
+constexpr bool is_mono_family(int32_t id) { return id == method_id || id == duoview_method_id; }
+constexpr bool is_deferred_family(int32_t id) { return is_mono_family(id) || id == quadview_method_id; }
 struct Choice { int32_t id; const char* label; };
 inline constexpr std::array choices {
     Choice{0, "Native Stereo"}, Choice{1, "Synchronized Sequential"}, Choice{2, "Alternating/AFR"},
     Choice{3, "Synthetic Stereo (DIBR, Experimental)"},
     Choice{4, "Synthetic Stereo (DIBR Single View, Experimental)"},
     Choice{method_id, "Mono (Experimental)"},
+    Choice{duoview_method_id, "DuoView Mono (Eye Tracked - Experimental)"},
+    Choice{quadview_method_id, "Quad Views Stereo (Experimental)"},
 };
-inline constexpr std::array non_dibr_choices {choices[0], choices[1], choices[2], choices[5]};
+inline constexpr std::array non_dibr_choices {choices[0], choices[1], choices[2], choices[5], choices[6], choices[7]};
 
 constexpr const char* label(int32_t id, std::span<const Choice> available = choices) {
     for (const auto& choice : available) { if (choice.id == id) { return choice.label; } }
     return "Unsupported rendering method (preserved)";
 }
 constexpr bool available(int32_t id, std::span<const Choice> options = choices) {
@@ -42,13 +48,13 @@ constexpr const char* unavailable_reason(const Capabilities& c) {
     if (c.extreme || c.split_screen || c.screen_2d || c.sceneview_compat || c.stereo_emulation) {
         return "Mono requires Extreme Compatibility, split-screen, 2D Screen, SceneView compatibility and Stereo Emulation OFF";
     }
     return nullptr;
 }
 
-// Requests from config, Lua/API and ImGui all use this transaction. Only Mono
+// Requests from config, Lua/API and ImGui all use this transaction. Mono-family
 // transitions are deferred; existing mode-to-mode selection remains unchanged.
 class Selection {
 public:
     struct State { int32_t method; uint32_t generation; };
     State snapshot() const {
         const auto packed = m_active.load(std::memory_order_acquire);
@@ -63,13 +69,13 @@ public:
         std::scoped_lock lock{m_mutex};
         if (m_initialized) { request_locked(value); return; }
         m_initialized = true;
         m_requested = pack(value, 1);
         // Even a startup profile enters through the same retired, game-frame
         // transaction. This also leaves unsupported startup requests escapable.
-        m_active = pack(value == method_id ? 0 : value, 0);
+        m_active = pack(is_deferred_family(value) ? 0 : value, 0);
     }
     void request(int32_t value) {
         std::scoped_lock lock{m_mutex};
         request_locked(value);
     }
     void consumers_retired(uint64_t token) {
@@ -89,13 +95,13 @@ private:
     }
     void request_locked(int32_t value) {
         if (value == requested()) { return; }
         m_retired_request = 0;
         m_requested = pack(value, static_cast<uint32_t>(request_token() >> 32) + 1);
         // A later old-mode request cancels an uncommitted entry into Mono.
-        if (active() != method_id && value != method_id) {
+        if (!is_deferred_family(active()) && !is_deferred_family(value)) {
             m_active = pack(value, snapshot().generation);
         }
     }
     mutable std::mutex m_mutex;
     std::atomic<uint64_t> m_requested{}, m_active{};
     uint64_t m_retired_request{};
@@ -206,13 +212,13 @@ constexpr bool frame_matches(uint64_t generation, uint64_t produced_generation,
     uint32_t render_frame, uint32_t pose_frame, uint32_t projection_frame, bool main_family) {
     return generation != 0 && produced_generation == generation && main_family &&
         render_frame == pose_frame && render_frame == projection_frame;
 }
 
 constexpr bool needs_frame_gate(int32_t method, uint64_t generation, uint64_t ready_generation) {
-    return method == method_id || generation != ready_generation;
+    return is_mono_family(method) || generation != ready_generation;
 }
 
 struct CopyRegion { uint32_t left{}, top{}, right{}, bottom{}, destination_x{}; };
 // Keep the established double-wide allocation: one engine view in its left
 // region, copied to both halves. No AFR timing, new target lifetime or shader.
 inline std::optional<std::array<CopyRegion, 2>> copy_regions(
diff --git a/src/mods/vr/OverlayComponent.hpp b/src/mods/vr/OverlayComponent.hpp
index 4dd4728e..d585b562 100644
--- a/src/mods/vr/OverlayComponent.hpp
+++ b/src/mods/vr/OverlayComponent.hpp
@@ -136,16 +136,16 @@ private:
     static const inline std::vector<std::string> s_overlay_type_names{
         "Quad",
         "Cylinder"
     };
 
     const ModCombo::Ptr m_slate_overlay_type{ ModCombo::create("UI_OverlayType", s_overlay_type_names) };
-    const ModSlider::Ptr m_slate_distance{ ModSlider::create("UI_Distance", 0.5f, 10.0f, 2.0f) };
+    const ModSlider::Ptr m_slate_distance{ ModSlider::create("UI_Distance", 0.5f, 10.0f, 10.0f) };
     const ModSlider::Ptr m_slate_x_offset{ ModSlider::create("UI_X_Offset", -10.0f, 10.0f, 0.0f) };
     const ModSlider::Ptr m_slate_y_offset{ ModSlider::create("UI_Y_Offset", -10.0f, 10.0f, 0.0f) };
-    const ModSlider::Ptr m_slate_size{ ModSlider::create("UI_Size", 0.5f, 10.0f, 2.0f) };
+    const ModSlider::Ptr m_slate_size{ ModSlider::create("UI_Size", 0.5f, 10.0f, 10.0f) };
     const ModSlider::Ptr m_slate_cylinder_angle{ ModSlider::create("UI_Cylinder_Angle", 0.0f, 360.0f, 90.0f) };
     const ModToggle::Ptr m_ui_follows_view{ ModToggle::create("UI_FollowView", false) };
     const ModSlider::Ptr m_ui_invert_alpha{ ModSlider::create("UI_InvertAlpha", 0.0f, 1.0f, 0.01f) };
     const ModCombo::Ptr m_game_ui_alpha{ModCombo::create("UI_AlphaMode_MonoDIBR",
         {"Unchanged", "Inspect only (no visual change)", "Straight RGB -> premultiplied", "Encoded-premultiplied -> linear-premultiplied"})};
     const ModCombo::Ptr m_imgui_alpha{ModCombo::create("UI_Framework_AlphaMode_MonoDIBR",
@@ -163,14 +163,14 @@ private:
     void publish_ui_composition(bool enabled) {
         auto old = m_ui_composition_request.load(std::memory_order_relaxed);
         while (!m_ui_composition_request.compare_exchange_weak(old, ((old & ~uint64_t{1}) + 2) | (enabled ? 1 : 0),
             std::memory_order_relaxed)) {}
     }
 
-    const ModSlider::Ptr m_framework_distance{ ModSlider::create("UI_Framework_Distance", 0.5f, 10.0f, 1.75f) };
-    const ModSlider::Ptr m_framework_size{ ModSlider::create("UI_Framework_Size", 0.5f, 10.0f, 2.0f) };
+    const ModSlider::Ptr m_framework_distance{ ModSlider::create("UI_Framework_Distance", 0.5f, 10.0f, 10.0f) };
+    const ModSlider::Ptr m_framework_size{ ModSlider::create("UI_Framework_Size", 0.5f, 10.0f, 8.0f) };
     const ModToggle::Ptr m_framework_ui_follows_view{ ModToggle::create("UI_Framework_FollowView", false) };
     const ModToggle::Ptr m_framework_wrist_ui{ ModToggle::create("UI_Framework_WristUI", false) };
     const ModToggle::Ptr m_framework_mouse_emulation{ ModToggle::create("UI_Framework_MouseEmulation", true) };
 
 public:
     OverlayComponent() 
diff --git a/src/mods/vr/RenderingMethodSetting.hpp b/src/mods/vr/RenderingMethodSetting.hpp
index f7f85791..f28ddfcb 100644
--- a/src/mods/vr/RenderingMethodSetting.hpp
+++ b/src/mods/vr/RenderingMethodSetting.hpp
@@ -24,28 +24,31 @@ public:
                     changed = true;
                 }
             }
             ImGui::EndCombo();
         }
         if (ImGui::BeginPopupContextItem()) {
-            if (ImGui::Button("Reset to default")) { request(0); changed = true; }
+            if (ImGui::Button("Reset to default")) { request(uevr::mono::quadview_method_id); changed = true; }
             ImGui::EndPopup();
         }
         ImGui::PopID();
         return changed;
     }
     void draw_value(std::string_view name) override {
         ImGui::Text("%s: %s (%d)", name.data(), uevr::mono::label(requested_value(), m_options), requested_value());
     }
     void config_load(const utility::Config& cfg, bool defaults) override {
-        m_selection.initialize(defaults ? 0 : cfg.get<int32_t>(m_name).value_or(requested_value()));
+        m_selection.initialize(defaults ? uevr::mono::quadview_method_id : cfg.get<int32_t>(m_name).value_or(uevr::mono::quadview_method_id));
     }
-    void config_save(utility::Config& cfg) override { cfg.set<int32_t>(m_name, requested_value()); }
+    // Tri-view B12: during the autostart warm-up the saved profile stays ID7.
+    void set_save_override(int32_t value) { m_save_override = value; }
+    void config_save(utility::Config& cfg) override { cfg.set<int32_t>(m_name, m_save_override >= 0 ? m_save_override : requested_value()); }
     void set(const std::string& value) override { request(std::stoi(value)); }
     std::string get() const override { return std::to_string(requested_value()); }
     std::string get_config_name() const override { return m_name; }
     std::string_view get_config_name_view() const override { return m_name; }
 private:
     const std::string m_name;
     const std::span<const uevr::mono::Choice> m_options;
     uevr::mono::Selection m_selection;
+    int32_t m_save_override{-1};
 };
diff --git a/src/mods/vr/d3d12/CommandContext.cpp b/src/mods/vr/d3d12/CommandContext.cpp
index e9221869..4bcc5b50 100644
--- a/src/mods/vr/d3d12/CommandContext.cpp
+++ b/src/mods/vr/d3d12/CommandContext.cpp
@@ -1,11 +1,12 @@
 #include <spdlog/spdlog.h>
 #include <utility/String.hpp>
 #include <atomic>
 #include <chrono>
 #include <string_view>
+#include <utility>
 
 #include "Framework.hpp"
 #include "render/D3D12Diagnostics.hpp"
 
 #include "TextureContext.hpp"
 #include "CommandContext.hpp"
@@ -660,12 +661,15 @@ bool CommandContext::references_retired() {
         this->poisoned, this->fence != nullptr, this->fence_value,
         [&] { return this->fence->GetCompletedValue(); });
 }
 
 void CommandContext::execute() {
     std::scoped_lock _{this->mtx};
+    // Pin and consume the optional queue before closing/submitting. Keep this
+    // ComPtr alive through both ExecuteCommandLists and the fence Signal.
+    auto command_queue = std::exchange(this->seam_submission_queue, ComPtr<ID3D12CommandQueue>{});
 
     if (this->poisoned || !this->ready()) {
         return;
     }
 
     if (this->has_commands) {
@@ -683,13 +687,13 @@ void CommandContext::execute() {
             }
             return;
         }
 
         this->close_failure_count = 0;
         
-        auto command_queue = g_framework->get_d3d12_hook()->get_command_queue();
+        if (!command_queue) command_queue = g_framework->get_d3d12_hook()->get_command_queue();
         if (command_queue == nullptr) {
             this->poisoned = true;
             spdlog::error("[VR] Cannot execute command list without a command queue. ({})", utility::narrow(this->internal_name));
             return;
         }
 
diff --git a/src/mods/vr/d3d12/CommandContext.hpp b/src/mods/vr/d3d12/CommandContext.hpp
index 113f9145..edc34bec 100644
--- a/src/mods/vr/d3d12/CommandContext.hpp
+++ b/src/mods/vr/d3d12/CommandContext.hpp
@@ -45,12 +45,17 @@ struct CommandContext {
         D3D12_RESOURCE_STATES dst_state = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
     void clear_rtv(ID3D12Resource* dst, D3D12_CPU_DESCRIPTOR_HANDLE rtv, const float* color, 
         D3D12_RESOURCE_STATES dst_state = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
     void clear_rtv(TextureContext& tex, const float* color, D3D12_RESOURCE_STATES dst_state = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
     void execute();
 
+    // Optional queue captured by a callback that records cross-slot GPU state.
+    // execute() consumes this reference for one submission; all other callers
+    // continue to use the D3D12 hook's current queue.
+    ComPtr<ID3D12CommandQueue> seam_submission_queue{};
+
     bool ready() const {
         return !this->poisoned && this->cmd_list != nullptr && this->cmd_allocator != nullptr && this->fence != nullptr;
     }
 
     ComPtr<ID3D12CommandAllocator> cmd_allocator{};
     ComPtr<ID3D12GraphicsCommandList> cmd_list{};
diff --git a/src/mods/vr/runtimes/OpenXR.cpp b/src/mods/vr/runtimes/OpenXR.cpp
index c9175efc..b4ab5378 100644
--- a/src/mods/vr/runtimes/OpenXR.cpp
+++ b/src/mods/vr/runtimes/OpenXR.cpp
@@ -450,23 +450,29 @@ void emit_openxr_state_probes(OpenXR* openxr, const char* context) {
 }
 
 void OpenXR::on_draw_ui() {
     ImGui::SetNextItemOpen(true, ImGuiCond_Once);
     if (ImGui::TreeNode("OpenXR Options")) {
         if (this->last_applied_resolution_width == 0 || this->last_applied_resolution_height == 0) {
-            this->last_applied_resolution_scale = this->resolution_scale->value();
+            {   // B42: during the low-resolution start the live scale is the warm-up scale
+                const float warm = triview_warmup_scale.load(std::memory_order_relaxed);
+                this->last_applied_resolution_scale = warm > 0.f ? warm : this->resolution_scale->value();
+            }
             this->last_applied_resolution_width = this->get_width();
             this->last_applied_resolution_height = this->get_height();
         }
 
         if (this->resolution_scale->draw("Resolution Scale")) {
             this->resolution_scale_reconfigure_pending = true;
         }
 
         if (this->resolution_scale_reconfigure_pending && !ImGui::IsItemActive()) {
             this->resolution_scale_reconfigure_pending = false;
+            if (triview_warmup_scale.exchange(0.f) > 0.f) {
+                spdlog::info("[TriView][LowStart] resolution slider moved by the user: low-resolution start ended");
+            }
 
             if (auto vr = VR::get(); vr != nullptr) {
                 const auto old_scale = this->last_applied_resolution_scale;
                 const auto new_scale = this->resolution_scale->value();
                 const auto old_width = this->last_applied_resolution_width != 0 ? this->last_applied_resolution_width : this->get_width_for_scale(old_scale);
                 const auto old_height = this->last_applied_resolution_height != 0 ? this->last_applied_resolution_height : this->get_height_for_scale(old_scale);
@@ -1437,12 +1443,14 @@ VRRuntime::Error OpenXR::update_poses(bool from_view_extensions, uint32_t frame_
     }
 
     this->last_pose_update_frame_count = frame_count;
     this->last_pose_update_from_view_extensions = from_view_extensions;
 
     const auto finish_pose_update = [&](VRRuntime::Error result) -> VRRuntime::Error {
+        if (vr->is_quadview_mode_selected() && result!=VRRuntime::Error::SUCCESS)
+            quadview_latest_located_pose.invalidate();
         const auto now = std::chrono::steady_clock::now();
         const auto pose_update_ms = std::chrono::duration<double, std::milli>{now - pose_update_start}.count();
         this->last_pose_update_result = static_cast<int64_t>(result);
         this->last_pose_update_ms = pose_update_ms;
         this->last_pose_view_locate_ms = view_locate_ms;
         this->last_pose_stage_locate_ms = stage_locate_ms;
@@ -1471,12 +1479,13 @@ VRRuntime::Error OpenXR::update_poses(bool from_view_extensions, uint32_t frame_
         }
 
         return result;
     };
 
     auto& pipeline_state = this->pipeline_states[frame_count % OpenXR::QUEUE_SIZE];
+    if (vr->is_quadview_mode_selected()) pipeline_state.quadview_pose_valid=false;
 
     if (vr->mono_frame_gate_required()) {
         mono_frames[frame_count % QUEUE_SIZE] = {};
     }
 
     if (this->is_everspace2_coherent_submit_active()) {
@@ -1543,12 +1552,13 @@ VRRuntime::Error OpenXR::update_poses(bool from_view_extensions, uint32_t frame_
 
     if (result != XR_SUCCESS) {
         spdlog::error("[VR] xrLocateViews for view space failed: {}", this->get_result_string(result));
         return finish_pose_update((VRRuntime::Error)result);
     }
 
+    const uint32_t quadview_head_view_count=view_count;
     view_locate_info = {XR_TYPE_VIEW_LOCATE_INFO};
     view_locate_info.viewConfigurationType = this->view_config;
     view_locate_info.displayTime = display_time;
     view_locate_info.space = this->stage_space;
 
     const auto stage_locate_start = std::chrono::steady_clock::now();
@@ -1584,13 +1594,40 @@ VRRuntime::Error OpenXR::update_poses(bool from_view_extensions, uint32_t frame_
     }
 
     const auto used_dead_island_stage_pose = synthesize_dead_island_view_space_pose(this);
 
     pipeline_state.view_space_location = this->view_space_location;
 
+    // Tri-view B15: newest frame with a located head pose (sync_assignment_mtx is held).
+    this->triview_pose_redirect = vr->is_quadview_renderer_active();
+    if ((this->view_space_location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT) != 0 &&
+        (!this->triview_pose_located || !uevr::quadview::pose_frame_newer(this->triview_newest_pose_frame, frame_count))) {
+        this->triview_pose_located = true;
+        this->triview_newest_pose_frame = frame_count;
+        this->triview_newest_pose_location = this->view_space_location;
+    }
+
+    if (vr->is_quadview_renderer_active()) {
+        pipeline_state.frame_count=frame_count;
+        const auto flags=XR_VIEW_STATE_ORIENTATION_VALID_BIT | XR_VIEW_STATE_POSITION_VALID_BIT;
+        pipeline_state.quadview_pose_valid=view_count==2 && quadview_head_view_count==2 && this->views.size()==2 &&
+            this->stage_views.size()==2 &&
+            (this->stage_view_state.viewStateFlags & flags)==flags &&
+            (this->view_state.viewStateFlags & flags)==flags &&
+            (this->view_space_location.locationFlags &
+                (XR_SPACE_LOCATION_ORIENTATION_VALID_BIT | XR_SPACE_LOCATION_POSITION_VALID_BIT)) ==
+                (XR_SPACE_LOCATION_ORIENTATION_VALID_BIT | XR_SPACE_LOCATION_POSITION_VALID_BIT);
+        if (pipeline_state.quadview_pose_valid) {
+            pipeline_state.quadview_head_views={this->views[0],this->views[1]};
+            quadview_latest_located_pose.publish(pipeline_state);
+        } else {
+            quadview_latest_located_pose.invalidate();
+        }
+    }
     if (vr->mono_frame_gate_required()) {
+        if (vr->is_duoview_renderer_active()) pipeline_state.frame_count=frame_count;
         auto& mono = mono_frames[frame_count % QUEUE_SIZE];
         mono.generation = vr->mono_generation();
         mono.pose_frame = frame_count;
         const auto flags = XR_VIEW_STATE_ORIENTATION_VALID_BIT | XR_VIEW_STATE_POSITION_VALID_BIT;
         mono.pose_valid = (this->stage_view_state.viewStateFlags & flags) == flags &&
             (this->view_state.viewStateFlags & flags) == flags && view_count == 2;
@@ -1726,16 +1763,48 @@ uint32_t OpenXR::get_width_for_scale(float scale) const {
         return 0;
     }
 
     return (uint32_t)((float)this->view_configs[0].recommendedImageRectWidth * scale * eye_width_adjustment);
 }
 
+// B42: one-shot switch from the low-resolution start to the saved scale, same
+// path as the menu slider (VR::on_openxr_resolution_scale_changed).
+bool OpenXR::finish_triview_warmup(const char* reason) {
+    if (this->view_configs.empty()) return false; // keep the warm-up until sizes are known
+    const float warm = triview_warmup_scale.exchange(0.f);
+    if (warm <= 0.f) return false;
+    const float full = this->resolution_scale->value();
+    const auto old_w = this->get_width_for_scale(warm), old_h = this->get_height_for_scale(warm);
+    const auto new_w = this->get_width_for_scale(full), new_h = this->get_height_for_scale(full);
+    spdlog::info("[TriView][LowStart] {}: resolution scale {:.2f} -> {:.2f} [{}x{}] -> [{}x{}]",
+        reason ? reason : "", warm, full, old_w, old_h, new_w, new_h);
+    if (old_w == new_w && old_h == new_h) return true;
+    auto vr = VR::get();
+    const bool live = vr != nullptr && vr->on_openxr_resolution_scale_changed(old_w, old_h, new_w, new_h);
+    if (live) {
+        this->resolution_scale_live_apply_deferred = false;
+        this->last_applied_resolution_scale = full;
+        this->last_applied_resolution_width = new_w;
+        this->last_applied_resolution_height = new_h;
+    } else {
+        this->resolution_scale_live_apply_deferred = true;
+        this->last_applied_resolution_scale = warm;
+        this->last_applied_resolution_width = old_w;
+        this->last_applied_resolution_height = old_h;
+        spdlog::warn("[TriView][LowStart] live resolution change not allowed; staying at {:.2f} until the next start", warm);
+    }
+    return live;
+}
+
 uint32_t OpenXR::get_width() const {
     if (this->view_configs.empty()) {
         return 0;
     }
+    if (const float warm = triview_warmup_scale.load(std::memory_order_relaxed); warm > 0.f) {
+        return this->get_width_for_scale(warm); // B42 low-resolution start
+    }
 
     const auto use_last_applied =
         (this->resolution_scale_reconfigure_pending || this->resolution_scale_live_apply_deferred) &&
         this->last_applied_resolution_width != 0;
     const auto scale = use_last_applied
         ? this->last_applied_resolution_scale
@@ -1753,12 +1822,15 @@ uint32_t OpenXR::get_height_for_scale(float scale) const {
 }
 
 uint32_t OpenXR::get_height() const {
     if (this->view_configs.empty()) {
         return 0;
     }
+    if (const float warm = triview_warmup_scale.load(std::memory_order_relaxed); warm > 0.f) {
+        return this->get_height_for_scale(warm); // B42 low-resolution start
+    }
 
     const auto use_last_applied =
         (this->resolution_scale_reconfigure_pending || this->resolution_scale_live_apply_deferred) &&
         this->last_applied_resolution_height != 0;
     const auto scale = use_last_applied
         ? this->last_applied_resolution_scale
@@ -1907,14 +1979,19 @@ static std::optional<uevr::mono::Geometry> mono_geometry(const std::vector<XrVie
     }
     return uevr::mono::geometry(eyes);
 }
 
 void OpenXR::reset_mono_projection_history() {
     std::scoped_lock lock{this->sync_assignment_mtx, this->pose_mtx};
+    invalidate_quadview_located_pose();
     mono_frames = {};
     mono_copied_frame.reset();
+    quadview_pending_pose.reset(); quadview_submitted_pose.reset();
+    quadview_continuity.reset(); quadview_holding=false; quadview_pose_generation=0;
+    duoview_pending_pose.reset(); duoview_submitted_pose.reset();
+    duoview_continuity.reset(); duoview_holding=false;
     this->should_recalculate_eye_projections = true;
     this->should_update_eye_matrices = true;
 }
 
 void OpenXR::note_mono_projection() {
     std::scoped_lock lock{this->sync_assignment_mtx, this->pose_mtx};
@@ -1928,12 +2005,23 @@ void OpenXR::note_mono_projection() {
             std::abs(this->projections[0][2][0]) > 0.0001f || std::abs(this->projections[0][2][1]) > 0.0001f) { return; }
     }
     frame.projection_frame = this->internal_frame_count;
     frame.generation = vr->mono_generation();
 }
 
+// DuoView passes the immutable source pose token observed before Joey's
+// Native Fix split invokes its second renderer callback.
+void OpenXR::note_mono_projection(uint32_t source_frame) {
+    std::scoped_lock lock{this->sync_assignment_mtx, this->pose_mtx};
+    const auto vr = VR::get();
+    auto& frame = mono_frames[source_frame % QUEUE_SIZE];
+    if (frame.pose_frame != source_frame || !frame.pose_valid) { return; }
+    frame.projection_frame = source_frame;
+    frame.generation = vr->mono_generation();
+}
+
 void OpenXR::note_mono_main_family(uint32_t frame, bool main_family) {
     if (!main_family) { return; }
     std::scoped_lock lock{this->sync_assignment_mtx};
     auto& entry = mono_frames[frame % QUEUE_SIZE];
     entry.main_family = entry.pose_frame == frame && entry.projection_frame == frame &&
         entry.generation == VR::get()->mono_generation();
@@ -2443,13 +2531,154 @@ void OpenXR::log_everspace2_coherent_submit_summary_if_needed() {
         this->everspace2_single_frame_hold_submit_count,
         this->everspace2_rejected_submit_count,
         this->everspace2_max_submit_pose_age_ms,
         this->everspace2_has_real_projection_submit.load(std::memory_order_acquire));
 }
 
+std::optional<OpenXR::PipelineState> OpenXR::capture_quadview_pose(uint32_t frame) {
+    auto pose=capture_quadview_current_pose();
+    if (!pose || pose->frame_count!=frame) return {};
+    return pose;
+}
+
+std::optional<OpenXR::PipelineState> OpenXR::capture_quadview_current_pose() {
+    std::scoped_lock lock{this->sync_assignment_mtx};
+    if (!quadview_latest_located_pose.get()) return {};
+    const auto& pose=*quadview_latest_located_pose.get();
+    if (!pose.quadview_locate_serial || pose.stage_views.size()!=2 || !pose.quadview_pose_valid ||
+        pose.frame_state.predictedDisplayTime<=0 || pose.frame_state.shouldRender!=XR_TRUE) return {};
+    const auto& h=pose.view_space_location.pose.orientation;
+    const double head_norm=double(h.x)*h.x+double(h.y)*h.y+double(h.z)*h.z+double(h.w)*h.w;
+    if (!std::isfinite(head_norm) || std::abs(head_norm-1.0)>.01) return {};
+    for (const auto& view : pose.stage_views) {
+        const auto& p=view.pose.position; const auto& q=view.pose.orientation; const auto& f=view.fov;
+        const double norm=double(q.x)*q.x+double(q.y)*q.y+double(q.z)*q.z+double(q.w)*q.w;
+        if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z) ||
+            !std::isfinite(norm) || std::abs(norm-1.0)>.01 ||
+            !std::isfinite(f.angleLeft) || !std::isfinite(f.angleRight) ||
+            !std::isfinite(f.angleUp) || !std::isfinite(f.angleDown) ||
+            f.angleLeft>=f.angleRight || f.angleDown>=f.angleUp) return {};
+    }
+    const auto& hp=pose.view_space_location.pose.position;
+    if (!std::isfinite(hp.x) || !std::isfinite(hp.y) || !std::isfinite(hp.z)) return {};
+    for (const auto& view : pose.quadview_head_views) {
+        const auto& p=view.pose.position; const auto& q=view.pose.orientation;
+        const double norm=double(q.x)*q.x+double(q.y)*q.y+double(q.z)*q.z+double(q.w)*q.w;
+        if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z) ||
+            !std::isfinite(norm) || std::abs(norm-1.0)>.01) return {};
+    }
+    return pose;
+}
+
+void OpenXR::invalidate_quadview_located_pose() {
+    std::scoped_lock lock{this->sync_assignment_mtx};
+    quadview_latest_located_pose.invalidate();
+    triview_pose_redirect=false;
+    triview_pose_located=false;
+    triview_newest_pose_frame=0;
+    triview_newest_pose_location={XR_TYPE_SPACE_LOCATION};
+}
+
+void OpenXR::invalidate_quadview_scene() {
+    std::scoped_lock lock{this->sync_assignment_mtx};
+    quadview_pending_pose.reset(); quadview_submitted_pose.reset();
+    quadview_continuity.reset(); quadview_holding=false; quadview_pose_generation=0;
+}
+
+void OpenXR::note_quadview_copy(PipelineState pose, uint64_t generation) {
+    std::scoped_lock lock{this->sync_assignment_mtx};
+    // Recheck under the same mutex used by GT world invalidation. A world
+    // change can occur after Present selected its source but before GPU copy.
+    if (!VR::get()->triview_source_epoch_accepts(pose.quadview_serial)) return;
+    const auto vr=VR::get();
+    if (!vr->is_quadview_renderer_active() || generation!=vr->mono_generation() ||
+        pose.stage_views.size()!=2 || !pose.quadview_serial) return;
+    if (quadview_pose_generation!=generation) {
+        quadview_submitted_pose.reset(); quadview_continuity.reset();
+    }
+    quadview_pose_generation=generation;
+    quadview_pending_pose=std::move(pose);
+}
+
+std::optional<OpenXR::PipelineState> OpenXR::capture_duoview_pose(uint32_t frame) {
+    std::scoped_lock lock{this->sync_assignment_mtx};
+    const auto& pose=this->pipeline_states[frame%QUEUE_SIZE];
+    if (!has_mono_frame(frame) || pose.frame_count!=frame || pose.stage_views.size()!=2) {
+        SPDLOG_WARNING_EVERY_N_SEC(2,
+            "[DuoView][Pose] Producer snapshot rejected source={} slot_token={} views={} mono_valid={}",
+            frame,pose.frame_count,pose.stage_views.size(),has_mono_frame(frame));
+        return {};
+    }
+    return pose;
+}
+
+void OpenXR::invalidate_duoview_scene() {
+    std::scoped_lock lock{this->sync_assignment_mtx};
+    duoview_pending_pose.reset(); duoview_submitted_pose.reset();
+    duoview_continuity.reset(); duoview_holding=false;
+}
+
+void OpenXR::note_duoview_copy(PipelineState pose, uint64_t generation) {
+    std::scoped_lock lock{this->sync_assignment_mtx};
+    const auto vr=VR::get();
+    if (!vr->is_duoview_renderer_active() || generation!=vr->mono_generation()) return;
+    duoview_pending_pose=std::move(pose);
+}
+
 OpenXR::PipelineState OpenXR::get_submit_state() {
+    if (const auto vr=VR::get(); vr->is_quadview_mode_selected()) {
+        std::scoped_lock lock{this->sync_assignment_mtx};
+        PipelineState selected{};
+        quadview_holding=false;
+        const auto scene=this->swapchains.find((uint32_t)SwapchainIndex::DOUBLE_WIDE);
+        const uint64_t handle=scene==this->swapchains.end() ? 0 : reinterpret_cast<uint64_t>(scene->second.handle);
+        if (vr->is_quadview_renderer_active() && quadview_pose_generation==vr->mono_generation()) {
+            if (quadview_pending_pose && !vr->triview_source_epoch_accepts(quadview_pending_pose->quadview_serial))
+                quadview_pending_pose.reset();
+            if (quadview_submitted_pose && !vr->triview_source_epoch_accepts(quadview_submitted_pose->quadview_serial)) {
+                quadview_submitted_pose.reset(); quadview_continuity.reset();
+            }
+            if (quadview_pending_pose) {
+                selected=std::move(*quadview_pending_pose); quadview_pending_pose.reset();
+            } else if (quadview_submitted_pose &&
+                quadview_continuity.can_hold(vr->mono_generation(),handle,GetTickCount64())) {
+                selected=*quadview_submitted_pose; quadview_holding=true;
+            } else if (quadview_continuity.ready()) {
+                // B41: nothing new and the hold window ran out: this frame goes to
+                // the headset without a scene image (black / SteamVR void).
+                ++triview_blank_frames;
+                SPDLOG_WARNING_EVERY_N_SEC(1,"[TriView][BlankFrame] no scene image sent: last real submit {} ms ago, hold window {} ms, blank frames so far {}",
+                    quadview_continuity.age_ms(GetTickCount64()),uevr::quadview::TriViewHold::window_ms(),triview_blank_frames);
+            }
+        }
+        // xrEndFrame uses the current frame time, while eye poses remain bound
+        // to the exact source image that was composed or explicitly held.
+        selected.frame_state=this->frame_state;
+        this->has_render_frame_count=false;
+        this->last_submit_state=selected;
+        return selected;
+    }
+    if (const auto vr=VR::get(); vr->is_duoview_renderer_active()) {
+        std::scoped_lock lock{this->sync_assignment_mtx};
+        PipelineState selected{};
+        const auto scene=this->swapchains.find((uint32_t)SwapchainIndex::DOUBLE_WIDE);
+        const uint64_t handle=scene==this->swapchains.end() ? 0 : reinterpret_cast<uint64_t>(scene->second.handle);
+        duoview_holding=false;
+        if (duoview_pending_pose) {
+            selected=std::move(*duoview_pending_pose);
+            duoview_pending_pose.reset();
+        } else if (duoview_submitted_pose &&
+            duoview_continuity.can_hold(vr->mono_generation(),handle,GetTickCount64())) {
+            selected=*duoview_submitted_pose;
+            duoview_holding=true;
+        }
+        selected.frame_state=this->frame_state;
+        this->has_render_frame_count=false;
+        this->last_submit_state=selected;
+        return selected;
+    }
     if (VR::get()->is_using_mono()) {
         // Do not relabel the latest pose as the rendered pose. Mono's two eyes
         // share one exact scene/pose/projection generation, never an AFR hold.
         std::scoped_lock lock{this->sync_assignment_mtx};
         const auto frame = mono_copied_frame.value_or(this->internal_render_frame_count);
         const auto& mono = mono_frames[frame % QUEUE_SIZE];
@@ -3867,12 +4096,15 @@ XrResult OpenXR::begin_frame(const char* caller) {
 
     return result;
 }
 
 XrResult OpenXR::end_frame(const std::vector<XrCompositionLayerBaseHeader*>& quad_layers, bool has_depth,
     uevr::ui_composition::Compositor* ui_composition) {
+    const bool quad_epoch_needed=VR::get()->is_quadview_mode_selected();
+    auto quad_epoch_lease=quad_epoch_needed ? VR::get()->triview_epoch_read() : uevr::triview::EpochGate::Read{};
+    if (quad_epoch_needed && !quad_epoch_lease) return XR_ERROR_SESSION_NOT_READY;
     std::scoped_lock _{sync_mtx};
 
     emit_openxr_state_probes(this, "end_frame");
 
     if (!this->can_run_frame_loop() || !this->got_first_poses || !this->frame_synced) {
         this->log_frame_lifecycle_state("end_frame refused because runtime was not ready");
@@ -4170,19 +4402,81 @@ XrResult OpenXR::end_frame(const std::vector<XrCompositionLayerBaseHeader*>& qua
     this->begin_profile();
     const auto collect_frame_timing = collect_openxr_frame_timing();
     const auto end_frame_start = collect_frame_timing
         ? std::chrono::steady_clock::now()
         : std::chrono::steady_clock::time_point{};
     auto result = xrEndFrame(this->session, &frame_end_info);
+    if (vr->is_quadview_mode_selected()) {
+        uevr::quadview::HookTraceRecord trace{};
+        trace.event=vr->is_quadview_renderer_active() && result==XR_SUCCESS && !projection_layer_views.empty()
+            ? "XR_SUBMIT" : "XR_END_RETURN";
+        trace.reason=projection_layer_views.empty() ? "no_projection_views" : "projection_views";
+        trace.generation=vr->mono_generation();
+        trace.serial=submit_state.quadview_serial;
+        trace.owner_generation=trace.serial ? trace.generation : 0;
+        trace.owner_serial=trace.serial;
+        trace.frame=submit_state.frame_count;
+        trace.canonical_frame=submit_state.frame_count;
+        trace.mode=7;
+        trace.source=trace.serial != 0;
+        trace.result=static_cast<int>(result);
+        trace.pending=projection_layer_views.size();
+        uevr::quadview::emit_hook_trace(27,trace);
+    }
     if (composed_ui && result != XR_SUCCESS && ui_composition) {
         ui_composition->reject_submission();
         vr->get_overlay_component().set_ui_composition_status(uevr::ui_composition::Status::failed);
         spdlog::warn("[UI Composition] Runtime rejected optional projection UI ({}); original layers restored on subsequent frames until toggled",
             this->get_result_string(result));
     }
-    if (mono && result == XR_SUCCESS && !projection_layer_views.empty()) {
+    if (vr->is_quadview_mode_selected()) {
+        std::scoped_lock lock{this->sync_assignment_mtx};
+        if (vr->is_quadview_renderer_active() && result==XR_SUCCESS && !projection_layer_views.empty()) {
+            if (!quadview_holding) {
+                const auto scene=this->swapchains.find((uint32_t)SwapchainIndex::DOUBLE_WIDE);
+                if (scene!=this->swapchains.end()) {
+                    quadview_submitted_pose=submit_state;
+                    quadview_continuity.submitted(vr->mono_generation(),
+                        reinterpret_cast<uint64_t>(scene->second.handle),GetTickCount64());
+                }
+            }
+            if (!quadview_holding) vr->note_quadview_xr_submit(quadview_pose_generation,
+                submit_state.quadview_serial,GetTickCount64());
+            vr->set_quadview_status(quadview_holding ? "Holding the last stereo QuadView image briefly" :
+                "Four engine histories: stereo QuadView image submitted");
+            SPDLOG_INFO_EVERY_N_SEC(2,"[QuadView][Submit] serial={} held={} eyes={}",
+                submit_state.quadview_serial,quadview_holding,projection_layer_views.size());
+        } else {
+            quadview_continuity.reset();
+            vr->set_quadview_status("Waiting for an executed four-view source and stereo output");
+        }
+    } else if (vr->is_duoview_renderer_active()) {
+        std::scoped_lock lock{this->sync_assignment_mtx};
+        if (const auto& stereo=vr->get_fake_stereo_hook(); stereo && this->frame_state.shouldRender==XR_TRUE) {
+            stereo->duoview_delivery.result(uevr::duoview::DeliveryEvent::submit,
+                submit_state.duoview_serial, result==XR_SUCCESS && !projection_layer_views.empty(), GetCurrentThreadId());
+        }
+        if (result==XR_SUCCESS && !projection_layer_views.empty()) {
+            if (duoview_holding) ++duoview_hold_submits;
+            else ++duoview_copy_submits;
+            if (!duoview_holding) {
+                const auto scene=this->swapchains.find((uint32_t)SwapchainIndex::DOUBLE_WIDE);
+                if (scene!=this->swapchains.end()) {
+                    duoview_submitted_pose=submit_state;
+                    duoview_continuity.submitted(vr->mono_generation(),
+                        reinterpret_cast<uint64_t>(scene->second.handle),GetTickCount64());
+                }
+            }
+            vr->set_mono_status(duoview_holding
+                ? "DuoView: holding the last submitted scene through a short source interruption"
+                : "DuoView: active two-source scene submitted to both eyes");
+        } else {
+            if (this->frame_state.shouldRender==XR_TRUE) ++duoview_empty_submits;
+            duoview_continuity.reset();
+        }
+    } else if (mono && result == XR_SUCCESS && !projection_layer_views.empty()) {
         vr->set_mono_status("Active: one current centered scene submitted to both eyes");
     }
     if (collect_frame_timing) {
         this->end_frame_timing.add(std::chrono::steady_clock::now() - end_frame_start);
     }
     this->end_profile("xrEndFrame");
diff --git a/src/mods/vr/runtimes/OpenXR.hpp b/src/mods/vr/runtimes/OpenXR.hpp
index 20a3d371..d095c1f1 100644
--- a/src/mods/vr/runtimes/OpenXR.hpp
+++ b/src/mods/vr/runtimes/OpenXR.hpp
@@ -23,12 +23,16 @@
 #include <common/xr_linear.h>
 
 #include <sdk/Math.hpp>
 
 #include "Mod.hpp"
 #include "../MonoRenderingPolicy.hpp"
+#include "../DuoViewFrame.hpp"
+#include "../TriViewHold.hpp"
+#include "../QuadViewGeometry.hpp"
+#include "../TriViewLocatedPose.hpp"
 #include "../ControllerTouchBindings.hpp"
 
 #include "VRRuntime.hpp"
 
 namespace uevr::ui_composition { class Compositor; }
 
@@ -115,12 +119,16 @@ struct OpenXR final : public VRRuntime {
     }
     VRRuntime::Error update_poses(bool from_view_extensions = false, uint32_t frame_count = 0) override;
     VRRuntime::Error update_render_target_size() override;
     uint32_t get_width() const override;
     uint32_t get_height() const override;
     uint32_t get_width_for_scale(float scale) const;
+    // B42: TriView low-resolution start. > 0 = this scale is used instead of the
+    // saved OpenXR_ResolutionScale (which is never changed). Ends once.
+    static inline std::atomic<float> triview_warmup_scale{0.f};
+    bool finish_triview_warmup(const char* reason);
     uint32_t get_height_for_scale(float scale) const;
 
     VRRuntime::Error consume_events(std::function<void(void*)> callback) override;
 
     VRRuntime::Error update_matrices(float nearz, float farz) override;
     VRRuntime::Error update_input() override;
@@ -267,12 +275,17 @@ public:
     std::atomic_uint32_t cached_depth_swapchain_height{};
     std::vector<XrView> views{};
     std::vector<XrView> stage_views{};
 
     //std::deque<std::vector<XrView>> stage_view_queue{};
     struct PipelineState {
+        uint64_t duoview_serial{};
+        uint64_t quadview_serial{};
+        bool quadview_pose_valid{};
+        uint64_t quadview_locate_serial{}; // Assigned only to a completed locate, never a scene-role stamp.
+        std::array<XrView,2> quadview_head_views{};
         XrFrameState frame_state{XR_TYPE_FRAME_STATE};
         XrSpaceLocation view_space_location{XR_TYPE_SPACE_LOCATION};
         std::vector<XrView> stage_views{};
         uint32_t frame_count{0}; // Updated on game thread prior to rendering
         uint32_t prev_frame_count{0}; // Updated right after xrWaitFrame is called
         uint32_t coherent_source_frame_count{};
@@ -329,15 +342,26 @@ public:
         return pipeline_states[frame_count % QUEUE_SIZE].view_space_location;
     }
 
     auto get_current_view_space_location() {
         std::scoped_lock _{ this->sync_assignment_mtx };
 
+        // Tri-view B15: role renders move internal_frame_count to frames that never get
+        // a located pose; recenter/origin/height must use the newest located head pose.
+        if (triview_pose_redirect && quadview_latest_located_pose.get()) {
+            return quadview_latest_located_pose.get()->view_space_location;
+        }
         return get_view_space_location(internal_frame_count);
     }
 
+    // Tri-view B15 (guarded by sync_assignment_mtx).
+    bool triview_pose_redirect{false};
+    bool triview_pose_located{false};
+    uint32_t triview_newest_pose_frame{0};
+    XrSpaceLocation triview_newest_pose_location{XR_TYPE_SPACE_LOCATION};
+
     auto get_frame_state(uint32_t frame_count) {
         std::scoped_lock _{ this->sync_assignment_mtx };
 
         const auto& result = pipeline_states[frame_count % QUEUE_SIZE].frame_state;
 
         if (result.predictedDisplayTime == 0) {
@@ -373,12 +397,31 @@ public:
 
         return false;
     }
 
     PipelineState last_submit_state{};
     PipelineState get_submit_state();
+    // Protected by sync_assignment_mtx. Scene-role frame stamps never mutate this copy.
+    uevr::triview::LocatedPose<PipelineState> quadview_latest_located_pose{};
+    void invalidate_quadview_located_pose();
+    std::optional<PipelineState> capture_quadview_pose(uint32_t frame);
+    std::optional<PipelineState> capture_quadview_current_pose();
+    void note_quadview_copy(PipelineState pose, uint64_t generation);
+    void invalidate_quadview_scene();
+    std::optional<PipelineState> quadview_pending_pose, quadview_submitted_pose;
+    uevr::quadview::TriViewHold quadview_continuity; // B41: configurable hold window
+    uint64_t triview_blank_frames{}; // B41: frames sent without a scene image
+    uint64_t quadview_pose_generation{};
+    bool quadview_holding{};
+    std::optional<PipelineState> capture_duoview_pose(uint32_t frame);
+    void note_duoview_copy(PipelineState pose, uint64_t generation);
+    void invalidate_duoview_scene();
+    std::optional<PipelineState> duoview_pending_pose, duoview_submitted_pose;
+    uevr::duoview::SubmitContinuity duoview_continuity;
+    bool duoview_holding{};
+    std::atomic<uint64_t> duoview_copy_submits{}, duoview_hold_submits{}, duoview_empty_submits{};
     struct Stalker2PairSubmit {
         std::array<XrView, 2> views{};
         uint64_t epoch{}, generation{};
         uint32_t source_frame{};
         bool reused{};
         bool scene_available{true};
@@ -395,12 +438,13 @@ public:
     }
     std::optional<Stalker2PairSubmit> m_stalker2_pair_submit{}; // sync_assignment_mtx
     std::atomic_bool m_stalker2_pair_pending{};
     void end_mono_transition_frame();
     void reset_mono_projection_history();
     void note_mono_projection();
+    void note_mono_projection(uint32_t source_frame);
     void note_mono_main_family(uint32_t frame, bool main_family);
     bool has_mono_pose(uint32_t frame);
     bool has_mono_frame(uint32_t frame);
     void note_mono_copy(uint32_t frame, bool success);
     struct MonoFrame {
         uint64_t generation{};

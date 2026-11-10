# Part E - Code map (B42.1 generated tree): where things are

Line numbers = generated tree. Files marked ADDED are full in Part D; changed upstream files are diffs in Part C.


## ADDED src/mods/vr/DuoViewConfig.hpp (232 lines)
Stage 8 — latch all DuoView settings/gaze exactly once per render frame. This header deliberately has no UEVR/UESDK/D3D/OpenXR dependency. Changes from ImGui/config reload cannot split the two UE views or the subsequent shader blend into different crop positions or densities.
Symbols: Settings@14, UiReconciled@54, FrameConfig@152, ConfigLatch@159, set_settings()@161, current_settings()@189, retire()@219

## ADDED src/mods/vr/DuoViewCropStability.hpp (131 lines)

Symbols: CropStability@5, reset()@114

## ADDED src/mods/vr/DuoViewD3D12.hpp (550 lines)

Symbols: ShaderConstants@11, Compositor@22, prewarm()@26, error()@348, recorded_commands()@349, gpu_milliseconds()@350, last_native_direct_xr()@351, last_native_source_extents()@352, srv_descriptor_refresh_count()@353, xr_rtv_refresh_count()@354, timing_frequency()@355, update_timing()@374, read_timing()@381, setup_timing()@391, IID_PPV_ARGS()@401, srv_format()@405, check()@434, prepare()@439

## ADDED src/mods/vr/DuoViewDelivery.hpp (215 lines)

Symbols: DeliveryTrace@14, DeliveryCounts@24, Delivery@29, Source@31, bool()@37, same_owner()@38, Command@45, owner()@48, attach()@49, family()@62, render()@78, executed()@93, block()@107, select()@115, retire()@128, counts()@136, reset_counts()@137, result()@138, note()@152, recent()@156, advance()@166, trace()@175, command_tail()@202

## ADDED src/mods/vr/DuoViewFrame.hpp (156 lines)
Stage 5 — per-frame DuoView coordination. No UE/D3D headers. New compositions require a complete pair with matching gaze/pose and method generation. Submit continuity may briefly reuse an unchanged released image with its original pose; it never recomposes stale source textures.  Backend integration contract: (1) begin() once per game-render frame with the *same* immutable layout, gaze and pose to
Symbols: FrameKey@25, SubmitContinuity@30, reset()@32, submitted()@33, can_hold()@36, RenderFrame@45, CompositedFrame@51, layout_valid()@57, FrameCoordinator@76, begin()@78, note_view()@93, note_gpu_complete()@113, consume_for_submit()@121, snapshot()@129, retire()@135, clear_locked()@141

## ADDED src/mods/vr/DuoViewGaze.hpp (137 lines)
Stage 4: gaze-to-Mono-frustum mapping and asynchronous validity policy. The caller must first convert the PSVR2 Toolkit combined calibrated ray from device/OpenXR coordinates into Joey's shared left-optical Mono basis. This module is a renderer-independent testable component, NOT a PSVR2 reader.
Symbols: Ray@14, UV@17, optical_ray()@21, ray_to_uv()@33, GazeCache@49, invalidate()@51, update()@57, RayRecovery@88, controls()@90, reset()@94, update()@95, age_ms()@125

## ADDED src/mods/vr/DuoViewGeometry.hpp (129 lines)
DuoView Mono: renderer-independent two-view layout, projection crop and compositor coordinate model. No UE/UESDK dependencies.
Symbols: renderer_view_index()@13, Rect@18, Layout@21, Tans@28, foveal_frustum()@82, apply_foveal_crop()@100, foveal_blend()@114, rendered_pixels()@123

## ADDED src/mods/vr/DuoViewMonoCopyD3D12.hpp (83 lines)
Stage 9 — safe single-width BGRA8 Mono image -> OpenXR double-wide copy. This is purpose-built for DuoView's full-FOV *composited* image. It does not alter Joey's original MonoD3D12::copy_scene contract. Call from the existing OpenXR DX12 copy command-list callback, after the compositor completes on the SAME queue or a properly waited dependency. Own both source/output resources until the swapchai
Symbols: bgra8()@15, stereo_destination_valid()@21

## ADDED src/mods/vr/DuoViewPSVR2Gaze.hpp (172 lines)
Stage 5: Joey DuoView PSVR2 Toolkit CAPI reader. No driver or OpenXR layer replacement. ABI: BnuuySolutions/PSVR2Toolkit projects/common/hmd2_gaze.h (328 bytes).
Symbols: Vec2@20, Vec3@21, Lens@22, WearableEye@24, Wearable@32, Foveated@39, Status@43, calibrated_ray()@56, projection_uv()@70, Counters@83, Reader@87, set_recovery_controls()@89, active()@93, counters()@94, initialize()@131

## ADDED src/mods/vr/DuoViewShaderSource.hpp (44 lines)
HLSL precompiled by Windows SDK fxc.exe in CI; no runtime D3DCompile.

## ADDED src/mods/vr/DuoViewState.hpp (148 lines)

Symbols: CameraPose@8, ViewFrame@12, NativeFrameBinding@23, native_frame_binding()@31, apply_frame_projection()@41, State@46, configure()@48, settings()@49, snapshot()@71, rectangle()@77, projection()@78, scene()@79, can_independent_shading()@87, camera()@95, camera()@101, family()@112, consume()@119, retire()@128, observe()@133

## ADDED src/mods/vr/HeadMovementScaling.hpp (16 lines)
Gains describe recentered player axes, not the runtime's arbitrary room axes. Keep this before the game's view rotation and after the recenter rotation. Do not use the live HMD orientation: looking around must not move the camera.

## ADDED src/mods/vr/QuadViewD3D12.hpp (825 lines)

Symbols: last_seam_analysis_milliseconds()@31, alignas@36, EdgeHistoryState@70, create()@74, SnapshotItem@95, snapshot_file_format()@104, write_snapshot_dds()@115, DepthInput@139, Compositor@154, sampling_format()@161, error()@171, prepared()@172, commands_recorded()@173, set_edge_history()@174, edge_submission_queue()@175, on_slot_retired()@330, gpu_milliseconds()@341, seam_gpu_milliseconds()@342, timing_frequency()@343, timing_ready()@344, uint64_t()@434, fail()@617, Source@622, flush_snapshot()@687, thread()@692, read_timing()@710, setup_timing()@731, IID_PPV_ARGS()@748, compatible_source()@756, valid_layout()@764

## ADDED src/mods/vr/QuadViewDelivery.hpp (612 lines)

Symbols: Delivery@17, DiagnosticsSnapshot@21, Source@31, bool()@44, same_owner()@45, EngineTicket@53, bool()@58, same_owner()@61, EngineRegistrationResult@77, register_engine_family()@86, register_engine_family_detailed()@92, tail_hooked_engine_family()@155, tail_hooked_engine_family()@164, executed_engine_family()@182, engine_commands_retired()@216, pending_engine_commands()@228, engine_tracking_overflowed()@236, diagnostics_snapshot()@241, register_bound()@267, family()@277, tail_hooked()@445, executed()@454, invalidate_reused_target()@478, select()@489, submitted()@509, execution_evidence()@518, retire()@527, retire_generation()@538, retire_all()@553, EngineSlot@564, FrameTicket@565, Slot@572, find()@578, find()@582, find_engine()@586, advance()@590

## ADDED src/mods/vr/QuadViewDepthContinuity.hpp (39 lines)

Symbols: Candidate@10, protectable()@18, newest_protected()@25

## ADDED src/mods/vr/QuadViewDepthIdentity.hpp (93 lines)
A producer identity, never a lookup by dimensions or current global GT key. The adapter may publish it only while executing one authenticated role-0 tail.
Symbols: DepthOwner@10, valid()@16, same_source()@20, matches()@24, DepthOwnerScope@31, DepthOwnerScope()@33, current()@38, DepthSubmissionSequence@45, acquire()@47, try_acquire()@48, DepthRecordingEpochs@54, current()@56, reset()@62, prune()@66, matches()@71, depth_copy_complete()@85

## ADDED src/mods/vr/QuadViewFamilyRouting.hpp (303 lines)

Symbols: FamilyIdentity@13, FrozenFamilyIdentity@20, FamilyRoute@33, bool()@36, PartialFamilyIdentity@39, valid_frozen_identity()@47, ScopedMainFamilyMutation@209, bool()@225, select_single()@227, restore()@235, MainFamilyDispatchResult@264, bool()@267

## ADDED src/mods/vr/QuadViewFocusLift.hpp (24 lines)
Robust fit to 52,584 flat-gray sky samples. These are source-domain gain parameters, not an assertion about the game's underlying postprocess.
Symbols: Profile@12

## ADDED src/mods/vr/QuadViewFramePacket.hpp (92 lines)

Symbols: RuntimeEye@11, RhiExecutionEvidence@20, valid_for()@26, FramePacket@37, valid()@46

## ADDED src/mods/vr/QuadViewGaze.hpp (184 lines)
Stereo adaptation of the published v186.1 DuoView gaze mapping. The CAPI ray is recovered once in head space; each eye then applies its own optical rotation and its own full projection matrix before the crop is frozen.
Symbols: valid_perspective_projection()@19, normalize()@28, multiply()@40, Tangents@89, projection_from_tangents()@106

## ADDED src/mods/vr/QuadViewGeometry.hpp (466 lines)

Symbols: Rect@13, Crop@18, FocusPoint@23, Layout@27, LayoutLatch@153, get()@155, freeze()@160, reset()@169, any_of()@187, color_source_rect()@296, source_extents()@302, triview_source_extents()@325, apply_native_local()@331, valid_view_index()@359, eye_for_view()@360, is_focus_view()@361, apply_focus_crop()@364, ResizeSizes@386, ResizeGate@389, Decision@397, confirm_live()@404, set_cooldown_ms()@409, cooldown_ms()@410, cancel_latch()@413, reset()@414, latched()@444, current_pose_frame()@459, pose_frame_newer()@463

## ADDED src/mods/vr/QuadViewHookTrace.hpp (59 lines)
Scalar observation only. No source leases, command pointers to dereference, retirement decisions, GPU operations or runtime synchronization live here.
Symbols: HookTraceRecord@10, HookTraceGate@29, Decision@31, visit()@35, Site@52, Epoch@53

## ADDED src/mods/vr/QuadViewNativeDelivery.hpp (831 lines)

Symbols: execute()@46, NativeDrainScope@57, Identity@59, current()@73, DiagnosticsSnapshot@94, Command@115, bool()@121, TailTicket@126, bool()@129, RuntimeEvent@132, bool()@135, TailOwnerBatch@142, retain()@148, AttachResult@166, bool()@169, publishable()@173, ExecutionResult@176, diagnostics_snapshot()@187, RenderTrace@306, hook()@357, sync_frame()@459, runtime_event()@465, claim_runtime_event()@471, executed_tail()@485, executed()@562, reset()@576, Slot@589, Participant@604, Tail@605, ContentStamp@614, find_index()@623, find_tail()@633, find_tail()@637, find_tail()@641, find_tail()@645, find_participant()@663, find_participant()@669, poison_slot()@675, poison_tail()@681, latch_completion()@689, stamp_matches()@709, find_content()@716, find_content()@734, target_is_live()@738, content_matches()@746, invalidate_resource()@754, record_write()@779, invalidate_ambiguous_tail()@798, finish_quartet()@811

## ADDED src/mods/vr/QuadViewNativeRetirementDiagnostics.hpp (75 lines)

Symbols: NativeRetirementListCount@17, NativeRetirementDiagnostics@24, to_string()@65

## ADDED src/mods/vr/QuadViewNativeTargets.hpp (96 lines)
The renderer writes four independent UE-owned targets before a stereo packet can be published. Keep the identity proof independent of D3D/UE headers so it can be exercised by the portable contract tests.
Symbols: NativeTargetIdentity@12, valid_native_target_quartet()@21

## ADDED src/mods/vr/QuadViewNgxDepth.hpp (577 lines)
Tri-view B11: capture the DLSS depth input of the PERIPHERY render every frame. Hooks (safetyhook, inline): NVSDK_NGX_D3D12_EvaluateFeature(_C) and Create/ReleaseFeature(_C) in nvngx_dlss.dll / _nvngx.dll, plus ID3D12CommandQueue::ExecuteCommandLists (vtable slot 10) to know when the game's command list holding our copy has been submitted. Never interferes with DLSS: inputs are restored before the
Symbols: NgxParameters@39, ngx_success()@58, ngx_uint()@59, ngx_resource()@65, DepthSnapshot@70, PeripheryDepth@89, pool_usage()@92, self()@102, set_expected()@105, restart_quiescent()@110, discard_completed_for_new_xr_session()@129, capture_supported()@147, set_enabled()@148, install()@158, latest_recent_submitted()@199, reason_name()@221, Stats@228, stats()@230, prune_locked()@270, reject()@282, Guard@285, transition()@287, inspect()@294, uint64_t()@329, IID_PPV_ARGS()@384, submitted()@441, install_reset()@477, evaluate()@514, create()@524, release()@534, execute_commands()@540

## ADDED src/mods/vr/QuadViewNgxSelect.hpp (39 lines)
Tri-view B11: portable periphery-depth selection rules (unit-tested on Linux).  Identity: the periphery is the only DLSS evaluation whose output size equals the shared context view. make_layout() guarantees the two foveas never have a size inside the conflict window (see unique_context_factor), so an output size match is unambiguous; no timing or thread ownership is involved. a within pct percent 
Symbols: close()@13, matches_periphery()@20, focus_conflicts_context()@26, unique_context_factor()@34

## ADDED src/mods/vr/QuadViewPSVR2Gaze.hpp (138 lines)
ID7 adapter for the exact v186.1 PSVR2 Toolkit ABI and validation rules. It deliberately returns the recovered calibrated HEAD-space ray so the caller can project it once per true stereo eye. ID6's reader stays intact.
Symbols: Counters@27, Reader@33, set_recovery_controls()@35, active()@40, available()@41, counters()@43, read_ray()@51, initialize()@86

## ADDED src/mods/vr/QuadViewProducer.hpp (340 lines)

Symbols: Key@14, KeyHash@19, operator()@20, ViewRecord@27, CameraPose@35, GazeEvidence@41, Snapshot@48, construction_complete()@69, histories_complete()@88, camera_complete()@92, Producer@105, rectangle_call()@148, projection_matrix()@176, camera()@187, context_camera()@198, note_compositor_record()@261, snapshot()@272, frozen()@279, retire()@285, retire_generation()@293, retire_all()@309, CompositorEvidence@316, compositor_evidence()@317, find_pending()@325, view_index_for_rect()@329

## ADDED src/mods/vr/QuadViewResourceReuse.hpp (43 lines)

Symbols: NativeResourceReusePlan@9, reuses()@12

## ADDED src/mods/vr/QuadViewRetirement.hpp (20 lines)
Presentation resource reconfiguration may proceed while new engine view owners continue to arrive. A rendering-mode transition must drain them.
Symbols: requires_engine_retirement()@14

## ADDED src/mods/vr/QuadViewSettings.hpp (239 lines)
Stereo-specific subset of the published v186.1 DuoView controls. Settings that only affect ID6's two-source capture or XR output path are not exposed
Symbols: Settings@14, Reconciled@76, same_settings()@206

## ADDED src/mods/vr/QuadViewSnapshot.hpp (32 lines)
Tri-view B11 proof snapshots (shared by the compositor and the menu). B11 proof snapshots: one request copies the final double-wide eye image, the three source renders and the periphery depth of the NEXT composite into CPU readback buffers; after that GPU slot retires, a background thread writes
Symbols: snapshot_requested()@14, snapshots_written()@15, snapshot_mutex()@16, snapshot_directory_storage()@17, set_snapshot_directory()@18, snapshot_directory()@19, last_snapshot_message_storage()@20, last_snapshot_message()@21, last_depth_state()@26, depth_state_name()@27

## ADDED src/mods/vr/QuadViewStatus.hpp (55 lines)

Symbols: StatusFacts@7, StatusTracker@11, Submission@13, submitted()@16, snapshot()@23, state()@28, display_state_text()@43

## ADDED src/mods/vr/QuadViewStatusPanel.hpp (17 lines)
Production and headless tests use the same container. All variable-height diagnostics belong inside it; following controls have a fixed cursor origin.
Symbols: draw_status_panel()@8

## ADDED src/mods/vr/QuadViewViewDemand.hpp (65 lines)

Symbols: source_admission_open()@9, DrawDemand@19, DrawDemandLatch@29, get()@40, reset()@54

## ADDED src/mods/vr/TriViewAdmission.hpp (23 lines)
Native source creation needs renderer/RHI progress. A warm-up family is engine-only: render its context once, never the otherwise unused role 1. Restore on every exit so Unreal's view/history bookkeeping stays unchanged.
Symbols: BootstrapViewCount@7, BootstrapViewCount()@9

## ADDED src/mods/vr/TriViewEpochGate.hpp (57 lines)
One GT writer; nonblocking close while existing XR callbacks drain. New callbacks cannot enter between the zero-reader check and world invalidation. Nested work on the same thread belongs to its already admitted transaction.
Symbols: EpochGate@10, Read@12, bool()@25, read()@34, try_close()@43, closed()@47, open()@48

## ADDED src/mods/vr/TriViewGammaTables.hpp (41 lines)
Like DuoView's static Native Fix table: Unreal may invoke its resource's virtual destructor after the last plugin packet owner has retired. These tiny immutable tables outlive all engine resources; they retain no textures.
Symbols: Entry@33

## ADDED src/mods/vr/TriViewHold.hpp (45 lines)
B41: TriView-only replacement for uevr::duoview::SubmitContinuity. Same interface and rules (no hold before the first submit, no hold across a mode/generation or swapchain change), but the hold window is a user setting (100..1000 ms, default 250) instead of DuoView's fixed 100 ms. DuoView keeps its own class unchanged.
Symbols: TriViewHold@13, set_window_ms()@19, window_ms()@22, reset()@24, submitted()@25, can_hold()@28, ready()@32, age_ms()@34

## ADDED src/mods/vr/TriViewLocatedPose.hpp (25 lines)
Caller holds the runtime's pose mutex. Only a successful locate may publish. Invalidation preserves the sequence so old draw packets cannot match a new epoch. Copy assignment reuses the two-view vector capacity in PipelineState.
Symbols: publish()@11, invalidate()@18, get()@19

## ADDED src/mods/vr/TriViewVramGuard.hpp (85 lines)
Tri-view B42: keep video memory below a safe share of the DXGI budget.  Headset finding (9-10 Nov 2026): STALKER 2 + TriView BSODs (0x139) when the game process fills its VRAM budget (~10 GB on a 12 GB RTX 5070). Our own colour targets are small (13-56 MB per set); the growth comes from Unreal's per-size scene buffers (G-buffer, Lumen, DLSS histories ...) that each new view size allocates while th
Symbols: source_pixels()@31, build_estimate()@39, limit_bytes()@41, allows()@49, snap_fraction()@76

## CHANGED src/hooks/D3D12Hook.cpp
- +847 (6 lines) in: HRESULT D3D12Hook::present_internal(IDXGISwapChain3* swap_chain, UINT sync_inter

## CHANGED src/mods/FrameworkConfig.hpp

## CHANGED src/mods/VR.cpp
- +60 (4 lines) in: 
- +4001 (6 lines) in: bool VR::should_force_native_stereo_fix_same_pass() const {
- +8762 (303 lines) in: void VR::on_post_engine_tick(sdk::UGameEngine* engine, float delta) {
- +13622 (30 lines) in: void VR::on_pre_calculate_stereo_view_offset(void* stereo_device, const int32_t
- +13702 (180 lines) in: void VR::service_mono_transition_game_thread() {
- +13883 (9 lines) in: void VR::service_mono_transition_game_thread() {
- +13893 (24 lines) in: void VR::service_mono_transition_game_thread() {
- +14256 (12 lines) in: void VR::on_config_load(const utility::Config& cfg, bool set_defaults) {
- +15272 (39 lines) in: void VR::handle_keybinds() {
- +15660 (7 lines) in: void VR::on_post_present() {
- +15669 (62 lines) in: void VR::on_post_present() {
- +15735 (57 lines) in: void VR::on_post_present() {
- +15974 (6 lines) in: void VR::on_draw_sidebar_entry(std::string_view name) {
- +15987 (408 lines) in: void VR::on_draw_sidebar_entry(std::string_view name) {
- +16406 (7 lines) in: void VR::on_draw_sidebar_entry(std::string_view name) {
- +17885 (8 lines) in: void VR::on_draw_sidebar_entry(std::string_view name) {
- +17895 (3 lines) in: void VR::on_draw_sidebar_entry(std::string_view name) {
- +18167 (13 lines) in: void VR::on_draw_ui() {
- +18898 (579 lines) in: void VR::update_statistics_overlay(sdk::UGameEngine* engine) {

## CHANGED src/mods/VR.hpp
- +39 (8 lines) in: 
- +475 (14 lines) in: public:
- +518 (155 lines) in: public:
- +760 (6 lines) in: public:
- +1364 (6 lines) in: private:
- +1802 (128 lines) in: private:
- +2229 (21 lines) in: private:
- +2255 (21 lines) in: private:
- +2521 (27 lines) in: public:
- +2781 (4 lines) in: public:

## CHANGED src/mods/vr/CompatibilityPolicy.hpp

## CHANGED src/mods/vr/D3D12Component.cpp
- +1554 (28 lines) in: bool D3D12Component::shf_scene_consumers_retired(bool include_stable_copy_produc
- +2557 (41 lines) in: void D3D12Component::sync_depth_target_stability_guard_state(VR* vr) {
- +2599 (57 lines) in: vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
- +3179 (3 lines) in: vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
- +5392 (258 lines) in: vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
- +6786 (8 lines) in: void D3D12Component::on_post_present(VR* vr) {
- +7249 (26 lines) in: bool D3D12Component::setup() {
- +7281 (30 lines) in: bool D3D12Component::setup() {
- +7341 (6 lines) in: std::optional<std::string> D3D12Component::OpenXR::create_swapchains() {
- +7499 (18 lines) in: std::optional<std::string> D3D12Component::OpenXR::create_swapchains() {
- +7598 (4 lines) in: std::optional<std::string> D3D12Component::OpenXR::create_swapchains() {
- +7708 (3 lines) in: std::optional<std::string> D3D12Component::OpenXR::create_swapchains() {
- +7712 (35 lines) in: void D3D12Component::OpenXR::destroy_swapchains() {
- +7754 (11 lines) in: void D3D12Component::OpenXR::destroy_swapchains() {
- +7766 (39 lines) in: void D3D12Component::OpenXR::destroy_swapchains() {
- +7961 (3 lines) in: void D3D12Component::OpenXR::release_acquired(uint32_t swapchain_idx) {
- +8428 (3 lines) in: bool D3D12Component::OpenXR::copy(
- +8473 (4 lines) in: bool D3D12Component::OpenXR::copy(
- +8480 (6 lines) in: bool D3D12Component::OpenXR::copy(
- +8515 (6 lines) in: bool D3D12Component::OpenXR::copy(

## CHANGED src/mods/vr/D3D12Component.hpp
- +427 (4 lines) in: private:
- +517 (4 lines) in: private:

## CHANGED src/mods/vr/FFakeStereoRenderingHook.cpp
- +1 (3 lines) in: 
- +126 (4 lines) in: 
- +155 (35 lines) in: static_assert(static_cast<int32_t>(VR::SYNTHETIC_DIBR_SINGLE_VIEW) ==
- +6074 (6 lines) in: std::optional<ValidatedNativeFixTextureChain> validate_native_fix_texture_chain(
- +13496 (9 lines) in: void FFakeStereoRenderingHook::on_frame() {
- +13568 (102 lines) in: std::string FFakeStereoRenderingHook::build_hook_provenance_json() {
- +16235 (3 lines) in: void FFakeStereoRenderingHook::attempt_hook_fsceneview_constructor() {
- +21877 (7 lines) in: struct SceneViewExtensionAnalyzer {
- +21957 (7 lines) in: struct SceneViewExtensionAnalyzer {
- +21983 (19 lines) in: struct SceneViewExtensionAnalyzer {
- +22024 (40 lines) in: struct SceneViewExtensionAnalyzer {
- +22073 (36 lines) in: struct SceneViewExtensionAnalyzer {
- +22113 (3 lines) in: struct SceneViewExtensionAnalyzer {
- +22127 (9 lines) in: struct SceneViewExtensionAnalyzer {
- +22137 (9 lines) in: struct SceneViewExtensionAnalyzer {
- +22166 (5 lines) in: struct SceneViewExtensionAnalyzer {
- +22175 (156 lines) in: struct SceneViewExtensionAnalyzer {
- +22338 (3 lines) in: struct SceneViewExtensionAnalyzer {
- +22418 (44 lines) in: struct SceneViewExtensionAnalyzer {
- +22569 (14 lines) in: struct SceneViewExtensionAnalyzer {
- +23284 (69 lines) in: sdk::FSceneView* FFakeStereoRenderingHook::sceneview_constructor(sdk::FSceneView
- +23773 (22 lines) in: sdk::FSceneView* FFakeStereoRenderingHook::sceneview_constructor(sdk::FSceneView
- +25404 (89 lines) in: void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
- +25885 (14 lines) in: void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
- +26332 (115 lines) in: void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
- +26777 (8 lines) in: void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
- +26797 (19 lines) in: void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
- +26829 (8 lines) in: void FFakeStereoRenderingHook::begin_render_viewfamily_real(void* render_module,
- +27657 (217 lines) in: void FFakeStereoRenderingHook::begin_render_viewfamily(ISceneViewExtension* exte
- +28122 (6 lines) in: void FFakeStereoRenderingHook::begin_render_viewfamily(ISceneViewExtension* exte
- +28450 (5 lines) in: FFakeStereoRenderingHook::get_native_stereo_frame_packet_for_submit(int32_t rend
- +28528 (5 lines) in: FFakeStereoRenderingHook::get_native_stereo_frame_packet_for_submit(int32_t rend
- +28561 (15 lines) in: FFakeStereoRenderingHook::get_native_stereo_frame_packet_for_submit(int32_t rend
- +29033 (90 lines) in: void FFakeStereoRenderingHook::pre_render_viewfamily_renderthread(ISceneViewExte
- +31080 (17 lines) in: void FFakeStereoRenderingHook::adjust_view_rect(FFakeStereoRendering* stereo, in
- +31151 (21 lines) in: void FFakeStereoRenderingHook::adjust_view_rect(FFakeStereoRendering* stereo, in
- +31198 (27 lines) in: __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
- +31431 (6 lines) in: __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
- +31524 (12 lines) in: __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
- +31540 (8 lines) in: __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
- +31550 (3 lines) in: __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
- +31562 (9 lines) in: __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
- +31693 (23 lines) in: __forceinline void FFakeStereoRenderingHook::calculate_stereo_view_offset(
- +31775 (9 lines) in: __forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_
- +31900 (87 lines) in: __forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_
- +32075 (6 lines) in: __forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_
- +32101 (12 lines) in: __forceinline Matrix4x4f* FFakeStereoRenderingHook::calculate_stereo_projection_
- +32283 (6 lines) in: uint32_t FFakeStereoRenderingHook::get_desired_number_of_views_hook(FFakeStereoR
- +41413 (642 lines) in: struct VRRenderTargetManager_Base::UE58UITextureOwner {

## CHANGED src/mods/vr/FFakeStereoRenderingHook.hpp
- +43 (11 lines) in: 
- +93 (3 lines) in: public:
- +100 (29 lines) in: public:
- +386 (10 lines) in: public:
- +608 (5 lines) in: protected:
- +802 (9 lines) in: public:
- +924 (9 lines) in: public:
- +956 (33 lines) in: public:
- +998 (3 lines) in: public:
- +1149 (4 lines) in: public:
- +1261 (7 lines) in: public:

## CHANGED src/mods/vr/MonoRenderingPolicy.hpp
- +17 (4 lines) in: inline constexpr int32_t method_id = 5;

## CHANGED src/mods/vr/OverlayComponent.hpp

## CHANGED src/mods/vr/RenderingMethodSetting.hpp
- +42 (3 lines) in: public:

## CHANGED src/mods/vr/d3d12/CommandContext.cpp
- +667 (3 lines) in: void CommandContext::execute() {

## CHANGED src/mods/vr/d3d12/CommandContext.hpp
- +51 (5 lines) in: struct CommandContext {

## CHANGED src/mods/vr/runtimes/OpenXR.cpp
- +456 (4 lines) in: void OpenXR::on_draw_ui() {
- +470 (3 lines) in: void OpenXR::on_draw_ui() {
- +1600 (26 lines) in: VRRuntime::Error OpenXR::update_poses(bool from_view_extensions, uint32_t frame_
- +1769 (29 lines) in: uint32_t OpenXR::get_width_for_scale(float scale) const {
- +1802 (3 lines) in: uint32_t OpenXR::get_width() const {
- +1828 (3 lines) in: uint32_t OpenXR::get_height() const {
- +1988 (4 lines) in: void OpenXR::reset_mono_projection_history() {
- +2011 (11 lines) in: void OpenXR::note_mono_projection() {
- +2537 (90 lines) in: void OpenXR::log_everspace2_coherent_submit_summary_if_needed() {
- +2628 (51 lines) in: OpenXR::PipelineState OpenXR::get_submit_state() {
- +4102 (3 lines) in: XrResult OpenXR::end_frame(const std::vector<XrCompositionLayerBaseHeader*>& qua
- +4408 (17 lines) in: XrResult OpenXR::end_frame(const std::vector<XrCompositionLayerBaseHeader*>& qua
- +4431 (46 lines) in: XrResult OpenXR::end_frame(const std::vector<XrCompositionLayerBaseHeader*>& qua

## CHANGED src/mods/vr/runtimes/OpenXR.hpp
- +29 (4 lines) in: 
- +125 (4 lines) in: struct OpenXR final : public VRRuntime {
- +281 (5 lines) in: public:
- +348 (5 lines) in: public:
- +356 (6 lines) in: public:
- +403 (19 lines) in: public:

# TriView B25: stable diagnostics and dormant trace CPU reduction

Based exactly on B24 Windows-CI-passing commit 5c9c909cd40561d5812470b52ad06ab78bd2e43d. B24 four-depth-lookups compositor is unchanged. B21-51 is the headset-confirmed rollback; B22-54 is the 25-sample comparator.

## Root cause of diagnostic flicker

The status text is a shared atomic pointer. Successful Game Thread beginning, Render Thread finishing source renders, source registration, and OpenXR successful submission all wrote messages on every frame. The UI displayed whichever finished last. "Waiting" therefore did not necessarily indicate dropped source frames.

The primary QuadView StatusTracker correctly uses successful fresh XR submits with a one-second timeout; retain it, its fixed-height menu panel, and genuine rejection/stall messages. Remove three normal-success status writes and the normal first-eye pending-pose message while still invoking the pose-capture function. Leave successful XR status writing the stable value.

## Additional CPU audit

B21 headset log had 79,403 lines; 60,414 HookTrace lines, 1,662 one-per-second depth status reports, 1,025 successful throttled XR submits, 42 OutputWaiting and seven CopyRejected warnings. "No stage views to submit" appears 1,313 times; root cause and visual impact are not confirmed. B22 made HookTrace output opt-in, but left construction of its detailed records, map/pointer reads and several std::chrono timing calls in the render/RHI path.

B25 checks the existing one-time cached UEVR_VERBOSE_HOOK_TRACE switch BEFORE detailed hook/RHI record construction. RHI trace clocks become conditional, and the explicitly optional NativeDelivery RenderTrace pointer is passed only when detailed tracing is enabled. The original trace is available by setting UEVR_VERBOSE_HOOK_TRACE=1 before launching the game.

Actual render and producer ownership paths, RHI mutex scope, OpenXR frame synchronization, source-slot fences and GPU state, NGX depth selection, shader, fovea geometry, and VRAM allocations remain unchanged. Do not change vtable_mutex lifetime or depth pool fences without targeted race proofs.

Do not infer FPS or VRAM gains from static analysis or CI. CI must compile the generated backend and run GPU WARP stereo/depth tests, B24 shader test, B25 generated-status/trace assertions and portable ASan/UBSan before this is headset-ready.

The headset check after CI: status detail should remain stable while primary indicator is Active; check fovea and periphery, hand/weapon occlusions, saved-game reload; compare FPS/frame pacing at same settings. If primary becomes Stalled or crash recurs, return to B21-51.

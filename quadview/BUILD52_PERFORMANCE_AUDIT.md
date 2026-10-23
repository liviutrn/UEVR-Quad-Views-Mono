# Build52 Quad Views performance audit

This is a read-only audit of Build51’s `upload/log(20261023-084331).txt` and the Quad Views source path. Build52 implements no performance optimization; it adds an opt-in CPU dispatch timer. The log contains no CPU or usable GPU timing result, so the cost rankings below are hypotheses to measure, not speed claims.

## Evidence from the log

The 437.613-second capture contains 14,447 lines and 7,374,396 bytes. During the two active ID7 windows (326.488 seconds), it contains 9,525 HookTrace lines totaling 6,177,379 bytes: about 29 lines/s and 18.9 kB/s. HookTrace site counters imply at least 598,515 gate visits during those windows (about 1,833/s); `HookTraceGate::visit` takes a mutex for each attempted event, including suppressed events. The synchronous logger and gate add work, but these counts do not show that logging materially reduced frame performance.

The sampled per-site counters reached 15,426 and 24,562 `RT_ENTER` visits in the two ID7 generations. Copy-enqueue counters reached 3,850 and 6,127; XR-submit counters reached 3,856 and 6,137. These imply roughly 30.6 quartet copy/submit events per second and about 120 renderer-family entry visits per second. They are diagnostic event-rate proxies, not verified FPS or GPU-completion counts.

The log records four source targets at 5136×2040 twice, then 7368×2928. That is 10,477,440 versus 21,573,504 texels per source, a 2.059× increase; across four allocations, 41,909,760 versus 86,294,016 texels. The log does not identify why the dimensions changed, and it does not record the saved quality settings or target format. These are texel counts, not byte or frame-time estimates.

## Source and compositor costs

Each quartet dispatches four singleton Unreal view families through the renderer. That repeated engine rendering and family work is the strongest CPU-cost hypothesis. Build52’s `native_dispatch` timer covers dispatch setup and the four renderer calls, but not the preceding whole-target liveness preflight or the rest of the game. It does not split the four calls or isolate scene gathering. Use it for a short measurement, then add per-role timing only if the combined result warrants it.

The source targets use full atlas dimensions because the current layout contract stores each view rectangle in atlas coordinates. `QuadViewGeometry::make_layout` places right-eye rectangles at an eye-width offset; `FFakeStereoRenderingHook::adjust_view_rect` returns those absolute rectangles. Target creation receives `atlas_width` and `atlas_height`, while `QuadViewD3D12::Compositor::record_sources` requires each source to match those dimensions and the shader samples using the atlas rectangles. Role-sized targets would need a coordinated source-local rectangle and compositor-coordinate redesign; changing only the allocation size would break this contract.

With code defaults only—focus crop 0.50×0.50, context scale 0.20, density 1.0—the rectangle coverage is about 29% of a double-wide output. For the logged dimensions, rounded per-eye context/focus rectangles are approximately 514×408 and 1284×1020, then 737×586 and 1842×1464. The log does not confirm those defaults were active. Rectangle coverage does not prove the engine clears or writes only those pixels; a GPU capture is needed to establish actual pass behavior.

No per-frame Quad Views `ClearRenderTargetView` or intermediate `CopyResource` was found in the plugin path. `CreateRenderTarget2D` receives an initial clear color when a target set is built; the engine renderer then draws the selected view. Presentation passes the four sources to one fullscreen-triangle compositor draw into the OpenXR double-wide image, with resource transitions around the sampling. Unreal’s internal render-pass clear behavior is not established by this source audit.

The default sharpen setting is 1.0. In `QuadViewComposite.hlsl`, a focused output pixel gets the center sample plus six additional Glamarye taps; with default crop geometry, the focus region covers 25% of output pixels. At 7368×2928 and a 30-event/s diagnostic rate, disabling sharpening would remove up to about 0.97 billion texture-sample instructions per second by operation count. Filtering, caching, feathering, and the unverified settings affect actual work; this is not a measured GPU speedup. It is a reversible GPU experiment, not a CPU optimization, and should follow shading-parity validation.

Repeated reflection is not an apparent per-frame hotspot: `find_property` for the two SceneCapture flags occurs during source-target-set construction/rebuild. Layout/settings/gaze work is frozen once per draw, rather than recomputed for every singleton. One repeated safety check is visible: the dispatch performs a four-owner `quadview_native_targets_live` preflight, then repeats the full four-owner validation before each of four slots (20 owner validations per quartet). Each owner check uses three guarded pointer reads. Any reduction must retain the full preflight and validate each target before use; preserve the existing ownership and retirement behavior.

## Follow-up experiments, safest first

1. Measure the CPU path with Build52’s dispatch timer for a short, repeatable scene. If it is material, split timings by role and separate renderer calls from source validation/gather work. Do not infer CPU relief from lower pixel resolution alone; it leaves four renderer submissions in place.
2. After the primary-pass shading fix is accepted, compare sharpen 1.0 and 0.0 with the compositor GPU timer and the same scene. Restore the preferred quality setting after the test.
3. Identify what caused the log’s 2.059× source-target extent increase. Compare resolution settings in a controlled run before changing output scale; resolution affects GPU pixels and memory, with a visible quality tradeoff.
4. If CPU measurements point to target validation, first test removing only the duplicate full-set check immediately before slot zero. Preserve the initial full-quartet preflight and subsequent per-slot liveness protection; do not weaken source or retirement ownership.
5. In a dedicated profiling build, compare HookTrace enabled/disabled after capturing the transition evidence needed for diagnosis; Build52 does not add a HookTrace toggle. HookTrace emitted about 6.18 MB during the active windows, but its CPU impact is unmeasured. Avoid changing the sampling gate until an A/B shows a benefit.
6. Treat role-sized source targets as a larger design experiment. They may reduce allocation footprint, but require independent source-local and output-atlas rectangles plus renderer, history, compositor, and lifetime validation.

No performance optimization is implemented in Build52 by this audit.

# Independent Sol 6.1 Medium review: Build 46 and future work

Reviewed 22 October 2026. Source: `af215afd3a0a624d9c1878e96e836fa9fbf26a4d` in the isolated `quadviews-future` checkout; generated `backend/` inspected read-only. Read Build 46 status, both prior Sol reviews, native delivery/target/retirement integration, timing instrumentation, and CVar ownership. This report is the only file written. No production changes, push, headset run, or Windows rebuild performed.

## Decision

Build 46 addresses the earlier identified construction, shared-tail, family-routing and physical-content problems at source level. The parent confirms Windows run 39687797421 passed all 60 tests and the package was verified. I did not independently repeat that CI/package authentication. Passing CI permits runtime evaluation; it establishes neither sustained headset output nor lighting, FOV, GPU ordering, performance or VRAM acceptance.

I found no additional confirmed rendering blocker in this bounded review. The next useful implementation is a small observation-only diagnostic increment, followed by a controlled headset measurement. Active adaptive screen percentage is a separate experimental phase, contingent on a validated timing source, effective resolution control and exclusive settings ownership. Do not combine it with a rendering architecture rewrite.

Preserve accepted Build 40 geometry/gaze/stereo behavior and current accepted ID6 baseline. Published v186.1 Glamarye and stable Build182 ancestry are the relevant DuoView anchors; experimental 198/first-person branches are not substitutes.

## Priorities and smallest concrete followup

| Priority | Work | Why / acceptance evidence |
| --- | --- | --- |
| P0 | Validate Build 46 in headset against Build 40 and accepted ID6 | Rendering correctness is still the largest uncertainty. No optimization can compensate for missing or incoherent images. |
| P1 | Add bounded delivery/retirement snapshots | Distinguish missing callbacks, quarantined sharing, full ledgers, fence lag and unavailable output without changing safety behavior. |
| P2 | Measure whole-scene cost and static SP response | Establish whether cost is GPU pixel work, repeated scene setup, CPU work, memory pressure, or pacing. |
| P3 | Implement adaptive policy in shadow mode | Validate decisions, settings lease and frame association before any automatic resolution writes. |
| P4 | Enable an opt-in controller for one verified configuration | Require effective resolution readback, supported temporal upscaler and independent replay/headset validation. |

**Recommended first patch:** expose a fixed-size snapshot from existing ledgers and retirement stages, optionally aggregate it into existing diagnostic export. Keep logging at most once per five seconds and on bounded state changes. No per-frame formatted logs, new resource owners, fences, waits, timeout release, queue scheduling, automatic recovery, or active SP controller.

Concrete hooks/fields:

* `QuadViewDelivery.hpp`: existing `pending_engine_commands(generation)` and `engine_tracking_overflowed(generation)` already answer part of the question; expose source/engine occupancy and observed peak occupancy under the existing mutex. The default engine/source capacity is 16. Report generation alongside every count.
* `QuadViewNativeDelivery.hpp`: `hook_batch`, `executed_tail`, `claim_runtime_event`, `slots_`, tail storage, `pending_count[4]`, rendered/hooked/executed masks and attach status identify failure stage. Add a compact snapshot of counts, representative oldest incomplete serial and role masks; summarize attached/duplicate/quarantined/overflow/rejected results. It has 32 quartet slots, not the same capacity as Delivery. Never retain a `Command`, `Source` or shared owner in diagnostics.
* `QuadViewNativeTargetOwner::RetireQueue` from `apply_quadview_native_retirement.py`: summarize pending/staged/in-flight/ready counts, peaks, last successful signal, cached last completion, signal queue/device identity and signal failures in `service_after_present`. Use the existing polling result; do not add a blocking fence query or queue submission. Sample stage counts while already traversing the lists where practical. Tag first-enqueue time only if age is included; report age, never use it to release anything.
* Existing `NativeFrameDiagnostics.hpp` provides a bounded try-only recorder and explicitly keeps its results out of acceptance decisions. Reuse that philosophy and export pathway instead of building a second unbounded event recorder. Export or format on UI/support paths, outside ledger/retirement locks. A dropped diagnostic snapshot must remain harmless.

A minimal first patch can omit age and cumulative counters if lifecycle accounting would enlarge scope: occupancy, overflow/quarantine reason, representative masks, and fence progression already distinguish important stalls. Snapshot queue identity is evidence of the observed signal queue, **not proof** that every Unreal producer use is ordered before it. Do not imply otherwise in UI or logs.

Tests: empty/partial/full/reset ledger snapshots; shared tail and cross-quartet quarantine; snapshot attempts interleaved with execution/reset; overflow visible without clearing its latch; diagnostics disabled/dropped leaves selection and retirement results identical. For retirement aggregation, test stage-count accounting with a portable helper only if useful, and inspect production wiring. Keep source export/checkpoint tests and existing native/family/provenance suites. No GPU-integration claim from a helper test.

## Performance hypotheses that require measurement

Four independent engine renders imply repeated scene setup, culling, shadow/exposure/history and transient work. Four full atlas color targets add roughly three atlas-sized color allocations relative to one atlas, before histories and temporary resources. This is an architectural cost, not a measured slowdown. Record actual dimensions, formats and retained target generations; distinguish estimated owned color bytes from actual process residency/budget telemetry.

Measure the same reproducible interior and outdoor route with fixed gaze/camera where possible: native reference, accepted ID6, Build40 and Build46. Hold runtime/upscaler/graphics settings constant. Collect scene GPU time, GT/RT busy time, native rendered frame cadence, callback/delivery occupancy, peak residency/budget and tail/fence lag; report median plus p95/p99 and spikes around loading/toggles. Measure compositor time separately.

Only then choose an optimization: lower internal SP if pixel-sensitive GPU work dominates; address repeated renderer CPU work if CPU-bound; investigate allocation/history churn if memory or transitions dominate. Smaller per-view targets would change layout/projection/history integration and require stronger proof. Do not first merge views, share histories, alter PRIMARY discipline, shrink FOV, skip focus renders, parallelize extra queues or switch global RHI dispatch. Those changes cross accepted correctness boundaries. Do not increase queue capacities to conceal missing retirement, or free conservative owners after a deadline.

## Adaptive FPS implementation plan for current ID6 and ID7

### 1. Define the controlled quantity and validate a timing provider

A target of 40 **native game-rendered frames/s** means 25 ms per rendered frame. A 120 Hz HMD has an 8.33 ms display period; it does not change that target to 120 native FPS. Reprojection may permit a one-third cadence but runtime policy must be measured. Frame generation, repeated composites, `Present`, OpenXR calls and distinct render families are not independent native scene frames. Associate samples with one completed pair/quartet serial and generation; consume each sample once.

Verified current source does not expose a ready-to-use whole-scene GPU timing provider in the reviewed path. `QuadViewD3D12.hpp` brackets its fullscreen `DrawInstanced`; `DuoViewD3D12.hpp` timestamps compositor work. `OpenXR.cpp` uses `steady_clock` around wait/begin/end and pose work: CPU durations, including pacing, not scene GPU time. A broader source search found no installed whole-scene GPU timing API adapter. That negative search is bounded, not proof that the game/UE cannot supply one.

IDs 6/7 require OpenXR through `MonoRenderingPolicy.hpp` and VR capability gating. OpenVR frame timing is therefore unavailable in the active configuration; do not open another runtime/session to obtain it. OpenXR predicted display period is a cadence hint, not GPU duration.

Define `TimingSample {generation, scene_serial, gpu_ms, cpu_busy_ms, native_interval_ms, sample_age, source, valid}` with optional fields and explicit scope. Prefer a validated existing UE dynamic-resolution/GPU timing integration if the shipped title exposes one. Otherwise a supported GPU capture/profiler first establishes ground truth; a custom DX12 timestamp provider is a later project requiring command-queue, async-compute dependency and whole-scene boundaries. A timestamp around an arbitrary CPU hook or four callback tails does not establish that scope. Never stall GPU readback for control. Without trustworthy feedback, remain shadow-only or disabled.

### 2. Establish that primary SP is effective and supported

Use UE internal **primary** screen percentage. Keep runtime render scale, output texture size, FOV/projection, focus/context crop, eye pose and gaze policy fixed. Epic distinguishes primary resolution scaling before UI from secondary scaling; secondary screen percentage is not the intended dynamic actuator. [Epic UE5.5 documentation](https://dev.epicgames.com/documentation/en-us/unreal-engine/screen-percentage-with-temporal-upscale-in-unreal-engine?application_version=5.5).

Probe static primary SP at three supported values, with settling, separately in accepted ID6 and Build46. Read CVar and actual primary view dimensions/effective fraction; a successful CVar write alone proves no rendering effect when a game/upscaler driver overrides it. Verify all two/four views receive the same fraction for one scene draw and that final targets/mapping remain valid.

Inspect shipped UE dynamic-resolution support before writing a competing controller. If it provides correct timing, one policy across all repeated families, upscaler compatibility and bounded settings ownership, prefer it. Merely finding `r.DynamicRes.*` names is insufficient. Never enable builtin and custom policies simultaneously. If neither path is authenticated, record unsupported and stop.

### 3. Lease settings without fighting existing writers

`CVarManager.hpp` already exposes float `r.ScreenPercentage` with 10..150 UI bounds. Those bounds are not a safe adaptive range. Use the intersection of user quality bounds, title/backend limits and upscaler-supported input bounds; initially choose a conservative tested range, not automatic 10..150.

Add one explicit CVarManager-owned session lease: capture initial actual value and ownership revision, refuse activation if SP is frozen or builtin DRS is active, and use the existing validated setter/readback approach from GT. `on_pre_engine_tick` already processes frozen values and console scripts; do not independently write from VR/render/RHI callbacks. UI edits, freeze requests, scripts, mode changes or unexpected readback changes revoke/suspend the lease. An external writer wins; do not force a higher CVar priority to take it back. Existing diagnostics do not report engine owner priority, so do not pretend that attribution is available.

Persist only controller preferences; never write transient SP into saved frozen values, game configs or startup scripts. On ordinary disable restore the captured value only if the lease is still valid and actual value still equals the last successful controller write. Preserve external edits. Revalidation is required after load/session/mode/upscaler changes.

### 4. Latch once at a proven game-thread draw boundary

Compute a proposed fraction from completed older samples, then apply/latch before main pair/quartet construction. Verify actual CVar-to-family screen-percentage capture order in the engine integration; `on_pre_engine_tick` alone is not proof. `quadview_begin_frame` freezes draw identity/layout; extend the draw contract with effective SP/revision if needed, and provide the equivalent once-per-pair latch for DuoView. Reject conflicting partial updates instead of writing between four singleton renderer calls. No SP writes from gaze callbacks. A resolution change must not create four incompatible temporal histories or target-owner generations.

### 5. Keep the first controller simple

Start with a tested finite policy: Disabled, Warmup, Settling, Active, Suspended. Example tuning to evaluate, not validated defaults: 2 seconds stable warmup; sample-age cap tied to measured pipeline latency; 0.5-second evaluation windows; 1-second settling after writes; reduce 2 percentage points after two sustained over-budget windows, raise 1 after four comfortably under-budget windows. Use a deadband and reserve a measured portion of the 25 ms for non-scene work. Faster descent than ascent limits hunting. Clamp every proposal, handle NaN/zero/stale/out-of-order samples, and reset windows on generation changes.

Freeze decisions during menus/loading, lost session, camera cuts and known shader/streaming disturbances; do not let a single hitch collapse quality. If resolution reductions fail to improve scene time/native cadence after settling, suspend further descent and flag likely CPU/fixed-cost/pacing limitation. A frame cap or reprojection lock can hold observed FPS constant while GPU headroom changes, so FPS alone cannot drive upward corrections. Diagnose CPU busy time separately from sleep/wait time. Unknown frame generation state or unverified cadence mapping keeps activation gated. At minimum SP report target unmet; at maximum stop increasing. Avoid PID, predictive gaze policies or multiple quality actuators initially.

### 6. Upscaler and temporal gates

NVIDIA DLSS SR exposes supported dynamic min/max input sizes conditionally; use actual integration capabilities rather than generic percentages. [DLSS guide](https://github.com/NVIDIA-RTX/Streamline/blob/main/docs/ProgrammingGuideDLSS.md).

The current NVIDIA DLSS-RR guide explicitly states DRS is unsupported and changing input resolution reinitializes the denoiser. Its generic dynamic-size fields do not override that warning. Default RR/unknown integration to blocked until the shipped game/version has specific verified support. [DLSS-RR guide](https://github.com/NVIDIA-RTX/Streamline/blob/main/docs/ProgrammingGuideDLSS_RR.md). Keep output dimensions, motion-vector/jitter scaling, resource extents and per-view histories coherent. Repeated history resets or eye/focus divergence are stop conditions, not accepted quality tradeoffs.

## Regression and release gates

| Phase | Required coverage | Stop condition |
| --- | --- | --- |
| Build46 runtime acceptance | Startup, shadowed interiors, both eye boundaries, stereo depth, FOV, gaze, load/resize, ID7↔ID6/native, sustained play | Black output, brightness/shadow regression, incoherent source, stranded transition |
| Diagnostics patch | Existing suites plus snapshot/reset/full/quarantine checks; overlay exports and Windows build | Acceptance behavior changes, extra owners/waits, unbounded logging |
| Static SP probe | Current ID6 and ID7 independently; supported upscaler modes; actual view fractions and history behavior | Ineffective CVar, mixed fraction within draw, target churn, recurrent history reset |
| Shadow controller | Deterministic synthetic GPU-bound/CPU-bound/capped traces, spikes, stale feedback, bounds, lease conflicts, restore cases | Hunting, fake FPS classification, unintended writes/persistence |
| Opt-in controller | Same-scene A/B, native frame cadence and p95/p99, temporal quality, memory, transitions | Worse stability/latency, sustained oscillation, external-writer fight, unverified feedback |

This plan can improve quality under a measured GPU budget; it cannot promise 40 FPS in CPU-bound or fixed-cost scenes. The first implementation should make the remaining uncertainty measurable while preserving Build46's ownership and accepted baseline behavior.

## Build 47 bounded implementation review

22 October 2026: reviewed the actual isolated diff and generated production integration. Approve this candidate for Windows compilation; no blocking defect found. The final design uses the existing on-demand Hook Provenance JSON export instead of the optional periodic logs proposed above. It adds independent try-lock POD summaries for delivery, native quartet state, RHI map sizes and bounded retirement lists. Busy data is omitted, retained completed owners remain visible, and shared tails include multiple roles within one attachment.

Snapshots retain no Source/Command/COM owners, nest no ledger locks, initialize no retirement queue and perform no GPU/COM queries. Retirement metadata is captured alongside existing polls/successful signals; device removal is explicit and historical fence values are not compared. The separately approved staged-head guard skips an unused GetDevice call while preserving pending staging, next-present signaling, fence polling and GT cleanup. No measured FPS gain is established.

New tests cover ledger states, actual lock contention, overflow, shared/ambiguous tails and bounded retirement aggregation. Production COM retirement remains an integration test limitation. Local passes are reported by the implementation worker; Windows production/WARP and headset gates remain outstanding at this review point. No active adaptive screen-percentage controller is included.

# DuoView and QuadView: implementation decisions and performance plan

22 October 2026. Joint review: supervising root, GPT-6.1 Sol Medium and a fresh
GPT-6 Luna Max worker. See `FUTURE_SOL61_REVIEW.md` and
`FUTURE_LUNA_REVIEW.md` for the independent opinions. This document records
the selected implementation and resolves differences between their proposals.

## Starting point and what is established

Build 46 source is `af215afd3a0a624d9c1878e96e836fa9fbf26a4d`.
Windows run [39687797421](https://github.com/liviutrn/MUSE-UEVR-DUOVIEW/actions/runs/39687797421)
passed the production DLL/injector build, 60 CTests and frontend checks.
The exact installable ZIP has SHA-256
`a7a7b4600b2c20d18f82ff5ae226b29771449f21e39c6a97d5151f5f7c8c361e`.
All 20 packaged files match the CI hashes; eight generated production files
match the reviewed source after accounting for Windows line endings.

Build 46 fixes the reviewed shared-tail, family-routing and physical-content
ownership defects and retains the Build 45 construction-readiness correction.
Its four independent PRIMARY sources implement the native path for both eyes'
context and focus. These facts do not establish actual headset lighting,
stability, queue ordering or a speedup. No Build 46 headset trace was available
when this plan was prepared. Keep accepted Build 40 geometry, gaze and stereo
as the comparison, and keep the ID6 source path intact.

The published DuoView baseline is v186.1 with Glamarye, source
`12986083d2706a0a3351006cd6323dd4970505d6`, with stable Build182 ancestry.
The newer 198/first-person branches are experiments; this work does not merge
their unrelated weapon or UI changes into the accepted renderer.

## First implementation: inspect stalls without changing rendering

The team selected a diagnostic-only followup. It extends the existing support
export: **Debug → Stereo Hook Options → Hook Provenance Diagnostics →
Refresh/Export Hook Provenance JSON**. The existing default-off diagnostic UI
is sufficient. No new periodic sampler, log loop or resolution controller is
needed for this increment.

The export will provide independently sampled, best-effort sections:

| Section | Useful evidence | Limits |
| --- | --- | --- |
| QuadView delivery | Generation, source/engine occupancy and overflow latch | Busy is unavailable, never zero |
| Native quartet delivery | Live owners/tails, ambiguous tails, representative oldest retained serial and rendered/hooked/executed masks | A mask describes callback bookkeeping, not a GPU completion fence |
| Queued RHI records | Scalar retained-record count under the existing map lock | No map/owner copies or unlocked enumeration |
| Native target retirement | Bounded pending/staged/in-flight/ready counts; last observed successful signal and poll identities/values | Counts can be lower bounds when truncated; one poll does not summarize all fences |

Snapshots are fixed scalar/POD data, obtained with try-locks. Release each lock
before acquiring another or formatting JSON. Exporting must retain no packet,
UObject, COM resource or command owner and initiate no discovery, GPU query,
queue submission, fence, wait or cleanup. Fence values carry their fence
identity: values from different fence/device epochs cannot be compared.
`UINT64_MAX` from an already-existing completion poll means device removal,
not completed work. Unknown or contended data is explicitly marked.

This increment observes existing safety decisions. It never clears
an overflow latch, frees an owner after a timeout, forces a transition or
changes rendering/retirement order. Missing evidence stays conservative.
The implementation is isolated from the unchanged Build 46 package.

One separately reviewed CPU work reduction is included: skip the retirement
queue's `GetDevice` call when there are no already-staged owners to classify
or signal. Existing in-flight fence polling, end-of-present pending staging,
next-present signaling and game-thread cleanup keep their order. This removes
an unnecessary COM query on those frames; no measured FPS gain is claimed.

Required checks include empty/partial/full/reset snapshots, shared and
ambiguous tails, overflow visibility, try-lock contention, bounded traversal
and truncation, fence-identity separation and unchanged selection/drainage.
Run the existing source-export checks, ownership/provenance suites, Windows
production compile, WARP tests, DuoView regressions and frontend checks.

## Performance work ranked by what measurements reveal

1. **Validate the image and delivery first.** Compare the same shadowed
   interior and outdoor route against Build 40 and accepted DuoView. Check
   both eye boundaries, shadows/brightness, FOV, stereo depth, gaze, loading,
   resize, repeated mode changes and sustained output. The new export should
   make a failed callback or retirement stage identifiable.
2. **Measure the whole workload.** Record native rendered cadence, scene GPU
   time, GT/RT busy time, compositor time separately, peak VRAM/budget and
   delivery/fence state. Use median, p95/p99 and transition spikes. Keep game,
   upscaler, runtime, refresh and reprojection settings identical. No such
   headset measurements are supplied by CI.
3. **Choose the matching optimization.** Pixel-sensitive GPU cost supports
   internal resolution adaptation. CPU/repeated scene cost calls for a
   different investigation. Allocation spikes or memory pressure call for
   resource/history analysis. Four full-atlas sources have an allocation
   cost, but useful raster area does not predict total GPU time.
4. **Prototype larger renderer changes separately.** Right-sized source
   targets could reduce memory, but require explicit preservation of source
   rectangles, projection/FOV and history identity. Shared histories, fewer
   PRIMARY renders, merged families or new queues cross the current
   correctness boundary. Do not implement them before profiles and tests
   justify the risk. Compositor optimization is worthwhile only if its own
   measured cost is material.

## Adaptive FPS controller: implementation plan for both modes

The requested actuator is Unreal's **primary internal screen percentage**.
Keep HMD/output dimensions, FOV/projection, gaze/crop geometry, stereo pose,
sharpening and graphics quality settings fixed. Apply one chosen fraction to
the whole DuoView pair or QuadView quartet, not separately to each source.

### Gate A: prove useful feedback and effective control

The current DuoView/QuadView GPU timers measure their compositor work, not
the full Unreal scene. OpenXR wait/begin/end measurements are CPU durations.
Both current modes require OpenXR, so OpenVR compositor timing cannot be
assumed available; do not open another runtime session to obtain it.

First investigate the shipped UE5.5 dynamic-resolution implementation. Prefer
it if its timing, platform support, upscaler support and fraction capture can
be authenticated for all repeated view families. CVar presence alone is not
support. Never run builtin and custom resolution controllers together.

If builtin DRS is unsuitable, define an explicit timing-provider interface:
generation, admitted draw serial, mode, covered view mask, scope, queue/device
identity, measured GPU interval, optional CPU busy/native interval, age and
validity. A custom nonblocking D3D12 provider is a separate integration task:
its boundaries and async dependencies must cover the actual scene work.
Arbitrary hook timestamps and plugin-pass timing are insufficient. Consume
each completed sample once. No GPU readback wait is permitted.

Probe several static primary percentages in current DuoView and QuadView
independently, with settling. Confirm actual internal view dimensions or
effective fraction, all 2/4 views' agreement and preserved output mapping.
Reading back the requested CVar alone does not prove that DLSS or a game
screen-percentage driver used it. If timing or effective control cannot be
authenticated, expose unsupported/shadow status and stop before automatic
writes. Do not claim a functioning controller from a portable simulation.

### Gate B: acquire a narrow settings lease

`CVarManager` already exposes `r.ScreenPercentage` and enforces frozen values
on the game thread. Add a single controller-owned lease through that manager;
do not create an independent writer in renderer callbacks. Initially refuse
activation when manual freeze or another dynamic-resolution policy owns the
setting. Capture the baseline and ownership revision only on successful
activation. UI edits, scripts, game/upscaler overrides, unexpected readback or
session/mode changes suspend or revoke the lease. The external writer wins.

Persist only controller preferences. Never save transient percentages as the
user's frozen value, game configuration or startup script. On ordinary disable,
restore the baseline only if ownership is still valid and the current value
equals the last successful controller write. Preserve external edits.
On a mode/session/upscaler transition, discard old-generation decisions and
attempt the same conditional restore at the last safe game-thread boundary
before releasing the lease. If restoration is unsafe or another writer has
taken over, do not force it; report any residual transient value explicitly.

### Gate C: implement and replay a small policy in shadow mode

Use a shared portable policy with Disabled, Warmup, Active, Settling and
Suspended states. Keep separate DuoView/QuadView profiles and reset feedback
windows on mode/generation/upscaler changes. A typical user target is 40 native
game frames/s: 25 ms, not the headset's 120 Hz period. Generated, reprojected,
repeated or separately rendered source views are not additional native frames.

Proposed tuning for evaluation, not validated shipping defaults: two seconds
of stable warmup, half-second feedback windows, a deadband, a one-second
settling interval after a write, a two-percentage-point reduction after
sustained overload and a one-point recovery after longer sustained headroom.
Reserve measured non-scene work within the budget. Prefer time-based windows
to frame-count thresholds whose duration changes with FPS. No PID or multiple
quality actuators in the first version.

Bounds are the intersection of the user's quality limits, title/backend limits
and the active upscaler's supported input sizes. The UI's 10..150 range is not
an adaptive safety range. Capture the initial percentage as the default
maximum; do not impose a generic 50% floor on a user already using 25%.
An empty supported interval disables adaptation.
If the authenticated upscaler minimum exceeds the captured baseline, treat
the interval as unsupported rather than raising resolution to enable the
feature. Size alignment and rounding must still yield one valid effective
fraction across every view in the draw.

Reject NaN/invalid/stale/duplicate samples and incomplete view masks. Hold
during loading, lost session, pause, transitions and known transient stalls.
Use CPU busy time and pacing evidence to avoid lowering quality for CPU,
frame-cap or fixed-cost bottlenecks. FPS alone cannot reveal GPU headroom
under a cap. If settled reductions do not improve the measured workload,
suspend further descent. At the quality floor report target unmet; do not
silently lower another setting.

### Gate D: wire one game-thread change before draw construction

Validate where UE captures its effective screen-percentage driver. Apply a
coalesced decision before that boundary and freeze its effective fraction and
settings revision for the full 2/4-view draw. `on_pre_engine_tick` is a
candidate setter location, not proof of capture order. No writes between the
four singleton native calls or from gaze/render/RHI callbacks. Keep output
targets and ownership tokens valid while older draws finish.

DLSS SR requires the actual integration's supported dynamic-size range.
NVIDIA's current Ray Reconstruction guide says input-size changes reinitialize
its denoiser and DRS is unsupported; RR/unknown paths remain blocked until
specific verified support exists for the shipped game integration. Do not
change the user's DLSS mode automatically. Stop on repeated history resets,
mixed eye/focus fractions, temporal instability or allocation hitches.

### Gate E: opt-in runtime acceptance

Replay synthetic GPU-bound, CPU-bound, capped, noisy, stale, loading and mode
change traces; test bounds, hysteresis, leases, conditional restore and absence
of transient persistence. Then run separate headset A/B tests for current
DuoView and QuadView, including effective fraction per view, frame-time tails,
quality, memory, gaze/FOV/stereo and transitions. Enable actual adaptation only
for a verified configuration and leave it off by default. The controller can
trade resolution for measured GPU headroom; it cannot guarantee 40 FPS where
CPU or fixed costs already exceed the budget.

## Primary references

- [Epic: primary and secondary screen percentage, UE5.5](https://dev.epicgames.com/documentation/en-us/unreal-engine/screen-percentage-with-temporal-upscale-in-unreal-engine?application_version=5.5).
- [NVIDIA: DLSS SR capability and dynamic input-size limits](https://github.com/NVIDIA-RTX/Streamline/blob/main/docs/ProgrammingGuideDLSS.md).
- [NVIDIA: DLSS Ray Reconstruction and resolution-change constraints](https://github.com/NVIDIA-RTX/Streamline/blob/main/docs/ProgrammingGuideDLSS_RR.md).

These references describe engine/SDK behavior, not a tested statement about
the particular STALKER 2 shipping integration. Runtime acceptance remains an
explicit dependency of the adaptive controller plan.

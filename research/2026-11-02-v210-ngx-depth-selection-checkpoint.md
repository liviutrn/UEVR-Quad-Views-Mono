# DuoView v210 NGX depth-matching checkpoint — 2026-11-02

## Objective and user correction

Continue v207/v208 as a **mono** DuoView performance and depth-dependent
foveal sharpening project. Liviu uses Cheeky r13 **NR ONLY**, not its SR mode.
Expected default sharpening: near 5.0, far 1.0, smoothly interpolated in meters.
Manual foveal DLSS source selection and visual depth proof are necessary, as
with the previous synthetic-stereo experiments. This is **not** permission to
replace DuoView mono with synthesized stereo.

**Useful user heuristic:** with their usual crop ~0.5x0.5, density ~1,
periphery ~0.2, the fovea's active DLSS-SR output should have the greater
pixel count. The actual settings allow different configurations (e.g., small
crop and high periphery scale), so maximum *allocation* size is not reliable.

## Evidence / state

- **CI-proven:** v208 #215 built and passed, but raises only the fixed Glamarye
  strength from 0..2 to 0..5. v209 #217 passed Windows CI: curve math,
  invalid-parameter handling and stored in-game controls. Its shader remains
  fixed strength, even if staged distance mode is enabled.
- **Source-read:** old CI69/70/76/81 NGX source browsers identified native
  D3D12 DLSS evaluation, `Depth`, `Color`, `Output`,
  `DLSS.Render.Subrect.Dimensions.Width/Height`, `OutWidth/Height`,
  `DLSS.Input.Depth.Subrect.Base.X/Y`, and `Jitter.Offset.X/Y`.
  CI69 used a manual pin key of feature+output extent, not an evaluation index;
  feature release invalidates it.
- **Source-read:** prior CI76 producer ticket offered RHI interval/extent
  correlation. It explicitly did **not** certify the exact per-view camera
  or source-frame matrix. Do not promote an extent-only association to
  confirmed GPU depth/color frame provenance.
- **v210 implementation:** the observer registers up to 24 bounded candidates
  while explicitly enabled in the DuoView UI. Expected fovea/periphery output
  sizes come directly from the immutable frame packet used by
  `compositor.record_native`, **not** the large Native source color allocation.
  The selection algorithm accepts a unique live NGX-SR output whose dimensions
  exactly match the expected fovea; retains a stable auto pin; never switches to
  an ambiguous equal-size candidate; manual pins override; feature release,
  resize and age invalidate stale matching. Largest allocation is not mistaken
  for largest active fovea output.
- **Not yet implemented:** GPU depth pixels are **not** copied, linearized,
  aligned to the fovea image or sampled by the fused shader in v210.
  The live image still uses fixed Glamarye strength. Do not label v210 as
  distance-aware sharpening or as headset-verified depth visualization.

## Why exact dimension matching alone is insufficient to consume depth

The expected active SR output size and DLSS render/input percent can identify
a candidate **class**. But DLSS's `Depth` is an NGX input resource, not a
guaranteed persistent GPU texture owned by DuoView. The game can reuse its
allocation for the periphery; the GPU queue containing its producing commands
might be distinct from the OpenXR compositor queue. A raw retained D3D12
resource pointer and the current CPU frame number are inadequate.

The old CI51/CI69 capture pipeline guarded GPU resource state and queues,
used GPU-only copies for retained depth, and tracked source and output
dimensions. Reuse its *lifetime/queue principles* in the v207 code without
copying synthetic-stereo warp or DSV galleries.

## Required next implementation — single selected fovea depth

1. In the existing NGX D3D12 Evaluate observer, on successful **SR feature**
   and matching the active frozen fovea packet, snapshot only the active depth
   subrect on the GPU. Reject unknown/unsupported format, ambiguous feature,
   missing input, or unproven queue provenance. Never keep only a borrowed
   NGX `Depth` pointer beyond its valid producer callback.
2. Retain per-slot `ID3D12Resource` ownership and a producer completion fence;
   make the OpenXR queue wait on the producer fence **on the GPU**. Retire the
   copied texture only after the actual XR submission/command-slot fence.
   No CPU readback, per-frame allocations, busy wait, or shader compilation.
3. Pass `DuoViewFrameKey`, captured source view, crop/projection,
   active depth subrect, sampled input/render dimensions, jitter, and
   reset/resolution generation with the snapshot. An exact output size does
   not excuse missing frame provenance. Prefer the manually pinned candidate
   when the user selects one; never substitute it with a different feature
   silently. When no match, use normal fixed sharpening with an explicit status.
4. Add optional **fovea-only raw depth visualization**, then **linear meters**
   visualization and a sample confidence/status indicator in the headset before
   making the effect default. Depth convention (reversed-Z or otherwise),
   frozen near/projection coefficients and world-to-meters scaling must be
   validated from the actual producer, not assumed. Source rect and crop
   mapping must account for game DLSS-SR and possible nested Cheeky NR.
5. When verified, sample the copied foveal depth once in the existing
   `PSNativeMain` (no extra fullscreen pass), use its linear camera-forward
   meters with the tested v209 `DistanceSharpenCurve`. Preserve v207
   shader path bit-for-bit when toggle off or valid depth missing.

## Verification and measurement

- CPU tests: manual selection, exact dimension ranking, ambiguity, independent
  feature handles, reset/resize/release, invalid subrects, stale candidate and
  frame-key mismatch, NaN/zero near/far, inversions, frame latching.
- GPU WARP tests: supported formats, subrect/jitter coordinate mapping, output
  equals baseline when disabled/fallback, copy state restoration, queue/fence
  retirement, no previous-frame depth leakage, missing depth no black pixels.
- Headset: check source candidate preview near a known close object and distant
  geometry, verify changing near/far values affects **only foveal image**, then
  compare GPU ms/VRAM against v207 at fixed resolutions. Keep 3 test questions
  maximum.
- Performance source audit remains separate: two separate UE render families
  cost about 7ms each even at 200x200 per Liviu's prior headset measurement,
  so resizing only the pixel rect does not remove per-family fixed cost.
  Observe active Native source allocations and current NR-only Cheeky runtime,
  including cache-retention behavior, before claiming FPS/VRAM improvements.

Baseline: `claude/v207-auto-fov-vram-periphery` @ `4020a443`.
v208 branch: `experiment/v208-depth-sharpen-optimization-20261102`.
v209 branch: `experiment/v209-distance-sharpen-curve-20261102`.
v210 branch: `experiment/v210-ngx-manual-depth-20261102`.

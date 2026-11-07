# TriView B32 – stronger, temporally stabilized hybrid seam
Date: 2026-11-07
Base: B31-110 commit `008c9f7548c43f5977c1197c4180cddb435c64de`.
Headset rollback: B31-110 (anti-vignette excellent, basic blend nearly invisible)
and B28-103 (older, user-tested rendering lifecycle).

## Headset findings from owner
- B31 anti-vignette is excellent. KEEP CALIBRATION AND CENTER BRIGHTNESS.
- B31 basic feather + anti-vignette nearly hides seam.
- B31 adaptive still visible/weak, gains flicker/pump and inward transition
  hard cap 64 px is too small. User wants 2–3x stronger.
- Cheeky DLSS NR runs BEFORE game SR, ONLY ON THE TWO FOVEAS. Periphery
  is not NR-processed; adaptive should compare FINAL post-SR/NR fovea
  textures to unmodified periphery. It already analyzes those source
  textures in the compositor and needs no Cheeky hook or new render pass.
- Overall headset FPS B31 about unchanged; avoid new heavy passes.

## B32 implementation
- New shipped ADAPTIVE correction strength=1.20 (B31 .85; range 0–1.5).
  Max auto relative gain=.50 (B31 .20; range .01–.75). At full
  confidence the maximum relative change is about 60% vs 17%, ~3.5x.
  Still bounded and clamped by the existing per-eye confidence.
- Color match strength=.70; local residual=.65, both adjustable.
- New Temporal Enabled: ON by default. Stability 0..1 (default .85)
  controls the EMA rate, roughly alpha=.10 per successful observation;
  independent gain delta limiter default .05 per GPU frame (range
  .005..30). Confidence <.20 holds the previous valid gain briefly,
  instead of resetting to 1 and flickering.
- Temporal history stores only 18 float4 gain/confidence records (288 B):
  two global and 16 local periphery corrections. Each compositor command
  slot owns a 288-B readback buffer; CS writes new smoothed gains;
  after the draw it copies only that tiny buffer to readback. CPU reads
  ONLY after the existing slot fence retires; no GPU waits, cross-slot
  UAV sharing, history textures or extra UE/DLSS rendering.
- Fence-retired history uses a monotonic serial and mutex. Out-of-order
  slot retirements cannot overwrite a newer result; dimension/device
  mismatch and age >850 ms discard stale history. Invalid depth can
  briefly hold the last gain; if no valid history remains fallback is
  the B31 neutral behavior. Disabled temporal = B31 instant matching.
- Hybrid Seam+Basic Blend is ON by default. It uses the existing
  Context/focus blend FEATHER FRACTION of the crop, not a fixed pixel
  width; matches appearance first and feathers corrected periphery
  into the focus at the boundary. The original Off/Manual/Adaptive
  control and full-sharp alternatives remain. Opt-out restores an
  explicitly adjustable inward transition 0..512 px (was 0..64).
- Fovea anti-vignette formula remains bit-for-bit source-identical
  to successful B31. Three original game views are unchanged.
  No changes to B28/B29 epoch, fence, resize, owner, or depth capture.

## Verification and caveats
- All source controls must pass guarded generated overlay tests.
- 784-B shared HLSL/C++ CB prefix, 1024-B aligned upload (old 480/512).
  No per-pixel temporal filters; extra CB read only in CSSeam.
- WARP regression tests exercise baseline modes, hybrid percentage
  feather, fovea-only color changes, temporal damping, missing-depth
  held gain, and disabling temporal.
- Sanitizers, FXC /WX, production WARP, backend and frontend build,
  final artifact ZIP mandatory. GPU timing claims require headset.
- NR handling described is only verified for BEFORE-SR fovea mode;
  Cheeky Universal Headset NR runs after the compositor and is out of
  scope. Temporal matching may reduce pumping but cannot guarantee
  absolutely zero flicker caused by depth reprojected geometry or NR
  intrinsic instability. Most shared-queue rendering performance
  remains identical apart from 288-byte asynchronous readback.

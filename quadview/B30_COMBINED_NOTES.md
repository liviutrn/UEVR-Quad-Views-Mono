# B30 combined appearance build

This is the single test build for calibrated anti-vignette, fovea brightness and
adaptive seam matching. It includes B29's XYZ/efficiency work and preserves the
B28-103 lifecycle/retirement implementation. The earlier focus-only run is
superseded on the same branch; workflow concurrency cancels it if still running.

## Defaults: ready without setup

- Fovea correction ENABLED, fitted strength1, overall brightness1 (neutral center).
- Exact-corner gain1.14799273, onset r-squared0.46940367, exponent0.92386647.
- Seam mode ADAPTIVE, strength0.85, relative gain cap0.20, color matching0.5.
- Local residual strength0.5, outward fade radius120 output pixels.
- Transition0 pixels: full rendered fovea remains sharp; no inward image blend.

The calibrated profile comes from52,584 gray-sky samples. Predicted residuals
are in focus_lift_calibration.json; the screenshot domain/bright plateau limits
certainty. Overall brightness remains neutral because there is no established
universal center correction. The independent brightness slider is available.

## How the combined correction works

1. Apply calibrated brightness-only compensation to the original fovea, after
   existing sharpening, without extra texture samples or blur.
2. Analyze corresponding current source patches on GPU. The analysis uses that
   SAME focus correction, so it matches to the displayed fovea reference.
3. Fit bounded independent per-eye global gains and eight local boundary gains.
   Global correction applies across the periphery; local residuals interpolate
   around the boundary and fade outward smoothly. Weak local estimates use the
   global gain. Match strength interpolates toward the resulting correction.
4. Compose the corrected periphery and original detailed/corrected fovea.

The analysis averages four samples per patch only to compare similar levels of
detail. It never blurs displayed foveal details. Out-of-bounds, disocclusion-fill,
near-black, clipped/highlight, high-gradient and broad luminance-outlier samples
are rejected. Requested but invalid/missing depth produces neutral automatic
statistics instead of concealing unreliable geometry. Depth provenance remains
approximate exactly as before; this is not a depth-flicker fix.

No image history is reused: every dispatch writes all18 gain/confidence records
(2 eyes x global+8 local). This avoids stale world/gaze/XR history. Rapid motion
can still reveal unstable estimates; bounded current-frame fitting does not
constitute a guarantee of temporal stability or an invisible seam.

## Controls and comparisons

Fovea brightness / anti-vignette and Advanced Seam Matching are independent.
Reset restores the calibrated focus profile. Seam Off restores legacy feather;
with Manual/Adaptive on, transition0 bypasses inward feather and uses full focus.
Optional transition pixels reserve EXISTING rendered focus edges for blending,
reducing the fully sharp interior. They add no physical outward guard coverage.

Adaptive confidence diagnostic colors peripheral output red-to-green. Existing
focus/context/layout/depth diagnostic views bypass appearance adjustments.
GPU timing reports total composition+analysis and the last retired analysis time.
Compare identical scenes/settings with both corrections Off versus On to measure
full incremental cost. The<=1ms target is unmeasured until headset testing.

## GPU and safety

Three existing render sources; no added Unreal view, DLSS operation or crop/target
resizing. One small two-group128-lane compute dispatch, followed by the existing
stereo draw on the same command list. No CPU statistics readback or GPU wait.
Two slot-local source gain arrays require18 float4 records (288 data bytes;
actual committed-buffer granularity is larger). Allocation stays bounded to
existing fence-retired compositor slots, with no per-frame buffer creation.

C++/HLSL/fixtures agree on480-byte constants within the512-byte allocation.
Six SRVs (four colors/depth/statistics), one UAV, seven heap descriptors. Sources
use ALL_SHADER_RESOURCE during analysis, and the stats UAV-to-PIXEL transition
orders compute writes before sampling. Existing fences/owner leases remain.

## Checks and remaining validation

Clean full source replay passed staged B28, B29, focus and combined seam checks.
Protected source checks retain exact B23 depth and B29 sampling/sharpening/output
math. Focus profile tests passed10,201 symmetry/bounds cases and actual sky sample
points; settings validation/equality checks passed for both features. The focus
math also passed ASan/UBSan. Fresh Luna review found no integration blocker.

Windows CI must compile VS/PS/CS with FXC SM5 /WX, full backend and WARP tests.
Production GPU tests cover focus/periphery/off identity, the fitted profile,
both eyes, adaptive independence and corrected-reference behavior, local
variation/uniform neutrality, rejection and optional transition. D3D12 debug
errors fail the new tests when the debug layer is available.

Neither screenshot fitting nor source/GPU tests certify PSVR2 perception,
performance or lifecycle behavior. Keep B28-103. Start with the ready defaults,
take comparable On/Off sky and ordinary-scene screenshots, test head/gaze motion
for halos/tint changes/double edges, and repeat a short resize/reload smoke test.

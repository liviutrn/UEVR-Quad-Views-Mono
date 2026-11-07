# B30 — calibrated fovea brightness compensation

Parent: corrected B29 `f02ca8224b32134a6f1b7ceda419914fa9d65967`.
Lifecycle baseline: user-tested B28-103 `3ebe512c830a8e7467717d85d1cd0b7f52c5e4ba`.
Branch: `experiment/triview-b30-focus-lift-20261107`.

## User decision and scope

Test anti-vignette/brightness alone first, then assess residual seams from new
headset screenshots. The larger adaptive seam implementation is preserved as
unbuilt prepared source in `archive/seam-matching-prepared-20261107`, commit
`144fe38f83e3b9f4f10be6d4d5e53249d1114396`. It is not included here.

The game vignette setting was already disabled; enabling it worsened the effect.
Similar crop-local darkening was observed in DuoView Mono screenshots, so this
is not evidence of a uniquely TriView lifecycle defect. This build compensates
measured appearance; it does not establish or repair the underlying cause.

## Ready-to-test preset

No initial slider setup is required. The new saved UI control defaults ENABLED,
strength 1, overall brightness 1 (neutral center). It is frozen with the same
source packet as all other compositor settings. Existing profiles have no key
for this new control and therefore receive that enabled default.

The fitted scalar gain is:

```
q = 2 * focus_uv - 1
r2 = saturate((q.x*q.x + q.y*q.y) / 2)
t = saturate((r2 - 0.46940367) / (1 - 0.46940367))
gain = brightness * (1 + (1.14799273 - 1) * strength * pow(t, 0.92386647))
```

Center gain is 1; exact-corner gain is about 1.148. Most of the interior stays
unchanged. This is not a uniform 14.8% brightness boost. Separate overall
brightness is available for a remaining center mismatch, but defaults neutral:
we do not have evidence for one universal center lift across different scenes.

Controls under QuadView settings: **Fovea brightness / anti-vignette**. Simple
controls are enable, strength, brightness and reset calibrated preset. Advanced
controls expose the curve only for later refinement. The old blend/feather is
unchanged; the correction is applied to the foveal image before that blend.

## Calibration evidence and limits

See `focus_lift_calibration.json`. The fit used 52,584 sampled exact-gray pixels
from `image(20261107-161252).png`, excluding the yellow border and values outside
125–146. A robust thresholded radial model fitted better than a simple quartic:

- Predicted absolute residual across all selected sky pixels: median 0,
  95th percentile 0.775 gray levels.
- Restricting to the 12,320 initially darker pixels: median 0.395, 95th 1.339.
- Simpler quartic residuals on those darker pixels: median 1.789, 95th 6.909.
- Other TriView gray-sky patches and DuoView images broadly support a similar
  corner falloff, but are not exact matched-camera ground truth.

The sky has a large plateau at gray146. These measurements constrain a starting
appearance correction, not a physical inverse of the game/tonemapper. Screenshot
encoding/runtime processing can differ from the sampled shader domain. The
preset is measured and preconfigured, but must still be checked in the headset.
Different crop aspect ratios, lighting or rendering settings may need refinement.
Brightening cannot recover clipped colors or lost detail and can clip highlights.

## Implementation and safety

Only foveal RGB in normal composition is multiplied, after existing sharpening.
No blur, new texture sample, render, compute pass, DLSS operation, readback, render
resource, descriptor, target-size or camera/projection change is added. Alpha,
peripheral output outside the crop, diagnostics, resource retirement and B28
world/XR safety remain unchanged. Both actual native stereo foveas use the same
normalized calibrated profile. This feature is exposed in TriView/QuadView, not
ported into the protected DuoView baseline in this change.

Two float4s extend constants from400 to432 bytes, inside the existing512-byte
slot-local allocation. HLSL, C++ and both old WARP mirrors agree. Existing five
SRVs and graphics root signature are unchanged. Off and zero strength with
neutral brightness execute the original output behavior. Existing standalone
Settings defaults remain off for legacy API tests; shipping saved UI defaults on.

## Verification

- CPU profile tests passed 10,201 symmetry/bounds cases, the actual measured sky
  sample points, neutral center and manual brightness checks.
- New settings validation/equality/boundary tests passed.
- New math tests passed ASan/UBSan locally (host leak checking unavailable).
- Full clean materialization/staged checks passed, including B28 lifecycle,
  B29 axes/depth housekeeping and B30 frozen controls/constants/preset.
- Protected-source test removes only the new helper, two vectors and one call,
  and requires all remaining HLSL to equal the exact pinned B29 shader.
- Fresh Luna review found no concrete blocker in the isolated implementation.
- Windows CI must compile FXC /WX, full backend and GPU WARP tests. The new WARP
  test checks CPU/GPU profile agreement across both complete focus regions,
  neutral center, corner/overall lift, exact periphery and disabled identity,
  zero-strength identity and debug-layer errors when available.

No in-headset improvement, zero-regression or numerical GPU-time claim is made
before testing. Retain B28-103. Start the new build with its default preset and
capture the same sky plus one ordinary scene with correction ON and OFF. Keep
other settings and the old feather fixed so the effect is attributable.

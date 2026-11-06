# TriView B24 — KISS shader compositor math optimization

Based exactly on B23 `a3c85bb529afc589becbb7f236816a57cf831aa8`, which reduced the B22 depth search to 4 lookups.
B21-51 remains the confirmed headset fallback; B22-54 remains the CI-passed 25-sample comparison.

## Two simple changes
1. Delay the eye-to-context projection until `ReadContext` is actually called. Fully opaque real stereo foveal pixels skip that homography entirely. Context-only, feather and other diagnostic paths still compute the same projection.
2. Compute the normalized pixel-to-focus tap offset once when sharpening is enabled. Reuse across six Glamarye sharpening taps, preserving positions algebraically.

## Deliberately unchanged
- B23 four depth lookup positions, depth-jump test, occlusion/disocclusion path and 15-tap background repair.
- Three physical sources, foveal imagery and optical geometry, NGX depth capture, source routing, XR/fence ownership, sRGB transfer, menu, memory allocations and GPU synchronization.
- The sharpen tap math is algebraically equivalent but reorganized: negligible float-rounding differences are possible, so this is not a promise of bit-for-bit pixel equality.

## Validation
- Guard against any changes to B23 ray warp or color output shader.
- Test 8000 crop/eye/tap normalization samples against the old expression.
- Re-run original Windows shader compilation, depth/stereo GPU WARP ground-truth tests, backend compatibility suite and portable ASan/UBSan.
- B23 four-step ground truth is not yet independently headset validated; B24 inherits that visual risk.
- No measured FPS improvement is claimed. Use compositing GPU timing at same resolution/settings to compare B22, B23 and B24.

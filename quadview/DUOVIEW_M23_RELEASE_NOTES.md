# DuoView Mono M2.3 — headset-driven changes

**Baseline:** M2.2 #203, successful and headset-stable, commit `342f5e45133f16dc53fc2ebac32b768fd77a6c66`.  
**Reference TriView:** B43-158, successful commit `67913082328c128d1d65bf6c76b0ad60cdbcb332`. This branch DOES NOT modify any TriView ID7 code or the TriView #158 shaders.

## Observed in headset (M2.2)

- Synthetic stereo on 0.9 strength, near depth 0.25, depth sharpness 0.25 works; no severe stereo flicker, but some weapon and hand depth artifacts.
- Increasing peripheral resolution improves apparent depth artifacts; fusion of higher-quality fovea depth is desirable.
- Fine depth toggle no visible effect: diagnostic log fine=false, zero successful pairs, code 4 rejection predominant (captures on different command lists).
- NGX jitter switch no visible effect despite its state changing; it remains experimental OFF by default.
- B40 mono brightness/colour matching introduces a discontinuity only when enabled, worse with larger foveal blend feather. This is not the approved TriView seam appearance.
- Per-eye regular sharpening works, existing extra-wide ring is too broad and should be adjustable independently.
- Runtime resolution, fovea crop and peripheral changes, Cheeky enable/disable: no crashes. Preserve all lifecycle safeguards.

## M2.3 changes

### 1. One B40 history; correction covers the actual blend feather

NO second per-eye seam histories. The shared mono centre scene needs one colour-correction history (32 knots × 4 deterministic sampling locations × 15 paired RGB probes, persistent queue-owned EMA). Previously the **B38 12-pixel inward correction ramp** was multiplied into the blend even when the actual v208d/Mono feather spanned far more pixels. This let the image revert to uncorrected periphery while the blend was still largely peripheral; user reported abrupt brightness bands.

Now `DuoB40InwardAnchor` always returns 1.0 for source matching while seam is enabled. Both native and fallback compositor already call `lerp(rawPeriphery,matchedPeriphery,DuoB40InwardAnchor(...))`; this now selects matchedPeriphery. The **existing final** `lerp(matchedPeriphery, fovea, BlendWeight)` smoothly attenuates matched context as the fovea takes over. Seam OFF preserves preexisting fallback, and all colour/fovea/VRAM/command lifetime resources stay identical. B38 inward slider's *stored value* is preserved for settings compatibility but no longer controls an independent seam correction ramp (UI explains the deprecation).

This is the requested **single-history** alternative. There is no second B40 compute dispatch or eye-specific history.

### 2. Experimentally permit guarded cross-list fine NGX depth

Strict pairing previously required same command-list pointer+epoch (reason 4 dominated). M2.3 also allows adjacent captured coarse/fine outputs on the **same tracked submitting D3D12 queue** if their recorded timestamps are ≤25 ms apart; all original generation/extent/role, jitter valid, submitted, producer fence ordering, fresh capture, and fail-closed 500ms cooldown remain. This is NOT exact colour-frame provenance; static 25ms matching may fail for low FPS or Cheeky interleaving. Fine OFF default; coarse-only fallback on any rejection. No additional depth pool allocation in the frame callback and no inter-queue unsafe reuse.

### 3. Independent inner and extra-wide sharpening

Keep linked/unlinked normal sharpening as in M2.2. Add an extra-wide strength slider (0–20, default 1), option to unlink per eye, plus wide left/right strengths (0–20). Wide now runs independently even with normal sharpening = 0; normal works with wide disabled; both contributions are fused in the same raster draw without allocating another texture or changing rendering pass count. Extra-wide filter radius and FXAA guard offsets changed from 2.8/7px (2× standard) to 2.1/5.25px (1.5×). No new scene render; TriView B43 extra-wide remains unchanged.

## Important omissions and risk

- **Not proven:** actual exact colour/depth source-frame identity or that fine pairing can succeed with Cheeky running. M2.2 log showed 0 successful pairs. The new conditions are conservative but only headset log can establish success.
- No temporal depth smoothing, new full-resolution fine grid, arbitrary 25ms pair, disocclusion inpainting, or changes to the successful stereo warp.
- Coarse-only synthetic stereo and original TriView continue to be the fallback.
- No claims of the seam being invisible until Liviu tests.

## Headset test (M2.3 vs stable #203)

1. First start with **fine OFF**, seam matching OFF, previous 0.9/0.25/0.25 synthetic settings. Verify headtracking, changing crop/periphery/runtime resolutions, toggling Cheeky and no crashes.
2. Seam matcher ON; try RGB correction at 1 and different regular feather widths, including a very large feather. Compare visual seam with M2.2, focusing on the abrupt light/dark band 12px inside the crop; test both eyes while moving head/gaze.
3. Regular sharpen = 0, wide ON strength 2; then wide strength 0 and regular >0; then both. Try independent per-eye wide. Verify radius is ~1.5× rather than 2×.
4. Fine depth ON with Cheeky ON and OFF in otherwise same scene. Look for `[DuoView][M2.1] fine=true`, `pair` increasing, rejection code and `gap_us`. If still false, do NOT assume fine depth improved quality; return a log. If fine=true, watch hand/gun/foliage depth and head/object motion for flicker or wrong-frame ghosting.
5. Toggle stereo OFF and verify v208d Mono route; verify mode ID7 TriView unchanged.

## Fable review instructions

Review the exact M2.3 shader and overlay, preferably compare M2.2 #203 and TriView B43-158. Focus on 12px correction-ramp discontinuity, 25ms/adjacent/equal producer-queue pairing (still no source frame ID), M1Constants size 256, independent wide when inner=0, per-eye crop/edge math, and absence of GPU resource or TriView regressions. Check Windows WARP/fxc CI but do not treat CI as headset validation.

# B36 — blend, blank border and depth continuity repairs

Based on user-tested B35-125 (`dba83e5845ac69d5b7064fbada13f8175e44cb09`). B31 calibrated anti-vignette remains byte-identical. Native rendering, view layout, target allocation, retirement fences, queue-pinned seam history and the existing 250 ms depth selection limit are retained.

## User observations and evidence

The standard Context/focus blend feather had no effect with Edge V2. Confirmed in code: B35's `SeamFocusWeight` ignored `Options.x` whenever a matching mode was enabled.

The supplied screenshot's yellow rectangle is the exact focus crop. Five columns immediately inside its right edge (x1653..1657) are RGB zero at all 600 sampled rows (y610..1209). Outside the edge, B35 spreads that darkness into the periphery because its exact-edge estimator treats source black as valid color. The screenshot alone cannot prove whether those blank pixels originate from Unreal, an upscaler subrect, source viewport rounding or another producer stage. B36 repairs the observed narrow blank-rim class in the compositor; it does not claim to have identified/fixed its upstream producer.

The below-30-fps stereo/mono switching had no explicit 30-fps cutoff in code. A concrete availability defect was found: the capture pool could recycle its sole/newest valid submitted depth while its replacement was merely being recorded. `latest_recent_submitted()` then had nothing to return until submission, so composition could temporarily skip depth warp. This can occur at interleaved low-frame-rate recording/presentation cadence. Runtime confirmation that it explains every reported shake/dropout is still needed.

## Changes

1. Edge V2 combines the original fraction-based feather with its pixel-based inward feather (the wider effective feather wins). The original control now works alongside automatic color matching. B31 modes retain their previous semantics.
2. GPU analysis checks twelve separated raw source probes per candidate border column/row. Only an exactly-zero continuous rim, ending within sixteen source pixels and within one eighth of the view dimension, with lit content at at least six first-valid probes, qualifies. A whole dark scene, isolated black objects and a broken/nonuniform rim do not qualify. Each eye/side is independent.
3. Focus center and sharpening taps clamp to the detected valid source rectangle. Coordinates inside that rectangle are unchanged: no recentering, stretching, new Unreal render, larger crop or target resizing. The missing margin is filled from nearest valid focus pixels; lost detail is not reconstructed. The matcher uses this same repaired appearance. Temporal broad correction resets when rim widths change.
4. New saved toggle **Repair uniform black source padding** defaults on. Turn it off for comparison or if a legitimate uniform-black narrow border is misclassified. This detector is deliberately conservative but remains a heuristic, not producer metadata.
5. Capture reserves the newest still-eligible submitted depth while recording a replacement. Other slots retain the original producer fence and consumer lease reuse checks. The latest selector, 250 ms age, size tolerance, queue rules and twelve-slot cap are unchanged. No stale snapshot is made eligible, no CPU/GPU wait or per-frame heap allocation is added. A singleton pool may allocate one additional normal pool slot under the existing cap.

## Cost and validation

Fixed, small additional GPU border probes; statistics grow from146 to148 float4 records. No image readback or GPU history synchronization change. No measured RTX cost claim before headset timing.

Extended production WARP tests cover five/eight-column rims, both eyes, compact source origins/allocation margins, signed RGB and sharpening, padding toggle/zero strength, ordinary black scenes/interior objects/nonuniform rims, original feather, and history reset on rim-width change. Existing Edge V2 and B31 tests remain. Portable depth-policy tests cover a singleton, Record/Present/Submit at44ms intervals, replacement promotion, expiration, resize, failed evaluation and incomplete foreign fences. Windows FXC /WX, GPU WARP and complete backend/frontend build gates must pass before recommending the artifact.

Depth and color still lack exact per-frame provenance in the inherited selector. Reserving a valid depth closes the verified availability gap; it does not prove all stale-depth motion artifacts are eliminated. Projection invalidity, prolonged missing depth or expired/unsafe snapshots still legitimately disable depth warp.

## Headset check

Keep B35/B31 backups and existing anti-vignette settings. Use Edge V2 Temporal and your usual Context/focus blend feather. Leave padding repair on. Check the yellow crop's outer sides/corners and the dark spill with fovea-only NR before SR, then compare the padding toggle. The crop must remain in the same place and the interior remain sharp.

Compare feather0 versus your usual value to confirm the standard blend responds. Test normal motion and22.5-to90 reprojection without resizing/restarting solely for stress. Compare total compositor GPU time/VRAM with B35. If depth still switches, retain the ordinary UEVR log (existing depth age/reason/warp fields are relevant); do not infer that a passing synthetic test proves headset stability.

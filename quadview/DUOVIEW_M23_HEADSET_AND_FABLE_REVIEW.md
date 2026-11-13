# DuoView Mono M2.3 — headset-driven fixes / B43-158 parity review

**Base:** known-stable M2.2 #203 (`342f5e45133f16dc53fc2ebac32b768fd77a6c66`).  
**TriView reference:** **UEVR-TriView-B43-158**, successful run `43237617658`, commit `67913082328c128d1d65bf6c76b0ad60cdbcb332`.  
**Scope:** DuoView synthetic stereo / mode ID6. The original TriView B43-158 `quadview/QuadViewComposite.hlsl` and `quadview/QuadViewD3D12.hpp` are unchanged and their exact blob hashes are checked in CI.  
**Status:** Requires full CI and PSVR2 headset testing. Known-good #203 remains available.

## Actual M2.2 headset observations

Liviu reports convincing **stable** cyclopean stereo at strength **0.9**, near limit **0.25 m**, depth edge sharpness **0.25**; substantially less flicker than previous asymmetric stereo experiments. Weapon/hand disocclusion artifacts persist. Higher periphery resolution helps quality. Fine NGX depth toggle shows no visible difference, jitter alignment A/B similarly inconclusive. Mono B40 seam brightness/colour matching introduces a visible abrupt transition with wide fovea/periphery blend feather; **without matching ON, the abrupt seam is absent**. Regular per-eye sharpen works; wide radius feels too large and should have its own strengths. Resolution/crop/runtime changes and Cheeky NR toggles remained stable without crashes — **preserve lifecycle and fallback**.

The attached log had 709 M2.1 diagnostics: `fine=false` throughout, 0 successful pairs and 351 pair attempts. The dominant reject reason 4 came from requiring the two NGX evaluations to use the **identical command list and epoch**; codes 3 (sequence) and 2 (missing candidates) also occurred. Cheeky is a separate NGX/NR consumer; whether it interleaves evaluations is **not proved**.

## Changes in M2.3

### 1. Fine fovea depth: conservative cross-list pairing

M2.1 rejected genuine fine/coarse NGX source captures recorded on separate D3D12 lists. M2.3 still requires (a) the same immutable rendering-generation/extents/request, (b) distinct expected fine/coarse sizes, (c) valid NGX evaluation, copied depth, role tag and jitter, (d) submission queue and fence validity, (e) both captures within the existing 250ms recency horizon, (f) **adjacent captured** evaluation sequence numbers, and (g) the 500ms coarse-only cooldown on a missing pair.

When the two roles were recorded on different command lists, M2.3 now **additionally** accepts the pair only if both have the **same recorded producer queue** and their NGX capture timestamps differ by **no more than 25ms**. This is a conservative provisional rule, **not proof** that both depths correspond to the exact presented colour frame. Fine remains OFF by default. If new movement artifacts appear, turn fine OFF and inspect `[DuoView][M2.1]` pair/reject/gap lines; do not disable fence safety or widen timing blindly. Jitter remains an opt-in A/B test.

### 2. Seam: repair the actual Mono blending defect, keep one shared B40 history

An earlier speculative attempt doubled the B40 history to separate eye buffers. **It has been reverted before shipping**. The user correctly noted that the issue appeared only after enabling seam matching; independent sharpening is not the primary explanation.

The proven B40 architecture remains exactly **one shared 32-knot Mono correction history**, 128 deterministic spatial subanchors, 15 paired samples per subanchor, componentwise trimmed outliers, one queue-owned temporal EMA with no crop/scene resets, existing GPU ownership and one compute dispatch. TriView B43 uses two histories because it has two separately rendered eye views; DuoView's input image is one shared Mono source, so two histories are unnecessary for a source-domain colour match.

**Proven code-level mismatch:** DuoView used `DuoB40InwardAnchor()` to erase matched peripheral colours within a **fixed 12px inward strip**, even if the visible peripheral contribution in the real feather stretched over many more pixels. This can produce a dark/light strip right *inside* the crop boundary when matching is ON. The actual final `lerp(periphery,fovea,weight)` already attenuates the corrected periphery by `1-weight` along the entire feather. M2.3 sets the correction anchor to 1.0, allowing only this correct, continuous attenuation. It leaves the original raw colour and gamma handling unchanged. No extra texture pass or GPU memory.

**Legacy setting:** The former `B38 inward raw-context anchor` slider is no longer shown because it no longer controls a valid separate strip. Its saved field and defaults remain harmless for compatibility. Blend Feather Width continues to control the actual output transition. A new numerical regression tests many feather widths and proves that an ideal constant-offset colour match stays constant over the full feather; the old fixed strip fails this oracle.

This is a *targeted Mono adaptation* of B43's established B40 matching model. The screenshot/headset outcome, not superficial algorithm naming, determines parity. There may still be differences in colour-space, depth-warp and per-eye sharpening references requiring later measured changes.

**Rendering order note:** Current synthetic stereo mode inverse-warps output sampling UVs first and performs source compositing after warp in the same final raster pixel shader. The foveal regular and wide sharpening calculations occur before the final blend. It does *not* literally composite a separate full Mono texture before stereo synthesis. No new intermediate full-resolution texture has been added.

### 3. Regular and wide sharpening independent

Regular sharpening remains linked or independently adjustable per left/right eye. Extra-wide sharpening can now be enabled with its **own linked strength (0-20)** or **independent left/right wide strengths (0-20)**, regardless of the regular strength. Wide radius/guard changes from 2.8px / 7.0px to **2.1px / 5.25px**, exactly 1.5x the original regular 1.4px / 3.5px filter. These are **two independent sharpening contributions within the same raster draw**, not another GPU render pass. Applies to synthetic stereo mode; legacy Mono controls remain unchanged. Wide starts OFF, regular user strengths are retained.

## Headset verification sequence

1. Keep #203 installed/available as fallback. Confirm #M23 synthetic stereo coarse-only looks identical at your 0.9 / 0.25 / 0.25 settings, and crop/resolution/runtime/Cheeky remain stable.
2. Enable Mono seam matching and move the **Blend Feather Width** broadly (small and large). A correct result must have no abrupt bright/dark band **inside** the crop when matching is ON; compare to B43-158 and to matching OFF, using the same scene and exposure.
3. Compare regular-only, wide-only (regular strength 0), and both, then independent left/right wide strengths. The wide effect should have shorter radius and independent strength.
4. Enable fine NGX depth. Watch `[DuoView][M2.1]`: want `fine=true` and growing `pair` count, with a reasonable `gap_us`. If pairing remains 0, leave fine OFF and send log; conservative rejection is better than wrong-frame depth.
5. Inspect hands/weapon near objects, movement/disocclusion, shadow contours, gaze motion, and any new shimmer or binocular rivalry. Disable fine on any temporal artifact.
6. Verify TriView ID7 unchanged, synthetic stereo OFF original Mono route, and old stability with resets, crop/periphery sizes, NR toggles. Report any crashes immediately.

## Fable adversarial review

Priorities: (a) full-feather correction equals `match*(1-BlendWeight)` (no early 12px cutoff) in both Native and Gather paths; verify shader sample domain through stereo warp, (b) one shared B40 history including edge-statistics colour-space/ref sharpening, (c) cross-list fine pairing and true colour-frame provenance risk, (d) M2.3 independent wide strength, 1.5x offsets and potential bypass when regular=0, (e) exact source parity and regression stability for B43-158 and M2.2/203, (f) FXC real compiler, WARP GPU and sanitizer test results. **Never claim CI alone verifies the headset result.**

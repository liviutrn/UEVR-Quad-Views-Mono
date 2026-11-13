# DuoView Mono synthetic stereo M2.3 — headset response / B43-158 parity

**Date:** 13 November 2026  
**Base:** Successful M2.2 build #203 (`342f5e45133f16dc53fc2ebac32b768fd77a6c66`).  
**TriView ground truth:** Successful **UEVR-TriView-B43-158**, GitHub Actions run `43237617658`, commit `67913082328c128d1d65bf6c76b0ad60cdbcb332`. The original `quadview/QuadViewComposite.hlsl` blob `3fd53f95cba42b0703e8fc146151e96a98cb00b7` and `quadview/QuadViewD3D12.hpp` blob `c7c06dbdc0d2c89779203feeb5ba5bb5d29944fb` are pinned as **unchanged** regression contracts.

## Liviu's M2.2 headset feedback

Cyclopean synthetic stereo functions at strength **0.9**, near depth **0.25 m** and edge sharpness **0.25**. Much better and steadier than former asymmetric synthetic stereo; weapon/hand occlusion artifacts remain, but no severe flicker. Increasing peripheral resolution reportedly reduces artifacts; fine-depth toggle and NGX jitter switch have no visible effect. Independent regular per-eye sharpening works, but the extra-wide radius is too large and wide should have independent strength. Mono seam RGB/brightness with blend feather does *not* match the approved TriView B43-158. Excellent device/lifecycle stability: resize, fovea crops, peripheral resolution, Cheeky NR toggle, runtime changes, no crashes. **Preserve that lifecycle.**

Provided UEVR log: 9369 lines, 709 M2.1 diagnostic lines. Fine flag was false **all 709 samples**, including 351 cumulative pair misses and **zero successful pairs**. Rejections: 628 code 4 (list/epoch), 69 code 3 (nonadjacent sequence), 2 code 2 (missing candidates), plus startup/off records. `coarse=true` 706/709; `jitter_fix=true` 7 diagnostics, proving the switch toggled. Peak depth pool reallocation 62, pool full 0. No evidence of a fatal pool exhaustion. Cheeky was loaded; log **does not prove** Cheeky caused pairing rejection.

## Fixes in M2.3

### 1. Fine depth acquisition actually eligible in DuoView

Original M2.1 required two captured NGX evaluations from **the exact same D3D12 command-list pointer and recording epoch**. Two genuine scene roles can naturally have separate command lists. This produced reject reason 4 and permanent coarse-only stereo.

M2.3 **keeps** per-role dimension validation, immutable generation/request identity, independent jitter data, valid evaluation, 250ms freshness, submission queue/fence ordering, adjacent *captured* sequence numbers and 500ms coarse-only cooldown. If two captures are **not** on the same command list, it now permits them only when (a) they share the same tracked submitting queue and (b) their actual recording timestamps differ by at most **25ms**. It still refuses other cases with reason 4. No second-copy workload, scene render, GPU queue wait, pool enlargement or unsafe depth SRV mutation.

This is a conservative **temporal association**, **not** a proven exact same-colour-frame ID. Liviu/Fable must look for `fine=true`, `pair=N/M` increment, `reject` and `gap_us`, and evaluate motion disocclusion. If still zero pairs, diagnose using captures before broadening the window; never turn off fences or compare unrelated frames.

### 2. Actual B43-158 per-eye seam architecture, not one Mono compromise

**Previous parity defect:** DuoView collapsed the two eye-specific 32-knot temporal B40 colour correction fields into **one** 32-knot Mono field. Its seam analysis used **linked** `SharpenStrength` even when displayed synthetic left and right eyes used independent M2 sharpen strengths. This is not the B43-158 architecture, and cannot match both displayed eyes' colours.

**M2.3:**
- Keeps the exact B40 spatial model **per eye**: 32 knots * four subanchors * 15 paired RGB samples; componentwise trimmed outlier groups; per-eye 350ms/other preset EMA history with continuous no-reset logic.
- GPU compute shader uses **64 lanes in one dispatch**, selecting the proper eye's pre-wide sharpen strength from a new `B40EyeSharpen` uniform. Each eye gets a *separate* 32-knot correction field and its own persistent 32-knot EMA.
- B40 history expands from 32 to 64 knots (a few extra KiB); per-slot stats from 64 to 128 float4, safely preallocated as before, no lifetime changes or additional queue/presentation work. Existing fence-owned resources and single queue remain.
- Native and gathered periphery pixel shaders select the matching eye's 32-knot correction when rendering synthetic stereo.
- Preserves TriView B43's policy that the additional wide/detail sharpening is display-only and must **not** contaminate low-frequency seam statistics; ordinary per-eye sharpen and brightness correction **are** applied in both analysis and display.
- Original B38 inward raw-context feather and B40 exterior matching are preserved. The goal is exact implementation architecture parity, not tuning defaults to hide a broken matcher.
- The original TriView B43-158 shader and compositor are **byte-for-byte unchanged**; CI checks their actual Git object hashes.

### 3. Regular and wide sharpen are independently controllable

- The original regular left/right strengths and their linked/unlinked controls are preserved.
- Added independent **wide strength** (0–20, default 1.0) and a separate toggle to unlink wide left/right. When unlinked, two further 0–20 wide strength sliders appear. Wide can work while regular=0; regular can work while wide=0.
- Runs two independent sharpening **calculations** inside the existing final raster pixel shader; does **not** add an extra fullscreen GPU draw/pass or re-render the scene.
- Wide diagonal/guard offsets changed from 2.8px/7px (**2×** regular 1.4px/3.5px) to 2.1px/5.25px (**1.5×**); the v208d regular kernel is unchanged.
- The changes apply to the synthetic stereo (`DUOVIEW_M1_RASTER`) path. The original mono fallback still keeps the preexisting linked wide controls. Wide is OFF by default.

## Deliberately unchanged

- The proven mono-to-stereo inverse-depth geometry, eight-sample/continuous inverse warp, globally conditioned coarse grid, 5×5 fine-depth footprint, near-depth cutoff and depth-edge diagnostic.
- No multi-layer DIBR, disocclusion inpainting, 2nd full-res fine grid, temporal depth accumulation or new GPU allocation in frame callbacks.
- Runtime reset/resolution/crop/VRAM safety from M2.2 and TriView B43.
- Cheeky NR is **not** modified; it operates as an independent plugin and potential NGX timing contributor.
- Jitter A/B remains OFF by default; lack of visible difference is not proof of incorrect jitter.
- Fine fovea depth remains OFF **by default** until the headset log confirms pairing and quality.

## Headset test / stop criteria

1. Preserve #203 binary as the known-stable fallback. Launch #M23 with synthetic stereo ON, fine OFF. Verify your previous 0.9 / 0.25 / 0.25 setup and that resets, cheeky switching, size/resolution controls still work.
2. With fine OFF, test seam correction ON/OFF, RGB mix at 1, B40 default temporal setting and a larger blend feather. Compare directly with B43-158 (identical scene/settings). Confirm no seam brightness jumps on gaze motion and that both eyes agree. If broken, send still images/video, the UEVR log and B40 warnings.
3. Test normal sharpen 0 / wide enabled 2; then normal 2 / wide 0; then both 2, and unlinked left/right wide. Confirm independent contribution and that the new radius is visibly narrower.
4. Enable fine depth and hold still at weapon/hand silhouette. Compare with fine OFF at the **same peripheral resolution**. Expect `[DuoView][M2.1] fine=true` and nonzero `pair`. If not, collect rejects/gap and avoid increasing depth resolution blindly.
5. Check moving head/object for depth trails, eye rivalry, ghosting or frame-to-frame jumps. These indicate F4 unproven frame correlation and require a stronger frame-stamp method before relaxing pairing further.
6. Test mode ID7 and compare with B43-158, plus M1 stereo OFF bypass. No regressions or BSODs acceptable.

## Fable adversarial review focus

1. Is conservative 25ms/adjacent/same-queue cross-list capture sufficient, or should we add exact frame/crop stamps? Does producer queue order + fence evidence guard GPU use correctly?
2. Validate both per-eye persistent B40 buffers and shader descriptor counts, HLSL root DWORD budget (224B + descriptors), command ownership across runtime/crop resizes, and shader FXC compiled output.
3. Verify the displayed **per-eye sharpened and anti-vignette-corrected fovea** is exactly the reference sampled in B40 analysis; remaining limitation: wide sharpening remains display-only just like B43-158.
4. Verify new independent wide intensity cannot borrow regular strength, 1.5× kernel tap distances, stereo OFF baseline, and PBO/performance under 20 FPS.
5. Watch for GPU regressions in WARP fixture and TriView Edge V2 flaky test; never characterize CI alone as in-headset validation.

**Status:** Code + CI may compile; headset verification is required before declaring this usable.
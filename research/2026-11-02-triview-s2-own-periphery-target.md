# Tri-View S2: periphery gets its own render target (2 Nov 2026, Claude, lead builder)

Branch `claude/triview-s2-20261102` (from `claude/triview-stage1-fixes-20261101`). Workflow
`.github/workflows/triview-stage1.yml` (now also triggers on this branch, artifact `Tri-View-S2-N`).
Labels: [capture-verified] [source-read] [CI-verified] [headset-verified] [estimated].

## Why Stage 1 build 2/3 showed the periphery on top of the left eye
- [capture-verified, Build 52 by Liviu + Sol] On STALKER 2.10 (UE 5.5.4) each singleton view-family render
  put its image at x = 0 of its own texture, although Build 51's constructor saw the requested rects
  (x = 2436 / 487 / 2923) [source-read: Build 51 `apply_quadviews.py` adjust_view_rect + constructor check].
  Under 2.06 the same code worked, so the engine update changed where a singleton render lands.
- [source-read] Stage 1 rendered view 2 as a singleton into Joey's main target with rect x = W.
  => [estimated, strong] it landed at (0,0) over the left fovea; the right half stayed black.
  Matches all three test-2 symptoms (periphery where the left eye should be, black edges, distortion).
- The same class of bug explains Build 40/51 after the update (four role textures sampled at atlas offsets).

## Fix
- View 2 renders into its OWN target at rect (0,0). The target is made exactly like Joey's STALKER Native
  Fix capture target: Kismet `CreateRenderTarget2D(W, H, RGBA8)`, a passive SceneCaptureComponent2D on
  Joey's capture actor holds it (no rooting => collected with the world like his), validated with his
  `validate_native_fix_texture_chain(+0x110/+0x10/+0x50)` on the render thread, display gamma hooked to the
  viewport's like his. Keyed to Joey's capture generation (new world / new capture => new target).
- GetDesiredNumberOfViews asks for 3 views only once that target is published (eyes only until then).
- No engine flag writes any more (bAdditionalViewFamily hack removed): clearing its own target is harmless.
- Compositor: three SRVs, every image read at its texture origin (t0 main = left fovea, t1 capture = right
  fovea, t2 periphery). Null periphery descriptor when view 2 was not rendered.
- Removed menu items: raw-target debug view, engine flag offset slider.

## Automatic evidence (no headset questions)
After 600 and 3600 composited frames the compositor copies main (left half), capture, periphery and the
XR image to readback buffers; a worker thread writes `TriView_Capture_1.zip` / `_2.zip` next to the UEVR
log: half-size BMPs + report.txt (layout, tangents, counters, per-region non-black % and mean colour:
fovea vs right/below of it, periphery image vs outside, XR fovea / edges / both sides of each seam).
Acceptance from the ZIP: main/capture non-black only inside the fovea rect; periphery non-black inside
its rect; XR edges non-black in both eyes; seam inside/outside means close (shading match).

## Checks before headset
- Local replay of the full v207 chain + this patch: OK. CPU tests (geometry, capture writer) pass locally.
- MinGW syntax check of the compositor + WARP test: OK. WARP pixel test (3 textures, decoy pixels in the
  old right-half spot and outside the periphery rect must never show; capture ZIP written) runs in CI.
- Independent Sonnet review: see PROGRESS.md.

## Results (2 Nov 2026, ~03:00)
- [CI-verified] S2 run 41368098590 (Tri-View-S2-7) and S3 run 41368117534 (Tri-View-S3-8): compiled, all
  Tri-View tests (geometry incl. gaze windows, capture writer, WARP compositor + capture ZIP) and Joey's
  41 compatibility tests passed. Not headset-tested.
- [source-read] Independent Sonnet review: no blockers; 5 fixes applied (see PROGRESS.md).
- Still unverified until the first capture: periphery target state after the engine render (assumed
  RENDER_TARGET exactly like Joey's capture), that the periphery lands at (0,0) of its own target,
  and the centre camera's temporal history (flicker?).

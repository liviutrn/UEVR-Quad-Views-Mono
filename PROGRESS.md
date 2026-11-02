# PROGRESS (Tri-View rebuild, branch claude/triview-s2-20261102)

Started 2 Nov 2026 02:00 (Claude, overnight). Base: claude/triview-stage1-fixes-20261101 (955ef14, v207 + Tri-View Stage 1 build 3).

## Root cause (from Liviu + Sol's Build 52 GPU capture, STALKER 2.10 = UE 5.5.4)
- [CAPTURE-VERIFIED, Build 52] A singleton view-family render puts its image at the target's (0,0) corner,
  even when the view rect asked for x = W (Build 51 asked for x = 2436 / 487 / 2923 and the constructor saw
  those rects; the pixels were still at x = 0). Under 2.06 the requested position was honoured.
- [source-read] Tri-View Stage 1 rendered the third (periphery) view into the main target at x = W.
  So [estimated, very likely] it landed at (0,0) on top of the left fovea: matches "periphery where the
  left eye should be, black edges, distortion".

## Fix (this branch)
- Third view gets its OWN render target (same kind as Joey's Native Fix capture: Kismet target, a capture
  component on Joey's capture actor keeps it alive, same gamma hook). View rect (0,0). No engine flag writes.
- Compositor samples three textures: main (left fovea at 0,0), capture (right fovea at 0,0), periphery (0,0).
- Automatic GPU capture: a ZIP next to the UEVR log with the three sources + the XR image + numbers.

## Builds (CI-verified = compiled + all tests in GitHub Actions; NOT headset-tested yet)
- S2 (fix only): branch claude/triview-s2-20261102, commit d8365de, run 41368098590, artifact Tri-View-S2-7.
- S3 (S2 + eye-tracked foveas): branch claude/triview-s3-gaze-20261102, commit 7e67c14, run 41368117534,
  artifact Tri-View-S3-8. Fovea windows follow PSVR2 gaze (DuoView's reader + crop stability, DuoView's gaze
  offset/smoothing settings), per-eye windows (same gaze direction in each eye), "Fovea size" 0.3-0.8 (default
  0.5), one layout per engine frame so engine crop and compositor agree. Menu: "Eye-tracked fovea" OFF = S2 behaviour.
- Both: Tri-View geometry, capture-writer and WARP compositor tests passed; Joey compatibility suite (41) passed.
- First CI run failed only on SPDLOG_WARNING (not a macro) -> SPDLOG_WARN.
- Sonnet review: no blockers; fixed: texture-array submit bypassing the compositor, attempt counter per
  generation, rebuild on size change, third-render guards reset per generation, readback Map range.

## Status
- [x] code  - [x] local replay  - [x] review  - [x] CI (S2, S3)  - [ ] headset (Liviu)
- v207 features: XYZ head scaling and hotkeys are global (work in ID7). Manual/auto FOV fix is DuoView-only
  (ID6 gate); Native Stereo uses the headset projections directly, so it is probably not needed [estimated].
- Checker for capture ZIPs: duoview/triview/analyze_triview_capture.py (placement, edges, geometry, seams).

## Test checklist for Liviu (S3 first; if the picture is wrong, S2 tells whether eye tracking is to blame)
1. New folder, inject, pick "Tri-View (Experimental)" directly.
2. Play ~2 minutes, close the game.
3. Send log.txt + TriView_Capture_1.zip + TriView_Capture_2.zip (same folder as the UEVR log).
   Optional: fps vs Native Stereo at the same resolution, and "picture right / wrong".

## Next
- Read the capture ZIPs with analyze_triview_capture.py; fix whatever FAILs.
- FPS: compare with Native Stereo at the same resolution; tune fovea size / periphery scale.
- Periphery is mono from the centre camera: near objects (hands) can shift up to ~5 deg at the fovea edge.
  Next quality step = per-eye depth reprojection of the periphery (Liviu's plan: cheap synthetic stereo only there).

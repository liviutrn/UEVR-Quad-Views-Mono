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

## Builds
- S2 (fix only): branch claude/triview-s2-20261102, commit 11e2e71, CI run 41366522141 (artifact Tri-View-S2-5).
  Local replay OK, CPU tests OK, MinGW syntax check OK, WARP pixel + capture test passed in CI (step 11).
- S3 (S2 + eye-tracked foveas): branch claude/triview-s3-gaze-20261102 (local first, pushed after S2 compiles).
  Fovea windows follow PSVR2 gaze (DuoView's reader + crop stability + DuoView's gaze offset/smoothing
  settings), per-eye windows (same gaze direction in each eye), "Fovea size" slider 0.3-0.8 (default 0.5),
  one layout per engine frame so engine crop and compositor always agree.

## Status
- [x] code S2  - [x] local replay  - [ ] review (Sonnet, running)  - [ ] CI  - [ ] headset (Liviu)

## Test checklist for Liviu (S2 first; S3 only if S2 looks right)
1. New folder, inject, pick "Tri-View (Experimental)" directly.
2. Play ~2 minutes, close the game.
3. Send log.txt + TriView_Capture_1.zip + TriView_Capture_2.zip (same folder as the UEVR log).
   Optional: fps vs Native Stereo at the same resolution, and "picture right / wrong".

## Next
- If S2 captures show a correct picture: S3 (eye tracking), then FPS tuning (fovea size, periphery scale).
- Known limitation: hands/near objects can double at the fovea edge (periphery is from the centre camera).

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

## Test 1 (Liviu, 2 Nov 10:40, S3-8) and S4
- [headset-reported] Black picture when switching DuoView -> Tri-View; worked after Native Stereo + Fix -> Tri-View.
  Bad flicker; with third view + eye tracking OFF the two foveas were OK; third view ON looked wrong, head lag.
- [capture-verified, TriView_Capture_1] Placement is right now: periphery only inside its own target's rect,
  foveas at (0,0) (rest of main/capture = stale pixels from the Native Stereo visit, never sampled).
- [capture-verified, SIFT] Foveas agree with each other exactly (scale 1.004, offset 188 px = design).
  The periphery does NOT: it covers eye tangents x -0.75..1.32, y 0.55..-0.92 = a ~92 deg game-FOV camera
  pointing ~16 deg right / 11 deg down of the head. => UE 5.5 builds view index 2 with the game camera and FOV
  (only its rect comes from our hook). Same class as Build 40/51 "FOV problem" on 2.10 (their views 2/3).
- S4 (commit 06d3aa6, CI run 41416704393): FSceneView constructor writes the centre camera (eye-pose midpoint,
  head rotation) and union projection into view 2's init options, like Joey's SceneView-compat path does for eyes;
  logs "[TriView][ctor]" with the engine's original values. Entering Tri-View restarts Native Fix once
  (automatic version of the detour). D3D12 logs which submit path runs if Tri-View is selected but not composited.

## Test 2 (Liviu, 2 Nov 11:47, S4-9) and S5
- [headset-reported] Periphery still bad / head tracking not good / trembling / artefacts; eye tracking shakes badly.
- [log-verified] Entering Tri-View restarted Native Fix by itself and the picture came up (no black start reported).
- [log-verified] The engine's own view 2 already had our union projection (m00 0.7736, m21 0.187) and our centre
  position; only its rotation was wrong. S4 overwrote the rotation.
- [capture-verified, SIFT] Periphery now within ~2 deg of the foveas (was ~18 deg). The remaining offset is the
  same in both eyes (dx +10, dy -4 periphery px) = gaze-window mismatch between render and composite.
- [source-read] Eye-tracked windows shook because Tri-View built DuoView settings with stabilize_crop = false
  (default) -> raw gaze every frame.
- [capture-verified] 138 of 737 frames were not composited (OpenXR copy returned early, e.g. GPU still busy
  with that swapchain slot -> try_wait failed). Same code path as Joey's Native Stereo; worth measuring there.
- S5 (d15b518): stabilisation always on (DuoView's lock-until-saccade, guard, pixel snap, hold/reacquire);
  the packet carries the window each eye's projection hook really applied.

## Test 3 (Liviu, 2 Nov 14:30, S6-11 = S5 picture + [TriDiag] logs)
- [log-verified] Every camera step for views 0/1/2 logged once per second. The engine builds view 2 with exactly
  the left eye's rotation (0.009 deg) and the eye-midpoint position; written periphery vs left eye: max 0.024 deg
  over every frame. Projections: eyes m00 1.786 m20 +-0.308 m11 2.367 m21 0.374; periphery = union (0.774/0/1.184/0.187).
- [log-verified] Game camera (SetupViewPoint) yaw -156.4 vs eye yaw -139.1 = 17.3 deg: the size of test 1's error,
  so in test 1 view 2 was rendered with the game camera instead of the head (cause of that S3-only failure unknown;
  S4+ write the camera in the constructor, so it cannot recur).
- [capture-verified] Periphery vs foveas within ~1 half-res periphery pixel (~0.2 deg) with eye tracking ON (S4: ~2 deg).
- [log-verified] Pacing steady: ~40 composited/s, 0 skipped except at start/end. Not a frame-rate problem.
- [log-verified] Gaze is sampled 2-3 times per engine frame (frame key changes mid-frame); S5 makes the packet use
  the windows the projection hook applied, so render and composite agree.
- Open: headset verdict on S5/S6 picture (periphery trembling? eye-tracking shake?).

## PARKED (2 Nov 2026, 14:42, Liviu): Tri-View stopped - no usable result.
- Last headset report (S6-11): periphery still trembles with eye tracking on and off, mostly the third view.
- Proven by then: placement (own target at 0,0), camera of all three views identical per frame (0.02 deg),
  still-frame alignment ~0.2 deg, steady pacing (~40 fps), automatic Native Fix restart, gaze stabilisation.
- Unresolved: temporal trembling of the periphery render. Leading untested lead: the game's temporal
  processing for the extra view (DLSS / TAA / TSR / motion blur history), or a DLSS add-on (Cheeky foveated
  DLSS NR) treating view 2 wrongly. Quick checks never run: add-on removed, upscaler off, motion blur off.
- Latest code: branch claude/triview-s3-gaze-20261102 (S6 = f2ff31e, run 41442278608, artifact Tri-View-S6-11).

## 3 Nov 2026 - third-view PROOF (branch claude/triview-proof-20261103)
- Liviu: prove a third view is possible with exactly the second view's plumbing (Native Stereo + Fix as is).
- Implemented on top of S6 (f2ff31e, 972f305 notes): PROOF toggle (default ON): uncropped eyes, view 2 = exact clone of
  the second eye view (constructor copy), compositor shows it tinted red in the right half of the right eye.
  Note: research/2026-11-03-triview-third-view-proof.md. Status: see commit messages / CI run; NOT headset-tested.

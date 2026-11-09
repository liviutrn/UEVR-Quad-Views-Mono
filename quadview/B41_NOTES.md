# TriView B41 (on B40 2a28e46)

Labels: SOURCE-READ / REPLAYED (patch scripts run locally) / CI / HEADSET.

## Changes
1. Black flashes. When no new frame is ready, UEVR re-shows the last image (with its pose, so SteamVR
   still follows the head). B40 allowed that for a fixed 100 ms; after that the headset got no scene
   image (black / SteamVR void). B41: TriView-only `TriViewHold` (quadview/TriViewHold.hpp), window is
   the menu slider "Hold last image on a missed frame (ms)", 100..1000, default 250. DuoView keeps
   its own 100 ms class unchanged. New log `[TriView][BlankFrame]` (only when a blank frame is sent).
2. Rejection diagnostics. `[TriView][TargetLifetime]` keeps the same admission check and reasons but
   now also prints native_resource / hook / hook_device / GetDevice HRESULT / resource device / live
   and a total count. Failure path only. Nothing is bypassed.
3. Queue pin. The shared colour history is submitted on its owning queue for seam modes 4, 5 and 6
   (B35 pinned only 4).
4. (Deferred) B40 colour matching on 128 GPU lanes instead of 32. The first B41 CI run (42594056723)
   compiled it, but QuadViewEdgeV2GpuTests failed in mode 4 ("Broad field jumped directly to the
   changed target"), which passed in B40. B41 therefore keeps B40's serial loop; the speedup returns
   in a later build once the cause is known. The test now prints the two values it compares.
5. Neutral fallback: without shared history B40 mode shows no correction (B40 showed the raw target).
6. Sliders in B40 mode: "Colour blend distance (x B40)" 1..3 (multiplies Outward reach, capped
   1024 px) and "Colour blend shape (1 = B40)" 0.5..2 (t^shape inside the same smoothstep; >1 keeps
   the correction strong farther out). Defaults reproduce B40 exactly. The shape travels in
   the V2 hysteresis value as shape*0.02 (EdgeV2.w), which mode 6 never read; the compositor and
   settings headers are unchanged from B40 (suspected: the edge_shape settings change broke the mode-3/4 WARP
   test in CI runs 42594056723/42597953163/42599410860, cause not yet understood).
7. Labels: workflow, zip, artifact and QUADVIEW_BUILD.json say B41; log line `[TriView][Build] B41`.

## Not changed
B37 source rectangles, B38/B27 inward feather, B40 temporal maths and presets, producer, depth,
target lifetime admission.

## Evidence for item 1 (SOURCE-READ + LOG)
Headset log 2026-11-08: two in-game TargetLifetime rejections (22:58:42, 23:00:36), each followed by
`OutputWaiting no executed source`; Liviu saw short (< 1 s) whole-view black with SteamVR void.
B40 hold = 100 ms (DuoViewFrame.hpp SubmitContinuity). Cause of the rejections still unknown: item 2.

## Liviu's standard defaults (added 9 Nov, apply_liviu_defaults.py)
Built-in defaults now match Liviu's config.txt (a saved config.txt still wins): rendering method
TriView (7), OpenXR runtime, advanced menu on / menu closed at start, UI and framework UI distance
10 / size 10 and 8, camera forward 15 / up 10, decoupled pitch on, world scale 0.85, recenter and
standing-origin key 226 (<> key), XYZ head scaling on X3 Y1 Z1.5, TriView focus 0.6 x 0.6, context
scale 0.30, feather 0.10, gaze breakout 0.25, micro gain 0.25, B27 inward feather OFF, sharpen
eyes unlinked, right eye sharpen 10 / max change 0.40. The script runs last and fails the build if
any option is not found exactly once.

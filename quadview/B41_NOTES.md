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
4. Blend distance: slider "Colour blend distance (x B40)" 1..3 in B40 mode multiplies Outward
   reach (capped 1024 px). Setting-only; default 1 = B40.
5. Shader, compositor and settings headers are IDENTICAL to B40.

Deferred to B42 (need shader changes): 128-lane B40 sampling (faster), blend SHAPE slider, neutral
fallback when shared history is missing. Every B41 attempt that changed QuadViewComposite.hlsl
(runs 42594056723, 42597953163, 42599410860, 42602127570) failed QuadViewEdgeV2GpuTests in mode 3/4
("Broad field jumped directly to the changed target: temporal=40 instant=40") although the changed
lines only run in mode 6; unchanged B40 passed the same test on 9 Nov (control run 42602648757).
Cause unknown (compiler codegen or a latent mode-3/4 shader bug exposed by any change).
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

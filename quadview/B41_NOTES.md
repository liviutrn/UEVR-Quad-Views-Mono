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
4. B40 colour matching on 128 GPU lanes instead of 32 (lane = knot*4 + sub; lane 0 of each knot
   combines the four results in the same order). Same maths, about 4x less serial work.
5. Neutral fallback: without shared history B40 mode shows no correction (B40 showed the raw target).
6. Sliders in B40 mode: "Colour blend distance (x B40)" 1..3 (multiplies Outward reach, capped
   1024 px) and "Colour blend shape (1 = B40)" 0.5..2 (t^shape inside the same smoothstep; >1 keeps
   the correction strong farther out). Defaults reproduce B40 exactly. The shape travels in
   EdgeV2.w, which mode 6 never read (constant buffer stays 512 bytes).
7. Labels: workflow, zip, artifact and QUADVIEW_BUILD.json say B41; log line `[TriView][Build] B41`.

## Not changed
B37 source rectangles, B38/B27 inward feather, B40 temporal maths and presets, producer, depth,
target lifetime admission.

## Evidence for item 1 (SOURCE-READ + LOG)
Headset log 2026-11-08: two in-game TargetLifetime rejections (22:58:42, 23:00:36), each followed by
`OutputWaiting no executed source`; Liviu saw short (< 1 s) whole-view black with SteamVR void.
B40 hold = 100 ms (DuoViewFrame.hpp SubmitContinuity). Cause of the rejections still unknown: item 2.

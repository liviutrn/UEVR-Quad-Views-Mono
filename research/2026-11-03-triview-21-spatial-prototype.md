# TriView 2.1 rebuild / 2026-11-03

Source base: clean DuoView Mono v207 (4020a443), Joey native backend (5ac7edc), not a previously built DLL. New method ID7 renders 2 real Native Stereo + Native Fix foveas at 0.5x0.5 by default (slider 0.3..0.8), and one full-FOV mono periphery from the eye midpoint. Own periphery render target at origin, independent from main and right Native Fix capture, with the three-texture GPU compositor from S6. PSVR2 gaze optional and OFF by default.

## Cause analysis
* 2.0.6 and 2.1 are both Unreal Engine 5.5.4. The engine upgrade happened at 2.0, so citing an engine version bump as cause is wrong. No exact shader or executable change between 2.0.6 and 2.1 has been isolated.
* Build 52 GPU capture: singleton views ignored atlas X placement and painted to (0,0), explaining black right-eye and old quad/tri missing textures. A standalone target per view fixes that geometrically.
* S6 capture/logs: view2 camera within 0.02 degrees of left view, static periphery alignment about 0.2 degrees; ~40 composited FPS with no steady frame drops. S6 headset: periphery still trembles with gaze ON and OFF. This cannot be a simple viewport rectangle problem.

## New repair hypothesis
In the verified third-view FSceneView constructor, only when 'Peripheral temporal isolation' is ON, set the SDK's discovered SceneViewInitOptions::SceneViewStateInterface pointer to nullptr. This prevents the third render from reusing/poisoning a stereo eye temporal history. OFF restores the S6 state untouched for instant A/B. Native Fix eyes have unchanged state. This is an **unverified hypothesis**, may disable TAA / DLSS temporal reconstruction and may expose aliasing; log the previous pointer. Distinct settings IDs prevent accidental carry-over from prior S6 eye-tracking defaults.

## CI and safety
Build replays Joey's exact UESDK-pinned, frontend-pinned v207 patch chain on clean checkout. Then applies the three-target TriView renderer with independent geometry, WARP GPU pixel tests, compatibility checks, and original backend build. No raw UE55 offsets or DLL redistribution outside generated UEVR package. Expected near-edge parallax from one mono centre camera is not fixed. Headset proof is mandatory.

## Minimal headset verification
1. Does each eye display a *different real* sharp fovea and filled periphery without black areas?
2. Does the periphery tremble with 'temporal isolation' ON? Does toggling it OFF change anything? Eye tracking stays OFF.
3. What FPS against Native Stereo + Fix at the same resolution?
Send log + TriView_Capture_1.zip if wrong.

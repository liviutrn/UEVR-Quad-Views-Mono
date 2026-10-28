# DuoView V3 TRUE Stereo XR — first headset test (experimental)

## Actual output architecture

UE0 physically renders LEFT-eye high-res fovea using the native UE cropped projection. UE1 physically renders RIGHT-eye full-FOV low-res periphery. R5 captures submitted, GPU-synchronized depth candidate copies. The added TRUE STEREO PSO is activated only when stereo mode 1/2 is selected. It writes directly to the DOUBLEWIDE OpenXR render target: x=[0,W) is FINAL LEFT eye; x=[W,2W) FINAL RIGHT eye. It never copies one finished mono composite to both eyes.

LEFT XR eye: high-resolution REAL LEFT fovea, inexpensive source-depth-guided RIGHT→LEFT periphery warp. RIGHT XR eye: depth-guided LEFT high-res foveal color, right-eye REAL low-res color for disocclusion repair, RIGHT real periphery. Both foveae inherit LEFT shading whenever geometry permits.

True-eye disparity uses frozen V3 native camera separation and frozen left/right projection matrix parameters (default physical IPD 1.0). Full reconstruction isn't yet the complete hybrid forward z/owner compute pipeline; the independent shaders are compiled but live operation is the fused **single-pass** conservative stereo raster for performance. No new Unreal scene render.

## Headset controls and first test

1. Install ZIP separately from verified V3. Enable DuoView ID6 and Split-Eye V3. Enable R5 DSV/RDG capture then exit and re-enter ID6 so the actual GPU observer attaches.
2. In DuoView ID6, TRUE STEREO: 0=original V3 mono A/B, 1=synthetic STEREO, 2=synthetic STEREO with RIGHT-eye blue tint so headset eye isolation can be confirmed.
3. First try mode 2. BLUE TINT MUST BE ONLY in the RIGHT eye. If it's in both, eye halves are still being duplicated and the build is NOT stereo-ready. Use mode 0 A/B and take CAPTURE NOW.
4. Mode 1: LEFT and RIGHT eye see different parallax in the fovea; outside fovea uses the right scene shading with moderate periphery disparity. Verify near characters/weapon against a distant tree or window; head motion should feel geometrically stable.
5. Depth candidates: LEFT fovea index and RIGHT periphery index separately, 0=auto, 1..N explicit ordinal; use View depth 1=left 2=right 3=split in headset to match geometry with original color. Set View depth 0 for stereo testing.
6. Capture outside/inside/NPC separately. Every press writes exact original LEFT/RIGHT colors, captured R5 depth candidates, the FINAL DOUBLEWIDE XR headset image, selected candidate identities, camera positions, projection/crop and runtime counters to %TEMP%\UEVR_DuoViewCaptures. Zip all capture_* folders + UEVR log; DO NOT discard .raw or manifest.json.

## Validation boundaries

- GitHub CI compiles HLSL including PSNativeStereo, renders the ACTUAL production compositor on D3D12 WARP with synthetic left/right camera origins and depth, verifies real LEFT/RIGHT output pixels differ, asserts direct OpenXR target, and runs full R5 queue/retirement, DuoView WARP and complete UEVR backend/frontend/compatibility tests.
- This is an **actual headset test**, not proof of perfect depth selection. The native left/right GPU source-camera correspondence was in-game verified in V3; R5 DSV-to-camera mapping must still be checked using the manual selector and captured image alignment. Candidate switching by DSV resource order may happen on scene reload.
- Reconstruction uses a bounded 2-iteration depth inverse gather in peripheral and a conservative foveal depth check, with right-eye real-color repair. The full V2 inverse gather + hybrid forward-owner kernels remain separate compiled prototypes, not activated in the live shader. This is a deliberate single-pass quality/performance tradeoff; further geometry refinements should follow actual captures.
- If stereo cannot produce output, the UI lists actual candidate resources and 0-mode V3 A/B; this is recovery, not project success. Send diagnostic ZIP so the next build can lock the correct depth pass.
- The source code does not affect verified V3 branch. Avoid installing over stable files. Eye comfort first: reverse disparity sign if near depth appears inverted, and do not use stereo until left/right XR tint test passes.

# DuoView DIBR architectural reset — 2026-10-23

**Status:** engineering specification, **NOT** a compiled or game-tested stereo build.
**Trusted runtime base:** v186.1 Build49 commit `60d0aae86949723d21266e4121a833f0191729c2`.
**Known live depth evidence:** Build118 `depth_proof/1792783609494` from STALKER 2.
**Rejected implementation:** Build123 branch `experiment/duoview-live-dibr-20261023`; do not promote or merge.

## Executive decision

Stop extending the P0 -> P1 -> S0 experiment. It is structurally incapable of guaranteeing
that stereo uses fresh scene depth belonging to the RGB image being displayed. The 123 CI
tests checked build success and static source substrings, not real two-eye GPU pixels or
per-frame RGB/Z identity. Do not interpret green CI as feature activation.

Retain exact existing DuoView Mono scene production, Native Stereo Fix, fovea/periphery,
Glamarye, gaze, HUD, eye alignment, persistence and current pose transaction. Add
**a new post-composition stereo-output stage** which consumes ONE completed fused
center-view color image and ONE full-field periphery depth image; optionally replace
depth in the foveal ROI with exact-matched high-res fovea depth. Avoid propagating
two independent color/depth paths throughout the XR renderer.

## What Build118 actually proves

Manifest `depth_proof/1792783609494/manifest.json`:
- Candidate 1: 860x684, DXGI 19 R32_TYPELESS, source state 16 -> 224, completed.
- Candidate 4: 860x684, DXGI 19 R32_TYPELESS, 16 -> 96, completed.
- Candidate 5: 860x684, DXGI 19 R32_TYPELESS, 16 -> 96, completed.
- Candidates 6 and 9: 344x276, DXGI 19 R32_TYPELESS, 16 -> 96, completed.
- Seven copied / submitted / completed; *every* `view_role` explicitly `unknown`.
- 1/4/5 have identical raw image content; 6/9 identical. These are candidate
  snapshots, NOT verified source-role or RGB-to-Z relationships.
- State 96 is DEPTH_READ | NON_PIXEL_SHADER_RESOURCE; 224 additionally includes
  PIXEL_SHADER_RESOURCE. Resource dimension/format and transition alone never
  prove scene identity or frame ownership.

Caution: The 860x684 and 344x276 dimensions are *observations at one DLSS/UE render
configuration*, not ABI constants or authoritative field-of-view transforms.
They must **not** be baked into release depth routing.

## Root-cause report: Build123

1. `DuoViewD3D12.hpp:record_native` computes `stereo_preview` as a conjunction
   of depth mode 5, positive strength, both buffers, a PSO, and an exact direct-XR
   render-target compatibility check. When false it returns normal Mono without
   an explicit, user-visible rejection reason. BGRA sampling fallback also
   silently returns `record_native_gather`, which is Mono.
2. `DuoDepthPairP1.hpp` guesses depth source roles by **only** width/height and
   format. There were multiple distinct resources of each size in Build118.
3. That observer lacks Build118's Reset/BeginRenderPass/EndRenderPass/Execute lifecycle
   guards and exact submitting-command-list-to-queue sealing. It updates two
   long-lived depth textures at arbitrary barriers and uses a one-shot fence as
   if it proved each later update's completion. This is neither reliable
   GPU ownership nor same-frame color matching.
4. The `SourceLineage.hpp` contract was unit tested in isolation but was **not
   wired to actual source packets**. It could not protect a real HMD frame.
5. Depth maps were treated as normalized eye-space inverse distance via a
   hard-coded `rawZ/0.012` transform and arbitrary disparity coefficient.
   Neither projection nor convergence was calibrated; apparent eye separation
   is not geometrically grounded.
6. Debug/P1/S0 controls were injected into the already crowded Mono quality
   TreeNode, introducing several prerequisite toggles and contradictory labels
   with no authoritative status of the actual submitted two-eye route.
7. The source-level CI checks only searched for strings such as `native_stereo_preview_pipeline_`
   and `depth0 && depth1`. They tested neither GPU output L/R difference nor
   correct scene depth provenance.

## New simplified data flow

```
UE existing primary/periphery + fovea capture (unchanged Build49)
    |
    +-- stage A: existing native Mono composition, one fused full-FOV RGB image
    |            Glamarye sharpening + crop blending preserved exactly
    |
    +-- stage B: engine/RHI-attached depth capture during SAME UE producer frame
                 required: one full-field periphery depth
                 optional: high-res foveal depth / matching crop transform
                 exact role, source_frame, scene pass, pose/projection and
                 GPU queue provenance; no discovery by dimensions alone
    |
    v
immutable FramePacket { color, periphery-Z, [fovea-Z], frame/pose/projection,
                        each resource generation, queue/fence, crop rect }
    |
    +-- no verified depth or mismatched frame -> Build49 Mono output
    |
    +-- validated and stereo enabled -> one DIBR full-width raster for BOTH eyes
            |
            +-- compatible XR RTV: render direct into double-wide target
            +-- incompatible XR RTV: render owned two-eye intermediate
                then copy to XR without collapsing back to Mono
```

The periphery depth is sufficient for an MVP full-FOV depth-guided stereo pass.
A high-res foveal depth refinement can be added after that works. This is
simpler than requiring **two** perfect independent depth sources to activate.

## Per-frame synchronization contract (hard gate)

The color packet and its depth resources must carry:
- `mode_generation`, `FrameKey` / source serial, `source_frame`, exact UE
  view family/render-pass role, camera origin, view/projection matrix revision,
  crop rect, native viewport, color-stage and depth-stage markers.
- Actual resource identity **plus** resource generation; pointer reuse does not
  imply same texture content.
- D3D12 command list recording epoch, submitting queue, completion fence value.
- A bounded per-frame ring of owned depth textures; never sample resources
  currently being rewritten by a later engine frame.
- Use the depth corresponding to the original color when DuoView holds a prior
  completed color packet. Never pair held RGB with newly captured Z.

Accept only full-field depth proven to belong to the same scene producer packet
and view origin. If proof is missing or a fence isn't retired, **fail closed**
to *labeled* Mono. Depth registration occurs at the same UE producer/RHI stage
as original color packet. Build118's safe command list/queue lifecycle observer
is a starting reference for interception, not a continuously reused global
resource registry.

## DIBR geometry

Use the **actual frozen UE camera projection/inverse projection** and per-eye
view offsets to transform depth into camera-space coordinates. For a perspective
center camera and each eye displaced by +/- IPD/2, approximate horizontal
disparity in normalized output coordinates is

`du = +/- (IPD/2) / (2 * tanHalfFovX) * (1/Z - 1/Zconvergence)`.

Do not use `rawZ * constant`: reversed UE hardware Z must be unprojected through
the real captured inverse projection. Prefer forward splatting of 3D points
with a z-buffer/visibility winner, then depth-aware hole fill; a cheap inverse
gather is permitted as a prototype but must not be called artifact-free DIBR.
Clamp disparity at startup and display a convergence control in meters.
Keep OpenXR HUD / crosshair alignment controls independent from 3D scene DIBR.
Optionally apply high-resolution fovea-Z as a same-frame depth refinement,
with eye-tracked ROI masking and matched source viewport.

## Minimal, usable UI

Top-level section **DuoView Stereo DIBR** (not nested under advanced controls):
- `Stereo output` toggle: OFF by default.
- `Stereo strength` / virtual IPD slider with units; `Convergence distance`
  only after real geometry is calibrated.
- Read-only operational state on every UI frame:
  `MONO / DEPTH_WAIT / RGB_D_MISMATCH / GPU_WAIT /
   XR_FORMAT_FALLBACK / STEREO_ACTIVE / ERROR`.
- On submit, show `frame serial`, `left/right unique CRC/hash` (or sampled
  checksum), `periphery/fovea depth frames`, `drop/miss counts`, actual
  PSO and render path. Do not say stereo active merely because a checkbox is ON.
- A 1-button deterministic L/R signature check may expose a temporary
  blue left / amber right debug marker to verify XR eye routing. Never count
  a source-level assertion as successful HMD eye separation.

Do not require users to manually arm a hidden P0/P1 probe. Capture and
validation are automatic when the single experimental stereo toggle is ON.
Expose an explicit reason if the feature cannot activate.

## Build acceptance gates

**G0: Mono immutability.** Compare stable Build49 OFF against new OFF path for
same source packet. No regression to head tracking, HUD, MPC, gaze or reprojection.

**G1: XR stereo reachability.** GPU WARP DX12 test feeds a synthetic valid
RGB + Z packet and confirms a *distinct* L/R render-target image. Assert that
the active doublewide PSO really ran. Test alternate XR format through a
two-eye intermediate rather than Mono fallback. Validate with a one-button
signature check on PSVR2 (not solely CI).

**G2: Real depth identity.** Logging proves selected full-field depth belongs
to the **current** UE producer role, and copies retire on actual submitting
command queue. Verify moving head/camera, static/moving objects, gaze crop, 
runtime reset and DLSS resolution changes; reject unknown role.

**G3: Real RGB-D binding.** For each presented stereo frame, assert color/depth
same source serial, scene projection, pose, frame generation, and retired fence.
Do not substitute old Z into new RGB or vice versa.

**G4: Geometry.** Compare RGB view geometry/depth overlays at world
near/mid/far, silhouettes, weapon/hands, sky. Correct reversed-Z unprojection,
occlusions, convergence/eye sign. Confirm left/right disparity on decoded
GPU output.

**G5: Stability.** Test 300+ frames with moving gaze, low FPS + SteamVR
reprojection, source holds, swapchain resize, runtime reset and resource churn.
No crash, black HMD, persistent wrong-eye crop or silent Mono.

**G6: Delivery.** Only package as `DuoView-DIBR-Stereo-Test` once G0/G1/G2/G3
have executable evidence. Mark performance and image quality experimental until
real-world G4/G5. Keep stable Build49 separate.

## Engineering priority

1. Remove the P0/P1/S0 chained observers and nested test UI from the NEW branch.
2. Prove **stereo presentation** from an explicit valid, synthetic depth texture
   in the actual XR path (without touching UE scene rendering); do this in WARP
   and via an immediate PSVR2 signature test. This is a code gate, not a separate
   user-facing depth research release.
3. Reuse successful Build118 capture lifecycle but make it per-producer-frame and
   attach depth to its original `FramePacket`; start with periphery only.
4. Unproject actual depth and render center-origin stereo; add per-eye output
   CRC/status, automatic fallback reason and proper fence ring.
5. Add fovea depth refinement only after full-FOV stereo is visibly working.
6. Re-run full Build49 regression and headset stress suite.

**No more speculative packaged releases consisting solely of a new HLSL
shader and source-string tests.**

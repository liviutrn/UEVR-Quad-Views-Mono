# DuoView AFW: decision and staged build plan
Date: 1 Nov 2026. Lead builder: Claude. Branch: `claude/afw-stage1-20261101`.

Labels: **source-read** (I read the code), **CI-verified** (GitHub Actions), **headset-verified** (Liviu tested it), **estimated** (not measured).

## Inputs
- Design review: `DuoView_AFW_Engineering_Design_Handoff_2026-11-01.docx` (10 pages).
- ChatGPT's work: handoff, `experiment/duoview-afw-decision-20261101`, two diagnostic branches, and an uncommitted bridge.
- The second independent review named in the work order was not provided. This document is the second view. No agreement is claimed for an unseen review.
- Code read:
  - v207 (`4020a44`) and its full patch chain, replayed locally.
  - Joey UEVR `5ac7edc`.
  - PureDark/UEVR `AFW` at `fc8de10`, including its tags and release notes.
  - witcher3-vr's MIT bridge.

## Where the reviews agree (adopted)
- Start from v207. Modes 0-6 keep their code paths.
- Use the plugin's default `CombinedWarping` first. Keep `IsFoveated` / `FoveatedArea` off until their meaning is known.
- Never warp a centre-camera (Mono) image, guessed depth or stale data. Each frame renders one real eye.
- One build per stage, with at most three headset questions. Never modify or redistribute PureDark's DLL. Credit PureDark.
- Biggest later risk: per-eye temporal histories (TAA/DLSS) when each eye renders every second frame.

## Disagreements, decided from code
1. **The AFW interface does not need probes or a hand-written bridge.** *(source-read)*
   - PureDark's header gained the `ShadingRate` field in `82b4496` (7 Aug).
   - Release "UEVR AFW v1.0-beta.6" was published on 13 Aug, and its notes say "Added a shading rate option".
   - The `UEVR_AFW_v1.0-beta.6` git tag points at `74b76bc`, a praydog master commit; that tag is misplaced.
   - The header has not changed since `f49cd54` (13 Aug), so `fc8de10` carries the beta-6 interface.
   - PureDark's own integration compiles against this header. So do we: the plugin is loaded with `LoadLibrary`/`GetProcAddress`, using `decltype` of the header's own declarations.
   - The witcher3-vr bridge is beta-5. Re-declaring the interface by hand would add exactly the mismatch risk it was meant to remove.
   - Decision: ChatGPT's export probe, device smoke and uncommitted bridge are parked, not deleted. Its `ShadingRate` offset finding was correct; it is the reason we use the real header.
2. **Stage 1 is a port, not a new design.** *(source-read)*
   - UEVR already renders one real eye per frame in AFR mode. PureDark's AFW is AFR plus his warp: about 1,500 lines in 6 files.
   - Dry run of his diff onto Joey `5ac7edc` plus v207: about 80% of the hunks applied unchanged. The rest needed hand anchors: the eye-pose code, the scene-state pairing and the menu.
   - Decision: port PureDark's integration with credit. Do not rebuild a camera and submission path.
3. **"Nothing else changes" means modes 0-6 behave exactly as before.**
   - Stage 1 necessarily changes frame pacing and submission, but only while ID 7 is selected.
   - The plugin is loaded and hooked only when ID 7 is first selected (review finding). Modes 0-6 never run an AFW hook, even with the DLL present.

## What both reviews missed
1. **The competitor is stock AFW, not Native Stereo.** *(estimated, from Liviu's headset numbers)*
   - Fitting the brief's measurements gives about 14.7 ms fixed cost for a one-view frame, about 22 ms for DuoView's two render families, and about 1.04 ms per megapixel. Stock AFW at 3.8k predicts about 27 ms; measured is 26.3 ms.
   - DuoView AFW with a 0.5 x 0.5 fovea and 0.2 periphery:
     - at 3.8k, about 37 fps against stock 38;
     - at 4.5k x 3.5k, about 36 against about 32;
     - at 5k x 4k, about 34 against about 28.
   - So the prize is a sharper centre at high resolution for stock-AFW speed, not more fps.
2. **The payoff can be measured without any build.** DuoView AFW renders per frame what v207 mode 6 renders, and stock AFW what mode 5 renders, plus the warp in both cases. So mode-6 fps divided by mode-5 fps, at the resolution Liviu would play, is the most DuoView AFW can gain over stock AFW. If the ratio is about 1.1 or less, stages 2 and later are not worth building.
3. **AFW already accepts depth and motion vectors at lower resolution than the colour image.** *(source-read)* That is its normal DLSS path: the motion-vector scale is multiplied by output size over render size. Stage 2 can feed the warp the composited colour plus the periphery's depth and motion. The fovea-depth merge is added only if the edges show it is needed.
4. **The v207 workflow fires on every `claude/**` push.** *(source-read)* On this branch it is renamed and restricted to this branch, so exactly one build runs.
5. **Defects in the reference integration, fixed in the port.** *(source-read)*
   - `SceneDepthZ` was stored without `AddRef` and later `Release`d.
   - `AddRef` could be called on a null pointer.
   - `lastFormat` was never updated.
   - A repeated Present could copy the warped eye into the wrong swapchain. The destination now follows the rendered eye.
   - The other eye could be submitted before AFW had ever written it.
6. **Joey's ghosting fix already pairs one view state per eye** (`ghosting_pair`). PureDark's `GhostingFixPair` is not needed.

## Final architecture (all stages)
```
ID 7 selected
  -> warm-up: Synchronized Sequential, 90 frames (after injection, mode switch or DLSS resize)
  -> each frame: one real eye, alternating L/R
       Stage 1:   ordinary full-eye render
       Stage 2+:  DuoView fovea + periphery from that eye's own camera
  -> DLSS (NGX) hook captures that eye's depth and motion; barrier hook captures the UE velocity buffer
  -> stereo hook records this eye's and the other eye's view and projection matrices
  -> PDAFWPlugin EvaluateFrameWarp (CombinedWarping, ShadingRate 1x1) writes the other eye
  -> OpenXR: real eye + warped eye submitted every frame
Plugin missing / DX11 / 2D screen: AFW never activates; ID 7 renders Synchronized Sequential.
```

## Staged build plan (one CI build each, then stop for Liviu's headset result)
1. **Stage 1: AFW inside our build.** PureDark's integration ported as ID 7, no foveation. Questions:
   1. Does it look like stock AFW, including hands?
   2. What fps at 3.8k x 3.1k, against stock 38?
   3. Any crash, black frame or swapped eyes?
2. **Stage 2: DuoView eye plus warp (go/no-go).** The current eye is rendered DuoView-style with its own camera. Separate view states per eye and region. The composited colour and the periphery's depth/motion go to AFW. A menu toggle "warp off" for diagnosis replaces a separate build.
   - Gate before building: the mode-6 / mode-5 fps ratio above.
3. **Stage 3: fix only what Stage 2 shows.** For example: fovea-depth merge at the border, history leaks, gaze lag.
4. **Stage 4: v207 feature check and a 30-minute regression run.**

## Stage 1 as built
- `duoview/afw/DuoViewAFW.hpp/.cpp`: the port. It is the only file that includes PureDark's header, so its `using namespace pd;` cannot leak into Joey's code.
- `duoview/joey_stage1/apply_afw_stage1.py` runs after the full v207 chain and edits by exact anchors:
  - `VR.hpp`/`VR.cpp`: mode predicates, settings, frame pacing, menu;
  - `FFakeStereoRenderingHook.cpp`: fresh pose every frame, AFW matrices;
  - `D3D12Component.cpp`: warp, other-eye copy, submit every frame;
  - `UObjectHook.cpp`; `MonoRenderingPolicy.hpp` plus its unit test; the frontend list plus its test; `CMakeLists.txt`.
- The script refuses to run unless the tree is the exact v207 state. It pins the header's SHA-256 and records hashes, checked again after the build.
- Workflow: `.github/workflows/duoview-afw-stage1.yml`, a copy of v207's with one added step. The package never contains the DLL or the header.

## Verification ledger (Stage 1)
| Gate | Status |
| --- | --- |
| v207 patch chain replayed on fresh pinned Joey and frontend (local, stand-in shader compiler) | done, all its tests pass |
| AFW patch applied on top; anchors unique; tree-state and whitespace checks | done (local) |
| Independent reviewer with minimal context (Sonnet, static reading) | done: no compile error found; fixed before build: lazy hook install, hooks enabled only after being stored, warped-depth size check, descriptor refresh on address reuse, inputs prepared during warm-up |
| Windows compile, unit tests, package | CI (see the run) |
| Headset | pending Liviu |

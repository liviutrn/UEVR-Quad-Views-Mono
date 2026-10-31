# DuoView project brief (team handoff)

Canonical copy: https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/claude/team-brief/research/PROJECT_BRIEF.md
Last update: 1 Nov 2026, 00:35 (Claude). Any team member may update it: keep it current, factual and short.

## How we work (all models, one team)
- Liviu (owner) is not a programmer: plain words, few steps, at most three precise test
  questions per build. Builds exist only in GitHub Actions; Liviu tests them in the headset.
- AI collaborators (Claude, ChatGPT, others) are one team: review each other's work, write
  findings to research/ in the repo, no competition. One builder per stage; others review.
- Branches: Claude pushes claude/..., ChatGPT experiment/... . Never change another member's
  branch or a released build; branch from it.
- Label every claim: source-read / CI-verified / headset-verified / estimated.
- One build per hypothesis or stage. Before every build: replay the patch scripts locally and get
  an independent fresh-eyes review; send the reviewer the order BEFORE pushing.

Current status (ChatGPT experiment branch, 1 Nov 2026): Step 1 decision [source audit](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/experiment/duoview-afw-decision-20261101/research/2026-11-01-duoview-afw-decision.md) written; Stage 1 NOT built (beta-6 DLL ABI, local replay/private SDK, second review and independent code review pending). This status applies only to this experiment branch; v207 is untouched.

Current status (ChatGPT experiment branch, 1 Nov 2026): [AFW beta-6 ABI preflight](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/experiment/duoview-afw-stage1-preflight-20261101/research/2026-11-01-duoview-afw-abi-preflight.md) source added; **not Stage 1 warp**, not headset-verified. Separate diagnostic utility will be compiled alongside unchanged v207. Actual DLL export/layout/gpu warp still untested; no v207 or claude/ branch edited.

Current status (ChatGPT experiment branch, 1 Nov 2026): optional standalone DX12 [AFW InitDevice smoke](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/experiment/duoview-afw-device-smoke-20261101/duoview/afw/README.md) source prepared on `experiment/duoview-afw-device-smoke-20261101`; baseline v207 source remains unchanged, actual full-eye AFW warp NOT built and not headset-verified. Compiling this probe does not prove stereo.

## Current goal: DuoView AFW (decided by Liviu, 1 Nov 2026)
Exactly what stable DuoView Mono v207 does today (no more, no less), plus STEREO through
PureDark's AFW warp. Must look cleaner than our synthetic stereo (CI127) and run faster than
Native Stereo (24 fps at 3.8k x 3.1k). Stock AFW (38 fps at 3.8k) is the reference.
Concept: each frame renders ONE real eye DuoView-style (sharp gaze-tracked fovea + low-res
full-FOV periphery, BOTH from that eye's camera, not DuoView Mono's centre camera), alternating
eyes; composite into one eye image with merged depth + motion vectors; AFW warps it into the
other eye.
Must keep working: PSVR2 eye tracking fovea, MPC FOV fix with auto reapply after loads, XYZ head
scaling, hotkeys, Catmull-Rom periphery, Cheeky's DLSS 5 Neural Rendering (NR).
Not required: letmein-vr Lua hands/IK mod compatibility, PIP scopes.

### PureDark AFW: access and permission
- The warp is a separate closed DLL (PDAFWPlugin.dll) with a public C++ API: PureDark/UEVR branch
  "AFW" (fc8de10), dependencies/pd-afwmod/include/PDAFWPlugin.h: InitDevice(DeviceParams),
  InitFrameWarp(FrameWarpInitParams) -> EyeFrameBuffers, EvaluateFrameWarp(FrameWarpEvaluateParams&):
  per-eye color + depth + motion vectors, CameraData (src/dest world/view/clip matrices), Mode
  (AlternateEyeWarping / PreviousFrameWarping / CombinedWarping), EyeIndex, MotionVectorsType,
  IsFoveated + FoveatedArea, UI layer; D3D12RendererAPI helpers (CorrectMotionVectors,
  FoveatedComposite, ...). Reference integration: his fork's src/mods/vr/D3D12Component.cpp,
  VR.cpp, runtimes/OpenXR.cpp.
- tig3rmast3r/witcher3-vr (MIT): src/puredark_afw_bridge.h/.cpp + tests = clean-room ABI
  declarations and loader for PDAFWPlugin.dll v1.0-beta.5 that do not copy PureDark's header.
  Prefer reusing it with MIT credit; verify the ABI against AFW beta 6. Credit template:
  its THIRD_PARTY_NOTICES.md. ClarkCheekyKent also runs the DLL outside PureDark's build.
- Permission: PureDark to Liviu (Discord, 31 Oct 2026): OK for NON-COMMERCIAL use. PureDark to
  clarkcheekykent (Discord, 8 Oct 2026): "with proper credits I am fine with others using AFW in
  their mod". Rules: non-commercial, proper credits, never modify the DLL.
- Open question for PureDark: what do IsFoveated / FoveatedArea do?

### Known risks for DuoView AFW
- DuoView AFW renders 2 families per frame (AFW: 1) => more CPU; stock AFW was CPU-bound at
  50 fps at low res.
- Per-eye temporal histories (UE view states, DLSS/TAA, DLSS 5 NR): each eye renders every 2nd
  frame; histories must be per EYE. Cheeky's CheekyFoveatedDLSS shows how NR coexists with stock
  AFW (source eye from AFW warp metadata; fixed outer DLSS size so AFW sees no resolution change).
- Merged depth/motion vectors at the fovea border (resolution step) must not ripple after the
  warp; fovea and periphery share the eye camera, so device depth is consistent and motion
  vectors rescale by the crop.
- Eye tracking: the warped eye's sharp area follows the content to the other eye's gaze point
  (correct by construction); one-frame fovea lag after saccades must be checked.
- Things that broke before: doubled hands / close objects when warping (synthetic stereo);
  projection inheritance between views (tri-view left-fovea bug); menu errors in old quad builds.
- NR cost per frame should stay ~= today (still one eye's fovea + periphery per frame), not double.

## Key measurements (Liviu, STALKER 2 2.10, RTX 5070 12 GB, Ryzen 5800X, PSVR2 via SteamVR)
- 200x200 per eye, GPU-bound: Mono 68 fps | Native Stereo 58 | Native Stereo + Native Fix 46 |
  DuoView Mono 45 | Quad Build 51 28 (26 in later test) | tri-view 34 | stock AFW 50 (CPU-bound).
  => each separate render family costs ~7 ms GPU regardless of resolution; an extra view inside
  the same family ~2.5 ms. Pixel savings barely help; number of renders is the lever.
- 3.8k x 3.1k per eye, GPU-bound: Native Stereo 24 fps | stock AFW beta 6 38 fps (+58%) |
  tri-view B3 ~28-30 (image broken). AFW + Cheeky foveated DLSS: bad GPU scaling.
- Synthetic cross-eye stereo CI127: 4.5k x 3.5k, periphery 0.5, 40 fps; crisper than AFW but its
  artefacts are more obvious. Liviu: AFW looks cleaner (below native stereo).
- Stock Native Stereo (two eyes in one family) has bad shading -> Native Fix (separate render per
  eye) needed. E1 (one family, right eye relabeled PRIMARY) also had artefacts: per-eye families
  are required. Lumen allows at most 2 views per family.

## Builds and branches (repo liviutrn/UEVR-Quad-Views-Mono unless noted)
- STABLE: DuoView Mono v207 = build #211, run 41210849144, commit 4020a44, branch
  claude/v207-auto-fov-vram-periphery, workflow .github/workflows/duoview-joey-stage234.yml, on
  joeyhodge/UEVR@5ac7edc (+UESDK 3cffbc8, frontend 60be4b0). Headset-verified (31 Oct).
  Local replay: clone Joey UEVR 5ac7edc + uevr-frontend 60be4b0, fxc stub on PATH that writes
  "DXBC" + >= 64 bytes to /Fo, run apply_* scripts in workflow order on fresh copies;
  verify_stage234 needs the private SDK (run with its two SDK asserts stripped).
- E1 (failed): claude/e1-shared-render-20261031.
- Tri-view (parked): claude/triview-b1-20261031, claude/triview-b2-20261031 (B3 = 4c0ee7f, run
  41239720583, artifact id 13057178165); workflow triview-b1.yml; based on Build 51 (f4e086c).
  Reviews: experiment/triview-b1-review-e9bcbfd-20261031, experiment/triview-b2-deep-review-20261031.
- Build 51 quad base: liviutrn/MUSE-UEVR-DUOVIEW workflow id7-build51-source-lifetime.yml (run
  39868145292). Build 40: source 7486fc5, packaged by liviutrn/OpenNR run 39505963684.
- Synthetic stereo CI-series up to CI127 (ChatGPT): DLSS depth captured via NGX hooks (CI48+).

## Findings worth keeping
- Mono convergence: Joey Mono and DuoView converge at ~2 m on PSVR2; Mono Eye Alignment -1.5
  cancels it. Liviu's IPD = 72 mm.
- VectorXR (DienerTech/vectorxr): OpenXR frame generation layer, playable from ~22 fps.
- letmein-vr/STALKER2-UEVR: the Lua hands/IK mod Liviu used with AFW (Native <-> AFW switching;
  PIP scopes crash under AFW).

## Lessons
- Measure exact FPS at a fixed resolution (tiny res isolates fixed costs) before architecture work.
- A geometry change needs a pixel-level test or one-frame debug view before headset time.
- Check the real source, not release notes, before ruling something out.

# Part A - TriView project overview for Fable (read this first)

Written by Claude (Opus 5.5), 10 Nov 2026, from the code (generated B42.1 tree), project docs and Liviu's headset logs.
Evidence labels used everywhere: **[SRC]** read in source, **[LOG]** seen in Liviu's UEVR log, **[HEADSET]** Liviu saw it in VR, **[CI]** compiled/tested in GitHub Actions only, **[MEAS]** Liviu's measurement, **[EST]** estimate, **[GUESS]** hypothesis.

## 0. How to use this bundle (saves you tool calls)
| Part | File | What | Size |
|---|---|---|---|
| A | fable-A-overview.md | This file: goal, hardware, architecture, frame pipeline, numbers, history, constraints, open problems, what we want from you | small |
| B | fable-B-patch-chain.md | All 75 workflow steps in exact order, one-line purpose each (EDIT vs CHECK) | 17 KB |
| E | fable-E-code-map.md | Every added file with its symbols and line numbers, and every changed region of upstream files with its enclosing function | 27 KB |
| C | fable-C-generated-diff-1.md | Full unified diff (-U6) of all changed upstream Joey UEVR files, B42.1 tree vs 5ac7edc | ~530 KB |
| D | fable-D-added-source-1.md | Full source of all 42 files the patch chain adds (DuoView*, QuadView*, TriView* headers) + HLSL shaders | ~420 KB |

Suggested reading: A fully, then E. Use E to jump into C/D only where a question needs code. B tells you which build step introduced a feature (script names carry the build number, e.g. apply_triview_b36_depth.py).
Not included: upstream Joey UEVR code that we did not change (public: github.com/joeyhodge/UEVR @ 5ac7edc), the private UESDK (pin 3cffbc8, must never be published), Cheeky's NR plugin (separate DLL, ChatGPT's fork liviutrn/OpenNR), VectorXR.

## 1. Goal and owner
- Owner: Liviu. **Not a programmer.** Wants to PLAY STALKER 2 in VR at high resolution, fast and stable, not mod forever. Plain words, max 3 test questions per build, he tests in the headset.
- Goal: foveated VR rendering for demanding UE5 games via UEVR (Joey Hodge's fork): sharp high-res centre where the eye looks (PSVR2 eye tracking), cheap low-res wide periphery, stereo correct.
- Current product line: **TriView (rendering method ID 7)**: 3 real renders per frame = 1 shared mono periphery + 2 stereo foveas (left/right eye crops).
- Fallback product: DuoView Mono v207 (ID 6, two renders of one mono camera, no stereo depth) [HEADSET stable 31 Oct].

## 2. Hardware, game, settings
- STALKER 2 patch 2.10, UE 5.5.4, DX12. OpenXR via SteamVR, PSVR2 + PSVR2 Toolkit (eye tracking). RTX 5070 12 GB, Ryzen 5800X.
- SteamVR global 100 %, STALKER 2 per-app 250 % -> **4060x3228 per eye** at UEVR scale 1.0 [LOG].
- Liviu's TriView defaults (apply_liviu_defaults.py, last patch step): focus crop 0.6x0.6, periphery (context) scale 0.30, feather 0.10, gaze breakout 0.25, world scale 0.85, decoupled pitch, XYZ head scaling X3 Y1 Z1.5, etc. [SRC]
- In-game: DLSS SR Performance (native STALKER DLSS), **Cheeky DLSS 5 Neural Rendering (NR) plugin** (CheekyFoveatedDLSS.dll, UEVR plugin, NR before SR on the foveas), **VectorXR** (OpenXR frame-generation layer).
- **NO-GO (Liviu): never lower texture quality, never disable VectorXR frame gen, never disable Cheeky DLSS 5 NR.** Picture must not get worse.

## 3. Repo and build system
- Repo github.com/liviutrn/UEVR-Quad-Views-Mono (public). It holds **patch scripts, not a source tree**. CI (GitHub Actions, windows-2022) clones Joey UEVR 5ac7edc + private UESDK 3cffbc8 + uevr-frontend 60be4b0, runs the patch chain (Part B), builds the DLL, runs CTest (48 tests incl. WARP GPU pixel tests of the compositor), packages artifact `UEVR-TriView-B42-VRAM-<run#>`.
- Workflow `.github/workflows/triview-b1.yml`; triggers on push to `claude/triview-**`. Build ~30 min.
- Nothing compiles locally (private SDK). Local replay of the python patch chain works (fxc stub writes "DXBC"+124 bytes; skip verify_exact_baseline/verify_stage234/verify_stage1 which need the SDK) - this is how Parts C/D/E were produced.
- Branches: Claude only `claude/...`, ChatGPT `experiment/...`. Current: **claude/triview-b42-20261110 @ 76daf1f (B42.1)**, run 42785043946 green.
- Known flaky CI test: `quadview-edge-v2-production-gpu` (QuadViewEdgeV2GpuTests): fails ~1 in 2-3 runs (assertion "temporal=40 instant=40" or a ~4 s segfault), passes on rerun, root cause unknown [CI].
- Source of truth for headers: `quadview/*.hpp` in the repo are copied into `src/mods/vr/` by the chain (generated copy == repo copy). CTest compiles the repo copies.

## 4. Architecture: what happens in one TriView frame
(Order verified from code [SRC] and log lines [LOG] of Liviu's 10 Nov session.)

1. **Mode entry.** A saved ID7 profile loads as a *request*; the active mode starts as Joey's Native Stereo. Autostart (VR.cpp ~13827, `m_triview_autostart_stage`) warms up Native Stereo + Native Stereo Fix, then commits ID7 at a viewport boundary (`[Mono] Committed rendering method 7` [LOG]). Direct entry into ID7 without warm-up historically showed black [HEADSET].
2. **Game thread: views.** The stereo device hook `GetDesiredNumberOfViews` returns 4 in TriView (`quadview_desired_view_count()`, FFakeStereoRenderingHook.cpp ~32283). Roles: 0 = periphery (mono, centre camera, union FOV), 1 = unused placeholder (constructed, not rendered), 2 = left fovea, 3 = right fovea. Per-view projection/camera/crop come from QuadViewGeometry.hpp `make_layout` + gaze.
3. **Game thread: isolated renders.** `uevr::quadview::dispatch_main_views` (QuadViewFamilyRouting.hpp ~272-291, called at FFakeStereoRenderingHook.cpp ~26388) splits the family: for each role it selects ONE view + its OWN render target and calls the engine's BeginRenderingViewFamily with a one-view family. Each role gets its own frame number (`roles=9753,0,9754,9755 mask=13` [LOG]). => **3 complete UE scene renders per frame**, each with its own FSceneViewState/histories, its own DLSS SR evaluate. Reason: on 2.10 one-family stereo has bad shading and E1 failed; Lumen max 2 views per family; Native Fix does the same per eye.
4. **Placement rule (2.10).** A singleton family render lands at (0,0) of its target regardless of the view rect [CAPTURE, Build 52]. Hence every role has its own target, read at origin. Never use atlas X offsets.
5. **Native target set.** QuadViewNativeTargets / ResourceReuse / Retirement: a "set" = 3 colour targets (periphery e.g. 1218x968, foveas e.g. 2436x1937 each at crop 0.6 on 4060x3228) published per generation (`Published THREE independent UE5.5 source targets` [LOG]); fence-protected retirement; same-world reuse. Size changes go through `ResizeGate` (QuadViewGeometry.hpp): settle 400 ms, hold the live set meanwhile, latch/retry/timeout; B42 adds 1.5 s cooldown and a VRAM guard.
6. **NGX hooks (periphery depth).** QuadViewNgxDepth.hpp hooks NGX DLSS Evaluate/Create/Release + queue/command-list paths; on the periphery's DLSS evaluate it copies the DLSS input depth (in=813x646 for out=1218x968) into a snapshot pool (max 12 slots; measured 4 slots / 16 MB [LOG]) used for periphery depth reprojection (stereo-correct periphery per eye, jitter-aware). Depth-stencil sources are copied whole (D3D12 cannot sub-copy them).
7. **Cheeky NR** (separate DLL, ChatGPT's fork) hooks NGX too: inside each fovea's DLSS SR evaluate it runs NVIDIA NR (Feature 18) on the raw input before SR, per eye, sequentially. Enabling NR costs ~+0.9 GB VRAM at once [LOG 10 Nov].
8. **RHI tail -> compositor.** When the three role renders' RHI work has executed (`[QuadViews][RHI] native tail executed`), the D3D12 compositor (QuadViewD3D12.hpp + shaders, see Part D) builds each eye: periphery (reprojected with depth to that eye) underneath, the eye's fovea on top, edge/seam handling (B27 inward feather, B37 exterior, B40 continuous ambient edge colour matching, edge-V2 temporal history), focus lift / brightness matching, gamma tables, sharpen. Output into the OpenXR double-wide swapchain (8120x3228) (`[QuadView][CopyEnqueued]`, `[QuadView][Submit] eyes=2` [LOG]).
9. **Hold window** (TriViewHold.hpp, B41): if a frame is missing, re-submit the last image (still head-tracked) up to 250 ms instead of black.
10. **OpenXR submit** -> VectorXR frame generation -> SteamVR -> PSVR2. UI (Slate) goes to a dedicated 1024x768 target and its own layer [LOG].
11. **Gaze.** QuadViewPSVR2Gaze / QuadViewGaze: PSVR2 eye tracking moves the fovea crops, with stabilisation and breakout thresholds.

## 5. Measured numbers
- Fixed cost: **each separate render family ~7 ms GPU regardless of pixels; an extra view inside the same family ~2.5 ms** [MEAS 200x200]. => number of renders is the main lever, not pixels.
- 200x200/eye: Mono 68 fps, Native Stereo 58, Native+Fix 46, DuoView Mono 45, tri-view 34 [MEAS].
- 4060x3228/eye: TriView B41 **~26 fps**, GPU-bound (fps rises with NR off / smaller fovea) [LOG/HEADSET]; Native Stereo ~24 at 3.8k; stock AFW 38 (rejected for quality).
- VRAM (B42, 10 Nov): steady **~8.6 GB of a ~10.1 GB DXGI budget (85 %)**; Cheeky NR enable +0.9 GB -> 93-94 %; depth pool 16 MB [LOG]. Budget shrinks ~1 GB while other processes (SteamVR etc.) grow [LOG].
- B40 colour matching: Liviu sees 0.5-1 ms (32 lanes x 60 serial samples) [HEADSET/EST].
- Liviu measured NR before SR ~5 ms vs ~15 ms after SR [MEAS, as reported].

## 6. Stability history (most important open area)
- **BSOD 0x139 (KERNEL_SECURITY_CHECK_FAILURE)** surge from 6 Nov (29 in 4 days, TriView B13+ era). Decisive test: periphery depth OFF + Cheeky NR OFF still BSOD; in the menu, spamming crop changes climbed VRAM until BSOD at ~10 GB => VRAM exhaustion (driver bug under overcommit) [HEADSET/LOG]. Growth source: UE allocates scene buffers per new view size while old ones live.
- Engine.ini `r.SceneRenderTargetResizeMethod=2` + ForceOverride stopped the climb but raised the start from 6.36 to 9.06 GB [LOG]; Liviu told to remove it.
- **B42/B42.1 (current)**: VRAM guard on resizes (refuse if used + 100 B/source px > 85 % budget), 0.05 size snapping, 1.5 s rebuild cooldown, low-resolution start (0.3, one live switch to 1.0 when loaded and VRAM allows), VRAM logs. Details: claude/handoff-b42-1-verify-20261110.md. **Low start and refusals not yet seen in a headset session.**
- B41.1 fixed black flashes: D3D12Hook refreshed m_device via GetDevice every frame (COM nulls the out pointer) -> other threads read nullptr -> false target rejections and rebuilds [LOG/SRC].
- 10 Nov CTD: Cheeky NR enabled (+0.9 GB), then NR foveation OFF (bigger NR image) -> out of VRAM -> crash [LOG]. Cheeky fix in progress by ChatGPT.
- Unexplained: "player moves by itself" once (no evidence yet).

## 7. History in one table (what failed and must not be repeated)
| Approach | Result | Lesson |
|---|---|---|
| QuadViews Builds 32-52 (4 views, atlas) | worked on 2.06, broke on 2.10 | 2.10 singleton renders land at (0,0): no atlas offsets |
| E1 one-family stereo | shading artefacts | per-eye families needed; **do not try one-family stereo** |
| DuoView AFW (PureDark warp) | fps fine, image rejected | quality |
| Synthetic stereo CI31-CI127 (depth-warped other eye) | 40 fps at 4.5k but doubled hands, edge jitter | artefacts |
| Third view as extra engine view index (proof builds) | head tracking broke ("theater screen") | Joey's 2-view bookkeeping; TriView uses isolated renders instead |
| Guessing UE struct offsets | harmful | never guess offsets |
| Stereo-atlas NR before SR | impossible: foveas are separate renders, each SR runs inside its own render | (10 Nov analysis) |
Full digest: project doc claude/failed-attempts-and-lessons-20261104.md.

## 8. Working rules (team)
- Claude and ChatGPT are one team; review each other; label every claim (source-read / CI / headset / estimate). No fake green: CI success is not a headset success.
- One build per real hypothesis, after local replay + an independent review. Check CI once when due.
- Liviu tests; at most 3 precise questions per build.
- Usage care: spend on thinking (root causes, design, review); avoid exploratory builds and repeated reads.

## 9. What we want from you (Fable)
Analyse the current TriView (B42.1) for the best **return on effort** in:
1. **Performance** (target: noticeably above ~26 fps at 4060x3228/eye without lowering image quality). Known ideas, unevaluated: periphery rendered every other frame with reprojection (est. 26 -> ~30 fps); fewer/cheaper passes in the per-role render (which UE features run 3x that could run once or cheaper on the periphery, e.g. via per-view show flags or cvars that don't change the picture); compositor cost (B40 colour matching 0.5-1 ms); CPU/render-thread overhead of 3 families.
2. **Stability**: remaining crash/BSOD risks (resize/reallocation paths, NGX hook interplay with Cheeky, lifetime/fence/retirement, threading), the automatic low-res -> full-res switch (new, untested), races (e.g. plain ints read cross-thread).
3. **VRAM**: where the ~8.6 GB goes and what can be freed without quality loss (UE per-view histories x3, retired sets, NR caches).
4. **Quality**: seam/edge, periphery tremble/jitter history, reprojection artefacts.
5. **Code health**: dead code from abandoned paths (QuadViews 4-view, DuoView) that still runs or costs, risky patterns.

Please deliver: a ranked list (impact x confidence / effort), each item with evidence (file:line from Parts C/D/E), a concrete change outline, risk, and how Liviu can verify it with at most 3 headset questions. Mark what you verified in code vs what you infer. If something needs a measurement first, say exactly which log line or number decides it.

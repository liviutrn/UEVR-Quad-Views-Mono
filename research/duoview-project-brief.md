# DuoView project brief - HANDOFF (updated by Claude Opus 5.5, 31 Oct 2026, ~20:00)

Read this first in any new chat. Liviu is not a programmer: plain words, few steps, at most
three precise test questions per build. Claude leads; ChatGPT is a team member who gets
concrete work orders (he holds the full project history). Claude pushes only claude/...
branches; ChatGPT uses experiment/... . Labels: source-read / CI-verified / headset-verified.

## Current goal: "tri-view" true-stereo build (approved by Liviu, 31 Oct)
3 real renders per frame: LEFT fovea + RIGHT fovea (true per-eye cameras, native stereo where
you look) + ONE shared mono periphery (centre-head pose, full FOV, low res). Each eye = own
fovea blended over the shared periphery, mapped per eye by OUR compositor (explicit
periphery convergence, default infinity, slider for fine tuning). No synthesis.
Plan (one build per step, each headset-tested):
  A. Cleanup + efficiency on Build 51 (see efficiency list; decide target right-sizing after
     the VRAM measurement below).
  B. Tri-view: 4 -> 3 sources (separate renders, Native-Fix style = known-good shading).
  C. Port from v207: MPC_FOV override + auto reapply after load + hotkeys, XYZ head scaling,
     Catmull-Rom periphery. (Mono eye alignment -> becomes periphery convergence only;
     Mono HUD convergence probably not needed in stereo.)
  Plan B only if CPU-limited: share one render via split-screen-style independent FULL views
  (NOT stereo SECONDARY: secondary views come out too bright - Build 40, Liviu confirmed).

## Base: Build 51 (Liviu's choice; good recenter)
- Built in repo liviutrn/MUSE-UEVR-DUOVIEW, workflow .github/workflows/id7-build51-source-lifetime.yml
  (branch fix/id7-build51-source-lifetime-ci-20261023, commit 6780adb, run 39868145292,
  artifact UEVR-QuadViews-ID7-Build51-Compiled-1 id 12465484329). That workflow checks out
  liviutrn/UEVR-Quad-Views-Mono@f4e086c (path "workspace") and applies its quadview/ scripts
  to joeyhodge/UEVR@5ac7edc (+UESDK 3cffbc8, frontend 60be4b0): apply_quadviews, consumer,
  native_delivery, native_retirement, recovery, role_frames, hook_trace, hook_output_trace,
  present_setup, target_lifetime, embed_shader. To change it: branch claude/... from f4e086c
  in UEVR-Quad-Views-Mono, copy that workflow in, point its "workspace" checkout at our commit.
- Build 52 (run 39930401452, branch build/id7-build52-foreground-mpc-20261023): adds shading
  parity toggle (no visible effect), conditional MPC (works), guarded transitions. Liviu's test
  (31 Oct): ~25 fps at 3.5k x 3k per eye, lighting OK, hands FOV correct with MPC, playable with
  VectorXR (works from ~22 fps), BUT constant in-game menu error and bad recenter -> do not use
  52 as base. Its log: 4 sources at 6984x2776 each (double-wide, all forced equal size/format),
  ~30 HookTrace lines/s (rate-limited; CPU gain from removing it is small, log ~70 MB/h).
- FPS facts (Liviu, 3.5k x 3k): DuoView Mono "a lot better" than quad; Joey stock Mono ~= quad.
  -> quad's cost = second sharp fovea (pixels) + removable overhead. GPU-vs-CPU limit NOT
  measured yet (no GPU % reading). Earlier at 4k: Mono ~40, quad 25-30. Tri-view estimate
  ~28-33 fps (unmeasured).

## Efficiency list for the stereo build (ranked by expected payoff)
1. Cheaper periphery render (own render => own settings: lower screen % / DLSS mode, fewer
   effects such as SSR, AO, fog, lower Lumen quality). Likely biggest GPU win.
2. Right-size the source targets (focus = crop x density, context = periphery scale) - decide
   after measuring VRAM: Task Manager "Dedicated GPU memory", DuoView Mono vs Build 51/52 at the
   same spot. Risky part of the code (engine-owned targets, vtable gamma hook, equal-size checks).
3. Smaller stereo fovea (0.4 x 0.4) with eye tracking. 4. Tri-view (one render fewer).
5. Catmull-Rom periphery (lower periphery scale for same look). 6. DLSS5 NR on foveas only.
7. Hook-trace logging off (minor).

## Open work order to ChatGPT (sent 31 Oct ~19:50)
Using the exact Build 51 pipeline: (1) where target size is decided / targets created / what
requires equal sizes; (2) does UE size scene textures from family RT size or view rect in this
path; (3) can the context render get cheaper per-render settings and where; (4) every place
hard-coding 4 views. Output: research/2026-10-31-build51-map-for-3view.md on branch
experiment/3view-research-20261031 (his first version wrongly said Build 51 was not
reproducible; it is, via the MUSE workflow).

## Stable product: DuoView Mono
- v186.2 = build #206 (commit 9152267, workflow duoview-joey-stage234.yml) in UEVR-Quad-Views-Mono.
- v207 = build #211 (run 41210849144, commit 4020a44, branch claude/v207-auto-fov-vram-periphery):
  auto FOV reapply after world change, lazy gather atlas (~380 MB at 4k), Catmull-Rom periphery
  toggle, PSVR2 retry backoff. CI-verified; Liviu reports it good.
- Local replay of that pipeline: clone joeyhodge/UEVR@5ac7edc + uevr-frontend@60be4b0, stub fxc
  on PATH, run apply_* scripts in workflow order (catches anchor errors in ~1 min).
- Declined (not worth risk): single-width shared swapchain; direct draw without intermediate.

## Findings worth keeping
- Mono convergence: Joey mono (and DuoView) converge at ~2 m on PSVR2 (Liviu, HUD at 100 m test);
  Mono Eye Alignment -1.5 cancels it (~2 deg). Likely cause: both eyes submitted with the left eye
  orientation + centre position; SteamVR/PSVR2 misplaces the right eye. Liviu's IPD = 72 mm.
  Real stereo looks correctly sized.
- VectorXR (github.com/DienerTech/vectorxr, MPL-2.0) is an OpenXR API layer before SteamVR; frame
  gen is per view everywhere (optical flow packs both eyes in one atlas). No mono dedupe; not
  forking. It has Quadviews support (frame gen on periphery+focus) - possible far-future idea.
- Synthetic stereo ABANDONED (CI48-CI82): holes near close objects can't look right; hands doubled
  even with single-source fill (cause never found). Native stereo at DuoView centre sharpness is
  ~6x too expensive.
- Build 40 = one render family with 4 views: good performance, secondary views too bright.

## Lessons (process)
- Measure FPS, GPU %, VRAM before architecture work. One build per hypothesis.
- Local patch replay + cheap fresh-eyes review (Haiku) before every build.
- New chat per big task; keep this brief current (Project doc claude/duoview-project-brief.md
  and this repo copy research/duoview-project-brief.md on branch claude/project-brief).

# Handoff: DuoView Mono (mode 6) brought up to date inside the TriView build (Claude -> ChatGPT, 12 Nov 2026)

Owner: Liviu (not a programmer, tests in the headset, max 3 test questions per build).
Author: Claude. Implementer: ChatGPT. Verifier afterwards: Claude.
Team rules: research/PROJECT_BRIEF.md on branch claude/team-brief (one team, label every claim
source-read / CI / headset / estimate, no fake green, one build per real hypothesis, local replay
of the patch chain before every push, never change another member's branch).

## 1. Goal (Liviu's words, condensed)
One UEVR build in which Liviu can play TriView (mode 7) normally and switch to DuoView Mono
(mode 6) in areas that are very hard on the GPU/CPU. Mode 6 must be:
1. exactly our latest DuoView Mono (all its features), and then
2. improved with everything from TriView that applies to a mono picture: the new sharpening
   (bigger limits, extra-wide ring), seam matching, vignette/brightness correction, etc.
NOT wanted: "sharp periphery" (Catmull-Rom periphery upscale). Liviu does not like it. Keep it
available only if it already exists in the DuoView version you port, and default it OFF.

## 2. Where things are (source-read by Claude, 12 Nov)
- Start branch: `claude/triview-b43-20261112` @ 1f75a2d (TriView B43, CI run 154 green, headset
  test pending). Create `experiment/duoview-parity-<date>` from it. Do not push to claude/ branches.
- Build: workflow `.github/workflows/triview-b1.yml` (trigger: push to claude/triview-** or
  experiment/triview-** touching quadview/** or the workflow). **Name your branch
  `experiment/triview-duoview-parity-<date>` so the push trigger matches**, or add your branch
  pattern to the trigger.
- Latest DuoView Mono line: branch `claude/v208b-sharpen5-vram-20261102` @ 9362b5e (v208d),
  workflow `.github/workflows/duoview-joey-stage234.yml`. v207 is the last HEADSET-verified
  DuoView (31 Oct). v208/v208b/v208d were CI-verified; headset status unknown to Claude.
  **Ask Liviu first which DuoView he actually plays (v207 or v208d) and port exactly that.**
  Do NOT use ChatGPT's v211/v218 DuoView branches (Liviu rejected them: depth/distance sharpen
  did not work).
- Same pins in both lines: Joey UEVR 5ac7edc, private UESDK 3cffbc8, frontend 60be4b0.

### What mode 6 in the TriView build is today
The TriView workflow builds DuoView from the `duoview/` folder pinned at f0a6be7 (old Build 182
baseline). A workflow step ("Verify preserved DuoView baseline against pinned ID7 parent",
triview-b1.yml ~line 28) FAILS the build if `duoview/` differs from f0a6be7. Then:
stage1 -> stage234 -> five byte-identical DuoView port scripts in `quadview/duoview_port/`
(apply_foreground_mpc_minimal, apply_xyz_head_scaling, apply_manual_fov_global_lookup_v165,
apply_v205_manual_fov_runtime_hotkeys, apply_v207_auto_fov_after_load) -> QuadView/TriView
overlays -> apply_liviu_defaults.py.

### Missing in mode 6 versus the v208d line (script/file comparison, not tested)
DuoView workflow scripts not applied in the TriView build, in DuoView's own order:
1. `apply_mono_hud_convergence.py` (after foreground MPC)
2. `apply_mono_alignment_build48.py` (mono eye alignment; Liviu uses -1.5 for life-size scale)
3. `apply_runtime_eye_alignment_persistence_build49.py` (+ its test) (keeps the alignment saved)
4. `apply_v208_shared_eye_vram.py` (same image for both eyes, VRAM readout)
5. `apply_v208b_sharpen_max_change.py` (sharpen 0-5 + max-change slider)
6. `apply_v208d_vram_options.py` (skip depth swapchain, gather-atlas line)
Core files that differ between `duoview/` @f0a6be7 and @9362b5e (`git diff --stat`):
DuoViewComposite.hlsl (+4/-0), DuoViewConfig.hpp (+18/-2), DuoViewD3D12.hpp (+36/-12),
DuoViewNativeCompositeRaster.hlsl (+43/-3, includes the Catmull-Rom "sharp periphery" path),
DuoViewPSVR2Gaze.hpp (+8/-1, v207 back-off when the PSVR2 Toolkit is missing).
In DuoView's workflow, mono HUD + alignment come between foreground MPC and XYZ head scaling.
In the TriView workflow those five port scripts run as one loop after stage234: insert the new
scripts at the matching positions.

## 3. Phase 1 build: mode 6 = latest DuoView (no new features)
- Update `duoview/` to the chosen DuoView commit and move the baseline check to that commit
  deliberately (say so in the commit message). TriView code must not change.
- Add the missing scripts above (copied byte-identical where possible, like duoview_port/).
  Expect anchor conflicts with later QuadView/TriView overlays: resolve them in NEW overlay
  scripts, never by editing older scripts in place.
- Add Liviu's DuoView values to `quadview/apply_liviu_defaults.py` (at least Mono eye alignment
  -1.5; ask him for his DuoView config.txt lines). He deletes UEVR settings after every build,
  so defaults are what he gets.
- Keep all CTests and contract tests green. Replay the full patch chain locally before pushing
  (see section 6).
- Headset questions (max 3): (1) mode 6 looks and feels like your DuoView (scale with
  alignment -1.5, HUD, sharpen, FOV after loads)? (2) switching 7 -> 6 -> 7 in-game works without
  black/crash? (3) TriView unchanged?

## 4. Phase 2 build: TriView improvements ported into mode 6
TriView's compositor is `quadview/QuadViewComposite.hlsl` + `QuadViewD3D12.hpp` + settings in
`QuadViewSettings.hpp`. DuoView's is `duoview/DuoViewNativeCompositeRaster.hlsl` (+
DuoViewComposite.hlsl) + `DuoViewD3D12.hpp` + `DuoViewConfig.hpp`. Different shaders: port the
math, do not try to run the QuadView compositor for mode 6. Where you copy a function, add a test
that freezes it equal to the QuadView original (pattern: quadview/test_triview_b23_four_samples.py).
Applicable, in priority order:
1. **Sharpening** (TriView B8 + B43): DuoView and TriView use the same v186.1 Glamarye "Bigger"
   filter. Port: strength 0-20, max change 0.05-0.80, extra-wide ring (QuadView shader
   `GlamSharpenRingChange`, radius 2.8 / guard 7.0, added on top of the normal ring, display only).
   **Per-eye settings caveat:** with DuoView "Same image for both eyes" ON (v208) both eyes share
   one image, so left/right sharpening cannot differ, and per-eye differences would also stop a
   mono VectorXR collapse. Implement per-eye values only when that toggle is OFF and say so in the
   menu; with it ON the left values apply to both. Liviu wants the right eye sharper (worse
   vision there), so he must know this trade-off (more VRAM/bandwidth with the toggle OFF).
2. **Brightness/vignette correction of the fovea** (TriView B30 focus lift: FocusLiftEnabled,
   FocusBrightness, FocusLiftStrength, FocusCornerGain, FocusLiftOnset, FocusLiftPower; B31
   `CorrectFocusColor` anti-vignette).
3. **Seam matching** fovea<->periphery (TriView B35 edge match, B37 exterior seam, B38 inward
   feather, B39/B40 continuous ambient edge colour matching with AmbientRadiusPx/InsidePx/TimeMs,
   Edge V2 temporal: EdgeV2Mode/Strength/Rate/Reach/Fast/Noise; SeamMode/Strength/MaxGain/
   ColorStrength/BrightnessEV/LocalStrength/TransitionPixels/RadiusPixels). DuoView's fovea and
   periphery come from the same mono camera, so mismatch is smaller than in TriView, but Liviu
   asked for it. Notes: quadview/B35..B41 NOTES files. Watch cost: B40 matching measured
   0.5-1 ms (Liviu, estimate).
4. Optional, check first: TriView B41 hold window (re-submit the last image up to N ms instead
   of black). DuoView has its own SubmitContinuity; port only if mode 6 shows black flashes.
Not applicable to mode 6: depth reprojection, NGX depth hooks, stereo foveas, ResizeGate/VRAM
guard/low-resolution start (TriView render-target logic), autostart warm-up.
Global fixes that already help mode 6 (no work): B41.1 D3D12 device nullptr fix.
- Defaults: every new option defaults so that mode 6 looks exactly like Phase 1 until Liviu
  turns it on (except where he asks otherwise).
- Headset questions: (1) right eye at 20/0.80 + extra-wide (toggle OFF same-image): sharp enough,
  halos? (2) seam/brightness matching ON: fovea edge less visible? any shimmer at the edge?
  (3) fps in a hard area mode 6 vs Phase 1 (same spot).

## 5. Deliverables for Claude's verification
- Branch name + commit per phase, CI run link, artifact name.
- A short notes file per phase in quadview/ (what changed, which scripts, which tests, what is
  CI-only vs headset-verified).
- The local replay command/output summary, and the list of tests you changed and why.

## 6. Local replay (how Claude does it; no SDK needed)
Clone joeyhodge/UEVR @5ac7edc (+ submodules glm, imgui, spdlog) as `backend`, joeyhodge/
uevr-frontend @60be4b0 as `frontend`, the repo as `workspace`; run every `python ...` line of the
workflow's patch steps in order, skipping verify_exact_baseline / verify_stage1 /
verify_stage234 / source_checkpoint (they need the private SDK). Replace fxc with a stub that
writes "DXBC" + 124 zero bytes to the /Fo path. For a real shader syntax check, glslangValidator
-D (HLSL front end) works on QuadViewComposite.hlsl. Lesson from B43: a shader change that made
the seam compute shader much larger failed the WARP seam GPU test in CI twice; keep seam-analysis
code paths unchanged unless needed.

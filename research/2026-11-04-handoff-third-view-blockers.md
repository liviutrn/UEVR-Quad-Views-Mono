# HANDOFF: third view (TriView) blockers - written 2026-11-04 by Claude (Sonnet 5.5)

For the next model. Read this first, then `research/2026-11-03-third-eye-design-v2.md`, `PROGRESS.md`, and
the project doc `claude/triview-proof-status-20261103.md`. User: Liviu, not a programmer, plain words, wants one
well-thought attempt rather than many small tests. He does the VR tests (costly). Claude works only on `claude/...` branches.

## 1. The goal (current scope)
STALKER 2 (patch 2.10, UE 5.5.4, DX12, OpenXR/SteamVR, PSVR2, RTX 5070). Joey UEVR "Native Stereo + Native Stereo Fix" works
perfectly (two real eyes). PROVE that a THIRD view can be rendered with the same plumbing as the second eye, without breaking
head tracking. Third view = exact clone of the second (right) view, only tinted red so it can be told apart.
No cropping, periphery, or eye tracking until this is proven.

## 2. What was built and tested (branch `claude/triview-proof-20261103`)
- Build 1 (commit fbc1e81): TriView base (rendering method 7), engine asked for 3 views (GetDesiredNumberOfViews=3, hooks for view index 2),
  third view rendered as a singleton into its own Kismet render target, D3D12 pixel-shader compositor draws the XR image from 3 textures.
  PROOF mode: eyes uncropped; right eye = left 1/2 real second view, right part = third view with red tint, 2 px black seam.
- Build 2: same, but view index 2 returns stereo pass SECONDARY (like the real second view) instead of PRIMARY.
- CI: green (compiled, 54+ tests, WARP GPU pixel tests of the compositor). Both HEADSET-tested by Liviu: both FAIL.

## 3. Headset results [HEADSET, Liviu]
- Third view OFF (proof on): head tracking identical to Native Stereo, image normal, right eye black where the red would be. So the compositor path itself is fine.
- Third view ON: whole image unstable, slightly trembling, and projected ~2 m in front like a head-tracked theater screen. Breaks the image.
- Build 2 (SECONDARY label): same. Label was not the (only) cause. Liviu tried all toggles.

## 4. What is PROVEN vs NOT
PROVEN:
- Third view renders correctly: GPU capture of the headset run shows it image-equivalent to the second view (correlation 0.97, ~2 px shift). [CI-built build, headset-run capture]
- Third view gets its own scene view state (log: "separate history", different state pointers). [LOG]
- Per frame the camera pose/rotation/projection of views 0,1,2 are consistent (log, build 2). So pose MATH looks right. [LOG]
- Build 2's relabel path ran (log shows Joey's same-pass relabel lines).
NOT PROVEN / OPEN:
- Why a third ENGINE view destabilizes head tracking. Root cause unknown.
- Whether Joey's own bookkeeping that assumes exactly two eyes is hit (see section 5).
- Odd numbers in build-2 log/capture: capture report said "composites 599, rejected 342" (rejected = our compositor fell back to Joey's copy; the capture was taken with PROOF OFF so it is not about the proof image) and Joey logged 6 "Refusing stale submit packet" (packet 2-3 engine frames old; log is rate-limited to 1 per 2 s, so real count unknown). Possible pacing/delivery clue, not analysed beyond this.

## 5. Findings from reading Joey (5ac7edc, src/mods/vr/FFakeStereoRenderingHook.cpp; helper inventory + own reading)
- Native Fix renders eye 0, then eye 1 as TWO SEPARATE renderer calls (~L26480-26710): clone pose `pipeline_states[now]=pipeline_states[last]` (only slot +1), set_render_target(capture target), views={right}, count=1, scene->decrement_frame_count(), render. Then one packet is published.
- Joey validators require EXACTLY 2 engine views and fail closed to the original render otherwise (~L25254, 25705, 26070). Our builds made the engine build 3 views, which is outside anything Joey validated.
- A view index of 2 flips Joey's static `index_starts_from_one` / `index_was_ever_two` in calculate_stereo_view_offset, adjust_view_rect and projection (~L29999-30018): eyes swap, view 0 ignored. TriView guards index 2 with a runtime flag `triview_owns_view_index_two()`; if that flag is false for any frame the legacy swap happens. Weak point, not verified in the log.
- Pose pipeline: only slot +1 cloned; a third render may need +2; packet `render_frame` taken at publish time; stale window accepts only exact / same engine frame / next frame (NativeFrameDiagnostics.hpp). A longer 3-render sequence may exceed it.
- LocalPlayer view-state count (`m_fixed_localplayer_view_count`, post_init_properties replay, `GetDesiredNumberOfViews` returns 2 inside post-init) decides how many FSceneViewStates exist. State bookkeeping structs are 2-wide.
- XR submit and the D3D12 delivery path only know 2 sources / 2 views. We bypass that with our own compositor (works with third OFF).

## 6. Design v2 (not built): third eye as a THIRD RENDERER CALL
Engine keeps exactly 2 views. After the second-eye call: set_render_target(third target), views={clone of eye-1 view with its OWN scene state}, count=1, decrement_frame_count, render. Clone pose slot +1 and +2. Own capture target. One packet with 3 captures. Reuse our compositor. Details in research/2026-11-03-third-eye-design-v2.md.

## 7. BLOCKERS
1. PRIVATE UESDK (Joey's, commit 3cffbc8; submodule empty in public checkout, CI has a credential). Cannot read locally: FSceneView layout (can `State` be overwritten after construction?), FScene::decrement_frame_count internals, FSceneViewFamily. Design v2 depends on this. Do NOT publish SDK contents in logs/artifacts (repo is public). Options: Liviu attaches the FSceneView header; or CI compile-time checks (static_assert on members).
2. Root cause of the head-tracking break is unknown; no test isolates it yet. Candidates (all unverified): Joey eye-order statics hit by index 2; pose slot +2 / packet staleness with 3 renders; third FSceneViewState/LocalPlayer count; interaction of PostInit view count.
3. No local build/test: only GitHub Actions (windows-2022). One build per hypothesis; Liviu's VR time is costly.
4. Fallback agreed with Liviu: if TriView base fails, start from pure Joey baseline and add the third eye exactly like the second (design v2). Liviu rejected side experiments ("extra render pass") and wants it done right, independent third eye.

## 8. Ideas worth trying (ranked by my judgement, none done)
1. Implement design v2 on pure Joey (engine = 2 views; third render call). Needs blocker 1 answered.
2. Cheap offline check of the current builds: does `triview_owns_view_index_two()` stay true every frame (log it) and is Joey's `index_was_ever_two` path ever taken?
3. Make Joey log every stale-packet refusal as a counter (not rate-limited) and compare third ON vs OFF.
4. Compare with old QuadViews Build 51 (worked on 2.06, 4 separate renderer calls, own dispatch, every view forced eSSP_PRIMARY, independent view states; Native Fix gate disabled). See research/2026-10-31-build51-map-for-3view.md. Its geometry broke on 2.10 (singleton lands at (0,0) of target) - separate known problem.

## 9. Repo / process facts
Repo github.com/liviutrn/UEVR-Quad-Views-Mono (public). Workflow `.github/workflows/triview-proof.yml` triggers on EVERY push to `claude/triview-proof-20261103` (use `[skip ci]` for docs). Patch script: `duoview/joey_stage1/apply_triview_stage1.py` (C++ inside Python strings). Pins: Joey 5ac7edc207866569334175e4ed8a7517971547f6, UESDK 3cffbc82429b6165ceec2714f0f0d9ae48f55596, frontend 60be4b0f9a646109fd9fdf448bacd41477234091. Always label results: compiled / CI-tested / headset-tested. Commit trailers per session rules.

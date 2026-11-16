# DuoView reconstruction — Phase C / 16 Nov 2026

## Production gate

**NO-GO for a new stereo reconstruction algorithm.** No playable branch, shader, real-world GPU resource ownership, or default changed. Continue using official compiled-WARP M4 baseline, not experimental CPU overlays.

## Source diagnostics actually integrated

- Commit `6c3049248bf6d3e4e45595487a77b26d8560743d` on isolated branch `experiment/duoview-improved-stereo-reconstruction-m41-diagnostics-20261116`.
- Workflow applies an opt-in metadata-only generator immediately after `apply_duoview_m41_frame_bind.py`, then runs its generated-source tests before subsequent M5 overlays.
- GitHub Actions #354: https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/43917492346 . At last observation run remained in progress; portable sanitizers passed, Windows build not yet complete. A single one-time follow-up is scheduled; do not claim it passed.
- Source counters: exclusive M4 marker rejection reasons, ready/unready/ineligible lookup and Present-epoch skew histograms before XR gating. They identify potential dropped intervals, **not causal scene-frame matching**.

## New CPU quality candidate and adversary

Inputs: independently calibrated 1024x816-per-eye **official #349 compiled-WARP baseline** as fallback, synthetic same-frame mono RGB and raw Quality-like fine/coarse NGX depths. CPU-only forward ownership with registered RGB motion and connected motion regions; no hidden stereo GT is used for reconstruction.

Recipe tested: global mono RGB phase-registration if correlation >0.5 and translation <3px, RGB-change threshold >0.08, connected component >=150 pixels, dilation 7px, fovea-only fine/coarse near-depth agreement within 0.1. Variant without additional color-edge gate shows nominal near-silhouette IoU improvements of **+5.27 percentage points moving weapon** and **+2.17 points moving foliage**, with no nominal stationary-foliage temporal penalty.

Mild artificial 1px shift plus 9x9 or 17x17 local color noise passes the nominal safety checks once registered components are filtered. **A stronger deliberately coherent 7x7-pixel-block color shimmer in stationary foliage decisively defeats this approach**: +60.67% edge-temporal error with color-edge gate; +270.75% without gate, compared with official M4. Thus **NO-GO** despite nominal wins. Adversary magnitude is synthetic; not a measured game condition.

## Why this matters

Previous Phase B fine/coarse-only ownership produced +54.5% stationary edge temporal regression. Color-temporal gating can prevent that only while RGB itself is stable. Both depth and color can shimmer; neither is a proven independent visibility oracle. Do not replace a depth-only false positive with a color-only false positive.

## Next gates

1. Finish Windows CI #354 with actual compile/front-end/CTest/WARP evidence. No merge if failing.
2. If diagnostic passes, obtain one short bounded runtime metadata log; report missing intervals and epoch skews without asserting source identity.
3. Obtain trusted color/depth producer-frame ID or registered real RGB-D capture, not merely identical Present epochs.
4. Only then compile new candidate shaders for 2030x1614 and 4060x3228-per-eye WARP with full-size independently calibrated charts, 1–3px wires and coherent 50px shimmer groups. Enforce all-scene edge temporal gates.
5. RTX 5070 profiling (VectorXR off) and independent quality review before any guarded headset build.

Full Phase C scripts, score JSON and SHA-256 manifest are packaged locally as `DuoView_Improved_Stereo_Reconstruction_PHASE_C_20261116.zip`. This note alone does not include the original 69MB WARP source capture archive.
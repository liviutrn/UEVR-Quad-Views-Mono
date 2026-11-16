# Phase D — Motion-vector feasibility and M4.1 diagnostic follow-on (2026-11-16)

**Production decision: NO-GO.** No reconstruction shader or playable runtime defaults changed.

## Windows integration already underway
- Isolated Phase C provenance probe commit: `6c3049248bf6d3e4e45595487a77b26d8560743d`.
- Workflow: https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/43917492346 (#354).
- Last direct observation: production Windows backend still building; portable sanitizers passed. A single automated check-back was already scheduled. Full Windows tests not yet confirmed.
- Present epoch/fences check timing and readiness, **not causal color/depth scene identity**.

## New Phase D results
Reused official compiled #349 M4 WARP BGRA at 1024×816 per eye as unmodified fallback, calibrated from zero-stereo UV chart. CPU candidate uses modeled Quality-like fine/coarse depth and **idealized analytic scene-ground-truth near-object motion masks** as a hypothetical motion-vector signal. That mask is an *oracle upper bound*; actual NGX motion vectors were never captured.

| CPU visibility overlay | Moving weapon IoU, pp | Moving foliage IoU, pp | Static false-depth edge temporal change |
|---|---:|---:|---:|
| Perfect near-object motion, no color gate | +7.12 | +2.62 | 0% |
| Same, false 7×7 MV groups at 1% of stationary near pixels | +7.12 | +2.62 | **+26.30% — FAIL** |
| Same, 5% false groups | +7.12 | +2.62 | **+92.50% — FAIL** |
| Perfect motion + RGB/depth color edge gate | +0.08 | +0.43 | 0% |
| Edge-gated, false 7×7 MV groups 1% | +0.08 | +0.43 | +3.65% |
| Edge-gated, false groups 5% | +0.08 | +0.43 | **+14.64% — FAIL** |
| Near MV nonzero in static-image inconsistency stress, no gate | +7.12 | +2.62 | **+230.96% — FAIL** |

All numbers are synthetic CPU candidate changes relative to real compiled WARP **baseline** images. The static-image/nonzero-MV stress is intentionally inconsistent, **not a physically correct head-motion simulation**. No new GPU candidate was compiled, tested on an RTX, or run in-game.

## Extra diagnostic prototype (NOT merged and NOT Windows built)
A metadata-only NGX motion-vector probe was prepared as a source post-pass to the already instrumented M41 generated C++ and D3D12 Present logger:
- Reads `MotionVectors` resource `GetDesc()`, `MV.Scale.X/Y` from public NGX API, and counts presence/format/extent/scale validity.
- No resource ownership retained, GPU allocations, image copies, GPU readbacks, shader or selection changes.
- Five Python exact-anchor/mutation tests pass; seven actual C++20 compiled mock-NGX boundary cases pass.
- Generated change: two backend source files, 108 unified diff lines, not sent to CI yet. Full source and original fixtures included in Phase D downloadable ZIP.

NVIDIA's DLSS guide explicitly warns that velocity can be missing/incorrect on thin geometry, and motion vectors need correct scale/jitter interpretation:
- https://github.com/NVIDIA/DLSS/blob/main/include/nvsdk_ngx_defs.h
- https://github.com/NVIDIA/DLSS/blob/main/doc/DLSS_Programming_Guide_Release.pdf

**Next go/no-go order:** finish #354 CI; obtain one bounded M41 provenance log if successful; decide whether to build the optional MV metadata-only post-pass; establish trusted real color/depth producer identity and MV validity; only then attempt compiled full-size (2030×1614 / 4060×3228) WARP experiments with worst-scene edge-temporal acceptance and RTX 5070 timing. Do not spend additional real-headset quality sessions on CPU-only proposals.

The complete 15-file Phase D ZIP contains code, deterministic result JSON, pre/post-generated patch, two source fixtures, tests, SHA256 manifest, and required original WARP capture hashes. This research note is intentionally not a claim of a production quality breakthrough.

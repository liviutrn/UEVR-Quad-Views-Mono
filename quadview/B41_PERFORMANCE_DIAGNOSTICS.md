# TriView B41 — opt-in performance diagnostics

Based on **B40 continuous ambient**, unchanged render-source identities, scene histories, native-target ownership, compositor geometry, depth, VRAM retirement, sharpening, blur, and color algorithms.

In VR > Quad Views Stereo > focus controls and diagnostics, expand **B41 Performance Diagnostics** and enable the checkbox. It also enables the existing QuadView GPU timestamp control. Off by default; no new rendering passes, GPU waits, fences, readbacks, or frame queues. All samples are aggregated with atomics, with no per-frame file writes. Disable after benchmarking.

## Measured, with clear boundaries

* Composed-image cadence, output accepted/rejected and missing source counters. This is **not display FPS**, reprojection FPS or the true Unreal game engine frame time.
* CPU callback wall time separately for shared peripheral view, left fovea, right fovea. These are timings around synchronous native view-family calls; they may enqueue work and **do not measure scene GPU execution**. Do not sum with GPU timings.
* CPU time recording compositor commands, plus CPU time inside OpenXR copy call (contains record; not additive).
* GPU compositor raster + seam-analysis timestamps, retrieved only after the existing command slot's fence retires (no new readback or synchronization). These do **not** cover Unreal scene GPU, DLSS/NR, headset runtime, or the driver.
* Mean, last and maximum elapsed sample times; no p95/p99 and no per-frame trace. Reset the samples between scenes.

Press **Export TriView profiling summary to UEVR log** and send the [TriViewPerfB41] line. The profile is an aggregate snapshot, not continuous disk logging.

## Suggested test

First compare same scene with diagnostics OFF and ON to check observer overhead. For each preset hold still for 20–30 seconds, reset the counters, and export the log:
1. Baseline, 0.5 x 0.5 crop, density 1, context 0.3, B40.
2. Density 0.7 and 0.5 with everything else unchanged.
3. B40 temporal seam mode versus Seam Off (if safe for the seam test).
4. Depth-reprojection enabled/disabled (if available) and fused sharpening 0/on.
For total scene GPU breakdown, use an external engine GPU capture (PIX/Nsight/UE profiler if exposed); B41 intentionally does not pretend CPU render callbacks are GPU timings. A selective D3D12 engine-pass timestamp hook needs a separate, safety-reviewed implementation.

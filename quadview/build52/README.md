# Build 52 v2 — automatic, failure-tolerant QuadViews diagnostics

**Source base:** original Build 51 `f4e086c`. Separate overlay branch only.
**Target:** STALKER 2.10 with the existing Quad Views Stereo ID7 mode.

## Zero visual-feedback test
1. Inject the compiled Build 52 v2 package into STALKER 2.10, select Quad Views Stereo (ID7), and leave the game rendering for approximately 15 seconds. No need to inspect or describe the headset output. Leave all graphics settings alone.
2. Exit the game. Press Win+R, enter `%TEMP%`, and attach whichever of the following files exists:
   - `UEVR_Build52_Diagnostics_<PID>.zip` (full GPU source evidence, **including an early-stage trace snapshot**);
   - `UEVR_Build52_Trace_<PID>.csv` (**independent fallback** when no GPU image was captured).
   If readily available, also attach the existing UEVR.log. No further headset tests or descriptions are needed.

## What the build actually records
- An early-stage trace CSV is written as soon as QuadViews view demand fires, **before** four valid views or compositor admission are required. Existing hook checkpoints include constructor/view state, role bind, native dispatch, RHI command tail, completion, source selection, compositor, presentation and XR submission. Every available row records generation, serial, frame, canonical frame, role, result and render/hook/execute/write masks.
- After 120 successful compositors, GPU capture reads seven 8-pixel-wide-in-Y horizontal strips across the **entire texture width** for each of the four source textures. Pixel maps include nonblack counts every 64 X pixels, expected source-rect coverage and zero-origin coverage. Render artifacts use the original viewport and shader unchanged.
- The GPU ZIP includes `README.txt` (source generation, serial, engine frame, expected four rectangles and D3D12 formats), `coverage_summary.csv`, `coverage_tiles_64px.csv`, `role_0.ppm` through `role_3.ppm`, and `hook_trace.csv` if present.
- The readback uses `GetCopyableFootprints`, restores every source's D3D12 state immediately, then reads the GPU bytes only after the original command-context fence retires. The trace survives early failure or game crash because each bounded event is closed/flushed immediately.

## Interpretation and limitations
- A ZIP with data at x=0 but zero pixels inside expected X offsets strongly supports the horizontal-source-placement hypothesis.
- Empty right-eye sources **plus** role execution/rejection evidence differentiate an absent render from bad sampling; a fully black source on its own proves neither.
- **No GPU ZIP is normal when the pipeline fails before composition**. Send the CSV instead. If neither exists, the failure occurred before instrumented view demand or file creation was blocked, and the ordinary UEVR.log becomes essential.
- Trace is bounded to 1600 gated events per process, with try-lock and close-per-event persistence. GPU readback is one-shot, limited to 7*8 rows per role, and can cause one temporary hitch.
- We cannot promise that one session will identify every future rendering failure. Do not mistake a passing build pipeline for successful capture; Windows CI and headset evidence are separate.

## Removal
Delete `quadview/build52/` and the isolated Build52 workflow or simply switch back to Build51. No existing Build51 source files are modified in this branch.

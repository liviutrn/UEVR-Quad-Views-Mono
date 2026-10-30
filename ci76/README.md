# CI76 — capture-guided composition and resize recovery

Based on CI75 build102 (`7a6ec9f24ae285fd79c23be0c41bcfb0c1e4cf92`).
Liviu reported persistent jitter, doubled peripheral hands and flicker/black
output while increasing peripheral resolution. Capture3 retained all83 frames.
It used CI71 LEFT mesh, not CI73 conservative mode.

## Changes

- All surface strategies (modes4/5) select one current image at each pixel.
  Partial geometry coverage no longer blends displaced native and synthetic
  silhouettes. The crop seam also selects one image. Mode6 remains a coverage
  diagnostic; legacy modes1–3 and ordinary mode0 remain comparisons.
- CI73's coarse RIGHT-depth-edge veto no longer forces sharpness changes at
  the final composite. Surface visibility tests still run. Conservative mode
  remains a reconstruction strategy, with the same common composition policy.
- Existing 80cm near-field protection now applies to every surface strategy's
  synthesized regions. This deliberately reduces local stereo where source
  foreground geometry cannot be trusted. It does not correct a viewmodel camera.
- Peripheral resizing waits250ms after editing, avoiding allocations at every
  slider step. Pins follow only the explicitly selected feature handle to its
  new expected output size. New/released features still require a manual pin;
  old-sized depth is never stretched or accepted for the new layout.
- After interruption/resize/source change, stereo needs eight consecutive fresh
  pairs. Repeated eye serials/evaluations, gaps and incomplete pairs cannot
  advance recovery. There is no stored-depth or RGB history.
- During stereo recovery, both eyes show current native RIGHT full-field color.
  This avoids composing a nominal mono fallback from two displaced cameras.
  Temporary low-resolution mono is intentional and reported, not a stereo fix.
- MPC_FOV writes are verified with getter readback. Values and verification are
  recorded. The established override values are unchanged.
- Recorder retains fallback output frames even when depth is missing, with
  explicit omissions. Mono controls now also request diagnostic depth. Archive
  splitting and numerical precision are unchanged.

## Evidence and limits

`baseline102/` contains the five actual production shader source files from
public source artifact12983947357 of build102. The WARP test executes the actual
PSNativeStereo before/after against displaced high-contrast source colors,
partial/full coverage, near/far depths and crop edges. It requires mixed-owner
pixels in CI75, zero in CI76, continued opaque synthetic use, and near protection.
This is a targeted ghosting-mechanism test, not a ground-truth stereo benchmark.

Portable tests cover recovery and actual registry migration, including one NGX
feature used with two distinguishable output sizes. Full Windows compilation
and the existing production tests remain required.

Capture motion measurements support the existing positive depth-jitter sampling
convention; native DLSS jitter, physical baseline/world scale, color sharpening
and projection/crop transforms are unchanged. Local edge shimmer, true target-only
disocclusions, eye/frame provenance and SteamVR-generated artifacts remain open.
There is no validated motion history in this build. A threshold alone cannot
promise temporal stability; no claim of eliminating all jitter or black screens.

## Headset check after a green build

Keep normal mode5 and existing selected depth features. Record the same truck
or another static edge once. Then release the peripheral resolution slider at
its desired value; allow recovery to finish. If the game replaces DLSS features,
select the newly live LEFT/RIGHT entries matching the expected sizes shown.
Record persistent artifacts once. Upload every ZIP part and its index; fallback
frames and foreground readback are now included in the evidence.

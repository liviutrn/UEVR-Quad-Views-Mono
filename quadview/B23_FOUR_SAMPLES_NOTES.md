# TriView B23: 4 depth lookups — deliberately simple experimental build

## Lineage
B22 CI-successful baseline: commit 11ae53daf224bd04137177ec900e96e619845488.
B21-51 remains user-headset-confirmed rollback. B22-54 remains CI-confirmed comparison.

## Changes
- Only TWO expressions in `quadview/QuadViewComposite.hlsl`:
  - `const float ds = sMax / 24.0;` → `const float ds = sMax / 3.0;`
  - `i <= 24u && !found` → `i <= 3u && !found`
- At most 4 depth lookups per peripheral output pixel, formerly up to 25 (0..24).
- All other shader logic is unchanged, including depth-jump detection; its thresholds scale naturally with `ds`.
- No new render target, new GPU queue, depth hierarchy, fence, synchronization, UI, UE render pass, allocation or state transition.
- B22 source-size hoisting and opt-in verbose HookTrace remain.
- Same three physical TriView renders, foveas, periphery quality, stereo/FOV/crop correction and DLSS depth capture.

## Risk and verification
- Earlier B11 used 4 fixed-point *iterations*, a DIFFERENT algorithm. A B11 headset frame exhibited doubled hands; B12 changed the algorithm to a 25-sample near-to-far march plus disocclusion handling. This does **not** establish that exactly 25 samples are necessary.
- Four coarse march positions may miss near-hand silhouettes, weapon edges or thin low-resolution occluders and can change hole filling. Examine user headset visuals.
- CI first verifies the exact two-literal shader diff, compiles FXC, runs real WARP stereo-depth ground truth, existing rendering and layout regression tests, portable sanitizers, and the production build. Any failed WARP ground truth means this should not be declared ready for headset testing.
- The compositor 2 ms figure is a **whole GPU compositing draw**, not a measured 2 ms exclusively spent on depth. No FPS or VRAM improvement is established until benchmarked.
- At peripheral output scale 0.2 each axis and DLSS Performance input nominally 0.5 each axis, depth may be about 0.1x full-eye width and height, not necessarily identical across all configurations.

## Headset evaluation, only IF CI and GPU WARP pass
One scene and same resolution/cheeky/sharpen settings: compare B22/B23 GPU compositor ms and FPS; hands and gun at several distances; both eyes; seam and large disocclusions; head movement; return to B21-51 immediately if artifacts/crashes occur.

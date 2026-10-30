# CI75: lossless stereo reconstruction diagnostic recorder

Includes the verified CI74 RIGHT-depth jitter/mask alignment repair. The
recorder itself does not change the reconstruction algorithm or strategy.

## Record and upload

1. Use the CI75 experimental build and your usual working Mode 5 / selected
   LEFT and RIGHT DLSS depth pins. The existing experimental opt-in is retained.
2. In **DuoView > Stereo and quality > Advanced stereo and capture diagnostics**,
   press **RECORD lossless stereo + depth (2s / 96 frames)**.
3. Close the menu during the three-second countdown. Fix gaze on an unstable
   weapon/NPC/pole edge. Keep head and gaze as steady as practical. For a
   second recording, deliberately move sideways slowly across the same edge.
4. Wait for **READY** or the explicit **INCOMPLETE/FAILED** explanation.
   Encoding happens after recording, on a background thread.
5. Open `%TEMP%\UEVR_DuoViewDiagnostics`. Upload the newest capture's
   **ALL numbered ZIP parts plus its `_index.json`**. Do not mix captures.

Each ZIP part is at most **20 MiB**. A larger sequence is split into parts;
recording and frames are NOT discarded to satisfy that per-upload size.
The index lists all filenames. Each part also contains its own manifest,
capture/build identity, part count and global frame indices. Upload parts in
successive messages if needed; the analysis must report missing parts.

Total size depends on the actual pixels/depth, PNG compressibility and FPS.
Expect tens of MiB rather than an uncompressed full-resolution multi-GB dump;
the actual ZIP totals must be measured in game. Native 192-pixel ROIs keep the
default scope focused on the edge you look at without resizing its pixels.

## What is retained

The target is up to two seconds OR 96 consecutive genuine game-rendered packets,
whichever comes first (normally about 60/80 at 30/40 FPS). At a higher genuine
render rate, the 96-frame sequence is shorter; its actual duration and
`frame_limit` termination are explicit, with at least 500 ms required. Duplicate packet serials are
not recaptured. SteamVR-generated frames and headset-lens output are excluded.

Per frame, when produced by the active path:

| Data | Stored region | Purpose |
|---|---|---|
| Final XR LEFT and RIGHT | 192x192 native pixels near gaze-crop centre | Observe edge motion and binocular output |
| Real LEFT fovea / RIGHT periphery color | 192 / 128 native pixels | Separate source-image changes from reconstruction changes |
| Selected LEFT / RIGHT raw device depth | 192 / 128 input texels, padded relative to output ROI | Reconstruct rays and inspect depth/edge phase changes |
| Synthetic RIGHT fovea / LEFT periphery | 192 / 128 native samples, including alpha | See generated coverage and invalid/synthetic transitions |
| Selected-evaluation motion vectors | 96x96 raw samples, optional | Diagnose temporal input where layout is known |
| Full active depth keyframes | Every 16th frame, optional bounded context | Check crop/rect conventions beyond the central ROI |

All planes preserve their underlying GPU bytes in a **lossless PNG byte
container**. This preserves 32-bit depth, half floats, packed depth formats,
10-bit color and alpha without normalizing values or using JPEG. These PNGs
are numerical containers; opening them as ordinary pictures can show strange
colors. The included decoder generates correct viewable images and depth maps.

Each plane records DXGI resource and footprint formats, dimensions, row byte
count, allocation size, actual crop box and resource identity. Each frame logs
packet/producer frame and generation, depth serials/epochs, source selection,
physical camera positions/rotations, frozen projections, gaze crop, active
depth rectangles/ranges, strategy, quality settings, stereo sign, actual stereo
recording/submission status, NGX feature generations/evaluation IDs, jitter,
motion scales/flags, resets, CPU monotonic time and QPC frequency/time.

Missing motion/coverage/keyframe planes carry explicit omission reasons.
Selected motion is copied only from the same selected depth slot/evaluation;
unknown MV layouts are not guessed. A dedicated short-lived capture flag keeps
the old all-candidate gallery separate. Large optional full-depth keyframes are
omitted before they can consume memory reserved for the complete core sequence.

## Usefulness and limits

This supports local edge-jitter diagnosis, depth-to-color/crop/jitter checks,
source versus synthesized temporal comparisons, coverage inspection and
reproducible engineering handoff. ROI boxes and full projection metadata are
essential: LEFT cropped-FOV depth and RIGHT full-FOV depth are not the same grid.

The record does **not** authenticate the engine eye/frame association merely
by logging it, does not contain native full-stereo ground truth, and does not
capture every pixel needed for arbitrary full-frame replay. Out-of-ROI
correspondences must be reported unavailable, not silently filled. Synthetic
alpha is geometry coverage, not a complete final pixel-owner mask. These
limitations are carried into the manifest and analyzer output.

The analyzer reports measured image/depth changes, stationary eligibility,
missing parts/frames and timing/identity problems. It generates decoded PNG
sidecars, heatmaps and a native-resolution stereo GIF preview. GIF timing is
quantized/coalesced by that preview format; the original timestamped lossless
PNG planes remain the evidence. No fabricated overall quality score is emitted.

Optional analysis (the engineering agent can do this after upload):

```text
python ANALYZE_CI75_CAPTURE.py capture_part01of02.zip capture_part02of02.zip --out analysis
```

Requires Python, numpy and Pillow. Preserve `report.json` with the capture parts.

## Integrity and resource safety

- The current Windows test executes real D3D12 WARP copies/fences through this
  production recorder, lossless WIC PNG encoding and multi-part writing.
  An independent Python ZIP/PNG decoder compares every recovered byte to
  the uploaded GPU fixture, including NaN, Inf, signed-zero, subnormal and
  nonzero RGB beneath zero alpha. All 24 fixture frames must survive splitting.
- The portable ZIP test checks CRC, EOCD/central-directory writing, size
  accounting and traversal rejection. Analyzer tests cover missing/corrupt
  parts, raw formats, motion/pose/crop changes and static-versus-jitter controls.
- Readbacks are allocated before XR command recording. The callback validates
  all required planes before recording any copy and restores declared states.
  No GPU resource allocation, CPU encoding, mapping or fence waiting occurs in
  that callback. Sources/readbacks remain owned until queue retirement.
- Readbacks are capped at 256 MiB; the default core has a bounded per-frame
  reserve. Encoding starts only after the requested sequence ends. An ambiguous
  submission disables further recording and retains its resources rather than
  risking a GPU use-after-free. Device removal is reported.
- READY requires at least 16 usable frames, at least 75% of the requested
  time span for time-window termination (or 500 ms for a completed frame-limit
  sequence), completion of the planned window/frame count, and no rejection,
  drop or memory-limit event. Data from incomplete sessions is still saved
  when possible, with explicit flags. Capture adds temporary overhead and
  should not be used to claim normal-game GPU performance.

The full Windows backend build remains necessary to validate the in-game UI,
NGX selected-motion plumbing and integration. Neither a fixture nor compilation
constitutes a headset-verified quality improvement.

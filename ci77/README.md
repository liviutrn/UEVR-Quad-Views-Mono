# CI81 — persistent whole-map depth

Based on CI80 build123. This experimental build prioritizes less depth flicker over short trails/motion lag, as requested.

## Starting controls

Keep stabilization, temporal stabilization, **Strong whole-map persistence**, and thin geometry ON. Start overall history95%, edge hold8 submitted frames, switching support20%. Keep Mono foreground guard OFF for the stereo comparison; it deliberately makes near hands mono.

- Overall history0..99% smooths metric depth on matching surfaces, including near depth. Strong mode OFF compares CI80 filtering.
- Edge hold0..30 frames retains a foreground hypothesis through temporarily absent depth samples. At40FPS hold8 is approximately200ms. Hold0 removes that allowance. Foreground and background device-depth endpoints stay separate.
- Switching support5..90% controls acquisition/release confidence. Lower support accepts weaker foreground evidence; trails can increase. The hold limit still releases unsupported geometry.
- New closer occluders replace old farther depth immediately. Camera reprojection, source/dimension changes, NGX resets, and age checks remain active.
- Processed depth previews sample the exact selected R32 maps used by reconstruction. **Retained-history mask** shows actual state: orange/yellow = retained missing foreground; green = current observed/confident state; magenta = processed state unavailable.
- With the hand guard OFF, stabilized right-fovea rendering no longer forcibly replaces near geometry with native RIGHT solely because it is close. Real disocclusions can still fall back to native imagery.

## Validation and limits

GPU tests carry actual MRT state and selected depth across frames. They measure noisy-surface depth RMS, hold/release of a one-pixel feature through background/sky dropouts, immediate closer-occluder replacement, reprojection bounds, resets, and control effects. Host fixtures validate per-eye resources, cross-slot history, and resizing with the D3D12 debug layer when available.

State history adds RGBA32 GPU buffers per eye and slot. Headset performance and perceived flicker/trails must still be measured. Retained depth cannot recover previously invisible color; stable guides do not alone guarantee a stable reconstructed image. No claim of native-stereo equivalence or zero remaining headset flicker is made from CI tests.

Existing raw/processed depth recording and Joey classic method4 comparison remain available. See JOEY_CLASSIC_PROVENANCE.md for that separate path.

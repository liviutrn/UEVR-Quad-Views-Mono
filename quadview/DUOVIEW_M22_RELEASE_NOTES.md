# DuoView Mono synthetic stereo M2.2 — 13 November 2026

**Base:** M2.1 build #201, commit `c66d444c9810ecbf6fd17e932958240f1d434a50`.
**Implementation branch:** `experiment/duoview-m22-fable-20261113` (created from the staged M2.2 changes).
**Scope:** DuoView mode ID6, synthetic stereo opt-in. TriView ID7 B43 carries forward independently.
**Runtime status:** CI build must pass; PSVR2/SteamVR headset behaviour remains unverified.

## Changes relative to M2.1 #201

1. **N1: smoother inverse warp without an extra depth texture read.** Retains eight bisection samples per eye/output pixel. Caches the sampled residuals at both bracketing endpoints and linearly interpolates the unique root, falling back to the last two probes when one bracket endpoint was never sampled. The answer is clamped back into the final bracket. This reduces bisection's staircase on smooth surfaces while preserving the monotone bounded solution. The interpolation is approximate if the final bracket straddles a depth-grid slope change; it does not guarantee zero residual or eliminate missing-image disocclusions.

2. **N3: visible diagnostic at high eye resolution.** The existing unwarped M2.1 depth-edge overlay now normalizes the change in inverse depth per display pixel by the theoretical maximum conditioned-grid slope per display pixel, instead of the fixed inverse-depth divisor of 0.05. It adds strong red over depth transitions. It visualizes the slope-conditioned field, **not** the actual sharp silhouette or an exact original colour/depth correspondence. Keep this diagnostic OFF for normal gameplay.

3. **N2: wider fine-depth near-object coverage.** The foveal contribution to the *one* globally conditioned inverse-depth field now takes the near-max of a 5x5 source-texel footprint instead of 3x3. This should reduce missed thin foreground depth features when the fine texture is much denser than the shared grid. It costs 25 vs 9 fine-depth samples **inside the crop only** while fine depth is enabled; GPU timing/headset visual benefit unknown. It does not add a second grid, scene render or descriptor.

4. **Regression coverage.** The existing numerical M2.1 oracle now checks the actual cached-bracket finish, plus 4K/eye, both signed disparities, caps 2 and 12.5, sharpness 0.5/0.8/0.9, changed crops, one-pixel accuracy and adjacent-pixel staircase reduction. A generated-source test ensures the 5x5 footprint, bounded finish, no new per-pixel depth reads and normalized overlay survived patch replay. The existing D3D12 WARP fixture continues to exercise actual fine-vs-coarse outputs and independent sharpening.

## Deliberately not changed

- The strict M2.1 coarse/fine pairing: adjacent NGX evaluation sequence, same producer list + epoch and 500 ms fallback. The `[DuoView][M2.1]` log remains the key evidence. If a Cheeky NR evaluation interleaves the captures, fine may never activate (reject reason 3).
- Matching a specific NGX depth capture to the exact presented colour frame (F4) is **still open**; no arbitrary frame-id assumption is made.
- No temporal depth averaging, hold-last-grid, disocclusion/inpainting passes or synthesized geometry layers, because they require headset evidence and/or carry timing risks.
- The existing 12-slot depth pool and texture reuse, TriView shared producer, M1 opt-in controls and B40 seam architecture are preserved.
- No automatic jitter change: the M2.1 NGX jitter alignment A/B switch stays OFF by default.

## Safe test sequence

Keep a copy of the last known-good #201 / M1 and your best TriView binary. In ID6 compare synthetic stereo OFF, then ON with fine OFF. Observe weapon/ground and edges while head moving. At fixed camera compare near limit 1.0 m vs 0.6 m and sharpness 0.5 vs 0.8; toggle the M2.1 jitter correction separately. Turn on the new depth-edge overlay to see conditioned contours; turn it OFF before evaluating actual image quality. Only then opt into fine fovea depth. Compare fine OFF/ON in the identical scene and note GPU milliseconds and whether the `[DuoView][M2.1]` line reports `fine=1`, `pair` increasing, rejection codes, pool reallocations and full slots. In ID7 confirm TriView rendering, seam, NR and runtime resets are unchanged.

## Fable review priorities

- N1 exactness across depth-grid cell boundaries, 4K/cap-off subpixel continuity and D3D FXC compiler results; look closely at the no-extra-lookup claim.
- Whether the 5x5 fine footprint is an acceptable quality/cost trade-off, or should be an A/B option / reverted.
- Whether the depth-edge overlay is actually visible and overlays the correct unwarped coordinates.
- Residual F4/N4: prove which capture belongs to the colour packet; do not loosen sequence conditions blindly.
- Verify mode ID7 shared producer and capture pool semantics have not changed, and mode ID6 stereo-OFF remains the original Mono route.

**Evidence standard:** successful GitHub CI means Windows compilation and automated tests passed, not that VR rendering, frame pacing or headset stability have been validated.

## CI and artifact provenance

Workflow: `.github/workflows/triview-b1.yml`, build name `TriView B43 + DuoView Mono M2.2`. The distributable artifact is named `UEVR-DuoView-M22-<run number>`. This release-note commit is the final staged change triggering the M2.2 Windows/Ubuntu build, and makes no additional shader modifications.

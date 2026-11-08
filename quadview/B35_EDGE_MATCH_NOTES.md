> Historical B35 notes. For B37, use B37_ROOT_CAUSE_NOTES.md: original standard feather replaces the extra inward control, and native final color rectangles start at their captured origin.

# B35 Edge Match V2 — test candidate

Base: B31-110, `008c9f7548c43f5977c1197c4180cddb435c64de`.

B31 anti-vignette `CorrectFocusColor` remains byte-identical. Native view rendering, depth reprojection, target ownership, engine registration and existing retirement fences remain inherited from B31. Existing B31 modes/settings are retained; select **Edge matcher: B31** to use them.

## New behavior

- Instant/Temporal modes compare corresponding RGB samples on the first displayed focus border, including fractional crop positions. They use the same context homography/depth reprojection, final focus source, Glamarye sharpening and B31 anti-vignette. NR/SR appearance already present in the fovea source is therefore included in the reference. There is no special NR API or periphery NR pass.
- Three tangential samples estimate local appearance; at corners both sides share one unshifted reference. This deliberately corrects low-frequency color, while the real stereo focus stays unchanged except for the user-selected inward feather. No extension of rendered focus coverage is claimed.
- Signed additive RGB residuals can handle dark/zero context channels and valid large color differences without the B31 gain ceiling. Output is limited by the existing render target gamut, so clipped source details cannot be recovered.
- 32 perimeter knots per eye describe the broad correction. A current-frame, locally sampled residual provides the immediate edge correction; a slow broad field fades outward. A one-output-pixel plateau keeps the first exterior pixel centers fully corrected even at fractional crops.
- Temporal stores actual previous correction and a two-threshold tracking state on the GPU. The response setting limits RGB change per second, not total correction. The immediate residual cancels broad-field lag at the edge. Temporal smoothing cannot fix bad geometric correspondence or make noisy edge estimates intrinsically correct.
- History resets on scene-generation/settings/geometry changes, a crop shift greater than half an output pixel, invalid correspondence, or a gap/backward timestamp over 250 ms. Gaze movement deliberately resets rather than reusing history at unrelated screen positions.

## GPU ownership and submission

The existing OpenXR copy mutex serializes recording through command submission. However, its CommandContext previously reread a mutable hook queue at submission. Temporal lists now carry a one-shot COM queue lease taken from their history object; ExecuteCommandLists and its existing fence Signal use that exact queue. The default queue path for all other lists is unchanged.

A tiny shared committed UAV (3,072 bytes logical data; D3D12 allocation granularity may use 64 KiB) belongs to the session/device/queue. Every command-slot compositor retains it through the existing fence retirement. Queue/device changes create a new history while old slots retain theirs. A UAV barrier before and after each dispatch orders in-place updates in GPU execution order; the pixel pass reads a slot-local copy, not the shared UAV. There is no CPU statistics readback, added CPU fence wait/poll, CPU ping-pong index, per-frame history allocation, or new fence. Pipeline/root signature and statistics buffers are prewarmed as before; constants now occupy the existing 512-byte allocation.

## Defaults and controls

New controls have separate persisted names. Default: Temporal, strength 1, broad reach 240 output pixels, immediate reach 32, inward feather 2, response .15 RGB units/sec, hysteresis .004. Lower response is steadier/slower. Fast reach is bounded by broad reach in shader math. Choose Instant to remove history, or B31 for the old behavior. Existing gain cap/color-strength controls affect B31 only. The diagnostic shows current edge validity, not guaranteed geometric correspondence.

## Verification

Portable generated-source anchor/ownership checks and baseline regressions are run before submission. The Windows pipeline must compile production VS/PS/CS with fxc /WX and run production D3D12 WARP tests before packaging a DLL. New GPU tests include independent eyes, signed/near-black/large RGB differences, displayed side/corner mismatches, fractional/asymmetric crops, sharpened/calibrated references, focus preservation, spatial border projection, temporal rate/hysteresis, alternating slots, epoch/crop/settings resets and invalid depth.

The uploaded screenshots are final composites before anti-vignette. They do not include both complete source textures or depth/camera data and cannot validate an exact post-NR simulation. No edited/generated picture is evidence of the algorithm. WARP RGB/lighting variations exercise source appearance changes; they are not a full simulation of NVIDIA's NR network.

Known limits: additive appearance correction can create a color halo away from the edge when source differences are spatially complex; depth/parallax/disocclusion differences remain; a narrow immediate field may vary with scene measurements; broad interpolation has finite spatial resolution. No invisible-seam, no-flicker, headset stability or RTX performance claim is made before testing. The near band does extra sharpen/depth samples; measure its cost using the compositor timing, not only the analysis timer.

## Headset test after Windows gates pass

1. Back up B31, install this candidate; leave anti-vignette at its known-good configuration. Start with default Edge V2 Temporal.
2. In one static sky/wall/indoor scene, compare B31 / Instant / Temporal at unchanged settings, first with fovea-only NR off, then on before SR.
3. Check all four sides and corners, warm/cool and bright/dark scenes. Look for outer color halos and foveal sharpness loss.
4. Move gaze/head, switch lighting, load a save, then use normal play. Stop on black views/delivery loss; retain log. A short test is not proof of long-session stability.
5. Compare total compositor GPU milliseconds, frame delivery and VRAM against B31. Tune reach/response only after observing default behavior; avoid risky resize/restart stress just to validate appearance.

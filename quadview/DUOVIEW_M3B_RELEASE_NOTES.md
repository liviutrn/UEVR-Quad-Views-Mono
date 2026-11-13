# DuoView M3b experimental build — 14 November 2026

Starting point: M3a branch at 4d42322 (includes the C2 WARP fixture correction).
All new switches are OFF by default; previous M3a controls and keys are unchanged.

## Experimental controls
- M3b Auto jitter: fourth `DuoM3JitterMode` choice. Scores coarse NGX depth and current colour on the GPU; 120-frame windows, 3% confidence, >0.05-pixel jitter, two agreeing windows.
- M3b temporal depth, strength 0–0.9 (default 0.6): seed/stabilize compute passes with 3×3 current-frame clamp and per-slot ping-pong history. **Identity reprojection fallback** (depth-frame centre rotation not proven). Resets on grid/crop change.
- M3b edge repair and mask: Joey-style confidence-gated, 3-sample stable background search, ≤8 source-grid texels, per eye. Mask: red repaired, yellow low confidence.
- M3b colour guided seed: at >2% depth discontinuities choose a colour-matched source depth texel, not an average.
- M3b fine gate tuning: optional toggle; agree tolerance .03 (0–.20), ratio low .60 (0–.99), ratio high .85 (0–1), contrast .10 (0–1).
- Depth debug and distance-fade sharpening now read each displayed eye's conditioned slice.

## Exclusions and limitations
- P6 VectorXR depth submission is **not implemented**. No extra OpenXR depth swapchain or layer-chain modification.
- Temporal history currently belongs to the retired compositor command slot, and identity reprojection will reject many samples while the head or gaze moves. It is **not** motion-compensated.
- M3b GPU features are experimental, not headset-tested. First check that Windows shader, source-contract and WARP tests pass. Do not assume green CI proves perceptual quality.
- Runtime GPU timing, temporal clamp percentage and pixel-repair percentage are not yet instrumented. The Auto-jitter window logs scores, vote and active sign. Existing M2.5a gate counters remain available.

## Safety
Switch off each new option to return to the M3a path. Test separately, then combine. Do not overwrite the last user-tested package.

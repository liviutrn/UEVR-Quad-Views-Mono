# TriView B27 — combined B22 + B23 + B24 + B26 (2026-11-06)

## Provenance
- Based on successful B26-100 Windows build commit `82af0277f684bbbf29404aa16c4e5106ebfa40d0` (XR session restart barrier).
- B26 already contains B22 shader source-size reuse / trace gating, and B23's exact four-depth-sample shader.
- The only additional rendering change is the EXACT B24-56 HLSL shader from its completed branch: lazy context projection for opaque foveal pixels, and shared sharpening tap-scale computation.
- Added B24's original compositor regression test (including 8,000 tap-math comparisons and preservation of B23 warp) INSTEAD of B23's mutually exclusive exact-two-literal equality test.
- All B25/B26 OpenXR guards, depth snapshot resets, Native Stereo Fix fresh-packet barrier, original UI, resource recycling and all other original Windows/GPU WARP/sanitizer tests are retained.

## Risks
- B22-54 confirmed working in game; this combined B27 is NOT yet tested in headset.
- B23's reduced four depth samples can miss hand, weapon, occlusion or disocclusion detail; image quality must be inspected against B22.
- B24 is algebraically equivalent except possible tiny float-rounding differences, and its FPS gain is unmeasured.
- B26's XR restart checks are source-verified, NOT proof the Windows kernel 0x139 / Arg1=3 BSOD is fixed; crop-change crash root cause still unknown.
- Integration adds no GPU render targets, no new per-frame allocation, and no new GPU waits.

## Test
1. Retain B22-54 as rollback; start B27 at safe known crop/periphery with Dynamic FG off.
2. Check stereo foveas, periphery reprojection, hands/weapons, seams, magenta depth flicker, sharpening and UI.
3. Compare GPU compositor time/FPS with B22 at identical settings/scene.
4. After normal play succeeds, try ONE manual OpenXR runtime reinitialize; verify fresh stereo/depth.
5. Only then try savegame reload and Dynamic FG. Avoid intentionally reproducing BSOD with aggressive rapid size changes.

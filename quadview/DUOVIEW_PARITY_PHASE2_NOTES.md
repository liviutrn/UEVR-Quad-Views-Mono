# DuoView Mono v208d in TriView B43 — Phase 2
Date: 2026-11-12. CI validation and headset validation tracked separately.

## Identity and isolation
- Branch experiment/triview-duoview-parity-phase2-20261112, forked from verified Phase1 67913082328c128d1d65bf6c76b0ad60cdbcb332 (CI run #158 passed).
- Original DuoView v208d subtree remains SHA 3d5593a82ac13532989420b2e356b17602b1098b; workflow validates its commit tree before modifying any checkout files.
- TriView B43 settings, shaders, compiler pipeline, ID7 switching, startup timing, and default settings are untouched. Changes only to generated ID6 source, workspace DuoView HLSL, Phase2 scripts, docs, and workflow.
- A separate guarded patch after all v208d and B43 scripts, before final DXBC compilation. No new GPU texture, history buffer, GPU compute stage, or frame-time shader compilation. The exact same fused ID6 raster pass samples both sources.
- SameImageBothEyes default ON; SharpPeriphery default OFF; native mono alignment default -1.5%; selected mode default still ID7. Existing installed configuration values preserved.

## Phase 2 behavior
1. Sharpen: DuoView Glamarye strength slider 0–20 (previously 0–5), max change 0.05–0.80 (previously up to .30); opt-in extra-wide 2x radius + 7px FXAA guard ring, in the ID6 fovea only. The original sharpen strength/default is preserved; extra-wide OFF by default.
2. Anti-vignette: opt-in brightness-only radial focus lift from B31 logic: uniform brightness, corner gain, normalized onset, radial power; center remains neutral when brightness = 1.00 and radial threshold not exceeded. Default OFF.
3. Mono seam: opt-in local automatic colour/brightness matching in 4 spatial probe groups. Rejects black and strongly mismatching edge samples, clamps gain, fades the correction only across configurable OUTWARD region; configurable INWARD feather preserves genuine fovea pixels (no fake stretched fovea). No history resets, no temporal accumulation or allocations. Default OFF.
4. Consistent ID6 compatible Native and fallback gathered raster outputs: identical knobs and helper shader, same root constant layout; no effects in TriView.
5. Conservative Direct XR guard: disables the two-half direct raster when sharpen or focus/seam corrections enabled, so mode6 composes once then copies twice; avoids doing neural-independent appearance work twice.

## Deliberate difference from TriView B35–B40
The Mono seam is NOT a byte-for-byte port of TriView's B40 temporal depth-aware seam matching. Mono has one view and no depth-warped periphery stereo. The Mono implementation uses one GPU raster and four spatial groups instead of persistent GPU sample buffers and temporal state, to preserve v208d stability and low memory. It has no temporal smoothness guarantee; visual flicker in headset and additional GPU time remain UNVERIFIED. If local seam matching shimmers or adds >1ms, disable SeamMatch and retain anti-vignette plus native feather.

## Validation gates
- Phase2 guarded source anchor application and code-contract checks; HLSL DXBC compiled by fxc.exe in CI for both native+fallback raster, no live compiler.
- Original pinned DuoView C++/WARP test suite, existing TriView CPU/GPU WARP tests, native Joey backend and UEVR compatibility suite.
- Config/constant layout changes must compile in native DX12 backend; root constant count 48 DWORDs (under 64 DWORD budget).
- GPU time and stability are not validated by CI. Never claim successful headset behavior without user's tests.
- ≤3 headset questions: (1) mode6 stability + sharpen/anti-vignette correct? (2) seam visual behaviour/flicker at near crop edge? (3) ID7 looks/performs unchanged?

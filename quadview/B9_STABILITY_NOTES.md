# TriView B9 startup and menu stability

Base: exact tested B8 overlay `275d6134adf2fbb7a6a80443718d876592a8fc75`.
Work branch: `experiment/triview-b9-startup-stability-20261105`.

B8 could enter ID7 before its constructor had discovered the engine view-family layout. Its early projection return also bypassed the existing LocalPlayer history bootstrap. B9 initializes the family layout before any ID7 family getter, preserving the original constructor when discovery is pending. The existing two-eye LocalPlayer setup runs before the ID7 projection branch and is eligible for supported requested/selected ID7. Its skip, lazy-runtime, two-view PostInit allocation and failure guards are retained. Extra histories still require existing independent role, frame, projection and lifetime proofs. No unchecked RHI vtable is installed.

The short primary status now follows successful fresh XR submissions in the current generation. Per-frame waiting detail cannot overwrite Active; held continuity images do not refresh it. Long diagnostic text, source target sizes, unavailable reasons and VRAM readings live inside one fixed-height scrolling panel. This prevents controls below them from moving as the text changes. TriView and QuadView labels follow the actual layout.

B7 depth capture is deliberately unavailable in B9. Its copy pool has no producer-completion fence and cannot match depth to the exact context/fovea producer. The hard gate prevents old saved ON values or the debug switch from entering that capture path. Reprojection defaults OFF. Show depth diagnostic now always produces an explicit whole-eye result: grayscale for validated synthetic test input, or a magenta/black checker when unavailable. In the game, B9 intentionally shows the checker. Turn the diagnostic OFF to return to normal rendering. This is a correctness boundary, not a repaired depth implementation.

True native stereo foveas, compact sources, FOV/head controls, output resolution/crop defaults, and B8 independent eye sharpening are retained. The preserved DuoView source tree remains byte-identical to the pinned baseline. No CPU/GPU speedup or seam repair is claimed.

## Verification

Local checks cover the full portable QuadView contract suite, actual pinned Dear ImGui layout and mouse hit testing, submit-state concurrency, source-checkpoint fixtures, bootstrap source-order contracts, and ASan/UBSan. The headless UI test alternates 60 frames of short/long text and absent/present diagnostics, asserting exact slider bounds and real mouse interaction. Bootstrap source checks establish control flow and preserved guards, not game behavior. Local overlay replay omits Windows fxc compilation; Windows CI must compile real shaders, run production D3D12 WARP including missing/rejected/non-shared/known-depth cases, compile the full DLL and frontend, verify source identity and package binary/PDB hashes. CI success does not establish headset success.

## Minimal headset test after CI succeeds

1. Start a fresh game and inject B9. Select Quad Views Stereo / TriView first, without first enabling Native Stereo Fix. Confirm image/head tracking, then switch Native -> ID7 -> Native -> ID7 once.
2. Keep the ID7 menu open while status changes: controls should remain stationary. Enable Show depth diagnostic: both eyes should show the magenta/black checker. Disable it to restore the game.

If startup fails, return the complete log. New `[QuadViews][Bootstrap]` lines distinguish family layout, LocalPlayer setup and RHI class readiness. No additional headset comparison is needed to diagnose the deliberately blocked depth path.

## Remaining work

- Confirm cold-start behavior in PSVR2. The supplied B8 log only captured the Native Stereo Fix workaround; it cannot prove which initialization omission caused the direct-start failure.
- Implement authenticated role-0 NGX provenance through the actual rendering/RHI path, producer queue fences, verified resource state/format, bounded fence-safe reuse and consumer retirement before enabling depth.
- Validate near/far seam geometry, jitter and independent history/color behavior. Mono context still has finite-depth parallax/disocclusion limits.
- Measure per-role CPU/GPU time and resident resource bytes in a reproducible scene before performance/VRAM optimization.

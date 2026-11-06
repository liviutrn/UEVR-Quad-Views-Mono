# TriView B22 — low-risk shader source-dimension hoisting

**Parent:** B21-51 tested working in PSVR2; exact parent commit 89eff76791010bc1de477bdf82cd4eff9fb42896.

## Changes
- No C++ or UE view-family changes.
- Same B21 three physical source textures, four logical roles, source selection, DX12 barriers, depth pool/leases, OpenXR presentation, foveal sharpening formula and parameters, foveal feather, stereo camera geometry and frame policy.
- In the HLSL compositor only: `AtlasUvKnownSize()` receives dimensions already fetched with `SourceSize()`. Share the one focus dimension query across its center + 6 sharpening neighbors and the one shared-periphery dimension query across 15 disocclusion color taps.
- Leave `WarpContextUv()` 24-step ray-marching and 15-tap repair **unchanged**. Do not claim that this build reduces depth-ray sampling cost.
- Expected pixel coordinates and color math are identical by construction; FXC may have already optimized the redundant resource queries. Actual GPU speedup **not established**.

## Verification
- The Windows job runs `test_triview_b22_shader_hoist.py`, FXC compilation, all existing QuadView shader WARP suites including stereo depth scene and output formats, backend compilation, package identity tests.
- The portable ASan/UBSan test suite remains unchanged.
- B21 rollback untouched. User headset-test should compare same scene, resolution, eyes and native stereo fix with sharpening and depth identical. Read compositor GPU milliseconds only with stable GPU timing enabled; avoid readback/snapshot while measuring.

## Explicit non-goals
No change to distance/seam calibration, old depth freshness policy, consumer/producer queue waits, resource lifetime, target allocations, gamma handling, periphery source quality, or camera pose.

**Do not report measured FPS, VRAM savings, crash freedom, nor visual identity until verified in headset.**

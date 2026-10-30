# CI74 targeted RIGHT-depth jitter alignment repair

Baseline: CI73 `b5dd303e0dd9f7138238e9646fe4ccd83abbe4cd`.

## Defects found in assembled CI73

1. `CI73ProtectedNear` and `CI73RightDepthEdge` address RIGHT depth at
   unjittered output UV. Surface reconstruction instead addresses RIGHT depth
   at `targetUV + MeshJitter.zw`. Therefore geometry and fallback/owner masks
   consult different samples when jitter is nonzero.
2. `CI73RightDepthEdge` starts its 2x2 footprint at the nearest sample rather
   than `floor(rectOrigin + jitteredUV * rectSize - 0.5)`, which is the
   pixel-center footprint used by the target inverse gather. The discrepancy
   exists even with zero jitter.

`apply.py` corrects those two mismatches and applies the RIGHT jitter offset
to the legacy `DeviceRightDepth` helper. Existing b0 padding becomes two
float jitter values; the buffer remains 240 bytes and root signatures stay
within the D3D12 64-DWORD limit. It adds no texture, pass, history or queue wait.
Native DLSS output color is not shifted. Source/target surface jitter signs,
camera baseline, crop, thresholds, strategy defaults and stable mono behavior
are preserved. Apply only after CI73 and before embedding shaders.

## Verification

- `coordinate_tests.cpp` uses production Guide normalization and SurfaceGeometry
  with asymmetric 6.4-cm separated cameras, 50 crops, 64 independent jitter
  phases, unequal 860x684 / 344x276 input sizes, nonzero rect origins and both
  normal/reversed Z. Negative controls omit jitter, reverse its sign and
  normalize by output dimensions. This verifies an explicitly declared
  raster-displacement convention, not the game's runtime convention.
- `mask_gpu_tests.cpp` compiles actual assembled production mask functions and
  runs them on D3D11 WARP: 54 frames / 663,552 pixel checks across vertical,
  horizontal and diagonal silhouettes, nine jitter phases, padded allocations,
  active rect offsets and normal/reversed Z. The old shader must reproduce
  errors; corrected shader must produce zero mask mismatches.
- The existing Windows backend build and DX12 production fixtures are retained
  in the production workflow. The independent public audit workflow requires
  no restricted SDK and does not produce an installable DLL.

The focused GPU test executes the actual HLSL functions through a diagnostic
entry point. It validates texture reads, sample footprints and b0 layout;
it is not a measurement of RTX 5070 performance or whole-game stereo quality.
The public materializer explicitly omits unavailable SDK-dependent source;
the full production workflow remains authoritative for complete assembly.

## Audit conclusions and unresolved evidence

The LEFT cropped-source / RIGHT full-FOV depth mapping is algebraically
consistent. Each view normalizes jitter by its own active input dimensions.
Source subtraction and target addition form an inverse pair under the stated
screen-displacement convention. NVIDIA's public DLSS API specifies input-pixel
jitter units; raw NGX interception alone does not authenticate actual game
view/frame/matrix/crop identities or prove the runtime sign convention.

This is a concrete consistency repair, not a claim that all headset flicker
is solved. Do not disable DLSS jitter or add another global sign toggle to
hide unknowns. Verify the actual game depth-pass matrix/jitter correspondence
using a captured frame. Legacy LEFT-depth helper jitter remains outside this
Mode-5-focused patch. Other CI73 fallback/temporal limitations remain.

# DuoView 165 — Stereo synthesis prototype V1

**Status:** shader + C++ binding contract + analytic CPU tests only, not connected to live UEVR. This branch was created from the **headset-validated Split-Eye V3 commit 26b1b412**. It does not modify any existing V3 code, OpenXR output, camera handling, source-pass shading, or your running depth-capture branch.

## Engineering decision

Stock JoeyHodge DIBR was a depth-dependent horizontal shift and image-repair solution based on ONE eye's information. In STALKER 2 its disocclusions, weapon/character silhouettes, foliage, and depth-candidate instability were particularly visible. Here we exploit the physically rendered opposite eye's REAL depth and low-resolution color.

**Right-eye fovea (implemented as standalone shader):**

1. From actual right-eye peripheral depth, unproject the target right-eye output pixel to a 3D point with the EXACT corresponding right depth view-projection inverse.
2. Project that world point into the actual left foveal **depth** projection, which may have a cropped FOV.
3. Examine up to four neighboring source-depth texels. Reconstruct each *source depth texel's* position in world space and compare its camera-relative distance to the candidate. Reject incompatible foreground/background depth.
4. Fetch left foveal color using the **color projection of that same validated source depth texel** (point fetch), then combine only the geometrically accepted samples with bilinear spatial weights.
5. If right depth is missing, close to a depth discontinuity, left camera cannot see the point, or visibility fails, return **real low-resolution right-eye color**. Output a reason mask and a separate confidence mask.

Unlike the draft research report, it does NOT validate one depth texel and then bilinearly sample color at an unrelated UV. That error makes silhouettes bleed. Also, lack of synthetic confidence is NOT lack of a valid real-color fallback.

**Left periphery:** the same inverse gather can run with source and target swapped ONLY if a real full-field left-eye depth resource is proven. The cropped left-fovea depth alone does not cover that FOV. Without target left depth, plan a deterministic z-buffered right-to-left forward scatter with source-owner resolution and low-confidence fallback (or an inexpensive full-field left depth pass). Do not paste stock Joey image dilation into this stage.

## GPU resources and C++ constant contract

Source files: StereoBackwardGather.hlsl and StereoBackwardContract.hpp.

SRVs: t0=left high-res foveal color; t1=left matching depth; t2=right full peripheral target depth; t3=right low-res native color.
UAVs: u0=synthetic right foveal color; u1=R32_FLOAT reconstruction confidence; u2=R32_UINT rejection mask.
Constant buffer b0=BackwardConstants (416 bytes, row_major matrices); static bilinear clamp sampler s0 ONLY for native right fallback.
Entry CSBackwardTargetDepth, [numthreads(8,8,1)], compute shader 5.0.

Four matrices must come from the SAME specific UE frame/render-pass generation as the resources:
TargetWorldFromClip: inverse of RIGHT depth jittered view-projection (full peripheral FOV).
SourceDepthClipFromWorld: actual LEFT depth jittered view-projection (fovea-cropped FOV).
SourceDepthWorldFromClip: inverse LEFT depth view-projection.
SourceColorClipFromWorld: actual LEFT color jittered view-projection.

Matrices use row_major storage and HLSL mul(matrix, vector) with D3D NDC z in [0,1]. Never derive these from approximate IPD/FOV values or silently discard TAA jitter. Use source and target camera positions in the same units as those matrices.

Four normalized resource-viewport rectangles are (originU,originV,sizeU,sizeV). They map native camera-projection UV to pixels within a potentially oversized DX12 resource allocation. **They are not foveal FOV crop tangents.**

For a first *EXPERIMENT* (not calibrated), DepthParams={0.000001,0.999999,0.03,0.0005} world units and EdgeParams={0.05,0.001,0,0}. Actual UE world scale and reversed-Z validity must be verified from the dumps, then thresholds tuned empirically. OutputConfig={fullRightWidth, fullRightHeight, 3, 0} requests real native fallback and conservative target depth-edge rejection. OutputRegion limits dispatch to the right foveal rectangle.

The output buffer's untouched pixels must be initialized or composited from real right periphery before the foveal dispatch. This compute shader modifies only OutputRegion. A D3D12 renderer must set up compatible color/depth SRV formats, descriptor heap, compute PSO/root signature, resource transitions and GPU lifetime fences **after** confirming input provenance. This standalone prototype does NOT implement the live hook or prove those capabilities.

## Offline tests

- Windows GitHub Actions compiles the shader using SDK FXC with cs_5_0, and compiles the C++ constant-buffer mirror with MSVC.
- Python standard-library tests verify reversed-Z projection/unprojection; binocular disparity from actual camera positions; resource-viewport rect transformations; and zero foreground-background color bleeding when depth tests reject a neighboring tap.
- These are CPU/math and shader compilation tests, not end-to-end STALKER 2 head-mounted validation.

## Integration go/no-go gates

- Need captured DEPTH/COLOUR of both V3 scene views from same frame, with pass identity and matching per-eye matrices, including crop projection, jitter, resource viewport.
- Need preserve V3 output unchanged unless an explicit experimental synthetic-stereo toggle is ON and all five BindingContract conditions are true.
- Need GPU timestamp cost, headset edge behavior and native stereo ground-truth comparison before claim of improved quality.
- Then implement forward z/owner scatter if left full target depth unavailable. Add temporal smoothing, hole repair, confidence-aware foveal seam only after this geometry works.

No external source code was copied; the architectural choice is from the DuoView Implementation-First Engineering Plan.

# Phase 1 depth probe — source audit and implementation gates

**Status:** audit only, no depth capture implementation or test build yet.
**Baseline:** `UEVR-Quad-Views-Mono-v186.1-MPC-HUD-EyeAlignment-Persist49-56`
**Parent SHA:** `60d0aae86949723d21266e4121a833f0191729c2` (Build49 CI #56)
**Date:** 2026-10-23

## Immutable architectural contract

Do not replace DuoView mode ID6 or add Unreal views. Its two centered scene color sources
(eye-tracked fovea and low-resolution periphery) must remain the original Native Stereo Fix
pair. The old double-wide monoscopic compositor and Build49 HUD/eye-alignment reset
persistence are the OFF-path reference. The first executable depth probe must not
produce stereo imagery, even on success.

## Verified source observations

1. `duoview/joey_stage1/apply_stage234.py` freezes `ViewFrame`, color role,
   `mono_source_frame`, source index and the OpenXR producer pose before composition.
   It adds packet data to `NativeStereoFramePacket` and validates the pair in
   `src/mods/vr/D3D12Component.cpp` immediately before `record_native`.
2. `duoview/DuoViewD3D12.hpp` provisions TWO color SRVs, not matching per-view depth
   SRVs, and copies Mono color identically to both eyes. Depth cannot safely be
   discovered by the compositor while submitting to OpenXR.
3. Pinned Joey `joeyhodge/UEVR` SHA `5ac7edc207866569334175e4ed8a7517971547f6`
   already contains `src/mods/vr/d3d12/DIBRPreview.*`, including
   `D3D12DepthStencilObserver`, `on_depth_stencil_view_created` and
   `on_resource_barriers`. Its observer is selected via
   `D3D12Component::m_dibr_depth_capture`; installing a second observer blindly
   risks overriding an existing D3D12 observer.
4. Original Joey DIBR watches D3D12 NPSR -> DEPTH_WRITE transitions and may copy
   one selected depth slice before UE reuses its resource. It has ONE global
   captured depth object and a global selected-candidate pointer; that is
   insufficient to prove TWO independent color/depth associations in DuoView.
   Do not reuse its single-eye capture lifecycle or any selection based only on
   format/dimensions.
5. Joey's source code can allocate/recreate the owned depth texture in the barrier
   callback (`ensure_captured_depth_locked`). The new implementation must prewarm
   per-source snapshots and descriptors outside this hot path. No render/XR waits,
   no unbounded logging and no readback on the render thread.
6. The original observer can see DSVs for shadows, captures and other passes.
   An apparent exact-resolution depth texture is *not* itself evidence of source
   identity, especially if UE transient RDG resources are reused.

## First integration seam and validation sequence

A. Create a strictly opt-in probe state distinct from the existing diagnostic color
   mode. Feature OFF must install no additional observer and record no depth work.
B. Select an engine/RHI-order-safe interception window inside each *completed*
   Native Fix scene pass; do not rely solely on the XR packet consumer.
   Record source role, original UE pass index, immutable `FrameKey`,
   `mono_source_frame`, pose token, scene family, projection revision, active
   viewport, resource generation and command-list / queue identity.
C. Use the existing D3D12 observer as research/reference only. Attribute each DSV
   / barrier event to an actual active pass and resource generation, or reject
   it. Do not assume thread-local renderer identity crosses RHI submission.
D. Copy each live source depth at a proven stage into its *own* prewarmed resource,
   validate copy states and slice indices, and hold owned resources until the
   producer and compositor GPU fences retire. Reject unknown states, unsupported
   formats, MSAA or incomplete per-pass association.
E. Bind `fovea/color + fovea/depth` and `periphery/color + periphery/depth`
   only after exact frame/pose/projection/color producer association.
   Even if GPU buffers look like plausible depth, unverified provenance
   must yield `depth_status=unavailable` and legacy Mono.
F. Implement opt-in per-frame telemetry, bounded ring, asynchronous fence-based
   snapshot export, numeric depth samples and separate fovea/periphery grayscale
   and combined views. Print `unknown` for unobserved camera/depth metadata.
G. Validate old Mono off-path first, then distinct owned depth, near/mid/sky,
   weapons, gaze motion, fovea role swap, runtime reset, reprojection and fault
   injection. Use the T00–T10 matrix supplied in the handoff.

## Regression boundaries

- Do not change Build49 persistence patch or the Build48 HUD convergence logic.
- Do not remove or reorder the Foreground MPC and Glamarye patches.
- Do not alter original Joey Mono ID5, native stereo ID0 or restricted UESDK.
- Preserve Stage5 packet continuity and fence ownership; never synthesize
  an output from an old depth snapshot when a held Mono frame is submitted.
- Do not reuse or enable original Joey standalone DIBR: user observed a
  STALKER 2 crash and the root cause has not been verified.
- No `CenterDIBR-P2` or other stereo reconstruction before both depth
  sources are proven by frame data plus independent real-game screenshots.

## CI delivery gate

A depth-probe artifact must be generated by the existing pinned Windows build
pipeline, with the new experiment included in its branch filter and with a
distinct artifact name (`DuoView-DepthProbeP1-*`) only when runtime capture
functionality is genuinely present. Bundle the schema, diagnostics, SHA256
manifest, and user test instructions. Do not relabel an unchanged Build49 DLL
as a working depth probe.

**Remaining blocker:** identify and implement a per-pass, GPU-timeline-safe
capture stage and verify it in STALKER 2. This source audit alone does not prove
depth provenance and is not a replacement for the Phase 1 test build.

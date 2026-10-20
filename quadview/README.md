# Experimental stereo Quad Views — Build 41

ID7 renders separate left/right context and focus views, then composes a distinct full-field image for each eye through ordinary stereo OpenXR submission. Runtime quad-view support is not required. The supported target is STALKER 2 UE5.5, DX12, and OpenXR. ID6 remains the preserved monoscopic DuoView path.

Defaults remain 50% × 50% focus, 20% linear context resolution, and 1× focus density. Per-eye PSVR2 gaze projection and crop stabilization, manual offsets, fused focus-only Glamarye sharpening, diagnostics, and optional GPU timing are retained. Saved values are respected. Full scene-target allocations remain; nominal raster-area savings are not proportional GPU-time or FPS guarantees.

Build 41 repairs demonstrated stale-image/pose selection and exact-owner retirement faults, and rejects output when engine ownership proof is lost. It adds no rendering feature or compositor pass. See [RELEASE_NOTES.md](RELEASE_NOTES.md) and [BUILD41_REVIEW.md](BUILD41_REVIEW.md).

Use the complete Windows package and follow [READ_FIRST.txt](READ_FIRST.txt). The source tree alone is not an injector. Start with fixed-center gaze and sharpening disabled at a known-safe resolution, then test gaze, live controls, transitions, and sustained gameplay.

Extreme Compatibility, split-screen, SceneView compatibility, 2D Screen, and Stereo Emulation must be off. Native Stereo Fix is bypassed in ID7; secondary-pass shading parity is not established.

Portable tests, Windows compilation, and WARP checks do not establish headset stability. The original RenderThread crash remains unproven fixed. The engine-ticket ledger observes selected RHI tails, not a universal engine flush; GPU command-slot fences remain separate. An explicit ownership-proof failure requires a game restart.

# DuoView Improved Stereo Reconstruction — Phase A provenance investigation (2026-11-16)

**Base:** `e84c62ed9b9d65c97b940158454064edfcb3f827` (research CI #350), intentionally isolated from shipping DuoView/TriView/VectorXR. **No renderer code changed.**

## Reproduced baselines

Original handoff SHA-256 manifest: 70/70 valid. Original research tests: 15/15 pass (3 use documented compatibility shims). Re-ran independent scorer against 48 official compiled-WARP #350 A/B/C captures (96 per-eye/frame scores): v1 and v2 both fail the strict scene-wise gate. Do **not** merge a new visibility-owner algorithm or claim an RTX 5070 GPU time: CPU visibility overlays increase false stationary-foliage temporal residual by ~61.9%, and WARP is a correctness/quality replay, not an NVIDIA performance test.

## Source-provenance finding

The *legacy coarse fallback* `PeripheryDepth::latest_duoview_submitted(generation,w,h,queue)` calls `select_recent()`; it accepts fence/queue-safe, generation/role/size-valid depth snapshots submitted within a 250ms window, picking highest sequence. Its signature lacks `packet_frame->present_epoch` and `mono_source_frame`. This admits (does not establish occurrence of) cross-Present-epoch color/depth combination. At a hypothetical 20 FPS, several prior frames fit that window.

Important distinction: the archived `m25a-baseline` source is **pre-generation**. The actual #350 `M25a-generated-source.patch` adds M25 epoch-offset histograms (`m25_note_epochs`), an alternate fine-depth content pair, and an M41 same-packet-serial coarse+fine path when M4 full-fine mode is required. Do not duplicate existing diagnostics or wrongly assert M4 uses the legacy selector. The pinned authored `apply_duoview_m41_frame_bind.py` (blob `43d8c11cfdf9b2bf4d708c8359fec816c9668959`, lines 104–145) **does wire** the close-marker call into `FFakeStereoRenderingHook.cpp` before the original engine callback. It requires `deferred_roles == 3`, valid packet ownership, M4 fine-grid/synthetic stereo and matching generation. The remaining unproven condition is that this capture interval truly represents the same color/pose/depth scene under real timing.

## Highest-priority verification

1. Inspect the **fully generated** `FFakeStereoRenderingHook.cpp` and trace marker **runtime ordering**: the authoring overlay contains the call and the workflow applies it, but current evidence does not prove its interval brackets both NGX coarse/fine Evaluate calls for the exact color packet and pose. Verify serial/thread origin, packet `serial`, enqueue/fences, transition/reinit behavior.
2. Validate actual source identity: color packet checks `mono_source_frame`, native `m_game_tex` and pose/generation; legacy NGX depth selector does not consume that ID. Present-epoch equality is necessary in certain fine paths but not automatically identical render-frame/pose.
3. Use existing `[DuoView][M2.5a]` `packet-coarse_hist` and `fine-coarse_hist` diagnostic counters (if wired in target build). Do not impose epoch equality or perform GPU depth readback until the overlap cadence is known.
4. NVIDIA NGX defines a `MotionVectors` input, but inspected depth capture does not acquire it. Its existence does not prove per-pixel confidence; animated foliage/alpha-tested features and MV scale/jitter/frame registration need validation.
5. Only after provenance: one bounded synchronized real RGB/depth/pose capture, then edge-local candidate simulations at 2030x1614 and 4060x3228, compiled WARP no-regression and RTX 5070 timestamp gate.

## Limits / independent reviewer notes

- No real STALKER 2 synchronized RGB/depth/pose trace in the uploaded handoff; its 49px depth fault remains synthetic.
- This branch contains investigation notes only. The full user-visible Phase A packet includes twelve offline policy/source contract tests and a machine-readable source evidence JSON. These are *not* D3D12 build/runtime tests.
- Do not turn a static missing grep match into a claim that an API is unreachable. Inspect complete generated build, not selected evidence snippets.
- No playable build, shader replacement, or frontend/UI change is proposed in this note.

External API references: https://github.com/NVIDIA/DLSS/blob/main/include/nvsdk_ngx_defs.h and https://developer.nvidia.com/blog/?p=95492.

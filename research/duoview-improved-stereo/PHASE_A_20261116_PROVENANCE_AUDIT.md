# DuoView Improved Stereo Reconstruction — Phase A provenance investigation (2026-11-16)

**Base:** `e84c62ed9b9d65c97b940158454064edfcb3f827` (research CI #350), intentionally isolated from shipping DuoView/TriView/VectorXR. **No renderer code changed.**

## Reproduced baselines

Original handoff SHA-256 manifest: 70/70 valid. Original research tests: 15/15 pass (3 use documented compatibility shims). Re-ran independent scorer against 48 official compiled-WARP #350 A/B/C captures (96 per-eye/frame scores): v1 and v2 both fail the strict scene-wise gate. Do **not** merge a new visibility-owner algorithm or claim an RTX 5070 GPU time: CPU visibility overlays increase false stationary-foliage temporal residual by ~61.9%, and WARP is a correctness/quality replay, not an NVIDIA performance test.

## Source-provenance finding

The *legacy coarse fallback* `PeripheryDepth::latest_duoview_submitted(generation,w,h,queue)` calls `select_recent()`; it accepts fence/queue-safe, generation/role/size-valid depth snapshots submitted within a 250ms window, picking highest sequence. Its signature lacks `packet_frame->present_epoch` and `mono_source_frame`. This admits (does not establish occurrence of) cross-Present-epoch color/depth combination. At a hypothetical 20 FPS, several prior frames fit that window.

Important distinction: the archived `m25a-baseline` source is **pre-generation**. The actual #350 `M25a-generated-source.patch` adds M25 epoch-offset histograms (`m25_note_epochs`), an alternate fine-depth content pair, and an M41 same-packet-serial coarse+fine path when M4 full-fine mode is required. Do not duplicate existing diagnostics or wrongly assert M4 uses the legacy selector. M41 is potentially stronger *if* its source marker is wired and its serial truly identifies the same color/pose/depth scene.

## Highest-priority verification

1. Inspect **fully generated** backend and marker hook: `m41_close_capture_interval` is defined in the archived generated patch, but a call is not shown in the archived baseline+patch excerpts. This is a **wiring evidence gap**, not proof of dead code. Confirm marker position relative to NGX coarse/fine Evaluate, serial and thread origin, packet `serial`, enqueue/fences, transition/reinit behavior.
2. Validate actual source identity: color packet checks `mono_source_frame`, native `m_game_tex` and pose/generation; legacy NGX depth selector does not consume that ID. Present-epoch equality is necessary in certain fine paths but not automatically identical render-frame/pose.
3. Use existing `[DuoView][M2.5a]` `packet-coarse_hist` and `fine-coarse_hist` diagnostic counters (if wired in target build). Do not impose epoch equality or perform GPU depth readback until the overlap cadence is known.
4. NVIDIA NGX defines a `MotionVectors` input, but inspected depth capture does not acquire it. Its existence does not prove per-pixel confidence; animated foliage/alpha-tested features and MV scale/jitter/frame registration need validation.
5. Only after provenance: one bounded synchronized real RGB/depth/pose capture, then edge-local candidate simulations at 2030x1614 and 4060x3228, compiled WARP no-regression and RTX 5070 timestamp gate.

## Limits / independent reviewer notes

- No real STALKER 2 synchronized RGB/depth/pose trace in the uploaded handoff; its 49px depth fault remains synthetic.
- This branch contains investigation notes only. The full user-visible Phase A packet includes eleven offline policy/source contract tests and a machine-readable source evidence JSON. These are *not* D3D12 build/runtime tests.
- Do not turn a static missing grep match into a claim that an API is unreachable. Inspect complete generated build, not selected evidence snippets.
- No playable build, shader replacement, or frontend/UI change is proposed in this note.

External API references: https://github.com/NVIDIA/DLSS/blob/main/include/nvsdk_ngx_defs.h and https://developer.nvidia.com/blog/?p=95492.

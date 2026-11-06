# TriView B19 — independent review and NGX resize race fix

Parent: B18 1a96e7b1cc7f71304ed106ec00424f5f14a6bf15.
Headset verification: **not yet performed**.

## Confirmed and fixed
B18 published expected periphery width and height with independent atomic
stores. A simultaneous resize and NGX evaluation could observe dimensions
from two different layouts, causing false depth selection/rejection. B19
publishes one 64-bit packed extent with release/acquire semantics, read once
in capture, lookup, pool pruning and telemetry. No new rendering path,
GPU allocation or manual UI is introduced. The generated backend is checked.

A 250,000-iteration producer/consumer stress test is added to the existing
Windows suite and Linux ASan/UBSan suite.

## Independent audit boundaries
- Three physical UE color targets are 0/2/3, logical 1 is a compositor alias.
- Source reuse and fenced retirement remain B18: no change to synchronization.
- Periphery depth color/frame matching remains approximate (size/time only).
  With overlapping frames, a newer depth evaluation can still be selected.
- World teardown when the engine already destroyed a hooked FRenderTarget is
  not fully proven; conservative retention can consume VRAM over level changes.
- D3D12 state assumptions and device-lost behavior require PSVR2 runtime.
- No claim of crash-free running, FPS improvement, or measured VRAM reduction.

## Safe headset checks
Start ID7 directly with depth OFF. Verify left/right stereo foveas and one
periphery. Enable depth; compare hands/motion. Scroll over diagnostics and
save/restart. Change periphery density moderately once and observe reuse_mask.
Then load another world. Stop after GPU reset or BSOD; preserve log/minidump.

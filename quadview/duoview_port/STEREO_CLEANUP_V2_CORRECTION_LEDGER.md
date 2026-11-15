# DuoView V2 correction ledger — 15 November 2026

Branch: experiment/stereo-cleanup-v2-fixes-20261115
Source: B318 #333 (5e89842f5b857e727e5aba82c7cfbd4160eee882)
Broken V2 head: 8804c5060e733826f6a1ba5aff412e0002f07d99
Status: corrective source commits; NOT CI/WARP/PSVR2 approval.

## Corrections

- P0 selector: the effective Settings.edge_reach_px (2 legacy, 20 new)
  now goes through Compositor::record_native -> M1Resources::write_constants
  -> data.m8_distance[3] -> HLSL M8Distance.w. The old temporal reach
  lane is reserved for this internal flag; no GPU layout change.
- P0 strict M4 pairing: restore internal M25 mode 1 while M4 enabled
  and old M2-only selection outside M4. This avoids filtering a valid
  strict fine_pair through the unrelated general pair pointer check.
- P0 coarse algorithm: replace unbounded winner-only origin/scale
  propagation with an associative constant-penalty envelope applied
  to reparameterized inverse depth, for BOTH coarse and production M4.
  The 3-segment continuous depth map has inverse derivative 0.10..1.0,
  so a <=0.99 grid slope remains within bound after unmapping.
  The new transition approximates (does not equal) the older M8 cubic.
  All unedited legacy depth response branches are preserved.
- P1 M8 OFF: zero stereo fill endpoints skip foveal hole search even
  when the legacy distance switch is off. The former pull is deliberately
  retired, so this is not complete B318 pixel parity.
- P1 first edit: old curve holds until explicit conversion button,
  after which the revised close/far controls are visible.
- P2: remove two unused compositor temporal-history locals.

## Reviewer issue ledger

| Finding | Status | Remaining verification |
|---|---|---|
| GPU selector hardcoded 2 | Patched | generated CPU-to-CB chain, MSVC/WARP |
| M4 fine pair rejection by M25=0 | Patched | delayed strict-pair fixture |
| New coarse winner propagation violates no-fold | Replaced | 2800 randomized cone-oracle tests in CI; GPU pixels |
| M8 disabled yet foveal 32-step search active | Patched | shader gate and image check |
| Stored M2-only fine contribution lost | Restored | old-profile regression fixture |
| Tiny slider edit replaces whole old transition | Explicit conversion | save/restart migration |
| Original M6/M7 edge history at 0.70 removed | Deliberate image change | headset motion and vegetation |
| Null D3D12 SRV/UAV and history lifetime | Uncompiled | FXC/MSVC/WARP debug layer |
| INI obsolete keys remain registered | Necessary legacy support | migration matrix |
| M1/M4 field blend can exceed independent slope bound | Theoretical risk | crop transition fixture |
| Object-edge disocclusion artifacts | Not fixed by cleanup | visibility/hole-mask prototype |

## Test boundary

The standalone local oracle passed 3500 deterministic random depth fields,
including reproduction of the adversarial 16-cell counterexample.
The new repository test runs 2800 random fields in the production workflow.
The generated-source test checks effective compositor forwarding, writer
assignment, shader-mode map/unmap and M41 gate. These are source and
mathematics tests, NOT a GPU constant-buffer readback or a WARP pixel test.

Not run yet: final Windows shader compilation, MSVC build, WARP GPU parity,
headset motion/relaunch, VectorXR, RTX 5070 timing or VRAM measurements.
Do not claim image-quality improvement from the cleanup build alone.

Preserved source intent: B318 source fit/output FOV, eye geometry and scale,
separate L/R sharpening, B40 seam history, NGX capture packet leases,
mono-first startup, true-mono fast path and XR depth swapchain skip.
B318 rollback remains unchanged.

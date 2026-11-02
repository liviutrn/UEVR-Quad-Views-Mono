# PROGRESS (Tri-View rebuild, branch claude/triview-s2-20261102)

Started 2 Nov 2026 02:00 (Claude, overnight). Base: claude/triview-stage1-fixes-20261101 (955ef14, v207 + Tri-View Stage 1 build 3).

## Root cause (from Liviu + Sol's Build 52 GPU capture, STALKER 2.10 = UE 5.5.4)
- [CAPTURE-VERIFIED, Build 52] A singleton view-family render puts its image at the target's (0,0) corner,
  even when the view rect asked for x = W (Build 51 asked for x = 2436 / 487 / 2923 and the constructor saw
  those rects; the pixels were still at x = 0). Under 2.06 the requested position was honoured.
- [source-read] Tri-View Stage 1 rendered the third (periphery) view into the main target at x = W.
  So [estimated, very likely] it landed at (0,0) on top of the left fovea: matches "periphery where the
  left eye should be, black edges, distortion".

## Fix (this branch)
- Third view gets its OWN render target (same kind as Joey's Native Fix capture: Kismet target, a capture
  component on Joey's capture actor keeps it alive, same gamma hook). View rect (0,0). No engine flag writes.
- Compositor samples three textures: main (left fovea at 0,0), capture (right fovea at 0,0), periphery (0,0).
- Automatic GPU capture: a ZIP next to the UEVR log with the three sources + the XR image + numbers.

## Status
- [ ] code  - [ ] local replay  - [ ] review  - [ ] CI  - [ ] headset (Liviu)

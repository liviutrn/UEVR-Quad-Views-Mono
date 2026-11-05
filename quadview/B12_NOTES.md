# Tri-view B12 (Claude, 6 Nov 2026) - on B11 (headset-tested 6 Nov 00:52-01:04)

Status: CI only until the headset test. NOT headset-verified.

## Evidence from the B11 headset run
- Depth capture worked: 18385 periphery copies, 18227 used, warp state "warping".
- Doubled hands: reproduced offline from the B11 snapshot (tools: numpy re-implementation of the shader on
  the real periphery colour + DLSS depth, compared with the real left-eye fovea). Geometry scale 1.0 fits best
  (geometry correct); the 4-step fixed-point warp stays on the mono position for close objects (hands at ~18 cm,
  ~36 periphery px of disparity) and shows a second, unshifted arm.
- Cold start: with ID7 saved, Selection::initialize starts active=0 / requested=7; the request never committed
  until Native Stereo + Fix had run (committed 4 s after the user's manual detour).
- Crash: first periphery-resolution change; ensure_quadview_native_target_set unpublished the live per-role
  set before the new one existed; frames fell back to the full atlas path (+850 MB VRAM transient seen at an
  earlier resize) and the process died 20 ms into that window (null read in ntdll; exact pointer unknown).
- VRAM: ~8.1 GB already at the ID7 commit; mod-owned textures ~15 MB; depth copies 260x204 (tiny).

## B12 changes
1. Shader: depth-marched backward warp (24 inverse-depth steps near->far, first surface hit, linear refine),
   disocclusion detected by a depth jump and filled with a soft 3x5 background average. Offline on the real
   frame: mean error vs real fovea 10.06 -> 8.47, no duplicate arm.
2. apply_triview_autostart.py: saved ID7 -> Native Stereo + Fix warm-up (cancel startup request, Fix ON),
   request ID7 after Native Fix is Active for 3 s (or 25 s), restore the user's Fix toggle after commit.
   [TriView][Autostart] and [TriView][Transition] log lines.
3. apply_triview_resize_safety.py: make-before-break. ensure() keeps the old set published while building a new
   one in the same world; draws keep the last live sizes until the new set publishes ([TriView][Resize] log).
4. Gaze menu identical to DuoView v218 (labels, help texts, guard only with Stable crop, defaults button);
   PSVR2 reader retry backoff 0.5 s -> 30 s as in DuoView v207. Gaze algorithms were already shared code.

5. apply_triview_vram.py: no OpenXR depth swapchain while TriView is active/requested/warming up (ID7 never
   submits depth): -240 MiB at 2568x2040 per eye, -768 MiB at 4096x4096. VRAM inventory: everything else UEVR/mod
   allocates in ID7 is small (colour swapchain 120 MiB is required; compact sources ~15 MiB; depth copies tiny).

## BSOD review (6 Nov, source-only)
No proven cause. No GPU-side waits/cross-queue fences in ID7, shader loop bounded, compositor slots fence-gated.
Risks: VRAM near budget (ID7 + QuadViews Build 51 both reported BSOD, Build 51 had no NGX code); the NGX depth
copy assumes NON_PIXEL_SHADER_RESOURCE at Evaluate (driver-level risk if wrong). Need the Windows stop code.

## Not done / open
- Crash root pointer unproven; B12 removes the window it happened in.
- CropStability is still committed before a layout is accepted (DuoView commits after) - minor.
- Per-eye gaze/convergence (PSVR2 per-eye rays) not used; same as DuoView.

# TriView B42 - VRAM safety

Problem (headset, 9-10 Nov 2026): BSOD 0x139 when the game's VRAM reaches its DXGI
budget (~10 GB of 12 GB). Not NGX hooks, not Cheeky NR (both off: still BSOD).
Each new TriView source size makes Unreal allocate a new set of scene buffers while
the old set is alive; crop changes and resolution increases push it over.
r.SceneRenderTargetResizeMethod=2 stops the climb but raises the start (+2.7 GB in
10 s, likely full-size scene buffers for every view): remove it from Engine.ini.

What B42 does
- VRAM guard: a resize builds a new set only if used + estimate <= limit
  (menu "VRAM limit for resizes", default 85 % of budget). Estimate = 100 B per
  source pixel (guess; calibrate from logs). Smaller sets allowed up to 95 %.
  Refused: the live set keeps drawing, the menu shows the refusal.
- Focus width/height, periphery scale, density snap to 0.05 steps.
- 1.5 s pause after each published set before the next rebuild.
- Low-resolution start (menu, default ON, scale 0.3): with TriView saved, the
  headset starts at 0.3; once TriView runs with a published set for 3 s and the
  guard allows it, ONE switch to the saved scale (same path as the menu slider).
  Saved OpenXR_ResolutionScale is never written. Moving the resolution slider
  ends it; TriView not running -> switch at once.
- Logs: [QuadViews][VRAM] every 2 s with depth pool slots/MB; VRAM on every
  [TriView][Resources] build and Published line; [TriView][VRAM] build allowed /
  resize REFUSED; [TriView][LowStart].

Status: CI only, NOT headset-tested.
Headset test: 1) start in TriView at 0.6x0.6: low start then switch to 1.0, no BSOD?
2) change crop fast many times: VRAM stays below the limit, refusals shown instead
of a crash? 3) send the log.

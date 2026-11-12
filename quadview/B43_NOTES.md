# B43 (over B42.5): stronger per-eye sharpen, shorter startup holds

Status: compiled only after CI; NOT headset-tested yet.

## Sharpen
- Strength range 0-10 -> 0-20, max change per pixel 0.40 -> 0.80, both eyes.
- New per-eye toggle "extra-wide sharpen" (QuadViewSharpenWideLeft/Right, default OFF):
  adds a second Glamarye ring at radius 2.8 (guard 7.0) on top of the normal 1.4 ring.
  Shader (B43b): GlamSharpenFocus/DisplayFocus are byte-identical to B42.5; the new
  GlamSharpenRingChange (copy of the body with radius/guard parameters) is applied only in
  ScenePixel (display), Sharpen.y bits 8/16. Seam analysis (CSSeam) is unchanged.
- First B43 attempt (ring inside GlamSharpenFocus) failed CI twice in
  quadview-combined-seam-production-gpu ("Adaptive matching did not fit the two eyes
  independently") although that test runs with sharpening OFF. Most likely cause (not proven):
  the much larger seam compute shader (DisplayFocus is unrolled 15x+3x there). B43b keeps the
  compute shader identical to B42.5, which also isolates the question.
- Tests: test_triview_b23_four_samples.py checks the ring equals the protected body;
  b38/b39 ScenePixel freezes ignore only the B43 block (b43_scene_strip.py).

## Startup (log 12 Nov 12:34, B42.5)
First game frame 29.7 s -> Native Fix ready 34.8 -> ID7 request 36.8 (2 s hold) -> one-time
UObjectHook scan of 400k objects 36.97-39.75 (2.8 s game-thread stall, triggered by
get_live_objects_by_class_name right after the ID7 commit) -> low-res set 40.4 -> full-res
switch 43.4 (3 s hold) -> full-res set 44.4. About 14.7 s in total.
B43: warm-up hold 2 s -> 1 s, low-start hold 3 s -> 2 s (must stay >= 2 s: VRAM sample is 1 Hz
and must be newer than the set, see the review). Expected saving ~2 s.
Not touched yet: the 2.8 s object scan (could be activated earlier, while fewer objects exist)
and UEVR's own ~5 s hook discovery.

## VRAM (same log)
Menu at low res 5.1-6.4 GB; full-res switch +1.7 GB (estimate 1558 MB); in game 8.4-8.8 GB of a
9.6-9.8 GB budget (86-91 %). The budget fell from 11.2 GB as SteamVR/other processes grew.

# CI82 — single-source stereo with same-camera hole fill (Claude, 31 Oct 2026)

Branch `claude/ci82-single-source`, built on ChatGPT's CI81 (#127, d9e82db). One
decisive experiment agreed with Liviu: if it is not clearly better than DuoView
Mono in feel, the stereo line stops and Mono is the product.

## Hypothesis (not headset-verified)
CI77–CI81 made depth steadier and each got "a little better". The final
compositor still chose, per pixel and per frame, between two different images
(alpha >= .995 → reprojected source, else native RIGHT). CI75 measured ~18% of
the RIGHT fovea and ~40% of the LEFT periphery as fallback, with 12–18%
frame-to-frame mask change. Sharp/blurry (and DLSS-5 / plain) owner flips at
edges read as shimmer; native RIGHT at the same screen position in the LEFT
periphery is the documented cause of doubled hands.

## Change
- Surface pass, bit 256 (`VSFill`): after the measured footprints, a coarse
  2-texel connected mesh of the SAME source is drawn with clip z = cleared
  depth, so it lands only where no measured surface did. Triangles across a
  depth edge use the flat colour of their farthest corner (background
  stretch, no foreground smear). Sky/far samples are pushed far along their
  ray. The RIGHT-depth veto (bit 1) still applies, so real RIGHT foreground
  stays visible in the RIGHT eye. Fill pixels write premultiplied alpha
  254/255 (yellow in coverage mode 6).
- Compositor, mode 5 + stabilized (`SingleSourceComposite`): RIGHT eye centre
  = LEFT reprojected, LEFT eye periphery = RIGHT reprojected; leftover gaps
  fade softly to native RIGHT; fovea/periphery cross-fade per eye (both
  layers share that eye's geometry). No hard .995 switch.
- Mono foreground guard forced off in this path (it deletes near geometry
  that the fill would then replace with background).
- Host: surface upload buffer 1024 → 2048 bytes (fill constants at
  1024/1536), one extra DrawInstanced per pass. No new textures.
- Test: `ci77/footprint_gpu_tests.cpp` `test_same_source_disocclusion_fill`
  runs the production VSSurface/PSSurface on WARP: a 4-px disocclusion next
  to a foreground block must be filled with background colour, while the
  foreground edge and background keep their measured colour/depth.

Legacy modes/strategies are untouched; the cleanup is deferred until this
experiment is judged.

## Known limits
- Disocclusion strips show stretched background (classic DIBR look); wide
  for near objects.
- LEFT periphery at the outer left frame edge (never seen by RIGHT) still
  falls back to native RIGHT.
- Coarse RIGHT depth at periphery 0.2 makes peripheral object edges blocky.
- Requires "Stabilize depth" ON; otherwise the legacy path runs.

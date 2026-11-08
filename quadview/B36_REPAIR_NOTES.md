# B36 — work in progress; black-bar root cause unresolved

Base: user-tested B35-125 (`dba83e5845ac69d5b7064fbada13f8175e44cb09`). No completed B36 test artifact is approved for headset testing.

## Confirmed changes

Edge V2 ignored the original Context/focus blend feather. Its shader now combines that fraction-based control with the explicit inward-pixel feather, using the wider effective feather. B31 anti-vignette remains unchanged.

The depth capture pool could recycle its sole/newest valid submitted snapshot before a replacement was submitted, leaving an availability gap between Record and Submit. The pending B36 policy reserves the latest still-selectable snapshot while recording a replacement. The existing 250 ms selector age, matching tolerance, producer fences, consumer leases and twelve-slot cap remain unchanged. No CPU wait or per-frame heap allocation is added. This closes a verified availability gap; runtime evidence is still needed to establish whether it explains all below-30-fps shake/dropouts.

## Black strip: do not conceal it

The supplied final screenshot has five RGB-zero columns immediately inside its right yellow focus border, for all 600 rows sampled. This does NOT establish that the raw focus source contains black. An initial uniformly-black-padding detector/clamp was implemented, then removed after the user explicitly rejected masking the defect. Do not reinstate it as a root-cause fix.

Independent B31→B35 source comparison found `AtlasUvKnownSize`, `ReadFocus`, `GlamSharpenFocus`, `CorrectFocusColor`, `SeamFocusWeight`, `ScenePixel` and PSMain unchanged. At a fully opaque focus pixel (`weight==1`), ScenePixel does not call context matching: it returns the focus source through the same sharpening/color correction. Thus the V2 context correction cannot independently paint an opaque focus pixel black given identical actual resources/constants. Pixels within the feather region remain a separate case. Runtime source bindings, valid rendered rectangles, NR/SR output coverage and downstream composition are not proven by this source invariant.

Required evidence: existing B35 snapshot from a bad frame, containing `src2_fovea_left`, `src3_fovea_right`, `eyes_final`, periphery/depth when available, and rect/crop metadata. Include current seam/inward feather, standard feather, sharpening and NR settings (B35 snapshot metadata does not record all these controls).

- Stripe in raw focus: inspect producer/upscaler output coverage and valid rectangles; compare NR on/off or pre/post-NR data to isolate that stage.
- Healthy focus, striped final at an opaque pixel: inspect actual shader constants, resource descriptors/formats and sharpening.
- Healthy final, striped mirror/headset: inspect downstream runtime composition.

Do not claim a root-cause fix or publish a complete B36 release before identifying the first failing stage. The clamp-bearing candidate is withdrawn. Build/test work is held to avoid spending another full Windows build on an unproven workaround.

## Local verification

B31 anti-vignette byte identity, generated overlay anchors, restored-feather source gates, depth continuity portable tests and inherited source/settings checks pass locally. Production WARP has standard-feather coverage added; current revised B36 Windows shader/backend execution is pending. B35's prior passing tests do not certify these new changes or solve the user-reported strip.

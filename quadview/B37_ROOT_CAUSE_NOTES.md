# B37 — B31 base, final color rectangle root repair, blend and depth continuity

Fresh experimental branch starts at the exact B31-110 commit `008c9f7548c43f5977c1197c4180cddb435c64de`. Reviewed B35 GPU matching/history is ported in isolation; B31 producer/engine view dispatch, target allocation, retirement and DuoView baseline remain intact. The abandoned black-padding detector/clamp is NOT included.

## Black bar: first failing stage identified

Evidence is the user-provided B35 snapshot `triview_20261108-165129`, not a generated image. Both raw final fovea textures are 2112x1664 BGRA8. Their RGB content occupies x0..2029 and y0..1613. Every column x2030 onward is black allocation space. The metadata engine rectangles are:

| Role | Engine identification rectangle | Actual final color rectangle |
| --- | --- | --- |
| Left focus | x16, y0, width2030, height1614 | x0, y0, width2030, height1614 |
| Right focus | x24, y0, width2030, height1614 | x0, y0, width2030, height1614 |
| Shared periphery | x0, y0, width812, height646 | x0, y0, width812, height646 |

The compositor used engine identification origins as color sampling origins. It skipped the first16/24 real columns and sampled16/24 black columns on the right. This is a coordinate-contract error, not missing edge detail to conceal.

Independent final-output cross-check: focus crop is x1015..3044 in each4060-wide eye. The wrong left/right origins predict black starting at eye-local x3029 and x3021. The saved final composite has exact-zero RGB columns beginning at precisely3029 and3021 across all1400 rows y900..2299 checked. The last border pixels are affected by the existing yellow debug outline/transition. This independently confirms the overrun explanation.

The same logical-origin sampling code existed in B31. The stronger B35 edge reference and different blend behavior made the mismatch conspicuous and propagated the black reference into the periphery. The snapshots establish the fault in the tested B35 configuration; they do not establish every historical B31 setup.

## Root repair

`color_source_rect()` separates final color-image coordinates from engine construction/identification rectangles. For standalone native-local targets it returns origin0 with the full original width/height. Shared atlas mode retains its original origins. The engine roles keep their x16/x24 identifiers; producer dispatch, allocations and lifetimes are unchanged.

No border detection, pixel rejection, cropped-away strip, widened blend to hide the bar, stretched image or replicated edge pixels. All2030 original fovea columns are read at their proper coordinates. The matcher therefore measures actual last-column content instead of empty allocation space. Snapshot metadata now also includes explicit color rectangles.

Origin0 is proven by the supplied final targets for the current rendering/NR configuration. Producer hooks do not expose a definitive final postprocess viewport for every AA/plugin combination. NR-off/other-AA universality remains unverified and is an explicit headset comparison, not an asserted result.

## B31 fovea and blend

`AtlasUvKnownSize`, `ReadFocus`, `GlamSharpenFocus`, `CorrectFocusColor` and `ScenePixel` remain byte-identical to B31. Only the bound native final-color rectangle is corrected. Edge V2 uses B31's original `FocusWeight` and existing Context/focus blend feather; the extra inward-pixel strip/control added for B35 is removed from V2 UI. Opaque focus pixels never run context correction. Matching acts on the context layer, including that layer's contribution to the existing feather overlap; the fovea source itself is not filtered by the new matcher.

The B31 legacy modes remain selectable. Their explicit old seam-transition control remains for compatibility; Edge V2 does not substitute it for the standard fractional feather.

## 20 FPS depth continuity

Capture could recycle its sole/latest usable submitted depth while a replacement was only being recorded. Presents between Record and Submit could see no valid snapshot and fall back to mono periphery. The new policy reserves the latest still-selectable snapshot until a newer valid submitted one takes its place. Other slots follow original producer-fence and consumer-lease reuse checks; the twelve-slot cap, matching tolerance and250ms age remain unchanged.

No added CPU/GPU wait, no expired-depth forcing and no per-frame heap allocation. Portable tests exercise repeated50ms (20 FPS) and44ms (22.5 FPS) Record/Present/Submit cycles, replacement promotion, age expiry, resize, failed evaluation and incomplete foreign-queue fences. This fixes a verified availability hole; exact frame provenance and every possible source of shaking are not solved by that policy. Invalid/missing/expired depth still legitimately disables warp.

## Verification and limits

Local source anchors and B31 focus-code identity gates pass. Portable tests reproduce captured geometry and distinguish logical versus final-color rectangles. Production WARP fixtures independently place final native content at0 with distinct first/last columns, eye markers and black allocation padding; every focus pixel must be preserved with matching off/on. Atlas coordinates, RGB/sharpening, standard feather, temporal stability/reset and depth validity coverage remain. Windows FXC /WX and WARP/backend/frontend gates must pass before the candidate is delivered.

No headset stability, invisible seam, no-flicker or RTX timing claim before user testing. The current capture verifies one NR/AA configuration. Keep the working B31/B35 packages as backups.

## First headset check after CI passes

Keep anti-vignette and ordinary standard feather settings. Use Edge V2 Temporal defaults. Check both outer focus edges with the yellow debug border, then turn the debug border off for appearance judgment. The full source image should be in place, without the black strip or its induced dark spill.

Compare the standard feather0/usual value, and NR before SR on foveas only/on-off if available. If NR-off differs, save a raw snapshot before inferring which producer output-rect contract changed. Finally test normal motion and20/22.5 FPS reprojection, compare total compositor GPU ms/VRAM and retain logs on any depth dropout.

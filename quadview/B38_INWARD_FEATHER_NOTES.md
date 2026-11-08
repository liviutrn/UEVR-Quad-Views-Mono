# B38: original B27 inward feather plus B37 exterior seam correction

## Provenance and scope
Base: B37-128 commit `9a4596a796ec447ada2390922284ac0eb74734d9`. Only the compositor's inside-feather mixture is changed. B37's depth continuity at 20/22.5 FPS, right/left native final-color rectangles, outer matching, GPU temporal history, queue/fences, fovea sharpen and anti-vignette remain untouched.

The admired B27 "blur" was a smoothstep crossfade of high-resolution focus into lower-resolution context INSIDE the crop; not a separate Gaussian blur. B37 retained its FocusWeight but changed the source in that inward crossfade by color-correcting the context. B38 uses raw original context in most of this feather.

## Algorithm, no new pass
- Outside crop: B37 matching byte-identical.
- Inside crop: read context once, compute its B37-matched version using existing math, smoothly fade matched->raw across the first 12 output pixels inward. Beyond the 12-pixel continuity strip, feed the uncorrected context through exact old B27 `lerp(context,focus,FocusWeight)`. Fully opaque focus remains unchanged.
- Existing feather fraction controls the full softness (e.g. .08 or .12). New "Original inward fovea feather (B27)" toggle defaults ON, OFF reproduces B37 exactly. "Inside seam continuity strip" 2-64px, default 12px.
- Original B31 gain/auto matching modes remain available separately, not summed with B37's signed corrections (double corrections can break seam accuracy). B37 Temporal is the actual time-smoothed matcher; the older B31 matching was spatial.
- No added texture read, compute pass, CPU wait, GPU allocation, state ownership, fence, depth queue or change of constant-buffer size. Main potential extra work is scalar blending where feather exists.

## Verification
Run full B37 original regression tests, B38 source identity gates, generated in-game UI checks, settings validation, production D3D12 WARP tests (outside and opaque exactly unchanged, inner after strip exactly old source interpolation), original backend/frontend compatibility suite. CI success cannot prove in-headset appearance; retain B37-128 for rollback.

Recommended headset check: Edge matcher Temporal, original inward feather ON, standard Context/focus feather 0.08 then 0.12, anchor 12; compare toggle OFF without changing other settings, with NR before SR in the foveas. Check head movement, gaze, corners, low-FPS depth, GPU ms and any residual seam shimmer.

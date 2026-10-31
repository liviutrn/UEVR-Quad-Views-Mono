# CI79 — RIGHT eye centre from the LEFT camera (smooth), LEFT outer view at the right place

**CI79b status (31 Oct): Change 2 (LEFT outer view) is DISABLED in this build.** Builds #117-#121
failed the CI69/CI70 software-GPU (WARP) tests with device removal (0x887A0005) in the final
composite shader; moving the CI79 shaders into their own entries and creating their pipelines
lazily did not help. The remaining suspect is the loop-heavy row search added to the composite
shader, so it is stubbed (same picture as CI77b) and its menu switch does nothing. Change 1
(RIGHT eye centre) is unchanged. If the tests pass, change 2 returns as its own shader pass.
The text below still describes the intended design of both changes.

**CI81 (on ChatGPT's CI80, 31 Oct): headset result of CI79b and what changed.** Liviu: the RIGHT-eye
switch "stabilizes a bit" but adds a double image on the RIGHT SIDE of objects and destabilizes
other things. Cause (source-read): on the right side of a near object the RIGHT eye sees a strip of
background the LEFT camera never saw (the object hid it). The pass still accepted the object's
colour from the LEFT picture there, because the colour-match tolerance grows with local detail,
i.e. exactly at edges. Fix: every proposal is also checked against the LEFT camera's own depth at
the place it would copy from (`DTLeftDepthAgreement`, 3x3 LEFT depth texels; 1.5x the
discontinuity bound allowed, fading out by 3x). A proposal hidden behind, or landing far from, the
surface LEFT really sees gets weight 0 and the pixel falls back to the colour-matched RIGHT image.
Not changed: the colour-match tolerance itself (one change per build).
Also: CI80 encodes its mono hand guard as reserved = 3 (stabilized = 2) and reads `>2.5`; CI79's
"+1" would have switched the guard on silently. CI79/CI81 flags now live in the fraction
(+.25 = RIGHT fovea) so those thresholds never see them. The hand guard defaults OFF under a new
saved name (DuoViewMonoForegroundGuardCI81), so an old saved ON cannot override.
Cost of the new check: 27 extra LEFT depth loads per fovea pixel; performance is not measured.
TODO before re-enabling the LEFT outer-view fix (flag +.5): +.25 and +.5 together make 2.75, which
passes CI80's `_reserved>2.5f` hand-guard test. Use `floor(_reserved)` in those thresholds first.

Built on ChatGPT's CI77b (experiment/ci77-stabilized-depth-left-geometry-20261030,
commit d6a9e9c). Experimental. Every claim here is source-read, plus
CI-verified once the Actions run for this exact commit is green. Nothing is
headset-verified yet.

## What the headset tests told us (Liviu, 31 Oct, headset-verified)

- CI77 with temporal ON: slightly less shimmer than OFF; good colours/shading.
- CI78: steadier, less shimmer, but worse colours/shading and strong rivalry:
  the RIGHT camera (whole view at ~0.2 scale) renders visibly different colours
  and shading, and CI78 took the RIGHT eye's colours from it.
- CI77b pixel footprints: helps grass a little, everything else still shimmers;
  the temporal depth weight/toggle shows no visible effect.
- LEFT outer view: wrong field of view, hands superimposed from the centre,
  two hands. Peripheral resolution above 0.2 gives artefacts; 0.499 gives a
  black outer view (not addressed here, needs a log, see below).

## Change 1: RIGHT eye centre (switch "CI79: RIGHT eye centre from LEFT camera, smooth")

The RIGHT eye's centre now shows the LEFT camera's colour, shading and detail
wherever the LEFT camera saw the same thing, like CI77, but chosen the CI78 way:
depth only proposes three places the colour could come from; the two stable
pictures decide with smooth weights, now over a 3x3 RIGHT-pixel neighbourhood
(more samples than CI78, so the choice moves less between frames). The LEFT
picture is favoured as soon as a proposal matches reasonably well. Where the
LEFT camera saw nothing (thin strips behind edges) the RIGHT image fills in,
colour-matched to the LEFT picture so it does not stand out. No yes/no switch.

Why not just stabilize depth harder: DLSS input depth is one jittered sample per
pixel. At edges the edge itself moves between frames, and a depth filter must
not blend foreground with background, so it cannot calm edges (source-read in
DuoViewDepthStabilization.hlsl). That is why the temporal depth slider shows no
visible effect. Stability has to come from not letting per-frame depth make
yes/no choices, which is what this does.

## Change 2: LEFT outer view (switch "CI79: LEFT eye outer view at correct position")

Wherever the reconstructed LEFT outer view had a hole (about 40% of the region
CI75 recorded), the LEFT eye was shown the RIGHT camera's picture at the same screen
position (source-read, SurfaceComposite). But the two eyes' views are mirrored
and 6-7 cm apart, so those pixels showed things in the wrong place: wrong field
of view, a second copy of the hand, and a hand that does not line up with the
sharp centre. Now each such pixel looks along its row of the RIGHT image for the
surface it really sees (nearest consistent surface wins; if the RIGHT camera
cannot see that spot, the background is shown), and the reconstructed and
filled pixels blend smoothly instead of switching.

Both switches sit under "CI77: Stabilize depth" (Stereo and quality → Advanced
stereo and capture diagnostics), default ON. Both OFF = CI77b exactly.

## Headset questions

Close the other eye to judge one eye at a time; toggle each switch a few times.
1. RIGHT eye centre with change 1: shimmer and colours/shading compared with OFF
   (CI77b)? Any rivalry left with both eyes open?
2. LEFT eye outer view with change 2: field of view and hands correct now (one
   hand, lining up with the centre)?
3. Anything new that looks wrong?

Optional: stereo mode 6 shows the RIGHT centre's confidence (green = LEFT
picture used, red = RIGHT image).

## Peripheral resolution above 0.2 (not fixed yet)

The cause is not visible in the code without a log. Please reproduce once
(set 0.3 and wait 5 seconds, then 0.499 and wait 5 seconds), quit, and send the
UEVR log: %APPDATA%\UnrealVRMod\<game exe name>\log.txt.

## Limits

- No temporal colour history is added. If shimmer remains, that is the next step.
- The LEFT outer view uses the legacy row mapping (ndcL = a*ndcR + b + c/z),
  which ignores any vertical difference or rotation between the eye cameras.
- Cost is not measured. Change 1 replaces the LEFT-geometry mesh for the RIGHT
  centre; change 2 adds about 15 depth reads per filled outer pixel.

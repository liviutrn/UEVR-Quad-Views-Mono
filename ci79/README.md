# CI79 — RIGHT eye centre from the LEFT camera (smooth), LEFT outer view at the right place

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

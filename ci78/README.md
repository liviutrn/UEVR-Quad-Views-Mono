# CI78 — RIGHT fovea = real RIGHT image + LEFT fine detail

Built on CI77 (claude/start-from-ci77, run 41119727868). Experimental.
Status of every claim below: source-read, plus CI-verified only once the
Actions run for this exact commit is green. Nothing here is headset-verified yet.

## The problem it targets

The shimmer in the RIGHT eye's sharp centre. Until CI77 each pixel there was
either sharp colour copied from the LEFT camera or the RIGHT camera's own colour,
which is about 5x blurrier (CI75 capture: RIGHT 812x646 vs LEFT crop 2030x1614).
The choice was a yes/no test on DLSS depth, and DLSS depth is jittered and
aliased every frame on grass, leaves and thin lines. The CI75 capture measured
~18% holes in the synthetic RIGHT fovea and ~12% of that mask changing between
neighbouring frames: pixels flipping between sharp and 5x blurry. CI77 smooths
depth on flat surfaces, but its history is rejected exactly at depth edges, so
it cannot stop those flips.

## What CI78 does

The RIGHT eye always keeps its own real image for every shape, colour and
outline, and only borrows the fine detail from the sharp LEFT image:

    RIGHT eye centre = real RIGHT image + confidence x (LEFT detail)

Depth no longer decides yes/no. It only proposes up to three places the detail
could come from (nearest, middle and farthest surface around the pixel). The two
stable, DLSS-finished colour images decide how much each proposal is trusted,
with smooth weights. A wrong proposal can at worst misplace fine texture; it
cannot paint a second copy of an object, because outlines always come from the
real RIGHT camera. The borrowed detail fades in across the fovea edge instead of
a hard seam. The LEFT eye is unchanged.

Cost: one tiny pass (LEFT blurred to RIGHT size) and one full-screen pass over
the RIGHT fovea, replacing the LEFT-geometry mesh. Not measured yet.

## Where the switch is

Stereo and quality → Advanced stereo and capture diagnostics →
"CI78: RIGHT fovea = real RIGHT image + LEFT detail (OFF = CI77)".
Default ON. It appears only while "CI77: Stabilize depth" is ON (default).
OFF gives exactly CI77, so you can compare live without restarting.

## The one headset question this build answers

Stand still where the shimmer was worst (grass, leaves, fences, wires). Close
your LEFT eye so you see only the RIGHT eye, and toggle CI78 on and off a few
times. Please send three lines:

1. Shimmer in the RIGHT eye centre: better, same or worse with CI78 ON?
2. Sharpness of the RIGHT eye centre with CI78 ON: close to the LEFT eye, or
   clearly softer?
3. Anything new and wrong (smeared texture next to edges, halos, colour shifts)?

Optional diagnostic: stereo mode 6 now colours the RIGHT fovea by detail
confidence (green = full LEFT detail used, red = real RIGHT image only).

## Limits

- A thin object that the low-resolution RIGHT depth does not contain gets its
  detail from the surface behind it: it stays stable but its fine texture may sit
  at slightly the wrong depth. Real disocclusions stay at RIGHT sharpness.
- The RIGHT image's own low-resolution DLSS shimmer, if any, is not removed.
  Raising peripheral resolution still helps.
- Near hands/weapon now also use detail transfer in the RIGHT fovea (their
  outline still comes from the real RIGHT image). Report it if they look worse.
- No temporal history is added. If shimmer remains, the next step is a short
  history on this one output, not more depth rules.

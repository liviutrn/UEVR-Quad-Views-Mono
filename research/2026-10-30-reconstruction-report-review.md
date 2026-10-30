# Review of the 30 October synthetic-stereo research report

Reviewed artifact: `deep-research-report (1).md`, titled **DuoView Synthetic
Stereo Reconstruction: Engineering-Ready Research and Validation Plan**.

## Decision

Keep its measurement strategy and stage geometry/history independently.
Treat HSVR-L2 as an untested candidate, not a selected replacement architecture.
First compare the minimally corrected CI73 baseline against CI71/72 on the
same nonzero-baseline moving input sequence using production shaders.

## Useful requirements to carry into the separate benchmark project

- Identical replay inputs for every strategy, with exact active strategy and
  effective shader/source hashes recorded.
- Independent physical cameras and jitter phases, moving gaze crops,
  unequal input/output dimensions, nonzero subrect origins, and reversed Z.
- Ground-truth disparity and visibility, slanted planes, thin poles/fences,
  moving foreground, viewmodel geometry, and true disocclusion.
- Track geometry error, motion-compensated edge error, useful high-resolution
  reconstruction coverage, unsupported coverage, native fallback, ghosting,
  and per-pass timings. A fallback-only image cannot count as improvement.
- Compare transported previous ownership on the same visible surface, not
  merely owner values at a fixed screen pixel during camera/object motion.
- Evaluate vertical disparity error relative to ground truth or rectified
  geometry; asymmetric eye projections need not produce zero raw vertical
  disparity in unrectified images.

## Corrections needed before implementing the proposed architecture

1. **Provenance:** a `CurrentRHIPacket()` lookup and extent comparison still
   do not bind a DLSS evaluation to a specific physical view. The exact hook,
   final jittered/unjittered matrices, view token and resource identities must
   be linked at the producing evaluation. Include accepted-frame and useful
   coverage minimums: rejecting every frame must not pass an identity gate.
2. **Layer support:** two neighboring front-depth candidates are observed
   alternatives, not an acquired hidden layer along each ray. Every second
   candidate needs measured depth AND color support in a source view. No
   algorithm can recover unseen detail solely by allocating another buffer.
3. **UV precision:** RG16F absolute normalized UV has a step of 0.00048828125
   in [0.5,1), causing up to 0.767578125-pixel rounding error at width 3144.
   This conflicts with the proposed 0.1-pixel coordinate target. Use FP32 or
   packed UNORM16 coordinates (maximum ~0.024 pixel rounding at that width),
   subject to full mapping/filtering precision tests.
4. **Atomic ownership:** selecting depth with `InterlockedMin` does not also
   select the correct source UV/confidence. Select a deterministic sample key
   atomically, then resolve that sample's attributes, or use a controlled
   per-pixel candidate gather. Prevent losing threads from writing attributes.
5. **Depth clustering:** sending every candidate outside cluster 0 into
   cluster 1 can merge multiple unrelated surfaces. Define a second seed,
   tolerance, ordering/tie rules and rejection for extra unresolved surfaces.
6. **History:** source kind/owner is not a stable surface ID. Validate motion,
   depth, current visibility, resets and crop changes before retaining history.
7. **Budgets:** timing, memory and quality percentages in the report are
   provisional targets. Account for actual per-eye regions and in-flight
   storage, then measure on RTX 5070. Do not present estimates as results.

The Markdown export contains citation tokens but no literal source URLs or
bibliography. Retrieve the original linked citations before relying on its
external technical claims or assessing implementation/license suitability.

## Findings from our separate code audit

CI73 owner masks omitted the RIGHT-depth jitter used by reconstruction and
used a shifted 2x2 edge footprint. CI74 corrects those inconsistencies while
keeping b0 at 240 bytes and preserving crop/baseline/DLSS sampling behavior.
Focused Windows run 41036935417 executed actual production mask functions:
72,160 mismatches / 663,552 checks before; zero after. This is mask alignment,
not an overall stereo quality score. Production Guide/SurfaceGeometry passed
38,400 coordinate checks under a declared raster-displacement convention.

The available latest capture report contains two JPEG output previews, no raw
device depth, no authenticated per-view matrices/jitter and no temporal trace.
It cannot establish the game's input association or runtime jitter convention.
That remaining evidence gap should be addressed by the capture/replay work;
it does not justify ignoring the concrete, reproduced shader defects.

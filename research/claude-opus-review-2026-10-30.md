# Independent review and CI78 decision (Claude Opus, 30 Oct 2026)

Labels: [source] = read in the assembled real code; [CI] = Actions run green;
[capture] = measured from Liviu's CI75 recording (ChatGPT's analysis, one
contact sheet re-checked by me); [headset] = Liviu saw it in VR.

## Root cause of the RIGHT-fovea shimmer

- The RIGHT eye's centre was, per pixel, either warped sharp LEFT colour or the
  RIGHT camera's own colour, which is ~5x blurrier (RIGHT 812x646, LEFT crop
  2030x1614, output 4060x3228 per eye) [capture].
- The choice was a chain of yes/no tests on DLSS input depth: triangle dropped
  when depth spread > 2 cm + 2.5% (DuoViewSurfaceD3D12.hpp edge defaults),
  RIGHT-depth occlusion veto, 0.995 alpha threshold, 80 cm near-field veto,
  exclusive owner since CI76 [source].
- DLSS input depth is one jittered, aliased sample per pixel. Thin geometry
  appears and disappears with the jitter phase, while the colour images are
  DLSS-accumulated and stable. So the tests flip every frame on grass, leaves,
  wires: synthetic RIGHT fovea coverage 80.9–83.5%, ~12% of its mask changing
  between neighbouring frames [capture]; blocky holes along silhouettes and in
  vegetation, different each frame (synthetic_right_contact.png) [capture].
- Jitter sign/offset is correct (registration fit ~1.0 px per jitter px)
  [capture], so this is not a coordinate bug.
- CI77 cannot fix it: its temporal history is rejected whenever the depth
  differs by more than the tolerance, i.e. exactly at depth edges, and its
  spatial resample cannot restore a blade missing from this frame's samples
  (DuoViewDepthStabilization.hlsl TemporalBlend/StabilizeSpatial) [source].

## 1. Architecture

Keep the two-camera split (LEFT gaze crop + RIGHT full field at low resolution).
Under the two-render limit it is the right shape: each eye owns one real image,
real baseline, cost near mono. What was wrong is the fusion in the RIGHT fovea.

- Mono + depth-made stereo: both eyes synthetic everywhere. Worse. Rejected.
- Third native view (a RIGHT fovea crop): best possible fovea, but a full extra
  UE5 view (Lumen, shadows, CPU); the native quad builds showed bad CPU and
  per-view shading differences. Plan C only if CI78-style fusion fails.
- Native stereo with cheaper periphery: needs engine-level VRS/foveation that
  UEVR hooks do not give us. Rejected for now.
- Real RIGHT base + LEFT detail (brief's Plan B): adopted as CI78.

## 2. What went wrong in CI71–CI77 (evidence, not tone)

1. A temporal-stability problem was treated as a per-frame correctness problem.
   Every layer added yes/no gates that "fail closed" to the blurry RIGHT image;
   each gate is one more sharp/blurry switch, which is the shimmer [source,capture].
2. The choice was framed as "blend two images (ghosting) or pick one" (CI76
   made picking strictly exclusive). Splitting by frequency (low = RIGHT,
   detail = LEFT) avoids both and was never tried [source].
3. CI77 smooths depth on flat surfaces, where it never mattered; the failure is
   at edges, where its history is rejected by design [source]. The request
   "stabilize depth first" was implemented without testing the hypothesis.
4. Process cost: whole-file fingerprints (CI77 broke twice on CI75's commit
   stamp), base64/lzma payloads, snapshots, policy-pinning WARP tests, dead code
   kept selectable (CI73StableComposite is never called; strategy bits
   1/2/4/8/16/32). Nobody could read the running code [source].
5. Fair credit: NGX depth capture and manual pinning made real stereo possible;
   CI74 fixed a real mask-coordinate bug [CI]; CI75's recorder produced the
   measurements that confirm this diagnosis [capture].

## 3. Refactor

Yes, in two steps.
- Done now: `tools/assemble_source.py` replays the whole stack locally (public
  UEVR + frontend, no SDK, no Windows) with every layer's own fingerprint checks
  passing, and `assembled_source/` keeps the result readable: DuoView's own files
  in full, changes to Joey's files as diffs.
- Next task (its own build, not mixed with an algorithm change): build CI from
  `assembled_source/` directly (copy `new/`, `git apply changed/*.diff` on the
  pinned UEVR) and retire the ci48–ci78 apply chain and its intermediate-state
  tests. A change then becomes a normal edit. After CI78 is judged in the
  headset, delete the losing strategies (CI71/72/73 paths, CI77 LEFT mesh).

## 4. CI78 (this branch)

RIGHT fovea = real RIGHT image + confidence x (LEFT − LEFT blurred to RIGHT
size). A prepass box-averages the LEFT crop onto the RIGHT pixel grid (the same
blur the RIGHT image has). RIGHT depth proposes up to three sources (middle,
nearest, farthest surface in one depth texel); each is weighted by how well the
zero-mean 5-point structure of blurred LEFT matches the real RIGHT image. No
hard switch, no LEFT-depth dependence, outlines always from the RIGHT camera,
detail faded across the feather. Toggle (default ON, shown under CI77
stabilization); OFF = CI77 exactly. See ci78/README.md for the headset question.

If shimmer remains with CI78 ON, the next step is a short reprojected history
on this single output (TAA-style, clamped to the RIGHT neighbourhood), not more
depth rules.

## 5. Update after the first headset tests (31 Oct, 00:35–00:46)

Headset-verified (Liviu): CI78 steadier with less shimmer than CI77, but worse
colours/shading and strong rivalry; CI77 temporal ON slightly better than OFF;
CI77b footprints help grass a little, everything else still shimmers, and the
temporal depth weight/toggle shows no visible effect. LEFT outer view: wrong
field of view, hands superimposed, two hands. Periphery > 0.2: artefacts;
0.499: black outer view.

Conclusions:
- Removing yes/no switching works (CI78 steadier). Keep that principle.
- My CI78 assumption that both cameras render the same low-frequency colour and
  shading was wrong: the ~0.2-scale full-view render looks visibly different.
  The RIGHT fovea must show LEFT shading. Liviu's instinct was right there.
- The "temporal does nothing" report matches the source: depth history is
  rejected exactly at edges, where the shimmer is. Depth-only filtering cannot
  calm moving edges without blending foreground and background.
- New source-read finding: in every surface mode the LEFT outer view fell back
  to the RIGHT image at the SAME screen position (SurfaceComposite), ignoring
  the mirrored frustums and the 6-7 cm parallax. About 40% of the recorded LEFT
  outer region used that fallback (CI75). That explains the wrong field of view
  and the doubled hands.

CI79 (claude/ci79-left-shading-stable, built on ChatGPT's CI77b, bit 128 so it
does not collide with CI77b's footprint bit 64):
1. RIGHT fovea = lerp(RIGHT colour-matched to LEFT, LEFT colour, confidence);
   proposals from RIGHT depth, smooth colour-agreement weights over 3x3 RIGHT
   texels, LEFT favoured.
2. LEFT outer fallback = RIGHT image at the position found by a row search on
   RIGHT depth (nearest consistent surface; background when none), blended with
   the reconstructed pixels by coverage.
Periphery resolution > 0.2 / black at 0.499: cause not found in the code; needs
Liviu's log.txt after reproducing.

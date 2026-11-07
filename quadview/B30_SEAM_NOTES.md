# Prepared seam-matching work — deferred for anti-vignette-first testing

Status: source checkpoint, not a completed or Windows-validated build.
The user chose to test fovea brightness compensation alone first. This combined
matcher is retained separately for a later integration; the independent focus
lift additions need a fresh full replay before this checkpoint is built.

# TriView B30 draft — current-frame appearance matching

Date: 2026-11-07. Parent: B29 `9fb0702b549d1710de573d302104dcd995cf1c7b`.
Tested lifecycle baseline retained: B28-103 `3ebe512c830a8e7467717d85d1cd0b7f52c5e4ba`.
Branch: `experiment/triview-b30-seam-matching-20261107`.

## Objective and updated evidence

Reduce the fovea/periphery boundary without blurring the opaque fovea, adding a
view/DLSS operation, changing camera/target sizing, or weakening B28 retirement.
This is an opt-in seam implementation, not a claim of an invisible boundary.

User supplied six initial screenshots, including NR off/on pairs. Bright gray
sky in image 5 showed sampled RGB146 in the focus center/nearby periphery and
roughly RGB130–136 near focus corners. That proves a spatial difference in
those sampled pixels, but equal bright sky does not rule out an overall exposure
difference elsewhere. The user then established that the game vignette setting
was already OFF; enabling it made the effect worse. A later darker-sky image
showed a broader brightness discrepancy. DuoView Mono screenshots showed a
similar crop-shaped effect too, so it predates TriView and is not uniquely
explained by TriView's extra eye or custom lifecycle. Source-side exposure,
post-processing, rendering dimensions and inherited paths remain candidates.

Do not describe this as a confirmed game-vignette defect, require the user to
switch an already-disabled setting off again, or assume this build removes a
source-side effect. The new matcher measures appearance differences directly.
No user screenshots are published in the repository.

## Implemented behavior

- **Off (default):** original B29 composition/feather. No analysis dispatch or
  matching buffer reads in the executed shader path. Extra bounded resources
  are created during ordinary slot prewarming, not per frame.
- **Manual:** peripheral sample-domain exposure bias. Foveal colors and details
  are unchanged. Approximate EV conversion for encoded UNORM is computed once
  on CPU; no per-output-pixel gamma conversions are introduced.
- **Adaptive:** one two-group compute dispatch (128 lanes per eye) compares
  corresponding current-frame image patches near the crop boundary, writes a
  global gain and eight local boundary gains per eye, then the same command
  list draws the stereo composite. No CPU statistics readback or image history.
- Each analysis point averages four small samples in each view to reduce the
  detail/bandwidth difference in the measurement only. Displayed focus samples
  retain the existing sharpening and are never analyzed by blurring output.
- Context analysis uses the actual compositor homography and four-sample depth
  warp. Out-of-bounds, disocclusion-fill, near-black, clipped/highlight,
  high-gradient and broad luminance-outlier patches are rejected. A requested
  but unavailable/invalid depth warp yields neutral automatic statistics.
- A global per-eye periphery correction provides a consistent far-periphery
  base. Eight local corrections are smoothly interpolated around the boundary;
  their residual relative to the base fades outward with a smoothstep radius.
  There is no abrupt transition back to uncorrected pixels and no side-selection
  discontinuity at corners. Weak local estimates fall back to the global gain.
- Automatic gains are bounded by the configured relative cap. Luminance-only
  and color matching interpolate through `Color matching`. Low sample confidence
  reduces automatic correction toward neutral, retaining any manual bias.
- Current-frame, stateless fitting intentionally avoids cross-world/gaze/XR
  history. It does not claim temporal tint stability until headset testing.

## Transition and UI semantics

Controls are saved beside the existing QuadView controls in Advanced Seam
Matching, copied into requested settings and frozen with the source packet.
Mode defaults Off; suggested test settings are Adaptive, strength .85, gain cap
.20, color .5, local residual .5, radius120 outputpx, bias0, transition0.

When matching is enabled, transition0 uses the full rendered focus at full
weight. The legacy inward feather is bypassed in that mode. Positive transition
pixels reserve the outer part of the EXISTING rendered focus crop for a smooth
image blend, reducing the fully sharp interior. This is explicitly labeled in
UI; it is not an extra outward guard, does not create additional valid pixels,
and does not preserve the old sharp-interior dimensions at nonzero width.

No geometry, camera, projection, target sizing, view count or source lifetime
changes are included. True extra outward coverage remains separate work.
Existing layout/focus/context/depth diagnostics bypass automatic appearance
matching; optional adaptive confidence colors only peripheral output.

## GPU layout, ordering and cost

- C++/HLSL/mirrored test constants are448 bytes in the existing512-byte CB.
- SRV table has6 entries: colors t0–t3, depth t4, structured seam statistics t5.
  The slot-local shader-visible heap has7 descriptors, adding UAV u0 at index6.
- Statistics contain18 float4 records: per eye1 global +8 local,288 data bytes.
  D3D12 committed-buffer allocation granularity exceeds the payload; allocation
  remains bounded to existing compositor slots, with no per-frame allocation.
- Source transitions use ALL_SHADER_RESOURCE during analysis; depth already
  uses its existing ALL_SHADER_RESOURCE contract. A stats UAV-to-PIXEL transition
  orders dispatch writes before sampling. Source states are restored before
  snapshot handling and then restored to the caller's original state.
- Each Compositor stays owned by its existing fence-retired command slot.
  Prewarm still refuses an in-flight owner; no waiting or retirement rules change.
- Local output lookup work is restricted to the configurable boundary region.
  Far periphery uses only the global gain; opaque focus avoids context/matching.
- Existing opt-in GPU timing now measures total analysis+composite; an additional
  timestamp exposes the retired analysis interval separately in the UI. Query
  readback happens only through the existing completed-slot timing path.

Target incremental overhead remains<=1ms on the actual RTX5070/output resolution.
No measured hardware cost is available before user testing. Do not equate the
small analysis dispatch with the full cost: periphery correction/local lookup
work must be included in same-scene Off/On total-compositor comparisons.

## Verification

Local portable checks:32 applicable executable tests passed, including settings,
existing geometry/ownership, head scaling and both real ImGui panel tests. The
new settings test passed ASan/UBSan with leak detection disabled for this host.
The portable runner also attempted the new Windows-only GPU test and correctly
could not find windows.h; this is excluded from the portable pass count.

Full overlay materialization and staged source tests pass, including B28 safety,
B29 axes/depth housekeeping, final B30 control/descriptor/order checks and exact
protected B23 depth/B29 sampling/sharpening/output functions. A fresh Luna static
review found no concrete blocker in the compute reduction, barriers, slot
ownership, constants layout or timestamp ordering. Source validation does not
substitute for shader compilation or driver/runtime validation.

Windows CI must compile VS/PS/CS with FXC SM5 /WX, build the full restricted-SDK
backend, run existing WARP pixel/depth tests and the new production-compositor
WARP cases. New GPU cases cover Off identity, manual bias, unchanged focus,
independent eye gains, confidence rejection, spatially varying boundary fit,
uniform local neutrality, repeated draws and optional transition behavior.
D3D12 debug-layer errors are fatal when the debug layer is available.

Remaining limitations: no exact NGX depth/color frame provenance, no guaranteed
recovery of source-side shading differences, no full temporal smoothing,
no claim that spatial correction erases the actual vignette-shaped pattern
inside the fovea, no PSVR2 image-quality or performance certification.

## Headset test

1. Same scene/settings: Off versus Adaptive, first with transition0. Compare
   boundary brightness, then detail. Verify focus center/detail is unchanged.
2. Try day/night sky, walls, vegetation and a weapon crossing the edge. Move
   head/gaze; check tint pumping, corner discontinuities, halos or double edges.
3. If needed vary local strength/radius. Optional transition8/16 pixels trades
   existing edge area for continuity; it is not required for color matching.
4. Toggle GPU timing and compare the TOTAL compositor cost, then analysis time.
   Do not attribute whole-game FPS changes between different scenes to this patch.
5. Repeat a short resize/save-load/runtime smoke test and retain B28-103.

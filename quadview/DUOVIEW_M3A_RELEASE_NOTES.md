# DuoView M3a combined build (lead build)

Base: M2.5a #248 (`88e65e5`) = M2.4 + world trace #21 + M2.5a content-checked fine depth.

**Every new setting defaults OFF. With defaults, the output equals #248.**

## New settings (DuoView → synthetic stereo)

- **M3a per-eye edges** (`DuoM3PerEyeEdges`, OFF):
  - each eye gets its own conditioned depth;
  - the occlusion side of a near object is bounded only as much as needed to keep the warp from folding;
  - the other side stays a sharp step.
  - This removes the sideways depth bands (the "lines" from the weapon top).
- **Occlusion edge sharpness** (`DuoM3OcclusionSharpness`, 0.95; 0.98 = crispest).
- **Fill revealed background** (`DuoM3BackgroundFill`, ON). Where an eye sees background the centre camera never saw, nearby background is mirrored in, instead of stretching the edge texel across the gap. OFF keeps a soft membrane on that side, using the old edge-sharpness slider.
- **Depth jitter alignment** (`DuoM3JitterMode`: Legacy / + / −). DLSS jitters the depth every frame. Try + and −: one should visibly reduce edge flicker, the other increase it.

## Other changes

- **M2.5a review fixes:**
  - the content-gate summary pass runs on 256 GPU threads instead of 1;
  - the 4-way depth debug selector has its own key (`DuoM25DepthDebug`), so old saves load cleanly;
  - the gate and the fusion share one sampling helper.
- **Menu:** the stereo section holds only depth-geometry controls. Per-eye sharpening and distance-faded sharpening moved next to the other sharpening controls. Behaviour is unchanged.
- **Contract C2 v1 producer:** `UEVRBackend.dll` exports `UEVR_GetSourceRolesV1`, which tells Cheeky which DLSS source is fovea or periphery. It has no effect until Cheeky uses it.

## Tests

- Numeric model: exact asymmetric envelope, no folds, both eyes, fill lands on background.
- Generated-source contracts.
- WARP:
  - M2.5a accepts matching fine depth and rejects a wrong frame, leaving the image unchanged;
  - M3a with no edges = OFF;
  - M3a changes a depth step;
  - jitter switch neutral at zero jitter;
  - C2 table.

**Not headset-tested.**

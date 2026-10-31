# Joey classic single-view DIBR comparison

## Implementation

`apply.py <prepared-backend-root>` adds a default-off toggle inside existing rendering method ID 4. ID 4 continues to use Joey's guarded full-FOV, one-source-view construction and readiness/warmup transition. The new toggle changes only the reconstruction: it disables the projection-matrix path and forces the classic depth response settings (`curve = 1`, `near cap = 1`), while gating off depth-edge stabilization, spatial repair, UI-footprint reprojection, and UI-alpha edge guards. The existing disparity slider remains available.

This selects the original classic disparity branch already present in Joey's pinned shader; it does not introduce a fabricated shader or rendering-method ID. Method 3, all other modes, and method 4 with the toggle off retain their existing behavior. The patch also registers the toggle as a persisted setting and scopes its UI to method 4.

## Provenance

- Joey backend pin: `joeyhodge/UEVR` commit `5ac7edc207866569334175e4ed8a7517971547f6`.
- Joey's initial DIBR shader implementation is commit `55410de1` (“Add opt-in DIBR reprojection and nonblocking ring”). Its classic path computes `near_depth = reversed ? raw_depth : 1 - raw_depth`, multiplies the saturated depth response by `DisparityPixels` and an edge feather, divides by source-eye width, then samples `target_u + disparity_uv` for the synthesized eye.
- The later pinned shader retains this branch as `LegacyDepthResponse` and `ResolveSyntheticRightSourceUv`. With cap and curve fixed to 1, `LegacyDepthResponse` reduces exactly to the initial saturated near-depth response. The patch checks that these shader anchors exist before editing.
- Joey's single-view construction was introduced in commit `afca4644` (“Enable UE4 DIBR single-view baseline”). Existing ID 4 remains the construction selector; this toggle compares classic reconstruction within that actual path.

## Application and limits

The patch script is intended for the exact Joey backend after the DIBR overlay has made `DIBRPreview.cpp` available. The isolated script was applied to a local checkout of the pinned public backend without errors. The full stock DIBR overlay script did not apply to that clean checkout because its current source anchor has diverged; the working CI workflow applies additional ordered overlays. The parent should run the selector stage after its prepared baseline and combined edits.

No Windows build, GPU test, or headset run was performed for this isolated patch. This remains a source-level comparison control until the combined CI and runtime checks complete.

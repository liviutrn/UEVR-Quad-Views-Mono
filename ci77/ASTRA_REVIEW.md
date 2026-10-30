# CI77 Astra review

Recommendation: enable bounded pixel footprints by default in the experimental build, conditional on the actual-production-shader GPU fixture passing; retain the triangle toggle for in-game A/B.

## Ranked remaining mechanisms

1. **Missing source topology, then unstable fallback ownership.** VSSurface rejects a triangle whenever its vertex depths cross 2 cm + 2.5% of nearest Z. A one-pixel vertical/horizontal foreground cannot form any triangle with three foreground vertices. Stabilizing depth values cannot supply that missing geometry. SurfaceComposite then changes between projected color and actual RIGHT color at coverage 0.995. In LEFT periphery this also changes physical viewpoint. In RIGHT fovea it changes source resolution/shading. Both match the two reported synthetic regions.
2. **Source phase/temporal class ownership.** CI77's canonical depth resampling and bounded current-supported foreground hysteresis directly address jittered depth boundaries. They do not make arbitrary moving vegetation or newly visible geometry constant. Spatial surface selection remains discrete; depth-only temporal validation cannot perfectly distinguish moving objects at similar depth.
3. **True disocclusions and source color/depth disagreement.** RIGHT color fallback is physically correct for RIGHT output but has the wrong camera for LEFT output. Neither topology nor depth smoothing can recover LEFT color never rendered. DLSS output color and raw input depth have different temporal/sampling behavior. Recorded camera/depth identity remains unauthenticated.

## Captured-data evidence

`measure_topology.py` decodes the six full RIGHT depth planes in the user's CI76 capture, uses its reciprocal projection, and reproduces production triangle depth rejection. Excluding image borders, 18.18–18.24% of valid measured depth pixels (~62,100–62,424 per frame) have no incident accepted triangle. These are raw CI76 input maps, not CI77 stabilized maps. This measures source connectivity only, not final screen coverage, visual quality, or causal jitter. The weaker threshold 5 cm + 5% still disconnects approximately 11.5%.

## Proposed implementation

`DuoViewSurfaceReproject.hlsl` adds flag64: one measured pixel footprint quad spanning exactly ±0.5 source pixels around each valid depth sample. Each corner uses the measured center device depth and actual source-to-target camera matrices. Hardware depth competition, projective source color, range rejection, and target visibility are retained. No fabricated middle-depth surfaces connect unrelated objects. Host dimensions become active columns+1 / rows+1, matching existing `(x−1)*(y−1)*6` draw count and including final row/column.

Flag32 remains the CI77 stabilized semantics. Flag64 is only enabled inside that path. Mesh A/B remains unchanged.

## Bounds and failure modes

- Footprints represent measured pixel support, not enlarged hand/vegetation geometry. An isolated valid pixel survives without requiring three adjacent equal-depth samples.
- Number of vertices is essentially unchanged: six per source pixel instead of six per source cell. Per-vertex depth/unprojection work is lower than the three-corner mesh path. Actual GPU timing still required; full LEFT map remains roughly twenty million vertices.
- Constant device depth per footprint approximates steep smooth slopes with steps. Under camera rotation or disparity this can leave subpixel cracks or overlaps. Hardware Z resolves overlap; source data cannot guarantee hole-free output.
- Subpixel thin detail not sampled in source depth cannot be reconstructed. Hard target raster coverage still aliases; this is not target-color TAA.
- Target all-four nearer consensus protects proven target occlusion; mixed low-resolution footprints intentionally cannot erase a high-resolution LEFT object.
- Complete native LEFT crop ownership and removing wrong-camera RIGHT near-hand override address deterministic hand seam mechanisms. Disoccluded LEFT peripheral pixels can still use RIGHT fallback and remain misaligned. No claim that all hands or all flicker are fixed is justified without headset testing.

# B39 — ambient area matching instead of B37 pixel mirroring

## User request
The B37 V2 temporal mode rate-limits a broad correction, but the immediate per-output-pixel edge probe cancels history at the border. An isolated bright highlight can therefore flash onto the nearby periphery. The desired result is an ambilight-like low-frequency color field, not a mirror of individual edge pixels. Original B27 inward fovea feather from B38 remains.

## Architecture
B39 is based directly on experimental B38 source commit `d043d5ec009e7290a0e0770615a462fd505e2b4b` (B38-129 failed an overly strict static name check before compilation; B39 repairs that test). B37-128 is still the last headset-tested baseline in this lineage.

Add a separate **Edge V3 Ambient Temporal** mode (mode 5) alongside B31, B37 V2 Instant, and B37 V2 Temporal. No changes to B37 algorithms when those older modes are selected.

- 32 evenly distributed perimeter control points per eye. Each point averages a 5-tangential x 3-inward grid = **15 RGB differences** between the actual post-sharpen/anti-vignette focus and matching warped periphery (at inward depths 25%, 62.5%, and 100% of selected reach).
- The default grid spans 48 output pixels along each edge and 32 pixels inward. It excludes invalid/out-of-view depth correspondences, requiring at least 8/15 accepted samples. Small bright spots cannot dominate an entire correction point.
- Across frames, each pooled residual enters a genuine time-weighted average (350ms default), then the inherited rate limiter/hysteresis. No current-frame per-pixel RGB difference bypasses this smoothing. A current-frame bright spot therefore cannot be instantly reflected on exterior pixels.
- The displayed outside correction interpolates only the smoothed control points, fading out over the existing 240px reach. The immediate reach slider is irrelevant in V3, but V2 remains unchanged. At the exact crop boundary the same corrected context passes into B38's 12px inward continuity strip, followed by original B27 soft feather.
- Reset safety: retains B37 queue-pinned history, epoch and source/crop/scene validity gates. Settings changes reset state. No new texture/VRAM allocations, command queues, GPU readbacks, producer passes, or synchronization.
- Mode V3 adds 15 samples * 32 knots * 2 eyes = 960 comparison points per composited frame, in existing GPU seam-analysis dispatch. It removes the costly B37 live per-pixel border probes. Actual RTX timing not established until measured.

## Controls
- Edge matcher: `Edge V3 Ambient Temporal` (default for a clean profile; existing saved B37 mode may remain until manually changed).
- Ambient width along edge: 48px default, 8-128px.
- Ambient sampling inward: 32px default, 8-96px.
- Ambient temporal average: 350ms default, 50-1500ms. Higher = steadier, slower response.
- Existing rate/hysteresis/outer reach and edge strength apply.
- Original inward fovea feather: ON, existing context/focus feather recommended 0.08-0.12, continuity strip 12px.
- Switch to Edge V2 Temporal to compare B37's precise but potentially flashing border-mirror logic.

## Validation and limitations
Source tests assert unchanged B38 inward feather, same native view/depth/queue lifecycles, no new memory, and retained B37 old mode. Production D3D12 WARP compares the original instantaneous flash to V3 with an identical tiny highlight, tests gradual response to sustained broad illumination changes, and checks V3 zero-strength neutrality. Run all previous WARP, backend/frontend and portable tests before delivery.

Spatial smoothing trades one-pixel exact correspondence for stable ambient color. Disocclusion/parallax, strong full-boundary flashes, post-NR content changes, and insufficient depth still require headset evaluation. CI success alone does not guarantee the seam becomes invisible.

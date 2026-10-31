# CI80 — submitted-frame depth history and classic DIBR comparison

Based on CI77b build116; keeps its color/shading and LEFT primary geometry.

- Temporal history follows the immediately preceding successfully submitted frame across XR image slots, with one-queue ordering and independent LEFT/RIGHT transforms. Unnecessary exact-projection/frame-gap vetoes are removed; dimension/identity/age and surface checks remain.
- Live menu and log show the actual sparse GPU acceptance count, applied weight, history frame, and rejection reason. Sample frame is labeled because fenced readbacks arrive later.
- Bounded foreground retention also handles sky, requiring current-frame foreground support and valid reprojection. This is not a freeze-depth mode.
- **Mono foreground guard (hands)** defaults ON. It replaces the union of both current near-hand silhouettes with current RIGHT-camera imagery in both eyes and suppresses displaced near geometry. This sacrifices local hand stereo/sharpness; OFF restores reconstructed near geometry.
- **Joey Classic Single-View DIBR** is available inside rendering method4. It uses Joey's existing classic depth-scaled disparity branch, curve/cap1, bypassing later projection reprojection and repairs. See JOEY_CLASSIC_PROVENANCE.md. Full-FOV one-source construction and existing readiness controls remain.
- Native source sampling continues to use the real active viewport within the larger allocation. Sampling unused padding is not a resize fix. Dimension changes reset incompatible temporal history. Game resize recovery remains an in-headset acceptance item.

Start with Mode5, depth stabilization and temporal ON, weight75%, thin geometryON. Compare weight0/75 while observing the live counters. The processed depth preview is the same guide reconstruction reads. Test the hand guard ON/OFF separately. Joey comparison: choose rendering method4, then enable its classic toggle; disparity remains configurable.

No claim of zero remaining shimmer, native-stereo equivalence, complete resize repair, or measured headset performance is made from compilation/GPU fixtures alone.

# CI77b — stabilized depth and measured pixel footprints

Experimental successor to CI76 build106. This build prioritizes stable depth guides and high-resolution LEFT geometry, with direct raw/processed visual comparison. A Windows build and GPU tests do not certify headset quality.

## Controls

Stereo and quality → Advanced stereo and capture diagnostics:

- **CI77: Stabilize depth before reconstruction / preview** (default ON). OFF restores raw guides and legacy A/B reconstruction choices.
- **CI77b: Preserve thin geometry (pixel footprints)** (default ON). Represents each measured depth pixel by its half-pixel footprint so isolated stems survive. OFF selects the old connected triangles for comparison.
- **Temporal depth stabilization (camera reprojection)** (default ON). OFF retains phase correction on each current frame.
- **Depth history weight (%)**: default75, range0–90. Larger weights retain more compatible history. This controls depth, not a blend of displaced eye images.
- **Display pinned DLSS depth**: LEFT, RIGHT or both. It samples the same processed textures used by stereo when stabilization is ON; RAW textures when OFF. Both NGX guides must be pinned for stabilized viewing.

For visual verification stand still near a static high-contrast boundary, then move/rotate normally and check for depth trails. The map must follow real camera/object motion; a frozen map is not valid stabilization. Compare stabilization OFF, ON with temporal OFF, and ON with temporal ON without changing the scene.

## Reconstruction changes

With stabilization ON, right-foveal geometry is projected from full-resolution LEFT depth. The old coarse RIGHT inverse gather is bypassed even if its legacy strategy toggle remains checked. RIGHT depth only conservatively tests visibility; mixed coarse foreground/background footprints do not independently veto sharp LEFT geometry. Foveal and full-FOV guide histories remain separate.

The optional pixel-footprint topology avoids discarding isolated measured foreground pixels merely because adjacent pixels belong to the background. It keeps real camera transforms and hardware depth competition; it does not invent invisible source color. See `ASTRA_REVIEW.md` for capture measurements and limitations.

The entire available native LEFT crop is retained up to its boundary. LEFT peripheral near geometry is no longer deliberately replaced with the RIGHT-camera hand. Actual disocclusions still have limited source data and require fallback.

## Recording

The existing recorder keeps its complete sequence and20MiB ZIP part scheme. Captures add lossless `depth_stable_left` / `depth_stable_right` planes alongside original raw depths when stabilization produces output. Metadata distinguishes requested and actually recorded stabilization. Upload all parts plus index and log.

## Scope

The source game's DLSS sequence remains intact; stabilization removes its phase from our reconstruction guides. Camera-reprojected history rejects inconsistent surfaces and stale sources; moving gaze uses the correct prior foveal crop. Bounded foreground edge retention requires both current and prior support and never averages foreground with background. Temporal influence fades out below 200cm and is disabled at/below 80cm to reduce hand-motion lag. Dynamic geometry and previously unseen surfaces cannot be made correct by holding an old depth map. No claim of zero remaining headset jitter, native-stereo equivalence or measured RTX5070 cost is made before in-game validation.

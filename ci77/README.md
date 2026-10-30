# CI77 — depth stabilization before reconstruction

Experimental successor to CI76 build106. This build prioritizes stable depth guides and high-resolution LEFT geometry, with direct raw/processed visual comparison. A Windows build and GPU tests do not certify headset quality.

## Controls

Stereo and quality → Advanced stereo and capture diagnostics:

- **CI77: Stabilize depth before reconstruction / preview** (default ON). OFF restores raw guides and legacy A/B reconstruction choices.
- **Temporal depth stabilization (camera reprojection)** (default ON). OFF retains phase correction on each current frame.
- **Depth history weight (%)**: default75, range0–90. Larger weights retain more compatible history. This controls depth, not a blend of displaced eye images.
- **Display pinned DLSS depth**: LEFT, RIGHT or both. It samples the same processed textures used by stereo when stabilization is ON; RAW textures when OFF. Both NGX guides must be pinned for stabilized viewing.

For visual verification stand still near a static high-contrast boundary, then move/rotate normally and check for depth trails. The map must follow real camera/object motion; a frozen map is not valid stabilization. Compare stabilization OFF, ON with temporal OFF, and ON with temporal ON without changing the scene.

## Reconstruction changes

With stabilization ON, right-foveal geometry is projected from full-resolution LEFT depth. The old coarse RIGHT inverse gather is bypassed even if its legacy strategy toggle remains checked. RIGHT depth only conservatively tests visibility; mixed coarse foreground/background footprints do not independently veto sharp LEFT geometry. Foveal and full-FOV guide histories remain separate.

The entire available native LEFT crop is retained up to its boundary. LEFT peripheral near geometry is no longer deliberately replaced with the RIGHT-camera hand. Actual disocclusions still have limited source data and require fallback.

## Recording

The existing recorder keeps its complete sequence and20MiB ZIP part scheme. Captures add lossless `depth_stable_left` / `depth_stable_right` planes alongside original raw depths when stabilization produces output. Metadata distinguishes requested and actually recorded stabilization. Upload all parts plus index and log.

## Scope

The source game's DLSS sequence remains intact; stabilization removes its phase from our reconstruction guides. Camera-reprojected history must reject inconsistent surfaces and reset when sources/layouts change. Dynamic geometry and previously unseen surfaces cannot be made correct by holding an old depth map. No claim of zero remaining headset jitter, native-stereo equivalence or measured RTX5070 cost is made before in-game validation.

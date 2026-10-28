# Source-depth stereo surfaces

Modes 4/5 are a live rendering replacement, separate from the old experimental
shader and the standalone compute prototypes. They retain the two existing UE
scene renders: LEFT cropped fovea and RIGHT low-resolution full field.

For the RIGHT fovea, source LEFT depth defines continuous surface triangles.
The renderer unprojects them through the cropped source projection, applies
the full relative camera transform, projects into the cropped RIGHT output,
and depth-tests competing surfaces in target space. Triangles crossing a depth
discontinuity are discarded. The pixel shader uses projective source texture
coordinates, retaining full source color resolution and the existing foveal
sharpening. It does not snap color to depth texel centers.

Coarse real RIGHT depth supplies a conservative occlusion veto. Only a full
2x2 footprint of nearer target surfaces vetoes a source sample. Mixed
foreground/background target footprints do not erase fine source geometry.
Unavailable samples fall back to actual RIGHT color. This addresses a key
limitation of making every foveal sample depend on low-resolution target depth
and strict source-neighbor agreement.

Mode 5 also projects the RIGHT RGBD surface into LEFT peripheral space. Its
target z-buffer resolves visible source surfaces; it does not invent surfaces
hidden from the RIGHT source. Such uncovered pixels use unwarped RIGHT color.
No full-field LEFT target depth is assumed from a cropped LEFT resource.

Camera transforms use signed 3D position differences and both rotations,
including vertical separation and relative eye tilt. Positions remain double
until the relative transform is built. UE +X/+Y/+Z axes are converted to
projection-space right/up/forward. Cropped and full target projections remain
distinct. Separate forward/reversed depth PSOs resolve visibility correctly.

## Modes and evidence

| Mode | Behavior |
| --- | --- |
| 0 | Existing V3 mono; no surface maps allocated |
| 1/2/3 | Legacy horizontal reconstruction, tint, fovea-only A/B |
| 4 | Source-depth RIGHT fovea; identical RIGHT periphery in both eyes |
| 5 | Source-depth RIGHT fovea and LEFT periphery |
| 6 | Coverage visualization for mode 5 |

The new modes select fresh owned current-interval copies immediately, bypassing
the old three-consecutive-pointer-key gate. GPU completion cannot release
unread copies. Previewed copies remain discoverable by that same capture
consumer until retirement. No stale prior-interval depth is admitted.

Manual captures include the two reconstructed maps, alpha coverage, exact
coverage counts in the manifest, and per-slot eligibility flags. Alpha 255
means a geometric surface reached the target pixel; it is not proof of Unreal
source identity. The total GPU timing includes both surface passes and the
final composite. Runtime cost and comfort require target hardware testing.

## Verification and remaining limits

The GPU fixture runs the actual compositor and shader with independently
derived ray/plane/color expectations across near/mid/far planes, physical
baseline signs, vertical separation, camera tilt, sloped surfaces, independent
near planes, padded active rectangles, forward/reversed depth, target
occluders, and a foreground/background disocclusion. Legacy and mode 0 tests
remain mandatory. The capture fixture first reproduces the previous overwrite
on the actual old implementation, then requires the corrected schedule to pass.

The live matrices are the frozen UE camera/projection callback outputs,
including the foveal crop. Actual DSV eye/frame/pass attribution and TAA/DLSS
sample registration are still not authenticated by an engine producer hook.
Do not populate the separate provenance contract's authenticated fields from
these heuristics. A source lifetime repair is not source-stage proof.

Depth resolution still limits silhouettes and thin geometry. Screen effects,
transparency, temporal upscaling and independent view shading can disagree
with opaque depth. First activation or a layout change creates resources once
per retired XR slot, so an initial hitch is possible. There is no measured GPU
performance or headset acceptance claim until it is tested in the actual game.

# DuoView experimental stereo headset candidate

This branch preserves the V3 two-render architecture: a real cropped LEFT high-resolution fovea and real RIGHT low-resolution full-FOV periphery. Mode 0 composes the V3 mono image into both OpenXR eyes. Modes 1/2 request a fused stereo shader; supported color formats render directly into the double-wide XR target, with the existing intermediate format-conversion path available otherwise. There is no additional Unreal scene render.

The LEFT fovea uses native LEFT color. The RIGHT fovea gathers LEFT color using RIGHT depth and a conservative LEFT visibility check, falling back to real RIGHT low-resolution color. LEFT periphery uses a bounded two-iteration RIGHT-to-LEFT inverse gather. Both foveae inherit LEFT shading where that gather succeeds. The complete full-matrix and forward z/owner kernels remain separate prototypes; they are not the live implementation.

## First test

1. Extract separately from your working V3. Select DuoView ID6, Split-Eye V3 ON, Mono Eye Alignment OFF. Enable R5 DSV/RDG capture and leave/re-enter ID6 to attach its observer.
2. Start with TRUE STEREO 0 and View depth 0. Request CAPTURE NOW. A request remains pending until eligible submitted depth exists; it no longer saves a misleading color-only snapshot. Preserve all raw files and manifest under `%TEMP%\UEVR_DuoViewCaptures`.
3. Auto selectors (0/0) jointly match LEFT/RIGHT active depth viewports to the frozen color source geometries at a coherent render scale, including DLSS. This is discovery, not eye/frame/pass proof. Manual ordinals override Auto and can change after a level load. Use View depth 1/2/3 to inspect candidates, then restore View depth 0.
4. Request mode 2. Its blue tint must cover the ENTIRE RIGHT eye, including corners, with the LEFT eye unchanged. Read **Actual XR output** separately from the requested mode. Waiting/rejected depth falls back to V3 mono and retries; mono does not increment the stereo submission counter.
5. Compare modes 0 and 1 at stationary near edges, an object around 2 meters, distant scenery, then slow head rotation. Record which mode was requested and what the Actual XR output line reported. Capture outdoor, indoor and character cases separately with the UEVR log.

## What the tests establish

The workflow retains the original backend/frontend builds and compatibility gates. Production D3D12 WARP tests exercise stereo pixel output, independent projections, offset depth viewports, depth ranges, invalid inputs, real RIGHT fallback, direct/intermediate output, whole-RIGHT-eye tint and unchanged mode-0 eye halves. Additional production depth-capture tests cover the observed small DLSS-scaled periphery, repeated read-only transitions, distinct write versions of a reused DSV, raw GPU readback and retirement after consumers. Exact test results belong to the corresponding workflow run.

Submitted means checked queue enqueue plus successful XR image release. It does not prove GPU completion, `xrEndFrame` success or physical headset presentation. Source camera/frame/pass identity, exact depth-pass matrices and temporal jitter remain unverified. Frozen source projections in captures are explicitly labeled as NOT depth-pass-verified. Full camera rotation and off-axis translation are not reconstructed by the current horizontal-disparity shader. A green CI run cannot establish STALKER 2 stereo quality or comfort.

The CI21 session exposed an interval-retirement ordering bug, a filter that rejected small periphery depth and fatal handling of ordinary missing-depth frames. This branch fixes those paths and exposes requested versus actual output. These fixes make the next test diagnostic; they do not turn inferred source selection into verified correspondence. Keep the stable V3 available and use mode 0 if the stereo result is wrong or uncomfortable.

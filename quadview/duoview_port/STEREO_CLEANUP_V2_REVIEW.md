# DuoView stereo V2 cleanup — pre-build review

**Base:** B318 #333 `5e89842f5b857e727e5aba82c7cfbd4160eee882`.
**Status:** source-generation overlay only; release build/Windows HLSL/WARP/headset NOT run. No measured GPU FPS or image-quality claim.

## Controls kept
Synthetic stereo on/off; close/far depth smoothing 0..1; depth transition start/end. Advanced: stereo strength, near limit, strict-paired M4 detail (off = coarse), developer depth picture. The original left/right image sharpening, wide sharpening, maximum changes, mono distance fade, gaze/crop/FOV/source-fit, periphery, B40 seam, Cheeky/VectorXR and XR pairing are unchanged.

## Old INI → effective new state

| Old saved keys | Treatment |
|---|---|
| `DuoViewSyntheticStereo` | Kept; startup mono-first gate unchanged |
| `DuoViewStereoStrength`, `DuoViewStereoNearMeters` | Preserved in advanced calibration |
| `DuoViewStereoEdgeSoftness`, `DuoM8DistanceEdges`, `DuoM8EdgeNear`, `DuoM8EdgeFar` | Read for one-time migration; exact legacy slope transition retained until new smoothing is edited |
| `DuoM8StartMeters`, `DuoM8EndMeters` | Preserved transition distances |
| `DuoDepthSmoothClose`, `DuoDepthSmoothFar` (new) | Effective monotonic smoothing after the first new edit, 0 sharp / 1 smooth |
| `DuoStereoDepthSchemaV2`, `DuoStereoLegacyCurveV2` (new) | Persistent internal migration markers; not shown |
| `DuoM4FoveaDepthGrid` | Preserved M4 strict-paired detail; off = coarse |
| `DuoM25FineMode`, `DuoM21FoveaDepth` | Old keys load but do not activate obsolete M2-only detail |
| `DuoM3PerEyeEdges`, `DuoM3OcclusionSharpness`, `DuoM3BackgroundFill`, `DuoM3JitterMode`, `DuoM21JitterCorrect` | Retired effective asymmetric/fill/jitter controls |
| `DuoM9PerEyeNear`, `DuoM9PerEyeFar` | Retired per-eye asymmetry; retired temporal-edge-reach lane carries the new legacy-curve marker (2 = legacy; 20 = new), while original M9 values remain available for true mono |
| `DuoM8FillNear`, `DuoM8FillFar`, `DuoFillHistory`, `DuoFillBlurPixels` | Effective zero; synthetic color fill/history/blur retired |
| `DuoEdgeHistory`, `DuoEdgeHistoryReachPixels` | Synthetic M6/M7 edge accumulation retired. **Deliberate image change**: archived edge history 0.70 was active |
| `DuoM24VerticalTaper` | Effective zero; its passes already skipped at zero |
| `DuoM25DepthDebug` | Kept developer diagnostic |
| `DuoM2LeftSharpen`, `DuoM2RightSharpen`, `DuoM5LeftMaxSharpness`, `DuoM5RightMaxSharpness`, `DuoM23WideLeft/Right` | Preserved independently per eye |

Migration: old curve was `clamp(base*(2-1.65*lerp(oldNear,oldFar,distanceWeight)),0,.99)` and could plateau for much of the transition. Merely mapping endpoints would change the image. Existing profiles therefore continue using the old curve internally until the user moves either new smoothing slider. The retired temporal-history reach constant is the internal 2/20 selector; no M9 directional constant is overloaded. New slider movement activates a monotonic `0.99*(1-0.90*smoothing)` profile. Old slopes below the new minimum 0.099 are not directly representable, but are preserved in the hidden legacy path until first edit. Other retired effects remain retired even in legacy mode.

## Source/running-work accounting

| Category | Result |
|---|---|
| Zero-fill equivalence-first | When M8 enabled and both fovea fill endpoints are exactly zero: skip unnecessary up-to-32-step hole-depth search, suppress fovea background color accumulation/blur; phase A still respects independently enabled M3 periphery fill |
| M6/M7 retirement | Delete synthetic stereo temporal shader reprojection/packing/history writes, per-frame history descriptors, UAV transitions and two R32G32B32A32_FLOAT 1024² history allocations |
| Allocation | Two × 1024² × 16 bytes = **32 MiB per compositor history owner** not allocated; preserve B40 seam buffer |
| Geometric policy | Coarse mono/legacy path unchanged; V2 coarse uses source-specific slope and two-eye bound; M4 preserves crop-width-aware no-fold safety |
| Retained dependencies | Separate left/right warp and submitted outputs, M4 fine field, root descriptor table layout, strict frame/depth leases, B40 seam history |
| Already inactive | No new M25 dispatch saving while M4 requested; vertical pass skipped when taper is 0 |
| Deferred | New edge-reconstruction algorithm for large artifacts beside near objects; this cleanup does not fix them |

## Validation

**Local PASS:** guarded overlay replay on original B318 #333 generated sources; Python syntax; numerical old/new endpoint and full-transition migration checks; monotone 0..1 slopes; both-eye full-eye-UV bounds; zero-fill equivalence model; static shader/state, UI, source-fit, B40 history and descriptor checks. The original M8 source tests still run *before* the cleanup stage; new V2 tests run *after* it.

**NOT RUN:** Windows FXC, D3D12 WARP, full backend compile, pixel-by-pixel GPU equality, VR headset image quality, crash/reload validation, actual GPU memory measurement and timing. CI is deliberately not triggered without approval.

## Required next headset comparison (after separately authorized build)
Use the same save/pose/settings: near railing/weapon silhouette; distant grass pan; slow gaze motion; seam; M4 vs coarse; independent eye sharpening; restart with saved old and new profiles. If removing temporal edge history creates meaningful vegetation flicker, restore a minimal internal fixed history path rather than shipping a known regression or reintroducing many ineffective sliders.

# TriView B1 adversarial code review — 2026-10-31

**Scope:** `claude/triview-b1-20261031` @ `e9bcbfde8963c7fd1e4c4d72c47f920019623fd6`, exactly one commit after Build 51 `f4e086cde6d4a183cf2c1223dd9effaf6f8f7a77`.

**Evidence class:** SOURCE-READ + mathematical counterexamples; **not headset-verified**, **not a compiled/tested green result**. The only observed workflow run for this commit, [Tri-view B1 run #1](https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/41236660064), was **cancelled** at the time of review. The code-review findings below are not build or performance measurements.

## Actionable bugs

### P1 — Shared-context frustum/UV mapping omits the relative eye rotation

**Source:** [QuadViewGeometry.hpp L46–90](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/e9bcbfd/quadview/QuadViewGeometry.hpp#L46-L90); [QuadViewComposite.hlsl L42–45](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/e9bcbfd/quadview/QuadViewComposite.hlsl#L42-L45); [apply_quadview_triview.py L34–88](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/e9bcbfd/quadview/apply_quadview_triview.py#L34-L88).

**Defect:** `apply_shared_context(layout,left,right)` receives ONLY lens projections. It computes union limits in each *eye-local* tangent frame, despite view 0 using the LEFT camera orientation and view 3 retaining the RIGHT camera orientation. The right-eye mapping `uvContext = uvEye * xy + zw` has no relative camera rotation. This is not generally correct even at infinity. The existing gaze path explicitly respects different eye orientations ([QuadViewGaze.hpp L49–69 and L157–178](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/f4e086c/quadview/QuadViewGaze.hpp#L49-L69)).

**Deterministic mathematical reproducer:** Choose two valid identical +Z-forward, column-major 90-degree horizontal perspective matrices (`p[0]=p[11]=1`, `p[8]=0`), with left optical yaw = 0 degrees and right optical yaw = +10 degrees. This implementation derives identical `context_uv` for both eyes and the same [-1,+1] tangent union. But the RIGHT centre ray projects at `tan(10deg) ~= 0.17633` in the LEFT context coordinate system; its true U is `(1 + 0.17633)/2 ~= 0.58816`, not `0.5` (sign reverses if yaw convention reverses). **Absolute error ~= 8.816% of context width at infinity.** Correct head-space union extends to `tan(55deg) ~= 1.428` on the right for this example, whereas the computed union stops at 1.0. The sign is convention-dependent; the non-zero error and undercoverage are not.

**Consequence:** A headset whose eye poses differ in orientation gets an incorrectly positioned shared mono periphery, border undercoverage/clamping, and a spatial mismatch between native per-eye foveae and their blended context. At finite distances there is also intended mono parallax error, but this finding exists **even at infinity** and cannot be dismissed as normal mono parallax.

**Minimal fix:** Provide the *frozen same-frame* per-eye camera orientations when constructing the shared layout. Transform both frusta into a chosen shared camera basis (left eye or head centre) before obtaining union bounds. Replace the affine 2D transform with a 3x3 rotation homography / ray-based UV mapping at infinity; a depth-aware path would be required for near-field exactness. Add a deterministic canted-eye test that projects identical head-space rays through both cameras and compares sampled context coordinates, including union corners.

### P2 — Midpoint translation uses LEFT optical rotation instead of the head-space translation rotation

**Source:** [apply_quadview_triview.py L50–77](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/e9bcbfd/quadview/apply_quadview_triview.py#L50-L77). In the pinned Joey base, the original `eye_translation_rotation` is `mono ? normalize(vqi_norm * current_hmd_rotation) : normalize(new_rotation)`, and `new_rotation` contains the per-eye optical rotation. The pinned source comments that the centre offset is head-space and must **not** undergo an extra optical rotation; the original mono path deliberately excludes it.

**Defect:** The inserted centre correction computes:
```cpp
center_offset = (left_eye_offset + right_eye_offset) * 0.5f;
center_separation = quat_converter * (eye_translation_rotation * (center_offset * world_scale));
qv_center_shift = eye_separation - center_separation;
```
TriView uses the stereo/LEFT `eye_translation_rotation` (containing the LEFT optical cant), so the desired camera centre is rotated with that left optical transform instead of the head rotation. For **zero mean eye offset**, this term is zero and the bug does not manifest. For non-zero/asymmetric mean eye offsets and nonzero cant, the midpoint camera is wrong by `(R_head - R_left_optical) * center_offset * world_scale` (up to the fixed converter/sign convention).

**Minimal fix:** Keep the LEFT-eye `eye_separation` for undoing the original stereo offset, but compute `center_separation` with `normalize(vqi_norm * current_hmd_rotation)`, i.e. the same rotation chosen in Joey's existing mono centre-position branch. Add a synthetic non-zero midpoint + canted-left-eye camera-position test.

## Requested invariants checked (no other demonstrated bug)

1. **Role 1 no longer blocks native publication by itself.** The dispatcher skips slot 1 only when `snapshot.layout.shared_context` is true (skip mask 0x02). Both production `NativeDelivery::bind` sites are patched to use required mask 0x0d in that mode, otherwise 0x0f. In `QuadViewNativeDelivery.hpp`, `latch_completion` checks `hooked == required`, execution checks `executed == required`, and content provenance ignores unrequired targets. Runtime cadence is anchored to role 3, which remains active. The four-view constructor/snapshot and four allocated targets are intentionally still required *before* per-role rendering, not an overlooked wait for a role-1 RHI tail. Existing tests exercise the three-role execution path but with `explicit_role_frames=false`, so real GT per-role-frame execution is **not independently integration-verified**.
2. **LEFT focus pose freeze is before shift.** The existing post-mod `quadview_producer().camera(... view_index=0, pose)` call is before the added `view_d += qv_center_shift`; focus view 2 loads that frozen left pose. The additive shift's **sign is correct**: from original `P - eye_separation`, adding `eye_separation - center_separation` yields `P - center_separation`. P2 concerns the rotation used to calculate `center_separation`, not this sign or capture order.
3. **Within a common camera orientation**, the +Z, column-major matrix algebra is consistent: `a=p[0 or 5]/p[11]`, `b=p[8 or 9]/p[11]`; union limits, `m[0][0]/m[2][0]/m[1][1]/m[2][1]`, and both U and vertically flipped V affine transformations have the correct signs. P1 is that *two cameras' coordinates are not a common basis*.
4. **Four-view toggle OFF:** source-read shows layout affine identity and separate context source indices 0/1; required mask 0x0f; skip mask zero; and no centre-camera shift or union projection override. The shader constant buffer is expanded from 144 to 192 bytes but both HLSL and CPU structures were expanded in the same order. **No specific four-view-OFF behavioral regression identified** by this static review; byte-for-byte equivalence and headset equivalence are not claimed.

## Release recommendation / verification boundary

Do **not** label B1's union reprojection as correct or exact for canted eyes. Fix P1 before treating image-quality comparisons as meaningful; fix P2 in the same small patch. Leave NativeDelivery masks alone unless a concrete trace disproves them. Rerun exact Build 51 four-view toggle-OFF compositor tests and the production explicit-role-frame path, then obtain a completed Windows compile and actual headset screenshots. The cancelled CI run supplies no build-green evidence.

**Files reviewed:** `quadview/apply_quadview_triview.py`, `QuadViewGeometry.hpp`, `QuadViewNativeDelivery.hpp`, `QuadViewFamilyRouting.hpp`, `QuadViewD3D12.hpp`, `QuadViewComposite.hlsl`, `NativeDeliveryTests.cpp`, `QuadViewShaderWarpTest.cpp`, `.github/workflows/triview-b1.yml`; corresponding Build 51 files; original overlay scripts for rendering/role frames/consumer/target lifetime; pinned Joey source around offset rotation; and existing `QuadViewGaze.hpp`. **No implementation files modified.**

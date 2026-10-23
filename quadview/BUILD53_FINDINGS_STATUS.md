# Build53: alternating fovea-first native render test

## Purpose and scope

The user reports that the first/primary source is consistently better shaded,
that Native Stereo Fix improves secondary shading but does not make it exact,
and that Build52's earlier PRIMARY classification did not resolve the mismatch.
The working hypothesis is that first-render lighting/cache updates are privileged
and alternating the first fovea may let both eyes accumulate those updates.
Lumen is a suspect, not an established cause. No lighting fix is claimed before
headset testing.

This experiment changes the **first actual native Unreal renderer invocation**.
It does not reorder the earlier construction of FSceneView objects, change
StereoViewIndex, relabel the remaining sources SECONDARY, rewrite scene-state
pointers, exchange eye histories, or swap completed left/right images. The
Build52 shading toggle remains independent. If the privilege belongs to earlier
view construction or index zero instead of renderer order, this experiment may
not move it. That distinction is deliberate and visible in the diagnostics.

## Saved control

`QuadViewRenderOrder` / **Fovea-first rendering test**:

| Value | Renderer call order (canonical role) |
| --- | --- |
| 0 | Left context, right context, left fovea, right fovea (Build52 baseline) |
| 1 | Left fovea, right fovea, left context, right context |
| 2 | Right fovea, left fovea, left context, right context |
| 3 (default) | Alternate orders 1 and 2 after each completed native source quartet |

The selected mode is frozen with the source settings. Incomplete/aborted source
quartets do not advance the alternation; repeated calls for one uncompleted draw
retain its plan. Mode changes take effect on the next source draw. Generation
changes start the sequence again. This counts game-source quartets, not the
headset's 120 Hz display refreshes or held/reprojected submissions. Both eyes and
both peripheries render every successful source frame: this is not AFR.

## Preserved identities and timing

Canonical roles remain 0=left context, 1=right context, 2=left focus, 3=right
focus. The engine-created view, history pointer, camera, projection, rectangle,
render target and compositor source remain attached to that role. Four distinct
native targets and four distinct histories remain required. Only the validated
permutation passed to the native singleton dispatcher changes.

Source registration now occurs at the selected first renderer callback while
presenting the original complete canonical family to the source ledger. Scene
frame compensation and the special original first-batch call follow dispatch
ordinal, not canonical role. Per-role GT/RT/RHI ownership stays authenticated.

The old delivery implementation singled out canonical role 3 for OpenXR cadence
because it was the last renderer call. Each packet now records its actual last
dispatch role (role 1 for the fovea-first orders; role 3 for baseline). Cadence
follows that last role. Engine tickets, CPU leases, tail provenance, quartet
completion, source overwrite rejection and GPU fence retirement remain required.
No timeout releases owners and no diagnostic marker proves retirement.

`[QuadViews][RenderOrder]` prints the frozen mode, completed-quartet sequence and
order. Bounded `ORDER_ROLE` HookTrace records identify each actual invocation's
ordinal, canonical role, history identity and target. `SHADING_SOURCE` still
reports constructor input; its order remains canonical.

## Acceptance test

Start a fresh game process, use the same save/scene, and keep the consistent
shading toggle, exposure/quality settings, resolution, crop and gaze configuration
unchanged while comparing this control. Compare 0, 1, 2, and 3, allowing 15–30
seconds for lighting/exposure to settle in each mode. Check whether better
shading moves with the first-rendered fovea, whether alternating converges, or
whether it flickers/ghosts. Then test head motion, gaze shifts, near weapons,
menus/loading, runtime reset and mode changes in both directions. Keep the full
log if any behavior differs.

This still executes four scene renders. It is a shading experiment and makes
no CPU/FPS improvement claim. Build51 remains the user-confirmed functional
fallback; Build52 remains the exact pre-order-test source baseline. The accepted
conditional foreground MPC fix and guarded transitions are retained.

## Automated validation

The new harness exercises the production permutation/sequence/dispatcher and
native delivery headers, including all 24 role permutations, frozen source
plans, aborted draws, stale tokens/generations, settings rejection, restoration
on failures/exceptions, per-role identity and last-dispatch runtime cadence.
Existing geometry, target lifetime, ownership, real policy and shader suites
remain required. Full Windows CI must compile the real SDK/backend/frontend,
run the original compatibility tests, run ASan/UBSan independently, and record
exact ZIP/DLL/PDB identities. Automated checks cannot validate game lighting.

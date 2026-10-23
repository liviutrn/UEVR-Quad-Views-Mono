# Build52: source shading parity, first-person fix and guarded transitions

Build51 is the first user-confirmed successful four-source Native Stereo Fix
QuadView build. Its source runtime revision is `f4e086c`, with notes and
validation at `c67e967`. Preserve that package as the headset-tested fallback.
Build52 is a new test candidate; Build51 acceptance does not establish Build52
headset acceptance.

## Changes

* Shading priority: all four native source views can now be classified PRIMARY
  at `GetViewPassForIndex`, before caller/post-process logic, rather than only
  temporarily inside FSceneView construction. Build51 returned PRIMARY for
  both left roles and SECONDARY for both right roles at that earlier boundary.
  This is a concrete eye-specific asymmetry matching the user's symptom;
  whether it explains all observed lighting/exposure differences requires a
  headset test. `QuadViewPrimaryPass` is a saved, default-on rollback toggle.
  Admission requires an active HMD, supported title, viewport draw, live native
  targets, and no nested native dispatch or view post-init. This API has no
  family argument, so these guards cannot identify every unrelated stereo
  scene capture nested elsewhere inside a viewport draw; test those paths too.
  Explicit view indices, eye poses and four distinct histories remain required.
  No gamma multiplier, exposure CVar, Lumen quality switch, or history sharing
  is used to conceal a difference. Per-role `SHADING_SOURCE` markers report the
  original/constructor input pass and state identity without guessed offsets.
* The existing timing toggle also measures average/maximum CPU time of the
  four-call native dispatch region, counting only completed quartets and
  protecting aggregate counters across threads. This excludes GPU execution
  and the rest of the game. The log did not contain a whole-frame CPU/GPU breakdown.
* Port the accepted DuoView `0bfb814` foreground implementation into ID7. Its
  actual shared-world MPC overrides are `IsFOVEnabled=0` and `DepthScale=1` in
  `MPC_FOV`. It does not rewrite `TanFOV` per view. Cached lookups and UObject
  identity checks remain; scalar getters run each active tick and setters run
  only when the current value differs. It restores the captured original values
  on ID7 exit or toggle-off, and refuses stale-world/asset writes. A saved
  `QuadViewForegroundMPC` toggle enables comparison with Build51 behavior.
* Register the existing QuadView controls with the backend's option collection,
  which supplies profile saving/loading. Original range/layout validation still
  reconciles loaded requests. Previously these controls were drawn but omitted
  from the saved option collection.
* In STALKER 2, route all serialized mode changes through the existing retired
  present / game-boundary commit transaction. Other titles retain their existing
  selection policy. Rapid replacement/cancellation invalidates old retirement
  acknowledgements. An invalid live destination cancels only that exact request,
  preserving any newer request; initial QuadView hook warmup may keep waiting.
* Add a narrow maintenance RHI callback while an outgoing ID7 transition has
  closed source admission. It requires no source owners, a known Slate drain,
  a validated readable command tail, and bounded bookkeeping. It always runs
  the original callback and worker drain, but never assigns poses, synchronizes
  or begins XR, publishes an image, or declares a resource retired. This remains
  true if its generation/request becomes stale.
* Log bounded blocked-transition ownership snapshots and maintenance hook/
  execution markers. No timeout clears engine tickets or bypasses GPU fences.

The log demonstrates a real outgoing ID7 transition stall. A maintenance callback
addresses the missing worker-pump path; it cannot prove retirement of an
unhooked/mismatched engine ticket. The new counters identify that distinction if
headset testing still stalls. No claim of complete runtime transition robustness
is made from portable tests alone.

## Preservation and validation

The four source render targets, engine-visible ownership, lifetime validation,
native-role frame binding, source matching, projection/FOV,
gaze sampling, shader and compositor math remain Build51's implementation.
The pinned DuoView source tree and upstream backend/SDK/frontend pins remain
unchanged. Pass classification is intentionally changed to address shading. No
rendering speedup is claimed; CPU measurement is opt-in.

The foreground tests include the exact production runtime block with a fake
reflection boundary. They verify cached discovery, no repeated stable writes,
single-scalar drift repair, original-value restoration, and stale-identity
refusal. The transition tests include the actual patched backend Selection
header: all 64 serialized mode pairs, rapid request changes, cancellation,
stale acknowledgement/rejection, callback admission, and genuine engine-owner
retirement before commit. Existing geometry/ownership/property tests remain.
Windows CI must additionally compile the real SDK/reflection adapters, shader
tests and frontend, run all compatibility suites, and record exact DLL/PDB hashes.

## Headset acceptance

Use a fresh game process. First compare left/right context and left/right focus
lighting in the same scene with the consistent-source-shading toggle ON/OFF.
Verify true binocular stereo and gaze remain correct. Then compare first-person hands, weapons, knife and detector
at the fovea seam with the MPC toggle on/off. Test ID7→ID6→ID7, ID7→ID5→ID7,
ID7→ID0→ID7, changes among the other available modes, cancellation/rapid requests,
loading screens, and a runtime reset. For steady performance comparisons use the
same save/location, resolution, crop/context settings, DLSS and FPS cap. Keep the
complete UEVR log; the transition markers must show actual retirement and commit.

Primary-source reference: Epic UE5.5 IStereoRendering::GetViewPassForIndex documents pass classification separately from the explicit view index: https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/IStereoRendering/GetViewPassForIndex?application_version=5.5 .

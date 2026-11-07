# TriView B28: DuoView comparison and repair candidate

Status: source repair candidate, locally tested; not Windows compiled, not headset validated, and not a certified BSOD fix.

## Conclusion

DuoView v186.2 / Build 206 keeps the original Native Stereo Fix two-source transaction. B22/B23 TriView explicitly disables that normal path and substitutes custom singleton dispatch, per-role engine frames, source ownership, RHI-tail tracking, composition and pose submission. Sharing the Joey backend does not mean these lifecycles are the same. The comparison justifies repairing these divergences; it does not establish a graphics-driver culprit.

## Exact references

- Stable DuoView build source: `915226735b03dc736028f01b93cb39a20efe81cb`, Actions run `40562995836`. Release tag is a later documentation commit.
- B28 parent: B23 `a3c85bb529afc589becbb7f236816a57cf831aa8`; B23 inherits B22 and changes the depth search sample count.
- Shared Joey backend: `5ac7edc207866569334175e4ed8a7517971547f6`.
- SDK pin: `3cffbc82429b6165ceec2714f0f0d9ae48f55596`.
- Frontend pin: `60be4b0f9a646109fd9fdf448bacd41477234091`.
- Local branch: `experiment/triview-b28-duoview-lifecycle-20261107`.

## Findings and changes

| Area | Concrete difference or defect | Prepared correction |
|---|---|---|
| Pose provenance | TriView stamps a reused scene-role ring slot with a new frame number while an old located pose can remain marked valid. Camera head queries and submitted pose can then refer to different snapshots. | Freeze one completed head-and-eye locate for cameras and submitted image. Scene-role stamps cannot create a located-pose identity. Reset caches at world/session transitions; preserve monotonic locate serials. |
| Native target hooks | DuoView uses a process-lifetime copied virtual table. TriView stored its table in a retireable owner and some cancellation paths wrote saved virtual pointers into old resources. | Use fixed-capacity immutable process-lifetime tables, retaining no textures. Remove cleanup writes into retired target pointers. Gamma callback reads a cached scalar, without following retired viewport/owner pointers. |
| Runtime restart | Swapchain teardown could return early while the caller still destroyed the runtime. Extra TriView producers/depth queues were not covered by the normal reset call. | Port checked B24/B26 teardown: close/drain through existing mode transition, wait for real completion, discard completed old-session depth, require a newly published native pair before returning to ID7. |
| World changes | Raw world address, cached resize/pose state and old callbacks can span a save load. A serial check alone races callbacks already admitted. | Observe actual Unreal object identity. Close new XR admission without blocking GT, let admitted callbacks finish, then invalidate cached publication/targets. Preserve old CPU leases until real callbacks drain. Gate source-only callbacks, target builds, composition and XR submission. Keep dirty recovery state across canceled mode requests. |

The frozen camera eye data is a small value type. Located-pose publication reuses existing vector capacity rather than allocating a new vector every locate. Three physical source targets, original controls, B23 shader, four depth samples, and B21 depth selection are preserved. There is no measured FPS or VRAM result.

## Log evidence

The supplied TriView log has four stale-source lifetime rejections and 5,229 `No stage views to submit` warnings; DuoView has zero of that warning and completes runtime resets. TriView also logs a runtime reset and resumes afterward before the file ends. Neither log proves which source defect caused a kernel crash, and the backend hash is shared, so it does not independently distinguish B22 from B23. User-reported resize/reset BSOD and load-related headtracking failure remain the hardware observations to validate.

## Validation completed locally

- Reconstructed exact released DuoView C++ source transformations and B23/B28 source transformations.
- Clean replay of every B28 source overlay: passed all exact anchors.
- 27 portable executable tests passed; the new epoch-gate test also passed (28 distinct executable tests in total).
- All three new production-helper tests passed AddressSanitizer and UndefinedBehaviorSanitizer with warnings as errors. LeakSanitizer is unavailable under this host tracing environment and was disabled; no leak-safety claim is made.
- Final generated integration checks passed. They check wiring/ordering, not Windows compilation or driver behavior.
- Preserved DuoView source integrity and whitespace checks passed after removal of a locally generated Python bytecode cache.

## Outstanding and limitations

Windows Actions build, restricted SDK verification, offline DXBC compilation, WARP GPU tests and PSVR2/STALKER hardware validation are not completed. Local materialization skipped only shader bytecode generation, which needs Windows fxc.exe; no C++ transformation was skipped. The new test bodies do not certify Unreal or graphics-driver lifetimes.

The reset state machine was ported from the existing B26 branch; it is not presented as a newly proven complete fix. Source retirement still relies on the existing engine/RHI and GPU completion machinery. Exact depth/color matching remains approximate. Simultaneous runtime optics/FOV changes require hardware validation of the inherited calibrated projection path.

A fresh Terra review found races/edge cases in early revisions. Corrected items include holding epoch admission through side effects, source-only callbacks, target-build admission, canceled recovery, public accessor visibility, canted-eye translation, and the gamma callback. These corrections passed clean source replay and local helper tests; runtime behavior remains unverified.

## Next step

Push this prepared experiment branch and let `.github/workflows/triview-b1.yml` compile B28 on Windows. Do not label it stable before that build and headset validation. The current workflow packages B28 identity and this note, retains exact PDB/DLL identity and evidence, and includes the new executable tests.

Publication was not attempted successfully: automatic approval review rejected a dry-run GitHub push because publishing a branch was outside the authorization it inferred. Explicit user approval to push/run the prepared build is required before retrying. Do not bypass that rejection with a different publishing tool.

## Short headset checklist after a successful Windows build

1. Direct ID7 start; verify both true stereo foveas, normal head motion, and recenter.
2. Load a save; verify tracking without a runtime reset.
3. Reset runtime; verify automatic return to TriView with a fresh native pair.
4. Change fovea width, height, and resolution one at a time.
5. Record the exact package build JSON and log for any failure; local checks do not justify repeated blind BSOD tests.

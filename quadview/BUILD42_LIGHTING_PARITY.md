# ID7 Build 42 — experimental constructor-time lighting parity

**Source:** exact Build 40 branch head `7486fc59890b14673cd50770b0dafeb692576716`; no Build 41 cherry-picks.

## Why this change

In a matched S.T.A.L.K.E.R. 2 interior, Quad Views Stereo ID7 Build 40 appeared uniformly brighter than Mono, Native Stereo and DuoView. The cause is not yet confirmed. Build 40 already renders four distinct scene views and has functional stereo, eye gaze, FOV and performance.

## Minimal adaptation

UEVR's `GetViewPassForIndex` assigns alternating `PRIMARY` and `SECONDARY` passes to the four requested views (indices 0–3). The known-good DuoView Native Stereo Fix backed path can transiently relabel a secondary view as `PRIMARY` during `FSceneView` construction.

Build 42 borrows **only** this view-constructor classification for the second and fourth quad views, when all main-family safety guards pass. The original `FSceneViewInitOptions` pass is restored immediately after the constructor returns. Importantly, the *constructed view's* classification may still be PRIMARY, as intended for the lighting A/B test.

The following remain as in Build 40:
- `is_native_stereo_fix_enabled()` is false for ID7. No Native Stereo Fix two-target split or renderer replay.
- Original four independent engine views/histories and atlas layout.
- No view list count manipulation, forced scene-state aliasing, FOV, camera or projection changes.
- Existing PSVR2 eye gaze, crop, submission, GPU compositor, and synchronization.
- No gamma adjustment, darkening or exposure multiplier hacks.

Relabel is skipped when source pass, target, scene, four-view slot, or view-family confidence is insufficient. In those cases the image follows Build 40 behavior and logs a diagnostic.

## Logging

Rate-limited `[QuadViews][Lighting42]` entries for each main view slot report original/effective constructor pass, relabel decision (where relevant), scene-state pointer, family, target and scene. These data show whether both right-hand eye views received the constructor adaptation. **Numeric PreExposure, Lumen show-flags, and engine tonemapper internals are not logged:** their version-dependent SDK offsets are not validated; reading them speculatively could cause a crash. Compare the same room under equivalent game exposure settings.

## Validation / limitations

Automated source-checkpoint tests protect ID7's original Native Stereo Fix gate and the four-view constructor logic. Windows CI must compile the backend and run the available QuadView tests. No automated test can prove STALKER 2 Lumen correctness, PSVR2 stereo, or frame pacing.

This is an **experimental engine-side constructor-pass parity candidate**, not a verified lighting fix. It might have no effect, or it could alter temporal history/lighting expectations. Do not promote it over Build 40 without headset comparisons.

### Headset test

1. Use the same indoor spot and game graphics/exposure settings as the Build 40 report.
2. Compare Mono, Native Stereo, DuoView, and Build 42 ID7; focus on contact shadows, indirect light and overall brightness.
3. Confirm both focus and context and both eyes look similar.
4. Test eye gaze movements, horizontal FOV, stereo depth, transitions, and frame delivery.
5. Switch away and back to ID7 multiple times (Build 40 activation was intermittent).
6. Test an outdoor location and move between indoor/outdoor for exposure changes.
7. Attach `[QuadViews][Lighting42]` log records and note whether slots 1 and 3 say `relabeled=1`.

### Interpretation

- Both secondary slots relabeled and lighting matches: promising constructor classification explanation.
- Both relabeled but still bright: inspect engine view-family, exposure and show-flag equivalence first; then evaluate compositor output format and sRGB/UNORM handling. Do **not** add a gamma fudge.
- Neither relabeled: safety guard likely rejected the family; use the logged slot/target data before changing conditions.
- FOV, stereo, gaze, or startup regression: return to Build 40 and do not expand this experiment without explaining the failure.

**Rollback:** checkout Build 40 commit `7486fc59890b14673cd50770b0dafeb692576716`.

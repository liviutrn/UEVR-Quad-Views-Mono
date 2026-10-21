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

## Additional user observation: left-eye context/focus mismatch

A later headset report says **the left eye alone** has visibly different shading between the low-resolution periphery and central fovea. The overlay's exact view indices are **0 = left context; 1 = right context; 2 = left focus; 3 = right focus**. The current Build 42 relabel touches only slots 1 and 3 (the right-eye SECONDARY constructors). Therefore it **cannot be asserted to fix the left-eye difference directly**, and is an informative first A/B candidate rather than a proven solution.

Both left views already request `PRIMARY` in the original alternating pass scheme. Different Lumen history/resolution/post-processing per source view, or focus-only sharpening, remain plausible. The compositor uses the same atlas sampling and output color encoding logic for both eyes; its existing sharpening filter applies to focus only. This observation argues **against** a global gamma/output darkening change.

### Isolation test using existing controls (zero rendering changes)

- In the same interior, set **Fused focus sharpening strength = 0**.
- Select existing **Source diagnostic 1 = context only**. Compare the same surface in each eye (do not judge it against focus while this mode is active).
- Select **Source diagnostic 2 = focus only**, and compare the *same overlapping scene location*, accounting for foveal crop.
- Return **Source diagnostic 0 = composited view**, then compare left context vs left focus, and right context vs right focus.
- Run the same comparisons with eye gaze frozen/fixed-center if possible to separate gaze-dependent history updates from view identity.
- Check whether relabel logs show slot 1/3 applied and whether left slot 0/2 report PRIMARY and the same scene/family.

If context-only already lacks shadows relative to focus-only, the difference originates **before** the compositor blend; do not compensate via compositing gamma. If original source views visually match but only the blended image differs, focus on sampling/sharpening/color handling. It may take runtime capture of Unreal's Lumen, eye exposure, and view-family state to locate a deeper root cause.

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

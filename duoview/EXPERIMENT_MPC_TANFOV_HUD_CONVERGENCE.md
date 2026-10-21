# Experimental DuoView: STALKER 2 MPC_FOV.TanFOV and OpenXR convergence

Baseline: v186.1 Glamarye; DuoView mode ID6 only. Stable release unchanged.

## Changes relative to Build 195

- **Removed** the ineffective `FSceneViewInitOptions.FirstPersonParams.FOVCorrectionFactor` heuristic scanner, menu toggles and tests.
- **Added** reflected Unreal `UKismetMaterialLibrary.GetScalarParameterValue`/`SetScalarParameterValue` for the game's actual collection `/Game/_Stalker_2/Materials/MPC/MPC_FOV.MPC_FOV`, scalar `TanFOV`.
- HUD convergence is **visible inside VR > DuoView Mono — quality and diagnostics**, in addition to generic Overlay Options. It adds a manual -0.25 to +0.25 m per-eye shift that works even when automatic stage-view IPD is unavailable. A counter shows successful dual-layer submissions.

## Calibration

- Select DuoView Mono ID6, open its **quality and diagnostics** tree.
- For HUD: select OpenXR UI Overlay Type **Quad**, set UI Distance/Size to **10/10**, enable **DuoView UI convergence**, set reference distance ~**2**, then sweep the manual convergence slider from **-0.05 to +0.05** until the reticle fuses. The number of **eye-specific OpenXR quad pairs submitted** should increase as frames are presented.
- For weapons: enable one **MPC TanFOV** toggle at a time. Fovea and periphery controls are independently persisted and frame-frozen, with factors **0.33–3.00**, neutral 1.00.
- Read **MPC TanFOV status** and confirmed/failed counters. Status 6 means a true game parameter read/write/readback succeeded. It **does not** establish that GPU work consumed a unique per-view value.

## Fundamental limitation

Unreal Engine material parameter collections are **world-shared**. DuoView attempts different TanFOV values at each producer-source construction, but the material collection may be sampled later by both Unreal render passes. This experiment must **not** be represented as a proven per-view projection fix until headset A/B testing shows distinct source behavior. Native Stereo Fix, delivery stabilization, gaze history, Glamarye sharpening and Mono fallback are unchanged.

If MPC status remains 1–5, preserve the log for a real failure classification. Do not infer that the weapon scale changed simply because a slider moved.

## Testing

- Debug Source 2 (fovea only), Debug Source 1 (periphery only), then combined mode.
- Hold gaze and camera steady. Compare weapon outlines in the center, not the external VR Peripheral edge-mirroring zones.
- Try factor 1.0, then 1.5 and 2.0 in one source with the other toggle OFF; restore both to OFF before comparing stock behavior.
- Check all crosshair/UI changes at UI 10/10, including UI Follows View and interaction.

The exact SDK provenance and CI evidence remain in the packaged build.

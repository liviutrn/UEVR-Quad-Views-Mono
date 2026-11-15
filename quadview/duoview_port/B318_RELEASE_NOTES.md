# DuoView B318 — release-candidate engineering notes

Base: passing #317 `c75d17dff905e3b705f4d31c583e8b184b63dd80`. The pinned `duoview/` source tree is unchanged. Changes are applied only to generated mode-6 source through the guarded `quadview/duoview_port/apply_duoview_b318_*.py` overlays in the production workflow.

## Changes
- **Real Unreal source shading:** vertically fit the shared center camera to the calibrated union of both eye frusta, retain a conservative 0.02 UV guard with outward 1/128 snapping, and reduce the actual periphery view rectangle. The foveal view rectangle and angular detail remain unchanged. No OpenXR output texture or visible FOV is cropped. Logical-to-source transforms are carried through M1, the compositor, M4 depth and M7 background fill. The fit toggle is latched once per OpenXR generation; a runtime reinitialize is required to change it.
- **Mono distance fade:** reuse the existing captured coarse NGX depth and M2.4 near/far fade for one common mono image, without M4 fine capture or per-eye double sharpening. Require matching source epoch; fall back to ordinary color sharpening if absent. Preserve M1's proven zero-depth stereo fallback.
- **Startup:** honor the persisted stereo toggle, but render a valid plain mono image before enabling synthetic stereo. During this initial gate also withhold mono depth-conditioned fade, so the startup workaround does not accidentally start the depth pipeline. Stage stereo on the next UE draw after visible mono submission.
- **OpenXR depth:** early skip predicate checks the selected/requested DuoView mode rather than the late active state. Skip only when runtime depth consumers are off. This does not remove internal DLSS/NGX depth.
- **Defaults:** vertical taper = 0, skip unused XR depth = on. No implicit override of existing per-game saved settings.

## CI and headset criteria
Preserve all 14 pre-existing M4 GPU WARP cases, the new B318 source-fit numerical test, backend DLL and compatibility tests. Measure actual game GPU time with VectorXR off, same SteamVR FOV, same DLSS/NR and both source modes. Verify two successive fresh game launches with saved stereo on, an in-game reload, upper/lower gaze, near foreground against a far wall, and per-eye full output resolution. A consistent saving even around 0.3 ms is useful, but **no game GPU timing or two-launch result is claimed by CI**.

See `.github/workflows/triview-b1.yml` for exact patch order. The STALKER 2 test profile remains the separately saved `DuoView-317-Defaults.zip`; do not silently overwrite the user's per-game config in the release archive.

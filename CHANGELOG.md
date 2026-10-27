# Changelog

This changelog documents **published DuoView releases**. Experimental Quad Views, DIBR and diagnostics builds are not promoted as recommended production releases. A published build may still include features awaiting headset validation; each entry specifies its test status.

## [v186.2 — Manual FOV recovery & configurable keybinds](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.2) — 2026-10-27

**Latest packaged release: GitHub Actions Build #206.** Binary source: `915226735b03dc736028f01b93cb39a20efe81cb`. The original #205 FOV recovery was confirmed successful after a real S.T.A.L.K.E.R. 2 save reload; #206's new keyboard controls and combined-key sequence have passed compilation and static/integration regressions but still require a headset test.

- **From verified Build #165:** retains the existing DuoView ID 6 foveal/peripheral rendering, Glamarye, first-person FOV correction, Mono HUD/eye alignment and XYZ head scaling.
- **Build #205 (manual recovery):** adds `Reapply DuoView FOV` beside `Reinitialize Runtime`. When the normal `MPC_FOV` lookup is unavailable after a load, its manually requested fallback resolves the previously validated collection in Unreal's global object registry, writes `IsFOVEnabled=0` / `DepthScale=1`, and verifies both scalar values. This path was confirmed effective in a save-load headset test.
- **Build #206 (hotkeys):** adds two persistent UEVR ModKey settings, `Reapply DuoView FOV Key` and `Reinitialize Runtime Key`, both initially Unbound. The same physical key can be assigned to both actions; the reset completes before a delayed gameplay-ready FOV reapply. The existing manual button and #205 FOV handler remain unchanged.
- **No broader automatic recovery:** no save-load watchdog, compositor recovery or automatic OpenXR reset. Rendering paths and protected modules are source-identical to #205.
- Full release notes: [v186.2](RELEASE_NOTES_V1862.md). Previous public release tags and binary assets remain unchanged.

## [v186.1 MPC/HUD/Eye Alignment Persist49-56](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.1-mpc-hud-eyealignment-persist49-56) — 2026-10-23

**User-tested stable DuoView update.** The binary is the original CI run #56 / Build 49 package, source commit `60d0aae86949723d21266e4121a833f0191729c2`.

- **Build 45:** STALKER 2 `MPC_FOV` foreground override fixes held-item fovea/periphery scale mismatch; conditionally maintains and restores engine scalar values.
- **Builds 47–48:** opt-in Mono HUD Optical Convergence, adjustable 2–200 m, Quad/Cylinder layer support, follows-view and UI-composition compatibility.
- **Build 48:** opt-in Mono Eye Alignment, −3% to +3% total horizontal alignment using OpenXR FOV tangents for Mono ID5 and DuoView ID6.
- **Build 49:** preserves the enabled state and exact alignment percentage across `Reset Runtime`, with range checking and diagnostic logging.
- Retains v186.1 fovea-only Glamarye sharpen and v182's foveated two-view monoscopic rendering.
- Release notes: [full details](RELEASE_NOTES_V1861_MPC_HUD_EYEALIGNMENT_PERSIST49.md).

## [v186.1 Glamarye](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.1-glamayre) — 2026-10-20

- Integrates fovea-only Glamarye Bigger Sharpen into the existing D3D12 compositor.
- Adjustable 0–2.0 sharpening, fresh-profile default 1.0; no separate external OpenXR sharpening pass.
- Retains the v182 DuoView Mono source/rendering behavior.
- Release notes: [Glamarye](RELEASE_NOTES_V186_GLAMARYE.md).

## [v182](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v182) — 2026-10-19

- Preserves the source and downloadable assets of the user-tested DuoView Build 182 baseline.
- Two-view gaze-driven fovea/periphery composition, delivery/frame-state logic and stable monoscopic headset output.
- Maintains original dependency/source provenance and compatibility tests.
- Release notes: [v182](RELEASE_NOTES_v182.md).

### Release policy

An explicitly **headset-validated** feature means it was observed working in-game, not that it is certified across machines or games. New functionality may be CI-verified only until tested on hardware. Earlier release assets and tags remain intact; experimental Quad Views and DIBR work is not implicitly incorporated into this release.

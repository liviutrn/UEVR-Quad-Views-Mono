# Changelog

This changelog covers **published stable releases**. Experimental Quad Views, DIBR and diagnostics builds are **not** promoted here.

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

"Stable" here means **tested and accepted by the project owner on the stated hardware and game**, not general multi-game/headset certification. Tags and assets for prior stable releases are preserved unchanged. Later diagnostic, Quad Views, and DIBR experiments are not implicitly part of any stable release.

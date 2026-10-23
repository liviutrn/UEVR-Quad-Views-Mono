# v186.1 — MPC, HUD and Mono Eye Alignment Persistence (Build 49 / CI 56)

**Latest user-tested stable DuoView release — 23 October 2026.**

This release packages the **unchanged, successfully built and user-tested** `UEVR-Quad-Views-Mono-v186.1-MPC-HUD-EyeAlignment-Persist49-56.zip` from GitHub Actions run **#56**, rather than rebuilding from later experimental branches. It advances the earlier v186.1 Glamarye release without replacing the v182 baseline.

## What's changed since v186.1 Glamarye

### Foreground and first-person FOV parity (Build 45)
- S.T.A.L.K.E.R. 2's `MPC_FOV` scalar parameters are reconciled while **DuoView / ID 6** is active: `IsFOVEnabled = 0`, `DepthScale = 1`.
- Fixes the visible scale/FOV discontinuity between foveal and peripheral renders of held weapons, hands, detectors and other first-person objects.
- The override remembers original parameter values and restores them on mode exit. It caches and validates the Unreal object identities; it writes only when a value has drifted.

### Mono HUD optical convergence (Builds 47–48)
- Adds an **opt-in** `Mono HUD Optical Convergence` setting and a **2–200 m** optical distance control.
- Preserves the on-screen HUD's apparent size and offsets while shifting its effective optical depth.
- Build 48 extends this to OpenXR **Quad and Cylinder** game-UI layers, with `UI Follows View` enabled or disabled and supported per-eye UI composition.
- Supported in **Mono ID 5** and **DuoView ID 6**. A crosshair baked into the game scene cannot be moved by a UI-layer-only setting.
- Disabled by default; native stereo and other UEVR modes retain their original behavior.

### Mono Eye Alignment (Build 48)
- Adds a **presentation-only, opt-in horizontal alignment** adjustment for the two submitted Mono eye views, **−3% to +3% total**, with a reset-to-zero control.
- Adjusts the **final OpenXR projection FOV tangents**; does not change Unreal scene rendering, foveal crop, gaze, motion vectors, pose, shaders, SteamVR settings or add an OpenXR layer.
- Applies to **Mono ID 5 / DuoView ID 6** only. The default is **OFF / 0%**. Calibration is user-specific; do not assume any particular percentage is universally appropriate.
- Keep `Virtual Desktop Fix` OFF when evaluating this setting and verify comfort and head-turn behavior.

### Runtime reset persistence (Build 49)
- **Reset Runtime no longer discards the live Mono Eye Alignment toggle or calibrated percentage.**
- Values are saved before OpenXR teardown and restored to the new runtime object, including across repeated resets.
- Validates that the saved percentage is finite and within range; logs the restored values.
- This fix is limited to reset lifecycle/state. It does **not** alter the render path or calibration math.

## Retained from v186.1 and v182

- Eye-tracked two-view **DuoView Mono**: high-detail fovea plus low-resolution full-field periphery.
- Native Stereo Fix-backed source rendering, gaze handling and frame delivery proven in Build 182.
- Integrated **Glamarye Bigger Sharpen** on the fovea, range 0.0–2.0, fresh-profile default 1.0; no separate OpenXR sharpen layer is required.
- Adjustable fovea geometry, density, periphery scale and blending; original UEVR Mono and Native modes remain separate.

## Installation

1. Download **`UEVR-Quad-Views-Mono-v186.1-MPC-HUD-EyeAlignment-Persist49-56.zip`** from **this release's Assets** and verify against its accompanying `.zip.sha256` file.
2. Extract to a **separate directory**, preserving your previous known-good setup.
3. Read the packaged **`READ_FIRST.txt`**; launch the included frontend/backend as directed.
4. Select **DuoView / rendering ID 6** for the dual-view monoscopic pipeline. Mono ID 5 also supports the Mono HUD/Eye Alignment controls.
5. Optionally configure Mono HUD Optical Convergence and Mono Eye Alignment. Both are OFF by default. Existing saved settings can override fresh-profile defaults.
6. Disable any **external Glamarye OpenXR sharpening layer** to avoid double sharpening.

## Tested scope and limitations

- **User-confirmed working:** S.T.A.L.K.E.R. 2 (DX12/OpenXR), PSVR2 + SteamVR/PSVR2 Toolkit; user confirmed on 23 October 2026 that Build 49/CI56 works well and improves their setup.
- **CI-confirmed:** GitHub Actions [run #56](https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/39853198565) completed successfully on the pinned backend, frontend and dependencies.
- **Still DuoView Mono**, **not** native stereo quad-views or depth-image-based stereo. Both headset eyes receive the same composed scene (aside from the optional presentation alignment).
- Other games, runtimes and hardware configurations are not validated by the above test. Avoid enabling competing external sharpening and optical-offset layers without checking their interaction.

## Binary identity and source provenance

- **Exact tested source commit:** [`60d0aae86949723d21266e4121a833f0191729c2`](https://github.com/liviutrn/UEVR-Quad-Views-Mono/commit/60d0aae86949723d21266e4121a833f0191729c2)
- **Exact successful CI run:** [#56](https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/39853198565)
- **Actions artifact ID:** `12459542202`
- **Actions artifact archive SHA-256:** `5ad8dbecf0dddb2e1da71f0a54ce1e06f684bae88803cb0e0892d3570b25125a` (this is the *outer Actions artifact archive* digest, not the inner distributable ZIP digest)
- The downloadable release includes the **original inner ZIP** and its **original SHA-256 sidecar**, published without rebuilding or repackaging.
- The Git tag points to the **exact CI56 build source commit**.

## Credits and license

This community fork builds on [praydog's UEVR](https://github.com/praydog/UEVR), [Joey's UEVR](https://github.com/joeyhodge/UEVR), [PSVR2 Toolkit](https://github.com/BnuuySolutions/PSVR2Toolkit), and Glamarye Fast Effects for ReShade by Robert Jessop (MIT). See [NOTICE.md](NOTICE.md), [COPYING](COPYING), and [RELEASE_NOTES_V186_GLAMARYE.md](RELEASE_NOTES_V186_GLAMARYE.md) on the repository's main branch for project licenses and attribution.

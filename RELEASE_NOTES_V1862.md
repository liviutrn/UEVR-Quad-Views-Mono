# v186.2 — DuoView FOV Recovery & Configurable Runtime Hotkeys

**Release date:** 2026-10-27  
**Package:** `UEVR-Quad-Views-Mono-v205-FOV-Runtime-Hotkeys-206.zip`  
**Reproducible binary:** GitHub Actions [run #206](https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/40562995836), source commit `915226735b03dc736028f01b93cb39a20efe81cb`.

This public release promotes the #206 build. It preserves the existing DuoView monoscopic foveal/peripheral renderer and adds a verified manual recovery procedure for S.T.A.L.K.E.R. 2 foreground FOV differences after a save load, with two configurable keyboard shortcuts. It is **not** the experimental native-stereo or depth-reprojection implementation.

## Highlights

- **Manual foreground FOV recovery, validated in-game in build #205:** The **Reapply DuoView FOV** button beside **Reinitialize Runtime** rebinds the validated Unreal `MPC_FOV` material parameter collection when needed, including an on-demand fallback to Unreal's global object registry. It explicitly applies `IsFOVEnabled=0` and `DepthScale=1` and verifies both effective scalar values on the game thread.
- **FOV recovery shortcut, new in build #206:** Configurable `Reapply DuoView FOV Key`. It invokes the same recovery path as the button.
- **Runtime-reset shortcut, new in build #206:** Configurable `Reinitialize Runtime Key`, using UEVR's existing OpenXR runtime reset.
- **One-key sequence:** Both actions may be bound to the same physical key. One press requests the runtime reset **first**; after a successful OpenXR initialization, at least 850 ms and a ready DuoView gameplay world, the FOV correction is requested. It is never applied during runtime teardown. The deferred action stops after a 30-second timeout if readiness does not return.
- **Unchanged working behavior:** The original DuoView view capture, D3D12 compositor, foveal/peripheral geometry, optical eye alignment, HUD logic and XYZ head scaling are preserved from the tested baseline. The on-screen recovery button also remains unchanged.
- **Default behavior:** Both new keybindings are **Unbound** until configured. There is no automatic scene-load detector or automatic runtime-reset loop.

## Using the keybinds

1. In UEVR open **VR → Keybinds → Overlay/Runtime Keys**.
2. Bind **Reapply DuoView FOV Key** to run the repair without resetting VR.
3. Bind **Reinitialize Runtime Key** to request UEVR's standard reset.
4. Optionally assign the **same key** to both settings to execute **reset → recovery** in sequence. Save your UEVR settings.
5. If a save load produces a foreground FOV mismatch, activate the keybind while DuoView rendering mode **ID 6** is selected. The existing **Reapply DuoView FOV** on-screen button remains an alternative.

## Compatibility, tests and limitations

- **Target:** S.T.A.L.K.E.R. 2, DirectX 12, UEVR DuoView ID 6, SteamVR/OpenXR. Eye-tracked foveation can use PlayStation VR2 Toolkit; fixed-center operation does not require eye tracking.
- The binary was compiled in GitHub Actions **#206**, with the original UEVR compatibility suite, geometry/GPU contract tests and integrity checks passing. The #205 working FOV controller and manual button were compared byte-for-byte against the build before hotkeys were added.
- The **#205 manual FOV recovery was confirmed working in an actual save-reload test**. The **new #206 keyboard shortcuts and combined-key sequence passed compilation and static regression checks but have not yet been independently headset-tested**. Keep a previously working installation as a fallback.
- DuoView ID 6 remains **monoscopic**: both headset eyes receive the same composed image. True stereo, Quad Views OpenXR extension and DIBR prototypes are not included.
- The combined-key sequence is designed for OpenXR and DuoView ID 6; OpenVR is not a supported combined reset-plus-FOV path. If runtime initialization fails or the game never becomes ready, automatic follow-up is cancelled or times out.
- This release does not guarantee compatibility with other games, non-DX12 rendering paths or other UEVR revisions.

## Installation, verification and history

Download the release ZIP **and its adjacent `.zip.sha256` checksum file**. Verify the ZIP SHA-256, extract into a separate directory, and follow the included `READ_FIRST.txt`. Do not overwrite a known-working installation until the new keybinds have been tested.

Previous public releases remain available: [v186.1 MPC/HUD/Eye Alignment](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.1-mpc-hud-eyealignment-persist49-56), [v186.1 Glamarye](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.1-glamayre), [v182](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v182), plus the [Build #165 rollback package](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.1-build165-xyz-rollback). See [CHANGELOG.md](CHANGELOG.md) for the complete stable-release timeline.

## Privacy, attribution and licensing

Release notes intentionally contain no private user details, contact information, machine-specific paths, raw runtime logs, credentials or saved game data. This archive is a compiled UEVR distribution, not an export of a personal settings profile. The public repository namespace and acknowledged upstream project names remain for attribution.

This is an independent community project. See [COPYING](COPYING), [NOTICE.md](NOTICE.md) and the [README](README.md) for GPL v3 and upstream attribution.

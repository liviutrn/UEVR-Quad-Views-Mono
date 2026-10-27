# UEVR Quad Views Mono

**Eye-tracked foveated rendering for Unreal Engine VR, built on Joey's UEVR.**

UEVR Quad Views Mono is an experimental rendering extension that prioritizes image quality where you are looking and reduces rendering resolution in peripheral vision. It combines a detailed, gaze-positioned **foveal view** with a lower-resolution **full-field peripheral view**, then composites both into a single image for VR display.

The goal is **higher effective resolution and better GPU efficiency** in demanding Unreal Engine games, particularly at high SteamVR render resolutions where pixel and shader workload — rather than CPU performance — is the bottleneck.

**Latest release:** [v186.2 — FOV Recovery & Runtime Hotkeys (Build #206)](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.2) · **Previous headset-tested FOV recovery:** [Build #205](https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/40554258531) · **Previous stable release:** [v186.1 MPC/HUD/Eye Alignment](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.1-mpc-hud-eyealignment-persist49-56) · **Original baseline:** [v182](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v182)

**Supported integration:** S.T.A.L.K.E.R. 2 (DX12 / OpenXR). Eye tracking: optional PlayStation VR2 Toolkit. **Validation:** the #205 manual FOV repair was headset-tested; #206's new keyboard shortcuts passed automated tests but still require a headset test.

> **Current stable architecture: DuoView Mono, not native stereo quad views.** The released build renders two differently detailed Unreal Engine views from a shared monoscopic camera, blends them and presents the same resulting image to both eyes. It does **not** yet render four independent left/right focus-and-context views, implement an OpenXR quad-views extension, or provide binocular stereo depth. The project name reflects its quad-view-inspired rendering approach and direction.

## How it works

Traditional VR rendering often spends substantial GPU time shading pixels in both eyes, including areas where the user is not looking. DuoView instead allocates detail unevenly within a common full-field monoscopic projection:

1. **Foveal view:** a high-density, cropped Unreal Engine view following the user's gaze (or a fixed center).
2. **Peripheral view:** a full-field Unreal Engine view rendered at a lower spatial resolution.
3. **Composition:** the two current-frame sources are aligned using their shared camera/projection and joined with a configurable feathered transition.
4. **VR output:** UEVR's OpenXR path submits the final monoscopic image to both headset eyes.

```text
                 Unreal Engine / UEVR
                   shared Mono pose
                          |
               +----------+----------+
               |                     |
        Foveal scene view     Peripheral scene view
       high-detail crop        low-resolution context
               |                     |
               +----------+----------+
                          |
                 D3D12 compositor
             gaze alignment + feather
                          |
               Full-field Mono frame
                          |
                  OpenXR / SteamVR
                   left eye = right eye
```

Unlike a simple post-processing blur or a headset-side foveation mask, DuoView works with **two Unreal scene views** and composes their rendered results. The implementation uses Joey's Native Stereo Fix rendering infrastructure to obtain compatible source views while retaining the Mono delivery path.

## Features

- **Eye-tracked foveation** using the [PlayStation VR2 Toolkit](https://github.com/BnuuySolutions/PSVR2Toolkit) CAPI, with a fixed-center option.
- **Adjustable focus area:** foveal crop width and height, foveal pixel density, peripheral resolution scale and transition feathering.
- **Gaze placement controls:** position offsets, crop stabilization, quantization and handling of transient invalid gaze samples.
- **D3D12 scene composition** of a high-detail focus view and low-detail full-field context.
- **Shared camera pose and frame-aligned composition** to keep focus and peripheral images spatially consistent.
- **Native Stereo Fix-backed source rendering** in the dedicated DuoView pipeline, while retaining conventional UEVR rendering modes separately.
- **OpenXR output through UEVR**, including SteamVR-based PC VR setups.
- **Integrated Glamarye Bigger Sharpen (v186.1):** fovea-only D3D12 sharpening in the existing compositor, adjustable strength **0.0–2.0** (fresh-profile default **1.0**), with edge protection and no separate OpenXR sharpening layer. See [release notes](RELEASE_NOTES_V186_GLAMARYE.md).
- **Foreground MPC parity (Build 45):** automatic STALKER 2 `MPC_FOV` correction while DuoView ID6 is active, fixing first-person hands and weapons appearing at different scales across foveal/peripheral views.
- **Mono HUD optical convergence (Builds 47–48):** optional 2–200 m HUD distance, preserving apparent size and position across compatible OpenXR Quad/Cylinder layers.
- **Mono Eye Alignment (Build 48):** optional horizontal OpenXR projection adjustment, −3% to +3% total, for Mono ID5 and DuoView ID6; OFF by default.
- **Reset Runtime persistence (Build 49):** preserves the alignment toggle and exact percentage across OpenXR runtime reset. See the [v186.1 release notes](RELEASE_NOTES_V1861_MPC_HUD_EYEALIGNMENT_PERSIST49.md).
- **Foreground FOV save-load recovery (Build #205):** user-invoked **Reapply DuoView FOV** button, beside **Reinitialize Runtime**, restores the STALKER 2 `MPC_FOV` values after save reloads, using the validated global Unreal object lookup if necessary. Applies `IsFOVEnabled=0` and `DepthScale=1` and verifies readback. This was confirmed working in-game.
- **Two configurable recovery hotkeys (Build #206):** **Reapply DuoView FOV Key** and **Reinitialize Runtime Key**, both Unbound by default. Binding both to the same key schedules runtime reset first and then one delayed FOV reapply after OpenXR/gameplay readiness. The original manual button remains available. See the [v186.2 release notes](RELEASE_NOTES_V1862.md) and [changelog](CHANGELOG.md).

The dedicated rendering option is **DuoView (rendering mode ID 6)**. This is distinct from Joey's standard Mono and Native Stereo modes.

## Performance

Under favorable high-resolution, GPU-bound conditions, DuoView could deliver **up to 50% higher FPS than standard Mono** and **up to 85% higher FPS than Native Stereo**.

Estimates are derived from **S.T.A.L.K.E.R. 2** testing on an **RTX 5070** at **3136 × 2768** and **4060 × 3584**, using **DLSS Performance**, a **50% × 50% eye-tracked foveal crop**, and **0.20× peripheral resolution**; the FPS gains are extrapolated from GPU utilization under a 40 FPS cap, not directly measured uncapped results.

## Compatibility and requirements

Build #206 retains the pinned #205 DuoView renderer and headset stack, with integrated sharpening, foreground FOV, HUD, eye-alignment and XYZ head-scaling enhancements:

- **Windows PC** with a DirectX 12-capable GPU
- **S.T.A.L.K.E.R. 2** using the DX12 renderer
- **UEVR** with the Joey-derived DuoView modifications
- **OpenXR runtime**, including SteamVR on the tested PC VR configuration
- **Optional PSVR2 eye tracking** via PlayStation VR2 Toolkit for gaze-driven focus; fixed-center foveation does not require gaze input

Other Unreal Engine titles, headset configurations, rendering APIs and UEVR versions are not established as compatible with this tested release. This is an independent experimental fork, not an official UEVR feature.

### Image quality and limitations

DuoView's current output is **monoscopic**: both eyes receive the same composed image. It retains headset tracking and a full-field VR presentation, but lacks the true binocular disparity of native stereo. The transition between detail levels can also expose differences in temporal effects, lighting, reflections or peripheral shading depending on the game.

Foveal area, density and peripheral scale trade visual quality against rendering cost. Increasing foveal density or peripheral resolution can quickly increase workload and memory pressure, especially at very high SteamVR resolutions. Performance depends on the game, scene, GPU, frame cap, upscaler and runtime settings.

## Download and use

**[Download latest release — v186.2 / Build #206](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.2)**

The previous [v186.1 MPC/HUD/Eye Alignment](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.1-mpc-hud-eyealignment-persist49-56), [v186.1 Glamarye](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.1-glamayre), [v182 baseline](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v182), and [Build #165 rollback](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.1-build165-xyz-rollback) remain available with their original assets.

1. Download `UEVR-Quad-Views-Mono-v205-FOV-Runtime-Hotkeys-206.zip` and `UEVR-Quad-Views-Mono-v205-FOV-Runtime-Hotkeys-206.zip.sha256` from the **v186.2 release assets**. Verify the ZIP checksum.
2. Extract into a **separate installation** and follow the included `READ_FIRST.txt`; keep the prior known-working version for rollback.
3. Select DuoView **rendering mode ID 6**.
4. Use the existing **Reapply DuoView FOV** button beside **Reinitialize Runtime** if a save load changes foreground geometry.
5. To use hotkeys, open **UEVR → VR → Keybinds → Overlay/Runtime Keys**. Set `Reapply DuoView FOV Key` and `Reinitialize Runtime Key` separately, or bind both to one key for reset-first-then-FOV behavior. Both start Unbound; save the settings.

The shared-key reset/FOV sequence waits for OpenXR reinitialization to finish, followed by a short delay and an active ready game world; it times out instead of resetting repeatedly. The on-screen #205 FOV recovery was confirmed working after save reloads. The new #206 keybind sequence is CI-tested but not yet headset-validated.

Existing saved sharpening settings may override the fresh-profile **1.0** default; set to **0.0** to disable. Disable an external Glamarye OpenXR layer to avoid applying sharpening twice. Mono HUD Convergence and Eye Alignment default to OFF. [v186.2 release notes](RELEASE_NOTES_V1862.md) contain controls, known limitations and provenance. Historical `SHA256SUMS` and `PROVENANCE.json` describe earlier binary baselines, **not** the new #206 ZIP.

## Source code and development

This repository carries the **DuoView implementation and integration patches**, alongside a reproducible build workflow based on pinned upstream UEVR components.

- [`duoview/`](duoview/) — foveal/peripheral layout, gaze handling, frame-state contracts, D3D12 composition shaders and Joey integration patches.
- [`.github/workflows/duoview-joey-stage234.yml`](.github/workflows/duoview-joey-stage234.yml) — manually triggered Windows build of the pinned backend, frontend and DuoView extension.
- [`build-182` branch](https://github.com/liviutrn/UEVR-Quad-Views-Mono/tree/build-182) — preserved v182 source baseline.
- [`release/v186-glamayre-default-1-20261020` branch](https://github.com/liviutrn/UEVR-Quad-Views-Mono/tree/release/v186-glamayre-default-1-20261020) — prior v186.1 integrated sharpening source.
- [`fix/duoview-v49-openxr-alignment-persistence-20261022` branch](https://github.com/liviutrn/UEVR-Quad-Views-Mono/tree/fix/duoview-v49-openxr-alignment-persistence-20261022) — source of the exact user-tested CI56 stable binary ([commit `60d0aae`](https://github.com/liviutrn/UEVR-Quad-Views-Mono/commit/60d0aae86949723d21266e4121a833f0191729c2)).
- [Build #206 source branch](https://github.com/liviutrn/UEVR-Quad-Views-Mono/tree/feature/v205-duoview-fov-and-runtime-hotkeys-20261027) — source of CI build #206; FOV recovery inherited unchanged from Build #205.
- [`CHANGELOG.md`](CHANGELOG.md) — preserved release history, from v182 through v186.2; [latest release notes](RELEASE_NOTES_V1862.md) — setup, validation status and limitations.
- [`PROVENANCE.json`](PROVENANCE.json) — exact upstream revisions and published binary provenance.

Building requires authorized access to the pinned **`joeyhodge/UESDK`** dependency, supplied to GitHub Actions through the `UEVR_SOURCE_TOKEN` repository secret (or supported legacy `PAT_TOKEN`). That restricted dependency is not bundled in this repository.

### Upstream projects and credits

UEVR Quad Views Mono builds on work from the following projects and authors:

| Project | Contribution |
| --- | --- |
| [**UEVR — praydog**](https://github.com/praydog/UEVR) | Original Unreal Engine VR injector and ecosystem. |
| [**Joey's UEVR fork**](https://github.com/joeyhodge/UEVR) | Backend, Mono rendering path and Native Stereo Fix infrastructure used by DuoView. |
| [**Joey's UEVR frontend**](https://github.com/joeyhodge/uevr-frontend) | Frontend basis and rendering-mode integration. |
| [**joeyhodge/UESDK**](https://github.com/joeyhodge/UESDK) | Unreal Engine SDK dependency used by the pinned backend (access restricted). |
| [**PlayStation VR2 Toolkit — BnuuySolutions**](https://github.com/BnuuySolutions/PSVR2Toolkit) | PlayStation VR2 eye-tracking interface and calibration support. |

The v182 baseline is pinned to [OpenNR commit `67c6e1e`](https://github.com/liviutrn/OpenNR/commit/67c6e1ec5b931d2922e0ef5d253b8e9bef7a1a80); the exact Joey backend, SDK and frontend commits are documented in [`NOTICE.md`](NOTICE.md) and [`PROVENANCE.json`](PROVENANCE.json).

## License

Source files are provided under the **GNU GPL v3** as documented in [`COPYING`](COPYING) and [`NOTICE.md`](NOTICE.md). Upstream components retain their respective licensing and attribution requirements. PlayStation VR2 Toolkit has its own usage terms, including restrictions on commercial use of its eye-tracking data.

This is an independent community project, **not affiliated with or endorsed by** praydog, Joey, BnuuySolutions, Sony, Epic Games, GSC Game World or the maintainers of the referenced software.

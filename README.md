# UEVR Quad Views Mono


> **Experimental offline depth proof (2026-10-23):** This branch starts from the user-validated v186.1 Build49 baseline and adds one opt-in depth-to-disk diagnostic. The failed P1/S0 stereo experiments are absent. See [test directions](duoview/depth_proof/README.md) and [source audit / architecture review](duoview/depth_proof/TAKEOVER_REVIEW.md). Windows WARP tests verify known-depth readbacks; STALKER 2 scene-depth acquisition remains unverified until exported samples are inspected. Stable branch and release are unchanged.

**Eye-tracked foveated rendering for Unreal Engine VR, built on Joey's UEVR.**

UEVR Quad Views Mono is an experimental rendering extension that prioritizes image quality where you are looking and reduces rendering resolution in peripheral vision. It combines a detailed, gaze-positioned **foveal view** with a lower-resolution **full-field peripheral view**, then composites both into a single image for VR display.

The goal is **higher effective resolution and better GPU efficiency** in demanding Unreal Engine games, particularly at high SteamVR render resolutions where pixel and shader workload — rather than CPU performance — is the bottleneck.

**Current release:** [v186.1 — Integrated Glamarye Sharpen](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.1-glamayre) · **Stable baseline:** [v182](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v182) · **Current game integration:** S.T.A.L.K.E.R. 2 (DX12 / OpenXR) · **Eye tracking:** PlayStation VR2 Toolkit

> **Current architecture: DuoView Mono, not native stereo quad views.** Version 182 renders two differently detailed Unreal Engine views from a shared monoscopic camera, blends them and presents the same resulting image to both eyes. It does **not** yet render four independent left/right focus-and-context views, implement an OpenXR quad-views extension, or provide binocular stereo depth. The project name reflects its quad-view-inspired rendering approach and direction.

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

The dedicated rendering option is **DuoView (rendering mode ID 6)**. This is distinct from Joey's standard Mono and Native Stereo modes.

## Performance

Under favorable high-resolution, GPU-bound conditions, DuoView could deliver **up to 50% higher FPS than standard Mono** and **up to 85% higher FPS than Native Stereo**.

Estimates are derived from **S.T.A.L.K.E.R. 2** testing on an **RTX 5070** at **3136 × 2768** and **4060 × 3584**, using **DLSS Performance**, a **50% × 50% eye-tracked foveal crop**, and **0.20× peripheral resolution**; the FPS gains are extrapolated from GPU utilization under a 40 FPS cap, not directly measured uncapped results.

## Compatibility and requirements

Version 186.1 uses the same pinned v182 renderer and headset stack, with integrated sharpening:

- **Windows PC** with a DirectX 12-capable GPU
- **S.T.A.L.K.E.R. 2** using the DX12 renderer
- **UEVR** with the Joey-derived DuoView modifications
- **OpenXR runtime**, including SteamVR on the tested PC VR configuration
- **Optional PSVR2 eye tracking** via PlayStation VR2 Toolkit for gaze-driven focus; fixed-center foveation does not require gaze input

Other Unreal Engine titles, headset configurations, rendering APIs and UEVR versions are not established as compatible with v182. This is an independent experimental fork, not an official UEVR feature.

### Image quality and limitations

DuoView's current output is **monoscopic**: both eyes receive the same composed image. It retains headset tracking and a full-field VR presentation, but lacks the true binocular disparity of native stereo. The transition between detail levels can also expose differences in temporal effects, lighting, reflections or peripheral shading depending on the game.

Foveal area, density and peripheral scale trade visual quality against rendering cost. Increasing foveal density or peripheral resolution can quickly increase workload and memory pressure, especially at very high SteamVR resolutions. Performance depends on the game, scene, GPU, frame cap, upscaler and runtime settings.

## Download and use

**[Download v186.1 — Integrated Glamarye Sharpen](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.1-glamayre)**

The original [v182 baseline](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v182) is still available unchanged. Integrated sharpening can be disabled by setting strength to **0.0**.

1. Download **the v186.1 Glamarye ZIP** from the release assets.
2. Extract it into a separate directory rather than overwriting a known-good UEVR setup.
3. Follow the included **`READ_FIRST.txt`** for the packaged build's actual installation and mode-selection instructions.
4. Select the dedicated **DuoView / ID 6** rendering mode and tune the fovea, periphery and gaze options to suit your headset and performance target.

The original v182 binary package is preserved without modification. Existing saved sharpening settings may override the new **1.0** default. Disable the separate Glamarye OpenXR layer to avoid applying sharpening twice. NVIDIA Smooth Motion was disabled in the reported smooth headset test. See [v186.1 modifications](RELEASE_NOTES_V186_GLAMARYE.md). For archive integrity and exact build identification, see [`SHA256SUMS`](SHA256SUMS) and [`PROVENANCE.json`](PROVENANCE.json).

## Source code and development

This repository carries the **DuoView implementation and integration patches**, alongside a reproducible build workflow based on pinned upstream UEVR components.

- [`duoview/`](duoview/) — foveal/peripheral layout, gaze handling, frame-state contracts, D3D12 composition shaders and Joey integration patches.
- [`.github/workflows/duoview-joey-stage234.yml`](.github/workflows/duoview-joey-stage234.yml) — manually triggered Windows build of the pinned backend, frontend and DuoView extension.
- [`build-182` branch](https://github.com/liviutrn/UEVR-Quad-Views-Mono/tree/build-182) — preserved v182 source baseline.
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

The v182 implementation is pinned to [OpenNR commit `67c6e1e`](https://github.com/liviutrn/OpenNR/commit/67c6e1ec5b931d2922e0ef5d253b8e9bef7a1a80); the exact Joey backend, SDK and frontend commits are documented in [`NOTICE.md`](NOTICE.md) and [`PROVENANCE.json`](PROVENANCE.json).

## License

Source files are provided under the **GNU GPL v3** as documented in [`COPYING`](COPYING) and [`NOTICE.md`](NOTICE.md). Upstream components retain their respective licensing and attribution requirements. PlayStation VR2 Toolkit has its own usage terms, including restrictions on commercial use of its eye-tracking data.

This is an independent community project, **not affiliated with or endorsed by** praydog, Joey, BnuuySolutions, Sony, Epic Games, GSC Game World or the maintainers of the referenced software.

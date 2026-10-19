# UEVR Quad Views Mono — v182

**Stable DuoView Mono baseline · Eye-tracked foveated rendering for Unreal Engine VR**

UEVR Quad Views Mono brings **two-resolution, gaze-guided scene rendering** to Joey's UEVR fork. Instead of rendering the entire image at uniformly high density, DuoView combines a detailed focus region with a lower-resolution full-field peripheral view. A D3D12 compositor blends the sources into one image for the headset.

This release preserves the **original v182 binaries unchanged**.

## Highlights

- **Engine-level foveated rendering:** a high-detail cropped Unreal Engine scene view and a low-resolution full-field context view share one Mono camera pose.
- **PSVR2 eye tracking:** the focus region follows gaze via PlayStation VR2 Toolkit; fixed-center foveation is also available.
- **Adjustable image quality:** control foveal area and pixel density, peripheral resolution, feathering and gaze offsets.
- **Stable frame and gaze handling:** v182 resolved previously observed flicker, stutter, gaze jumps and image trembling on the tested PSVR2 setup.
- **Joey UEVR integration:** D3D12 composition, Native Stereo Fix-backed source rendering, dedicated DuoView rendering mode **ID 6**, and OpenXR output.

### Performance potential

The main objective is **better image clarity per unit of GPU work**, particularly at **high VR render resolutions in GPU-bound scenes** where the CPU/game thread is not the limiting factor.

For example, a **50% × 50% fovea at 1× density plus 0.20× linear-resolution periphery** has a nominal source-view pixel budget of **29% of one full-resolution monoscopic frame** (25% focus + 4% context). This is a *theoretical pixel count*, not an equivalent reduction in total GPU time: full-size intermediate textures, Unreal rendering passes, lighting, upscaling and composition still cost performance.

### Measured comparisons with normal Mono and Native Stereo

In **S.T.A.L.K.E.R. 2**, development builds were compared at matched output resolution and screen percentage on an **RTX 5070**, with **motion smoothing forced** and a **40 FPS ceiling**:

| Build | Resolution | Screen percentage | Normal Mono | DuoView | Normal Native Stereo |
| --- | --- | ---: | --- | --- | --- |
| v24 | 4060 × 3584 | 50% | 95% GPU / 38 FPS | **66% GPU / 40 FPS** | — |
| v168 | 3136 × 2768 | 100% | 97% GPU / 36 FPS | **72% GPU / 40 FPS** | — |
| v168 | 3136 × 2768 | 50% | 74% GPU / 40 FPS | **67% GPU / 40 FPS** | 97% GPU / 31 FPS |

- **Versus Mono:** DuoView used **30.5% less GPU** at 4060 × 3584 (95% → 66%), and **25.8% less** at 3136 × 2768 / 100% screen percentage (97% → 72%). Observed FPS increased by **5.3%** (38 → 40) and **11.1%** (36 → 40), respectively.
- **Versus Native Stereo:** At 3136 × 2768 / 50% screen percentage, DuoView used **30.9% less GPU** (97% → 67%) and achieved **29.0% higher FPS** (31 → 40). At that setting it also used **9.5% less GPU than normal Mono** (74% → 67%) while both modes reached 40 FPS.

“Less GPU” means a **relative reduction in the reported GPU-utilization percentage**, not a measured equal reduction in GPU frame time. Screen percentage is a render-scale setting, **not foveal crop size**. The 40 FPS limit and motion smoothing constrain interpretation of the FPS numbers. These are **v24/v168 development measurements, not v182 benchmarks**, and results vary with GPU load, scene, CPU/game-thread bottlenecks and renderer overhead.

### Important distinction

**v182 is DuoView Mono, not true stereoscopic Quad Views.** It creates two Unreal Engine source views (focus and periphery) from a shared Mono camera, composites them, and displays the **same final image to both eyes**. It does not generate four independent left/right focus and peripheral views or implement the OpenXR quad-views extension. True stereo parallax is not present in this release.

## Compatibility

- **Game:** S.T.A.L.K.E.R. 2 (DirectX 12)
- **Runtime:** OpenXR, including a SteamVR-based PSVR2 setup
- **Eye tracking:** PlayStation VR2 Toolkit (optional for fixed-center operation)
- **Platform:** Windows PC with a DX12-capable GPU
- **Renderer option:** DuoView / **ID 6**

Other games, headsets and rendering configurations are not yet established as compatible.

## Download and installation

**Download:** [`UEVR-Quad-Views-Mono-v182.zip`](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/download/v182/UEVR-Quad-Views-Mono-v182.zip)

Extract the archive in a separate folder and follow **`READ_FIRST.txt`** inside the package. Keep any existing known-good UEVR installation intact when trying this build.

Additional release assets:
- **`UEVR-Quad-Views-Mono-v182-actions-artifact.zip`** — unchanged archive from the original GitHub Actions build.
- **`SHA256SUMS`** and **`PROVENANCE.json`** — checksums, pinned source revisions and binary provenance.

## Source and credits

Based on **[praydog's UEVR](https://github.com/praydog/UEVR)** and the **[joeyhodge/UEVR](https://github.com/joeyhodge/UEVR)** backend, including Joey's Mono rendering path and Native Stereo Fix infrastructure. Uses Joey's [UEVR frontend](https://github.com/joeyhodge/uevr-frontend) and [UESDK](https://github.com/joeyhodge/UESDK), with eye-tracking integration through [PSVR2 Toolkit](https://github.com/BnuuySolutions/PSVR2Toolkit).

The exact v182 DuoView source baseline comes from [OpenNR commit `67c6e1e`](https://github.com/liviutrn/OpenNR/commit/67c6e1ec5b931d2922e0ef5d253b8e9bef7a1a80). See the [project README](README.md), [`NOTICE.md`](NOTICE.md) and [`PROVENANCE.json`](PROVENANCE.json) for implementation details, licensing and full provenance.

*Independent experimental community project; not an official UEVR, PSVR2 Toolkit or OpenXR release.*

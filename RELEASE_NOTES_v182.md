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

### Performance

Under favorable high-resolution, GPU-bound conditions, DuoView could deliver **up to 50% higher FPS than standard Mono** and **up to 85% higher FPS than Native Stereo**.

Estimates are derived from **S.T.A.L.K.E.R. 2** testing on an **RTX 5070** at **3136 × 2768** and **4060 × 3584**, using **DLSS Performance**, a **50% × 50% eye-tracked foveal crop**, and **0.20× peripheral resolution**; the FPS gains are extrapolated from GPU utilization under a 40 FPS cap, not directly measured uncapped results.

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

# DuoView AFW — Beta-6 diagnostic / Stage 1 preflight
Date: 2026-11-01  
Branch: \`experiment/duoview-afw-stage1-preflight-20261101\`  
**Status before CI: SOURCE-READ and SOURCE-PREPARED only. NOT an AFW warp prototype. No headset validation.**

## Objective and scope

Compile a **separate, non-invasive ABI/export probe** alongside the untouched stable v207 build. It checks whether the user's own \`PDAFWPlugin.dll\` can be loaded from an explicit local path and whether \`InitDevice\`, \`InitFrameWarp\`, and \`EvaluateFrameWarp\` are exported. It intentionally **never invokes any of those functions**: doing so without an isolated binary ABI and GPU resource-ownership test is unsafe.

This does **not** satisfy Stage 1 from the shared project brief. Stage 1 requires an actual full-eye render -> color/depth/motion -> AFW warp -> opposite-eye OpenXR submission. That is not implemented here.

## Source findings (SOURCE-READ)

The independent Witcher3VR MIT bridge describes beta-5 \`FrameWarpEvaluateParams\` with a reserved float-array starting at offset 132. PureDark's AFW interface inserts a \`ShadingRate\` value at 132 and moves reserved entries to 136; the full x64 structure size may still be 184 bytes. The program statically validates **our declarations**, not the unseen DLL internals.

Source:
- https://github.com/tig3rmast3r/witcher3-vr/blob/main/src/puredark_afw_bridge.h
- https://github.com/PureDark/UEVR/blob/AFW/dependencies/pd-afwmod/include/PDAFWPlugin.h
- https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/claude/v207-auto-fov-vram-periphery/.github/workflows/duoview-joey-stage234.yml

## Files added

- \`duoview/afw/afw_abi_probe.cpp\`: x64 layout checks and external DLL export detection; no proprietary code or binaries
- \`duoview/afw/CMakeLists.txt\`: Windows 64-bit build and self-test
- \`duoview/afw/README.md\`: user instructions and limitations
- \`.github/workflows/duoview-afw-abi-preflight.yml\`: isolated copy of v207 workflow; adds diagnostic build/test and artifact, explicitly labels baseline as Mono, not AFW Stereo
- This document and a branch-local team brief status

No v207 source patch scripts, original Joey backend, protected source, or PureDark binary are modified. The unchanged v207 chain is replayed during Windows CI.

## Gate and acceptance checklist

- [ ] Windows CI compiles the unchanged v207 chain and the diagnostic utility
- [ ] 64-bit probe's \`--self-test\` passes
- [ ] Evidence and baseline artifact packages uploaded
- [ ] Liviu runs \`AFWAbiProbe.exe "C:\full\path\PDAFWPlugin.dll"\` on a machine with stock beta 6 already installed
- [ ] DLL file version/hash and exact binary layout/calling convention verified before warp invocation
- [ ] Independent model review and full pinned local patch replay (outside CI) before Stage 1 source changes
- [ ] Only then implement one real-eye full-FOV AFW stereo submission build

## Truth labels

- **SOURCE-READ:** v207 baseline workflow source, original PureDark public API, Witcher3VR independent bridge.
- **CI-VERIFIED:** only after successful GitHub Actions result (not assumed here).
- **HEADSET-VERIFIED:** none.
- **ESTIMATED:** running the exported interface can be made compatible with beta 6; no verification yet.

Credit: PureDark (closed AFW DLL); tig3rmast3r / Witcher3VR (MIT independent bridge design). Non-commercial usage only as authorized; no DLL distributed or changed.

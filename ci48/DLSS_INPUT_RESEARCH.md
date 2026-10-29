# DLSS-native depth/MV research for DuoView

Research-only branch note (2026-10-29); **NOT included in Build48 binaries**.

## Concrete source path
- CheekyFoveatedDLSS `src/d3d12_ngx_dispatch.cpp`: D3D12 NGX evaluation dispatch, private vs public/lower callbacks, feature handle, command list, parameter object and successful result.
- Cheeky `src/fg_capture.cpp::fg_publish_ngx`: reads NGX `Depth` and `MotionVectors`, `OutWidth/OutHeight`, depth/MV subrects, `Jitter.Offset.X/Y`, `MV.Scale.X/Y`, `DLSS.Feature.Create.Flags`, and `Reset`. Its own comment cautions that there is **no frame ticket** for its FG guide recording; XR completion associates a pair.
- NVIDIA Streamline DLSS docs: DLSS-SR takes color/depth/MV inputs; DLSS-G also takes depth/MVs and frame index/common constants.

Sources:
https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/master/src/d3d12_ngx_dispatch.cpp
https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/master/src/fg_capture.cpp
https://github.com/NVIDIA-RTX/Streamline/blob/main/docs/ProgrammingGuideDLSS.md
https://github.com/NVIDIA-RTX/Streamline/blob/main/docs/ProgrammingGuideDLSS_G.md

## Experiment, separate from Build48
Add read-only NGX SR evaluation telemetry (no GPU copy): feature/handle, command list, depth/MV/resource descriptions, input subrects, output dimensions, scale, jitter, flags, reset, evaluation ordinal, and UEVR color packet/pose generation as an explicitly unverified hint. Confirm whether TWO distinct DLSS evaluations map to high-res cropped LEFT fovea and low-res full-FOV RIGHT periphery. Only after positive observation add a fence-safe capture of both NGX resources and compare same-frame raw depth to registered source colors.

Do not promote a DLSS input pointer into an authenticated engine eye/frame/stage stamp; do not enable FG or alter pacing to make the capture happen; preserve existing DSV/manual fallback and Build45 rollback.
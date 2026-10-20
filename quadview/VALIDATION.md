# QuadView validation evidence

The preserved Build182 overlay passes `scripts/verify_baseline.py` for all
84 manifest entries. The original SDK_CONTRACTS.json evidence file was
recovered unchanged from the original local export after discovering it
had been omitted from the migrated Git tree; its SHA-256 matches the
existing baseline manifest.

The five unchanged DuoView CPU suites passed locally with GCC C++20,
optimization enabled, and assertions explicitly enabled.

## Initial portable contracts and compositor shader

- Commit: `6dbecb4982321271fa4718b35542af8bbc3250e5` on
  `quadview/validation-182`.
- [Windows Actions run 39295297436](https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/39295297436).
- Windows Server 2022 / Visual Studio C++20 Release build: passed.
- `quadview-geometry-history-transaction`: passed.
- `quadview-stereo-shader-warp`: passed.
- CTest reported two of two tests passing on 2026-10-19.

The WARP test compiles the actual compositor HLSL vertex and pixel shaders
with strictness and warnings-as-errors, executes a raster pass, and reads
back every output pixel. It checks separate left/right context and focus
sources, an off-center focus ROI, spatial gradients at 1:1 focus density,
atlas-edge clamping, context-only output, and focus-only output.

This run does not compile or inject the production UEVR backend. Portable
delivery code may change after this checkpoint and must be retested. The
test does not establish engine raster completion, correct STALKER 2
histories, headset fluidity, shading parity, or GPU performance gains.

## Production compositor checkpoint

- Commit: `2ee62694f26999fedf7e1e50803008bf75e49d4c`.
- [Windows Actions run 39296237939](https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/39296237939): passed.
- Offline FXC compilation and DXBC embedding: passed.
- Portable producer/delivery/projection contracts: passed.
- Actual `QuadViewD3D12.hpp` compositor compiled and executed through WARP.
- Six GPU cases checked the standalone shader and production compositor
  against identical full-image expectations. Production packet ownership
  survived recording/execution and released only at explicit slot retirement.

This checkpoint includes production compositor validation, but not the
injected Unreal/OpenXR adapters. The preceding CI attempt captured portable
headers during an interface edit and failed compilation; the completed
checkpoint above supersedes that intermediate snapshot.

## Asynchronous delivery and resource-state checkpoint

- Commit: `6045a9dad3490551a18737ae48e8d4dacadb2541`.
- [Windows Actions run 39297505779](https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/39297505779): passed.
- All three CTest targets passed, including 100,000 transactions across
  concurrent producer/RHI threads with bounded render-ahead, reused family
  and command identifiers, UE frame-counter wrap, pose-token reuse, output
  retries, and three simulated in-flight output slots.
- Production WARP cases also exercise render-target, common, generic-read,
  and copy-destination state transitions and reject overlapping atlas regions.
- The GPU test enables the D3D12 debug layer when installed and treats its
  error/corruption messages as test failures. Debug-layer installation is
  optional; full pixel readback checks run in either case.

## Installable experimental ID7 package — Build 5

- [Successful Windows run 39337089437](https://github.com/liviutrn/OpenNR/actions/runs/39337089437).
- Compiled overlay: OpenNR `4edf095a87956be004bb1b69cc2a1b1c74035c41`.
- Matching feature source: `c25144fc5af09a51432783b3ba3978de7676561c`.
- Full backend, auxiliary DLLs, and matching frontend compiled successfully.
- All five QuadView CTests passed, including asynchronous delivery and real
  D3D12 WARP output with typed, sRGB, and typeless destination resources.
- Four pinned DuoView tests, six independent DuoView tests, and all 41
  original compatibility tests passed. Frontend rendering-ID tests passed.
- Five source-checkpoint regression tests passed. Final verification checked
  338 patched source inputs and the unchanged pinned SDK; four generated
  build products have separate hashes and generator provenance.
- [Installable artifact](https://github.com/liviutrn/OpenNR/actions/runs/39337089437/artifacts/12227388461).
- [Validation evidence](https://github.com/liviutrn/OpenNR/actions/runs/39337089437/artifacts/12227493316).

Earlier packaging verification incorrectly treated normal generated files as
reviewed source inputs; the final checker verifies those products separately.
Superseded intermediate runs are not the installable checkpoint above.

This is an opt-in STALKER 2 UE5.5 / DX12 / OpenXR prototype. Native Stereo
Fix is bypassed in ID7; fixed-center focus is used initially. Actual engine
four-view production, headset alignment, shading, performance, and the
required ten-minute gameplay acceptance remain to be tested on the user's PC.
Build182/ID6 remains the preserved baseline.

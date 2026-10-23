# Offline depth proof

## Purpose and status

This experiment is meant to answer one narrow question: can the running game provide a real, inspectable depth image through the supported UE5/DX12 path? It is designed to capture one bounded depth sample for offline inspection. It does not implement stereo, claim a fovea/periphery role, or replace the stable DuoView Mono path.

The known-good v186.1 Build49 baseline is preserved at `fix/duoview-v49-openxr-alignment-persistence-20261022` (`60d0aae86949723d21266e4121a833f0191729c2`). This branch is experimental. The independent capture code is implemented on this branch. CI compilation, static tests, and packaged files do not establish live game depth access or headset output. The capture remains unverified in STALKER 2 until a user-produced file is inspected.

## Capture behavior

The diagnostic exposes one action: **Capture depth proof (10 seconds, once per game)**. It arms one bounded observation session and stops recording after 10 seconds (the next Present processes completion and asynchronous export), whether or not a candidate is found. It never records continuously. A failed or timed-out attempt must say so explicitly and leave the selected Mono renderer untouched.

Write each completed session below Framework's persistent data root:

```text
<Framework persistent root>/depth_proof/<session_timestamp>/
```

The session contains:

- `candidate_N.pgm` and `candidate_N.bmp` — a grayscale visualization of the captured candidate. It is a display aid; its pixel values are not linear metres.
- `candidate_N.f32` — a documented floating-point readback, with dimensions and conversion recorded in the manifest. Do not label it metric depth unless the conversion and near/far mapping are measured.
- `preview.html` — open in your browser to inspect all saved candidates.
- `image_results.json` — per-image validity and raw range statistics.
- `manifest.json` — source resource identity (session-local), width, height, DXGI format, selected plane/subresource, observed state transition, command-list and queue/fence evidence, capture time/frame identifiers when available, readback conversion, and a bounded rejection histogram with representative rejected tuples.

The manifest states `view_role: "unknown"` and that fovea/periphery identity, color-frame correspondence, calibrated projection, metric units, and stereo readiness are unproven unless independently established. Do not infer those properties from texture dimensions or two successful copies.

## Evidence gates

1. Produce a non-empty image and manifest from a real game frame, or a precise timeout/rejection report.
2. Inspect the PGM and raw sample offline; confirm the image responds to scene geometry and record the exact source metadata.
3. Only then investigate pairing depth with a specific color view, view rectangle, projection, frame and pose. Stereo work remains a separate later gate.

Keep the Build49 Mono fallback available throughout. No experimental failure should silently present Mono as a successful depth view.

## Implementation and limits

Candidate discovery runs for one second, then preallocates readbacks for up to eight frequently observed candidates. The registry is bounded to 24 resources, 256 command lists and 192 transition tuples. The total readback allocation budget is 128 MiB. Frequency is only a capture-budget selector; it does not establish scene identity. Overflow and rejection counts are exported.

A candidate must have a supported depth/stencil format, one mip and array slice, one sample and extent 128..8192. Copying requires a known recording epoch, no active/suspended D3D12 render pass, no split/alias/ambiguous barrier batch, and a depth-plane transition from `DEPTH_WRITE` into a read-only state. Only plane 0 is temporarily transitioned and restored. The exact recorded command list must subsequently appear in `ExecuteCommandLists`; the fence is signalled on that queue after the original submission call. Device removal is a failure, never fence completion.

One session is allowed per game process. Readback/source resources remain held until process exit, including timeout/cancellation/reset, because unobserved command-list submissions cannot safely be retired. This is a bounded diagnostic memory cost, not a production capture design. The temporary observation/allocation/copy work can add overhead. A game or driver using unhooked command-list/queue interfaces will yield explicit missing-recording/submission evidence instead of an assumed success.

A snapshot is the first qualifying depth-write-to-read boundary after prewarm. This may be a prepass, shadow map or other depth texture. It is not guaranteed final scene depth. No texture is called fovea or periphery. The protected DuoView compositor, shaders, producer, OpenXR pose path, gaze and HUD behavior are hash-checked before/after this patch in CI.

## Test in STALKER 2

1. Extract the experimental package into a separate folder; retain the stable installation.
2. Load a scene, activate DuoView ID6, then open **DuoView Mono quality → Depth proof to disk (experimental)**.
3. Click **Capture depth proof (10 seconds, once per game)** and remain in the scene for roughly 10 seconds plus export time.
4. The status names the output folder under `%APPDATA%/UnrealVRMod/<game>/depth_proof/<timestamp>/`. Open `preview.html` or the BMP images.
5. Send the complete timestamp folder as a ZIP and the fresh UEVR log. If no image was captured, the manifest is still the useful result. A second session requires restarting the game.

Windows WARP tests exercise actual copies/readbacks and rejected lifecycle/state cases. CI output will record their result; live STALKER 2 acquisition remains unverified until the exported game samples are inspected.

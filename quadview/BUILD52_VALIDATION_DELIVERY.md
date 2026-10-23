# Build52 validation and delivery — 2026-10-23

Build52 is compiled and delivered as a headset-test candidate. Build51 remains
user-confirmed. No headset acceptance, resolved brightness mismatch, resolved
freeze, absence of regressions, or FPS gain is inferred from CI tests.

## Immutable build identity

* Runtime source: `a64f44de9c9b1229ea6a894150bf375fa15adfb5`.
* Workflow source: `8f30bbeedbdc9b4d3c4fce68fb605be7867be746` in `liviutrn/MUSE-UEVR-DUOVIEW`.
* Successful CI: https://github.com/liviutrn/MUSE-UEVR-DUOVIEW/actions/runs/39930401452 .
* Original backend `5ac7edc207866569334175e4ed8a7517971547f6`, SDK `3cffbc82429b6165ceec2714f0f0d9ae48f55596`, frontend
  `60be4b0f9a646109fd9fdf448bacd41477234091`; pinned DuoView baseline unchanged.
* Runtime ZIP: `UEVR-QuadViews-Build52-NativeStereoFix-1.zip`, delivered with
  the descriptive filename `UEVR-QuadViews-Build52-Shading-MPC-Transitions.zip`.
  Rename only; bytes unchanged.
* ZIP SHA256: `4ab6bb9746a7e31c029bb50c03d5acbfa1528c79bc5e94d2ee1d92663feaaf08`.
* DLL SHA256, locally compared with the packaged CI identity record:
  `a5901926223f14f7cadbf87747cc1e0153f40380fc9833896ddbffea807b3e1b`.
* Exact PDB SHA256 recorded by CI:
  `1dbd67e5bc31bb037329c749d52f7506d7c602cbc653d2c7f91200829310d34c`.
* Compiled artifact ID `12492271735`; exact symbols artifact ID `12492645787`.
  The artifact download digest, inner ZIP checksum, ZIP CRCs, DLL hash, runtime
  source pin, workflow pin, and unverified-headset metadata were checked locally.

## Completed checks

The Windows job passed all **75 CTest entries**: 24 QuadView tests including
three production compositor WARP formats, 4 pinned DuoView production tests,
6 independent DuoView tests, and 41 original backend compatibility tests.
The matching frontend rendering-ID/profile tests and publish also passed.
Real SDK/reflection adapters, backend DLLs, and offline shaders compiled.
The post-build source checkpoint retained the exact SDK boundary and recorded
generated-output provenance separately.

The independent Ubuntu job passed ASan/UBSan runs for 11 production-header or
exact-runtime-include harnesses, mutation checks, log-parser tests, and the
84-file pinned baseline verifier. Local validation additionally passed all
21 portable CTests with the actual patched Selection header and all 10 source
checkpoint cases. These checks establish the tested software contracts, not
actual game lighting or runtime scheduling correctness.

The all-mode harness covers 64 serialized ID pairs, rapid changes/cancellation,
and stale retirement/rejection tokens. It does not establish that every mode
is available in every runtime or that every live game transition is freeze-free.

## Headset test order

1. Fresh process, same save and scene: compare the default-on **Consistent
   source shading pass** with OFF (Build51 pass classification). Hold the scene
   steady and let exposure settle. Compare both focus views and both peripheral
   views; verify binocular depth, FOV, gaze, auxiliary captures and menus.
2. Verify hands, weapons, knife and detector with **First-person FOV parity**.
   The accepted donor reads cached MPC scalars and repairs drift with conditional
   setters, then restores originals on exit. It does not set TanFOV every tick.
3. Exercise 7→6→7, 7→5→7, 7→0→7, other available mode pairs, rapid changes,
   cancellation, loading and runtime reset. Preserve the complete log if stalled;
   maintenance execution alone is not retirement evidence.
4. Only after shading acceptance, enable the existing QuadView GPU timing toggle
   for the new CPU native-dispatch average/max. It measures elapsed dispatch
   time, including four renderer calls and waits, not CPU utilization or total
   game/GPU frame time. Compare the same resolution and settings.

See [BUILD52_PERFORMANCE_AUDIT.md](BUILD52_PERFORMANCE_AUDIT.md) for ranked
profiling experiments and [BUILD51_USER_LOG_ANALYSIS_2026-10-23.md](BUILD51_USER_LOG_ANALYSIS_2026-10-23.md)
for the observed transition failure. No speculative performance optimization
was bundled with the shading candidate.

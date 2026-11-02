# CODEMAP: uevr-quad-views-mono

Mapped at branch `claude/triview-s2-20261102` (HEAD `955ef14`, working tree clean).

## 1. Overview and build

This repo is not a full program. It holds Python patch scripts, C++/HLSL module files, tests and CI workflows for DuoView (eye-tracked foveated rendering for STALKER 2, DX12, OpenXR) and its Tri-View Stage 1 experiment (rendering method ID 7). The GitHub Actions job (`windows-2022`) checks out this repo as `workspace` plus three pinned external sources: joeyhodge/UEVR at `5ac7edc` (backend), joeyhodge/UESDK at `3cffbc8` (restricted, needs a token), and joeyhodge/uevr-frontend at `60be4b0`. It verifies the exact baseline, then runs the patch scripts in order against the backend. Each script replaces exact anchor strings that must match exactly once, and the job fails otherwise. After patching it runs the CMake/WARP tests, builds the backend and frontend, and zips the package as an artifact. Nothing is compiled locally.

## 2. Patch and build steps, in workflow order

From `.github/workflows/triview-stage1.yml`. Scripts are in `duoview/joey_stage1/` unless noted.

Preflight (no edits):
0. `duoview/clean_restart/verify_exact_baseline.py`: checks the three checkouts against `baseline.lock.json`.

Patches and their checks:
1. `apply_stage1.py` (then `verify_stage1.py`): makes mode 6 a selectable method that routes through Joey's single-view Mono renderer. Verify fails if other source changed.
2. `apply_stage234.py`: DuoView through Joey's Native Stereo Fix pipeline (mode 6 only, STALKER 2 DX12 OpenXR). Largest script, about 1100 lines.
3. `apply_foreground_mpc_minimal.py`: STALKER 2 foreground MPC override. Edits only `src/mods/VR.cpp`.
4. `apply_mono_hud_convergence.py`: opt-in convergence distance for the single game HUD quad in Mono mode.
5. `apply_mono_alignment_build48.py`: repairs HUD convergence and adds zero-cost Mono presentation alignment.
6. `apply_runtime_eye_alignment_persistence_build49.py`: keeps Mono eye alignment across OpenXR "Reset Runtime". Guard: `test_runtime_eye_alignment_persistence_build49.py`.
7. `apply_xyz_head_scaling.py`: opt-in scaling of HMD translation on X, Y and Z. Contract: `test_xyz_head_scaling.py`.
8. `apply_manual_fov_global_lookup_v165.py`: manual-only MPC_FOV recovery with a global object-lookup fallback. Guard: `test_manual_fov_global_lookup_v165.py` (fails if GPU, pose or eye code changed; compares protected-file hashes).
9. `test_v205_recovery_hotkeys.py --capture` runs first. Then `apply_v205_manual_fov_runtime_hotkeys.py` adds two configurable hotkeys (reapply DuoView FOV, reinitialize runtime). Then `--verify` checks the #205 logic is unchanged.
10. `apply_v207_auto_fov_after_load.py`: re-presses the FOV reapply request 1.5 s after a world load. Edits only `src/mods/VR.cpp`.
11. `git diff --check` (whitespace), then `verify_stage234.py`: checks Stage 2-4 added and edited files and that the SDK is untouched.
12. `apply_triview_stage1.py BACKEND FRONTEND DUOVIEW_DIR EVIDENCE`: adds Tri-View as ID 7 (section 4). Then `git diff --check` again.

Build and test (after patching):
- `duoview/triview/CMakeLists.txt`: Tri-View geometry tests and, on Windows, the WARP compositor test.
- `duoview/joey_stage1/CMakeLists.txt`: pinned production contract, PSVR2 gaze and WARP tests.
- `duoview/CMakeLists.txt`: independent DuoView geometry, gaze, frame, config, state and WARP tests.
- Backend: `cmake -S backend` builds `uevr`, `vr-plugin-nullifier`, `LuaVR`, the test targets and the compatibility suite.
- Frontend: `dotnet run --project frontend/tests/RenderingModes`, then `dotnet publish`.
- Final step: `apply_triview_stage1.py --verify` confirms no patched file changed during the build. Then the job zips `Tri-View-Stage1-<run>.zip` and uploads it with the evidence folder.

## 3. Directories

| Path | Contents |
|---|---|
| `.github/workflows/` | 5 CI workflows. `triview-stage1.yml` is the current one; the other 4 are older preflight and test runs (v182, v186.1 MPC, HUD convergence, Build48). |
| `duoview/` (top level) | DuoView Mono sources (`DuoView*.hpp`, `DuoViewComposite*.hlsl`), independent tests (`stage*_tests.cpp`, `production_warp_test.cpp`), `CMakeLists.txt`, `embed_shader.py`, and many handoff and review `.md` files. |
| `duoview/joey_stage1/` | The patch chain: `apply_*.py`, `verify_*.py` and `test_*.py` checks, pinned-contract C++ tests, and `DuoViewDelivery.hpp`. |
| `duoview/triview/` | Tri-View Stage 1 source: geometry header, D3D12 compositor, HLSL shader and tests. Copied into the backend by step 12. |
| `duoview/reviews/` | Review notes and checkpoints from October 2026 (audits, investigations, planning). |
| `duoview/clean_restart/` | Exact-baseline lock file and verifier, source audits, an offline subfolder, and SDK reconstruction (the README says the active build does not use it). |
| `research/` | Design decision records. One file. |
| `scripts/` | `verify_baseline.py`: checks copied files against the Build182 baseline. |

Root files: `README.md` (project overview; current release v186.1), `RELEASE_NOTES_*.md`, `PROVENANCE.json`, `SHA256SUMS`, `BASELINE_SOURCE_SHA256SUMS`, `NOTICE.md`, `COPYING`, `.gitignore`.

## 4. `duoview/triview/` files

- `TriViewGeometry.hpp`: pure math, no UE or D3D. Fixed centre windows are the two foveas. One centre camera covering both eye frusta is the periphery. Assumes parallel eyes.
- `TriViewD3D12.hpp`: D3D12 compositor, one instance per OpenXR command slot. Writes the double-wide XR image in one draw.
- `TriViewComposite.hlsl`: the shader. Each eye gets the periphery underneath and its own fovea on top.
- `embed_triview_shader.py`: compiles the HLSL to DXBC with fxc and writes `TriViewShaderSource.hpp`. Reuses `duoview/embed_shader.py`.
- `TriViewGeometryTests.cpp`: CPU checks that the engine projections and the compositor map agree.
- `TriViewCompositorWarpTests.cpp`: runs the real shader and PSO on the D3D12 WARP software device and checks pixels (Windows only).
- `CMakeLists.txt`: builds the two tests. Needs `TRIVIEW_INCLUDE_DIR`.

## 5. `duoview/joey_stage1/apply_triview_stage1.py`

Modes: apply as `BACKEND FRONTEND DUOVIEW_DIR EVIDENCE`, verify as `--verify BACKEND EVIDENCE`.

Preconditions: backend HEAD is `5ac7edc` and frontend HEAD is `60be4b0`. The backend must match the exact v207 file sets (`V207_EDITED`, `V207_ADDED`).

Backend files edited by exact anchors (`BACKEND` dict):
- `src/mods/vr/MonoRenderingPolicy.hpp`: `triview_method_id = 7` and its menu entry.
- `src/mods/vr/RenderingMethodSetting.hpp`: ID 7 runs the Native Stereo code paths. Tri-View reads the raw ID.
- `src/mods/VR.hpp` and `src/mods/VR.cpp`: declarations and edits. `VR_CPP_APPEND` is added to the end of `VR.cpp` and defines `VR::is_triview_active()`.
- `src/mods/vr/FFakeStereoRenderingHook.hpp` and `.cpp`: engine-side view count, index-2 hooks and the third render.
- `src/mods/vr/D3D12Component.hpp` and `.cpp`: compose the Tri-View image instead of Joey's copy, only while ID 7 is active.
- `tests/MonoRenderingTests.hpp` and `tests/CadenceReplayTests.cpp`: test updates.

Files copied or generated into the backend: `src/mods/vr/TriViewGeometry.hpp`, `src/mods/vr/TriViewD3D12.hpp` (copies) and `src/mods/vr/TriViewShaderSource.hpp` (generated).

Frontend (`FRONTEND` dict): `UEVR/RenderingModeOptions.cs` adds `TriView = 7` to the menu. `tests/RenderingModes/Program.cs` checks IDs 0 to 7. `UEVR/FilteredExecutables.json` is generated.

Main names:
- Constants: `LABEL` ("Tri-View (Experimental)"), `V207_EDITED`, `V207_ADDED`, `TRIVIEW_EDITED`, `MODULE_FILES`, `TRIVIEW_ADDED`, `FRONTEND_EDITED`, `FRONTEND_GENERATED`, `BACKEND`, `VR_CPP_APPEND`, `FRONTEND`.
- Functions: `git()`, `sha()`, `apply_edits()` (each anchor must match once), `tracked_state()`, `apply()` (writes `triview-stage1-hashes.json` to evidence), `verify()` (re-hashes after the build).

## 6. `research/`

- `2026-11-01-triview-stage1-decision.md` (107 lines): decision record for Tri-View Stage 1, dated 1 Nov 2026. Goal is the fastest correct Tri-View test build, built from Joey's Native Stereo and Native Fix. Sections cover how Native Fix makes per-eye renders, the third-render design, review fixes, checks before headset, and headset test notes.

## 7. Notes

- Branch: the requested name `work-triview` does not exist here. The checked-out branch is `claude/triview-s2-20261102`.
- `triview-stage1.yml` triggers on push only for `claude/triview-stage1-20261101`. Pushes to this branch do not start it. Use the manual "Run workflow" button (`workflow_dispatch`).
- Pinned SHAs: backend `5ac7edc207866569334175e4ed8a7517971547f6`, UESDK `3cffbc82429b6165ceec2714f0f0d9ae48f55596`, frontend `60be4b0f9a646109fd9fdf448bacd41477234091`.
- Patches are exact-string edits. One changed anchor fails the whole build.

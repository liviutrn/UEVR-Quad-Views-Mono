# Part F — Cheeky DLSS Neural Rendering (our 0.6.3 NR Lite fork)

**Prepared:** 10 Nov 2026. **Status:** source inspection and exact source reconstruction; **not** a new headset benchmark or runtime certification.

**Evidence notation (same as Part A):** **[SRC]** source-read, **[LOG]** captured game/plugin log, **[MEAS]** Liviu's measurement, **[GUESS]** hypothesis/unverified runtime outcome. All technical assertions below carry one or more of these labels.

## 0. Pinned inputs, how to read this part

- **[SRC]** Our fork: [`liviutrn/OpenNR`, branch `experiment/cheeky-v063-triview-nr-lite-vram-20261110`](https://github.com/liviutrn/OpenNR/tree/experiment/cheeky-v063-triview-nr-lite-vram-20261110/CheekyPort), including [view-routing patch script](https://github.com/liviutrn/OpenNR/blob/experiment/cheeky-v063-triview-nr-lite-vram-20261110/CheekyPort/scripts/apply_v063_nr_view.py), [NR Lite patch script](https://github.com/liviutrn/OpenNR/blob/experiment/cheeky-v063-triview-nr-lite-vram-20261110/CheekyPort/scripts/apply_v063_nr_lite.py), [VRAM policy](https://github.com/liviutrn/OpenNR/blob/experiment/cheeky-v063-triview-nr-lite-vram-20261110/CheekyPort/include/nr_lite_budget_policy.hpp) and [Windows build workflow](https://github.com/liviutrn/OpenNR/blob/experiment/cheeky-v063-triview-nr-lite-vram-20261110/.github/workflows/cheeky-v063-nr-lite.yml). Checked fork patch commit `0918cb86f7e303c4b78f85be9cd27c2029ebea23`.
- **[SRC]** The workflow pins [upstream `ClarkCheekyKent/CheekyFoveatedDLSS` commit `39bfc96214498e5e21cf861f0eb21f875697b428`](https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/tree/39bfc96214498e5e21cf861f0eb21f875697b428) (v0.6.3), then runs **view script → NR Lite script → version-header correction** (`shared/version.h` 0.6.2→0.6.3).
- **[SRC]** [Full generated unified diff, all changed files](fable-F-cheeky-fork-vs-upstream.patch) (**15 files**, including dynamic changes to the Lua UI, full replacement of Cheeky's private SR function, copied headroom policy, and corrected version macro). This is a reconstruction of the CI-generated Cheeky source, **not** a comparison of the unrelated OpenNR/Skyrim source against Cheeky.
- **[SRC]** Full reconstructed relevant implementation, with original line numbering preserved inside each generated file: [hooks.cpp](fable-F-cheeky-source/src/hooks.cpp), [dlss_nr.cpp](fable-F-cheeky-source/src/dlss_nr.cpp), [dlss_nr_input.cpp](fable-F-cheeky-source/src/dlss_nr_input.cpp), [dlss_nr_input.hpp](fable-F-cheeky-source/src/dlss_nr_input.hpp), [nr_guides.hpp](fable-F-cheeky-source/src/nr_guides.hpp), [GPU lifetime .hpp](fable-F-cheeky-source/src/dlss_nr_lifetime.hpp), [GPU lifetime .cpp](fable-F-cheeky-source/src/dlss_nr_lifetime.cpp), and [crop_motion.cpp](fable-F-cheeky-source/src/crop_motion.cpp). The last four are unchanged upstream at this pin but included because they define GPU guide, queue/recording lifetime, and adjacent GPU allocation paths.
- **[SRC]** Exact string-match patch assertions passed during reconstruction; no source changes were made to TriView/UEVR, no binary was compiled and no VR tests were performed as part of this document. The fork's build/Windows test workflow is the independent executable validation route.

## 1. One frame in plain language

1. **[SRC]** The separate UEVR Cheeky DLL intercepts game DLSS-SR feature creation/evaluation and chooses whether to process each NGX view. **`EyeProcessingMode=3`** identifies the **two equal-geometry stereo foveas**, passing the dissimilar full-FOV mono periphery through to native SR; ambiguous mapping fails closed. It does **not** cause UEVR to render a fourth source. Mode `0` processes all DLSS views, including the periphery. See `src/hooks.cpp:5009–5017`, view-routing modifications in the diff, and `CheekyPort/V063_NR_VIEW_PORT.md`.
2. **[SRC]** In the **Before SR** configuration, `NativeNrInputScope` builds a `DlssNrFrame` from the game's NGX **Color, Depth, MotionVectors, Output**, input/output dimensions, crop and gaze data. It selects a private D3D12 raw-color texture and records **copy source color → NVIDIA NR Feature 18 → substitute processed Color NGX parameter → original native DLSS SR evaluate** on the current command list. Its scope restores the original NGX parameter afterwards. This happens separately for each fovea: `src/hooks.cpp:4781–4848, 4941–4960, 4962–5055`; `src/dlss_nr_input.cpp:53–188`.
3. **[SRC]** **Native STALKER 2 DLSS Super Resolution stays authoritative.** The NR Lite-generated `evaluate_native_d3d12_canonical` always returns `false` (private Cheeky SR path bypassed); the normal original NGX SR callback proceeds. See `src/hooks.cpp:4904–4918, 5028–5055`. If NR preparation fails, the original color is forwarded rather than blocking the game.
4. **[SRC]** NR Feature 18 gets its own state/history per **view ID and model pass**, model key and GPU scratch. It converts color/depth/motion into NR's expected inputs, evaluates NVIDIA's NGX NR, then decodes the result. One- or two-pass UI options are supported; a second pass has its own feature and optional output texture. See `src/dlss_nr.cpp:128–196, 420–570, 810–1000, 1124–1660`.
5. **[SRC]** This is **NOT an active two-eye atlas batch**. The `[CheekyNR][AtlasProbe]` merely reports handle and input order. A correct atlas would need verified same-frame left/right raw color, depth and motion **before either native SR call**, which is not established in this hook. See [stereo atlas handoff](https://github.com/liviutrn/OpenNR/blob/experiment/cheeky-v063-triview-nr-lite-vram-20261110/CheekyPort/STEREO_ATLAS_HANDOFF.md).
6. **[MEAS]** Liviu previously compared NR **before** SR (~5 ms) vs **after** SR (~15 ms) in this game/setup. These are his observations, not code-derived timings or guarantees at every resolution.

## 2. Interception and hook installation

- **[SRC]** Hooked public/core D3D12 NGX exports include `NVSDK_NGX_D3D12_Init`, `CreateFeature`, `EvaluateFeature`, `EvaluateFeature_C`, and `ReleaseFeature`. D3D11 counterparts are also implemented; the current STALKER 2 route is **D3D12**. `src/hooks.cpp:~3770–3959, 5826–5940`. The plugin separately obtains its private NGX NR Feature 18 create/evaluate/release functions through `GetProcAddress` on the model runtime (`src/dlss_nr.cpp:~291–410`).
- **[SRC]** The library discovers resident and late-loaded NGX DLLs, checks/stabilizes module exports, installs **inline/trampoline detours** on exports and **IAT/import substitutions** where applicable; a worker scans loaded modules after attachment. Streamline is intercepted through a separate inline hook path and safeguards against double-processing nested NGX calls. `src/hooks.cpp:~888–930, 1070–1100, 4940–5055, 5460–5950, 6440–6520, 6600–6635`. The game executable's `GetProcAddress` import is explicitly excluded on one interception path; don't characterize this as blanket detouring of every import.
- **[SRC]** Submission/reset/allocator bookkeeping feeds the NR lifetime tracker: `src/dlss_nr_lifetime.hpp:18–45`; `src/dlss_nr_lifetime.cpp:160–285`. The tracker observes recording identity and GPU queue fence completion; it is **not** a simple frame-count timer. Threading/hook interactions with TriView are a review target rather than a claim of proven stability.
- **[SRC]** `NVSDK_NGX_D3D12_AllocateParameters`, `CreateFeature`, `EvaluateFeature`, and `ReleaseFeature` used for the plugin's **own NR Feature 18** are calls into NVIDIA's runtime, distinct from calls intercepted on the game SR path (`src/dlss_nr.cpp:~291–410, 420–570, 1420–1600`).

## 3. Resource ownership and VRAM

| Resource and owner | Count / size | When retained or released | Evidence |
| --- | --- | --- | --- |
| Before-SR private color input, `dlss_nr_input.cpp` | Up to **4 slots per active DLSS view ID**, not 4 total; identical extent/format to incoming raw Color, 1 mip, UAV-enabled. Size = **D3D12 allocation-info bytes**, dependent on input resolution/format/alignment. | Reused after relevant command list is complete (or ordered in same recording); old/changed-format slots marked retired and freed only after recording/queue lifetime ends. | **[SRC]** `src/dlss_nr_input.cpp:11–43, 98–162, 190–225` |
| NR GPU scratch, `dlss_nr.cpp` | **8 cached `GpuResources` maximum per NR view/pass state**; original output, color proxy, neural output, optional pass-2 output, guides, descriptors/shaders; sizes derived from region, working scale and allocation format. **Not 8 buffers total across both eyes.** | Completed old-resolution resources retired; cold completed scratch trimmed after **3 seconds**, retaining a warm eligible idle set. Pass-2 scratch released when switching to 1 pass once GPU-safe. | **[SRC]** `src/dlss_nr.cpp:128–196, 597–667, 810–1000` |
| NR guide textures | Motion guide `R32G32_FLOAT` (**8 B/pixel**), depth guide `R32_FLOAT` (**4 B/pixel**); actual dimensions from the NR pass and GPU allocation alignment. | Owned by corresponding `GpuResources`. | **[SRC]** `src/nr_guides.hpp:11–55` |
| NVIDIA Feature 18 model and temporal history | **1 live NGX handle per view/pass** (potentially two passes per fovea). **0 spare reusable old features** by current policy, but in-flight retired handles may temporarily coexist. **Opaque NVIDIA allocation size unknown**. | Model-key changes create new features; old features released only when GPU work is finished. No forced drain/CPU stall to free them. | **[SRC]** `src/dlss_nr.cpp:153–196, 212–250, 420–570, 1124–1160` |
| GPU recording/queue fences | Dynamically associated with recording identities and all executing queues. | Released only when completed/reset safely; no assumption of triple buffering. | **[SRC]** `src/dlss_nr_lifetime.cpp:13–30, 107–145, 160–285` |
| Private Cheeky SR/FG textures | Private SR path bypassed, **Cheeky-owned FG forced off** in NR Lite; retained generic code does not mean those modes run each frame. | VectorXR has **separate** FG resources; Cheeky does not manage them. | **[SRC]** generated `hooks.cpp:4904–4918` and changes to `src/settings.cpp` / UEVR Lua in unified diff |

**[SRC]** The NR Lite VRAM log executes about **once every 2 seconds** (see `dlss_nr.cpp:263–300`), with **committed resource estimate** and counts, but excludes opaque NVIDIA-owned allocations:

```text
[CheekyNR][VRAM] scratchMiB=... scratchSets=... busyMiB=... busySets=... beforeMiB=... beforeSlots=... beforeBusyMiB=... beforeBusy=... beforeRetired=... ngxFeatures=... ngxRetired=... pass2Outputs=... (NGX opaque allocations excluded)
```

**[SRC]** `beforeMiB` is the sum of private raw-color inputs; `scratchMiB` counts known GPU scratch (color outputs, guides etc.); `busyMiB` and `beforeBusyMiB` are outstanding-recording portions, not additional allocations to add again. `ngxFeatures` counts **handles** not their unseen memory footprint. To determine the plugin's full cost, compare overall DXGI usage/budget before and after enabling NR.

**[SRC]** The CPU-only, non-atlas diagnostic samples first 32 hook calls and then every 256:
```text
[CheekyNR][AtlasProbe] seq=... view=... list=... color=... depth=... mv=... source=... input=... output=... offset=...
```
`hooks.cpp:4800–4812`. **[SRC]** A changing pointer or consecutive calls does not prove both eyes' resources are simultaneously GPU-ready.

**[SRC]** The `nr_lite_check_budget` **admission guard** runs before settings/template transactions that could reallocate an NR model. It queries local DXGI `usage/budget` and requires a **heuristic headroom reservation**; it leaves old settings/history untouched on rejection. The reservation is **not** a measured allocation: e.g. enabling foveated two-fovea NR requests **1,024 MiB** free, disabling NR foveation requires **2,304 MiB** for foveas (3,072 MiB for all views), and increasing from 1→2 passes requires **1,536 MiB** for foveas. It may still underestimate NVIDIA's opaque model memory. [Policy source](https://github.com/liviutrn/OpenNR/blob/experiment/cheeky-v063-triview-nr-lite-vram-20261110/CheekyPort/include/nr_lite_budget_policy.hpp), generated `uevr/runtime.cpp` in diff.

```text
[CheekyNR][VRAMGuard] approved action=... freeMiB=... reserveMiB=... nrFoveated=... passes=...
[CheekyNR][VRAMGuard] REJECTED action=... valid=... usedMiB=... budgetMiB=... freeMiB=... reserveMiB=... nrFoveated=... passes=...
```

**[LOG]** Part A reports about **8.6 GiB of a ~10.1 GiB DXGI budget** in one B42 session and about **+0.9 GiB** when NR was enabled. **[GUESS]** Neither number isolates Cheeky scratch from NVIDIA feature history or VectorXR and is **not** a memory profile of this newer NR Lite binary.

## 4. Settings actually exposed by NR Lite

- **[SRC]** Source choice `EyeProcessingMode`: **0** all NGX views, **1/2** respective Duo view, **3** TriView two foveas only. UI favors 3; old profiles default to 0 unless migrated/changed; read the saved setting rather than assuming the selection.
- **[SRC]** Enable NR; `NrProcessingOrder` **After** (0) or **Before native SR** (1); `NrFoveated` toggle, optionally follow original SR crop, otherwise width/height/roundness/transition; NR working scale; model choice default/original/faster; style, intensity, local tone, local structure, optional skin structure/automatic mask, paper white, HDR transfer, color strength, depth convention, motion scales.
- **[SRC]** One or two model passes in the reduced UI (backend has `max_nr_passes=3`), extra settings for pass 2; two saved **NR-only** per-game templates, template toggle/load/save; explicit reset NR history and status refresh. Private Cheeky SR, Cheeky FG and old eye-tracking panels hidden; Cheeky FG is forcibly disabled even if an old profile saved it. See generated Lua diff + `src/settings.hpp`, `src/settings.cpp`, and `uevr/runtime.cpp`.
- **[SRC]** Upstream struct defaults, before saved profile: `nr_enabled=false`, `nr_foveated=true`, `nr_processing_order=after_upscaling`, `nr_width=nr_height=0.56`, `nr_working_scale=1`, `nr_passes=1`. **[GUESS]** Do not confuse defaults with Liviu's currently saved **Before SR** profile or the UI selection after switching to NR Lite.

## 5. Code map (line numbers in the supplied generated source)

| File | Symbol / region | Lines | Why it matters |
| --- | --- | --- | --- |
| [`src/hooks.cpp`](fable-F-cheeky-source/src/hooks.cpp) | inline hook installer / trampoline | ~888–930 | **[SRC]** Low-level detour |
| same | `NativeNrInputScope` / `prepare` | 4781–4848 | **[SRC]** Before-SR raw color, crop, parameter substitution and probe |
| same | `evaluate_native_d3d12_canonical` | 4904–4918 | **[SRC]** Private SR disabled |
| same | `recognizable_d3d12_dlss_evaluation` | 4941–4960 | **[SRC]** NGX input/guide screening |
| same | `process_d3d12_evaluation_impl` | 4962–~5055 | **[SRC]** View selector → NR → native SR |
| same | C-form evaluate / alternate native scope | ~5200–5260 | **[SRC]** Lower-hook variant |
| same | direct/IAT/Streamline hook setup and worker | ~5460–5950, 6440–6635 | **[SRC]** Load and hook integration |
| [`src/dlss_nr_input.cpp`](fable-F-cheeky-source/src/dlss_nr_input.cpp) | `prepare_dlss_nr_input` | 53–188 | **[SRC]** Up to four before-SR color slots/view |
| same | `dlss_nr_input_memory_stats` / collect/release | 190–225 | **[SRC]** Budget logs and retirement |
| [`src/dlss_nr.cpp`](fable-F-cheeky-source/src/dlss_nr.cpp) | `GpuResources`, `ViewState`, capacities | 128–196 | **[SRC]** Scratch / feature cache scope |
| same | `release_gpu`, `collect_retired_views` | 198–250 | **[SRC]** Release after GPU completion |
| same | `log_nr_lite_memory` | 263–300 | **[SRC]** 2-second VRAM telemetry |
| same | `find_or_create_view`, `create_feature` | 410–~570 | **[SRC]** Per-pass NVIDIA Feature 18 |
| same | `find_or_create_gpu` | 810–~1000 | **[SRC]** Scratch cache / trim / pass-2 output |
| same | `evaluate_dlss_nr` | 1124–~1660 | **[SRC]** NR recording, passes, history |
| [`src/nr_guides.hpp`](fable-F-cheeky-source/src/nr_guides.hpp) | `NrGuidePass` GPU texture allocation | 11–55 | **[SRC]** Depth/motion guides |
| [`src/dlss_nr_lifetime.cpp`](fable-F-cheeky-source/src/dlss_nr_lifetime.cpp) | `NrLifetime::record`, `nr_recording_submitted`, reset | 160–285 | **[SRC]** Queue/fence lifetime |
| generated files shown in [unified diff](fable-F-cheeky-fork-vs-upstream.patch) | `src/settings.*`, `uevr/runtime.cpp`, `uevr/scripts/cheeky_foveated_dlss.lua` | Search symbol `eye_processing_mode`, `nr_lite_check_budget`, `Cheeky TriView NR Lite` | **[SRC]** Configuration, transaction guard and UI |

## 6. Licence / can we publish?

- **[SRC] YES, conditionally.** Upstream Cheeky is **GNU GPL version 3**: see [upstream LICENSE](https://github.com/ClarkCheekyKent/CheekyFoveatedDLSS/blob/39bfc96214498e5e21cf861f0eb21f875697b428/LICENSE) and the [included copy](fable-F-cheeky-source/LICENSE-GPL-3.0.txt). The GPL allows public redistribution and modification of covered source if its obligations are met: retain copyright/licence notices, identify modifications, convey the licence and provide corresponding source for distributed GPL binaries. Fork modifications are themselves subject to applicable original GPL terms.
- **[SRC]** These snapshots and the patch can be present in our **public repo** as clearly attributed GPL-covered sources; this does **not** grant an exception to merge GPL code into independently licensed UEVR binaries or redistribute proprietary NVIDIA/UE SDK components. A combined derivative/binary requires a separate licence-compatibility and redistributability check. We did **not** copy NVIDIA proprietary runtime/model binaries or private UESDK.
- **[GUESS]** If the purpose is only Fable review, keeping the patch and snapshots as separately labelled research assets is safer than importing them into the production UEVR build. This is a practical licensing interpretation, not legal advice.

## 7. Unknowns / checks Fable should not skip

- **[GUESS]** VRAM can still fail at small view sizes because opaque NGX per-feature history, delayed old model retirement, UE view histories and VectorXR buffers have non-pixel-fixed overhead. The code does **not** prove a total memory ceiling or successful headset stability.
- **[GUESS]** Two fovea evaluations remain sequential. The AtlasProbe is **not** proof of a safe frame-local stereo atlas; verify a UE5 callback before either SR evaluate before attempting one-call batching.
- **[SRC]** To attribute the crash: correlate **DXGI local usage/budget**, `[CheekyNR][VRAM]` and `[CheekyNR][VRAMGuard]`, native NR Feature 18 create/release lines, VectorXR's **Frame Generation process video memory**, and TriView's native target/resizing logs in one time window. Log correlation, not a guessed per-pixel formula, is the deciding evidence.

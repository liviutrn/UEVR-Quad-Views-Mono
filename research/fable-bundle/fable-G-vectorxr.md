# Part G — VectorXR OpenXR frame-generation layer

**Prepared:** 10 Nov 2026. **Status:** public source/documentation research, **not** an inspection of Liviu's installed executable or new headset measurement.

**Evidence labels:** **[SRC]** directly read in public source/documentation, **[LOG]** observed in supplied runtime logs, **[MEAS]** Liviu measured it, **[GUESS]** inference or unverified for this particular installation. Technical claims use these labels, following Part A.

## 0. Pin and quick answer

- **[SRC]** Vendor/source: **DienerTech LLC**, [VectorXR repository](https://github.com/DienerTech/vectorxr), public [v0.20.1 release notes](https://github.com/DienerTech/vectorxr/blob/master/release/notes/v0.20.1.md), [usage guide](https://github.com/DienerTech/vectorxr/blob/master/docs/usage.md), [architecture](https://github.com/DienerTech/vectorxr/blob/master/docs/architecture.md), [licence](https://github.com/DienerTech/vectorxr/blob/master/LICENSE). **Known public release documented: 0.20.1**; source lines below refer to **`master` as read 10 Nov 2026**, which may include post-release experimental work. They are **not** an assertion that every experimental master feature ships in v0.20.1.
- **[GUESS]** **Liviu's installed VectorXR version is not yet verified** in the logs reviewed for this handoff. The current binary's About page, installer version, or runtime startup banner is necessary to tie behavior to an exact compiled revision.
- **[SRC]** VectorXR is a **Windows OpenXR API layer** inserted between the VR application/UEVR and the OpenXR runtime. Its separate desktop app edits settings; the native layer performs frame pacing, optical flow, generated-frame output and OpenXR submission. It is **not** a DLSS/NGX plug-in, and **does not** require changes to TriView's render targets to operate.
- **[SRC]** Normal Frame Generation **reads the rendered per-eye color images**, can additionally use the game's submitted **depth** if present and validated, and normally **estimates motion from consecutive color images** using GPU shader block matching or NVIDIA hardware optical flow. **It does not use game motion-vector textures in the standard, user-facing FG path.** Current `master` includes a research-gated experimental engine-motion-vector path; this distinction is crucial below.

## 1. Loading and one-frame pipeline

1. **[SRC]** VectorXR registers an **implicit OpenXR API layer** on Windows. OpenXR's loader discovers its manifest and dispatches selected calls to its DLL. Source entry points are [`layer/src/layer_entry.cpp`](https://github.com/DienerTech/vectorxr/blob/master/layer/src/layer_entry.cpp) and [architecture](https://github.com/DienerTech/vectorxr/blob/master/docs/architecture.md#runtime-architecture). The config UI can enable/reorder OpenXR API layers; its process need not be running throughout game play.
2. **[SRC]** At `xrCreateSession`, the FG setting is latched for that OpenXR session. The layer tracks swapchains and image-acquire/release calls. It intercepts `xrWaitFrame`, `xrBeginFrame`, and `xrEndFrame`, in supported configurations running its own presenter thread. Its `FrameGenPresenter` knows which OpenXR projection image each eye submitted. Source [`docs/architecture.md` lines ~73–120](https://github.com/DienerTech/vectorxr/blob/master/docs/architecture.md) and [`layer/src/framegen/framegen_presenter.cpp`](https://github.com/DienerTech/vectorxr/blob/master/layer/src/framegen/framegen_presenter.cpp).
3. **[SRC]** FG captures the **final per-eye color swapchain image(s)**, with previous real frames, estimates optical flow on GPU shader cores (default) or on an NVIDIA optical-flow accelerator (optional), and synthesizes new frames into **layer-owned output swapchains**. Two modes: `Interpolate` mixes between real frames (usually smoother, some additional latency); `Extrapolate` predicts beyond the latest frame (less delay, more edge/reveal artifacts). **[GUESS]** TriView's rendered periphery/foveas are already composited into each eye's submitted image by this stage: VectorXR cannot independently reduce TriView's three UE render-family costs.
4. **[SRC]** If the projection view carries valid depth information (OpenXR's `XrCompositionLayerDepthInfoKHR`, `XR_KHR_composition_layer_depth`), FG can use that depth to account for stereo/head translation and improve sharpness near objects. The depth pipeline checks validity and relative-eye alignment; bad/missing/disabled depth falls back to color-derived flow. This works in **D3D12**, and in **D3D11/Vulkan via respective bridges** where compatible depth is submitted. The **0.20.1** release specifically added D3D11 bridge depth, including UEVR titles. [Usage guide lines ~765–841](https://github.com/DienerTech/vectorxr/blob/master/docs/usage.md#game-depth); [0.20.1 release notes](https://github.com/DienerTech/vectorxr/blob/master/release/notes/v0.20.1.md).
5. **[SRC]** FG controls runtime pacing, presenting generated frames between or around genuine frames, potentially at `2x`, `3x`, `4x` or Dynamic-selected pacing. OpenXR `xrEndFrame` count and the game's real render FPS must be distinguished; the generated frames do not mean the game has rendered extra scene families.
6. **[GUESS]** Whether this specific STALKER 2 **D3D12 UEVR + TriView** session supplies usable projection-depth information to VectorXR has **not** been verified. TriView's **internal DLSS periphery depth snapshot** is not automatically the same thing as a depth image submitted through the OpenXR projection layer. Do not assume depth is active because TriView has a depth buffer.

## 2. Exactly what is read: color, depth, and game motion vectors

| Signal | Standard VectorXR FG | Evidence and important distinction |
| --- | --- | --- |
| **Real per-eye color** | **Required; read from OpenXR projection color swapchains** on every real frame. | **[SRC]** `FrameGenViewSubmission::source` in [`layer/include/depthxr/framegen_gpu.h`](https://github.com/DienerTech/vectorxr/blob/master/layer/include/depthxr/framegen_gpu.h), `FrameGenPresenter`, `docs/architecture.md`. |
| **Depth** | **Optional; automatically used when present, readable and valid**, unless `Use game depth` disabled. Usually attached by `XrCompositionLayerDepthInfoKHR` and processed in D3D12/bridges. | **[SRC]** [`layer/src/engine_motion.cpp`](https://github.com/DienerTech/vectorxr/blob/master/layer/src/engine_motion.cpp), [`docs/usage.md`](https://github.com/DienerTech/vectorxr/blob/master/docs/usage.md#game-depth); `depthUsed` in 30-second summaries and OSD `uses depth` are practical evidence. |
| **App/engine motion-vector image** | **Not used in the normal released FG path**; movement is inferred by matching color across successive frames. | **[SRC]** Usage guide, `docs/usage.md` section **Current limits**, explicitly says it does not use game motion vectors yet. NVIDIA **optical flow** is **not** the same as native UE5 scene motion vectors. |
| **Experimental engine vectors in `master`** | **Code exists, off by default, for research.** A `VECTORXR_FRAMEGEN_ENGINE_MV` environment switch can request `census`, `capture`, `observe`, `assist`, or `lead`; `off` is default. This may consume OpenXR space-warp vector swapchains in special circumstances. | **[SRC]** [`layer/src/framegen/framegen_presenter.cpp:~621–645`](https://github.com/DienerTech/vectorxr/blob/master/layer/src/framegen/framegen_presenter.cpp) reads the research switch; [`layer/include/depthxr/framegen_plan.h:~733–746`](https://github.com/DienerTech/vectorxr/blob/master/layer/include/depthxr/framegen_plan.h) declares modes; [`layer/include/depthxr/framegen_gpu.h:~87–110`](https://github.com/DienerTech/vectorxr/blob/master/layer/include/depthxr/framegen_gpu.h) defines optional game-vector job. **[GUESS]** No evidence Liviu enabled this experimental mode or that his installed binary includes it. |

**[SRC]** Short example from [DienerTech VectorXR, `layer/src/engine_motion.cpp:~52–59`](https://github.com/DienerTech/vectorxr/blob/master/layer/src/engine_motion.cpp), provided under MPL-2.0, showing detection of an OpenXR depth extension in a submitted structure chain:

```cpp
const XrCompositionLayerDepthInfoKHR* LeadingDepth(const void* next) {
    for (auto* node = static_cast<const XrBaseInStructure*>(next); node; node = node->next) {
        if (node->type == XR_TYPE_COMPOSITION_LAYER_DEPTH_INFO_KHR) {
            return reinterpret_cast<const XrCompositionLayerDepthInfoKHR*>(node);
        }
    }
    return nullptr;
}
```

**[SRC]** The existence of this parser does **not** demonstrate that the actual STALKER 2 session supplied depth. **[GUESS]** Without `depthUsed`/OSD/session logs, quality or VRAM changes attributed to depth would be speculation.

## 3. Frame-generation settings relevant to our setup

- **[SRC]** FG enable/disable per app, default profile normally off; changes to enabling FG and some bridge settings require restart.
- **[SRC]** **Mode:** `Interpolate` (default, better continuity with delay) or `Extrapolate` (lower added delay, more errors).
- **[SRC]** **Rate:** `Dynamic` (default, app runs as fast as its pacing allows, FG fills missing displays; can stand down) versus `Fixed: Auto / 2x / 3x / 4x` (holds app at a refresh divisor). In a 120Hz headset, **[GUESS]** 4x generally targets a ~30Hz real-frame budget *if* runtime actually runs at 120Hz and the path supports 4x. Never infer a fixed 4:1 multiplier from arbitrary decimal FPS ratios.
- **[SRC]** **Motion source:** `Shader` (default) or NVIDIA `hardware` optical flow. Under Interpolate, **Fall back to Shader when hardware can't keep up** defaults on; Extrapolate uses the selected flow source. These are not input options for game motion vectors.
- **[SRC]** **Advanced:** `Use game depth`; flow quality `Performance` (~1/16 image), `Balanced` (~1/8, default), `Quality` (~1/4); artifact suppression (default 50/100); motion limit (default 10% of view width); diagnostic views, OSD and A/B binding. [Usage guide, settings section](https://github.com/DienerTech/vectorxr/blob/master/docs/usage.md#frame-generation-settings).
- **[SRC]** Output-image pools persist for the session after creation so changing dynamic/fixed rate may **not** immediately return VRAM. [Usage guide rate and memory](https://github.com/DienerTech/vectorxr/blob/master/docs/usage.md#frame-rate-dynamic-or-fixed).

## 4. VRAM use: known values vs Liviu's unknown

**[SRC]** VectorXR's [own VRAM documentation](https://github.com/DienerTech/vectorxr/blob/master/docs/usage.md#video-memory) (illustrative documented budgets, **not measured here**):

| At **per-eye resolution** | Kept real images | Generated-output images | Typical total FG budget |
| --- | --- | --- | --- |
| **3000×3000** | ~**0.1 GB per kept real frame** | ~**0.2 GB**, both eyes' output swapchains | **Under 1 GB** total in cited configuration |
| **6864×6908** | ~**0.55 GB per kept real frame** | ~**1.1 GB**, both eyes' output swapchains | **~3–4 GB** total for D3D12, ~4–5 GB if D3D11/Vulkan bridge image copies needed |

**[SRC]** In just-in-time mode it keeps **five** real frames if the local memory budget permits, otherwise **three**, with different fallback for non-just-in-time sessions; an individual stored frame is approximated at **6 bytes per pixel per eye** across color + reduced-resolution depth/trust/flow. The layer adds its own swapchain output images (normally **three images × 4 bytes/pixel × two eyes**), flow/depth processing buffers, and possible bridge copies. Fixed higher multipliers can demand additional output images. **Do not add 0.55 GB five times without checking the session resolution.**

**[GUESS]** At Liviu's logged **4060×3228 per eye**, rough pixel-area scaling places VectorXR's D3D12 working/storage allocation around **0.7–1.3 GB** depending on the number of retained frames/output images, padding and optional features. This is a **planning estimate only**, not a measured breakdown: the game's actual submitted swapchain size and FG allocation strategy can differ. Even with TriView's **mono periphery**, VectorXR sees two final full-size eye images.

**[SRC]** Obtain the **real** answer from a VectorXR session log: search for **`Frame Generation process video memory`** lines, which distinguish process local usage/budget from FG's own working/output images; check **`Frame Generation keeps the last 5 real frames`** (or 3) and session flags **`justInTime`** plus **`twinMiB`** on bridge routes. [Source doc lines ~888–908](https://github.com/DienerTech/vectorxr/blob/master/docs/usage.md#video-memory). **[LOG]** The Part A VRAM ~8.6GB + NR ~0.9GB was an overall/NR-enablement observation and does not isolate VectorXR's retained frame pool.

## 5. Code map (public VectorXR source, `master`, 10 Nov 2026)

| File | Functions/region | Why inspect |
| --- | --- | --- |
| [`layer/src/layer_entry.cpp`](https://github.com/DienerTech/vectorxr/blob/master/layer/src/layer_entry.cpp) | OpenXR loader negotiation/function dispatch | **[SRC]** How implicit layer enters game |
| [`docs/architecture.md:~73–120`](https://github.com/DienerTech/vectorxr/blob/master/docs/architecture.md) | Session/frame/swapchain hook sequence | **[SRC]** Where FG inserts work |
| [`layer/src/framegen/framegen_presenter.cpp:~621–650, 842–900, 2416–2495`](https://github.com/DienerTech/vectorxr/blob/master/layer/src/framegen/framegen_presenter.cpp) | Research engine-vector switch, GPU support check, optional capture | **[SRC]** Why seeing experimental code is not evidence it is enabled |
| [`layer/include/depthxr/framegen_gpu.h:~18–55, ~87–110`](https://github.com/DienerTech/vectorxr/blob/master/layer/include/depthxr/framegen_gpu.h) | `FrameGenViewSubmission`, `FrameGenExecuteResult`, `FrameGenMotionJob` | **[SRC]** Inputs, outputs, optional depth/game-vector status |
| [`layer/include/depthxr/framegen_plan.h:~733–746, ~1013`](https://github.com/DienerTech/vectorxr/blob/master/layer/include/depthxr/framegen_plan.h) | `FrameGenEngineMode`, default `kOff` | **[SRC]** Research feature gating |
| [`layer/src/engine_motion.cpp:~52–60, ~119–145`](https://github.com/DienerTech/vectorxr/blob/master/layer/src/engine_motion.cpp) | `LeadingDepth`, `EngineMotionProblems` | **[SRC]** Depth structure discovery, optional vector validation |
| [`layer/src/framegen/framegen_gpu.cpp`](https://github.com/DienerTech/vectorxr/blob/master/layer/src/framegen/framegen_gpu.cpp) and [`layer/shaders/framegen.hlsl`](https://github.com/DienerTech/vectorxr/blob/master/layer/shaders/framegen.hlsl) | GPU color/flow/synthesis path | **[SRC]** Rendering/processing cost |
| [`docs/usage.md:~765–841, 854–960, 888–908, 1034–1045`](https://github.com/DienerTech/vectorxr/blob/master/docs/usage.md) | Depth, rate, FG memory, current limits | **[SRC]** Operator settings and runtime telemetry |
| [`release/notes/v0.20.1.md`](https://github.com/DienerTech/vectorxr/blob/master/release/notes/v0.20.1.md) | D3D11 UEVR depth support/fixes | **[SRC]** Release-specific behavior |

## 6. Licence: source may be excerpted

- **[SRC]** VectorXR source is publicly available under **Mozilla Public License 2.0 (MPL-2.0)**, [repository LICENSE](https://github.com/DienerTech/vectorxr/blob/master/LICENSE), copyright DienerTech LLC (and other respective contributors). **Yes, licence-compliant source excerpts may be quoted in this bundle** with attribution and notices; distributing modified MPL-covered source files requires preserving MPL requirements and making the covered files' source available. It is a **file-level copyleft** licence, not the same blanket relicensing rule as Cheeky's GPLv3.
- **[SRC]** We did **not** vendor/build VectorXR source or proprietary SDK binaries into the TriView repo; the single short excerpt above is for review only. A combined binary or larger port would need compatibility, notice and third-party dependency checks.

## 7. What Fable should verify before proposing changes

1. **[GUESS]** Retrieve Liviu's **installed VectorXR version** and the session startup log (0.20.1 public docs may not match an older local build). Identify actual `Interpolate/Extrapolate`, `Dynamic/Fixed`, `Shader/NVIDIA hardware` and `justInTime` state rather than assuming defaults.
2. **[SRC]** Verify whether depth is really in use from OSD **`uses depth`**, `depthUsed` in each 30s summary, and whether UEVR submits `XrCompositionLayerDepthInfoKHR` for these full-sized composed eyes. **[GUESS]** If it does not, altering TriView's internal DLSS depth copy alone will not add depth to VectorXR's input.
3. **[SRC]** Record **`Frame Generation process video memory`** (owned working bytes and output images vs process DXGI budget) before/after VectorXR FG. **[GUESS]** This may account for a material portion of the 12GB pressure and is the only reliable way to quantify the part controllable by VectorXR rather than Cheeky/UE.
4. **[SRC]** Do **not** enable the `VECTORXR_FRAMEGEN_ENGINE_MV` experimental assist/lead mode solely because source support exists; it is research-gated and includes a GPU-device-removed safeguard. Any proposal to connect actual UE5 motion vectors must be tested independently of normal FG, licence and compatibility permitting.

# DUOVIEW CENTER-ORIGIN DIBR STEREO — ENGINEERING TAKEOVER HANDOFF

**Prepared:** 24 October 2026  
**Project:** STALKER 2 VR / Joey UEVR / DuoView Mono foveated renderer / PSVR2 via SteamVR OpenXR  
**Repository:** https://github.com/liviutrn/UEVR-Quad-Views-Mono  
**Clean redesign branch:** [`redesign/duoview-frame-synchronous-dibr-20261023`](https://github.com/liviutrn/UEVR-Quad-Views-Mono/tree/redesign/duoview-frame-synchronous-dibr-20261023)  
**Clean redesign branch tip when authored:** `4524cf2f7cece020fbce6fad398ffbd9a3e47aae`  
**Stable runtime baseline commit:** `60d0aae86949723d21266e4121a833f0191729c2` (`fix/duoview-v49-openxr-alignment-persistence-20261022`, v186.1 Build49 / CI #56)  
**This handoff is a specification plus captured evidence; it is NOT a compiled stereo build.**

---

## 0. READ THIS FIRST — NONNEGOTIABLE TAKEOVER INSTRUCTIONS

**The user wants an actual working DIBR synthetic-stereo implementation, quickly and with high engineering quality.** They are understandably frustrated after many nonfunctional depth/stereo builds, especially Build #123, which compiled but had a broken UI and produced no observable stereo. Do **not** restart a chain of passive logging-only builds, use unverified depth buffers in a live stereo shader, or call a green GitHub Actions run a functional success. Do not ask the user to re-explain the design.

### Goal

Keep existing **DuoView mode ID6** rendering exactly **two center-camera Unreal views**—a high-resolution gaze-tracked fovea and low-resolution full-FOV periphery—with its proven Native Stereo Fix shading parity and compositor. Derive **distinct left- and right-eye images from the same center-origin Mono scene** using depth-image-based rendering (DIBR), *not* additional Unreal scene rendering, native Quad Views, or Joey's crash-prone single-eye DIBR feature. Submit those distinct eye images to the real PSVR2 OpenXR compositor. A clean fallback must preserve the stable DuoView Mono experience.

### Immediate disposition

- **KEEP:** known-good v186.1 Build49 DuoView, including foreground MPC fix, HUD convergence, Mono eye alignment persistence, gaze, Glamarye and existing packet/frame delivery.
- **KEEP AS EVIDENCE ONLY:** Build #118 independent offline depth proof. It successfully acquired seven inspectable DX12 depth readbacks but did **not** prove RGB/depth pairing, role, projection, or real-time suitability.
- **REJECT AS PRODUCTION CODE:** experimental Build #123 / branch `experiment/duoview-live-dibr-20261023`. User tested: *"not doing anything, and the ui is broken"*. Do not patch it incrementally.
- **USE AS START POINT:** `redesign/duoview-frame-synchronous-dibr-20261023`. This branch descends from stable Build49 and currently contains the architecture specification `DIBR_ARCHITECTURE_RESET_2026-10-23.md`, **not** Build123's P0/P1/S0 chain.
- **DELIVERY RULE:** a binary artifact is not accepted as a stereo build until it has a deterministic two-eye GPU output test and runtime activation telemetry. Clearly distinguish simulated/WARP success, Windows compilation, real-game output, and headset confirmation.

### User workflow preferences

- Act as senior engineering lead: make decisions and implement; don't repeatedly seek approval for obvious steps.
- Move efficiently, but do not substitute superficial patches, more UI toggles, or extra diagnostic builds for an architecture that can work.
- Use GitHub and Windows Actions for reproducible builds; keep stable release untouched.
- Incorporate meaningful diagnostics **inside** a functional stereo test build: show active route, exact reason for failure, actual L/R output difference, and depth/color source identity.
- If any step is not verified, say exactly what is missing. **Never claim that CI proves PSVR2 functionality.**

---

## 1. HARDWARE, RUNTIME, AND TARGET

User's relevant test environment (historical, verify from new logs rather than assuming unchanged):

| Area | Known configuration |
|---|---|
| Game | STALKER 2: Heart of Chornobyl, DX12 Unreal Engine 5, patch ~2.06 |
| GPU | NVIDIA RTX 5070 |
| CPU / RAM | Ryzen 7 5800X / 32 GB DDR4 |
| OS | Windows 10 LTSC, observed build 19044 in uploaded log |
| HMD | PSVR2, 120 Hz SteamVR; reprojection sometimes targets 30–40 game FPS |
| VR API in **Build118 uploaded log** | **OpenXR** (`SteamVR/OpenXR : playstation_vr2`), even though user uses OpenVR in some unrelated games |
| UEVR | Joey UEVR with Native Stereo Fix; experimental DuoView renderer ID6 |
| Foveation | 2 UE views from ONE center origin: fovea + periphery, default 0.50 × 0.50 crop and 0.20 peripheral scale; often uses DLSS Performance |
| Eye tracking | PSVR2 Toolkit CAPI, working DuoView gaze handling and center fallback |
| Normal render | User prefers stable ~30–40 FPS and high sharpness; don't add an expensive full second UE scene pass |

**Important:** OpenXR was definitely active in the Build118 log: log lines 154–158 request OpenVR but report **"OpenVR failed to load: OpenXR already loaded"**, then initialize OpenXR. Line 211 reports `SteamVR/OpenXR : playstation_vr2`. Do not assume OpenVR-specific eye submission from memory about Skyrim VR.

**Render resolution warning:** SteamVR's advertised width/height, UE view rect, DLSS internal size, source texture allocation, compositor crop and sampled UV dimensions are distinct. Do not infer one directly from another. Earlier work required a special ~0.8483 optical/FOV factor. Stereo must use frozen actual projection/rect metadata, not a guessed resolution ratio.

---

## 2. VERIFIED BASELINES, BRANCHES, COMMITS, AND BUILDS

### 2.1 Trusted functional baseline

- Source GitHub repo: https://github.com/liviutrn/UEVR-Quad-Views-Mono
- Stable branch: `fix/duoview-v49-openxr-alignment-persistence-20261022`
- Stable commit: `60d0aae86949723d21266e4121a833f0191729c2`
- User-accepted release line: `UEVR-Quad-Views-Mono-v186.1-MPC-HUD-EyeAlignment-Persist49-56`.
- Build v182 introduced major stability improvement; later v186.1 added the first-person MPC correction and HUD convergence/alignment controls.
- Known good attributes: two-view center-origin rendering, acceptable shading via Native Stereo Fix, stable first-person weapon/hands scaling, eye gaze handling, active Mono fallback, user-approved UI eye alignment percentage persistence (e.g. -1.25%), and Glamarye sharpening default 1.0.
- Current clean redesign branch already forks this stable source, rather than inheriting broken experimental code.

### 2.2 Pinned upstream sources / reproducible checkout

Found in `duoview/clean_restart/baseline.lock.json`:

| Component | Repository | Pinned SHA |
|---|---|---|
| Joey backend | `joeyhodge/UEVR` | `5ac7edc207866569334175e4ed8a7517971547f6` |
| UE SDK (restricted) | `joeyhodge/UESDK` | `3cffbc82429b6165ceec2714f0f0d9ae48f55596` |
| Joey frontend | `joeyhodge/uevr-frontend` | `60be4b0f9a646109fd9fdf448bacd41477234091` |

The CI checkout is defined in `.github/workflows/duoview-joey-stage234.yml`. The restricted SDK requires the repository's authorized `UEVR_SOURCE_TOKEN` or `PAT_TOKEN` GitHub Actions secret; do not invent the token or use an incompatible public UESDK as if it were binary-identical.

**Crucial CI nuance:** the clean redesign branch's current workflow push filter does not include the redesign branch. A future engineer must intentionally adjust the workflow trigger or invoke a correctly enabled workflow; merely pushing source files to that branch may not create a Windows binary.

### 2.3 Build #118: successful **offline depth acquisition**, not live stereo

- Branch: `experiment/duoview-depth-offline-proof-20261023`
- Successful workflow: https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/40008078681
- Diagnostic build package: `UEVR-DuoView-OfflineDepthProof-118`, GitHub Actions artifact ID `12525083961`.
- Runtime evidence uploaded by user: `depth_proof.rar`, `log(20261023-192901).txt`, plus exported `manifest.json`, `image_results.json`, and candidate contact sheet. The attached handoff ZIP includes the uploaded proof archive, log and the parsed JSON (see `evidence/`).
- Runtime log: `[DepthProof] start=true` at 2026-10-23 22:26:49.494; `[DepthProof] Saved 7 depth candidate images` at 22:27:01.139; a second start at 22:27:01.373 was rejected due to one-session-per-process design.

### 2.4 Build #123: compiled, user-rejected live DIBR

- Broken branch: `experiment/duoview-live-dibr-20261023`
- Workflow: https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/40015533384
- Artifact: `UEVR-DuoView-LiveDIBR-123`, ID `12528309278` (11.6 MB).
- Windows CI passed, including compiling backend, frontend, shaders and existing tests.
- **Actual user result:** "not doing anything, and the ui is broken"; no verified stereo and no usable activation diagnostics. This observed failure outweighs all CI success. DO NOT release or promote Build123.
- Its source is available for a *negative example*, not a base for patches.

### 2.5 Architecture reset

- Branch: https://github.com/liviutrn/UEVR-Quad-Views-Mono/tree/redesign/duoview-frame-synchronous-dibr-20261023
- Architecture doc: `DIBR_ARCHITECTURE_RESET_2026-10-23.md`
- First specification commit: `4524cf2f7cece020fbce6fad398ffbd9a3e47aae`
- **As of this handoff, this branch is a clean baseline + specification, not a working stereo build.**

---

## 3. EVIDENCE — BUILD118 HARD DATA, NOT GUESSES

### 3.1 Export files and meaning

The user-supplied proof capture contains:

- `manifest.json`: source D3D12 candidate metadata, state transitions, recording epochs, command list and queue identities, completed fences, rejection counts.
- `image_results.json`: per-image validity, nonconstant raw depth, min/max and conversion caveats.
- `candidate_N.f32`: little-endian float32, row-major hardware depth, **not linear metres**.
- `candidate_N.bmp` and `.pgm`: preview visualizations with percentile/log compression; don't measure depth numerically from these previews.
- `preview.html`: visual gallery.
- `log(20261023-192901).txt`: runtime sequence, host API, STALKER 2 and UEVR activation.

**The program itself states** the candidates are anonymous plane-0 snapshots at a depth-write-to-read boundary; they are **NOT verified** as scene depth for a specific DuoView view, current RGB frame, or metric Z. Trust these limitations.

### 3.2 Exact successful captures

From the actual uploaded `manifest.json` and `image_results.json`:

| Candidate ID | Size | DXGI format | Barrier (before → after) | Present tick | Recorded / submitted / complete / sealed | Raw-Z range | Interpretation |
|---|---|---|---|---|---|---|---|
| **1** | **860×684** | 19 (`R32_TYPELESS`) | **16 → 224** | 7498 | 1 / 1 / 1 / 1 | 0 .. 0.00602222 | Plausible scene geometry; visually matches IDs 4/5 |
| 2 | 4096×2048 | 53 | 16 → 192 | 7498 | 1 / 1 / 1 / 1 | 0.00122072 .. 1 | Different geometry; likely unrelated atlas/capture, **unproven** |
| 3 | 860×684 | 19 | 16 → 192 | 7498 | 1 / 1 / 1 / 1 | 0 .. 0.000534826 | Almost entirely zero, not suitable primary candidate |
| **4** | **860×684** | 19 | **16 → 96** | 7498 | 1 / 1 / 1 / 1 | 0 .. 0.00602222 | Same observed content as ID 1 |
| **5** | **860×684** | 19 | **16 → 96** | 7498 | 1 / 1 / 1 / 1 | 0 .. 0.00602222 | Same observed content as IDs 1/4 |
| **6** | **344×276** | 19 | **16 → 96** | 7498 | 1 / 1 / 1 / 1 | 0 .. 0.0117631 | Plausible wider-FOV image; matches ID 9 |
| **9** | **344×276** | 19 | **16 → 96** | 7498 | 1 / 1 / 1 / 1 | 0 .. 0.0117631 | Same observed content as ID 6 |

Raw candidate pairs/groups were compared in the prior analysis: **1/4/5 are bitwise-identical**, and **6/9 are bitwise-identical**. Preserve the actual `.f32` files and revalidate this offline as desired. Note there are multiple candidate resources at the **same resolution**: this alone disproves choosing a unique current scene pass by size.

**D3D12 state decoding (critical):**

- `16` = `D3D12_RESOURCE_STATE_DEPTH_WRITE`
- `96` = `D3D12_RESOURCE_STATE_DEPTH_READ | D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE`
- `224` = `DEPTH_READ | NON_PIXEL_SHADER_RESOURCE | PIXEL_SHADER_RESOURCE`
- `192` = `NON_PIXEL_SHADER_RESOURCE | PIXEL_SHADER_RESOURCE`

All seven successfully captured barriers at source tick 7498 and on the same tracked queue (manifest queue-local ID `401271920`), but with different command-list IDs/recording epochs. These copies **are not a live per-frame stereo synchronization proof**.

### 3.3 Extremely important capture-health counters

From `manifest.json`:

| Counter | Captured value | Engineering implication |
|---|---:|---|
| `recorded` / `submitted` / `completed` | **7 / 7 / 7** | The observer did genuinely read back seven images |
| `device_lost` | `false` | No device removal during this diagnostic |
| `queue_submissions_observed` | **29,311** | Submissions were tracked; diagnostic active across busy DX12 activity |
| `candidate_overflow_events` | **873,851** | Resource registry overflow **very high**; unsafe to extrapolate selection completeness |
| `tuple_overflow_events` | **21,616** | Transition tuple registry overflow |
| `rejections.non_depth_plane` | **5,403** | Plane handling must remain explicit |
| `rejections.state_window` | **15,561** | Many barriers outside safe capture window |
| `rejections.ambiguous_batch` | **68** | Ambiguous barrier batches exist |
| `rejections.callback_contention` | **1,463** | Lock contention exists; reduce observer hot-path overhead |
| `rejections.unknown_recording` | 0 | This capture had sufficient command-list evidence for the accepted copies |
| `rejections.render_pass` | 0 | Accepted copies were not inside a rejected active render pass |

The Build118 implementation deliberately uses bounded registries, one-shot capture, exact command-list submission observation, state guards, readback-buffer retention, and queue fence completion. It is **not** safe to turn that one-shot mechanism into continuous capture simply by copying to two persistent textures.

### 3.4 Required offline proof question

Before declaring any candidate the live full-field **periphery depth**, demonstrate using actual UE producer metadata and controlled movement:

1. Candidate responds correctly to geometry and the **current** camera position, not a reflection/shadow/minimap capture.
2. Candidate's projection FOV, origin and view rect match the actual **periphery Mono color source**.
3. The buffer is captured from a resource associated with a particular UE source pass, not merely a repeated RDG pool allocation with matching dimensions.
4. Candidate and color share the same actual `FrameKey`, serial, pose and projection.
5. GPU copy completes before the DIBR compositor samples it and is not overwritten until the reader's fence retires.

Using the same `capture_present_tick` is **not** enough: render passes/command lists can span scheduling boundaries, and present clocks are not producer provenance.

---

## 4. WHY BUILD123 DID NOT WORK (CODE-LEVEL RCA)

**Do not simply increase the shader strength and rebuild.** The failure is architectural.

### RCA A — silent Mono fallback by design

Broken branch source: `duoview/DuoViewD3D12.hpp`, `record_native()` approximately lines 106–295. A stereo output request activates only when:

```cpp
const bool stereo_preview =
    depth_debug == 5 && stereo_preview_strength > 0 &&
    depth0 && depth1 && native_stereo_preview_pipeline_ &&
    direct_compatible;
```

`direct_compatible` requires a specific directly-renderable **double-wide** XR texture, format and size. If false, the code selects the old Mono compositor or even returns `record_native_gather()` for unsupported source formats. **There was no fallback to a two-eye intermediate**. Consequently the user can click "stereo" while the headset receives **exactly the same eye image**.

**Fix:** actual stereo path must have two output modes: direct XR double-wide when safe, or an owned **double-wide stereo intermediate** with **two distinct halves** copied to XR. A mono-copy fallback is explicitly reported as `MONO_FALLBACK(reason)`; never report `STEREO_ACTIVE` after falling back.

### RCA B — depth resource IDs guessed from dimensions

Broken `duoview/stereo/LiveDIBRDepthPair.hpp` contains:

```cpp
if (desc.Width == 860 && desc.Height == 684) role = 0;
if (desc.Width == 344 && desc.Height == 276) role = 1;
```

That is not source identity. Build118 had **multiple** 860×684 and **multiple** 344×276 resources, some even with different contents. A change to UE screen percentage or DLSS immediately makes the heuristics miss. The hard-coded dimensions also ignore the actual active rect and projection.

**Fix:** attach source-role and resource-generation metadata in the **producer/RHI code path** that already knows `main_target`, `duoview_secondary_target` and `FrameKey`. Track the depth RHI resource alongside that producer. Reject `UNKNOWN` roles. Use observed dimensions only for warnings/telemetry, not identity.

### RCA C — GPU hazard / stale depth even if UI says “2/2”

The broken observer copies arbitrary matching `DEPTH_WRITE → READ` transitions to just **two long-lived** GPU textures, rate-limited ~20 ms, and signals **one** fence after the first two copies. Subsequent live copies can overwrite the same textures while XR may still be reading them. It does not enforce recorded command-list reset epochs, render pass nesting, exact queue submits, and consumer fence retirement with a per-frame ring. 

**Fix:** own immutable depth snapshots per source packet or bounded ring slot. Associate each slot with the source render command-list/queue and a fence; bind to XR only after the exact producer copy is complete; release/recycle only after **both** producer and XR consumer fences retire. If a held Mono color frame is reused, it must retain **its original depth** or explicitly stay Mono.

### RCA D — source contract exists only in an isolated unit test

`duoview/stereo/SourceLineage.hpp` on earlier S0 branch defines sensible provenance fields (`generation`, `tick`, `pose_token`, `depth_stage_token`, `color_stage_token`, role, resource generation, queue fence), but Build123 **never populated those from real packets**. It compiled and passed static tests while ignoring the guard in the actual raster submission.

**Fix:** wire real producer metadata to the compositor. `accept_rgbd()` is a **mandatory runtime predicate** before stereo output, not merely a synthetic test helper.

### RCA E — arbitrary nonlinear raw depth interpretation

Broken `duoview/DuoViewCenterStereoPreviewRaster.hlsl` used a hand-tuned transform based on `saturate(rawZ / 0.012)` and a width coefficient, without captured inverse projection or view origin. Raw UE reversed-Z is **not depth in meters**; full-frame depth and fovea depth can have different projections/rects. Candidate image maxima `0.006...` and `0.011...` are observations, **not universal calibration constants**.

**Fix:** linearize/unproject using actual producer projection and near/infinite-far convention. Derive left/right shifts from explicit virtual eye baseline/convergence and camera geometry. Handle sky, silhouettes and invalid depth without aggressively stretching raw-Z.

### RCA F — UI designed around experiments, not usage

Legacy P0 discovery toggle + P1 capture button + S0 stereo switch + depth-debug mode + 8% strength were embedded in an already huge “DuoView Mono — quality and diagnostics” ImGui `TreeNode`. The user reported the UI broken, and no runtime evidence clarified whether it was clipped, malfunctioning, displaying stale state or hiding controls. **We have not seen a screenshot/log of Build123**, so the exact UI symptom is unconfirmed; don't assert a single root cause for the visual defect.

**Fix:** one short independent **DuoView Stereo DIBR** section, accessible when DuoView is selected; no mandatory nested menus. One stereo toggle (OFF initially), a strength control and a real status/rejection reason. Disabled controls must say why. Do not show an enabled label if output is Mono.

### RCA G — nonfunctional CI assertions

`duoview/stereo/test_live_dibr.py` searched source strings such as `"depth0 && depth1"` and `"native_stereo_preview_pipeline_"`. That proves neither runtime reachability nor distinct left/right GPU output. Shader compilation does not test which PSO the compositor actually submitted. CI passed Build123 despite the real user test producing no change.

**Fix:** run actual DX12 WARP pixel readbacks, assert left-eye and right-eye images differ for known nonflat depth, assert output is identical for an intentionally zero-disparity mode, and assert the active GPU pipeline runs from the real `record_native`/XR submission path. Fail CI on any unsupported XR format that silently copies Mono when stereo is requested.

---

## 5. REPLACEMENT ARCHITECTURE: “COMPOSE ONCE, REPROJECT TWICE”

### 5.1 Why this is simpler and better

Instead of building two independent RGB-D pipelines and warping fovea/periphery separately, use **one center-origin blended color image** produced by the existing DuoView compositor. Acquire **one full-field periphery depth buffer** from the same source frame. Reconstruct **both eyes from that shared center camera**. Adding a foveal-depth refinement comes only after end-to-end full-FOV stereo works.

This preserves the user's most valuable working properties: uniform Native Stereo Fix lighting/shadows, no duplicated first-person weapon meshes from two eyes, unchanged gaze/crop logic, lower scene-render cost, independent HUD control, and unchanged legacy Mono fallback.

### 5.2 Target data flow

```text
             STALKER 2 / UE5 (UNCHANGED from v186.1 Build49)
                  CENTER-CAMERA ORIGIN
                   /               \
        UE primary/secondary (fixed view family/Native Stereo Fix)
                |                      |
        fovea RGB image         full-FOV periphery RGB image
                |                      |
                +---- current DuoView composer ----+
                                                   |
                                       fused center RGB image
                                       (crop blend + Glamarye)
                                                   |
        same producer frame + metadata ---+        |
                                         |        |
                    proven periphery R32 depth   |
                    (option: proven fovea depth) |
                                         |        |
                         [IMMUTABLE COLOR + DEPTH FRAME PACKET]
                                         |
                      verify origin / role / pose / projection
                      verify command submit + fence readiness
                      verify packet serial + resource generation
                                         |
                      +------------------+-------------------+
                      |                                      |
               not verified                                 verified
                      |                                      |
       stable ID6 Mono output                      depth unproject + DIBR
       status: MONO(reason)                           /           \
                                               left-eye     right-eye
                                                   \          /
                                                  double-wide
                                               raster / intermediate
                                                        |
                                                    OpenXR submit
```

### 5.3 New modules (proposed file structure, not yet implemented)

Use new isolated code under `duoview/dibr/`; avoid contaminating the original Mono compositor's logic:

| Proposed file | Responsibility |
|---|---|
| `duoview/dibr/DepthProducerBinding.hpp` | Capture UE scene pass role, exact `FrameKey`, projection/pose, scene depth resource generation from producer/RHI stage |
| `duoview/dibr/DepthFrameRingD3D12.hpp` | Per-packet depth copy slots, D3D12 state safety, list/queue/fence ownership and retirement |
| `duoview/dibr/CenterRgbdPacket.hpp` | Immutable frame contract holding fused RGB and periphery depth; optional fovea depth later |
| `duoview/dibr/SourceLineage.hpp` | Mandatory validation predicate; source/target metadata and typed rejection reasons |
| `duoview/dibr/DIBRGeometry.hpp` | Projection/reprojection conventions, coordinate transforms, per-eye offset/convergence mathematics |
| `duoview/dibr/CenterDIBR.hlsl` | Stereo raster/compute pass, depth discontinuity guards, eye-local warps, disocclusion handling |
| `duoview/dibr/DIBRPresentD3D12.hpp` | Two-eye output direct XR vs two-eye intermediate; never silent Mono as stereo |
| `duoview/dibr/DIBRStatus.hpp` | Central runtime state machine/counters/last-reject ring |
| `duoview/dibr/tests/*` | WARP GPU readbacks, frame matching, rejection and reset tests |
| `duoview/dibr/apply_center_dibr.py` | Exact-anchor patch of pinned Joey backend + unchanged v186.1 base |

The file names are design proposals. **Do not claim these files exist yet.**

### 5.4 Integration seams in existing code

Read these actual repository paths first:

1. `duoview/joey_stage1/apply_stage234.py` — primary exact-anchor patch applied to upstream Joey. Defines the DuoView UI branch; `duoview_begin_frame()`, `duoview_producer_key()`, source view setup, gaze/pose freeze, `NativeStereoFramePacket` extension; injects DX12 `record_native()` call into the packet consumer. **Must preserve Stage5 source packet continuity and existing exception/fallback behavior.**
2. `duoview/joey_stage1/apply_delivery.py` — binds source packet metadata to the actual RHI command tails, source role and source targets. Includes `duoview_secondary_target`, main target and RHI-thread lifecycle; **best starting point to attach producer-derived scene-depth identity**. Scope validation first; do not assume every callback/thread-local mapping is identical across UE render and DX12 submission.
3. `duoview/DuoViewD3D12.hpp` — stable GPU composer; `record_native()` and `record_native_gather()`, prewarmed PSOs, stereo destination compatibility, source SRVs, output path, shader constants. A new stereo stage should reuse or minimally wrap the existing stable Mono fused output without changing its sampling math.
4. `duoview/DuoViewNativeCompositeRaster.hlsl` — known-good foveal/peripheral RGB composition, Glamarye sharpening, crop blend; currently duplicates exactly the same Mono content across both eye halves.
5. `duoview/DuoViewFrame.hpp` — `FrameKey`, source-frame coordination and held-frame continuity; do not conflate packet frame serial with actual GPU completion. It documents `note_gpu_complete()` only after an actual fence reaches value.
6. `duoview/DuoViewState.hpp` and `duoview/DuoViewGeometry.hpp` — frame config, crop rects, view-layout math, eye-tracked offsets.
7. `duoview/clean_restart/baseline.lock.json` / `duoview/clean_restart/verify_exact_baseline.py` — pinned source identity.
8. `.github/workflows/duoview-joey-stage234.yml` — Windows compilation, WARP tests, packaging, hashes, release artifacts. Adapt to new branch and new tests.
9. Build118-only branch files: `duoview/depth_proof/DepthProofObserver.hpp`, `DepthProofSession.hpp`, `apply_depth_proof.py`, `depth_proof_warp_test.cpp`, `TAKEOVER_REVIEW.md`. Reuse the *safe capture lifecycle patterns*, not the one-time export implementation as a continuous renderer.
10. Broken branch files (for negative analysis only): `duoview/stereo/LiveDIBRDepthPair.hpp`, `apply_live_dibr.py`, `DuoViewCenterStereoPreviewRaster.hlsl`, `stereo/test_live_dibr.py`, `depth_probe/DuoDepthPairP1.hpp`, and the S0 patch.

### 5.5 An explicit decision about when to compose

**Recommended:** keep the existing source composition as a first GPU pass into an owned **fused Mono texture**. Run DIBR from this texture into a separate double-wide stereo output. Do **not** run Glamarye twice (once per eye) or independently compose fovea/periphery at potentially different shifted UVs until basic stereo is proven. This makes the image identity, sharpening and debug comparisons vastly simpler.

This adds a fullscreen compose pass and a fullscreen stereo warp in the experimental path. That is acceptable initially if needed for correctness. Optimize later by fusing passes only after pixel-equivalence and performance tests; maintaining the one-pass color source is more important than an early theoretical millisecond saving.

**If** directly using the existing mono output `output_` as the intermediate would race another XR command slot, allocate/store the center texture **per retired slot**, not globally. The current class prewarms resources at swapchain setup and uses command-slot lifetime management—follow that pattern.

---

## 6. FRAME PROVENANCE AND GPU SAFETY CONTRACT

**This is the most important part of the implementation. A good-looking still depth map is not sufficient.**

### 6.1 Exact immutable packet fields

An accepted `CenterRgbdPacket` should record at minimum:

```cpp
struct CenterRgbdPacket { // schematic, not existing API
  uint64_t mode_generation;
  uint64_t source_frame_key;
  uint64_t source_packet_serial;
  uint64_t pose_token;
  uint64_t projection_revision;
  uint64_t scene_family_token;

  // Same-origin center camera plus actual current periphery projection.
  CameraPose center_pose;
  Matrix4x4 periphery_view;
  Matrix4x4 periphery_projection;
  Matrix4x4 inverse_periphery_projection;
  Viewport periphery_viewport;
  CropRect fovea_in_output;

  OwnedResource fused_center_rgb; // one full-FOV image
  OwnedResource peripheral_depth; // one full-field depth map
  OptionalOwnedResource foveal_depth; // optional after MVP
  uint64_t rgb_generation;
  uint64_t depth_generation;
  uint64_t rgb_producer_stage_token;
  uint64_t depth_producer_stage_token;
  Dx12QueueToken producer_queue;
  uint64_t depth_copy_fence_value;
  Dx12QueueToken xr_consumer_queue;
  uint64_t xr_retirement_fence_value;

  bool producer_role_verified;
  bool projection_calibrated;
};
```

This struct illustrates contract ownership, not a copy-paste-compile definition. Actual types must follow the codebase's threading and D3D12 lifetime conventions.

### 6.2 Mandatory accept rules

A DIBR frame is accepted only if:

- mode ID6 is live, not quarantined; source view pair is valid and complete;
- center pose and periphery view role match **the same producer packet** as color;
- RGB and depth have the same mode generation, producer frame/serial and camera/projection revision;
- RHI resource **allocation generation** matches recorded source ownership;
- source copy is recorded *inside a proven safe state window*, on a known recorded command list, not inside a suspended render pass or an unsupported split-barrier transition;
- exact command list and submission queue have been identified; producer fence completion has been observed;
- depth isn't currently being overwritten and its owned copy will remain valid for the XR GPU consumer;
- sampled viewport/crop transforms map correctly to real native depth pixels, including dynamic screen percentage or DLSS changes;
- a **genuinely stereo** raster output route is available (direct XR or stereo intermediate), not a mono-copy compatibility route.

Every failed rule must return a typed status and increment a corresponding counter, without crashing or presenting incorrect eye images.

### 6.3 Recording / submission / retirement sequence

Suggested strict lifecycle:

```text
Producer (game/RHI thread):
  begin UE source packet -> note source role and immutable frame/projection
  identify THIS source's depth resource (not a random pool lookup)
  when safe DEPTH_WRITE -> READ barrier is reached:
    assert no active/suspended pass, no split/alias state ambiguity
    transition source -> COPY_SOURCE, slot-owned depth -> COPY_DEST
    CopyTextureRegion depth plane 0
    restore both states
    mark copy in command_list_epoch
  on exact ExecuteCommandLists(queue, lists):
    seal recording, bind packet -> queue/fence timeline
  when producer fence retires:
    mark depth copy GPU-ready

Compositor (XR fenced command slot):
  select validated center Mono RGB packet
  require exact RGB-D match and producer GPU readiness
  record fused-RGB compose then dual-eye warp (or safe alternative)
  present proper left/right eye images
  retain RGB/depth/PSO/SRV/resource generations until XR fence retires
  recycle slot only AFTER all relevant fences retire
```

**No GPU readback, shader compilation, global mutex wait or resource allocation in the XR per-frame callback.** Prewarm PSOs, descriptors, depth buffers and optional intermediates. Keep callbacks bounded (try-lock or wait-free registry is okay only if missed captures cause clear `DEPTH_WAIT`, never silent corrupted stereo).

**Queue safety:** do not `Signal` an arbitrary Present queue and assume a copy recorded on another queue has completed. If multiple queues are involved, explicitly link them with D3D12 `Wait`/`Signal` only after proving ordering and fence ownership; fail closed when ambiguous.

**Held frames:** current DuoView continuity can reuse a released Mono image briefly (historical policy up to ~100 ms). A held color must use the **same held Z**, pose and projection if it is reprojected. Otherwise submit it as Mono and count `RGB_D_MISMATCH`. Never warp a held color with a newly rendered depth frame.

**Resets:** on swapchain/runtime reset, retire/reinitialize only when GPU references are safe. Invalidate generations; don't reuse a depth SRV across a swapped resource pointer or repointed descriptor heap. Preserve Build49 HUD eye-alignment toggle and value exactly.

### 6.4 Rendering source proof mechanism

`apply_delivery.py` is the promising seam, but requires a careful engine/RHI review:

- Find where `NativeStereoFramePacket` knows `main_target` and `duoview_secondary_target`, current `duoview_frame`, and the actual RHI command tail that belongs to each source role.
- Within the same producer transaction, record **which** depth resource is bound/used by the `periphery` pass. Prefer engine/RDG-native metadata if a legitimate reliable hook exists; observe only **owned** resource transitions within that pass if not.
- Match command-list recording epoch and pool allocation identity to the packet. Log `source_role`, `source_frame`, `scene_family`, `camera_revision`, `depth_resource`, `color_resource`, `queue`, `fence`—not just width and last-seen Present frame.
- If threading means a per-view TLS tag cannot survive into DX12 resource barriers, attach immutable tags to the RHI command/task or use an explicit RHI registration map keyed by command-list epoch and source pass token. Reject unregistered barriers. Never assume ordering alone proves role.

Do **not** enlarge the Build118 anonymous candidate registry and hope the top-frequency candidate is correct; frequency is only a discovery clue.

---

## 7. STEREO REPROJECTION MATH AND IMAGE QUALITY

### 7.1 One center camera, two synthetic eye cameras

The source camera is the **center origin** between the synthetic eyes. Reconstruct:

- left eye at center minus `virtual_IPD / 2` along local camera right;
- right eye at center plus `virtual_IPD / 2`;
- virtual parallel-eye (off-axis / asymmetric-frustum) reprojection for desired zero-disparity convergence distance, **without rotating the virtual cameras toe-in**;
- use the actual UE-to-OpenXR camera-to-world units and world-scale conversion. Don't hardcode `0.064` metres in an Unreal-centimetres shader without conversion.

For an idealized pinhole center camera and depth `Z` in matching world units, approximate eye-space horizontal normalized shift:

\[
\Delta u_{\mathrm{eye}} = \pm \frac{B/2}{2\tan(\mathrm{FOV}_x/2)}\left(\frac{1}{Z}-\frac{1}{Z_c}\right)
\]

where `B` is virtual eye separation and `Z_c` convergence depth. **This is a sanity-check approximation, not a substitute for exact source and target projection matrices.** Verify sign with recognizable foreground objects and ensure no unwanted divergent disparity.

### 7.2 Decode actual UE depth and view rectangle

- Confirm hardware Z semantics: DXGI depth, reversed Z, DSV plane, near/far policy, jitter/TAA/DLSS pass stage.
- Use source projection/inverse projection to recover actual 3D eye-space point from `uv` and raw depth; map from depth resource extent and active `FIntRect`, including origin offsets and any texture padding.
- Account for UE NDC conventions and texel-center mapping; avoid `uv * render_target_alloc_extent` when an active rect is smaller.
- Transform view-space 3D point into the target eye view; project with **target eye projection**, not a guessed constant horizontal shift.
- For UE infinite reversed-Z, test finite, near, far and sky values; do not let `depth=0` produce an infinite shift or NaN.
- Target stereo convergence must not modify unrelated OpenXR HUD quad/cylinder layers. Build49 optical eye-alignment is a separate feature; initially set it to zero for stereo trials.

### 7.3 Visibility and disocclusion

Recommended final quality path:

1. Scatter/splat center RGB pixels to each synthetic eye, with a depth-order winner (z-buffer or depth-atomic resolve). A compute shader is viable.
2. Use a depth-aware hole-fill pass for newly exposed background, respecting object silhouettes and sky classification.
3. Avoid pulling foreground colors across thin objects, weapons, sights, foliage and high-contrast edges.
4. Use temporal data **only** if actual motion/pose matrices and frame matching are available; no blind history reuse.
5. Output separate left/right images with a known convergence model. Test still, lateral head movement, near hands/weapon, vegetation, thin rails, high-frequency foliage, moving NPCs, and gaze border crossing.

For an MVP, an inverse-gather shader can prove binocular image separation with edge guards, but label its expected disocclusion limits. Production-quality DIBR should not be claimed until holes/occlusions are handled.

### 7.4 Fovea/periphery quality policy

- MVP: **full-field periphery depth only**, already enough to reproject the fused high-quality center RGB image. Don't gate stereo on a foveal depth candidate.
- Fovea depth refinement: add only when its source pass + pose/projection/crop rectangle are proven **the same frame**. Blend depth carefully at ROI boundaries. The two raw Z textures should not be mixed numerically if projections differ.
- Keep Glamarye sharpening exactly once after source composition; don't accidentally sharpen one eye differently or duplicate heavy GPU cost.
- Native Stereo Fix shading remains untouched. The synthetic eyes will still share a center-camera lighting solution and may show some view-dependent highlight shortcomings; these are expected limitations, not a reason to spawn new Unreal shading views.

---

## 8. MAKE THE UI SMALL, EXPLICIT, AND TRUSTWORTHY

The previous nested experimental UI was unusable. Replace with a short section at **the primary DuoView screen level**, visible as soon as DuoView ID6 is selected; don't require opening three nested diagnostic menus.

### Minimum controls

- **Enable DIBR stereo** — single toggle, default OFF. Turning ON starts depth capture and verification automatically; no P0 or P1 arming button required.
- **Stereo strength / virtual IPD** — controlled and safely bounded; numeric value and clear units.
- **Convergence distance** — only when depth unprojection has been calibrated; otherwise display “Not calibrated” instead of fake metres.
- **Last submitted output** — `MONO`, `WAITING_FOR_DEPTH`, `WAITING_FOR_GPU`, `RGB_D_MISMATCH`, `XR_OUTPUT_INCOMPATIBLE`, `STEREO_ACTIVE`, or `ERROR`.
- **Exact reason + packet number** — one-line current rejection, total attempted stereo frames, genuine stereo frames, Mono fallback frames, last accepted producer serial.
- **Left/right signature test** — one-button optional debug that deliberately displays different per-eye corner markers (e.g. cyan left, amber right) to verify the OpenXR stereoscopic route; this is *not* a depth quality test.

### Truthful mode reporting

"Stereo ON" (user request) is NOT "Stereo Active" (actual output). The status is set **only after** the appropriate two-eye GPU draw is recorded and submitted, ideally backed by asynchronous readback of per-eye pixel samples or distinct CRCs. If the compositor uses a Mono fallback, show `MONO_FALLBACK: <exact reason>`, even if the user toggle remains ON.

### Diagnostics examples

```text
DIBR requested: YES
DIBR output: STEREO_ACTIVE
Accepted source packet: generation=... serial=... source_frame=...
Depth: periphery role=VERIFIED  extent=344x276  recording_epoch=...
Projections: source=... targetLeft=... targetRight=... revision=...
GPU: copy fence=... retired=YES   consumer slot=... fence=...
Eye output: left_crc=... right_crc=... different=YES
Frames: stereo=...  fallback=...  depth_miss=...  stale=...  xr_format=...
```

When failures occur, throttle logs, retain an in-memory ring of the last 32-128 typed events, and export a compact debug report on demand. Do not dump thousands of raw D3D12 barriers per frame.

### UI QA

Test visible control hierarchy, disabled states, resetting runtime, switching ID5/ID6, opening/closing TreeNodes, DPI/window scaling, screen-reader labels if supported, persistence and correct label text. A UI that changes state but does nothing in the headset is **a failing build**.

---

## 9. FASTEST CREDIBLE IMPLEMENTATION ORDER — NO FILLER BUILDS

This is a **single, implementation-driven delivery plan**. The gates are private engineering checks whenever possible; avoid issuing repetitive diagnostic-only user builds.

### Stage A — clean branch, reproducible base, instrument actual stereo route

1. Check out redesign branch from Build49; verify upstream backend/SDK/frontend lock and source hashes.
2. Keep v186.1 modules and all legacy `ID0`, `ID5`, `ID6` behavior intact with feature OFF.
3. Introduce isolated `DIBRStatus` and `DIBRPresentD3D12`, with **one** simple UI toggle/status.
4. Generate a known synthetic center RGB + depth pair **within GPU tests** and invoke the **actual two-eye compositor route**, not a mocked shader function.
5. Verify left/right pixel difference and **eye-order identity**, including XR output direct raster and compatible stereo-intermediate fallback.
6. Ensure any failed stereo prerequisite yields explicit reason + known-good Mono. The test should deliberately exercise each failure branch.

**Gate A acceptance:** a WARP or real DX12 readback proves `L != R` for a chosen known-depth scene; a “stereo requested” frame cannot exit unnoticed via mono-copy. The code preserving Build49 OFF path passes regressions.

### Stage B — full-field depth registration and lifetime

1. Instrument producer/RHI metadata at same actual source command stage as DuoView color packet (likely `apply_delivery.py` seam).
2. Derive full-field periphery depth **from producer role**, not from texture dimensions. Keep logging anonymous discovery only as fallback evidence.
3. Reuse Build118 safe state-transition and queue-observer pattern with per-slot preallocated depth buffers; bounded CPU work and no frame-loop allocations.
4. Prove exact same-frame color/depth serial plus renderer camera matrices. Carry projection through the immutable frame packet.
5. On failure, continue correctly labelled Mono; **do not** widen unsafe capture windows just to make stereo light up.

**Gate B acceptance:** at least 300 consecutive frames in a controlled test with exact CPU/GPU lineage and no read/write hazard; definite false candidates rejected. In-game test should show current periphery depth associated with the current camera view.

### Stage C — integrate scene depth into real two-eye output

1. Reproject from fused center RGB + verified periphery Z through **actual** source and target projection matrices.
2. Add a conservative disparity cap and convergence defaults; document expected user comfort limits.
3. For initial live test, enable optional eye markers and active status to prove the headset receives **distinct images**.
4. Visualize depth overlay on demand **in the same binary** if stereo looks wrong; do not require another diagnostic fork.
5. Handle invalid/no-depth pixels and basic silhouette rejection; log fallbacks.

**Gate C acceptance:** real STALKER 2 headset output shows clear binocular parallax on near/mid/far scene objects, with correct depth order, while the existing DuoView image remains sharp and functional. Any lack of visible effect must correspond to an explicit UI state and debug reason.

### Stage D — robust image quality and release candidate

1. Depth-aware disocclusion fill, correct sky/horizon handling and weapon/hand discontinuities.
2. Optional per-frame matched fovea-depth refinement (not required to reach initial stereo).
3. Dynamic resolution, DLSS changes, moving gaze, 30–40 FPS engine with 120 Hz SteamVR reprojection, runtime resets, source holds, long-session GPU retirement tests.
4. GPU timings: separate UE scene render, depth copy, Mono composition, DIBR warp, hole fill, XR submission. Avoid promising an improvement based on pixel counts alone.
5. User acceptance in PSVR2, 30-minute stability, no flicker/black headset/eye jumps, usable UI and persistent original settings.

**Gate D acceptance:** new stereo works and is stable in target hardware. Ship as test / release candidate with honest limitations; never replace the stable branch until accepted.

---

## 10. AUTOMATED TEST MATRIX (MANDATORY)

| ID | Test | Expected result |
|---|---|---|
| T00 | Feature OFF: Build49 frame/color/HUD/gaze compare | Bitwise-identical or understood isolated difference; no new observer overhead |
| T01 | Controlled WARP source RGB + constant Z | Expected deterministic left/right eye shift or zero-disparity if configured |
| T02 | Synthetic near object + far background | Correct binocular separation, no depth-order reversal |
| T03 | Stereo mode ON with missing depth | Explicit `MONO_FALLBACK: DEPTH_MISSING`, stable headset image |
| T04 | Wrong `FrameKey`/pose/projection/resource generation | Reject DIBR, increment mismatch counter |
| T05 | Depth copied but producer GPU fence not retired | `GPU_WAIT` (never sample unready depth) |
| T06 | Depth owner freed or reused before XR fence | Lifetime guard prevents reuse; no GPU validation errors |
| T07 | Direct XR target incompatible with stereo PSO | Two-eye intermediate still outputs distinct L/R; or explicit rejection |
| T08 | Deliberate L/R signature test | Opposite markers in correct eye halves, both readback and headset |
| T09 | Fovea gaze motion across crop border | No old-color/new-depth seam; crop/rect mapping correct |
| T10 | Forced 100 ms held Mono packet | Holds its own matched depth or outputs Mono; never current Z |
| T11 | Switch ID6 -> ID5 -> ID6 / reset runtime | Feature generations invalidate; stable Mono + HUD persistence intact |
| T12 | DLSS/screen-percentage changes | Capture reconfigures/revalidates; no hard-coded 860×684 requirement |
| T13 | Non-depth, shadow, ambiguous or split barriers | Rejected and classified, no copies during invalid state |
| T14 | Eye projection and optical calibration | No inverted parallax, gross FOV shrink or divergent disparity |
| T15 | Weapons, detector, knife, hands and HUD | Correct scale relative to world, acceptable occlusion, no duplicate crosshair |
| T16 | Motion/particles/foliage/thin geometry | Bounded artefacts; disocclusion tests pass image-difference checks |
| T17 | 30–40 FPS game / SteamVR 120 Hz reprojection | No pose/depth temporal inconsistency or flicker |
| T18 | DX12 device loss, bad SRV, command list reset and swapchain resize | Controlled fallback; no use-after-free or crash |
| T19 | Performance timing | Quantified costs per stage; no unexplained heavy CPU synchronization |
| T20 | 30-minute PSVR2 real-game soak | No HMD blackscreen, severe eye discomfort, crashes or persistent wrong-eye output |
| T21 | UI/telemetry reachability | Every user-visible stereo control has a real active effect and clear feedback |

**Golden test assertion:** `stereo_requested && stereo_accepted` implies the **actual eye surfaces differ** for a known nontrivial scene. Conversely, `stereo_requested && !stereo_accepted` implies a **visible exact fallback reason**. This should be codified as a GPU-test invariant, not a UI string assertion.

---

## 11. GITHUB BUILD / REVIEW / DELIVERY PROCEDURE

1. Start on `redesign/duoview-frame-synchronous-dibr-20261023` and inspect `DIBR_ARCHITECTURE_RESET_2026-10-23.md` plus this handoff.
2. Update branch workflow filters explicitly. Do not modify default `main` or stable release directly.
3. Use pinned backend (`5ac7...`), SDK (`3cff...`) and frontend (`60be...`) from baseline lock. Fail CI on unapproved source drift.
4. Add new exact-anchor script(s) **after** existing Stage234 + Build45 foreground + HUD/eye-alignment persistence patches. Preserve all prior patches in their established order.
5. Add DX12 WARP **real shader compilation and readback tests**, GPU safety regression, packet state tests, and proof that Mono fallback is preserved.
6. Build backend `UEVRBackend.dll`, original frontend EXE, nullifier and LuaVR using same pinned workflow; package complete install with hashes and provenance.
7. Produce a uniquely named test artifact (e.g. `UEVR-DuoView-CenterDIBR-Stereo-Test-<run_number>`). No stable release until user confirms headset rendering.
8. Bundle `READ_FIRST.md` with precise in-game instructions, status codes, screenshot capture guidance, expected performance and known risks, and a `BUILD_STATUS.json` including:

```json
{
  "baseline": "60d0aae86949723d21266e4121a833f0191729c2",
  "intent": "two-eye center-origin DIBR, DuoView mode ID6",
  "windows_compiled": false,
  "synthetic_warp_two_eye_pixels_verified": false,
  "periphery_depth_producer_verified": false,
  "same_frame_rgbd_verified": false,
  "real_stalker2_headset_verified": false,
  "stable_release": false
}
```

Update booleans only after actual evidence. Preserve CI artifacts, source commit, workflow URL, primary SHA256, and test logs.

9. Never classify source-level assertions (text tests), a UI checkbox, or a nonzero depth texture as verified stereo.
10. A senior engineering review should target GPU lifetime, producer identification, matrix conventions, XR view ordering, fallback correctness, and first-person/HUD regressions.

---

## 12. PERFORMANCE AND COMFORT CONSTRAINTS

- **No extra Unreal world shading views.** The original DuoView two-pass (high-res fovea, low-res periphery) remains the scene cost.
- DIBR is a postprocess after Mono scene composition. A GPU full-screen / compute raster and a depth copy cost memory bandwidth. Measure actual frame times on RTX 5070; target minimal overhead without claiming an invented number.
- No per-frame shader compilation, expensive CPU readback, or waiting for GPU completion on XR thread. Diagnostic readbacks asynchronous and opt-in.
- User's PSVR2 runs 120 Hz; game frames can be ~30–40 FPS plus SteamVR reprojection. Depth and color must refer to the same game frame, even if head pose updates more frequently. Later reprojection/late-latched gaze cannot synthesize a fresh scene depth automatically.
- Wrong left/right eye signs and excessive divergent disparity can be uncomfortable. Provide a true OFF toggle and conservative strength; never hide a failed stereo state behind plausible but unstable warped imagery.
- Preserve first-person foreground MPC parity and HUD optical convergence controls. Treat center HUD and crosshair as potentially separate overlays or baked scene; no double reticles and no eye-specific HUD alteration without explicit user controls.
- Respect world scale and headset optics. User previously used PSVR2 and explicit eye-alignment corrections; verify stereo independently of those adjustments.

---

## 13. WHAT THE NEXT ENGINEER SHOULD DO ON OPENING THIS HANDOFF

**Do these without asking for further general instructions:**

1. Read this handoff and architecture reset. Check GitHub redesign branch still descends from Build49. Locate the Build118 `DepthProofSession.hpp` callback/fence path and `apply_delivery.py` packet assembly.
2. Write a concise implementation map identifying actual entry points for source depth binding, fused-Mono staging, XR per-eye draw, and GPU resource retirement.
3. Implement **an actual stereo output path** from an explicitly valid synthetic RGB/Z packet and test it with WARP readback in both direct and intermediate-XR modes. Remove silent Mono-copy fallback from any accepted stereo route.
4. Implement producer-tagged full-field periphery depth capture with per-frame immutable slot/fence ownership. Wire it to the original DuoView packet, not to a global texture-size registry.
5. Add a minimal real DIBR toggle and a status line that surfaces missing depth, stale frame and incompatible XR paths; no nested experiment panels.
6. Wire actual projection transforms and conservative two-eye warp. Keep Build49 OFF path unmodified; preserve exact renderer/gaze/HUD/shader behavior when toggle is OFF.
7. Make the first headset test binary only after synthetic L/R output and frame-binding tests pass. Give the user one ZIP, direct Actions link and short precise test instructions. Keep a built-in diagnostic eye-marker switch so a nonworking stereo path can be isolated in the same build.
8. If the user says “not working,” use the visible stereo state, frame serials, fence readiness, per-eye hashes and source-role telemetry to identify *which stage failed*, rather than guessing and producing another blind build.

### Specifically forbidden shortcuts

- Do not fork Build123 and merely change `0.012` or shift strength.
- Do not use 860×684 and 344×276 as **identity** or static configuration constants.
- Do not bind `DepthProofSession` one-shot candidate readbacks as if they were synchronized current-frame GPU resources.
- Do not signal one fence and thereafter overwrite its associated textures indefinitely.
- Do not treat `SourceLineage.hpp` synthetic validation as real source metadata.
- Do not use different RGB/depth source frame numbers under SteamVR reprojection.
- Do not construct arbitrary left/right rays by copying a single eye from Joey standalone DIBR. The desired input is **center-origin fused Mono RGB** and both synthetic eyes.
- Do not ship a “stereo” build whose accepted path still copies identical Mono into both XR halves.
- Do not alter stock Joey rendering modes ID0/ID5, original stable DuoView ID6 fallback, or stable settings, without a verified regression requirement.

---

## 14. OPEN QUESTIONS TO RESOLVE FROM CODE / RUNTIME EVIDENCE

These are engineering questions, **not reasons to ask the user to re-explain the project**:

1. Which exact UE5 depth resource is produced by the **periphery** view at the stage of the color image sampled in `record_native`? Which hook can tag both reliably across the game/RHI thread boundary?
2. Is its projection identical to full-field color's, except for DLSS/TAA pixel-stage differences? Does depth require jitter compensation?
3. Which D3D12 queue actually executes that producer copy relative to the XR consumer? Is an explicit cross-queue fence needed?
4. Can the color compositor be directed to an owned per-XR-command-slot fused texture while preserving exact Baseline shader gamma, sRGB and Glamarye behavior?
5. When direct stereo XR render target is not compatible, can an intermediate stereo texture be copied to XR without format reinterpretation or copying the same half twice?
6. Where are the correct frozen UE projection/inverse matrices already available (native view matrices vs XR source pose)? What UE world-unit conversion applies?
7. Does the expected full-field depth include first-person hands/weapons or does UE render those in a separate foreground FOV/path, requiring separate z/layer strategy?
8. How best to fill disoccluded background without creating bright halos/ghosts at periphery/fovea boundaries?
9. What exact GPU staging/fence ring size is sufficient for low game FPS and multiple queued OpenXR frames while keeping memory bounded?
10. Why was the Build123 UI “broken” on the user's configuration (visibility/layout, invalid controls, stale values, or disabled path)? Don't assume cause without evidence; the replacement UI should be self-diagnosing.

---

## 15. SOURCE / EVIDENCE INDEX

| Resource | Where |
|---|---|
| **This file** | `DUOVIEW_DIBR_ENGINEERING_HANDOFF_2026-10-24.md` in handoff ZIP and GitHub redesign branch when uploaded |
| Existing architecture reset | `DIBR_ARCHITECTURE_RESET_2026-10-23.md`, redesign branch |
| Stable runtime source | `fix/duoview-v49-openxr-alignment-persistence-20261022` at `60d0aae86949723d21266e4121a833f0191729c2` |
| Core composer | `duoview/DuoViewD3D12.hpp`, `duoview/DuoViewNativeCompositeRaster.hlsl` |
| Source packet and RHI hooks | `duoview/joey_stage1/apply_stage234.py` and `apply_delivery.py` |
| Immutable frame model | `duoview/DuoViewFrame.hpp`, `DuoViewState.hpp`, `DuoViewGeometry.hpp` |
| Pinned upstream sources | `duoview/clean_restart/baseline.lock.json` |
| Independent depth proof code | `experiment/duoview-depth-offline-proof-20261023`, `duoview/depth_proof/` |
| Successful proof CI | https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/40008078681 |
| Broken live DIBR negative example | `experiment/duoview-live-dibr-20261023` |
| Broken Build123 CI | https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/40015533384 |
| User evidence (ZIP bundle) | `evidence/depth_proof.rar` and `evidence/log(20261023-192901).txt` |
| Parsed candidate metrics | `evidence/manifest.json`, `evidence/image_results.json` |
| Visual candidate comparison | `evidence/depth_candidates_contact_sheet.jpg` |
| UI feedback after #123 | User: **“not doing anything, and the ui is broken”** |

The `depth_proof.rar` file is a captured raw data archive, **not** a binary installation or malware scan target. Treat uploaded logs as user-provided diagnostics; avoid publishing any local usernames / machine paths from logs into public issue reports.

---

## 16. FINAL ENGINEERING POSITION

**What is proven:** the stable DuoView Mono renderer works; the game exposes readable nonconstant hardware depth images; Build118's GPU capture completed seven copies; the existing pipeline already knows the scene source packet/pose/foveal and peripheral color resources; a two-eye GPU PSO can compile.

**What is not proven:** which real-time depth candidate corresponds to the exact periphery RGB view; same-frame RGB/D matching; calibrated hardware-depth-to-meters conversion; reliable per-frame queue/fence safety; distinct left/right runtime output in STALKER 2; headset comfort and stability.

**The simplest credible implementation:** keep the proven dual-source Unreal scene and Mono compositor unchanged, produce one fused center RGB texture, attach one **verified full-field periphery depth** buffer to the same producer frame, then produce actual left and right images using calibrated DIBR. Foveal depth refinement comes later. The GPU command/eye output state must be observable and fail closed.

**Success is a PSVR2-visible, stable, depth-correct stereo effect—not a successful ZIP upload.**

# DuoView AFW — engineering decision and Stage 1 gate
Date: 2026-11-01 · Builder: ChatGPT · Branch: `experiment/duoview-afw-decision-20261101`
Status: **Step 1 source decision recorded; Stage 1 NOT built / NOT CI-verified / NOT headset-verified.**

## Evidence and input coverage

- **SOURCE-READ:** [shared team brief](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/claude/team-brief/research/PROJECT_BRIEF.md), stable v207 [workflow](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/claude/v207-auto-fov-vram-periphery/.github/workflows/duoview-joey-stage234.yml), [apply_stage1.py](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/claude/v207-auto-fov-vram-periphery/duoview/joey_stage1/apply_stage1.py), [apply_stage234.py](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/claude/v207-auto-fov-vram-periphery/duoview/joey_stage1/apply_stage234.py), [verify_stage234.py](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/claude/v207-auto-fov-vram-periphery/duoview/joey_stage1/verify_stage234.py), [v207 FOV patch](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/claude/v207-auto-fov-vram-periphery/duoview/joey_stage1/apply_v207_auto_fov_after_load.py), pinned [Joey D3D12Component.cpp](https://github.com/joeyhodge/UEVR/blob/5ac7edc207866569334175e4ed8a7517971547f6/src/mods/vr/D3D12Component.cpp), [Joey OpenXR.cpp](https://github.com/joeyhodge/UEVR/blob/5ac7edc207866569334175e4ed8a7517971547f6/src/mods/vr/runtimes/OpenXR.cpp).
- **SOURCE-READ:** PureDark [AFW API](https://github.com/PureDark/UEVR/blob/AFW/dependencies/pd-afwmod/include/PDAFWPlugin.h), [NGX interception](https://github.com/PureDark/UEVR/blob/AFW/src/mods/VR.cpp), [D3D12 warp integration](https://github.com/PureDark/UEVR/blob/AFW/src/mods/vr/D3D12Component.cpp), [OpenXR submission](https://github.com/PureDark/UEVR/blob/AFW/src/mods/vr/runtimes/OpenXR.cpp); Witcher3VR [MIT bridge header](https://github.com/tig3rmast3r/witcher3-vr/blob/main/src/puredark_afw_bridge.h), [bridge implementation](https://github.com/tig3rmast3r/witcher3-vr/blob/main/src/puredark_afw_bridge.cpp), [third-party notices](https://github.com/tig3rmast3r/witcher3-vr/blob/main/THIRD_PARTY_NOTICES.md).
- **USER-SUPPLIED DESIGN REVIEW (read, not independently verified):** `DuoView_AFW_Engineering_Design_Handoff_2026-11-01(1).docx`, 10 pages. It proposes an alternating-eye DuoView image and full-eye color/depth/motion merger, then seven gated stages.
- **REVIEW COVERAGE LIMIT:** The task refers to *two independent reviews*, but only one design-review attachment was accessible in this conversation. The shared team brief supplies constraints, **not** a substitute second independent review. Consequently the two-review agreement/disagreement comparison is provisional; no agreement by an unseen reviewer is claimed.
- **HEADSET-VERIFIED (Liviu's reports in brief):** stable v207; 24 fps Native Stereo at 3,800×3,100; stock beta 6 AFW 38 fps there; CI127 ~40 fps at 4,500×3,500 and visibly less stable than stock AFW. **ESTIMATED:** DuoView AFW 30–35 fps, *not measured*. Small-target measurements indicate substantial per-Unreal-family fixed cost.

## Decisions — where the available review and team brief agree

| Decision | Evidence | Adopt? |
| --- | --- | --- |
| Start from unchanged v207 on an `experiment/` branch; preserve stock Joey modes and existing ID6 Mono | SOURCE-READ: brief, v207 workflow and guarded patch | **Yes.** No edit to `claude/...` or stable build. |
| Treat PureDark as external, proprietary DLL and Witcher3VR as independent MIT bridge; credit both | SOURCE-READ: API, bridge, notices; permission statement USER-SUPPLIED | **Yes**, with external DLL loaded from user-owned installation, never modified or silently redistributed. |
| Prefer stock `CombinedWarping` before tuning | SOURCE-READ: PureDark default path; design review | **Yes**, subject to confirming tested beta-6 parameters. |
| Full-eye geometry and per-eye camera identity are prerequisites | SOURCE-READ: AFW interface, NGX capture, DuoView patch | **Yes.** No fake depth/motion or mismatched frame acceptance. |
| Defer `IsFoveated`/`FoveatedArea` | SOURCE-READ: fields exist; no verified semantics in current materials | **Yes**, both off in Stage 1. |
| Preserve all applicable v207 gaze/FOV/head scale/sharpening/hotkeys/NR; measure GPU, CPU and VRAM | SOURCE-READ: brief, patch; HEADSET-VERIFIED v207 | **Yes**, with a regression gate on the AFW-off path. |

## Apparent conflicts, decided from code rather than opinion

1. **“Stage 1 just loads the DLL; nothing else changes” versus working AFW stereo.** **SOURCE-READ:** v207's ID6 renders two region views with the same Mono pose and sends the same composite to both eyes. PureDark's D3D12 example supplies **one real eye**, depth, motion, per-eye camera matrices and a warped output. Merely calling `EvaluateFrameWarp` on v207's duplicated Mono image cannot demonstrate stock-like stereo. **Decision:** Stage 1 must be a minimal *vertical slice* including physical-eye selection, correct full-eye color+geometry, warp evaluation and XR output. “Nothing else” means **no foveation/merged-region logic and no changes to other modes**, not no camera/output changes.
2. **Directly reuse beta-5 Witcher bridge versus target beta-6 DLL.** **SOURCE-READ:** Witcher3VR's `FrameWarpEvaluateParams` has `reserved[12]` after `use_uint64`, with `reserved` expected at offset 132. PureDark's published header inserts `ShadingRate` between these fields, default `ShadingRate_1X1`. **Decision:** old layout is *not* proof of beta-6 ABI. The public header suggests the new shading-rate field occupies the old reserved position, so the entire structure size might remain unchanged; that makes a silent semantic mismatch especially dangerous. Verify the **actual beta-6 binary** (hash/version/exports, calling convention, struct offsets, vtable slots and minimal isolated invocation); extend the MIT independent declarations rather than copy a proprietary header. **SOURCE-READ** for field discrepancy; **ESTIMATED** for binary outcome.
3. **Render one normal full eye through old Mono pipeline versus preserve v207 unchanged.** **SOURCE-READ:** the v207 script reuses Native Stereo Fix/Mono frame-key gates to produce its ID6 regions; it does not already produce a validated full-eye AFW color-depth-motion triple. **Decision:** use an explicit opt-in AFW switch default OFF within the v207-based backend. When ON for Stage 1, select a proper physical eye and one ordinary full-eye render; do not inject synthetic depth, pass cropped region buffers, or enable region composition. Fall back cleanly to existing unaffected mode when OFF.
4. **Use whichever NGX textures last appeared versus exact frame ownership.** **SOURCE-READ:** PureDark's NGX hook extracts depth/MV/output/jitter/MV scale and indexes a frame-selected eye. DuoView will later have multiple NGX evaluations per engine frame. **Decision:** even Stage 1 tags every acquired resource with current frame, physical eye, resolution, command list and generation; future stages must also tag view role and DLSS/NR history. No “last DLSS call wins” ownership.
5. **Assume FPS rises with smaller fovea versus fixed render-family cost.** **HEADSET-VERIFIED:** 200×200 runs suggested ~7 ms per extra family and stock AFW was CPU-bound ~50 fps at low resolution. **Decision:** treat 30–35 fps as a hypothesis; instrument matched CPU/GPU times and keep a decisive Stage-4 stop rule. No optimistic FPS guarantee.

## Findings missed or under-specified in the available design review

- **SOURCE-READ:** The published API's new `ShadingRate` field may leave `sizeof` unchanged while turning the bridge's old zero `reserved[0]` into an invalid shading-rate value. A `sizeof` test alone is insufficient.
- **SOURCE-READ:** PureDark's implementation skips AFW after DLSS render-size changes (90-frame recovery counter in inspected NGX hook). Stage 1 must use a **fixed full-eye input size** and log reinitialization; later gaze/crop changes must not be mistaken for whole-eye resize.
- **SOURCE-READ:** The pinned v207 workflow requires a credential for the original restricted UESDK, plus exact Joey/UESDK/frontend revisions. Replacing its patch chain with a generic build is not valid verification.
- **SOURCE-READ:** v207's verifier asserts protected boundaries and exact output contracts; Stage 1 needs a **new verifier** that permits only carefully enumerated AFW-on additions while demonstrating AFW-OFF parity. Existing verifier cannot simply be disabled.
- **ESTIMATED:** A successful DLL load does not prove DX12 resource state transitions, descriptor ownership, GPU fence completion, swapchain reuse or graceful reset. Require isolated tests and logs for those specific failures.
- **ESTIMATED:** Stale eye parity after pause/reset, and rendering-rate vs submission-rate mismatch, can invert source eye; require eye+generation diagnostic stamps and per-eye matrix checks.
- **ESTIMATED:** DLSS 5 Neural Rendering and conventional DLSS may expose different NGX paths/histories; preserve NR but prove the selected feature's real depth/MV before enabling AFW. No invented fallback depth.
- **PERMISSION LIMIT:** “Non-commercial use permitted” (USER-SUPPLIED) is not automatically permission to *redistribute the proprietary DLL*. Keep it out of source and Actions artifacts unless the exact written redistribution terms are checked.
- **REVIEW LIMIT:** A second independent review and an independently run pre-push code review have not been provided/performed. Do not claim either completed.

## Final architecture contract

```
Stage 1 ONLY: single ordinary full-eye UE render for physical LEFT/RIGHT
  -> capture synchronized full-eye color, depth, MV, jitter, source/dest matrices
  -> beta-6 ABI-validated external PDAFWPlugin.dll / CombinedWarping
  -> real source-eye image + AFW destination-eye result
  -> correct OpenXR two-eye submission and UI, per-frame ownership
AFW OFF: untouched v207 ID6 Mono and original Joey modes
Later: Stage 2+ replace ordinary eye color with current-eye DuoView fovea+periphery,
       and only warp merged color+depth+motion after provenance proofs.
```

**Core invariants:** correct eye, current generation, one camera geometry, valid depth convention, valid MV scale, correct jitter, stable size, safe D3D12 states/fences, safe OpenXR left/right placement, no use-after-free. Invalid input ⇒ no spurious stereo-success label; use a deliberate safe original-mode fallback.

## Staged build queue (one build/stage, stop for headset result)

**Pre-build gate — no build:** (a) obtain actual beta-6 DLL version/hash and prove independent ABI and vtable, (b) inspect any missing second review, (c) replay exact patch scripts locally on pinned Joey + frontend using an available restricted SDK, (d) independent fresh-eyes review of **proposed Stage 1 diff**. Any missing gate stops the code push.

**Stage 1 — plain AFW vertical slice.** Exact beta-6 dynamic load; fixed-size, one real source eye, correctly captured color/depth/motion and matrices, `CombinedWarping`, full binocular OpenXR output, fallback when unavailable. Foveation and region merger OFF. Build only after the gate, then at most three headset questions: (1) Stereo like stock AFW, including hands? (2) FPS at 3,800×3,100 compared with 38? (3) Any crashes, black frames or wrong-eye imagery?

**Stage 2 — alternating real-eye DuoView color.** Fovea and periphery from *same selected physical eye*; frame-frozen gaze and base projection; AFW disabled on merged image until valid depth/MV proven.

**Stage 3 — four temporal histories and DLSS/NR resource provenance.** Tag eye × region, view-state lifetime, full matrices, motion scale and jitter. Reject stale/wrong-eye source.

**Stage 4 — merged full-eye color + visibility-selected depth + corrected motion into AFW.** Compare CI127, stock AFW and native at matched resolution/scene; ≥30 fps working target, >24 fps Native Stereo, hands/near edges no worse than stock AFW, cleaner temporal stereo than CI127. Main go/no-go.

**Stage 5 — gaze region and warp ROI.** Only test foveated flags after semantics and coordinates are proven.

**Stage 6 — moving objects, fog/fire/Lumen, HUD, VRAM parity.** Fix measured defects only.

**Stage 7 — 30-minute headset regression and recovery.** Save/load, menu, pause, eye tracking, resolutions, reset, original modes, 0 unexplained black frames.

## Files queued before implementation (reviewed baseline first)

**READ before modification (SOURCE-READ already):** v207 `duoview/joey_stage1/apply_stage1.py`, `apply_stage234.py`, `verify_stage234.py`, `apply_v207_auto_fov_after_load.py`, `.github/workflows/duoview-joey-stage234.yml`; Joey pinned `src/mods/vr/D3D12Component.cpp`, `src/mods/vr/runtimes/OpenXR.cpp`; PureDark AFW API, `VR.cpp`, `D3D12Component.cpp`, `OpenXR.cpp`; Witcher3VR bridge header/source and notices. Also inspect actual generated v207 `VR.hpp`, `VR.cpp`, `FFakeStereoRenderingHook.cpp`, `DuoViewState.hpp`, `DuoViewD3D12.hpp` through guarded patch replay before touching them.

**PLANNED only, NOT MODIFIED:** create `duoview/joey_stage1/apply_afw_stage1.py`, a narrowly scoped independent AFW bridge/header + assertions, Stage-1 source/ABI/provenance tests, and a **copy** of the v207 workflow under a new file targeting only the experiment branch. Existing v207 patch scripts should remain byte-identical. Enumerate every added or altered backend source path after local replay and before committing any implementation. Avoid embedding DLL and avoid committing a copied PureDark proprietary header.

## Verification ledger

| Gate | Status |
| --- | --- |
| Shared brief read first | SOURCE-READ ✓ |
| Available design review read | SOURCE-READ ✓ |
| Both independent reviews | **BLOCKED: second attachment not present** |
| Public v207/Joey/PureDark/Witcher source inspected | SOURCE-READ ✓ (not full locally built generated tree) |
| Actual beta-6 DLL ABI verification | **NOT DONE: DLL absent from accessible files** |
| Replay pinned patch scripts locally | **NOT DONE: container cannot resolve GitHub; restricted SDK unavailable locally** |
| Minimal-context independent model review of Stage-1 code | **NOT DONE: no Stage-1 diff or subagent execution available** |
| Stage-1 implementation pushed | **NO** |
| Windows GitHub Actions Stage-1 compilation | **NO** |
| Stage-1 PSVR2 headset validation | **NO** |

**Decision:** Record source findings now. Do **not** push a fabricated “working Stage 1” or run a misleading CI build before the actual binary ABI, local replay, and independent-review gates are satisfied. The goal is one trustworthy prototype, not a merely green workflow.

## Credit and rights

PureDark: AFW algorithm/plugin `PDAFWPlugin.dll`; used only under Liviu's reported non-commercial permission (scope to verify for redistribution). tig3rmast3r / Witcher3VR: MIT clean-room integration bridge, credits preserved with its license and third-party notices. Joey Hodge/UEVR and DuoView contributors: underlying render and patch architecture. No modification or bundling of PureDark DLL in this stage.

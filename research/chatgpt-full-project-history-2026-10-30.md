---
title: "QuadViews Mono / DuoView"
subtitle: "Complete project history, rendering architecture, research foundation, build evolution and engineering handoff"
author: "Technical reconstruction from repository documentation, recorded tests and user feedback"
date: "30 October 2026"
lang: en-US
---

# Contents

**Scope and evidence:** this report separates user-observed headset outcomes, GitHub/CI-tested code and still-unverified research hypotheses. Source links appear in §16.

- Executive overview
- Section 1 — Why the project exists
- Section 2 — Underlying software and real rendering concepts
- Section 3 — Architectures: how they actually render
- Section 4 — Technical pipeline in operational detail
- Section 5 — Build and design chronology — major milestones
- Section 6 — Detailed technical evolution of the synthetic-stereo branch
- Section 7 — User feedback — what specifically drove the design
- Section 8 — What performance evidence actually exists
- Section 9 — Research foundations and what is transferable
- Section 10 — Diagnosing the remaining failure modes
- Section 11 — Objective experiments, numerical metrics and acceptance standards
- Section 12 — Practical state as of 30 October 2026
- Section 13 — Recommended next engineering priorities
- Section 14 — Reproducible handoff for the next engineer or model
- Section 15 — Glossary and distinctions
- Section 16 — Sources, provenance and reading order

# Executive overview

**Project:** [liviutrn/UEVR-Quad-Views-Mono](https://github.com/liviutrn/UEVR-Quad-Views-Mono). **Primary target:** *S.T.A.L.K.E.R. 2* (Unreal Engine, DirectX 12, UEVR), PC PlayStation VR2 with eye tracking through PSVR2 Toolkit and SteamVR/OpenXR. **Reference machine:** NVIDIA RTX 5070 12 GB, Ryzen 7 5800X, 48 GB RAM, Windows 10 19044; PSVR2 commonly at 120 Hz. **Snapshot date:** 30 October 2026.

The project attempts something more ambitious than ordinary fixed foveated rendering. It changes *which Unreal scene views are rendered*, where their detail is concentrated, and how they are presented to the headset. There are three substantially different implementation families:

1. **DuoView Mono (proven useful):** a sharp, gaze-following, high-resolution central crop and a low-resolution full-field view from the **same camera**, merged into one monoscopic image and sent to both eyes. This provides normal head motion/6DoF but **not** binocular depth.
2. **True native Quad Views (proven possible, not satisfactory):** two views per physical eye, so four independent Unreal views, then per-eye composition. This produced genuine stereo on the headset but incurred serious CPU overhead, inconsistent lighting/shading, crashes, black starts and sometimes incorrect FOV.
3. **Asymmetric physical two-view synthetic stereo (current experimental direction):** render **one actual LEFT-eye high-resolution fovea** and **one actual RIGHT-eye low-resolution full-FOV periphery**. Use real game depth, physical camera transforms and GPU reprojection to synthesize the complementary missing regions. The output aims to preserve binocular parallax without rendering every region twice. Its latest identified experimental branch is **CI77**, which stabilizes the depth guides and prioritizes high-resolution LEFT depth for RIGHT-fovea synthesis.

**The central decision:** native two-eye stereo is the quality reference, not something philosophically rejected. It is expensive for this specific heavy Unreal/UEVR workload. Native four-view stereo is especially problematic because the engine may do work per view that does not shrink in proportion to pixels. The synthetic path is an experiment to achieve useful *physical* stereo with something closer to DuoView's source-pixel cost. It has **not yet demonstrated acceptable temporal stability in the headset**. CI77 has implemented mechanisms and tests, not a verified zero-jitter outcome.

**Evidence convention used here:** **Confirmed in headset** means the user actually saw or measured it; **CI/fixture validated** means build/tests or offline captures support that narrower statement; **Implemented/unverified** means code/docs describe a feature but there is no confirmed headset success; **Hypothesis** is an explanation still requiring controlled testing. User reports and source/CI facts are deliberately kept apart. This report is historical/engineering documentation, **not a claim that every binary was personally recompiled or that all previous chat messages were re-audited**.

# 1. Why the project exists

## 1.1 The performance versus presence problem

Modern Unreal Engine titles such as *S.T.A.L.K.E.R. 2* are costly in VR. In conventional native stereo, a separate physical viewpoint is rendered for each eye. Modern instancing and shared work may reduce the true overhead, so it is **incorrect** to assume all CPU/GPU cost always doubles. Nonetheless, duplicated high-resolution shading, view-dependent postprocessing, visibility, temporal effects and per-eye resources can make a demanding title unplayable at the desired resolution. The user's practical target often is **30 or 40 genuinely rendered frames per second**, sustained with SteamVR motion smoothing/reprojection at a 120 Hz display; uninterrupted frame pacing matters as much as mean utilization.

Pure Mono is cheaper, but sending the same source pixels to both eyes eliminates binocular disparity: objects do not have normal interocular depth even though head movement still creates motion parallax. That is a meaningful compromise in presence, scale and near-object interaction. The user wanted the sharpness/performance of gaze-driven DuoView **and** natural stereo depth in weapons, hands, NPCs and the surrounding world.

The strategic question became: **Can one expensive native foveal render and one cheaper opposite-eye peripheral render supply enough physical 3D information to reconstruct two correct stereo images, without the scene-processing expense of four views or two full-resolution views?**

## 1.2 Why not simply run native stereo?

Native full stereo is still the comparison baseline and the best representation of separately visible surfaces. It is not prohibited or inherently inferior. It is currently avoided *as the main high-performance mode* for three practical reasons:

- At very high eye resolutions the full per-eye pixel and shader costs can exceed the RTX 5070's comfortable budget; lowering resolution reduces foveal detail.
- In Joey/UEVR/Unreal experiments, independent view invocations added real CPU/render-thread overhead and per-view state/history complexities. These costs do not vanish when peripheral textures are tiny.
- The true four-view implementation showed visible shading asymmetry and runtime issues, so even when it produced stereo it did not produce the consistent image the user wanted.

A reasonable long-term design might still be native stereo with VRS, shared work, selective reprojection or a hybrid three-view arrangement. None should be dismissed without measurements. The present synthetic architecture is a deliberate **performance/quality experiment**, not proof it beats an optimized native-stereo renderer.

## 1.3 The visual non-negotiables

Retain the real physical eye baseline and normal world scale; do not fake depth by multiplying stereo separation. Preserve crisp high-resolution fovea; track gaze without a bouncing crop; keep high-detail foreground geometry; avoid wandering contours, duplicated fingers/weapons, flickering ownership and inconsistent shading. Keep original Mono as a fast rollback. A green GitHub Actions job is only a prerequisite: the standard of success is *headset-visible, stable, comfortable stereoscopy in motion*.

# 2. Underlying software and real rendering concepts

## 2.1 Upstream stack and hardware context

The independent fork builds on **praydog's UEVR**, **Joey Hodge's UEVR backend and frontend**, a pinned restricted **joeyhodge/UESDK**, and the **PSVR2 Toolkit** eye-tracking interface. The v182 source lineage also references [OpenNR commit 67c6e1e](https://github.com/liviutrn/OpenNR/commit/67c6e1ec5b931d2922e0ef5d253b8e9bef7a1a80). Source provenance in the repository pins Joey UEVR `5ac7edc...`, SDK `3cffbc8...`, frontend `60be4b0...`. Because the SDK dependency is access-restricted, a public patch alone is not necessarily independently buildable.

The implementation operates around Unreal rendering and UEVR's DX12/OpenXR output path; it is **not** simply a SteamVR overlay or an OpenXR foveation setting. It uses native scene-view construction and a D3D12 GPU compositor. The published `README.md` accurately warns that original DuoView Mono is **not** an implementation of an OpenXR quad-views extension despite the project name.

## 2.2 What fovea, periphery, native camera and synthetic camera mean

- **Fovea:** a narrow, gaze-centered view using a cropped projection of the scene and comparatively high pixel density; the practical chosen crop is about **0.50 × 0.50 of full FOV**. It moves with the tracked gaze; fixed-center is possible.
- **Periphery:** the whole field of view at much lower producer resolution; the experimental synthetic-stereo scale defaults to **0.20**, is user-controlled up to **0.499**, and must stay below the fovea producer size.
- **Physical native view:** a scene actually rendered by Unreal from one eye's real pose/projection (LEFT or RIGHT). It contains correct view-dependent occlusion, when its shaders/history behave correctly.
- **Synthesized region:** a view constructed by reprojection using an image and depth from the *other* physical eye. It can reuse correct visible surfaces but cannot reveal texture hidden from both sources.
- **Depth guide:** source-view geometry/depth sampled from a game's render pipeline, currently preferentially intercepted around DLSS Super Resolution/NGX. A guide contains values and metadata; it does **not** inherently certify which Unreal view, frame or object those values belong to.

## 2.3 A theoretical source-pixel budget, not a speed claim

For illustration only, a foveal crop occupying 50% of image width and 50% of height at nominal full pixel density covers **0.25 of one full-eye image**. A full-FOV peripheral image with linear resolution factor `s=0.20` covers **s² = 0.04 of one full-eye pixel count**. A two-source configuration would then shade a nominal **0.25 + 0.04 = 0.29 full-eye-equivalents**, versus **2.0** full-eye-equivalents for idealized dual full-resolution images. Under these *simplified* assumptions, the source pixel count is **14.5%** of two full-eye images.

**Do not mistake that for an 85.5% measured GPU saving.** The actual crop implementation, density, upscaler render dimensions, eye texture allocation, fovea edge, duplicate overdraw, Lumen/Nanite/reflections, constant-cost scene work, motion/depth capture and reconstruction passes all matter. Also, exact scale semantics must be checked for each build. This arithmetic explains the motivation, not final performance.

# 3. Architectures: how they actually render

## 3.1 Architecture A: stable DuoView Mono

```text
PSVR2 gaze + shared UEVR/Unreal MONO camera pose
                     |
          +----------+----------+
          |                     |
  Unreal high-resolution   Unreal low-resolution
  gaze-cropped FOVEA       full-FOV PERIPHERY
  same mono viewpoint      same mono viewpoint
          |                     |
          +----------+----------+
                     |
        DX12 same-frame composite
          crop alignment + feather
                     |
          ONE full-field Mono image
                     |
        OpenXR LEFT = RIGHT image
```

Its principal strength is predictable alignment: both source views originate from the **same** viewpoint. Mis-registration is mostly a gaze/crop/jitter/timing problem rather than true stereo occlusion. The v182 baseline resolved severe earlier gaze jitter/trembling and asynchronous delivery problems on the user's headset. The v186.1 line integrated **Glamarye Bigger Sharpen** as fovea-only D3D12 sharpening (0–2 strength, nominal default 1.0), eliminating the need for a separate OpenXR sharpening layer. Subsequent v186.2 / Build206 is identified in the CI73 handoff as the stable public Mono track. Save/load, material-parameter overrides (MPC_FOV), first-person/HUD convergence and persistent eye alignment have been ongoing integration concerns.

**Limitation:** copying that same image into left and right headset images preserves 6DoF head tracking but cannot provide genuine binocular parallax. A split-eye variant that renders from two different source cameras but still *copies one mixed image to both eyes* is not real stereo either; it can change local apparent position or generate double/incorrect viewpoint cues.

## 3.2 Architecture B: true native Quad Views

```text
LEFT native eye pose                 RIGHT native eye pose
   |            |                       |            |
LEFT fovea   LEFT periphery         RIGHT fovea  RIGHT periphery
   +------------+                       +------------+
     LEFT composite                      RIGHT composite
           +-----------------------------------+
                  stereo OpenXR submit
```

The 2026-10-20 to 2026-10-27 branch series tried this four-Unreal-view route. On good builds the user **saw stereo and working gaze**. Its structural flaw was **not** that four views cannot work; it was that this game/render pipeline repeatedly executed scene/view CPU work and could generate independent exposure, lighting, ambient occlusion, Lumen/reflection or temporal state. In-headset testing found dramatically brighter indoor images with reduced shadows in some builds, apparent fovea/periphery and eye-dependent shading differences, brief successful startup followed by black output, and build-specific FOV regressions. The Native Stereo Fix had to apply to **all four** views and their source identity/lifetimes, not just one primary eye.

It is an important architectural reference and a real-stereo proof of concept, but not the preferred production implementation on this machine. Retain it for correctness, comparisons and as potential ground-truth capture, not as a silently interchangeable implementation of DuoView.

## 3.3 Architecture C: asymmetric two-camera synthetic stereo

```text
        one actual physical LEFT-eye viewpoint
                   |  0.50 x 0.50 gaze crop
            NATIVE LEFT FOVEA  ------------+
                   |                        |
   source color + LEFT DLSS depth/MV        |
                   |                        v
                   |             high-res geometry / LEFT→RIGHT warp
                   |                        |
                   |                        v
       LEFT eye output                SYNTHETIC RIGHT fovea
       native LEFT fovea                     |
       + synthetic LEFT periphery            |     RIGHT eye output
                   ^                        |     synthetic RIGHT fovea
                   |                        |     + native RIGHT periphery
   RIGHT→LEFT warp  |                        |
                   |                        |
           NATIVE RIGHT PERIPHERY -----------+
             low-res full-FOV
        one actual physical RIGHT-eye viewpoint
        source color + RIGHT DLSS depth/MV
```

The intended eye outputs are asymmetric **but physically anchored**:

| Displayed region | Preferred source | Operation | Main intrinsic risk |
| --- | --- | --- | --- |
| LEFT fovea | Actual LEFT high-resolution view | Direct/native | Gaze crop or temporal source mismatch |
| LEFT periphery | Actual RIGHT low-resolution full-FOV view | RIGHT-to-LEFT depth-guided warp | Lower spatial detail; target disocclusion |
| RIGHT fovea | Actual LEFT high-resolution fovea | LEFT-to-RIGHT depth-guided warp | Foreground edge accuracy; missing RIGHT visibility |
| RIGHT periphery | Actual RIGHT low-resolution full-FOV view | Direct/native | Low detail; disparate temporal shading |

Both eyes use their actual headset poses; the reconstruction supplies complementary regions rather than collapsing the final output to mono. The user confirmed genuine 3D was visible after manually selecting valid depth inputs, but also reported severe instability. **The hard problem is not creating some parallax; it is reconstructing correct, stationary-in-world surfaces at every frame and maintaining consistent binocular occlusion at silhouettes and close objects.**

# 4. Technical pipeline in operational detail

## 4.1 3D scene-view requests, gaze and camera geometry

UEVR and Joey's Native Stereo Fix machinery are used to request the views with distinct left/right pose, crop and projection matrices. For the experimental mode, LEFT has a cropped high-density camera, RIGHT is full-FOV low-density. Gaze is a screen-space location that drives the foveal crop; the crop moves but should not change the *physical* camera or artificial world scale. For every frame, the effective renderer needs the eye index, camera-to-world and world-to-camera transforms, projection (jittered and unjittered), near/far/device depth convention, crop extent, active depth rect, source allocation dimensions and output dimensions.

Coordinate spaces must never be confused: (a) full-eye unjittered normalized UV, (b) local cropped fovea UV, (c) DLSS active-subrect texels, (d) allocation texels, (e) NDC/clip coordinates, and (f) eye/world 3D coordinates. Incorrect mapping can look like a correct still frame but jitter as DLSS sample phases change. Normal versus reverse-Z, depth range, world-to-meters and viewmodel projection need explicit treatment.

## 4.2 Capture at the DLSS/NGX boundary

The original DSV (depth-stencil-view) path tried to discover plausible game depth by enumerating DX12 resources and checking format/shape. This often selected shadow maps or stale/overwritten resources. The project therefore moved to **DLSS/NGX Super Resolution guide inputs** that the game already supplies: color, depth, motion vectors, jitter, active subrect and evaluate/feature identities. Example guides observed in headset captures were roughly **860 × 684** for a foveal input and **344 × 276** for a peripheral input, *not* the full 2,500-pixel-class presentation texture. This mismatch previously blocked or misaligned reconstruction routines expecting output-sized depth.

Using the game's DLSS depth is a strong engineering move **because it gives a real, active producer resource**, not because DLSS creates a perfect geometry oracle. NVIDIA's published programming guidance specifies pixel-space jitter, depth encoding and motion-vector flags/scales, and notes that missing thin geometry remains a challenge [E2]. An intercepted NGX Evaluate still must be matched to the actual Unreal camera, eye, exact frame, and correctly captured guide generation. One can have convincing depth thumbnails yet wrong time/pose association in real stereo.

Manual LEFT/RIGHT pinning became necessary after automatic candidates switched frequently and mis-selected resources. Correct dimension/type/generation filtering is useful but **dimensions are not proof of physical camera identity**. Feature objects can be recreated on resize or DLSS change. CI69–CI70 add freshness/generation checks and require explicit unsafe-mode opt-in when identities remain unverified.

## 4.3 D3D12 lifetime, GPU fences and producer-consumer safety

A DLSS guide can be overwritten or released before a compositor uses it, even when its CPU pointer still exists. The captured source has to be copied after the relevant evaluation, with correct resource states and queue ownership. The capture/render paths use retained snapshots, command lists, fences, resource-state transitions, explicit source generation and lifetime checks. Cross-thread producer ticketing bridges intervals but is not a substitute for authenticated UE eye/frame identity. Bad conditions must fail closed instead of sampling a random stale slot.

Earlier corrected failure patterns included copy-before-completion, reuse/overwrite before consumption, wrong producer resource extent, missing source pair, invalid stereo transition, and mixing newly resized source slots with old-size depth. The code has a meaningful test suite around these hazards, but **WARP or Windows build success is not a real-game timing guarantee**.

## 4.4 Transform, warp, visibility and composition

The geometry conversion is conceptually straightforward for a valid surface sample: reconstruct 3D from **source pixel + source depth + source inverse projection**, transform through source camera/world to **target camera**, project to target pixel, and compare with the target's nearest independently measured surface depth where available. The difficulty is which *surface* an aliased low-resolution pixel actually represents, whether that surface is visible in the target and how to fill or reject holes.

**Forward warp / mesh or splat:** project LEFT source depth samples into RIGHT. High-resolution LEFT geometry preserves edges, but source samples can leave holes; triangles crossing a foreground/background discontinuity create false surfaces. CI71's stride-2 surface mesh and edge tests attempt to prevent this.

**Target-guided inverse gather:** for each RIGHT target pixel inspect nearby RIGHT depth candidates and look back into LEFT source. CI72 can reject target-occluded features, but its coarse right-depth neighborhoods can arbitrarily select foreground/background across a moving sample lattice.

**Coverage and ownership:** reconstructed alpha means a candidate generated geometric coverage, not proof the color is correct. If synthetic and native views depict displaced silhouettes, interpolating their RGB across 20–80% alpha creates two hands or double edges. CI76 addresses this mechanism by selecting one owner per pixel (with native fallback where appropriate). Ownership should eventually be temporally consistent at a *surface* level, not merely hard-switched independently each frame.

**Disocclusion:** a surface behind a foreground object may be visible only from RIGHT and not from LEFT, or vice versa. No depth filter can recover unseen color perfectly. The honest options are validated other-eye color, geometry-aware hole filling or bounded fallback, with coverage and error reported. Reflections, translucent surfaces, screen-space effects, animation and separate viewmodel cameras are more difficult than opaque static geometry.

## 4.5 Why DLSS depth itself jitters and why preview must show the processed map

DLSS uses subpixel phase shifts and history-aware reconstruction. A depth pixel location may therefore alternate between neighboring geometric footprints even when a world-space edge is stationary. Directly reprojecting raw, phase-varying guide texels means the *reprojection geometry* changes across frames. Merely showing a smoothed final RGB image is inadequate; the user specifically required the depth source to be stabilized **before** reconstruction and the on-screen depth-preview toggle to display the exact processed guide. That is the CI77 validation principle.

CI77's proposed order is: decode active depth rect + device-Z, remove the current phase shift onto a canonical per-eye sampling grid with discontinuity-aware support, optionally reproject compatible prior stabilized depth with previous/current eye matrices, reject inconsistent historical geometry and reset on source/layout changes, then feed that same output to the warp and optional preview. RIGHT coarse depth is restricted to visibility validation, not an authority that invents fine LEFT geometry. The spatial/temporal method is **implemented and WARP-tested in the experimental source**; the headset has not yet shown whether all moving edges are stable or whether history trails and dynamic geometry require further work.

# 5. Build and design chronology — major milestones

**Numbering warning:** project build numbers, feature-level `CI##` labels, GitHub Actions run numbers (`#94`, `#102`, etc.), and release versions (`v182`, `v186.1`, `v186.2`) are **different numbering systems**. Build 51 in the native-quad family is not necessarily CI51 in the later NGX family. Names must be accompanied by branch, commit or artifact when reproducing results.

| Period / build family | What changed | Recorded result / what was learned |
| --- | --- | --- |
| 12–14 Oct: DuoView concept and early builds | Same-pose high-res fovea + low-res periphery, OpenXR Mono output; Native Stereo Fix-backed source rendering | Early public-SDK code compiled; integration/real headset required; a later Build 3 reportedly completed 30 min without hitches. |
| Mono Build 33–37 | Eye tracking/crop handling, initialization sequencing, Native Stereo-before-DuoView workaround | Build 33 crop trembled; fixed-center steadier; builds 34–35 crashed in NVIDIA NGX; initialization order affected success. |
| Mono v168 / v182 | Hardened gaze stabilizing, frame transactions and mono composition | Significant GPU savings recorded in specific scenes; v182 binary became known-good after user confirmed no stutter/flicker/gaze jumps. |
| 19–20 Oct: public release / v186.1 | Public repository and pinned upstream provenance; fovea-only Glamarye shader, persistence/HUD/MPC repair work | v182 retained unchanged; v186.1 sharpen released. Later v186.2/Build206 identified as stable Mono line. |
| Native Quad Build 32 | First headset four-view stereo prototype | Four views/3D briefly visible, but crash, intermittent two-view operation and missing eye tracking. |
| Native Quad 39–40 | View demand latch, explicit ownership, per-eye gaze, compositor and lifetime tests | Build 40 was substantially better: real 3D and gaze/performance at times; black startup, very bright indoor shading and missing-looking shadows/Lumen. |
| Native Quad 41–44 | FOV, eye role and Native Stereo Fix attempts | Build 41 worked briefly but smaller FOV/black output; Build 42 partial fix; Build 44 flashed picture then black with waiting/loading. |
| Native Quad 45–52 | Render-family accounting, all-view native-fix, safety and transition tests | Build 51 confirmed real Quad Views but poor CPU and mismatched shading; Build 52 compiled with changes, not a headset-proven cure. |
| 23–27 Oct: DSV depth proof and DIBR R2/R5 | Depth candidate discovery, raw capture, bidirectional reprojection, split-eye tests | Several real depth candidates looked convincing; automatic/manual selection often wrong, R2 failed, R5 still artifacted, split-eye copied mono did not create stereo. |
| 28–29 Oct: CI31–CI51 / CI66–CI68 | Geometry/camera audits, snapshot lifetime, NGX capture/pairing, initial stereo raster modes | Build/fixture tests passed; many early runs did not establish in-headset efficacy or correct depth/camera identity. |
| 29 Oct: CI69–70 | Manual pinned NGX source registry, freshness and independent previews, explicit unsafe stereo opt-in | User finally manually selected recommended DLSS depth and saw real 3D, but severe silhouette shimmer remained. |
| 29–30 Oct: CI71–73 | LEFT-forward anchored geometry, RIGHT inverse-gather research A/B, conservative single-owner strategy | Better geometric hypotheses, passing CI; not an established stable image. CI73 workflow #94 passed. |
| 30 Oct: CI74 | Corrected RIGHT depth-jitter lookup/mask coordinates and 2×2 footprint | **72,160 → 0** mismatches across **663,552** WARP fixture samples; strong proof of a specific coding defect, not proof of overall visual stability. |
| 30 Oct: CI75 | Lossless two-second stereo/depth diagnostic capture and analysis | Build #102 recorder line; 83-frame/1.97 s capture available for inspection; data showed real composition/pairing failures. |
| 30 Oct: CI76 | Exclusive owner compositor, resize recovery, native RIGHT fallback, eight-pair hysteresis | Mixed-owner test pixels **8,496 → 0** in targeted fixture; removes a concrete doubled-silhouette mechanism; real headset flicker/black remains open. |
| 30 Oct: CI77 | Pre-reconstruction jitter-phase depth correction, optional camera-reprojected depth history, LEFT authoritative high-res geometry, processed preview | Experimental source and GPU fixtures exist; no demonstrated zero-jitter headset acceptance, complete temporal stability or RTX5070 benchmark as of this snapshot. |

# 6. Detailed technical evolution of the synthetic-stereo branch

## 6.1 Before NGX: why the DSV/DIBR approach was fragile

DIBR means **depth-image-based rendering**, not a specific source-selection technology. The first attempts captured likely depth-stencil resources and tried to warp a monocular or mixed view. The failing assumption was that an available D3D12 depth texture of plausible dimensions was necessarily the camera's final view depth. Unreal makes many depth-like resources: main depth, shadows, prepasses, custom/depth effects, different eye views, and reused allocations. Timing and lifetime were equally critical: depth could be overwritten before reading, or a capture might correspond to a different render view. Build #118's seven depth candidates included identical 860×684 foveal-looking selections, identical 344×276 peripheral-looking selections, a likely shadow atlas and a largely empty candidate. This proved capture feasibility **but not authenticated eye/frame matching**.

The user repeatedly rejected iterations that compiled yet never produced playable stereo. The corresponding lesson is that source correctness, exact transform/viewport and GPU ordering must be proven before polishing raster shaders. Later CI31–CI51 addressed portions of this: saved depth copies, source-space geometry and target-space visibility, distinct diagnostic output modes and the start of a frame transaction contract.

## 6.2 CI49–51 / CI66–68: moving toward actual DLSS guides

The NGX route observes DLSS SR feature evaluations. Its benefit is a concrete producer boundary and known inputs: depth, color and motion. It introduces its own complications: interception timing, feature-object generation, separate RHI/UEVR threads, source dimensions at DLSS input rather than final presentation, active rect offsets, reverse Z and pixel-space jitter. CI51's experimental output description specified **native LEFT fovea + RIGHT-to-LEFT synthetic periphery**, **synthetic RIGHT fovea + native RIGHT periphery**, modes 4/5/6, and a right-fovea operation that initially leaned on coarse RIGHT target depth. GPU tests initially evaluated real shader logic on synthetic geometry, not real STALKER 2 artifacts.

CI67's cross-thread ticket linked producer packets with consumer frames more robustly. But a time-adjacent DLSS call is **not equivalent to authenticated camera provenance**; two nearby evaluations can refer to different eyes, view families or temporal resets. That limitation persists in the research agenda.

## 6.3 CI69 and CI70: a turning point in headset usability

In a crucial headset session the user had to **manually choose the recommended DLSS depth**, after which they could see real stereo. Automatic depth selection was not reliable enough. CI69 therefore tied a pin to NGX feature identity, dimensions and generation and prevented stale/duplicate role pairing. CI70 allowed isolated previews of LEFT or RIGHT depth even without a valid pair, and made dangerous unverified stereo explicitly opt-in.

This was progress: before that, a black frame or mono fallback could hide the fact that reconstruction never had the correct input. The diagnostic preview made the actual selected guide visible. It still did not guarantee that every displayed stereo frame had synchronized camera matrices, source colors and depth.

## 6.4 CI71: high-resolution LEFT forward geometry

CI71 treats high-resolution LEFT depth as an important geometric anchor. It projects sampled LEFT surfaces toward the RIGHT eye using a mesh, with discontinuity checks on mesh cell corners and interior points so triangles should not span arbitrary foreground/background jumps. It uses hardware depth/visibility and tests more than mere color alpha. The strengths are retention of fine LEFT foveal edges and reduced dependence on coarse RIGHT depth for geometry generation.

Its weakness is undercoverage or false coverage around one-texel silhouettes and unstable edge classification when a stride-2 mesh changes ownership under jitter. Rejecting a cell can be safer than fabricating a surface, but if rejection toggles every other frame, the resulting foreground flickers even with correct camera transforms.

## 6.5 CI72: inverse gather using RIGHT target depth

CI72 was a research counterproposal: infer the surface seen at the RIGHT target pixel from the local RIGHT depth footprint, back-project to a matching LEFT source position and check visibility there. It can be more target-correct in uncomplicated geometry, but the 344×276 RIGHT depth is too coarse to unambiguously represent finger edges, thin poles or weapon outlines. The 2×2 candidate pool can switch abruptly between object and background. Correct target visibility does not automatically produce a stable high-resolution RIGHT fovea if the target geometric sample is wrong.

## 6.6 CI73 and CI74: compositor ownership and precise jitter lookup

CI73 proposed stronger single-owner compositing, crop seam restrictions and near-viewmodel protection; a conservative strategy was available behind an A/B toggle. It did **not** fix all temporal failure modes. The subsequent code audit found two concrete mask bugs: RIGHT depth fallback/edge functions sampled unjittered output coordinates while the reconstruction used jittered source coordinates; and the 2×2 edge footprint was anchored at the wrong pixel-center offset. CI74 corrected both, without adding extra passes or changing stereo geometry, and deliberately preserved real DLSS jitter.

The focused test is unusually good evidence: on its controlled WARP input, the pre-fix production function had **72,160 sampling-footprint mismatches in 663,552 checks**, including **6,272 even at zero jitter**; the corrected function had **zero**. Separate coordinate fixtures passed **38,400** checks. These prove a deterministic offset bug was eliminated **for the declared convention**. They do not prove that STALKER 2's actual producer jitter sign, engine camera matrices or all other shaders are correct.

## 6.7 CI75: captures finally made failure measurable

CI75's recording system captures up to **2 s or 96 distinct game-rendered packets**, not synthetic SteamVR reprojection frames; captures are split into **at most 20 MiB ZIP parts** plus `_index.json`. It preserves native output LEFT/RIGHT eye strips, real LEFT foveal/RIGHT peripheral color, raw depth, synthetic output/coverage and optionally selected NGX motion. It records resource formats and active rectangles, physical camera transforms, projection, gaze, jitter, feature generations, frame IDs, selected strategy and source timing. Numerical bytes are saved losslessly, sometimes in PNG containers that do *not* look like ordinary photos until decoded. The analysis script and tests explicitly flag missing planes and incomplete captures.

A reported **83-frame, ~1.97-second capture** provided substantially better evidence. It showed both depth and synthetic planes but the active algorithm was **`CI71_LEFT_MESH`**, not the expected CI73 conservative strategy. Repeated incompatible depth pairs caused fallback, and synthetic coverage was roughly **82% of RIGHT fovea** and **60% of LEFT periphery** (capture-specific median figures, *not* universally achieved coverage). That test also revealed mixed synthetic/native rendering around displaced hand edges, and that periphery resizing disturbed source pair selection. Offline analysis indicated a depth phase-correction approach could reduce variation on smooth stationary regions by about **85%**, but boundary flicker was still unresolved. Captures themselves cannot provide ground-truth hidden surfaces or automatically authenticate game-eye identities.

## 6.8 CI76: one actual color owner at each pixel, safe resize recovery

The user reported doubled peripheral hands, persistent jitter and black/flickering output after periphery resolution changes. CI76 made a concrete compositor policy change: **do not blend independently projected native and synthetic silhouettes at partial alpha** for modes 4/5; instead, choose exactly one source owner at each output pixel. It retained depth visibility checks, made near-field protection universal in synthetic areas and removed an extra coarse RIGHT-depth veto at final composition that had driven contour sharpness switches.

It also delayed periphery resizing for **250 ms** after edits, migrated only an explicitly pinned NGX feature to its new expected extent, and required **eight consecutive fresh compatible source pairs** before restoring stereo after an interruption or resize. During recovery both eyes display **current native RIGHT full-field color**, a deliberate low-resolution mono fail-safe. A controlled GPU test counted **8,496 mixed-owner pixels before vs zero after**; this validates a particular doubled-image mechanism, not complete silhouette reconstruction. The change could eliminate one category of double hand even while leaving geometric jitter from depth and missing target color.

## 6.9 CI77: the present depth-stabilization proposal

CI77 shifts stabilization **upstream**: the depth map actually used for warping is corrected before creating a synthesized fovea or periphery. Source files `ci77/DuoViewDepthStabilization.hlsl`, `.hpp`, `patches.json` and WARP tests implement a spatial phase-alignment shader plus an optional temporal history stage.

Spatial processing estimates a depth layer from a local four-sample neighborhood around `pixel + jitter` in **source input texel units**, chooses compatible geometry to avoid averaging foreground and background, and outputs a canonical depth grid in device-depth encoding. Temporal processing projects current geometry into the previous eye/crop frame, tests prior depth agreement and reprojection error, and selectively retains history. Separate per-eye/per-command-slot ping-pong histories are designed to reset for source/layout changes and protect resources with ownership/fence logic. Typical defaults are **stabilization ON**, **temporal ON**, **75% depth-history weight** with adjustable **0–90%** range. Turning temporal OFF keeps current-frame phase correction and creates a useful A/B control.

With stabilization ON, **high-resolution LEFT depth is authoritative for synthesizing the RIGHT fovea**. The old coarse RIGHT inverse-gather algorithm is bypassed even if a legacy toggle is enabled; RIGHT depth remains a conservative **visibility** check. Importantly, mixed coarse foreground/background footprints are not allowed to veto sharp LEFT geometry by themselves. The full available native LEFT crop is retained to its boundary, and LEFT-peripheral foreground is not deliberately replaced wholesale with RIGHT-camera hand geometry. True disocclusions remain unresolved in principle.

The user specifically demanded that choosing LEFT/RIGHT depth preview display the **same stabilized textures actually fed into the reconstruction** when stabilization is enabled. This is addressed in CI77's controls/patches. Capture also adds `depth_stable_left` and `depth_stable_right` planes alongside original raw depth where available. There are actual shader fixture tests for sloped planes, opposite jitter phases, thin/discontinuous edges, same-surface temporal reuse, old-background rejection, misprojected history and reset. **These are implementation checks only:** a stable-looking depth map in a test cannot establish tracking through animated NPCs, exposure changes, head rotations or nonrigid geometry in the real game. A result of *absolutely no jitter* has **not** been verified.

# 7. User feedback — what specifically drove the design

The following are meaningful historical observations, not generic theoretical complaints.

| Feedback or test observation | What it meant and the engineering response |
| --- | --- |
| DuoView gaze crop/image trembled or jumped; fixed center steadier | Gaze smoothing, crop quantization, frame-state ownership and presentation sequencing required attention. v182 later became stable enough to preserve as rollback. |
| Native Quad Build 32 showed four-view 3D briefly, then crashed; eye tracking missing | Basic multiview rendering was feasible but mode lifecycle and gaze were not production-ready. |
| Build 40 was much better than Build 39, but startup sometimes black; indoors far brighter with seemingly absent shadows/Lumen | Preserve working four-view baseline; inspect per-view lighting flags, history, Native Stereo Fix and source dispatch instead of assuming success. |
| Build 41 had narrower FOV; Build 44 flashed image then black | An apparent view count or compiler pass did not guarantee correct projection nor sustained OpenXR submissions. |
| Build 51 genuine QuadViews worked, but CPU performance was 'really bad' and shading differed between views | Strong motive to reduce number of independent Unreal views and pursue synthetic stereo, but compare against measured native stereo. |
| Split-eye fovea/periphery copied into identical outputs showed no useful stereo | Different camera samples are not enough unless the final headset LEFT and RIGHT images differ with correct physical geometry. |
| DIBR depth candidates looked clear in saved images; selected source often wrong | Good looking depth picture is necessary but insufficient. Pin features and authenticate frame/eye/crop; never silently substitute shadow depth. |
| Manual selection of recommended DLSS depth produced real 3D | Proof that actual synthetic-stereo pipeline can work in principle when a plausible guide pair is selected. |
| Despite RIGHT periphery up to 0.499, hands and object edges had strong flicker, edge wandering and trembling | More RIGHT depth resolution alone was not enough; high-resolution LEFT geometry, provenance, phase alignment and temporal ownership become priorities. |
| User pushed sliders toward LEFT-dominant reconstruction, asked to use LESS coarse RIGHT depth | CI71–CI77 increasingly prioritize LEFT color/depth for the RIGHT fovea; RIGHT depth becomes visibility evidence. |
| User observed a doubled hand only in LEFT fovea versus LEFT periphery; RIGHT looked acceptable | One suspect was native/synthetic RGB blending across displaced hands; CI76 imposed exclusive per-pixel ownership. Other causes remain possible. |
| Changing peripheral resolution previously produced black output, then was reported working again | CI76 added resize debounce, pin/extent migration and eight-good-pair reacquisition. The user's later report confirms periphery resize could work without black, not that all transitions are solved. |
| 'We need depth completely stabilized; the jitter is unacceptable' | CI77 applies geometry stabilization before reconstruction rather than merely softening the final picture. |
| 'When I see the depth with your menu toggle, show it actually stabilized' | CI77 tries to make processed RAW/STABILIZED preview verifiable and separately configurable. |
| 'Use high-resolution left depth as primary geometry for right fovea; constrain coarse right depth to visibility checks' | Adopted explicitly in CI77's active reconstruction strategy; this is a binding architectural requirement, not an optional cosmetic slider. |
| User requested an independent technical review and measurable experiments rather than more ungrounded build promises | Preserve capture evidence, alternative algorithms, failure counters, same-frame A/B replay and no production claim without headset tests. |

The repeated user preference is consistent: prioritize a *playable, genuinely stereoscopic and stable* headset result; thorough review is welcome, but research with no functioning testable implementation is not considered sufficient. An assistant should not call a Windows green build “fixed” without on-device evidence. The project should use well-defined, separate A/B modes rather than a crowded collection of ambiguous sliders, and keep the known-good Mono release untouched.

# 8. What performance evidence actually exists

## 8.1 Measured or reported Mono/DuoView evidence

An earlier **v168** comparison at approximately **3136 × 2768**, 50% crop, in a 40 FPS-capped context recorded **DuoView 40 FPS at 67% GPU utilization**, versus **Mono 40 FPS at 74% GPU**. Relative utilization reduction: `(74−67)/74 ≈ 9.5%`. A native stereo comparison in that test was reported around **31 FPS and 97% GPU**. Other recorded scenes reported ~25.8–30.5% lower GPU use for DuoView versus Mono. These are environment-dependent observations and the rendering mode details matter; a 40 FPS cap prevents direct inference of unlocked frame rates.

A later approximate comparison near **3144 × 2500** reported **Duo 69% GPU**, **Mono 91% GPU**, and **native stereo around 100% GPU with 34 FPS** in one scene. The README's **up to 50% greater FPS than Mono / 85% over Native Stereo** should be read as **extrapolations from utilization under a frame cap in favorable GPU-limited conditions**, *not direct controlled uncapped FPS measurements*. The repository README itself makes that qualification.

## 8.2 Why GPU utilization alone is inadequate

For synthetic stereo, measure per-stage GPU timestamps, CPU render-thread times, frame-ID continuity, synchronization stalls and p95/p99 rather than a single utilization percentage. A depth stabilizer can have modest shader cost yet add a new dependency/fence wait. Four-view rendering may be CPU-bound even if pixels are low. At 120 Hz headset refresh with 30 or 40 true FPS, repeated frames and motion smoothing can make a barely changing world contour appear to vibrate. A synthetic effect that achieves faster frames but distractingly unstable object edges is not an improvement.

**Current evidence gap:** no published same-scene RTX 5070 side-by-side measurement yet establishes CI77's GPU and VRAM overhead or whether the new depth-history stage wins in actual headset stability without ghosting.

# 9. Research foundations and what is transferable

The program is grounded in several fields, but no single paper proves it can synthesize native-quality stereo for this game. The CI73 engineering handoff and deep-research assignment articulate hypotheses and experiments; a subsequent repository review explicitly warns that one research report lacked a retrievable source bibliography and that its proposed HSVR-L2 replacement architecture was **untested**, not a validated winner [P5]. Therefore research recommendations should be treated as designs to test, not historical accomplishments.

## 9.1 Classical view synthesis / depth-image-based rendering

The DIBR idea is to transform visible surface samples from one camera into another camera using depth and projection. The *Layered Depth Images* paper by Shade, Gortler, He and Szeliski (SIGGRAPH 1998) explicitly addresses warping, multi-layer visibility and occluded surfaces [E1]. This maps to our hole-filling/visibility problem: a single depth value per ray cannot represent surfaces hidden behind the first layer. However, the paper does **not** claim that arbitrary hidden game geometry can be recovered from one image. Current DuoView only has two *partial and asymmetric* real views, not a rich multi-layer scene capture.

## 9.2 Temporal reprojection and video denoising principles

History can reduce per-frame sampling noise only when a previous sample truly represents the **same world surface**. For static geometry, camera transforms can project current 3D surface positions into the preceding frame. For animated or skinned NPCs, camera-only history is insufficient; correct object motion vectors and source provenance may be required. Reject history on disocclusion, depth mismatch, invalid motion, gaze crop exit, resized input, fresh NGX feature generation, large camera change or mismatched exposure. Otherwise stabilized depth becomes **ghost depth** and produces a trailing edge, sometimes worse than raw flicker.

CI77 is an initial conservative depth-history implementation, not a complete motion-guided per-object temporal stereo synthesis system. A future surface-ownership history may need separate native/synthetic surface IDs and confidence to suppress flickering decisions without flattening stereo or carrying invalid color.

## 9.3 DLSS's real guide contracts versus the 'perfect depth' myth

NVIDIA's DLSS programming guidance documents input-resolution depth, active input extent, explicit jitter and motion-vector direction/scale/flags [E2]. It describes thin-feature and motion-vector failure cases even when DLSS successfully reconstructs the game image. Consequently:

- DLSS *has* depth and motion inputs; interception is a sensible source acquisition method.
- Its own output looking sharp **does not mean** every input depth pixel is a perfect high-resolution geometric truth.
- A feature-evaluation intercept alone does not identify a UEVR physical eye or camera frame unless the engine and hook metadata prove it.
- Depth is typically at **render input scale**, not necessarily final upscaled resolution; interpolating it cannot invent fine silhouettes that never existed.
- Native game motion vectors can have signs, scales, jitter inclusion and object-coverage conventions that differ from our reconstruction assumptions.

## 9.4 Foveated rendering and stereo alternatives

Engine-supported foveation/VRS reduces peripheral shading, and Unreal also exposes instanced stereo [E3]. These are real alternatives, but their benefit on a particular UEVR-injected title depends on renderer/game path and per-view work. Original DuoView's advantage is that it actively renders a gaze-cropped high-density scene view plus a lower-density context scene view instead of merely masking pixels after a full render. The four-view version increased independent view CPU costs, suggesting experiments with **two physically distinct native views plus reconstruction**, or later **three views** if quality requires one additional low-cost native source.

## 9.5 Related approaches considered but not proved useful here

Optical-flow frame interpolation (OFXR, etc.), neural depth super-resolution, traditional edge-aware upsampling, learned stereo synthesis, multi-plane imagery, surface splats and asynchronous timewarp may contribute methods. But frame-generation motion smoothing does not solve incorrect interocular depth or upstream jittery geometry. Running an additional neural model can cost latency/VRAM and may hallucinate edges. The user's earlier experience with OFXR was that higher FPS did **not** reliably feel smoother than SteamVR motion smoothing, so subjective comfort and temporal artifacts must be included in the benchmark. For now, deterministic source registration, geometry/depth conditioning and conservative history acceptance are a more testable first step than speculative AI upsampling.

# 10. Diagnosing the remaining failure modes

The order below reflects a defensible *working* ranking based on source reviews, CI75 evidence and user reports. Only individual controlled tests can establish causality and relative importance.

| Root-cause candidate | Evidence / confidence | Distinguishing experiment |
| --- | --- | --- |
| Sampling-phase / jitter mismatch between guide and masks | **High for CI73 bug**; fixed in CI74 fixture | Replay identical depth with several known input jitter phases and compare raw vs canonical grid at stationary edges. Verify actual in-game sign via captures, not convention alone. |
| Coarse RIGHT depth aliasing at foreground silhouettes | **High plausibility** from 344×276 and observed fingers/hands | Compare LEFT-authoritative CI77 to CI72 target inverse gather on *same captures*; score edge disparity and foreground leakage. |
| Wrong NGX feature/eye/frame association, stale pairing | **Medium–high concern**, repeated pair failures in CI75; no authenticated per-eye proof | Log UE view-family/pass IDs and exact NGX eval + color/depth/MV generations, assert immutable per-frame identity. Deliberately mismatch candidates in a fixture. |
| Mixed RGB ownership between cameras | **High for one doubled-hand mechanism**, 8,496→0 fixture CI76 | Capture per-pixel owner masks; inspect hand silhouette while toggling exclusive ownership only. |
| Unstable rejection/hole-filling around depth discontinuities | **High plausibility**; CI71/72/73 classification changes | Compare warped coverage/owner flips with ground-truth occlusion under subpixel motion, near poles and hands. |
| Incorrect viewmodel projection or independent effects/shading | **Medium**, QuadViews lighting and hand symptoms | Independently record camera projection/crop for world and first-person viewmodel, plus native LEFT/RIGHT baseline samples. |
| Temporal history misses motion/disocclusion/reset rules | **Future risk** in CI77, no headset validation | Moving object crossing a static background; measure trailing ghosts, history accepted/rejected, reset latency. |
| SteamVR reprojection artifacts or bad frame pacing | **Potential amplifier**, not sole evidence for depth jitter | Compare genuine saved rendered frames against headset-synthesized cadence at matching 30/40 FPS, MS ON/OFF. |

Crucially, *depth stabilization is not the same as geometry truth*. A perfectly still but wrong depth edge produces a **stable wrong stereo object**. Conversely a high-confidence edge that follows a real moving hand should move in world space. Success is not zero pixel change on the map; it is removing **unphysical** variation while respecting real motion and stereo parallax.

# 11. Objective experiments, numerical metrics and acceptance standards

## 11.1 Build an independent reference replay set

Use at least two cameras with known physical separation (6–8 cm as a **test fixture**, not an assertion of user IPD), accurate per-frame source and target matrices, both forward and reverse-Z, source crops, genuine unequal 860×684 and 344×276 input grids, nonzero depth subrect origins, randomized but recorded DLSS jitter, 2D/3D moving objects, thin poles/fences, a moving foreground hand, slanted plane and genuine target-only disocclusion. Render both high-resolution physical eye images *only as test ground truth*, while feeding the two asymmetric native inputs to all experimental warps.

Use the **same captured sequence** for CI71, CI72, CI73/CI74, CI76 and CI77, with every source input and shader hash recorded. Do not compare one user-played game session against another without identical frames. The diagnostic output must include output stereo RGB, raw/stabilized depth, valid surface region, depth-edge class, true target visibility, owner/native-fallback mask and per-pixel reprojection residual.

## 11.2 Metrics that actually measure stereo success

- **Geometry/disparity error:** median and p95 physical interocular disparity deviation at valid opaque surfaces, separately at foreground boundaries and in flat surfaces. Check vertical disparity too.
- **World-stationary edge jitter:** temporal edge displacement after subtracting the expected projection from known camera/object motion; report 95th-percentile in pixel units. This directly tests the user's main complaint.
- **Owner flip frequency:** fraction of pixels switching native/synthetic ownership without a real occlusion event; distinguish crop seam motion from genuine disocclusion.
- **False coverage and foreground leakage:** pixels assigned synthesized background where the nearest physically valid target surface is foreground, or vice versa.
- **Effective high-resolution synthesis coverage:** correct RIGHT-fovea reconstruction fraction; avoid rewarding a solution that shows low-res RIGHT native everywhere.
- **Temporal ghost duration:** how long depth/color from a disappearing surface remains after the object leaves; track history rejection by reason.
- **Pairing/frame integrity:** duplicate/stale features, unmatched render packet, resized allocations, jitter/sign mismatch, in-flight fence waits and frame-to-frame provenance.
- **Cost and pacing:** p50/p95/p99 GPU time in ms for each pass, CPU time, peak extra VRAM, frame skips, genuine game FPS and presentation conditions.
- **Headset comfort:** fixed-scene reproducible tests of near weapon/fingers, NPC outlines, railings, foliage, reflective and transparent materials, fast head turn, gaze tracking, save/load and resize.

A sensible acceptance strategy is **relative to a captured baseline**, not invented universal thresholds: CI77 should materially reduce world-aligned edge jitter *without* loss of stereo disparity, useful foveal coverage or unacceptable new ghost trails, and within a measured GPU budget. Record failures, not just averages. A clear stabilized depth preview is necessary but insufficient: the actual output must pass the same tests.

## 11.3 Minimum suggested in-headset A/B session

1. Preserve a verified Mono and CI76 rollback install. Record full exact versions, shader hashes, UEVR settings, STALKER 2 build/mods/Engine.ini and DLSS quality. Work with the user's usual PSVR2 120 Hz environment.
2. Confirm genuinely fresh, explicitly pinned LEFT/RIGHT NGX depth sources and effective stereo mode 5; record mode/strategy. Do not infer an active strategy from an unchecked label.
3. Record a **stationary** edge capture with stabilization OFF; then ON/temporal OFF; then ON/temporal ON, keeping same scene, selected features and camera position. Capture raw and processed depth for each run.
4. Repeat slowly strafing around the same edge and then around a close hand/NPC, followed by moderate gaze motion. Examine moving-edge lag/ghosting and eye-difference maps.
5. Toggle reconstructed/native owner visualization and compare to CI76. Confirm the doubled-hand region is no longer blended but that fine LEFT geometry still survives.
6. Change peripheral scale, await the 250 ms debounce and eight-fresh-pair recovery; verify fallback is current RIGHT mono and stereo automatically returns only after valid sources, without stale/released depth.
7. Run save/load, DLSS mode change, resolution scale change, ten mode toggles and gaze reacquisition; check crashes, missing shading, FOV, disabled controls, head movement and pin invalidation.
8. Time each GPU stage and capture meaningful p95 frame times on RTX 5070, not in WARP. Compare equal scenes/quality against stable Mono, native stereo and CI76.

If frames cannot be authenticated to their real producing camera, mark the run **diagnostic only** and do not assert reconstruction quality numbers as authoritative.

# 12. Practical state as of 30 October 2026

| Subsystem | Current level | Remaining issue or caveat |
| --- | --- | --- |
| Stable DuoView Mono | **User-validated baseline** (v182; newer v186.1/v186.2 release track) | Mono lacks binocular stereo. Keep independent release/rollback. |
| Eye-tracked crop and high-res fovea | **Works in known-good Mono** | Must remain aligned with per-eye physical camera and independently valid history in stereo. |
| Native four-view stereo | **Seen in headset, not satisfactory** | CPU load, shading/history asymmetry, FOV/black/startup and mode transitions. |
| Physical LEFT + RIGHT source views | **Physical disparity observed** | Exact per-frame camera/depth provenance not fully verified. |
| NGX depth acquisition | **Operational with manual pinning** | Format/rect/jitter/feature changes and incorrect automatic selection still matter. |
| Synthetic fovea + periphery | **Visible genuine 3D** | Headset edge jitter, missing geometry, close hand artifacts and fallback behavior. |
| CI74 phase/mask correction | **Reproduced and fixed in fixture** | Need real game-camera convention verification. |
| CI75 lossless recorder | **Implemented and used for capture** | ROI capture not full-scene truth; omitted/missing planes and 20-MiB parts must be checked. |
| CI76 exclusive ownership and recovery | **Fixture validated** | May remove one double-image cause; does not guarantee stable target geometry. |
| CI77 spatial + temporal depth stabilization | **Implemented; GPU tested; headset UNVERIFIED** | Must test dynamic surfaces, true camera/frame pairing, ghost trails, user-visible processed depth and GPU overhead. |
| Zero-jitter, native-quality synthetic stereo | **Not achieved/verified** | Must not be described as solved or production-ready. |

**Latest experimental branch recognized:** [`experiment/ci77-stabilized-depth-left-geometry-20261030`](https://github.com/liviutrn/UEVR-Quad-Views-Mono/tree/experiment/ci77-stabilized-depth-left-geometry-20261030). The branch is **17 commits ahead** of the CI73 baseline in the repository comparison examined for this report. CI77 README calls itself an experimental successor to CI76 Build106. The public Mono release tracked in the prior handoff is [`v186.2`](https://github.com/liviutrn/UEVR-Quad-Views-Mono/releases/tag/v186.2) / Build206. This report does **not** infer the exact downloadable CI77 binary/run number or a green headset result from the existence of its branch.

# 13. Recommended next engineering priorities

**Priority 0 — preserve proven behavior and identify what is running.** Freeze the exact stable Mono build and current CI76/CI77 binaries, settings and source hashes. Separate Mono, native Quad, CI71/72/73, CI76 and CI77 strategies in the UI. Show **effective strategy**, source identities, stabilization actually executed and mono fallback status, rather than a forest of toggles whose precedence is obscure.

**Priority 1 — prove depth is stabilized on real captured frames.** Use CI77's raw/processed depth preview and capture. Quantify edge motion under static scene and separate jitter phase correction from camera-history correction. Do not continue onto final RGB unless the processed depth is demonstrably better and lacks old-foreground trails. The user's priority is the geometry map, not cosmetic blur.

**Priority 2 — prove high-resolution LEFT geometry actually drives RIGHT fovea.** Trace the production shader inputs and inspect owner/visibility/coverage masks at the user's doubled-hand edge. Coarse RIGHT depth must be limited to checking visibility and cannot override a coherent fine LEFT surface merely due to two conflicting low-res samples. Retain physically separate cameras and a correct binocular baseline.

**Priority 3 — authenticated source/frame association.** Add immutable UE view-family eye/pass/crop and DLSS Evaluate IDs, with no pairing across unsuitable output generations, frame packets or queue retirements. If the exact provenance cannot be established, diagnostic output should say **UNVERIFIED**, not imply normal stereo. This is foundational to trustworthy temporal history.

**Priority 4 — objective replay and architecture comparison.** Replay identical real and synthetic sources through CI71, CI72, CI76 and CI77, inspecting world-aligned jitter, edge disparity, coverage and ghosting. A further refactor may be justified, but only if it wins these measurements. Investigate a surface-layer/priority representation or a low-cost extra native source only if CI77's two-view ceiling is demonstrably inadequate.

**Priority 5 — full headset acceptance and performance.** On STALKER 2/PSVR2, exercise real movement, moving actors, HUD/weapon, DLSS, resize, save/load and performance at the intended 30/40 FPS with SteamVR motion smoothing. No stable release promotion before meeting the quality gate.

The ideal future pipeline is **provable input identity → spatially phase-correct depth → valid motion-aware depth/owner history → high-res LEFT authoritative geometry → conservative RIGHT visibility → single-owner native/synthetic output → independently measurable per-eye stereo → headset acceptance**. Merely stacking stronger blur, larger thresholds or more native fallback could reduce visible shimmer while destroying the point of the project: correct, useful stereoscopy.

# 14. Reproducible handoff for the next engineer or model

To continue safely, start with the repository and exact CI77 branch. Read the linked CI73 handoff and branch README history, then inspect the **assembled production source after ordered patches**, not just frozen `ci51/production` originals. Record a per-run manifest: commit SHA, branch, Actions run/artifact SHA, actual loaded DLL hash, game version/Engine.ini/mods, UEVR/PSVR2 Toolkit/SteamVR settings, effective true-stereo mode, manual NGX source pins, source dimensions, active color/depth roles, strategy, stabilization/temporal weights, crop, resolution and headset feedback. Build/CI traces, a screenshot of each menu and a full `CI75` recorder ZIP index + all numbered parts are the core evidence package.

**Do not assume**: a green build ran on PSVR2; a good-looking NGX depth image is synchronized to the eye; the game's DLSS jitter can be turned off safely; source and target depth are identical grids; 0.499 RIGHT periphery guarantees high-resolution geometry; a low flicker score means correct depth; a frozen map is stabilized; native RIGHT fallback is equivalent to reconstructed stereo; or the unstable 2-camera experimental path is the public Mono release.

**Minimal questions for the new engineer to answer with evidence:** Which exact two NGX Evaluate operations produce the two physical source images in the same render transaction? Is jitter phase correctly decoded at the actual input subrect and pixel-center? Which surfaces cause invalid historical depth retention? Is the CI77 processed guide literally the guide sampled by the production warp and displayed in preview? What proportion of the RIGHT fovea is correct high-res LEFT geometry versus low-res fallback? Are the remaining doubled hands present *before* composition, or introduced by ownership blending? How many microseconds/ms and MiB are added on RTX 5070? How does the answer differ for near weapon, distant edge, moving NPC and gaze motion?

# 15. Glossary and distinctions

| Term | Meaning in this project |
| --- | --- |
| UEVR | Unreal Engine VR injector; upstream baseline from praydog and Joey forks. |
| DuoView Mono / ID6 | Dedicated foveal+peripheral pipeline, initially shared-eye camera and identical final output. |
| Native Stereo Fix | Joey-derived mechanism for obtaining correct independent Unreal views; important for view roles and temporal shading. |
| Quad Views | Four actual view renders (LEFT fovea/periphery and RIGHT fovea/periphery), not synonymous with DuoView Mono. |
| DIBR / DIBV | Depth-guided view reconstruction; requires valid source depth and camera transforms. |
| NGX / DLSS SR | NVIDIA upscaling execution interface providing real render color/depth/MV/jitter inputs to the game's upscale. |
| Guide / pin | Intercepted depth/camera-related resource and manually selected source role, with generation and active rectangle. |
| ROI / active subrect | The portion of an allocation containing meaningful input texture pixels. |
| Jitter / phase | Subpixel sampling displacement used by temporal upscaling; must be separated from world motion. |
| Reversed Z | Depth mapping with farther geometry near one end of depth encoding; requires correct projection/range conversion. |
| Forward warp | Project known source pixels into the target eye, with holes/occlusion treatment. |
| Inverse gather | For each target pixel estimate which source point supplies its visible color. |
| Owner/coverage | Whether a pixel is sourced natively or synthetically; coverage alone is not correctness. |
| Temporal reprojection | Use camera/geometry transforms to bring valid prior depth to a current surface, with strict rejection. |
| WARP | Windows software rasterizer used for deterministic GPU-function tests, not RTX5070 performance validation. |
| CI71/72/73/74/75/76/77 | Experimental feature-level build progression, not GitHub Actions run numbers. |
| v182, v186.1, v186.2 | Public and stable Mono release lineage, separate from experimental synthetic-stereo builds. |

# 16. Sources, provenance and reading order

## Internal project evidence (primary)

- **[P1] Main repository and public README:** [UEVR-Quad-Views-Mono](https://github.com/liviutrn/UEVR-Quad-Views-Mono), especially `README.md`, `PROVENANCE.json`, `duoview/` and workflow files. Baseline v182 source/release details and caveated performance numbers.
- **[P2] CI73 baseline and engineering handoff:** Local archived document `DuoView_CI73_Engineering_Handoff_2026-10-30.md` (30 October 2026), based on source review and prior headset reports; [CI73 branch](https://github.com/liviutrn/UEVR-Quad-Views-Mono/tree/experiment/ci73-conservative-stereo-quality-20261030), [successful workflow run #94](https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/40979111325). This earlier report is not an independent headset validation.
- **[P3] CI74 precise jitter fix:** [README and tests](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/experiment/ci77-stabilized-depth-left-geometry-20261030/ci74/README.md); [workflow run 41036935417](https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/41036935417).
- **[P4] CI75 diagnostic recorder:** [CI75 README](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/experiment/ci77-stabilized-depth-left-geometry-20261030/ci75/README.md), `DuoViewDiagnosticRecorder.hpp`, `analyze_capture.py` and test files. Actual recorded results are capture-specific.
- **[P5] Research report critique:** [Research review dated 30 October](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/experiment/ci77-stabilized-depth-left-geometry-20261030/research/2026-10-30-reconstruction-report-review.md). It expressly calls proposed HSVR-L2 architecture untested and notes absent bibliography in the exported report.
- **[P6] CI76 mixed-owner and resize fix:** [CI76 README](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/experiment/ci77-stabilized-depth-left-geometry-20261030/ci76/README.md), `owner_gpu_tests.cpp`, `NgxPairRecovery.hpp`.
- **[P7] CI77 stabilization and LEFT geometry:** [CI77 README](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/experiment/ci77-stabilized-depth-left-geometry-20261030/ci77/README.md), [`DuoViewDepthStabilization.hlsl`](https://github.com/liviutrn/UEVR-Quad-Views-Mono/blob/experiment/ci77-stabilized-depth-left-geometry-20261030/ci77/DuoViewDepthStabilization.hlsl), `DuoViewDepthStabilization.hpp`, `depth_gpu_tests.cpp`, `patches.json`.
- **[P8] Prior testing conversations / user reports:** contemporaneous feedback from 12–30 October 2026 and two-source capture analyses. These observations are user-reported and do not replace code inspection or independent measurement. The report cannot guarantee every older message, artifact and branch was independently revisited.

## External research and documentation

- **[E1]** Jonathan Shade, Steven J. Gortler, Li-wei He and Richard Szeliski, **“Layered Depth Images”**, SIGGRAPH 1998. [Harvard archival publication](https://dash.harvard.edu/entities/publication/73120378-7e84-6bd4-e053-0100007fdf3b); [Microsoft Research entry](https://www.microsoft.com/en-us/research/publication/layered-depth-images/). Foundational view warping, multi-layer visibility and occlusion concepts.
- **[E2]** NVIDIA, **DLSS Programming Guide**, edition dated 31 March 2026, especially depth input and motion vectors (jittered motion flag, motion scale/direction and thin-feature issues). [Official guide PDF](https://raw.githubusercontent.com/NVIDIA/DLSS/main/doc/DLSS_Programming_Guide_Release.pdf). Also see [Streamline DLSS Frame Generation programming guide](https://github.com/NVIDIA-RTX/Streamline/blob/main/docs/ProgrammingGuideDLSS_G.md) for depth/MV/HUD guide semantics; FG is *not* equivalent to stereo synthesis.
- **[E3]** Epic Games, **Unreal Engine Rendering Settings**, VR fixed foveation, VRS and Instanced Stereo. [Official documentation](https://dev.epicgames.com/documentation/unreal-engine/rendering-settings-in-the-unreal-engine-project-settings). Transferability to UEVR must be tested, not assumed.
- **[E4]** [Praydog UEVR](https://github.com/praydog/UEVR), [Joey UEVR](https://github.com/joeyhodge/UEVR), [PSVR2 Toolkit](https://github.com/BnuuySolutions/PSVR2Toolkit). Upstream ecosystem and integration provenance.

## Closing verdict

**We have demonstrated why the project is worth pursuing and proved several crucial pieces:** stable high-efficiency monoscopic DuoView; real physical independent-view rendering; real stereo visible with manually selected DLSS depths; reproducible depth sampling and RGB ownership bugs; a useful lossless capture system; and an implemented CI77 depth-stabilization/LEFT-geometry path. **We have not yet proved that synthetic stereo is sufficiently correct and temporally stable in STALKER 2 on PSVR2, nor that its cost/quality beats an optimized native-stereo alternative.** The next decisive result must be a measured, captured and headset-validated reduction of edge wandering and ghosting with correct binocular disparity—not another list of successfully compiled features.

# TriView B2 — adversarial correctness and efficiency review

**Review date:** 2026-10-31. **Target:** claude/triview-b2-20261031 at c9733fd9a2ebf85772f4ac4a037d0fd1d062f2ed. **Baseline:** Build 51 at f4e086cde6d4a183cf2c1223dd9effaf6f8f7a77. **Change scope:** this report only; no implementation or test changes.

## Evidence convention

- **[source-read]** Direct inspection of the specified repository source, its exact comparison, and the pinned Joey UEVR source. This can prove source control flow and algebra, but does not establish that the generated binary executed correctly.
- **[CI-verified]** A completed and successful GitHub Actions job. Do not conflate portable sanitizers with a production Windows build, or any CI result with an HMD validation.
- **[headset-verified]** Liviu's explicitly supplied headset/game measurements and observations, not independently reproduced by this reviewer.
- **[estimated]** Reasoned prognosis, proposed experiment, performance model, or unverified dynamic failure mode. No such item is a measured result.

Each substantive finding below carries one or more of these labels. **Review verdict: BLOCK B2 headset acceptance until the left-fovea projection inheritance defect is fixed and tested.** [source-read] Other paths look coherent but have untested dynamic failure states. [estimated]

## Sources and reviewed file inventory

[source-read] GitHub comparison https://github.com/liviutrn/UEVR-Quad-Views-Mono/compare/f4e086c...c9733fd enumerates **exactly nine paths**, three commits ahead of Build 51:

| Changed file | Delta | Reason and audit status |
| --- | ---: | --- |
| .github/workflows/triview-b1.yml | +326, added | Integration sequence, test/packaging provenance; read |
| quadview/NativeDeliveryTests.cpp | +19 | Tri-mask portable test; read |
| quadview/QuadViewComposite.hlsl | +16/-3 | H matrix and context-source shader; read |
| quadview/QuadViewD3D12.hpp | +18/-7 | 256-byte CB, alias and transitions; read |
| quadview/QuadViewFamilyRouting.hpp | +4/-1 | Dispatch skip mask; read |
| quadview/QuadViewGeometry.hpp | +101 | Centre union, handedness and homographies; read |
| quadview/QuadViewNativeDelivery.hpp | +11/-5 | Required-role completion and provenance; read |
| quadview/QuadViewShaderWarpTest.cpp | +4/-1 | CB format update, not an H test; read |
| quadview/apply_quadview_triview.py | +109, added | Generated backend modifications; read |

[source-read] The Build 51-dependent paths examined alongside those changes include quadview/apply_quadviews.py, apply_quadview_native_delivery.py, apply_quadview_role_frames.py, apply_quadview_recovery.py, apply_quadview_native_retirement.py, apply_quadview_target_lifetime.py, QuadViewProducer.hpp, QuadViewDelivery.hpp, QuadViewFramePacket.hpp, QuadViewSettings.hpp, QuadViewNativeTargets.hpp, QuadViewRetirement.hpp, QuadViewViewDemand.hpp, QuadViewTests.cpp, QuadViewShaderWarpTest.cpp, NativeDeliveryTests.cpp, CMakeLists.txt, and BUILD51_FINDINGS_STATUS.md. All are at the target commit. Those unchanged files matter because the new patch is applied *after* the other overlays rather than being a checked-in generated FFakeStereoRenderingHook.cpp. [source-read]

[source-read] Real upstream pin: joeyhodge/UEVR at 5ac7edc207866569334175e4ed8a7517971547f6, specifically src/mods/vr/FFakeStereoRenderingHook.cpp (large blob 42858980...), src/mods/vr/runtimes/OpenXR.cpp, and src/mods/VR.cpp and VR.hpp. Restricted UESDK at 3cffbc8 was not available for an independent compiled runtime inspection. We inspected exact text substitutions plus their matching upstream anchors; **this is not equivalent to inspecting a CI-produced full generated source tree**. [source-read]

## Executive issues, ordered by severity

1. **BLOCKER / left-fovea projection corruption:** quadview/apply_quadview_triview.py modifies **view 0** into the union projection. Build 51's quadview/apply_quadviews.py hooks construct **focus view 2** from quadview_producer().projection_matrix(key, 0), which is exactly the *already rewritten* view-0 projection. The focus crop is then applied to that union rather than the original LEFT full-eye frustum. View 3 inherits right context view 1, which was not rewritten. The result is asymmetric incorrect left-focus camera/projection pairing and an incorrectly mapped focus/context seam. There is no separate pre-union left-eye projection preserved for view 2 on this path. **Reproduce by tracing projection_call(0), projection_matrix(key,0), apply_focus_crop for index 2.** [source-read] A visible left-focus scale/seam defect is the predicted symptom, **not** headset-verified. [estimated]
2. **No B2 HMD validation and missing critical H tests:** the NativeDelivery tri test uses non-explicit role frames; the shader test updates only the constant structure, and never asserts the new rotated-eye homography/source-1 alias pixel result. A green portable job cannot catch (1) or a camera-space mismatch. [source-read]
3. **Toggle-OFF is a source-level semantic fallback, not binary-identity proof.** Skip mask 0, required mask 0x0f, shared_context false and identity H preserve expected four-view geometry, but HLSL always executes new projection code, the CB size is 256 rather than 144, and the new binary/CI workflow is not Build 51. [source-read]
4. **OpenXR frame coherence and dynamic transitions remain unproved.** Geometry uses a frozen stage-space eye-pose pair, while Joey's eye transform reads runtime eyes (view-space) at the camera hook. The relative rotations agree algebraically if captured for the same frame, but there is no new B2 assertion tying their identities per draw. [source-read] A race or a mode toggle within an in-flight quartet could manifest as a missing/different producer, even if the immutable layout avoids cross-contaminating a correctly bound packet. [estimated]
5. **Packaging misidentifies experimental B2 as Build 51 / TriView B1.** The new workflow packages QUADVIEW_BUILD.json with build='51', writes BUILD51_BINARY_IDENTITY.json, uses TriView-B1 names and inherited READ_FIRST prose, and does not describe the Tri-view toggle. This is a concrete traceability failure for HMD feedback and crash diagnosis. [source-read]

## Part 1 — correctness and regression

### A. Toggle OFF, four-view equivalence audit

[source-read] Overlay application order in the Tri-view workflow: pinned Joey backend and frontend → DuoView stages 1–4 → apply_quadviews → consumer → native delivery → native retirement → recovery → role frames → hook trace → output trace → presentation setup → target lifetime → **apply_quadview_triview.py last** → embedded shader → CI tests → production compilation. Thus B2 only adds the nine above changes to the Build 51 quadview overlay.

[source-read] The exact OFF branches are:
- The new ModToggle is a separate UI state; OFF prevents apply_shared_context, leaving the Layout from make_layout with **shared_context=false**, four distinct rectangles, and **identity** context_h matrices. The default is ON, unlike Build 51's absence of the toggle.
- GetDesiredNumberOfViews is **not changed by B2**, retains the Build 51 four-view demand and quadview_begin_frame startup logic. The four constructors, four projected view IDs, four distinct FSceneViewState histories and complete 0x0f producer masks remain required. See apply_quadviews.py and QuadViewProducer.hpp.
- The view-rect hook is **unchanged**: view indices 0,1,2,3 get the same make_layout rectangle for OFF. The centre-camera conditional requires layout.shared_context and therefore does not translate view 0. Existing focus views copy the two frozen eye cameras.
- The union-projection overwrite is conditioned on view_index==0 and shared_context; OFF leaves the Build 51 projection matrix. Existing focus crop stays unmodified.
- dispatch_main_views(...,skip_mask=0) follows the old loop exactly: before(0–3), first batch at slot 0 and singleton for 1,2,3; ScopedMainFamilyMutation restores the family/target/array.
- Both native bind sites use **required_roles=0x0f**, the default. The new equality checks are 0x0f in OFF, and content_matches iterates all four target stamps. Thus the former 0x0f completion contract is retained.
- The compositor sets ContextSource = (0,1) and ContextH = identity; per-eye context rectangles are their original views[0] and views[1]; source 1 is **not** aliased and barriers still cover four distinct sources; foveal sources 2 and 3 stay independent.
- Recovery, native target leases, fences, and presentation setup scripts are unchanged relative to Build 51. Repeated old diagnostic text sometimes still says quartet even in tri mode.

[source-read] **The differences even with OFF:** new saved toggle + default ON; larger 256-byte constant upload and changed HLSL cbuffer; shader now evaluates a 3×3 identity matrix and divides by 1, with compiler-dependent numerical/code-generation equivalence rather than literal source identity; optional skip_mask and required_roles arguments extend APIs; workflow/package and compile artefacts differ. Consequently the claim “line-by-line identical to Build 51” is false at binary or shader-instruction level. The defensible claim is **expected functional four-view equivalence when OFF**, conditional on compilation and runtime. [estimated]

**Missing OFF regression:** compare Build 51 vs B2 with toggle OFF at fixed camera and gaze: same per-source 4-frame IDs, 0x0f render/hook/executed/stamped masks, identical eye colour/brightness within 8-bit tolerance, four independent per-eye histories, and same scene-shading behaviour. [estimated]

### B. Toggle ON: trace one nominal full frame

| Stage | B2 behaviour | Closure conditions and risk |
| --- | --- | --- |
| Admission | Build 51 GetDesiredNumberOfViews returns **4**; quadview_begin_frame takes key=(generation,draw_serial), frozen OpenXR pose and source config. | [source-read] Tri-view deliberately does **not** request 3 UE constructors. Wrong runtime, title, missing hooks, incompatible emulation modes cause admission failure. |
| Layout/pose | make_layout builds 4 rects; if toggle ON, !stereo emulation, valid per-eye projections and 2 stage_views, apply_shared_context computes union and sets shared_context. freeze pins it for the draw. | [source-read] Failure leaves all 4 rendered. A previously frozen layout cannot be retroactively changed by a toggle inside the same draw. |
| Camera offset | For view0, compute regular *left-optical* eye_separation. Existing Build51 freezes left context camera for focus2, then B2 adds eye_separation−head_midpoint_separation to view0, putting context translation at head midpoint; its rotation remains LEFT optical. View1 keeps RIGHT. Views2 and 3 copy left/right frozen cameras. | [source-read] Correct position sign in the existing subtraction convention; requires actual matching eye/head pose data and double precision. |
| Projection | View0 writes context_projection into m[0][0],m[2][0],m[1][1],m[2][1], preserving other rows. View1 maintains right full-eye projection. Focus views apply crops to captured context projection. | **[source-read] BLOCKER:** focus2 gets overwritten view0 union, not left original. Expected masks may still pass because constructor and producer see the same *incorrect* matrix. |
| Scene constructor | All four FSceneView constructors run; each forces PRIMARY and temporarily zeros family view count, captures distinct FSceneViewState pointers and projection hash/rect. Producer requires all 4 constructors, matrices and both context cameras before snapshot.main_family passes. | [source-read] One constructor failure rejects producer; no 3-history shortcut. Four histories exist even though view1 is not submitted as a render. |
| Source dispatch | The original main-family batch renders slot0. dispatch_main_views's skip_mask=0x02 omits before/select/singleton for slot1; slots2 and3 render as independent singleton families with their target. Scoped mutation restores the original 4-view family. | [source-read] Actual UE work: 3 independent render families, not 3 FSceneViews in one family. Slot1 original target still exists but remains unwritten for this draw. |
| GT role frames | Native build registers the immutable source and four distinct native source targets, with required_roles=0x0d and explicit_role_frames=true. GT BeginRenderViewFamily binds each executed singleton's *actual* frame number, target and scene. | [source-read] Role1 has no GT binding by design. Role2/3 frame numbers need not equal role0; exact observed values are required. Missing GT binding stalls that role's native render matching. |
| RT owner | NativeDelivery.render matches (generation, per-role GT frame, target, scene); first role claims the canonical engine family and exact source from Delivery, subsequent roles add ownership. | [source-read] A wrong frame/target, duplicate role, previous generation, or source-owner mismatch prevents publication. |
| RHI attach | For each actual singleton, hook_batch associates the exact owner and target-set with an authenticated RHI command tail; shared tails retain a TailOwnerBatch, with ambiguous drain/list ownership quarantined. Role3 (not skipped) alone claims runtime advancement. | [source-read] Missing hook/invalid drain scope/overflow/quarantine can block selection; role1's absence is not itself a wait once required_roles is 0x0d. |
| RHI execute | Actual callback executes attached tails; record_write stamps physical targets for 0,2,3, clearing conflicting old content; latch_completion requires hooked==0x0d, executed_tail completes if executed==0x0d. | [source-read] content_matches checks *only required* targets but retains full owner/source frame/serial/target-set/view IDs. This is the correct conceptual producer proof for the 3 rendered inputs. |
| Source publication | finish_quartet calls Delivery.executed_engine_family with source if coherent and empty source if poisoned; ordinary Delivery.select peeks latest *already executed* source on same submission thread. Submitted only after accepted XR copy. | [source-read] Later incomplete frames do not block selection of an older already completed packet. A visible stale pose while newest frame incomplete is possible; this is policy inherited from Build 51, not a proven cross-layout corruption. [estimated] |
| D3D12 composite | Native packet owns four native_resources and owner leases. Compositor validates original sources, aliases active[1]=source[0] for shared_context, sets rectangle[1]=rectangle[0], context_source=(0,0), copies two H matrices, barriers each unique active resource and destination, draws, restores transitions. | [source-read] Unwritten source1 is **not sampled or transitioned**. Source1 is still required to exist and have matching extent/format; that contract can reject a packet if target1 is invalid, even though it was not rendered. |
| Shader/result | HLSL maps per-eye UV into shared union context with the corresponding 3×3 homography; left and right foveae sample source2,source3. Focus feather blends reconstructed context from source0. | [source-read] Homography is exact for same-direction rays at infinity, **not correct parallax for finite nearby geometry** because periphery camera is head-centred and left optical, whereas both runtime eyes have different translations. Expect peripheral seams/disocclusions and head-motion swim. [estimated] |
| Retirement | CPU packet leases and GPU command-slot fences retain targets until genuine retirement; a mode generation transition requires full engine retirement; presentation reset is scoped to presentation fences. | [source-read] Failing tails cannot simply be reset without proven CPU execution and GPU fence retirement. No new tri-specific watchdog/abort or stale-layout test was added. |

**Summary of waits:** [source-read] The old *always wait for role 1* checks in NativeDelivery (hooked/executed/content) were changed to per-slot required=0x0d; role3 remains cadence driver. Other 4-bit requirements are **intentional constructor/history checks before rendering** and 4-resource allocation/validation **after rendering**, not role-1 render waits. Any additional legacy atlas route still uses Build51's four-view assumptions and must not claim a coherent tri packet without NativeDelivery's executed physical stamps. [source-read]

**Residual failure conditions to instrument:** [estimated] (a) a late unexpected role1 hook changes exact-equality mask from 0x0d to 0x0f; (b) role2 or3 GT role-frame binding fails; (c) a tail is attached but never actually executes; (d) older completed content is selected during a new-layout transition; (e) a source1 texture becomes invalid although source1 is unsampled; (f) stage pose corresponds to one frame and runtime transform to another.

### C. Geometry, signs and **real UEVR source** verification

[source-read] Pinned Joey OpenXR.cpp at lines ~1540–1555 calls xrLocateViews twice: first with view_space into **views**, then with stage_space into **stage_views**. At ~1995–2000 it assigns the runtime eyes matrices from **views[0/1].pose.orientation** and positions. Pinned VR.cpp ~17266–17276 returns these via get_eye_transform; ~17234–17247 returns positions via get_eye_offset. VR.cpp ~17187–17193 gets stage HMD rotation from current view_space_location.

[source-read] Crucial original hook source: FFakeStereoRenderingHook.cpp ~30249–30253 computes:
~~~cpp
current_hmd_rotation = normalize(rotation_offset * quat(get_rotation(0)));
current_eye_rotation_offset = normalize(quat(get_eye_transform(true_index)));
new_rotation = normalize(vqi_norm * current_hmd_rotation * current_eye_rotation_offset);
~~~
The **relative** stage-eye rotation qLeft^-1*qRight cancels a common head rotation and corresponds to the two optical rotations used in new_rotation **when both are from the same pose sample**. B2 rel = Rleft^T*Rright is therefore conceptually right. Its quaternion-derived matrix maps a local direction to stage space; the right-to-left relative matrix is a *rotation*, not its inverse. [source-read] A dynamic source mismatch remains: stage_views comes from a quadview capture and get_eye_transform reads runtime eyes, which can change if the frame/sample boundary is not held; B2 has no explicit paired-rotation numerical assertion. [source-read]

[source-read] Joey hook ~30267–30270 calculates nonmono eye_separation via optically rotated **new_rotation**, and hook ~30293–30299 subtracts it from position. B2 first freezes that LEFT optical pose for focus2 then adds eye_separation−center_separation, where center_separation uses vqi_norm*current_hmd_rotation and average of the head-relative eye offsets. Therefore the final view0 position is original_position−head_offset−center_separation, with no second optical cant rotation of head-centre displacement. This sign and operation order are correct **under the pinned hook's convention**. [source-read]

[source-read] Joey OpenXR.cpp ~2086–2105 builds a projection with x scale 2/(right-left), x offset −(right+left)/(right-left), y counterparts and p[11]=1 for clip-w=z. Thus B2's a=p[0 or5]/p[11], b=p[8 or9]/p[11], x ndc=2u−1 and y ndc=1−2v match column-major +Z-forward UE projection. Stage directions are OpenXR −Z forward, converted with S=diag(1,1,−1): R_UE = S(R_left^T R_right)S. The two (i==2)!=(j==2) sign flips implement exactly that change, including the u/v orientation, and HLSL dot(row.xyz, uv1) respects padded-row layout. [source-read]

**Numerical example** [estimated; independently computed from reviewed formulas]:
- Left stage optical rotation identity; right stage optical quaternion yaw +5° about OpenXR +Y; both unmodified full-eye projections have a_x=a_y=w=1, b_x=b_y=0 and tangent bounds [−1,1] on x/y.
- Converted right→left direction R has entries R00=0.9961947, R02=−0.0871557, R20=+0.0871557, R22=0.9961947. Right frustum transformed corners produce x tangent range [−1.1917536, +0.8390996], y range [−1.1000629,+1.1000629]. The union with the left frustum is x [−1.1917536,1], y [−1.1000629,+1.1000629].
- Union projection: ca_x=0.91251134, cb_x=+0.08748866, ca_y=0.90903896, cb_y≈0. Left H rows (un-padded): [0.91251134,0,0.08748866], [0,0.90903896,0.04548052], [0,0,1].
- Right H rows: [1.00381984,0,0], [0.08715574,0.90903896,0], [0.17431149,0,0.90903896].
- Input eyeUV=(0.5,0.5) maps to left context UV≈(0.54374433,0.5), right context UV≈(0.50382713,0.5). **The right mapping is projective and cannot generally be implemented by a 2D affine scale/offset.** [estimated]

**Important limitations:** [source-read] The function checks unit quaternion norm only within 0.01, not exact normalization; accepted nonunit quaternions slightly perturb the rotation. It checks finite double H before casting to float but does not assert final float H finite or an H denominator lower bound at all in-crop pixels. Shader uses h.xy/max(h.z,1e-4); this protects division but makes near-degenerate projection nongeometric instead of rejecting it. [estimated] Test extreme cant, projection offsets, changed OpenXR projection overrides, and both aspect ratios. Homography does not model translational depth parallax. [source-read]

### D. Runtime toggle, generations and loading screens

[source-read] The UI reads the live toggle **when creating a candidate layout**, then freezes shared_context, H and context_projection in LayoutLatch keyed by (generation,draw_serial); later dispatch and both bind sites derive skip/required mask from the immutable producer snapshot, not from live toggle. Correctly bound packets own their producer snapshot and engine target lease. Consequently an OFF→ON or ON→OFF change **after freeze** should apply to the next candidate rather than cause the currently frozen packet to use a different required mask. [source-read]

[estimated] However, this is not an atomic end-to-end mode-transition contract: a game loading screen or re-entry while a prior draw has pending RHI tails can hold old and new layouts concurrently within the same generation. Delivery.select chooses the newest *completed* same-generation serial (not necessarily the newest attempted serial), so it can legitimately output an older layout and pose until the new one completes. Exact source tickets generally protect content ownership, but in-flight stale-display behaviour is untested. There is no new explicit per-mode toggle drain, request epoch, freshness bound or packet layout-ID assertion at XR publication. [source-read]

**Required trace** [estimated] record for each draw: generation, draw_serial, source producer key, layout.shared_context, expected mask, observed GT role frame numbers, 4 physical target generations, hooked/executed/written masks, packet selected serial and XR pose time, and actual compositor H/ContextSource. Test toggle ON→OFF→ON while *RHI tails are deliberately held or delayed*, then level load, engine source recreation, and a 60-second idle view.

### E. Recovery, retirement, legacy and emulation

[source-read] apply_quadview_recovery.py preserves engine-only drains for bootstrap/legacy family routes and quarantines mixed legacy atlas writes; these cannot produce a physical three-target provenance proof. apply_quadview_native_retirement.py and Build51 target-lifetime script keep engine-owned UTextureTarget holders and GPU fence retirement, and their code is unchanged. NativeDelivery explicitly requires **four distinct target addresses** at bind, so simply not rendering target1 does **not** permit deleting the fourth source target/owner/format validation. In the compositor source1 is aliased only at SRV/barrier stage, after four-source validation. [source-read]

[source-read] B2 applies shared mode only while !is_stereo_emulation_enabled. The broader Build51 QuadView admission gate rejects Stereo Emulation outright, along with Extreme Compatibility, split-screen and 2D paths, so it is wrong to claim this is a successfully supported tri→four fallback in emulation. Without frozen stage views or valid projection, it falls back to all four views for that draw, and a status message is emitted. [source-read]

[estimated] Retire/recover edge cases needing actual tests: destroyed target1 despite never being rendered; old tri source packet left pending as new quad owners arrive; same physical target set reused after toggles; a queued role3 tail losing its runtime event; partial 0x0d hook/executed masks on level transition; legacy atlas rendering after unadmitted tri attempt; target rebuild before old GPU fences signal. Do not remove four-resource/legacy fallbacks until measured.

### F. Test coverage and CI boundary

[source-read] NativeDeliveryTests.cpp's new tri case binds with required=0x0d, **explicit_role_frames=false**, calls roles 0,2,3 in order and checks select success only after last executed role. It proves the portable mask mechanic in a simple distinct-tail execution, **not** GT per-role frame binding, out-of-order/wrong role callbacks, shared-tail quarantine, stale role1 physical stamps, or toggle concurrency.

[source-read] QuadViewShaderWarpTest.cpp only changes the constant-memory layout and static_assert(sizeof(Constants)==256). The shader WARP pixel scenarios use identity H and do not set ContextSource.y=0 or assert rotated 3×3 corner/centre mappings, source1 poison non-read, barriers after source alias, and left-focus full-eye alignment. CPU geometry tests are still the baseline four-view geometry tests rather than an end-to-end B2 rotated-optics test. The runtime union-vs-focus2 inheritance bug is **not** checked by the producer's internal hashes, which only check that the wrong matrices are consistently captured. [source-read]

**Prioritized tests** [estimated]:
1. A source-projection unit test: with union!=left projection, expect view0=union, view1=right original, view2=**left original cropped**, view3=right original cropped; assert full left and right optical alignment at crop edges. This should fail B2.
2. CPU math tests for qLeft≠qRight and all 8 transformed frustum corners, extreme asymmetric FOV, positive homogeneous denominator; numeric reference from section C.
3. GPU WARP pixel test with source0 patterned, source1 magenta poison, source2/3 distinct colour patterns, yaw±5°, H sampling at known pixels (including context only/blended), debug layer enabled and state transition assertions. Verify role1 never sampled or barrier transitioned, including restoration.
4. Native producer tests with explicit_role_frames=true: nonconsecutive GT frame counts per role0/2/3; distinct shared tails with authenticated drain scopes; role1 unexpected callback; missing role3; poison/overwritten target stamps; tri↔quad overlapping serials within one generation.
5. Mid-game toggle run with 20 rapid toggles, scene/level load and forced target recreation, full packet/physical target log plus fenced GPU completion, monitored for black frames and stale brightness.
6. Actual PSVR2 headset: horizontal/vertical left-focus seam alignment, hand at 0.3–1m, 2–5m props, tree/foliage, head yaw/roll, eye-gaze movement, canted-eye asymmetry and brightness/Lumen matching; compare B2-OFF vs exact Build51 on same settings. Record GPU/CPU, 1% lows and per-render-family GPU pass timing, not only mean FPS.

**CI status at review time:** [CI-verified] GitHub Actions run 41238221904, head c9733fd, portable-sanitizers job 124646391070 completed successfully (ASan/UBSan portable suite). The Windows quadview-stereo-output job 124646390727 was **in progress** when inspected; no successful production build or packaging verdict yet. [source-read] Workflow tests can detect compilation and basic ledger issues but do not simulate correct left-focus projection/real UE rendering histories in the headset. [estimated] Status should be rechecked before binary testing. The workflow's package metadata says Build51 and TriView B1 even though this is B2; fix provenance before distributing.

## Part 2 — strategy, family floor and efficiency

### A. Measured baselines and model

[headset-verified; Liviu-provided STALKER 2 RTX 5070, GPU-bound, 200×200 measurements, not independently reproduced]

| Mode | FPS | Frame time (ms) | Source of value |
| --- | ---: | ---: | --- |
| Mono | 68 | 14.71 | headset-verified/user-provided |
| Native Stereo | 58 | 17.24 | headset-verified/user-provided |
| Native Stereo Fix | 46 | 21.74 | headset-verified/user-provided |
| DuoView Mono | 45 | 22.22 | headset-verified/user-provided |
| Full Quad | 28 | 35.71 | headset-verified/user-provided |

[headset-verified; user-provided] Incremental GPU costs from controlled experiments are about **7ms per extra separate render family**, and **2.5ms per additional view inside the same family**. E1 moved both foveae into one family by relabeling the right eye PRIMARY but produced artefacts; keep both eye foveae genuinely independent PRIMARY for clean shading unless a later headset experiment disproves that requirement. The reported Lumen limit is two views per family; this review has not independently demonstrated the engine cap in restricted engine source. [estimated]

**Tri forecast** [estimated]: 35.71ms full quad − ~7ms for removing the unrendered right-context family ≈ 28.71ms → **34.8 FPS** in ideal same-settings conditions. Sensitivity 26.7–31.7ms ≈ 31.5–37.5 FPS allowing a few ms of non-ideal overhead or cost variance. Actual in-HMD result is unknown. Relative to DuoView Mono, estimated Tri spends ~6.5ms/frame more, yielding ~35 instead of 45fps; a significant sacrifice for real stereo only in the foveal patches.

### B. Is 3 families the strict minimum?

**No—not as a general architectural claim.** [estimated] It is the minimum for the **specific constraint that every one of the three renders be PRIMARY/isolated in its own family**. For clean stereo foveae, the two separate PRIMARY family owners are necessary based on E1 evidence, but the mono shared periphery is not necessarily forced into a **third** family.

**Untried 2-family topology** [estimated]:
- **Family A:** LEFT fovea as PRIMARY, mono shared periphery as SECONDARY (two separately posed views within one family).
- **Family B:** RIGHT fovea as PRIMARY (one view).
- Alternative: Family A=RIGHT fovea PRIMARY + mono periphery SECONDARY, Family B=LEFT fovea PRIMARY, if asymmetric camera/timing paths favour the other eye. Both primary foveae have separate FSceneViewFamily state and primary ownership; only the periphery is secondary.
- This respects the user-reported “at most two views” Lumen cap. It does **not** repeat E1's failure mode of making the right-eye fovea secondary (or merely relabeling it PRIMARY inside a family).
- Risk: UE's secondary-view rules could break *periphery* lighting, exposure, shadows, Lumen reuse, occlusion, or pose/geometry; shared-context seam can become ugly, and the family primary's render-target layout and projection requirements must be validated. No guarantee until GPU source captures and a headset comparison.

[estimated] If one family costs ~7ms and its extra view costs ~2.5ms, combining periphery with a foveal family saves about **4.5ms compared with Tri**, yielding ideal ~24.2ms or **41.3fps**, close to DuoView Mono's 45. This is a high-value, tightly scoped **research/prototype experiment**, not a performance result. If the secondary context lighting differs badly or invalidates a fovea's clean shading, reject it rather than patching broad per-family CVars.

**Other layouts** [estimated]: One family with both foveae is ruled out *practically* by E1 headset artefacts, not formally impossible; one family for all three views conflicts with the user-reported Lumen two-view cap and fovea-isolation requirement. Two families with shared periphery composited separately but no third render is possible only by reuse/synthesis from a fovea and is a different quality trade-off. Pure mono context + split-screen family tricks may improve throughput but remain untested for UE5.5 scene histories.

### C. Rank achievable levers (all savings estimates, not measurements)

| Rank | Lever | Expected incremental saving | Risk / constraint |
| --- | --- | --- | --- |
| 1 | Two-family topology, periphery SECONDARY next to one PRIMARY fovea | **~4.5ms vs Tri** (7−2.5), if valid | High technical, medium experiment cost; independent PRIMARY stereo foveae must remain intact |
| 2 | Per-family *safe* reduced show flags on separate periphery family | **~0.5–3ms**, scene dependent | Medium–high; lighting/tonemap discontinuity at feather; validate specific UE5.5 flags and screenshot |
| 3 | Half-rate shared periphery with depth/pose reprojection and owned texture/fences | **theoretical ~3–4ms average** at 7ms family cost; 0 on rendered frames, up to ~7 on skipped frames | Very high visual and lifecycle risk; 2-frame cadence spikes and stale occlusion, especially nearby hands |
| 4 | Engine-side fixed-cost elimination (per-family Nanite/VSM/Lumen/sky/fog work) | **~1–4ms if pass profiling identifies eligible duplicate passes** | High; engine patch and view-family ownership; not validated |
| 5 | Lower only periphery scale (already 0.20 at 200×200) | **~0–0.5ms** when fixed family overhead dominates | Low code risk, medium–high visual degradation, unlikely meaningful |
| 6 | Change DLSS mode/screen percentage per family | **unknown; possibly ~0–2ms but not a supported proven independent setting** | High; global plugin state, history/jitter/upscaling mismatch; avoid cross-family CVar flips |
| 7 | Compositor/texture alias micro-optimizations or moving fourth resource out | **likely sub-millisecond** | Medium; correctness/fences risk dominates; not a strategic FPS lever |

**What “safe show flags” actually means here** [source-read + estimated]: EngineShowFlags are family/view setup flags and can be varied in a separately constructed periphery FSceneViewFamily without temporarily changing *global* UE console variables. Plausible first experiments: MotionBlur OFF, DepthOfField OFF, LensFlares OFF, SSR OFF *if not needed for materially matching reflections*, possibly separate expensive translucency/decal/postprocess passes, and peripheral-only AO/volumetric fog toggles after inspecting GPU pass traces. These flags are *not universally safe*—SSR, AO, fog and translucency can create sharp fovea-context seams; postprocessing and exposure may be coupled across family or renderer. Do **not** casually turn off Lumen GI, shadows/VSM, Nanite, tone mapping, TAA/TSR/DLSS history, depth passes or global illumination and claim equivalent shading. Some pass costs are scene-wide and flags may be ignored in UE5.5. Source/measurement validation is required before putting a saving into a roadmap. [estimated]

**Half-rate caution** [estimated]: Inverting an odd-frame render into a stale physical target is not free; NativeDelivery's provenance requires the correct serial/ticket. A genuine half-rate path needs explicit persistent shared context with reprojection motion/depth, own frame-age bounds, and separate fence/target leases; otherwise it will either fail publication or display temporally wrong content. At a 120Hz HMD and ~35 rendered FPS, 17Hz periphery updates with simplistic reprojection could feel markedly worse than 28fps full quad.

**Resolution caution** [estimated]: A 0.20× 200-pixel context is only ~40 source pixels wide before enlargement (or ~30px at 0.15). At the measured fixed family cost, shrinking it further buys little but substantially worsens shimmering. The requirement that periphery be less dense than fovea is already satisfied.

### D. Strategic verdict and priority order

**[estimated] Do not treat B2 as a release or spend another long iteration tuning visual quality while its projection bug is unfixed.** Fix the source projection decoupling and produce a failing-then-passing test before trusting any visual complaint. After a clean source/CI run, do **one** controlled headset A/B with the precise same stationary scene, eye tracking and GPU timing: Build51 four, B2 tri ON, B2 OFF; capture GPU family cost and left-focus seam. Stop if B2 is not comfortably above ~33–35fps or produces new reprojection/shading artefacts. [estimated]

**[estimated] The strongest architectural opportunity is not finer TriView math: it is trying the *two-family fovea-primary + periphery-secondary* arrangement once.** Give that a hard go/no-go on foveal shading parity and periphery seam acceptability; no prolonged pursuit if the primary fovea is compromised. If it succeeds near ~40fps while retaining true-stereo foveae, continue; if it fails, **prioritize finalizing the already working DuoView Mono (45fps)** over spending substantial effort to stabilize TriView around ~35fps. A real stereo fovea is only worth the cost if it is visibly better and comfortable after sustained headset use. [estimated]

**[source-read]** B2 does make meaningful, technically coherent progress on mask/alias/rotated-frustum infrastructure. **[source-read]** It also contains one clear mathematical integration bug (left focus view 2 inheriting the union projection), significant test blind spots and incorrect build identity. **[CI-verified]** Only the portable sanitizer job had completed green at review time. **[headset-verified]** No B2 improvement has yet been demonstrated in a headset.

## Reviewer completion / evidence boundary

[source-read] This report is a code-source review, with direct cited source files/line regions and independently evaluated projection arithmetic. It deliberately makes **no implementation changes** and contains no claim that an HMD test was run. [CI-verified] Portable ASan/UBSan job green, Windows not yet concluded at initial check. [estimated] A second independent model review was not available through the connected tools; a separate mechanical pass cross-checked the projection inheritance against the producer buffer and shader constants, and the remaining dynamic risks are not represented as proven crashes.

**References:** exact compare https://github.com/liviutrn/UEVR-Quad-Views-Mono/compare/f4e086c...c9733fd ; CI https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/41238221904 ; upstream pinned hook https://github.com/joeyhodge/UEVR/blob/5ac7edc207866569334175e4ed8a7517971547f6/src/mods/vr/FFakeStereoRenderingHook.cpp ; upstream OpenXR https://github.com/joeyhodge/UEVR/blob/5ac7edc207866569334175e4ed8a7517971547f6/src/mods/vr/runtimes/OpenXR.cpp ; upstream VR.cpp https://github.com/joeyhodge/UEVR/blob/5ac7edc207866569334175e4ed8a7517971547f6/src/mods/VR.cpp .

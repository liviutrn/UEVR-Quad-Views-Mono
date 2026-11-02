# v207 optimization audit and distance sharpening work record

Base: `4020a4430301296948759bfa30e5eb0d469df550` (v207, build 211).
Working branch: `experiment/v208-depth-sharpen-optimization-20261102`.
Status: source audit + v208 range-only implementation. Distance mode is NOT
implemented by v208. No optimization speedup or VRAM saving is measured here.

## Active user configuration (clarified during this work)

**Liviu report, 2 Nov:** Cheeky is used ONLY for Neural Rendering (NR) on the
DuoView fovea. Cheeky's SR/foveated-SR processing is never used.
Treat this as the active configuration. The source discussion of Cheeky's
optional peripheral DLAA/SR below is background capability, NOT an explanation
of current performance. Do not propose disabling a feature he already disables.
The remaining audit priorities are: correct NR-only foveal source selection,
once-per-produced-frame NR invocation, NR resolution/working buffers and cache
retirement, and UEVR/Unreal source target and compositor allocation costs.
The game's original DLSS SR/depth path is distinct from Cheeky's disabled SR.
Runtime source identity/invocation counts still need evidence; intended foveal
selection is not itself proof that the current source mapping is correct.

## Evidence labels

- **source-read**: inspected source, not a measurement of the running game.
- **CI-verified**: record actual Windows run result separately below.
- **headset-verified**: only an explicit report by Liviu; v208 pending.
- **estimated**: calculations, expectations, and proposed work.

## User request

1. Audit rendering, FPS and VRAM, retaining the working mono image and features.
2. Extend fused foveal Glamarye strength from 0..2 to 0..5.
3. Add efficient distance-based foveal sharpening from the fovea's DLSS depth,
   configurable in-game. Example: strength 5 nearby, smoothly fading to 1 far away.
4. Verify whether the custom Cheeky build processes only the foveal source once.

## v208 implemented scope

**source-read:** New exact-anchor patch applies AFTER v207. Changes only the
strength slider maximum in `VR.hpp` and BOTH validation paths in the generated
`DuoViewConfig.hpp`. Default 1.0, persisted setting name, shader, limiter,
geometry, gaze, captures, OpenXR and other modes remain byte-identical to v207.
A shader maximum-change limiter still applies: strength 5 is not a promise
of 5x contrast. Strength is a gain in the existing nonlinear sharpening formula.
No new depth hooks, copies, allocations or GPU passes are introduced by v208.

Files:
- `duoview/joey_stage1/apply_v208_sharpen_range.py`
- `duoview/joey_stage1/test_v208_sharpen_range.py`
- `duoview/joey_stage1/SharpenRangeTests.cpp`
- pinned test registration and existing Windows workflow update.

**source-read/local verification:** Full patch stack replayed from fresh Joey
5ac7edc + frontend 60be4b0. A Linux fxc stub is used ONLY for anchor replay;
this is not a shader compile or GPU validation. Real fxc, private SDK, Windows
compile, WARP and original compatibility suites remain required in CI.
Source snapshot proves only the two expected generated source files changed.
Tests exercise 0,1,2,3,5; reject negative, >5, infinity, NaN; retain frame latch
immutability. Original CPU geometry/gaze/frame/config/state/delivery tests pass.

## Actual rendering and memory findings

**source-read:** ID6 still uses TWO separate Native Fix source renders with the
same mono camera. One is the cropped fovea, the other is full-FOV low-resolution
periphery. Frozen configuration, producer pose and packet ownership are preserved
through composition. This is not two rendered stereo eyes followed by throwing
one eye away. See `apply_stage234.py:525-638`, `DuoViewState.hpp:31-44,95-109`.

**headset-verified (earlier project brief):** Tiny-resolution tests showed roughly
7 ms GPU per separate family, even at 200x200. **estimated:** Therefore reducing
pixel counts alone cannot remove the fixed work of the second scene render.
A precise Lumen/shadow/Nanite cost breakdown has not been measured in this audit.

**source-read:** Fused Glamarye runs only where fovea contributes in normal
composite view. One W x H mono composite is sharpened, then copied to both eyes.
Enabling it bypasses direct double-wide raster to avoid doing the same expensive
foveal work twice. See `DuoViewNativeCompositeRaster.hlsl:64-74`,
`DuoViewD3D12.hpp:139-150,254-270`, `DuoViewMonoCopyD3D12.hpp:68-73`.
This already avoids a separate sharpen pass, full-frame sharpening and an
additional external OpenXR layer. The arithmetic uses four diagonal and two
edge samples, with gamma decoding/encoding and a limiter.

**source-read:** v207 already allocates the double-wide gather atlas lazily,
only for incompatible direct source SRVs. Descriptor views are cached per retired
XR command slot. Shader compilation is offline in CI. Do not reimplement these.

**source-read:** A full W x H BGRA8 `output_` remains preallocated for every
compositor slot, including slots that use direct-XR on eligible frames.
**estimated:** At 4060 x 3228 it is 49.99 MiB per slot. This cannot be removed
from the present sharpening path: that path actually uses it. Making it optional
helps only an eligible direct-XR path and requires preserving fallback allocation
and GPU lifetime. It is not an automatic saving for Liviu's sharpened mode.

**source-read:** Native periphery Catmull-Rom uses nine bilinear samples outside
solid fovea; v207 bypasses that expensive filter under solid fovea. The shader
still has a bilinear periphery expression there. A compiler may optimize that
expression away when the lerp weight is 1; disassembly or GPU measurement is
needed before claiming a gain from a source rewrite. Debug isolation must stay
correct if restructuring this code.

**source-read:** Large source allocations exist beyond these compositor buffers.
Joey capture creation requests full HMD eye dimensions (`create_scene_capture`,
generated `FFakeStereoRenderingHook.cpp` around line 42300); DuoView only reduces
the source view rectangle to crop*density or peripheral scale. Native packet,
texture extent, capture-generation and source-validity checks assume existing
Native Fix sizes. STALKER 2 also uses an owned stable primary scene copy in
`D3D12Component.cpp` around 3380-3480. Removing it blindly risks volatile resource
lifetime problems. Right-sizing source resources is a plausible larger VRAM
project, not a two-line resolution change.

**estimated:** Candidate order for later optimization builds:
1. Collect same-scene game GPU ms/FPS, VRAM current usage AND budget, active source
   dimensions, output route and compositor GPU time at fixed settings.
2. Profile full-size primary/capture/stable copies and engine intermediate/history
   allocations before resizing them; verify pixels land at (0,0).
3. Test source right-sizing as its own build with immutable expected extents,
   capture generations and a GPU image test. Keep original-size fallback.
4. Measure shader/periphery alternatives independently; retain quality toggles.
5. Investigate engine per-family work only after pass timings. A one-family
   rewrite is not approved evidence of correctness; previous shading failures
   remain relevant.

Do not promise an FPS percentage or label unmeasured changes as performance wins.

## Exact Cheeky audit

**source-read:** Found custom r13 at `liviutrn/OpenNR`, branch
`experiments/cheeky-psvr2-r13-duoview-eye-select`, commit
`ad2d43336318ac3c35f4ad42d1032c258e8f3cfc`. Workflow
`.github/workflows/cheeky-psvr2-r13.yml` pins Cheeky source
`4e47eefe51a512dcaf76bbdc672dcdab5251fc71`. Workflow calls it 0.5.5;
that upstream commit's own version file says 0.5.4 before our patch changes it.
Use SHA and patch stack for identity, not only the display version.

**source-read/local replay:** All six custom scripts successfully replayed on
that pristine Cheeky SHA: overrides, adaptive, shaping, mono_dx12_test, r12, r13.
No Cheeky source modifications were made for this audit.

**source-read:** R13 settings:
- 0: Both, default and legacy behavior.
- 1: source role 0 only (UI labels it fovea).
- 2: source role 1 only.

The early gate precedes private SR/NR/peripheral-DLAA preparation in native DX12,
C ABI, DX11 and Streamline routes. Unselected source calls the original game
DLSS unchanged; it does NOT stop the scene render or the game's DLSS evaluation.
Unknown or shared-mono assignments bypass custom processing instead of guessing.
Relevant source: `CheekyPort/scripts/apply_r13.py:1-8,31-47,90-160`.

**source-read:** Role 0 is the existing eye-role coordinator's assignment. It
is not an explicit DuoView packet fovea contract. In particular DuoView supports
swapping its fovea source (`DuoViewFoveaSourceView`), while r13's UI label remains
'Eye 0 only (fovea)'. Do not assert that label proves correct mapping in the
installed configuration. Calibration can also mark a source shared-mono, in
which case single-role custom filtering bypasses it.

**source-read:** Both high-level and lower native NGX hooks exist, but Cheeky's
interception-depth dispatch prevents processing one nested native call twice.
Streamline also suppresses the nested native custom-processing path with
`inside_streamline_evaluation`. This is source protection, not a runtime count.

**source-read:** Even one selected source can involve a center SR operation,
optional extra peripheral DLAA, and an NR operation. These are distinct stages.
NR is not a synonym for SR. In the pinned source `Settings::peripheral_dlaa_enabled`
defaults true (`src/settings.hpp:45`), and optional NR defaults false (`:94`).
Cheeky's internal peripheral DLAA is inside one selected source; it is distinct
from DuoView's low-resolution periphery render. A runtime configuration using
both may have extra upscaler work within the already cropped DuoView fovea.
Compare this setting independently before modifying Unreal rendering. Disabling
it is a quality/performance tradeoff, not a proven free saving.
The final duplicate mono eye copy does not call DLSS.
It is therefore incorrect to claim 'DLSS runs only once total because mono'.

**not yet headset-verified:** Installed r12/r13 version, saved EyeProcessingMode,
actual source-role mapping and per-stage evaluations per game frame. Existing
Cheeky runtime JSON contains NR evaluation_calls, diagnostic API evaluations,
and per-view evaluations; sample deltas for a bounded interval at fixed settings,
not lifetime totals divided by an assumed headset refresh rate.

## Distance sharpening design and unresolved integration

**estimated/design:** Expose:
- Distance-based foveal sharpening toggle (default OFF for backward compatibility).
- Near strength 0..5, default 5; far strength 0..5, default 1.
- Near distance in meters: full near strength at or nearer than this.
- Far distance in meters: full far strength at or farther than this.
- Linear or smoothstep interpolation. Require far > near, reject NaN/infinity.
An inverted strength curve (far > near) must also be supported.
The existing fixed strength remains active when distance mode is off or current
foveal depth is unavailable. Report why fallback is active; never silently pretend
that distance is working. Equal endpoints are invalid, not a divide-by-zero path.

For near distance a, far distance b and camera-space depth z in meters:
`t = clamp((z-a)/(b-a), 0, 1)`; smooth mode uses `t*t*(3-2*t)`;
`strength = near_strength + (far_strength-near_strength)*t`.
Use camera-forward depth as the documented distance convention, or explicitly
choose radial distance and account for off-axis projection. Do not mix the two.

**source-read:** v207 color compositor has NO matching DLSS depth input. Old CI
code exists in `ci51/.../DuoViewNgxObserver.hpp`, `ci76/DuoViewNgxGuide.hpp` on
`experiment/ci81-persistent-depth-20261031`. It retrieves Depth/Color/MV/Output,
NGX subrects, input/output dimensions, reset, creation flags and jitter. It also
explicitly labels RHI interval/size association as NOT proof of a per-view camera.
Do not copy all old synthesis, temporal warp or candidate-gallery machinery.

**source-read:** NGX depth input is not guaranteed to be a temporally reconstructed
stable DLSS output. Jitter is supplied separately in input pixel units. In Cheeky,
outer DuoView fovea may itself be cropped into a smaller SR/NR region. Raw Depth
plus a guessed full-view UV is insufficient. Nested private NR depth can differ
from the game SR depth. This integration must account for both hook orders.

**estimated/required next stage before enabling distance mode:**
1. Observe exact foveal producer identity and active DLSS subrect, hook nesting,
   frame key, camera/projection, world units per meter, jitter and reset. Never
   identify depth by largest allocation or evaluation order alone. Attach/release
   and resolution changes must invalidate old association.
2. Preserve only foveal depth while its NGX input resource is valid. Prefer a
   bounded GPU-only snapshot of the active rect. Do not retain a raw pooled depth
   pointer for later sampling after periphery rendering has reused it. Verify
   source state, producer queue ordering and fenced retirement; no CPU readback,
   busy waits, per-frame allocations or full color/MV copies in normal operation.
3. Sample it in the EXISTING mono fovea shader, one depth lookup + arithmetic,
   so there is no additional full-frame sharpen pass or per-eye duplication.
   Map post-DLSS foveal UV to its valid depth rect and cancel documented jitter.
   Derive linear meters from the frozen projection and actual world units/meter;
   do not hardcode near plane, 100 units/meter or depth convention.
4. Provide a fovea-only distance/strength visualization and valid/fallback counters.
   GPU tests must check known near/far depths, nonzero subrects, jitter signs,
   reversed-Z, resize, missing depth, source swap and identical mono eye output.
5. Headset verification: near/far visualization on known geometry, visible
   configurable fade, and same-scene FPS/VRAM delta. At most three questions.

This work record deliberately does not present the distance design as implemented.
The actual live depth-to-color association remains the prerequisite.

## Independent source review

**source-read:** A fresh Luna review found no blocking issue in the v208 patch,
validation tests, hash scope check or workflow ordering before the first push.
Reviewer did not independently execute Windows/GPU tests.

## CI startup correction

**CI-verified:** Run #214 / 41451754971 reached and applied the new patch,
but the source-scope test compared Windows backslash keys to slash keys.
Normalize snapshot keys with Path.as_posix(); no runtime source change.
Real fxc shader compilation and existing patch checks passed before that failure.

## Deeper Cheeky diagnostics and retained caches (source-read)

R13's `skip_dlss_nr_history(view_id)` only sets `was_enabled=false`
(`src/dlss_nr.cpp:1507-1510`); `skip_d3d12_history` only invalidates crop history
(`src/d3d12_backend.cpp:734-737`). These calls do not retire the selected view's
existing private resources. **estimated:** Changing Both to one source can stop
new custom processing without immediately returning all previously cached VRAM.
This is retained cache behavior, not proof of a leak. A future cache-retirement
change must use the existing submission/lifetime tracking and must not free GPU
resources or private features still referenced by recorded/submitted work.
NR stores up to six cached GPU resource sets per view (`dlss_nr.cpp:183-189`),
plus feature/history state; do not estimate total residency from only one texture.

Existing support data is useful but not a complete per-source execution proof:
- `view_details[].evaluations` counts processing preparation, before all SR
  success/fallback paths have completed; Left/Right is the role coordinator label.
- NR totals are global and NR history statistics describe the latest view.
- `nr_details.vram_bytes` is the formula for the latest region/working texture
  set (`dlss_nr.cpp:1343-1345`), not DXGI residency or all cached resource sets.
- AFW eye counters must not be interpreted as ordinary DuoView source counters.
Do not claim exact successful SR/NR evaluations per game frame from those fields
alone. Use them to inspect settings, dimensions and likely source selection;
add per-source instrumentation if exact successful-call proof is required.

Runtime export names `CheekyRuntime_Snapshot` / `CheekyUEVR_Snapshot` expose JSON,
not depth. The existing UI path is **Cheeky Foveated DLSS > Support > Create
support ZIP only**. Its ZIP contains diagnostics.json, settings.ini and logs.
It can establish the installed version and settings relevant to the next stage.

## NR-only path verification after user clarification (source-read)

Independent Luna source review plus root source inspection found that the r13
EyeProcessingMode gate is evaluated before NR setup and independently of SR's
Enabled setting. With Enabled=false, NrEnabled=true, an unselected source calls
the original game DLSS without Cheeky NR. Selected source follows the explicit
NR-only before-upscaling or after-upscaling path. The private SR/peripheral-DLAA
path exits immediately while Enabled=false (`hooks.cpp:4800 onward`).

Before-order NR prepares/substitutes the input once; its after-DLSS callback
performs only optional border work, not a second NR evaluation. After-order
prepares no NR input first and evaluates NR after successful game DLSS instead.
Streamline suppresses nested native processing; generic D3D12 interception uses
an outermost-call guard. No duplicate NR evaluation was found for a SINGLE outer
DLSS evaluation in the audited native DX12, C and Streamline paths. This is not
runtime proof of exactly one outer evaluation per produced DuoView frame.

Remaining live verification: the selected source-role must match DuoView's
actual fovea; current runtime diagnostics do not prove exact per-source successful
NR invocations per produced game frame. NR-only performance work should focus
on processing dimensions/working scale, codec/copy cost and retained NR caches,
plus the independent Unreal/DuoView allocation and render-family costs.

## v208 final Windows result

**CI-verified:** Build #215, run 41452078775, source commit
`93c2d11ccee71d173ea06e2da07c5ab4ee42deca`, completed successfully.
https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/41452078775
Pinned production suite: 5/5; independent CPU/GPU suite: 6/6; original Joey
compatibility suite: 41/41. Real fxc shader compilation, backend/auxiliary DLLs,
frontend and final source integrity/package checks all passed.
Artifact: `UEVR-DuoView-Mono-v208-Sharpen-0-5-215`, ID `13147060302`.
Download: https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/runs/41452078775/artifacts/13147060302
**headset-verified:** pending for v208. No FPS or VRAM saving measured/claimed.
Distance-based sharpening and renderer/NR memory optimizations remain pending;
this is the isolated fixed-strength range build, not completion of those stages.

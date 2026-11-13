# DuoView M2.4 — independent review candidate (not headset verified)

**Base:** successful M2.3 #220, commit `beda32142be27ea76a9060066b3024c527818feb`.  
**Branch:** `experiment/duoview-m24-tears-seam-fade-epoch-20261113`  
**Reviewer:** Claude Opus, see `DuoView_M24_Implementation_Handoff_for_ChatGPT.md` supplied by Liviu.

## Implementation

1. **Horizontal break-line reduction (F6):** second compute PSO `CSConditionM1Vertical` on same per-command-slot `soft_depth` UAV after horizontal pass, with explicit UAV barrier. Columnwise doubling max-minus-penalty envelope. Horizontal Lipschitz bound stays intact by taking maxima of rowwise Lipschitz fields; vertical bound follows new taper. UI `Vertical depth taper` 0..8, default **2**. Zero skips vertical pass and reproduces M2.3's row-only algorithm **except** the deliberate constant grid described below. WARP GPU performance/correctness and headset tear/halo outcome remain to be evaluated.
2. **Seam corners (F3):** single 32-knot B40 temporal correction is unchanged; sampling *inside* crop uses radial central side projection, outside still uses previous nearest-edge B40. M2.3 full-feather matching is retained. The two fields in TriView B43-158 remain unchanged; no extra B40 history.
3. **Distance-faded sharpening:** opt-in OFF by default, controls near m=2, far m=15, normal far 40%, wide far 20%; apply independently to existing per-eye normal/wide strengths, based solely on the conditioned inverse-depth field, within ID6 synthetic stereo pixel shader. No world-scale double application: `geometry.world_to_meters` already includes `get_world_scale()`. New M1 cbuffer float4, total 272 bytes, upload 512 bytes. Mono OFF unchanged if fade OFF.
4. **Mono / stereo OFF wide:** b0 `FocusProfile.y` passes the linked wide strength to non-stereo Mono native compositor, ensuring wide works even when normal sharpening is zero. Stereo linked/unlinked strengths preserved. Direct-XR fast path and packed-effects routing now respect wide-only mode. When the linked wide strength equals normal strength, existing effect operation is preserved.
5. **Frame epoch additive rejection:** NGX depth snapshots stamp an atomic present epoch at capture, and frozen Mono packet stamps it at `VR.cpp` frame begin. Epoch increments once in the D3D12 Present depth-hook setup. In addition to prior M2.3 **adjacent sequence, <=25ms, same queue or same list, valid fences, matching request/generation/extents and freshness**, fine pairs must have `packet_epoch==coarse_epoch==fine_epoch`; missing epoch rejects. This does **not** prove exact scene-frame identity. The selector logs packet/coarse/fine epochs, source frame, epoch equality/reject counts. Fine remains OFF by default. Check the log before ever enabling fine, because VR frame freeze and NGX recording can occur at different timeline positions. Rejecting too much is safer than mismatching eyes.
6. **Fine depth ramp-in only:** 5 consecutive successful gated pairs start a 200ms weight ramp of fine-depth seeds *inside* global conditioner (`M1Filter.w`); any invalid candidate immediately drops the weight to zero, never samples an invalid lease. No independently owned history or extra target, preserves original resource lifecycle. The depth conditioner now ALWAYS uses its full bounded grid, even when fine depth is disabled; this deliberately **changes coarse-only conditioning resolution** relative to #220, aiming to prevent resampling pops when enabling fine.
7. **Scale log:** every two seconds `[DuoView][M2.4] scale` reports eye baseline, already-scaled world-to-metres, stereo strength, signed k, disparity at 1.0 and 0.4 metres (both eyes combined).

## Validation / gaps

- Python numerical model checks 2D Lipschitz monotonicity, vertical extent, 0 vertical pass, frame-epoch over-rejection, world-to-metres fade. Generated-source contracts assert alignment, constants, UI wiring, root PSOs, barriers and TriView isolation.
- FXC offline compiles both conditioner entries; production backend C++ tests and original WARP tests run in Windows CI.
- **Not implemented / must not be claimed:** dedicated 32x32 fine/coarse GPU content readback probe and independent timestamp-resolved per-pass GPU ms measurement. They require per-fence readback/owner state to avoid stalls and are intentionally deferred rather than adding unsafe GPU work to the stable renderer. Existing GPU timing can still be enabled for aggregate compositor cost, and pair metadata plus runtime log are available.
- Also not implemented: full dedicated WARP readback fixture for vertical conditioned grid; current numeric model tests the algorithm, shader FXC confirms syntax, production compiler tests integration.
- Legacy TriView Edge V2 temporal reference test remains nonblocking but **failed** in #220; do not call it a timing flake. Separate B43-158 reference test/async barrier investigation needed. Original TriView shader/compositor blobs must remain identical.
- **No headset validation:** do not claim break lines/halos, seam corners, sharpening perception or epoch pairing fixed until Liviu tests.
- M2.2 #203 remains known stable fallback, M2.3 #220 available as intermediate.

## Reviewer priorities

1. Audit actual Present epoch cadence relative to colour `mono_source_frame` and NGX eval, and the possibility of extra late NGX evaluations crossing Present; prove that additional gate is sound. Evaluate safe capture content comparators and exact engine stamps if needed.
2. Inspect `CSConditionM1Vertical` and CPU penalty formula for correct UV/disparity units and 1024 array bounds; verify UAV barrier, PSO and root signature, transition, timing and possible vertical halos.
3. Inspect `DuoB40CentralSide` corner continuity versus actual 32 B40 knots (and clipped/edge crops); ensure OFF and outside behavior preserved.
4. Verify Mono linked wide strength in gather and native routes; test regular=0, wide>0, and compare stereo OFF with M2.3 #220 when linked wide=regular.
5. Inspect 272-byte shader constants, 512-byte allocation and correct depth fade for actual world scale and NGX jitter.
6. Check cross-list queue/fence ownership and fine-depth ramp-to-zero logic; no stale leases or GPU use after retirement.
7. Review whether a separate 32x32 depth content probe and timestamp timing should be the *next* M2.4b before headset, rather than blocking a focused visual test.

## Headset (only after Claude diff review)

1. With fine OFF, usual stereo 0.9 / near 0.25m / sharpness 0.25: test whether weapon-top horizontal break lines improve with Vertical taper OFF/2/4/8; watch for vertical depth halos.
2. Seam matcher ON, broad blend feather: check corner diagonals. Activate distance fade, assess far foliage shimmer vs weapon detail; test wide-only in Mono.
3. Send 5 minute log showing epoch packet/coarse/fine, scale and no crashes. Leave fine OFF until equality proves reliable.

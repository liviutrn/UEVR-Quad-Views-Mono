# Quad Views Stereo ID7 — Build 41 engineering review

Date: 21 October 2026 (Europe/Bucharest).

Build 41 extends Build 40's isolated ID7 overlay. It keeps the four-view renderer, per-eye gaze/crop stabilization, fused Glamarye filter, quality defaults, and preserved DuoView ID6 source. Its purpose is to make atlas provenance and transition retirement agree with observed RHI command-tail execution. This bookkeeping is separate from GPU completion, which remains governed by the existing command-slot fences.

## Reproduced faults and intended repairs

| Fault | Independent reproduction | Repair |
|---|---|---|
| Source-less engine render overwrites an older eligible atlas | Execute a valid source, then a same-target engine ticket with no accepted source. The older source remains selectable. | A verified writer invalidates every other executed, unsubmitted candidate for its target. |
| Out-of-order completion pairs the wrong image and pose | Execute source 21's tail, then source 20's against the same target. Selection still chooses 21, although 20 is the last observed writer. | Use observed execution order rather than draw-serial comparison for target invalidation. |
| Completed engine ticket leaves an unexecuted source blocking retirement | Register matching engine/source records; execute the engine tail without a source match. Engine pending count reaches zero, but retirement remains false. | Retire only the exact unexecuted, unsubmitted source belonging to that proven completed ticket. |
| Unknown or failed engine ownership still allows image selection | Poison ownership through capacity/ambiguity or a terminal hook failure while an older candidate exists. | Block selection while ownership proof is lost; preserve known completion bookkeeping and show a restart-game diagnostic. |

Submitted owners and unrelated pending sources must remain retained. No timeout, forced generation advance, or assumed GPU completion may clear uncertainty.

## Scope and limits

- No changes to `duoview/**`, restricted SDK source, original backend pins, or stable tags/releases.
- No new compositor pass, sharpening algorithm, gaze smoothing, or render-scale defaults.
- The original Build 32 RenderThread access violation remains unsymbolized and unproven fixed. These repairs address demonstrated bookkeeping faults; they do not establish the crash's exact cause.
- A genuinely missing RHI-tail proof, an untrackable family, or ledger overflow still requires safe failure. Automatic recovery is not implemented without a verified engine/RHI quiescence mechanism.
- The generated adapter supports only one tracked family per hooked command tail. Multiple families sharing a tail are a plausible failure path, but recurrence and ordering have not been demonstrated in the supported game. Build 41 must diagnose and fail closed rather than introduce speculative batching.
- Headset stability, shading parity, GPU performance, and 1% low FPS require real STALKER 2 testing.

## Validation

The supervisor independently reproduced stale selection and the orphan-source drain stall against the pre-fix code. A separate reference model passed 160,000 randomized completions against the candidate, using two targets, optional sources, and reordered engine tails; that model fails against the pre-fix code.

- Build 40 base: `7486fc59890b14673cd50770b0dafeb692576716`.
- Implementation used GPT-6 Luna at maximum reasoning, with separate supervisor review and regression checks.
- Supervisor rerun: producer contracts, 100,000 asynchronous transactions, 300,000 geometry/settings cases, 160,000 independent target-writer model completions, nine Python checkpoints, and all 84 protected baseline source files passed.
- Worker ASan/UBSan producer and asynchronous checks passed; leak detection was disabled for that run.
- Worker and supervisor separately applied the overlays to pristine pinned backend/frontend sources. Windows FXC was explicitly unavailable/skipped for these local source-application checks; they are not Windows compilation results.

Full Windows compilation and headset acceptance remain separate gates. The packaged build metadata identifies the exact compiled canonical source and CI runner commits.

## Headset acceptance

Use the same known-safe resolution and game scene as the baseline. Keep NVIDIA Smooth Motion disabled for comparisons.

1. Start with gaze off and sharpening 0. Confirm stereo depth, stable focus/context alignment, correct head movement, and sustained four-view output.
2. Test gaze on, manual offsets with gaze off, and sharpening 0/1/2. Check UI, edges, blinks, and gaze reacquisition.
3. Repeat 7 → 6 → 0 → 7 transitions. Confirm the modes either complete safely or show an explicit unresolved-ownership status; never force a blocked transition.
4. Run 30–60 minutes of ordinary gameplay, including loading/menu transitions. Collect UEVR and game logs if output stops or a crash occurs.
5. Compare identical scenes/settings against Build 39/40 using GPU frame time and 1% lows. No performance increase is claimed from portable or WARP tests.

If ownership proof is explicitly lost, restart the game. Do not deliberately exhaust VRAM or force-reset the ownership ledger.

The observed tail need not be a universal end-of-family barrier: this snapshot does not prove that Unreal cannot append more commands afterward or that Present cannot occur inside the original hooked command. The changes preserve the existing adapter contract and do not resolve that ordering uncertainty. Dedicated engine/RHI instrumentation and headset evidence are required before strengthening the claim.

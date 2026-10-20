# Build 41 — ID7 ownership and delivery fixes

Based on Build 40 source `7486fc59890b14673cd50770b0dafeb692576716`.

- Invalidate stale, unsubmitted atlas candidates when another tracked family writes the same target, including families without an accepted source.
- Follow observed RHI-tail execution order when completions arrive out of draw order. Keep the corresponding image and pose together.
- Retire an unexecuted source after its exact engine ticket completes without a source match. Unrelated pending work and submitted GPU owners remain retained.
- Stop selecting images after ownership proof is lost through ambiguity, capacity exhaustion, or a terminal hook failure. Stale callbacks cannot poison a newer generation.
- Report a restart-game status and log conflicting owner/tail identities for diagnosis.
- Add deterministic regressions and an independent 160,000-completion reference-model test.

The renderer, per-eye gaze stabilization, fused Glamarye filter, quality defaults, and preserved ID6 source remain unchanged. No new compositor pass is added. Glamarye attribution ships in `GLAMARYE_LICENSE.txt`.

This is an experimental candidate. The original Build 32 RenderThread crash remains unproven fixed. Observing an RHI tail is not a universal engine flush or a GPU completion fence. Unknown ownership still fails closed; there is no timeout-based forced recovery.

Use `READ_FIRST.txt` for the test sequence. See `BUILD41_REVIEW.md` for reproduced faults, verification, and remaining risks. Full Windows compilation, shader/WARP tests, and a real headset retest are required before treating the candidate as validated.

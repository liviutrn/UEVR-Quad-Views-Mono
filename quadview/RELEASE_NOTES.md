# Build 46 — four-source Native Stereo Fix

Build 46 addresses the reviewed ID7 issues around deferred command ownership,
main-family routing and physical render-target contents. It is built from the
accepted Build 40 source at
`7486fc59890b14673cd50770b0dafeb692576716`.

## Review finding to fix to test

| Review finding | Production change | Regression coverage |
| --- | --- | --- |
| Several native view callbacks can resolve to one deferred Slate tail. | ID7 brackets each Slate worker drain with a thread-local drain identity and immediate-list identity. The NativeDelivery ledger batches every attached view role and completes only the roles actually present. Partial same-quartet batches can finish across later tails. Cross-quartet or otherwise ambiguous sharing remains drainable but cannot publish. | `NativeDeliveryTests.cpp` covers partial shared tails, distinct later tails, ambiguous cross-quartet sharing, missing/late callbacks and owner drainage. |
| Selecting the first view family or filtering every auxiliary family can misroute a batched render call. | The adapter authenticates the unique main family against the frozen family/scene/target/four-view snapshot. It preserves the first original batch, including auxiliary families, then sends only selected main-family singletons to later callbacks. Invalid main identity fails closed; unrelated auxiliary families can pass through even with empty scene/target identities. | `FamilyRoutingTests.cpp` exercises exact identity, auxiliary ordering and null/empty auxiliary families, duplicate and malformed main candidates, nested callbacks, first-registration failure, exceptions and restoration. |
| A later physical writer can leave a newer packet selectable even after its pixels were overwritten. | Per-target content stamps identify the packet that last wrote each native output. Actual writers invalidate older content proofs; queued future quartets remain eligible to restore coherence after their own four writes. Content bookkeeping safely reclaims targets only after no live owner uses them. | `ContentProvenancePropertyTests.cpp` checks all 40,320 write orders across two quartets, checks each selection against the reference contents, verifies fresh-quartet recovery and tests 40 same-generation target-set replacements. |
| A source or packet can be reclaimed while its CPU-side RHI command is still queued. | Each production RHI map entry retains one native command/source owner per represented quartet. The callback copies an execution lease before erasing the map and holds it through the original callback. | `NativeDeliveryTests.cpp` resets the delivery ledger while a copied owner lease is the only packet reference and checks release after the lease ends. |
| View callbacks must not advance OpenXR cadence four times per quartet. | Only a represented view-3 event can claim runtime cadence; a shared tail chooses the newest attached view-3 event, deduped by generation and serial. Quarantined content still drains, while its selected packet is blocked. | `NativeDeliveryTests.cpp` checks partial roles do not advance cadence, view 3 advances once, duplicate claims are rejected, and late older events cannot regress the frame. |

## Preserved behavior and limits

Build 40's FOV, gaze, crop geometry, fixed-center option and stereo behavior
are retained. ID6 DuoView and its source tree remain unchanged. ID7 renders
left/right context and focus into four engine-owned outputs, then composites a
different image for each eye using ordinary stereo OpenXR submission.

Each native target retains the full source atlas extent so existing Unreal
view rectangles and projections remain intact. This increases target memory
use; pixel-count estimates are not performance measurements. Display-gamma
parity, in-game shading and shadow behavior, live GPU-fence retirement, and
performance have not been measured on a headset. No headset stability claim
is made from CI.

See [`README.md`](README.md), [`READ_FIRST.txt`](READ_FIRST.txt), and
[`VALIDATION.md`](VALIDATION.md) for setup, supported target, and evidence.

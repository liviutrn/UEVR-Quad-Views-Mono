# Build 49 — explicit singleton frame identities

Builds 46, 47 and 48 failed in the user's PSVR2. Build 40 remains the
last visually working Quad Views comparison, with intermittent startup and
excess brightness indoors. No newer version is headset verified.

## Concrete defect addressed

Build 48 creates one native quartet at singleton role zero, skips source
registration for later roles, and matches every RT singleton using role zero's
frame number. Its dispatch validation checks view and target restoration but
never proves the four engine-assigned family frame numbers agree. A role with
a different frame cannot claim its native owner; falling through to the
original-atlas matcher cannot recover it because that ticket has another target.
Such a quartet cannot complete or retire its engine ticket.

Build 49 records each role's own frame, scene and isolated target in that role's
GT BeginRenderViewFamily callback, before Unreal copies its renderer family.
RT matching uses those exact role keys. The original source/engine ledger is
claimed with the quartet's canonical frame, independently of RT arrival order.
No approximate frame matching, larger ledger, forced retirement or fabricated
GPU completion is used. Original fencing and four-of-four publication remain.

The explicit-binding mode is used at both production native bind sites,
including discard-only packets. The header retains its legacy same-frame bind
API for existing callers/tests. New tests exercise the production explicit mode.

## Diagnostics

`NativeRole/GT` reports all four assigned frames and their bound mask;
`NativeRole/RT` reports exact unmatched frame/target/scene keys. Native tail
execution is now logged at the actual callback. `EngineRegistration` reports
the actual rejection reason, pending/capacity and oldest serial. Reason enum:
0 invalid ticket, 1 stale generation, 2 duplicate same owner (accepted),
3 ambiguous RT key, 4 capacity exhausted, 5 accepted.

Important correction to earlier interpretation: generated Build48 does not
emit the historical `RHI source executed` string. Its absence alone was not
proof that its callbacks never executed. Zero CopyEnqueued/Submit and the
user's black screen still establish the three failures.

## Validation and limits

Existing portable production-header suites cover asynchronous delivery,
retirement, physical content provenance, source selection and recovery.
New tests cover distinct per-role frames, reordered RT arrivals, missing or
conflicting registrations, exact target/scene matching, generation changes,
target reuse, runtime cadence and sustained bounded occupancy. A mutation
restoring the old same-frame assumption must fail the new regression test.
Windows CI additionally compiles the actual backend against its original
restricted SDK and runs the existing GPU WARP and compatibility suites.

The actual assigned frames in the three historical runs were not logged.
Therefore this is a source-proven missing contract and a tested recovery
candidate, not a proven sole explanation of those runs or a headset fix claim.
Other failures (including OpenXR handle errors after reinitialization) require
new runtime evidence if they remain. Test in a separate folder: start ID7,
check both eyes/gaze/FOV and interior shadows, then 10 minutes and mode reentry.
Supply the full log if delivery still stops. The new markers distinguish a
frame-key miss from tail execution or downstream copy/submission failure.

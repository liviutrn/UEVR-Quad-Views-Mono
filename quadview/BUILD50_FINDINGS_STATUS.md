# Build50 diagnostic status

Build49 compiled and passed CPU/GPU/compatibility/sanitizer tests but failed
repeated headset testing. Native ID0 also exhibited headtracking stutter.
Build40 remains the last visually working quad-view reference (intermittent
startup; overly bright interiors). No newer quad build is headset verified.

Three independent reviews agree that the first unretired transaction must be
observed at the actual engine hook adapter before another behavioral patch.
Build49 logs show engine ticket 4126 before native targets, then native quartet
4128 with four distinct GT frames. Pending capacity eventually reaches 16;
there is no observed tail retirement/copy/submission. Later RT misses do not
establish whether the first native RT match succeeded. Generic callback success
occurred before ID7 and does not establish ID7 callback execution.

## Build50 changes

Automatic bounded scalar trace at actual GT/RT/Slate/hook/RHI boundaries,
all 27 hook returns and attach results, vtable/map/owner/frame/drain snapshots,
and callback/worker/XR timing. The native matcher has an optional scalar observer;
fresh-ledger tests compare results and state with and without that observer.
The parser reports earliest observed rejection and missing observed stages,
without converting absence into proof of nonexecution. Counts are per-site
cumulative observations; the pre-lock and owner-bound entry records are distinct.
A stale-address clue (recorded entry with live vtable different from our hook)
is evidence to investigate, not permission to delete an outstanding owner.

## Deliberately unchanged behavior

No map pruning, ownership admission, retirement, pointer-chain traversal,
vtable replacement, execution index selection, XR sync policy, original callback
invocation or render geometry fix. The upstream has_good_root precedence quirk
is preserved; route markers reveal Slate fallback. A first legacy engine ticket
can remain unretired, foreign recorded tails can reject native owners, and
shared-tail quarantine may prevent publication. Which event occurs first is
not yet established. No lighting, shader, frame pacing or submission issue is
cleared by these tests.

The exact original Joey backend/SDK/frontend pins and all 84 preserved DuoView
baseline files remain unchanged. ID7 uses a custom four-source path; this is not
an assertion that its end-to-end dispatch is identical to the working DuoView.

## Release gate

Build50 is diagnostic only. Production readiness requires repeatable cold ID7
startup, mode transitions/loading, coherent four-source rendering and actual
headset output, FOV/stereo/gaze/lighting parity and sustained motion stability.
Compilation and WARP tests cannot establish these outcomes. Collect three
separate logs as described in READ_FIRST.txt before selecting a behavioral fix.

## Trace result legend

GT_REGISTER result: 0 invalid ticket, 1 stale generation, 2 duplicate same owner,
3 ambiguous RT key, 4 capacity exhausted, 5 accepted.
RT_MATCH result: 0 accepted, 1 no role key, 2 ambiguous role key, 3 already
rendered, 4 missing canonical engine claim, 5 engine identity mismatch.
NATIVE_ATTACH result: 0 attached, 1 duplicate, 2 quarantined (drain only),
3 overflow, 4 rejected. Quarantined does not authorize publication.
Native execution result is accepted=1/rejected=0. XR sync result uses the
original VRRuntime::Error enum. Addresses are hexadecimal; masks are decimal.
Possible stale-vtable clues require ours_known=true.

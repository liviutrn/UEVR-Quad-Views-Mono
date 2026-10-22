# Build 48 recovery candidate — 22 October 2026

## Source-backed defects

Build 47's outer family router returned without calling Unreal when the current
producer snapshot was incomplete but the batch contained the potential main
family. Its original GT callback, exact frame binding, RT callback and RHI
cadence therefore could not run. This creates a recoverability trap while pose,
constructor or source evidence is warming up. This is a demonstrated code path;
the historical logs do not establish it as the sole cause of their black screens.

The recovery path now authenticates a unique readable original family using its
known target, scene, family and constructor-view subset, calls the original
engine batch unchanged, and records an engine-only ticket. Source eligibility
continues to require the complete four-view producer and coherent stereo pose.
Malformed or ambiguous potential main families still fail closed.

The original engine-tail map kept one owner. Several deferred engine-only
callbacks sharing that tail could leave later tickets permanently unretired.
The new bounded drain batch records and retires all authenticated tickets at
the original callback. Native and engine-only owners can share a known tail in
either arrival order. Mixed legacy atlas sources are demoted; packet leases
remain in existing callback records while original CPU commands execute.
Unknown hooked tails, capacity exhaustion and ambiguous native provenance are
rejected. A CPU callback is not a GPU fence. Native resource retirement retains
the existing genuine queue/fence path.

## Validation

The deterministic harness exercises 2,400 coherent source-owner selections over
24 generation resets, 192 startup/recovery tickets, two/four-view family
admission, invalid targets/scenes/families/views, duplicate tickets, wrong tails,
partial execution, reversed tail execution, shared native tails, mixed
engine/native tails in both arrival orders and demotion of unproved atlas
content. It uses production delivery/routing headers; its source writes are
simulated and do not claim real Unreal rasterization or real OpenXR submission.
An explicit legacy-admission mutation must return the starvation signature and
exit code 2; arbitrary failures cannot pass that check.

The separate existing suites cover 100,000 asynchronous transactions, 40,320
two-quartet write permutations, settings/layout properties, renderer geometry,
owner leases, native retirement diagnostics and actual Windows WARP shader
pixels. The pinned Windows workflow builds the backend, auxiliary DLLs,
matching frontend and original compatibility tests. CI source and package
manifests identify the exact reviewed overlay and SDK. Consult the linked CI
run for completion; local portability checks alone do not clear the Windows gate.

The new log classifier distinguishes fresh two-eye submits from held output,
scopes serials to mode generations, rejects zero/regressing serials and flags
startup-only success or prolonged starvation. Nine unit cases include synthetic
startup black, positive progress with mode changes, held images, invalid serials,
and verbatim excerpts from two historical logs. The full 21 October trace
contains two fresh submits 62.202 seconds apart and 2,199 missing-stage messages;
it fails continuity. The 20 October trace also fails despite 37 submit records.
Throttled logs cannot establish FPS or GPU completion.

Luna performed bounded log/test work and two read-only critique passes. The
first caught mixed-tail owner drainage and a weak mutation check; both were
repaired and covered by targeted tests. Stale generation drain batches are
intentionally ignored after a ledger reset; this protects the new generation
and is not a statement that an old GPU fence completed.

## Windows compiler regression

The first complete Windows compile exposed a Windows SDK `max` macro collision
in the new drain helper. The helper now compares serials directly. A dedicated
compile/runtime test includes the production header under a hostile function-like
`max` macro and verifies that newest-serial ordering is unchanged. A negative
compile with the pre-fix header reproduces the collision. The rebuilt pinned
Windows workflow must pass before distribution.

## Preserved behavior and acceptance limits

Build 40 remains the user-tested binocular/FOV/gaze comparison. The shader,
projection, crop, colors, native quartet publication criteria, SDK pins, native
fence retirement and all 84 baseline ID6 files are preserved. No adaptive
resolution, weapon-FOV or UI convergence feature is added here.

Offline tests cannot establish that this build works visually on PSVR2. Test
startup, a shadowed interior, both eye seams, gaze movement, horizontal/vertical
FOV, repeated mode changes, save loading and at least ten minutes of gameplay.
Keep the full log and optionally export the existing Hook Provenance JSON if
any scene output stops. Compare against your saved Build 40 folder and restore
that injector/build to roll back. No profile edits are required by this patch.

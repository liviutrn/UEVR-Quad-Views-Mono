# CI31 provenance contract — engineering status

Parent: e1d72917e482855592c02be799a2070e9244d4cb (CI30)
Branch: experiment/ci31-provenance-audit-20261028

This is a **producer-identity test/diagnostic build**, not stereo playback validation.
No existing D3D12 depth observer, candidate shape, DSV pointer/write rank, copy
fence or later XR packet may set `Stamp::authenticated=true`. Only a future
engine-source producer hook that observes actual UE view family / scene-frame /
view, render stages, color and depth resource writes may assert that fact.

The pure-C++ contract explicitly rejects: missing left/right authenticated
depth, wrong role, different actual producer frames, different view generations,
invalid stage family, differing view/projection/jitter or common origin, missing
matrices, expired ownership, unsubmitted or unsynchronized GPU resources.
Its tests run on Windows CI. The contract is NOT yet connected to the live
selector. The existing mode 1 remains the CI30 experimental horizontal shader,
and hybrid HLSL remains offline. V3 mode 0 is unchanged.

CI31 additionally counts **normal-interval viewport-shape observations**
versus successfully recorded depth copies, separately against each expected
source geometry. A shape may match both roles at different scales. These counters
are diagnostic, not semantic UE0/UE1 labels or same-frame proof. Snapshot capture
does not contribute to the normal counters.

Next mandatory integration: attach authenticated stamps at real UE0/UE1 depth
producer writes in the pinned backend, with exact source-color write and per-pass
matrices; bind them to DSV captures and apply this validator *before* enabling
a new, isolated opt-in hybrid dispatch. Never relax the validator to make tests
pass by supplying guessed stamps.

Verification tags: source-confirmed contract, Windows C++ test pending CI,
headset NOT tested, depth/color semantic identity NOT yet verified, hybrid live
dispatch NOT integrated, gameplay speed and visual quality NOT measured.

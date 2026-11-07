# TriView B31 - conservative GPU efficiency fixes
Date: 2026-11-07
Parent: B30 commit `2e9b7567bbe190b1c934045ed64121ba655458e2`.
Known-good rollback: B28-103 `3ebe512c830a8e7467717d85d1cd0b7f52c5e4ba`.

## Scope and invariants
No extra Unreal view, DLSS invocation, texture or D3D12 allocation.
B28 world gates, ownership leases, fence retirement, resizing, restart, depth
age limit and foreign-queue completion rules are unchanged. B29 XYZ and
depth-hook improvements and all B30 saved UI defaults are retained.

## Shader fast paths
* Enabled focus correction uses the same radial gain formula, but skips pow()
  while r2 <= onset or when radial gain is disabled. Uniform focus brightness
  is still applied even inside the neutral center.
* Adaptive peripheral correction uses squared distance to reject pixels
  outside the local fade radius; sqrt() executes only inside that radius.
  Four-side blending, gain caps, confidence and interpolation are unchanged.
* When requested depth-dependent alignment is unavailable, every compute
  lane takes the same uniform early branch. Lanes 0..8 write neutral
  (1,1,1,0) records per eye, and there are no color or depth probes.
  No groupshared barrier is skipped by only some lanes, and stale records
  from a previously valid dispatch are overwritten.
* Adaptive correction at strength zero skips the compute dispatch entirely,
  unless the confidence diagnostic is requested. The pixel shader also skips
  the corresponding statistics loads. Matching-mode sharp-focus behavior
  remains enabled as before; strength zero does NOT restore legacy feather.

## GPU timings
The last-retired analysis time is zero when a timed frame contains no
adaptive compute dispatch. Total compositor timing still covers the
ordinary command interval. Missing/unavailable timings remain unmeasured.
No new CPU synchronization, GPU wait or readback is introduced.

## Regression coverage
* Expanded WARP test: zero-strength pixel identity, sharpening enabled
  during adaptive matching, missing depth after valid statistics followed
  by valid-data recovery, along with all previous per-eye/near-edge cases.
* Added static/math checks for radial equivalence, squared radius, uniform
  neutral record writes, no unneeded statistics loads and no-analysis timing.
* FXC /WX, Windows WARP, compatibility suite, backend/frontend, portable
  sanitizers and package checks still gate the final artifact.
* Fix B30 packaging stop by restoring literal 'ID7' in READ_FIRST.txt
  (the existing packaging validator explicitly requires it).

## Caveats
No verified PSVR2 performance gain or visual improvement is claimed until
headset tests. The matcher still uses unsharpened low-frequency fovea
probes to avoid additional sharpening passes, not final sharpened pixels.
Rapid motion may still cause adaptive global brightness/color pumping.
There is no outward guard band, and low-FPS peripheral depth flicker is
not addressed here. Preserve the B28-103 headset rollback.

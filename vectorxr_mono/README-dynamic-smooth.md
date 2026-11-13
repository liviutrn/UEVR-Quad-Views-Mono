# VectorXR 0.20.1 — build #19: reserve diagnostics and lead safety

Experimental source branch: `experiment/vectorxr-dynamic6-reserve19-20261113`.
Based on **fully CI-passed build #18** at `bf01c70c67fe6408dec6855cc3974f209ea0911b`.
Pinned original VectorXR upstream: `DienerTech/vectorxr`
`8fffa72e99be8ab1e39457c7353faeb1218ac83f`.
The reviewed **Mono baseline** `96aebe7d5fbe35af6cecb0fc0f609b4ff9ce70ed`
remains untouched, as do shaders, stereo, FOV/poses and unrelated TriView code.

This is a research build, **not an official VectorXR release**. A passing CI
suite proves compilation and simulated-runtime regressions, not perceived
PSVR2 smoothness or true compositor scanout timing.

## What is (and is not) meant by "6x"

Dynamic + JIT + Interpolate already synthesizes slots on every nominal
refresh (when GPU/runtime can manage); a source frame every 50 ms at
120 Hz can already give five intervening generated frames. The switch
`VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX=6` increases Dynamic's possible lead
cap and per-multiplier history bookkeeping. **It does not add frames**.
It is worth trying only if the log shows a relevant `leadSlots=16 (cap)`.

## Settings — restart OpenXR/game after edits

The settings are read from Windows environment variables or
`%LOCALAPPDATA%\VectorXR\framegen-research.txt` (one `NAME=VALUE` per line).

```ini
VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX=6
VECTORXR_FRAMEGEN_FLOW_LEAD_RESERVE=2
```

Defaults, in this research build:
- `VECTORXR_FRAMEGEN_FLOW_DIAGNOSTICS`: **1, enabled without any setting**.
  Set `=0` only for overhead comparison. Full debug per-frame CSV remains
  **off by default** because extra I/O can change pacing.
- `VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX`: **4** (stock ceiling). Values 5/6
  opt into larger bookkeeping capacity.
- `VECTORXR_FRAMEGEN_FLOW_LEAD_RESERVE`: **0** (stock lead controller).
  Values 1–4 are accepted, but **test 1–2 only** until actual headset logs
  establish adequate frame history. Reserve applies only to Dynamic +
  Just-in-Time + Interpolate; other modes are unchanged.

## Evidence-based reserve controller, build #19

The reserve targets measured *early GPU completion slack* rather than
blindly adding N refreshes to a formula-derived latency:
- ON-TIME with fewer than N refreshes spare: **thin**. Three thin samples
  among the recent ten can raise the lead by just one refresh.
- ON-TIME with more than N + 1.1 refreshes spare: **spare**. Measured
  samples (excluding unknowns) can authorize stepping down. The helper
  requires at least five measured samples, at least 70% of measured frames
  spare, and at most one thin. Seven spare + three thin **cannot** trigger
  both up and down in the same window.
- Missing GPU completion evidence scores **unknown**, not spare or thin.
  When reserve is on, blind probes are suppressed except after a long run
  of unmeasurable slack.
- A measured down followed by a reserve up in under 15 seconds triggers
  a 20-second prohibition on further measured downs; subsequent flaps
  double it to 40 and then 60 seconds.
- Current-lead, timely, non-cover ring shortages suspend extra reserve
  for 120 seconds. Shortages due to a late presenter, older lead/multiplier,
  cover frame or stale-motion fallback are *excluded*.
- The controller remembers the failed lead for ten minutes, so it won't
  immediately try the same high lead. It refunds one reserve-added lead
  step if available and safe; it does **not** force a larger state reset.
  An active backoff does not extend itself continuously on more shortages.
- Reserve's own additional lead steps are tracked as credits; normal
  down/probe/clamp steps consume credits. The session and compositor-start
  resets clear this accounting and the history of previous reserve scores.

With reserve=0 and max=4 the lead scoring, lowering, probing, cap and ring
policy follow stock code; diagnostics add measurements but not pacing
decisions. This equivalence is a targeted test/review objective.

## Diagnostics: every 30-second summary

New build #19 regime/lead counters:
- `smoothScored`: scored frames at the current lead, excluding skipped
  grace/probe history.
- `smoothSlackUnknown`: scored on-time frames without valid early GPU
  slack; compare with `smoothScored` to judge whether reserve can work.
- `smoothReserveOff`: scored frames with reserve configured but inactive
  (e.g. ring backoff); compare with `smoothScored`.
- `smoothSlackRefreshesP05P50`: 5th percentile/median *measurable*
  early slack, expressed in refresh periods, works even when reserve=0.
  Not an estimate for missing/unknown frames.
- `smoothReserveUps`, `smoothReserveFlaps`,
  `smoothRingBackoffs`, `smoothReserveGivebacks`: observed reserve
  interventions. A backoff is counted on entry, not each subsequent
  suspended frame: use `smoothReserveOff` for duty cycle.
- `smoothCover`: accepted, distinct JIT predictions that took the
  cover path; `smoothMotionLate`: separate accepted predictions using
  fallback from late motion measurement.
- `smoothSubmitted`, `smoothInterp`, `smoothPredict`, `smoothOther`:
  accepted JIT runtime submissions by classification (the last three
  partition the first). Classification is not proof of correct images.
- Existing from #18: inferred proxy-content `smoothFreeze`, `smoothJump`,
  `smoothRewind`, `smoothMotionErrMsP50P95/P99`; target gaps, return
  gaps and CPU lateness P50/P95/P99; missing grid, target reversals,
  per-source-pair gaps and long pauses. Counters exclude discontinuities
  across compositor restarts and pauses.
- Always inspect stock `appFps`, `outputFps`, `distinctFps`,
  `leadSlots`, `lateReal`, `covers`, `ringExhausted`,
  `ringShort`, `unready`, `runtimeHalved`, `gpuMs`, `ofaMs`.

**These counters are NOT a measurement of what SteamVR actually scanned
out.** Even `smoothFreeze=0` can coexist with visual ghosting or GPU
reprojection. Verify perceived quality inside the headset, and optionally
SteamVR frame timings and upstream's debug `.framegen-trace.csv`.

## Critical simulated-runtime investigation: the 82.4% timeline anomaly

Build #18's 90Hz fake runtime, at about 16.1 real FPS and ~90 outputs/s,
reported `TimelineShare=0.824324` in both Max 4 and Max 6 runs. That
could mean one off-time image for every real source frame; it could also
be adaptive lead movement. **It is an unresolved anomaly, not evidence of
a working improvement.**

Build #19's `TestJitDynamicInterpolationSlow` now:
- Warms up 2500 ms, records the *start and end lead* and *real frame count*.
- Prints **off-timeline count / total**, not just a passing fraction.
- When `FG_TEST_GAPS=1`, lists each bad refresh's time, error in 90Hz
  refresh periods and phase relative to the nearest real game frame.
- Compares adaptive lead to a lead **pinned at its warm-up settled value**
  (not an arbitrary value that might be capped during startup).
- Requires **at least 95%** content-time accuracy in pinned mode. Adaptive
  pass is diagnostic and no longer hides the problem with a 0.80 threshold.
- Still checks >90% distinct output, non-stalling, ordered timestamps.
  It tests both Dynamic Max 4 and Max 6 in a 90Hz fake runtime.

If the pinned test falls below 95%, CI must fail: stop, examine the
bad-phase evidence, and investigate the underlying presenter pacing before
claiming build #19 as usable. No scheduler or shader changes are included.

## Owner A/B test once build passes

Do not skip real headset evidence. Use the same demanding STALKER 2 scene,
same UEVR/Cheeky and OFA settings, 3 minutes per test:
1. **Build #16**, 120 Hz, reserve 0, Max 4.
2. **Build #16**, 90 Hz, identical settings.
3. **Build #18**, 120 Hz, Max 6 and reserve 2.
4. **Build #19**, only after full CI success, 120 Hz, Max 6 and reserve 2.

Send complete VectorXR logs, plus whether each felt smoother and whether
latency and weapon trails were tolerable. One small change cannot be called
an improvement without these observations.

## Builds and rollback

CI patches exact pinned upstream with the protected Mono patch first,
then this Dynamic patcher, using strict single-match anchors. It builds
the Windows Release DLL, runs both small focused tests, two fake-runtime
tests, and the full upstream CTest suite, then uploads package and test
evidence. Keep the installed 0.20.1 DLL as a backup and copy **DLL only**;
do not replace the OpenXR layer JSON. Restore the backup on regression.

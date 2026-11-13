# VectorXR v0.20.1 — evidence-based Dynamic reserve + motion telemetry

Personal experimental derivative of upstream `DienerTech/vectorxr` commit
`8fffa72e99be8ab1e39457c7353faeb1218ac83f`, with the **reviewed
unchanged Mono implementation from commit `96aebe7`**. This build is NOT an
official VectorXR release and has not been evaluated in a PSVR2 headset.

The previous audit build #16 (commit `75303dbda0dafe7462337f80931bbdb0bdf8c64d`)
is preserved as an A/B reference. These changes live only on
`experiment/vectorxr-dynamic6-evidence-reserve-20261113`.

## What 6× actually does

Dynamic/JIT interpolation in stock VectorXR already requests **one output
per runtime refresh** and positions each intermediate image by its target
display time. At 20 real FPS on a 120 Hz runtime, this can already mean
five intermediate images between real frames. The setting
`VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX=6` **does not create more slots**:
it extends Dynamic's lead/multiplier bookkeeping and lead-cap ring indices
to 5 and 6. Its performance value must be established from
`leadSlots=16 (cap)` or ring evidence; do not assume that Max 6 improves
smoothness.

## Settings and defaults

Set in `%LOCALAPPDATA%\VectorXR\framegen-research.txt` or as environment
variables, then restart the game/OpenXR session:

- `VECTORXR_FRAMEGEN_FLOW_DIAGNOSTICS`: **ON by default** in this
  experimental audit build. Set `0` to disable. Per-refresh counters
  use bounded vectors; expensive sorting happens only at summary time.
- `VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX`: **4 by default**, can opt into
  `5` or `6`. With 4, lead and Dynamic cap behavior remain stock.
- `VECTORXR_FRAMEGEN_FLOW_LEAD_RESERVE`: **0 by default**, choose 1–4
  to target that many refresh periods of measured spare arrival time.
  The reserve is active only in Dynamic + Just-in-Time + Interpolate,
  and is suspended on history-ring exhaustion/shortage.

With reserve 0, the stock late/spare score and down-probe paths are retained.
Unlike #16's formula floor, the new reserve does **not** preallocate a fixed
number of additional buffered refreshes. It instead increments the lead by
one only if at least 3 recent on-time frames had less measured slack than
requested. It can step down only when at least 7 recent frames have
more than reserve + 1.1 refreshes of measured slack; blind probes are
suppressed except after a prolonged period of unmeasurable slack.
Ring exhaustion or ring shortage disables reserve for 120 seconds;
it does NOT immediately force the existing lead lower.

This tradeoff is experimental. Increasing lead can add latency, lower
application FPS, or exhaust a 3-real-frame history ring. The logs—not
the multiplier name—must determine whether it helps.

## Default-on log fields (30-second reporting windows)

- Existing `appFps`, `outputFps`, `distinctFps`, `lateReal`,
  `covers`, `unready`, `ringExhausted`, `ringShort`,
  `runtimeHalved`, `leadSlots`, `gpuMs`, `ofaMs`.
- `smoothSubmitted` counts accepted JIT `xrEndFrame` submissions;
  `smoothInterp` + `smoothPredict` + `smoothOther` must equal
  `smoothSubmitted`. Classification is conservative: only the
  distinct, non-exact, primary JIT write (path 3) gets Interp/Predict.
  Other includes repeats, fallback paths and blank/unchanged images.
- `smoothCover` counts predicted frames covered because the next frame
  is late, **including late motion measurement fallback**; it may be a
  subset of the existing broader `covers` statistic.
- `smoothReserveUps`, `smoothRingBackoffs`: measured-slack reserve
  increases and reserve suspensions on insufficient history.
- `smoothEndGapMsP50P95/P99`: gaps between successful JIT
  `xrEndFrame` **CPU returns**, not actual display scanout.
  `smoothTargetGapMsP50P95/P99`: gaps between requested OpenXR display
  timestamps. `smoothSubmitLateMsP50P95/P99`: lateness of CPU
  `RuntimeBegin` entry relative to the layer's scheduled due instant.
  `smoothSubmitLateHalf`: lateness > half a nominal refresh.
- `smoothMissedGrid`, `smoothTargetRegress`: inferred missing target
  grid slots and target reversals. Requested timestamps are not a record
  of what the display actually scanned out. A runtime rate change or
  halving may appear as missing targets.
- `smoothPairs`, `smoothPairRewind`, `smoothPairGap`: source-pair
  continuity of accepted interpolation fractions, ignoring long pauses.
- `smoothFreeze`, `smoothJump`, `smoothRewind`, and
  `smoothMotionErrMsP50P95/P99`: **inferred content-time cadence**
  from source timestamps/fractions and repeated images. These describe
  nominal motion time, not image pixels, OFA correctness, perceived
  smoothness or exact headset refresh behavior. A misgenerated optical-flow
  image can still score as perfectly timed; all zeros are NOT proof of
  perfect VR motion.
- `smoothPauses`: accepted-target discontinuities longer than the
  presenter's pause limit. Presenter restarts reset the continuity
  history so menus/restarts do not inflate cadence error metrics.

Frame samples use bounded memory. Optional debug logging starts upstream's
`.framegen-trace.csv` containing frame-by-frame `pick`, `sub`, target
times and fractions. Debug is intentionally **not** enabled by default,
because per-frame CSV disk writes can perturb the pacing being measured.

## Headset A/B test

Use Dynamic + Interpolate + NVIDIA OFA, with identical UEVR/Cheeky settings
in the same demanding STALKER 2 area. Preserve existing VectorXR DLL for
rollback. Only swap the DLL; do not replace the OpenXR layer JSON.

1. **Baseline build #16** at PSVR2 120 Hz, reserve 0, no extra settings,
   about 3 minutes. Save full VectorXR log.
2. **Same #16 at 90 Hz**, same workload/settings. Save log and subjective
   ranking of smoothness, lag and weapon trails.
3. **New evidence-reserve build** at 120 Hz with:
   ```ini
   VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX=6
   VECTORXR_FRAMEGEN_FLOW_LEAD_RESERVE=2
   ```
   Diagnostics are already on. Save full log after at least two 30-second
   windows; note whether lag is acceptable and whether motion improved.
4. Optional short debug-trace run and SteamVR frame timing.

When interpreting: `leadSlots=16 (cap)` justifies examining Max 6;
nonzero late real/covers suggests lead; nonzero ringExhausted/ringShort
suggests a memory/history limit; `runtimeHalved` or 16.7ms target gaps
at 120 Hz suggest a runtime cadence limit. The new lead reserve must not
be called a win without actual headset evidence.

## CI and regressions

The branch patches the same pinned upstream code using
`apply_vectorxr_mono.py` first and
`apply_vectorxr_dynamic_smooth.py` second, with strict anchor counts.
The review-protected `mono_framegen.h`, its patcher, the shaders,
poses/FOV and unrelated TriView code have not been edited.
Unit tests check reserve thresholds (including stock-off equivalence),
content cadence classification, 5/6 bookkeeping and target-grid math.
Upstream's existing fake-runtime presenter harness receives additional
slow-Dynamic and jittered-reserve smoke tests.

CI verifies Release DLL compilation, both focused tests, the new fake-runtime
smoke tests, complete upstream CTest suite and a downloadable DLL artifact.
**A green CI build does not establish 20→120 headset smoothness.**

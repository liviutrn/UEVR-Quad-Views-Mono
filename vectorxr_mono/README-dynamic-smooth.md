# VectorXR 0.20.1 — Dynamic6 telemetry audit build

This is an **experimental personal build** based on upstream VectorXR 0.20.1
(commit `8fffa72`) plus reviewed Mono baseline `96aebe7`. The original
Mono detector, stereo mode, shaders, poses/FOV, and VectorXR Fixed/Auto
scheduling are not changed by this telemetry phase.

## Default behavior — IMPORTANT

The **low-overhead summary diagnostics are ENABLED by default** in this
audit branch. You do not need to add any setting to activate them. Set
`VECTORXR_FRAMEGEN_FLOW_DIAGNOSTICS=0` to disable and compare overhead;
`=1` enables explicitly. A game/OpenXR session restart is needed.

The actual timing experiments are **still opt-in**:
- `VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX` defaults to `4` (reviewed behavior);
  accepted values: `5`, `6`. This affects Dynamic lead/multiplier
  bookkeeping; timestamp-based JIT synthesis itself was never capped at 4×.
- `VECTORXR_FRAMEGEN_FLOW_LEAD_RESERVE` defaults to `0` and is NOT
  recommended for initial measurements. Values `1` to `4` enforce
  a high minimum lead only for Dynamic + Interpolate + JIT; at 20 real FPS
  it could be more than 100ms and reduce source FPS or exhaust history.
- Diagnostics are enabled for all JIT output in the session, not solely
  when Dynamic Max 6 is selected.

These can be set in `%LOCALAPPDATA%\VectorXR\framegen-research.txt`,
or overridden with Windows environment variables.

Suggested first comparative run at 120Hz, Dynamic + Interpolate + NVIDIA OFA:

```ini
VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX=6
VECTORXR_FRAMEGEN_FLOW_LEAD_RESERVE=0
# Diagnostics is already on (no line necessary)
```

## What the normal 30-second log now reports

`smoothSubmitted` counts JIT slots whose `RuntimeEnd` succeeded.
`smoothInterp`, `smoothPredict`, `smoothOther` partition **accepted JIT
submission attempts**, so their sum must equal `smoothSubmitted`.
To avoid false quality claims, only distinct, non-exact output writes from
the primary JIT path (path=3) qualify as interpolation/prediction. Alternate
source/path 4 and exact/unchanged copies go to Other.

`smoothCover` counts *a subset* of predicted submissions using a cover
choice while the next real frame is late. `smoothStale` counts predicted
submissions using older motion fields.

`smoothEndGapMsP50P95` and `smoothEndGapMsP99` measure CPU clock gaps
between successful JIT runtime `xrEndFrame` **returns**.
`smoothTargetGapMsP50P95` and `smoothTargetGapMsP99` measure gaps
between the submitted target `XrTime` values, which are requested display
slots, NOT a recording of actual scanout.
`smoothSubmitLateMsP50P95` and `smoothSubmitLateMsP99` record positive
delays from the internal scheduled submission instant to the CPU start of
`RuntimeBegin`. `smoothSubmitLateHalf` counts delays > half a refresh.

`smoothMissedGrid` estimates omitted nominal refresh slots based on the
submitted target-time gap and current measured grid period, capped at 120
per discontinuity. `smoothTargetRegress` counts non-monotonic submitted
target times. These are **diagnostic inferences**; a runtime refresh-rate
change or halving can look like a missing slot.

`smoothPairs` counts *observed* new source-frame pairs used for accepted
primary JIT interpolation. `smoothPairRewind` detects a non-increasing
interpolation fraction within one pair. `smoothPairGap` detects >1.5
refresh between interpolated samples using the same pair. These counts
do not establish complete coverage of every real-frame pair; the full
debug trace is needed for exact missing-fraction reconstruction.

Existing fields (`appFps`, `outputFps`, `distinctFps`, `covers`,
`repeatedFrames`, `runtimeHalved`, `ringExhausted`, `unready`,
`ofaMs`, `gpuMs`, `leadSlots`) remain essential.

**Neither these counters nor successful `xrEndFrame` prove that SteamVR
actually scanned out a unique, optically correct image.** Cross-check
headset perception and SteamVR frame timing.

## Files to send after the first run

1. Full VectorXR session log (including startup and at least two 30-second
   summaries from a stable difficult scene).
2. For a short second run, enable VectorXR's normal **Debug** log level and
   send the adjacent `.framegen-trace.csv`, which includes per-frame JIT
   source IDs, target display timestamps and chosen interpolation fractions.
   Debug tracing is intentionally NOT default-on: its per-frame disk I/O
   could affect the pacing we are trying to measure.
3. Optionally SteamVR's frame timing or a consistent headset observation
   (camera pans and moving weapon). Do not change Cheeky/UEVR settings
   between A/B tests.

## Safe test & rollback

First test Dynamic Max 4 with built-in diagnostics, then Max 6 and no lead
reserve, at 120Hz (and optionally 90Hz). Then test save reload and Mono ↔
Stereo. Keep a backup of the installed VectorXR 0.20.1 DLL; restore it if
there is a black eye, device hung, or extra judder. Replace DLL only, not
the installed OpenXR JSON. This is **CI-buildable code, not a verified
smooth 20→120 headset result**.

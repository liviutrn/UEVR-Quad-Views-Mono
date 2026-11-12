# VectorXR 0.20.1 / Dynamic Smoothness experiment

Base: reviewed Mono patch commit 96aebe7 applied over upstream 8fffa72.
Experimental timing policy only, no changes to stereo, Mono image collapsing,
FOV/poses, shaders, OFA or UEVR. All switches **off by default**.

In `%LOCALAPPDATA%\\VectorXR\\framegen-research.txt` add:

```ini
VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX=6
VECTORXR_FRAMEGEN_FLOW_DIAGNOSTICS=1
# Optional after reading the initial 30-second logs:
VECTORXR_FRAMEGEN_FLOW_LEAD_RESERVE=1
```

- DYNAMIC_MAX: 4 (stock), 5 or 6; extends only Dynamic multiplier and
  lead/ring bookkeeping. The JIT interpolation fraction is already uncapped.
- LEAD_RESERVE: 0 (stock), 1-4; creates an enforced minimum on top of a
  latency/real-interval estimate in Dynamic + Interpolate + JIT; **not pinned**.
  The adaptive controller cannot probe below that floor, but can still step
  above it and the learned ring ceiling still caps it. With 50ms application
  work and 50ms real interval at 120Hz, reserve=1 requests 13 slots (~108ms).
  This is NOT a cheap, guaranteed one-slot increase over the current lead.
  A large floor may reduce real FPS or exhaust the capture ring. Keep
  LEAD_RESERVE disabled until the diagnostics justify trying it.
- DIAGNOSTICS: log successful-runtime-submission, distinct, non-exact JIT
  writes classified by their *chosen synthesis mode*: smoothInterp and
  smoothPredict. smoothOther covers other successful JIT slot submissions,
  including copies/repeats/fallback paths and no-layer slots. The invariant
  is smoothInterp + smoothPredict + smoothOther = smoothSubmitted.
  smoothEndGapMs is median/p95 of wall-clock gaps between successful JIT
  xrEndFrame **returns**, not deadlines or headset panel scanout. The labels
  do not guarantee optical correctness or that SteamVR actually displayed
  each image. Existing outputFps, distinctFps, repeatedFrames, covers,
  unready, staleMotion, runtimeHalved and ringExhausted remain essential.

20 real FPS on 120 Hz ideally means 20 real + 100 synthetic FPS, five
interpolated frames between real A/G at 1/6, 2/6, 3/6, 4/6, 5/6.
The existing debug 'pick' trace contains source IDs, presentation times
and chosen interpolation fractions.

Test at 120Hz in the same heavy scene: control with switches OFF,
DIAGNOSTICS only, then MAX=6, then RESERVE=1 and =2 individually.
Provide 2+ 30-second windows of each, then repeat at 90Hz.
Also test Mono to Stereo switching and save/reload. CI does not prove
headset display cadence, image fidelity or runtime safety.

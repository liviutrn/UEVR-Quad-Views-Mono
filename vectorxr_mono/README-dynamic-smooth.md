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
- LEAD_RESERVE: 0 (stock), 1-4 added refresh slots above a calculated
  minimum in Dynamic + Interpolate + JIT; **not pinned**. Automatic lead
  increases and history ceiling continue operating. A large reserve may
  reduce real FPS or exhaust the capture ring.
- DIAGNOSTICS: log distinct true interpolations (smoothInterp), successful
  extrapolations (smoothPredict), and median/p95 intervals between
  xrEndFrame **returns** (smoothEndGapMs), not actual headset scanout.
  Existing outputFps, distinctFps, repeatedFrames, covers, unready,
  staleMotion, runtimeHalved and ringExhausted remain essential.

20 real FPS on 120 Hz ideally means 20 real + 100 synthetic FPS, five
interpolated frames between real A/G at 1/6, 2/6, 3/6, 4/6, 5/6.
The existing debug 'pick' trace contains source IDs, presentation times
and chosen interpolation fractions.

Test at 120Hz in the same heavy scene: control with switches OFF,
DIAGNOSTICS only, then MAX=6, then RESERVE=1 and =2 individually.
Provide 2+ 30-second windows of each, then repeat at 90Hz.
Also test Mono to Stereo switching and save/reload. CI does not prove
headset display cadence, image fidelity or runtime safety.

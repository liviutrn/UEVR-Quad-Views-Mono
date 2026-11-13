# VectorXR research build #21 (instrumentation + opt-in A/B/C)

Pinned upstream: DienerTech/vectorxr 8fffa72 (0.20.1). This experiment branches from **green #20** 6b67fa55. Both behavior experiments are **off by default**. No production source-clock, pose/FOV, shader, or ring-size changes with empty settings. The existing reserve controller is unchanged but disabled in A/B/C.

## What changed

1. Frame classification: exact, repeated, fallback, zero-projection, unknown (disjoint subdivision of successful JIT submissions). Prior `smoothOther` remains for backward log compatibility.
2. GPU capture-ready vs motion-analysis-ready first observed fence samples and needed-deadline diagnostics. First positive means only a bound (refresh-quantized), **not** an exact GPU-fence timestamp. Additional fence queries require `VECTORXR_FRAMEGEN_RESEARCH21=1`.
3. A world-tick-driven fake-app test with independent wall-time game-thread tick (UE-style) and #18 exact 1-second warm-up fixture alongside #20 2.5-second warm-up. Diagnostic assertions do not presume improvement.
4. Optional **content-clock B** uses sub-refresh *release phase* to relabel GPU synthesis fractions only; the original grid value still picks the source, gates exact copies, and shifts headset eye-position pose. This is an imperfect proxy for UE world tick; compare with separately logged UEVR trace before judging.
5. Optional **Max6 hysteresis C** permits Dynamic multipliers 2–6, switching when smoothed frame interval crosses an extra +/-0.75 refresh boundary; it retains the stock cap/ring accounting for each multiplier. No change at Max4.
6. Startup line: `VectorXR #21 mode: A/B/C ...`.

## One-session headset test (after Claude reviews code and green CI)

Use the supplied `settings-presets` directory. Copy A, B, C one at a time to `%LOCALAPPDATA%\\VectorXR\\framegen-research.txt` (rename only), restarting the game each time. Use 120Hz TriView, same heavy area, ~3 minutes per run, slow head-turn + strafe past narrow objects. Include the UEVR trace DLL to collect game tick vs pose/render info. No text edits required. Send VectorXR logs, UEVR CSV, UEVR log, and one-line notes for each mode.

## Predetermined stop/go rules

When a reliable frame-ID join exists, compute world-tick versus JIT real-frame content stamp **interval error**: P95 >= 3 ms @120Hz supports further dual-clock work; <= 1 ms argues stopping; in between requires headset A/B. For GPU readiness, if measured capture-and-motion margin under one refresh occurs in under 1% of eligible frames, no new lead controller is justified. If join or sample volume is insufficient, declare result inconclusive. DistinctFps is not scanout or visual correctness.

**Review blockers:** confirm the release-phase proxy does not contaminate pose or exact frames; validate UEVR game/render frame join, fence sampling side effects, all CI tests; no headset claim before actual test.

# VectorXR research build #21 (instrumentation + opt-in A/B/C/D)

Pinned upstream: DienerTech/vectorxr 8fffa72 (0.20.1). This experiment branches from **green #20** 6b67fa55. Both behavior experiments are **off by default**. No production source-clock, pose/FOV, shader, or ring-size changes with empty settings. The existing reserve controller is unchanged but disabled in A/B/C.

## What changed

1. Frame classification: exact, repeated, fallback, zero-projection, unknown (disjoint subdivision of successful JIT submissions). Prior `smoothOther` remains for backward log compatibility.
2. GPU capture-ready vs motion-analysis-ready first observed fence samples and needed-deadline diagnostics. First positive means only a bound (refresh-quantized), **not** an exact GPU-fence timestamp. Additional fence queries require `VECTORXR_FRAMEGEN_RESEARCH21=1`.
3. A world-tick-driven fake-app test with independent wall-time game-thread tick (UE-style) and #18 exact 1-second warm-up fixture alongside #20 2.5-second warm-up. Diagnostic assertions do not presume improvement.
4. Optional **content-clock B** uses sub-refresh *release phase* to relabel GPU synthesis fractions only; the original grid value still picks the source, gates exact copies, and shifts headset eye-position pose. This is an imperfect proxy for UE world tick; compare with separately logged UEVR trace before judging.
5. Optional **Max6 hysteresis C** permits Dynamic multipliers 2–6, switching when smoothed frame interval crosses an extra +/-0.75 refresh boundary; it retains the stock cap/ring accounting for each multiplier. No change at Max4.
6. Startup line: `VectorXR #21 mode: A/B/C/D ...`.

## Per-refresh trace schema and objective A/B/C/D comparison

Research outputs to `%LOCALAPPDATA%\\VectorXR` are unique files for each launch: `vectorxr-real-trace21-<timestamp>-<mode>.csv` and `uevr-world-trace21-<timestamp>-<mode>.csv`. No copying or editing files between runs. Both traces use an atomic rolling buffer (131,072 entries); a file snapshot is written every 20 seconds **and explicitly on normal OpenXR session teardown**. Do not hard-kill the game: force termination can still lose its last interval. A runtime reinitialization flushes without permanently stopping future recording.

Each row uses `kind,frame,secondary,tick,qpc_ns,display_xr,pose_xr,aux,extra`. VectorXR's per-compositor-refresh record is `kind=7`, created after successful `xrBeginFrame` and optional successful `xrEndFrame`. A row with `aux` bit 11 clear is a *begin-only hold*, not a successfully submitted new image. These records are not proof of physical headset scanout.

For `kind=7`:

- `frame`: source real-frame ID of the image actually selected (0 if unknown); join VectorXR `kind=6` real-frame records by this ID
- `secondary`: source's previous real-frame ID, if still present in the frame-history ring (0 if unavailable)
- `display_xr`: target OpenXR refresh display time (ns)
- `pose_xr`: **GPU fraction × 1,000,000**, or `-1` for output with no newly synthesized GPU fraction. The field name `pose_xr` is historic; do not interpret it as a pose time on kind 7
- `aux`: packed path/flags: bits 0–7 selection path; 8 exact; 9 written; 10 distinct; 11 submitted xrEndFrame; 12 rendered; 13 fraction valid; 14 generated; 15 cover; 16 unmeasured; 17 stale; 18 motion late; 19 source ID known; 20 previous ID evicted; **21 extrapolation** (otherwise interpolation when fraction valid)
- `extra`: previous real-frame `XrTime` even if its ID was evicted

Source IDs and actual GPU fractions are recorded from the final post-synthesis choices, *not* the planned pre-GPU selection. Fallback, repeated, pose-only, no-projection, and unknown paths must be analyzed separately. Do not calculate reconstructed scene time for rows whose fraction is invalid or whose source timing cannot be joined. With a valid UE tick mapping, interpolation scene time is `w_prev + f×(w_source − w_prev)`; extrapolation is `w_source + f×(w_source − w_prev)`. Exclude stale/unmeasured cases from the high-confidence distribution and report their frequency.

Join UEVR by its `kind=1` independent game tick counter (in `tick`) to `kind=2` render assignment (same `tick`), render `frame` to `kind=3` pose and `kind=4` submit (use last pose before submit when duplicated), then UEVR `kind=4` `display_xr` to VectorXR `kind=6` real-frame `display_xr`. Verify monotonically advancing frame IDs, unique source IDs, and the proportion of successful joins. UEVR's `kind=1` `frame` is **not** the game frame ID; do not join on that stale value.

For each A/B/C/D run report (a) P50/P95/max of the *median-centered interval error* between UE world tick and real-frame labels, (b) reconstructed displayed-content residual by refresh for valid generated and exact frames separately, (c) fraction of repeated/held/fallback/missing-projection frames, (d) real FPS and reported output FPS, and (e) any invalid/missing source joins. Compare changes in phase variance, not constant phase offset. The agreed P95 go/stop thresholds (3 ms/1 ms) apply only when the join is reliable; otherwise declare the result inconclusive. If B fails to improve the real headset's motion, reject it even if the proxy looks attractive.

The synthetic residual equation test checks only the algebra for interior samples; it is *not* independent evidence of real-world improvement. CI and an adversarial code review are required before installing.

## One-session headset test (after Claude reviews code and green CI)

Use the supplied `settings-presets` directory. Copy A, B, C, D one at a time to `%LOCALAPPDATA%\\VectorXR\\framegen-research.txt` (rename only), restarting the game each time. Use 120Hz TriView, same heavy area, ~3 minutes per run, slow head-turn + strafe past narrow objects. Include the UEVR trace DLL to collect game tick vs pose/render info. No text edits required. Send VectorXR logs, UEVR CSV, UEVR log, and one-line notes for each mode.

## Predetermined stop/go rules

When a reliable frame-ID join exists, compute world-tick versus JIT real-frame content stamp **interval error**: P95 >= 3 ms @120Hz supports further dual-clock work; <= 1 ms argues stopping; in between requires headset A/B. For GPU readiness, if measured capture-and-motion margin under one refresh occurs in under 1% of eligible frames, no new lead controller is justified. If join or sample volume is insufficient, declare result inconclusive. DistinctFps is not scanout or visual correctness.

**Review blockers:** confirm the release-phase proxy does not contaminate pose or exact frames; validate UEVR game/render frame join, fence sampling side effects, all CI tests; no headset claim before actual test.

## Claude #21 P0 corrections
- Mode B uses an EMA mean release phase as the content-time target; the stock exact real-copy rule and pose clock stay untouched. No claim that this equals UE world time.
- World-tick fake logs GPU synthesis fractions (not just pose-based TimelineShare) and a separate deterministic content-clock residual model.
- CSV traces retain recent data in a dynamically allocated ring, snapshot every 20 seconds and at shutdown, and use timestamp/mode-specific filenames to preserve A/B/C/D runs without copying files.
- Analysis completion time is **not** directly measurable with the current backend API. `researchAnalysisLateDue` is a conservative synthesis-outcome indicator, not a first-fence timestamp; `researchGpuMargin` is a conditioned, readiness-before-due sample.
- D is an optional cadence lock at 120Hz; only use it when the game can sustain its target. A=off, B=clock, C=max6 hysteresis, D=locked cadence. Independent switch, default 0.

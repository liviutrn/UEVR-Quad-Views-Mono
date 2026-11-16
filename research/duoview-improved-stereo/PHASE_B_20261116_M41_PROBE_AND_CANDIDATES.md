# DuoView improved stereo — Phase B probe and conservative candidates (2026-11-16)

**Scope:** research only. Based on the complete engineer handoff, official compiled WARP #349/#350 captures, and generated C++ diff. This note does not authorize a playable build or changing M4 defaults.

## Reproduced controls
- Handoff archive integrity 70/70; baseline Python tests 15/15.
- #350 compiled-HLSL 48 A/B/C stereo captures: v1 and v2 rejected under the original all-scenes gate.
- Calibrated official #349 baseline is 1024×816 per eye with 81.3% independently calibrated valid source region.

## New isolated CPU-overlay quality experiment
All methods reuse the *official generated-M4 WARP image* as fallback. Newly synthesized candidates are CPU-only and have NOT been compiled to HLSL. Foreground truth is independently projected and not fed to the candidate.

| method | static foliage motion-subtracted residual vs GPU M4 | static foliage edge-band temporal | verdict |
|---|---:|---:|---|
| raw owner | +61.9% | +369% | NO-GO |
| fine/coarse agree | +9.8% | +54.5% | NO-GO |
| agree + color edge | +11.5% | +56.2% | NO-GO |
| bulk opening 13px | +26.0% | +172% | NO-GO |

The fine/coarse gate reduces whole-frame false jitter but still creates unacceptable local flashing. It improves weapon and layer edges, but cannot be promoted under single-scene worst-case gates. Additional 17px bulk opening and diluted/color variants failed too. Stop tuning these mechanisms absent a new independent source of confidence.

## M41 source identity: exact fault boundary

The pinned authored overlay `apply_duoview_m41_frame_bind.py` emits a Slate-tail marker with owner packet serial. The generated backend accepts one coarse + one fine NGX evaluation between consecutive serial markers on the same CPU thread. The GPU fence check protects depth-copy completion, **not scene identity**. A marker serial cannot prove that both NGX evaluations were from the same source frame as the color packet. A pair may pass even when an independent oracle assigns different hidden scene IDs; this is unobservable using current NGX snapshot fields.

The existing M25 epoch histogram is sampled later in the compositor and may miss packets that fail M41 before XR acquisition. Avoid inferring a high matched-pair rate from these successful-only logs.

## New metadata-only diagnostic patch (NOT applied to live repo)
A separate working packet contains `apply_m41_metadata_probe.py` and the exact `M41_METADATA_PROBE_generated_350.patch`. Apply only after the M41 overlay to a materialized backend on an isolated diagnostic branch. Adds exclusive per-marker reject reasons, lookup readiness counters, marker↔coarse and fine↔coarse Present-epoch skew histograms at interval close, and cumulative logs every 2 seconds before the fine-pair XR gate. No extra GPU images, SRVs, readbacks, or rendering algorithm. The generator refuses changed source anchors and leaves both input files untouched on failure.

The extracted C++20 M41 method was compiled and executed under a Windows-free fixture; the C++17 telemetry struct/log stub also compiled. 18 additional isolated offline tests pass, including source drift and oracle-indistinguishability cases. **The full Windows backend build and real-game runtime remain untested.**

## Resolution coverage
New analytic stress corpus generated at 2030×1614 and 4060×3228 per eye, with 1–3 px wires, overlapping near/mid, stereo sign, a 0.5×0.5 fine crop, jitter, false 7×7 raw-depth blocks and physically moving thin geometry. This is explicitly **NOT WARP-calibrated at these sizes**, and cannot qualify a replacement shader.

## Next gate
1. Apply the opt-in patch on an isolated build branch and compile with existing Windows CI; verify no backend behavior changes. No playable release.
2. If a diagnostic build is available, acquire ONE bounded ordinary session and parse the cumulative counters with `analyze_m41_probe_log.py`; no repeated headset tests.
3. If marker correspondence is causally established, seek a genuinely independent depth-confidence source; then rerun full-size compiled WARP and NVIDIA RTX GPU timestamps before any guarded gameplay build.

**No playable release has been modified; no new algorithm is approved.**

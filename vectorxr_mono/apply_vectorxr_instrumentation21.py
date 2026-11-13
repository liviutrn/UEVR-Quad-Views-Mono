#!/usr/bin/env python3
"""Add non-behavioural VectorXR #21 research counters after Mono and Dynamic patchers.

Upstream is pinned by the workflow. All anchor edits fail closed. This patch
cannot modify frame selection, frame time, lead policy, GPU writes, or shaders.
Research fence queries are OPT-IN (VECTORXR_FRAMEGEN_RESEARCH21=1).
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
H = root / "layer/include/depthxr/framegen_presenter.h"
P = root / "layer/src/framegen/framegen_presenter.cpp"
files = {H: H.read_text(encoding="utf-8"), P: P.read_text(encoding="utf-8")}

def change(path, old, new, label, expected=1):
    current=files[path]
    found=current.count(old)
    if found!=expected:
        raise SystemExit(f"#21 anchor {label}: {found}, expected {expected}; no files written")
    files[path]=current.replace(old,new)

change(H, "    bool scored{false};\n        // Quad views:",
"""    bool scored{false};
        // Diagnostics only; never involved in a frame selection decision.
        bool research_capture_recorded{false};
        bool research_analysis_recorded{false};
        bool research_due_recorded{false};
        // Quad views:""", "JitFrame flags")

change(H, "    bool smooth_diagnostics_{true}; // audit build: enabled unless explicitly disabled",
"""    bool smooth_diagnostics_{true}; // audit build: enabled unless explicitly disabled
    bool research21_{false}; // extra GPU fence sampling; OPT IN only
    std::vector<double> research_capture_margin_periods_;
    std::vector<double> research_analysis_margin_periods_;""", "research fields")

change(H,"        std::uint64_t smooth_rewinds{0}; // inferred content-time rewinds",
"""        std::uint64_t smooth_rewinds{0}; // inferred content-time rewinds
        // #21 JIT output paths: the first three are disjoint, the rest
        // subdivide successful "other" outputs. Never scanout proof.
        std::uint64_t research_exact{0}; // path 2 or path 3 exact
        std::uint64_t research_repeated{0}; // non-distinct submitted paths
        std::uint64_t research_fallback{0}; // path 4,5,7,8 when distinct
        std::uint64_t research_no_projection{0};
        std::uint64_t research_other_unknown{0};
        // First-positive fence observation bounds, not GPU timestamps.
        std::uint64_t research_gpu_seen{0};
        std::uint64_t research_analysis_seen{0};
        std::uint64_t research_due_count{0};
        std::uint64_t research_gpu_not_ready_due{0};
        std::uint64_t research_analysis_not_ready_due{0};""", "research totals")

change(P,
'    smooth_diagnostics_ = ReadResearchSwitch("VECTORXR_FRAMEGEN_FLOW_DIAGNOSTICS") != "0";',
'''    smooth_diagnostics_ = ReadResearchSwitch("VECTORXR_FRAMEGEN_FLOW_DIAGNOSTICS") != "0";
    research21_ = ReadResearchSwitch("VECTORXR_FRAMEGEN_RESEARCH21") == "1";''', "optional flag")
change(P,
'    smooth_slack_periods_.clear();',
'''    smooth_slack_periods_.clear();
    research_capture_margin_periods_.clear();
    research_analysis_margin_periods_.clear();''', "reset samples", expected=2)

# These are the stock GPU-fence observations. Counting observes state,
# not changing it. Additional Measured() queries occur only when opted in.
change(P,
"""            for (JitFrame& kept : jit_frames_) {
                if (!rendered) {
                    kept.scored = kept.scored || kept.time <= slot_time_ + period / 2;
                } else if (!kept.scored && kept.needed > slot_time_ + period / 2) {
                    kept.ahead = true;
                    if (!kept.captured_early) {
                        kept.captured_early = !gpu_ || !kept.capture_mark || gpu_->CaptureReached(kept.capture_mark);
                    }
                }
            }""",
"""            for (JitFrame& kept : jit_frames_) {
                if (!rendered) {
                    kept.scored = kept.scored || kept.time <= slot_time_ + period / 2;
                } else if (!kept.scored && kept.needed > slot_time_ + period / 2) {
                    kept.ahead = true;
                    if (!kept.captured_early) {
                        kept.captured_early = !gpu_ || !kept.capture_mark || gpu_->CaptureReached(kept.capture_mark);
                    }
                    if (research21_ && period > 0) {
                        if (kept.captured_early && !kept.research_capture_recorded) {
                            kept.research_capture_recorded = true;
                            ++totals_.research_gpu_seen;
                            AddSample(research_capture_margin_periods_,
                                      static_cast<double>(kept.needed - slot_time_) / static_cast<double>(period),
                                      kMaxFrameSamples);
                        }
                        if (!kept.research_analysis_recorded && kept.analyzed &&
                            Clock::now() >= kept.motion_not_before &&
                            (!gpu_ || gpu_->Measured(kept.analyzed))) {
                            kept.research_analysis_recorded = true;
                            ++totals_.research_analysis_seen;
                            AddSample(research_analysis_margin_periods_,
                                      static_cast<double>(kept.needed - slot_time_) / static_cast<double>(period),
                                      kMaxFrameSamples);
                        }
                    }
                } else if (research21_ && rendered && !kept.research_due_recorded &&
                           kept.needed <= slot_time_ + period / 2) {
                    kept.research_due_recorded = true;
                    ++totals_.research_due_count;
                    if (gpu_ && kept.capture_mark && !gpu_->CaptureReached(kept.capture_mark))
                        ++totals_.research_gpu_not_ready_due;
                    if (gpu_ && kept.analyzed &&
                        (Clock::now() < kept.motion_not_before || !gpu_->Measured(kept.analyzed)))
                        ++totals_.research_analysis_not_ready_due;
                }
            }""", "fence sampling; flag off")

# Disjoint classification within successful JIT submissions. The prior
# smoothOther bucket remains untouched for backwards-compatible logs.
change(P,
"""                     ++totals_.smooth_submitted;
                     // A compositor restart,""",
"""                     ++totals_.smooth_submitted;
                     if (path == 1) {
                         ++totals_.research_no_projection;
                     } else if (!distinct) {
                         ++totals_.research_repeated;
                     } else if (path == 2 || (path == 3 && write.exact)) {
                         ++totals_.research_exact;
                     } else if (path == 4 || path == 5 || path == 7 || path == 8) {
                         ++totals_.research_fallback;
                     } else if (path != 3 || !written) {
                         ++totals_.research_other_unknown;
                     }
                     // A compositor restart,""", "output classification")
# Path 3 distinct/!exact moving frames remain smoothInterp/smoothPredict.
change(P,
'                  ", smoothSubmitted=" + std::to_string(delta(&Totals::smooth_submitted)) +',
'''                  ", smoothSubmitted=" + std::to_string(delta(&Totals::smooth_submitted)) +
                  ", researchExact=" + std::to_string(delta(&Totals::research_exact)) +
                  ", researchRepeat=" + std::to_string(delta(&Totals::research_repeated)) +
                  ", researchFallback=" + std::to_string(delta(&Totals::research_fallback)) +
                  ", researchNoProjection=" + std::to_string(delta(&Totals::research_no_projection)) +
                  ", researchOtherUnknown=" + std::to_string(delta(&Totals::research_other_unknown)) +
                  ", researchGpuSeen=" + std::to_string(delta(&Totals::research_gpu_seen)) +
                  ", researchAnalysisSeen=" + std::to_string(delta(&Totals::research_analysis_seen)) +
                  ", researchDue=" + std::to_string(delta(&Totals::research_due_count)) +
                  ", researchGpuLateDue=" + std::to_string(delta(&Totals::research_gpu_not_ready_due)) +
                  ", researchAnalysisLateDue=" + std::to_string(delta(&Totals::research_analysis_not_ready_due)) +
                  ", researchGpuMarginP05P50=" + Percentiles(research_capture_margin_periods_, 0.05, 0.5) +
                  ", researchAnalysisMarginP05P50=" + Percentiles(research_analysis_margin_periods_, 0.05, 0.5) +''', "summary counters")

for path, text in files.items():
    path.write_text(text, encoding="utf-8", newline="")
print("Applied #21 instrumentation-only patch (research fence sampling opt-in)")

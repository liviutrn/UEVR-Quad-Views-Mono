#!/usr/bin/env python3
"""Opt-in Dynamic Smoothness patch for VectorXR 0.20.1 (8fffa72).
Apply AFTER vectorxr_mono/apply_vectorxr_mono.py from reviewed 96aebe7.
No mono detector, shader, stereo pose/FOV, Fixed or Auto semantic changes.
"""
from pathlib import Path
import shutil
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_vectorxr_dynamic_smooth.py <vectorxr checkout>")
root = Path(sys.argv[1])
here = Path(__file__).resolve().parent
files = {}

def load(rel):
    if rel not in files:
        files[rel] = (root / rel).read_text(encoding="utf-8-sig")
    return files[rel]

def replace(rel, old, new, label, expected=1):
    source = load(rel)
    count = source.count(old)
    if count != expected:
        raise SystemExit(f"Dynamic Smooth anchor mismatch {rel} [{label}]: {count}, expected {expected}")
    files[rel] = source.replace(old, new)

H = "layer/include/depthxr/framegen_presenter.h"
P = "layer/src/framegen/framegen_presenter.cpp"
CM = "layer/CMakeLists.txt"
shutil.copyfile(here / "dynamic_smooth.h", root / "layer/include/depthxr/dynamic_smooth.h")
shutil.copyfile(here / "dynamic_smooth_tests.cpp", root / "layer/tests/dynamic_smooth_tests.cpp")
replace(P, '#include "depthxr/framegen_presenter.h"\n',
        '#include "depthxr/framegen_presenter.h"\n#include "depthxr/dynamic_smooth.h"\n',
        "include helper")
replace(H, "    std::array<LeadRing, 5> lead_ring_{};",
        "    std::array<LeadRing, 7> lead_ring_{}; // index 2-6 for Dynamic 6x", "ring capacity")
replace(H, "    FrameGenDynamicPolicy dynamic_policy_;",
        """    FrameGenDynamicPolicy dynamic_policy_;
    std::uint32_t smooth_dynamic_max_{4}; // stock default
    std::uint32_t smooth_lead_reserve_{0}; // opt-in adaptive minimum, not pinned
    std::uint32_t smooth_min_lead_{0}; // floor enforced by the adaptive controller
    bool smooth_diagnostics_{false};
    Clock::time_point smooth_last_success_end_{};
    std::vector<double> smooth_end_gaps_ms_; // successful JIT RuntimeEnd return gaps, not scanout""",
        "config fields")
replace(H, "        std::uint64_t generated_distinct{0};",
        """        std::uint64_t generated_distinct{0};
        std::uint64_t smooth_interpolated{0}; // unique, true JIT interpolations
        std::uint64_t smooth_predicted{0}; // unique, JIT extrapolations
        std::uint64_t smooth_other{0}; // accepted JIT slots: copies/repeats/fallbacks/empty
        std::uint64_t smooth_submitted{0}; // all accepted JIT RuntimeEnd calls""",
        "diagnostic totals")
replace(P, "    const std::uint64_t research_reads = ResearchFileReads();",
        """    // Session-scoped; defaults preserve the reviewed build exactly.
    smooth_dynamic_max_ = 4;
    const auto max_setting = ReadResearchSwitch("VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX").value_or("");
    if (max_setting == "5") smooth_dynamic_max_ = 5;
    if (max_setting == "6") smooth_dynamic_max_ = 6;
    smooth_lead_reserve_ = 0;
    const auto reserve = ReadResearchSwitch("VECTORXR_FRAMEGEN_FLOW_LEAD_RESERVE").value_or("");
    if (reserve == "1" || reserve == "2" || reserve == "3" || reserve == "4")
        smooth_lead_reserve_ = static_cast<std::uint32_t>(reserve[0] - '0');
    smooth_diagnostics_ = ReadResearchSwitch("VECTORXR_FRAMEGEN_FLOW_DIAGNOSTICS") == "1";
    smooth_min_lead_ = 0;
    smooth_last_success_end_ = Clock::time_point{};
    smooth_end_gaps_ms_.clear();
    if (logger_ && (smooth_dynamic_max_ != 4 || smooth_lead_reserve_ || smooth_diagnostics_)) {
        logger_->Info("Frame Generation Dynamic Smooth: max=" + std::to_string(smooth_dynamic_max_) +
                      ", reserve=" + std::to_string(smooth_lead_reserve_) +
                      ", diagnostics=" + std::to_string(smooth_diagnostics_) + ".");
    }
    const std::uint64_t research_reads = ResearchFileReads();""",
        "settings")
replace(P, "    return static_cast<std::uint32_t>(std::clamp(std::lround(dynamic_interval_slots_), 2l, 4l));",
        "    return dynamic_smooth::Slots(dynamic_interval_slots_, smooth_dynamic_max_);", "dynamic ceiling")
replace(P, "    if (!RingCeilingLocked() || multiplier > 4 || !jit_) {",
        "    if (!RingCeilingLocked() || multiplier >= lead_ring_.size() || !jit_) {", "lead cap indexing")
replace(P, "    if (multiplier > 4 || !DynamicLocked()) {",
        "    if (multiplier >= lead_ring_.size() || !DynamicLocked()) {", "ring expiry")
replace(P, "                        multiplier <= 4 && !late_write;",
        "                        multiplier < lead_ring_.size() && !late_write;", "ring short")
replace(P, "        !(lead_probe_->ring && multiplier <= 4 && RingJudgedLocked(lead_ring_[multiplier], now))) {",
        "        !(lead_probe_->ring && multiplier < lead_ring_.size() && RingJudgedLocked(lead_ring_[multiplier], now))) {",
        "lead probe ring")
# Only the opt-in floor is new; the stock controller remains unchanged.
replace(P, """    if (lead_policy_.pinned_lead) {
        return; // tests: the lead stays where it was pinned
    }
    const auto now = Clock::now();""",
        """    if (lead_policy_.pinned_lead) {
        return; // tests: the lead stays where it was pinned
    }
    const std::uint32_t smooth_minimum =
        smooth_lead_reserve_ && jit_ && jit_interpolate_ && DynamicLocked()
            ? std::max(1u, std::min(smooth_min_lead_, LeadCapLocked(multiplier)))
            : 1u;
    const auto now = Clock::now();""", "controller floor")
replace(P, "if (step_down && lead_slots_ > 1 &&",
        "if (step_down && dynamic_smooth::CanProbeDown(lead_slots_, smooth_minimum) &&",
        "prevent spare probe below reserve")
replace(P, "    if (lead_probe_ || lead_slots_ <= 1) {",
        "    if (lead_probe_ || !dynamic_smooth::CanProbeDown(lead_slots_, smooth_minimum)) {",
        "prevent calm probe below reserve")
replace(P, """    if (lead_slots_ > cap) {
        ClampLeadLocked(cap);
    }
    // Predict the first slot the frame will really reach.""",
        """    if (lead_slots_ > cap) {
        ClampLeadLocked(cap);
    }
    // Only Dynamic / JIT / Interpolate gets the opt-in extra reserve.
    // Enforce the minimum in the controller as well, so its down-probe cannot
    // repeatedly be undone on the very next wait (resetting its history).
    smooth_min_lead_ = 0;
    if (dynamic && interpolate_jit && smooth_lead_reserve_ > 0) {
        const double interval = dynamic_interval_slots_ > 0.0
                                    ? dynamic_interval_slots_ * period_ms : app_latency_ms_;
        const auto floor = dynamic_smooth::LeadFloor(
            app_latency_ms_, interval, period_ms, smooth_lead_reserve_, cap);
        smooth_min_lead_ = floor;
        if (lead_slots_ < floor) {
            lead_slots_ = floor;
            lead_probe_.reset();
            ClearLeadHistoryLocked();
            lead_calm_since_ = Clock::now();
        }
    }
    // Predict the first slot the frame will really reach.""",
        "extra adaptive lead")
# Successful JIT RuntimeEnd is recorded at the actual JIT submission site,
# not in NoteSubmissionLocked (which also handles non-JIT and rejected calls).
replace(P, """            if (XR_SUCCEEDED(result) && submit) {
                result = RuntimeEnd(calls, session, &end_info, true);
            }
            submit_lock.unlock();
            lock.lock();
            if (!submit) {""",
        """            if (XR_SUCCEEDED(result) && submit) {
                result = RuntimeEnd(calls, session, &end_info, true);
            }
            // Sample only a successful JIT runtime submission, immediately
            // after RuntimeEnd, not after re-acquiring the presenter lock.
            const auto smooth_runtime_return =
                smooth_diagnostics_ && submit && XR_SUCCEEDED(result) ? Clock::now() : Clock::time_point{};
            submit_lock.unlock();
            lock.lock();
            if (!submit) {""", "capture successful return")
replace(P, """                const bool moved = distinct && written && !write.exact;
                generated_ += moved ? 1 : 0;
                NoteSubmissionLocked(distinct, moved);""",
        """                const bool moved = distinct && written && !write.exact;
                if (smooth_diagnostics_ && XR_SUCCEEDED(result)) {
                    ++totals_.smooth_submitted;
                    switch (dynamic_smooth::ClassifyJit(true, path, distinct, written, write.exact,
                                  choice.mode == FrameGenSynthesisMode::kInterpolate)) {
                    case dynamic_smooth::JitKind::kInterpolate:
                        ++totals_.smooth_interpolated; break;
                    case dynamic_smooth::JitKind::kPredict:
                        ++totals_.smooth_predicted; break;
                    default:
                        ++totals_.smooth_other; break;
                    }
                    if (smooth_last_success_end_ != Clock::time_point{})
                        AddSample(smooth_end_gaps_ms_, Milliseconds(smooth_runtime_return -
                                      smooth_last_success_end_), kMaxFrameSamples);
                    smooth_last_success_end_ = smooth_runtime_return;
                }
                generated_ += moved ? 1 : 0;
                NoteSubmissionLocked(distinct, moved);""", "count successful submission")
replace(P, '            ")" + ", copiesSkipped=" + std::to_string(delta(&Totals::copies_skipped)) +',
        """            ")" +
            (smooth_diagnostics_
                ? ", smoothInterp=" + std::to_string(delta(&Totals::smooth_interpolated)) +
                  ", smoothPredict=" + std::to_string(delta(&Totals::smooth_predicted)) +
                  ", smoothOther=" + std::to_string(delta(&Totals::smooth_other)) +
                  ", smoothSubmitted=" + std::to_string(delta(&Totals::smooth_submitted)) +
                  ", smoothEndGapMs=" + Percentiles(smooth_end_gaps_ms_, 0.5, 0.95)
                : std::string()) +
            ", copiesSkipped=" + std::to_string(delta(&Totals::copies_skipped)) +""",
        "30 second summary")
replace(P, "    ring_short_write_ms_.clear();\n",
        "    ring_short_write_ms_.clear();\n    smooth_end_gaps_ms_.clear();\n",
        "clear samples at start and summary", expected=2)
replace(CM, "        set_tests_properties(vectorxr_mono_framegen_tests PROPERTIES TIMEOUT 10)\n",
        """        set_tests_properties(vectorxr_mono_framegen_tests PROPERTIES TIMEOUT 10)
        add_executable(vectorxr_dynamic_smooth_tests tests/dynamic_smooth_tests.cpp)
        target_include_directories(vectorxr_dynamic_smooth_tests PRIVATE include)
        target_compile_features(vectorxr_dynamic_smooth_tests PRIVATE cxx_std_20)
        add_test(NAME vectorxr_dynamic_smooth_tests COMMAND vectorxr_dynamic_smooth_tests)
        set_tests_properties(vectorxr_dynamic_smooth_tests PROPERTIES TIMEOUT 10)
""", "test registration")
for path, source in files.items():
    (root / path).write_text(source, encoding="utf-8", newline="")
print("Applied Dynamic Smoothness patch:", ", ".join(sorted(files)))

#!/usr/bin/env python3
"""Dynamic Smoothness with default-on diagnostic summaries for VectorXR 0.20.1 (8fffa72).
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
PT = "layer/tests/framegen_presenter_tests.cpp"
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
    std::chrono::steady_clock::time_point smooth_ring_backoff_until_{}; // reserve disabled after history failure
    bool smooth_diagnostics_{true}; // audit build: enabled unless explicitly disabled
    std::chrono::steady_clock::time_point smooth_last_success_end_{};
    XrTime smooth_last_success_target_{0};
    std::uint64_t smooth_last_interp_pair_{0};
    float smooth_last_interp_fraction_{0.0f};
    XrTime smooth_last_interp_target_{0};
    XrTime smooth_last_content_{0}; // inferred shown content time, not scanout
    std::vector<double> smooth_end_gaps_ms_; // successful JIT end-return gaps
    std::vector<double> smooth_target_gaps_ms_; // requested XrTime gaps
    std::vector<double> smooth_submit_late_ms_; // positive scheduler lateness
    std::vector<double> smooth_motion_err_ms_; // proxy content-time cadence errors""",
        "config fields")
replace(H, "        std::uint64_t generated_distinct{0};",
        """        std::uint64_t generated_distinct{0};
        std::uint64_t smooth_interpolated{0}; // unique, true JIT interpolations
        std::uint64_t smooth_predicted{0}; // unique, JIT extrapolations
        std::uint64_t smooth_other{0}; // accepted JIT slots: copies/repeats/fallbacks/empty
        std::uint64_t smooth_submitted{0}; // all accepted JIT RuntimeEnd calls
        std::uint64_t smooth_covers{0}; // predicted with cover enabled
        std::uint64_t smooth_stale{0}; // used older frame motion
        std::uint64_t smooth_grid_missing{0}; // inferred missing target grid slots
        std::uint64_t smooth_target_regressed{0}; // nonmonotonic target times
        std::uint64_t smooth_late_half{0}; // CPU submit start > half refresh after schedule
        std::uint64_t smooth_interp_pairs{0}; // observed interpolated real-frame pairs
        std::uint64_t smooth_interp_rewinds{0}; // nonincreasing fractions in pair
        std::uint64_t smooth_interp_gaps{0}; // >1.5 refresh gaps within pair
        std::uint64_t smooth_reserve_ups{0}; // low measured slack increased lead
        std::uint64_t smooth_ring_backoffs{0}; // history failure disabled reserve
        std::uint64_t smooth_pauses{0}; // accepted target gap exceeded pause limit
        std::uint64_t smooth_freezes{0}; // inferred same-content refreshes
        std::uint64_t smooth_jumps{0}; // inferred content-time jumps
        std::uint64_t smooth_rewinds{0}; // inferred content-time rewinds""",
        "diagnostic totals")
replace(P, "    const std::uint64_t research_reads = ResearchFileReads();",
        """    // Session-scoped timing switches remain stock-off; audit telemetry defaults on.
    smooth_dynamic_max_ = 4;
    const auto max_setting = ReadResearchSwitch("VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX").value_or("");
    if (max_setting == "5") smooth_dynamic_max_ = 5;
    if (max_setting == "6") smooth_dynamic_max_ = 6;
    smooth_lead_reserve_ = 0;
    const auto reserve = ReadResearchSwitch("VECTORXR_FRAMEGEN_FLOW_LEAD_RESERVE").value_or("");
    if (reserve == "1" || reserve == "2" || reserve == "3" || reserve == "4")
        smooth_lead_reserve_ = static_cast<std::uint32_t>(reserve[0] - '0');
    // No change to frame timing with diagnostics enabled. Explicit =0 opts out.
    smooth_diagnostics_ = ReadResearchSwitch("VECTORXR_FRAMEGEN_FLOW_DIAGNOSTICS") != "0";
    smooth_ring_backoff_until_ = Clock::time_point{};
    smooth_last_success_end_ = Clock::time_point{};
    smooth_last_success_target_ = 0;
    smooth_last_interp_pair_ = 0;
    smooth_last_interp_fraction_ = 0.0f;
    smooth_last_interp_target_ = 0;
    smooth_last_content_ = 0;
    smooth_end_gaps_ms_.clear();
    smooth_target_gaps_ms_.clear();
    smooth_submit_late_ms_.clear();
    smooth_motion_err_ms_.clear();
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
# Evidence-based reserve: stock controller scoring and probes are unchanged when reserve=0.
replace(P, """    if (lead_calm_since_ == Clock::time_point{}) {
        lead_calm_since_ = now;
    }""",
        """    if (lead_calm_since_ == Clock::time_point{}) {
        lead_calm_since_ = now;
    }
    // Only Dynamic / JIT / Interpolate with measured slack: no formula floor.
    const std::uint32_t smooth_reserve =
        smooth_lead_reserve_ && jit_ && jit_interpolate_ && DynamicLocked() && now >= smooth_ring_backoff_until_
            ? smooth_lead_reserve_ : 0u;""", "reserve activation")
replace(P, """        const bool spare = !late && slack_ms && *slack_ms > period_ms * 1.1;
        lead_history_.push_back(late ? 1 : spare ? 2 : 0);""",
        """        const bool spare = !late && slack_ms && *slack_ms > period_ms * 1.1;
        // Keep stock scoring exactly when reserve is disabled.
        lead_history_.push_back(smooth_reserve
            ? dynamic_smooth::ScoreLead(late, slack_ms.has_value(), slack_ms.value_or(0.0), period_ms, smooth_reserve)
            : (late ? 1 : spare ? 2 : 0));""", "reserve lead scoring")
replace(P, "        if (judged && !repeated && step_up) {",
        """        // Raise by only one refresh when 3 of 10 measurements had less
        // spare slack than the requested reserve; no late frame required.
        if (smooth_reserve && !lead_probe_ && !step_up && !at_ceiling && lead_slots_ < cap &&
            count(dynamic_smooth::kLeadThin) >= 3) {
            ++lead_slots_;
            ++totals_.smooth_reserve_ups;
            ClearLeadHistoryLocked();
            lead_calm_since_ = now;
            return;
        }
        if (judged && !repeated && step_up) {""", "reserve one-slot up")
replace(P, "    if (now - lead_calm_since_ < CalmProbeWaitLocked()) {",
        """    // Measured reserve uses only spare-time evidence to step down.
    // Unmeasurable slack eventually allows a rare stock probe.
    if (smooth_reserve &&
        (std::count(lead_history_.begin(), lead_history_.end(), dynamic_smooth::kLeadUnknown) < 8 ||
         now - lead_calm_since_ < lead_policy_.explore_max)) {
        return;
    }
    if (now - lead_calm_since_ < CalmProbeWaitLocked()) {""", "avoid blind reserve probes")
replace(P, "            totals_.ring_exhausted += write.ring_exhausted ? 1 : 0;",
        """            totals_.ring_exhausted += write.ring_exhausted ? 1 : 0;
            // Prevent extra reserve escalation while the history ring is
            // insufficient; stock adaptive lead control stays in charge.
            if (smooth_lead_reserve_ && (write.ring_exhausted || write.ring_short)) {
                const auto now = Clock::now();
                if (now >= smooth_ring_backoff_until_) ++totals_.smooth_ring_backoffs;
                smooth_ring_backoff_until_ = now + std::chrono::seconds(120);
            }""", "ring backoff")
replace(P, """    jit_frames_.clear();
    jit_shown_.reset();""",
        """    jit_frames_.clear();
    // Restart = new pacing timeline; do not bridge loading screens, standby,
    // or compositor restarts when evaluating real-time cadence.
    smooth_last_success_end_ = Clock::time_point{};
    smooth_last_success_target_ = 0;
    smooth_last_interp_pair_ = 0;
    smooth_last_interp_fraction_ = 0.0f;
    smooth_last_interp_target_ = 0;
    smooth_last_content_ = 0;
    smooth_ring_backoff_until_ = Clock::time_point{};
    jit_shown_.reset();""", "restart telemetry reset")

# Summary percentile helper: only runs at the 30-second summary.
replace(P, "// \"lead:frames\" for each lead told in a summary window, \"-\" when none.",
        """std::string SmoothP99(std::vector<double> values) {
    if (values.empty()) return "-";
    const std::size_t index = std::min(values.size() - 1,
        static_cast<std::size_t>(0.99 * static_cast<double>(values.size())));
    std::nth_element(values.begin(), values.begin() + static_cast<std::ptrdiff_t>(index), values.end());
    return Number(values[index], 1);
}

// "lead:frames" for each lead told in a summary window, "-" when none.""",
        "p99 summary helper")

# Successful JIT RuntimeEnd is recorded at the actual JIT submission site,
# not in NoteSubmissionLocked (which also handles non-JIT and rejected calls).
replace(P, """            // Nothing current to show: the frame is begun, not ended, so the
            // runtime shows its last frame again (the next begin discards it).
            XrResult result = RuntimeBegin(calls, session, &begin_info);""",
        """            // Nothing current to show: the frame is begun, not ended, so the
            // runtime shows its last frame again (the next begin discards it).
            const auto smooth_submit_begin = smooth_diagnostics_ ? Clock::now() : Clock::time_point{};
            XrResult result = RuntimeBegin(calls, session, &begin_info);""",
        "JIT submit start timer")
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
                    // A compositor restart, loading pause or non-rendered slot
                    // must not be interpreted as missed pacing or a huge jump.
                    const XrDuration target_gap = smooth_last_success_target_ ? time - smooth_last_success_target_ : 0;
                    const bool continuous = target_gap > 0 && target_gap <= PauseLimitLocked() && path != 1;
                    if (!continuous) smooth_last_interp_pair_ = 0;
                    if (smooth_last_success_target_ && target_gap > PauseLimitLocked())
                        ++totals_.smooth_pauses;
                    if (smooth_last_success_target_ && target_gap <= 0)
                        ++totals_.smooth_target_regressed;
                    const auto kind = dynamic_smooth::ClassifyJit(
                        true, path, distinct, written, write.exact,
                        choice.mode == FrameGenSynthesisMode::kInterpolate);
                    switch (kind) {
                    case dynamic_smooth::JitKind::kInterpolate:
                        ++totals_.smooth_interpolated;
                        if (source && source->id != smooth_last_interp_pair_) {
                            smooth_last_interp_pair_ = source->id;
                            smooth_last_interp_fraction_ = choice.fraction;
                            smooth_last_interp_target_ = time;
                            ++totals_.smooth_interp_pairs;
                        } else if (source) {
                            if (choice.fraction <= smooth_last_interp_fraction_ + 0.0001f)
                                ++totals_.smooth_interp_rewinds;
                            if (continuous && period > 0 && time - smooth_last_interp_target_ > period + period / 2)
                                ++totals_.smooth_interp_gaps;
                            smooth_last_interp_fraction_ = choice.fraction;
                            smooth_last_interp_target_ = time;
                        }
                        break;
                    case dynamic_smooth::JitKind::kPredict:
                        ++totals_.smooth_predicted;
                        totals_.smooth_covers += (choice.cover || write.motion_late) ? 1 : 0;
                        totals_.smooth_stale += write.stale ? 1 : 0;
                        break;
                    default:
                        ++totals_.smooth_other; break;
                    }
                    if (continuous && smooth_last_success_end_ != Clock::time_point{})
                        AddSample(smooth_end_gaps_ms_, Milliseconds(smooth_runtime_return -
                                      smooth_last_success_end_), kMaxFrameSamples);
                    smooth_last_success_end_ = smooth_runtime_return;
                    if (continuous && period > 0) {
                        AddSample(smooth_target_gaps_ms_, static_cast<double>(target_gap) / 1e6, kMaxFrameSamples);
                        totals_.smooth_grid_missing += dynamic_smooth::MissingGridSlots(target_gap, period);
                    }
                    smooth_last_success_target_ = time;
                    // Inferred content time is a timeline proxy, not a visual
                    // motion/ghosting or actual SteamVR scanout measurement.
                    XrTime shown = smooth_last_content_; // hold paths 6,8
                    if ((path == 3 || path == 4) && source) {
                        shown = dynamic_smooth::ContentTime(
                            source->previous_time, source->time, choice.fraction,
                            choice.mode == FrameGenSynthesisMode::kInterpolate, write.exact);
                    } else if (path == 2 || path == 5 || path == 7) {
                        shown = jit_content_time_;
                    }
                    if (continuous && period > 0 && smooth_last_content_ != 0 && shown != 0) {
                        const XrDuration step = shown - smooth_last_content_;
                        AddSample(smooth_motion_err_ms_, std::abs(static_cast<double>(step) -
                                  static_cast<double>(target_gap)) / 1e6, kMaxFrameSamples);
                        switch (dynamic_smooth::ClassifyMotionStep(step, target_gap, period)) {
                        case dynamic_smooth::MotionStep::kRewind: ++totals_.smooth_rewinds; break;
                        case dynamic_smooth::MotionStep::kFreeze: ++totals_.smooth_freezes; break;
                        case dynamic_smooth::MotionStep::kJump: ++totals_.smooth_jumps; break;
                        default: break;
                        }
                    }
                    smooth_last_content_ = (path == 1) ? 0 : shown;
                    const double late_ms = std::max(0.0, Milliseconds(smooth_submit_begin - submit_at));
                    AddSample(smooth_submit_late_ms_, late_ms, kMaxFrameSamples);
                    if (period > 0 && late_ms > static_cast<double>(period) / 2e6)
                        ++totals_.smooth_late_half;
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
                  ", smoothCover=" + std::to_string(delta(&Totals::smooth_covers)) +
                  ", smoothStale=" + std::to_string(delta(&Totals::smooth_stale)) +
                  ", smoothMissedGrid=" + std::to_string(delta(&Totals::smooth_grid_missing)) +
                  ", smoothTargetRegress=" + std::to_string(delta(&Totals::smooth_target_regressed)) +
                  ", smoothSubmitLateHalf=" + std::to_string(delta(&Totals::smooth_late_half)) +
                  ", smoothPairs=" + std::to_string(delta(&Totals::smooth_interp_pairs)) +
                  ", smoothPairRewind=" + std::to_string(delta(&Totals::smooth_interp_rewinds)) +
                  ", smoothPairGap=" + std::to_string(delta(&Totals::smooth_interp_gaps)) +
                  ", smoothReserveUps=" + std::to_string(delta(&Totals::smooth_reserve_ups)) +
                  ", smoothRingBackoffs=" + std::to_string(delta(&Totals::smooth_ring_backoffs)) +
                  ", smoothPauses=" + std::to_string(delta(&Totals::smooth_pauses)) +
                  ", smoothFreeze=" + std::to_string(delta(&Totals::smooth_freezes)) +
                  ", smoothJump=" + std::to_string(delta(&Totals::smooth_jumps)) +
                  ", smoothRewind=" + std::to_string(delta(&Totals::smooth_rewinds)) +
                  ", smoothMotionErrMsP50P95=" + Percentiles(smooth_motion_err_ms_, 0.5, 0.95) +
                  ", smoothMotionErrMsP99=" + SmoothP99(smooth_motion_err_ms_) +
                  ", smoothEndGapMsP50P95=" + Percentiles(smooth_end_gaps_ms_, 0.5, 0.95) +
                  ", smoothEndGapMsP99=" + SmoothP99(smooth_end_gaps_ms_) +
                  ", smoothTargetGapMsP50P95=" + Percentiles(smooth_target_gaps_ms_, 0.5, 0.95) +
                  ", smoothTargetGapMsP99=" + SmoothP99(smooth_target_gaps_ms_) +
                  ", smoothSubmitLateMsP50P95=" + Percentiles(smooth_submit_late_ms_, 0.5, 0.95) +
                  ", smoothSubmitLateMsP99=" + SmoothP99(smooth_submit_late_ms_)
                : std::string()) +
            ", copiesSkipped=" + std::to_string(delta(&Totals::copies_skipped)) +""",
        "30 second summary")
replace(P, "    ring_short_write_ms_.clear();\n",
        "    ring_short_write_ms_.clear();\n    smooth_end_gaps_ms_.clear();\n    smooth_target_gaps_ms_.clear();\n    smooth_submit_late_ms_.clear();\n    smooth_motion_err_ms_.clear();\n",
        "clear samples at start and summary", expected=2)

# Exercise actual Dynamic/JIT integration using upstream's fake OpenXR runtime.
# The slow cadence probes what happens around 5.5 refreshes per real frame.
replace(PT, "// Repeats the one-interval clamp of extrapolation predicts between real frames shown at `times`:",
        """// Research regression: the presenter must still submit correctly when the
// application takes roughly 5.5 simulated 90-Hz refreshes per real frame.
void TestJitDynamicInterpolationSlow() {
    for (const bool six : {false, true}) {
        _putenv_s("VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX", six ? "6" : "");
        FrameGenPresenter presenter;
        GpuLog gpu;
        Runtime runtime;
        runtime.paced = true;
        std::unique_ptr<App> owned;
        App* app = nullptr;
        StartJit(presenter, gpu, FrameGenSynthesisMode::kInterpolate,
                 FrameGenMultiplier::kDynamic, app, runtime, owned);
        _putenv_s("VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX", "");
        app->eye_speed = 0.5;
        app->end_offset_periods = 1;
        RunPipelined(*app, 1000ms, 18ms, 61ms);
        const std::size_t first = runtime.Submissions();
        const auto started = std::chrono::steady_clock::now();
        std::chrono::steady_clock::duration gap{};
        const int frames = RunPipelined(*app, 1600ms, 18ms, 61ms, {}, &gap);
        const double elapsed = Seconds(std::chrono::steady_clock::now() - started);
        const FrameGenStatus status = presenter.Status();
        const auto log = runtime.Snapshot();
        const double rate = static_cast<double>(log.size() - first) / std::max(elapsed, 0.001);
        const double timeline = TimelineShare(runtime, first, 8, app->eye_speed);
        std::cerr << "  slow Dynamic " << (six ? "max6" : "max4") << ": app "
                  << frames / std::max(elapsed, 0.001) << " fps, output " << rate
                  << " fps, timeline " << timeline << ", lead " << status.lead_slots
                  << ", distinct " << status.distinct_fps << std::endl;
        Check(status.threaded && status.dynamic && !status.standby,
              "slow Dynamic: engaged JIT presenter");
        Check(log.size() > first + 40 && rate > 65.0, "slow Dynamic: output continues each refresh");
        Check(timeline > 0.80, "slow Dynamic: most images follow content timeline");
        Check(gap < 250ms, "slow Dynamic: no prolonged app stall");
        CheckOrderedTimes(log, "slow Dynamic");
        presenter.Stop();
        Check(!runtime.ordering_violation && !g_release_violation,
              "slow Dynamic: runtime and swapchain ordering");
    }
}

// Jittered-source smoke: reserve must never break the frame submission path.
// Precise effectiveness requires measured headset logs, not this fake GPU.
void TestJitDynamicSlackReserve() {
    for (const bool reserve : {false, true}) {
        _putenv_s("VECTORXR_FRAMEGEN_FLOW_LEAD_RESERVE", reserve ? "2" : "");
        FrameGenPresenter presenter;
        GpuLog gpu;
        Runtime runtime;
        runtime.paced = true;
        std::unique_ptr<App> owned;
        App* app = nullptr;
        StartJit(presenter, gpu, FrameGenSynthesisMode::kInterpolate,
                 FrameGenMultiplier::kDynamic, app, runtime, owned);
        _putenv_s("VECTORXR_FRAMEGEN_FLOW_LEAD_RESERVE", "");
        app->eye_speed = 0.5;
        app->end_offset_periods = 1;
        RunPipelined(*app, 1000ms, 16ms, 32ms);
        const auto first = runtime.Submissions();
        const auto started = std::chrono::steady_clock::now();
        RunPipelined(*app, 2000ms, 16ms, 32ms,
                     [](int i, const XrFrameState&) {
                         if (i % 9 == 7) std::this_thread::sleep_for(16ms);
                     });
        const auto status = presenter.Status();
        const auto log = runtime.Snapshot();
        const double rate = static_cast<double>(log.size() - first) /
            std::max(Seconds(std::chrono::steady_clock::now() - started), 0.001);
        std::cerr << "  jittered Dynamic reserve " << (reserve ? "2" : "0")
                  << ": output " << rate << ", lead " << status.lead_slots
                  << ", late " << status.late_cpu << "/" << status.late_gpu << std::endl;
        Check(status.threaded && status.dynamic && !status.standby,
              "slack reserve: presenter remains engaged");
        Check(rate > 65.0, "slack reserve: frame submissions continue");
        Check(status.lead_slots >= 1 && status.lead_slots <= 24,
              "slack reserve: lead remains bounded");
        CheckOrderedTimes(log, "slack reserve");
        presenter.Stop();
        Check(!runtime.ordering_violation && !g_release_violation,
              "slack reserve: runtime and swapchain ordering");
    }
}

// Repeats the one-interval clamp of extrapolation predicts between real frames shown at `times`:""",
        "fake-runtime Dynamic slow and jitter tests")
replace(PT, "    RUN(TestJitDynamicInterpolation);",
        """    RUN(TestJitDynamicInterpolation);
    RUN(TestJitDynamicInterpolationSlow);
    RUN(TestJitDynamicSlackReserve);""",
        "register fake-runtime regression tests")

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

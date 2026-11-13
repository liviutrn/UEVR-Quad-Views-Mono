#!/usr/bin/env python3
"""Optional continuous release-phase clock and Dynamic cap hysteresis for #21.

Applied after dynamic smooth and #21 telemetry. Both behavioral experiments
default OFF. Production eye-pose interpolation and exact-copy decisions keep
the original grid fraction. Fails closed on any upstream anchor mismatch.
"""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
H=root/"layer/include/depthxr/framegen_presenter.h"
P=root/"layer/src/framegen/framegen_presenter.cpp"
files={H:H.read_text(encoding="utf-8"),P:P.read_text(encoding="utf-8")}
def change(path,old,new,label,expected=1):
    s=files[path]
    n=s.count(old)
    if n!=expected:
        raise SystemExit(f"Clock21 anchor {label}: {n} != {expected}; no files written")
    files[path]=s.replace(old,new)

change(H,"    bool research21_{false}; // extra GPU fence sampling; OPT IN only",
"""    bool research21_{false}; // extra GPU fence sampling; OPT IN only
    bool research_content_clock_{false}; // opt-in world fraction, not pose
    bool research_cap_hysteresis_{false}; // opt-in Dynamic step hysteresis
    mutable std::uint32_t research_dynamic_slots_{0};
    XrDuration research_phase_mean_ns_{0};
    XrTime research_last_target_{0};
    bool research_phase_mean_valid_{false};
    std::uint32_t research_cadence_lock_{0};""","clock policy members")
change(H,"        XrTime time{0};            // the display time it was rendered for\n        XrTime previous_time{0};",
"""        XrTime time{0};            // the display time it was rendered for
        XrTime world_content_time{0}; // optional release-phase clock label
        XrTime previous_world_time{0}; // previous real scene timestamp
        XrTime previous_time{0};""","JitFrame content labels")
change(H,"        XrTime target_time{0};         // the display time of target_slot",
"""        XrTime target_time{0};         // the display time of target_slot
        XrTime world_content_time{0};  // experimental phase-continuous label""","ThreadedFrame timestamp")
change(H,"        float fraction{1.0f};\n        bool cover{false};",
"""        float fraction{1.0f};
        float pose_fraction{1.0f}; // stock grid fraction for eye-position shift and exact gate
        bool cover{false};""","choice pose fraction")
change(P,
'    research21_ = ReadResearchSwitch("VECTORXR_FRAMEGEN_RESEARCH21") == "1";',
'''    research21_ = ReadResearchSwitch("VECTORXR_FRAMEGEN_RESEARCH21") == "1";
    research_content_clock_ = ReadResearchSwitch("VECTORXR_CONTENT_CLOCK21") == "1";
    research_cap_hysteresis_ = ReadResearchSwitch("VECTORXR_MAX6_HYSTERESIS21") == "1";
    research_dynamic_slots_ = 0;
    research_phase_mean_ns_ = 0;
    research_last_target_ = 0;
    research_phase_mean_valid_ = false;
    const auto lock21 = ReadResearchSwitch("VECTORXR_CADENCE_LOCK21");
    research_cadence_lock_ = lock21 == "5" ? 5u : (lock21 == "6" ? 6u : 0u);
    if (logger_) {
        logger_->Info("VectorXR #21 mode: " +
                      std::string(research_cadence_lock_ ? "D locked rhythm" :
                                  research_content_clock_ ? "B release-phase content clock" :
                                  research_cap_hysteresis_ ? "C max6 cap hysteresis" : "A stock content clock") +
                      ", contentClock=" + (research_content_clock_ ? "on" : "off") +
                      ", hysteresis=" + (research_cap_hysteresis_ ? "on" : "off") +
                      ", cadence=" + std::to_string(research_cadence_lock_) +
                      ", contentProxyComparable=" + (research_content_clock_ ? "no" : "yes") +
                      ", max=" + std::to_string(smooth_dynamic_max_) +
                      ", reserve=" + std::to_string(smooth_lead_reserve_) +
                      ", gpuProbe=" + (research21_ ? "on" : "off") + ".");
    }''',"mode init log")
change(P,
"    return dynamic_smooth::Slots(dynamic_interval_slots_, smooth_dynamic_max_);",
"""    const auto nominal = dynamic_smooth::Slots(dynamic_interval_slots_, smooth_dynamic_max_);
    if (!research_cap_hysteresis_ || smooth_dynamic_max_ <= 4 || dynamic_interval_slots_ <= 0.0) return nominal;
    if (!research_dynamic_slots_) research_dynamic_slots_ = nominal;
    const double measured = dynamic_interval_slots_;
    if (measured > static_cast<double>(research_dynamic_slots_) + 0.75 &&
        research_dynamic_slots_ < smooth_dynamic_max_) ++research_dynamic_slots_;
    else if (measured < static_cast<double>(research_dynamic_slots_) - 0.75 &&
             research_dynamic_slots_ > 2) --research_dynamic_slots_;
    return research_dynamic_slots_;""","cap hysteresis decision")
change(P,
"""    frame.wait_return = Clock::now();
    last_returned_time_ = frame.predicted;""",
"""    frame.wait_return = Clock::now();
    // Both clocks remain in the same XrTime epoch. In mode B only, the
    // fractional release phase labels scene motion. Clamp to one period:
    // an exceptional GPU wait must not shift world-content time by frames.
    frame.world_content_time = frame.target_time;
    if (research_content_clock_ && phase_wall_ != Clock::time_point{} && period > 0) {
        const auto now_xr = phase_xr_ +
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                frame.wait_return - phase_wall_).count();
        const XrDuration phase = std::clamp<XrDuration>(
            now_xr - slot_time_, 0, period - 1);
        if (research_last_target_ &&
            (frame.target_time <= research_last_target_ ||
             frame.target_time - research_last_target_ > 12 * period)) {
            research_phase_mean_valid_ = false; // pause/restart: learn anew
        }
        research_last_target_ = frame.target_time;
        if (!research_phase_mean_valid_) {
            research_phase_mean_ns_ = phase;
            research_phase_mean_valid_ = true;
        } else {
            research_phase_mean_ns_ += (phase - research_phase_mean_ns_) / 30;
        }
        frame.world_content_time += phase;
    }
    last_returned_time_ = frame.predicted;""","release phase timestamp")
change(P,
"""    score.capture_mark = last_capture_mark_; // its views were released before its end
    score.scored = late;""",
"""    score.capture_mark = last_capture_mark_; // its views were released before its end
    score.world_content_time = frame.world_content_time;
    score.scored = late;""","copy clock into score")
change(P,
"""    jit.time = frame.app_time;
    jit.previous_time = analysis.synthesized ? previous_time : 0;""",
"""    jit.time = frame.app_time;
    jit.world_content_time = score.world_content_time;
    jit.previous_time = analysis.synthesized ? previous_time : 0;
    if (jit.previous_time && !jit_frames_.empty() &&
        jit_frames_.back().time == jit.previous_time)
        jit.previous_world_time = jit_frames_.back().world_content_time;""","JIT world times")
change(P,
"""            choice.fraction = FrameGenFraction(FrameGenSynthesisMode::kInterpolate, frame.time, next.time, time);""",
"""            choice.fraction = FrameGenFraction(FrameGenSynthesisMode::kInterpolate, frame.time, next.time, time);
            choice.pose_fraction = choice.fraction;
            // The content-only clock changes GPU motion interpolation, not
            // which real frame is selected or its original headset pose.
            if (research_content_clock_ && frame.world_content_time &&
                next.world_content_time > frame.world_content_time)
                choice.fraction = FrameGenFraction(FrameGenSynthesisMode::kInterpolate,
                    frame.world_content_time, next.world_content_time, time + research_phase_mean_ns_);""","interpolated content-only fraction")
change(P,
"""    choice.fraction = 0.0f;
    if (frame.previous_time && time > frame.time &&""",
"""    choice.fraction = 0.0f;
    choice.pose_fraction = 0.0f;
    if (frame.previous_time && time > frame.time &&""", "pose fraction zero for extrapolation")
change(P,
"""        choice.fraction =
            FrameGenFraction(FrameGenSynthesisMode::kExtrapolate, frame.previous_time, frame.time, time, frame.reach);
    }
    if (newest) {""",
"""        choice.fraction =
            FrameGenFraction(FrameGenSynthesisMode::kExtrapolate, frame.previous_time, frame.time, time, frame.reach);
        choice.pose_fraction = choice.fraction;
        if (research_content_clock_ && frame.world_content_time &&
            frame.previous_world_time > 0 &&
            frame.world_content_time > frame.previous_world_time) {
            choice.fraction = FrameGenFraction(FrameGenSynthesisMode::kExtrapolate,
                frame.previous_world_time, frame.world_content_time, time + research_phase_mean_ns_, frame.reach);
        }
    }
    if (newest) {""","extrapolated content-only fraction")
change(P,
"""    return frame.previous_time == 0 ||
           (choice.mode == FrameGenSynthesisMode::kExtrapolate ? choice.fraction <= 0.0f : choice.fraction >= 1.0f);""",
"""    return frame.previous_time == 0 ||
           (choice.mode == FrameGenSynthesisMode::kExtrapolate
                ? choice.pose_fraction <= 0.0f : choice.pose_fraction >= 1.0f);""","retain exact-copy gate")
change(P,
"""        unmoved.fraction = 1.0f;
        unmoved.cover = false;""",
"""        unmoved.fraction = 1.0f;
        unmoved.pose_fraction = 1.0f;
        unmoved.cover = false;""","exact fallback pose")
change(P,
"    const float eye_time = write.exact ? 0.0f : extrapolate ? choice.fraction : choice.fraction - 1.0f;",
"    const float eye_time = write.exact ? 0.0f : extrapolate ? choice.pose_fraction : choice.pose_fraction - 1.0f;",
"preserve view pose timing")
change(P,
"""            choice.fraction = std::min(choice.fraction, 1.0f);""",
"""            choice.fraction = std::min(choice.fraction, 1.0f);
            choice.pose_fraction = std::min(choice.pose_fraction, 1.0f);""",
"keep stale pose exactly stock with clock disabled")
change(P,
"""    const std::uint32_t cadence = dynamic ? 1 : multiplier;""",
"""    const std::uint32_t cadence =
        dynamic ? (research_cadence_lock_ ? research_cadence_lock_ : 1u) : multiplier;""",
"D: optional refresh-aligned game release cadence")
for path,s in files.items():
    path.write_text(s,encoding="utf-8",newline="")
print("Applied #21 content phase and Max6 hysteresis; both default OFF")

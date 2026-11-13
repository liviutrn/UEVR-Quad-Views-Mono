#!/usr/bin/env python3
"""Optional #21 per-real-frame joinable timestamp CSV.

Applied last to pinned VectorXR after clock and telemetry patchers.
Disabled unless VECTORXR_FRAMEGEN_RESEARCH21=1.
Never modifies source selection, GPU work, poses, or lead policy.
"""
from pathlib import Path
import shutil,sys
root=Path(sys.argv[1]).resolve()
here=Path(__file__).resolve().parent
cpp=root/"layer/src/framegen/framegen_presenter.cpp"
text=cpp.read_text(encoding="utf-8")
def replace(old,new,label):
    global text
    found=text.count(old)
    if found!=1: raise SystemExit(f"research #21 real trace anchor {label}: {found}, expected 1; unchanged")
    text=text.replace(old,new)
replace('#include "depthxr/dynamic_smooth.h"',
        '#include "depthxr/dynamic_smooth.h"\n#include "depthxr/ResearchTrace21.hpp"',
        "include")
replace("""    last_returned_time_ = frame.predicted;
    // For the summary:""",
"""    last_returned_time_ = frame.predicted;
    research_trace21::Sink().Record(research_trace21::kXrWait,
                                    frame.id, frame.lead, frame.predicted,
                                    frame.target_time, frame.world_content_time);
    // For the summary:""",
"real-frame wait")
replace("""    // Claimed in the layer's xrEndFrame (ClaimQuadFrame): its primary
    // projection holds the four source views.
    const bool claimed = frame.quad && quad && quad->route == FrameGenQuadRoute::kClaimed;""",
"""    // Claimed in the layer's xrEndFrame (ClaimQuadFrame): its primary
    // projection holds the four source views.
    research_trace21::Sink().Record(research_trace21::kXrRealEnd,
                                    frame.id, frame.lead, info.displayTime,
                                    frame.target_time, frame.world_content_time);
    const bool claimed = frame.quad && quad && quad->route == FrameGenQuadRoute::kClaimed;""",
"real-frame end")


# #21: One row for EVERY successfully scheduled compositor refresh,
# including begin-only holds (submit=false). This is an OpenXR runtime
# submission trace, NOT proof of physical headset scanout. The GPU fraction
# is valid only for paths 3/4 after a successful synthesis.
replace("""            if (XR_FAILED(result)) {
                PauseLocked("runtime rejected a frame from the presenter thread (""",
"""            if (research_trace21::Sink().Enabled() && XR_SUCCEEDED(result)) {
                const bool synthesized_now = (path == 3 || path == 4) && source && written;
                // When a fallback or repeat is shown, report the last shown
                // real-frame identity, not the unsubmitted current candidate.
                const std::uint64_t shown_id = synthesized_now
                    ? source->id
                    : (jit_shown_ ? std::get<0>(*jit_shown_) : 0);
                const auto shown_in_ring = find_kept(shown_id);
                const XrTime previous_time = synthesized_now
                    ? source->previous_time
                    : (shown_in_ring != jit_frames_.end() ? shown_in_ring->previous_time : 0);
                const auto previous = std::find_if(jit_frames_.begin(), jit_frames_.end(),
                    [&](const JitFrame& candidate) {
                        return previous_time && candidate.time == previous_time;
                    });
                const std::uint64_t previous_id =
                    previous != jit_frames_.end() ? previous->id : 0;
                const std::int64_t fraction_ppm = synthesized_now
                    ? static_cast<std::int64_t>(std::llround(
                        static_cast<double>(write.exact ? 1.0f : choice.fraction) * 1000000.0))
                    : -1; // Not a new GPU synthesis: no valid fraction.
                // aux bits: 0..7 path; 8 exact; 9 written; 10 distinct;
                // 11 xrEndFrame submitted; 12 rendered; 13 fraction-valid;
                // 14 generated; 15 cover; 16 unmeasured; 17 stale;
                // 18 motion-late; 19 source-known; 20 prev ID evicted;
                // 21 extrapolation (else interpolation, when fraction-valid).
                const auto bit = [](bool value, unsigned shift) -> std::int64_t {
                    return value ? (std::int64_t{1} << shift) : 0;
                };
                const std::int64_t classification =
                    (static_cast<std::int64_t>(path) & 0xff) |
                    bit(synthesized_now && write.exact, 8) |
                    bit(written, 9) |
                    bit(distinct, 10) |
                    bit(submit, 11) |
                    bit(rendered, 12) |
                    bit(synthesized_now, 13) |
                    bit(generated, 14) |
                    bit(choice.cover, 15) |
                    bit(write.unmeasured, 16) |
                    bit(write.stale, 17) |
                    bit(write.motion_late, 18) |
                    bit(shown_id != 0, 19) |
                    bit(previous_time != 0 && previous_id == 0, 20) |
                    bit(synthesized_now && choice.mode == FrameGenSynthesisMode::kExtrapolate, 21);
                // kind 7 schema: frame=actual shown source id,
                // secondary=previous id (0 if evicted), display_xr=refresh time,
                // pose_xr=GPU fraction*1e6 (or -1), aux=classification bits,
                // extra=previous real-frame XrTime (remains joinable after eviction).
                research_trace21::Sink().Record(research_trace21::kXrRefresh,
                    shown_id, previous_id, time, fraction_ppm, classification,
                    previous_time);
            }
            if (XR_FAILED(result)) {
                PauseLocked("runtime rejected a frame from the presenter thread (""",
"successful per-refresh output, actual GPU fraction and path")

# Flush only AFTER the compositor thread has been stopped. Calling it at
# Stop() entry could miss final compositor writes still in flight.
# Do not permanently stop the writer; runtime reinit in the same process
# must keep producing trace records.
replace("""    lock.unlock();
    {
        // Finish outstanding GPU work before the runtime frees the output""",
"""    lock.unlock();
    research_trace21::Sink().FlushNow();
    {
        // Finish outstanding GPU work before the runtime frees the output""",
"post-compositor session-end CSV flush")

out=root/"layer/include/depthxr/ResearchTrace21.hpp"
out.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(here/"ResearchTrace21.hpp",out)
cpp.write_text(text,encoding="utf-8",newline="")
print("VectorXR #21: optional bounded real-frame wait/end CSV (default OFF)")

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

out=root/"layer/include/depthxr/ResearchTrace21.hpp"
out.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(here/"ResearchTrace21.hpp",out)
cpp.write_text(text,encoding="utf-8",newline="")
print("VectorXR #21: optional bounded real-frame wait/end CSV (default OFF)")

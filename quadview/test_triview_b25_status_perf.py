#!/usr/bin/env python3
"""B25 generated-backend assertions, not only comparisons to overlay scripts."""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: test_triview_b25_status_perf.py BACKEND")
root=Path(sys.argv[1])
vr=(root/"src/mods/VR.cpp").read_text(encoding="utf-8")
xr=(root/"src/mods/vr/runtimes/OpenXR.cpp").read_text(encoding="utf-8")
hook=(root/"src/mods/vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
status=(root/"src/mods/vr/QuadViewStatus.hpp").read_text(encoding="utf-8")

def require(ok,msg):
    if not ok:
        raise AssertionError(msg)

for stale in [
    "Waiting for four engine view histories and main-family raster",
    "Four isolated native source renders completed; waiting for exact quartet RHI tails",
    "Four-view source registered before the renderer copies this family",
    "Waiting for both context offsets to capture one exact OpenXR pose frame",
]:
    require(stale not in vr+hook, "Routine flicker status still written: "+stale)
require('(void)vr->quadview_note_eye_pose(static_cast<uint32_t>(view_index));' in hook,
        "Important pose-side-effect lost")
require('note_quadview_xr_submit(quadview_pose_generation' in xr,
        "Fresh XR submission status was changed")
require('vr->set_quadview_status(quadview_holding ?' in xr,
        "XR success presentation path changed")
require('Stalled: no fresh XR submission for 1 second' in status,
        "Primary status stall detector missing")
require('if (!uevr::quadview::hook_trace_enabled()) return;' in hook,
        "Hook tracer still prepares records while disabled")
require('if (qv_trace_verbose) {' in hook and
        'if (!qv_trace_verbose) return;' in hook and
        'const auto qv_lock_start=qv_trace_verbose ?' in hook and
        'const auto qv_lock_acquired=qv_trace_verbose ?' in hook,
        "RHI profiler still works with verbose trace off")
require('hook_trace_enabled()?&native_trace:nullptr' in hook,
        "Optional native trace collector still always on")
require('std::scoped_lock _{vtable_mutex};' in hook,
        "RHI owner lock must not be removed")
for important in [
    "Could not select a distinct owned native source target",
    "Engine view/history did not match its frozen rectangle",
    "Tracked engine family command failed RHI tail validation",
]:
    require(important in vr+hook, "Actual failure warning missing: "+important)
print("B25 generated status/trace/XR and RHI ownership invariants: PASS")

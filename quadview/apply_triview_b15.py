#!/usr/bin/env python3
"""Tri-view B15: Recenter View / Set Standing Origin / Set Standing Height work in TriView.

Defect (source-read; HEADSET symptom 6 Nov: menu button AND keyboard key "do
nothing, at random", only in TriView, never in DuoView):
- Every "where is the head now" read (VR::get_transform(0) / get_position_unsafe)
  goes through OpenXR::get_current_view_space_location(), i.e. the pose ring slot
  pipeline_states[internal_frame_count % 6].
- ID7 renders its roles as separate renderer calls with their own frame numbers
  (canonical N, then N+1, N+2); Joey's BeginRenderingViewFamily hook sets
  internal_frame_count to each role frame. update_poses() locates a head pose only
  for N. With 3 frames per draw and 6 slots, the role slots are never refreshed,
  so between draws (where the UEVR menu, keys and gamepad recenter run, on the
  game-thread tick) the "current" pose could be minutes old. Recentering to that
  old head direction looks like "nothing happened" or leaves you diagonal.
- Joey's Native Fix / DuoView copy the pose into their second slot, so they never
  had this.
Fix: remember the newest frame update_poses located (under sync_assignment_mtx).
While the TriView renderer is active and the current frame is not that frame,
answer from the newest located frame (uevr::quadview::current_pose_frame). The
rendered image does not use this path at role time; other modes are unchanged.
Run after apply_triview_b14.py.
"""
from pathlib import Path
import sys

HPP = Path("src/mods/vr/runtimes/OpenXR.hpp")
CPP = Path("src/mods/vr/runtimes/OpenXR.cpp")


def once(text, old, new, what):
    if text.count(old) != 1:
        raise RuntimeError(f"B15 anchor ({what}) count {text.count(old)}")
    return text.replace(old, new, 1)


def header(text):
    text = once(text, '#include "../DuoViewFrame.hpp"\n',
        '#include "../DuoViewFrame.hpp"\n#include "../QuadViewGeometry.hpp"\n', "include")
    text = once(text,
        "    auto get_current_view_space_location() {\n"
        "        std::scoped_lock _{ this->sync_assignment_mtx };\n"
        "\n"
        "        return get_view_space_location(internal_frame_count);\n"
        "    }\n",
        "    auto get_current_view_space_location() {\n"
        "        std::scoped_lock _{ this->sync_assignment_mtx };\n"
        "\n"
        "        // Tri-view B15: role renders move internal_frame_count to frames that never get\n"
        "        // a located pose; recenter/origin/height must use the newest located head pose.\n"
        "        const auto frame = uevr::quadview::current_pose_frame(this->triview_pose_redirect,\n"
        "            this->triview_pose_located, internal_frame_count, this->triview_newest_pose_frame);\n"
        "        if (frame != internal_frame_count && this->pipeline_states[frame % QUEUE_SIZE].frame_count != frame) {\n"
        "            return this->triview_newest_pose_location;\n"
        "        }\n"
        "        return get_view_space_location(frame);\n"
        "    }\n"
        "\n"
        "    // Tri-view B15 (guarded by sync_assignment_mtx).\n"
        "    bool triview_pose_redirect{false};\n"
        "    bool triview_pose_located{false};\n"
        "    uint32_t triview_newest_pose_frame{0};\n"
        "    XrSpaceLocation triview_newest_pose_location{XR_TYPE_SPACE_LOCATION};\n",
        "current view-space location")
    return text


def source(text):
    return once(text,
        "    pipeline_state.view_space_location = this->view_space_location;\n"
        "\n"
        "    if (vr->is_quadview_renderer_active()) {\n"
        "        pipeline_state.frame_count=frame_count;\n",
        "    pipeline_state.view_space_location = this->view_space_location;\n"
        "\n"
        "    // Tri-view B15: newest frame with a located head pose (sync_assignment_mtx is held).\n"
        "    this->triview_pose_redirect = vr->is_quadview_renderer_active();\n"
        "    if ((this->view_space_location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT) != 0 &&\n"
        "        (!this->triview_pose_located || !uevr::quadview::pose_frame_newer(this->triview_newest_pose_frame, frame_count))) {\n"
        "        this->triview_pose_located = true;\n"
        "        this->triview_newest_pose_frame = frame_count;\n"
        "        this->triview_newest_pose_location = this->view_space_location;\n"
        "    }\n"
        "\n"
        "    if (vr->is_quadview_renderer_active()) {\n"
        "        pipeline_state.frame_count=frame_count;\n",
        "update_poses newest frame")


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit("Usage: apply_triview_b15.py <backend> [quadview-workspace]")
    root = Path(sys.argv[1])
    files = {root / HPP: header, root / CPP: source}
    out = {p: f(p.read_text(encoding="utf-8")) for p, f in files.items()}
    for p, t in out.items():
        p.write_text(t, encoding="utf-8")
    print("Tri-view B15: recenter/origin/height read the newest located head pose in TriView")


if __name__ == "__main__":
    main()

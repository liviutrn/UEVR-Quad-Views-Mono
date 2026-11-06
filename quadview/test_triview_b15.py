#!/usr/bin/env python3
"""Tri-view B15 source contracts on the GENERATED backend (run after apply_triview_b15.py).
Fails on B14: there the current head pose was always the current-frame ring slot."""
from pathlib import Path
import sys


def fail(msg):
    raise SystemExit(f"B15 contract: {msg}")


root = Path(sys.argv[1])
hpp = (root / "src/mods/vr/runtimes/OpenXR.hpp").read_text(encoding="utf-8")
cpp = (root / "src/mods/vr/runtimes/OpenXR.cpp").read_text(encoding="utf-8")
vr = (root / "src/mods/VR.cpp").read_text(encoding="utf-8")
fn = hpp[hpp.find("auto get_current_view_space_location() {"):]
fn = fn[:fn.find("\n    }\n")]
if "uevr::quadview::current_pose_frame(" not in fn or "sync_assignment_mtx" not in fn:
    fail("current head pose does not use the newest located frame in TriView")
if cpp.count("this->triview_newest_pose_frame = frame_count;") != 1:
    fail("update_poses does not record the newest located frame")
# Every recenter/origin/height path must read the head pose through that function.
for needle in ("void VR::recenter_view()", "void VR::recenter_horizon()"):
    body = vr[vr.find(needle):][:400]
    if "get_rotation(0)" not in body:
        fail(f"{needle} no longer reads get_rotation(0)")
tr = vr[vr.find("Matrix4x4f VR::get_transform(uint32_t index, bool grip) const {"):][:2200]
if "m_openxr->get_current_view_space_location()" not in tr:
    fail("VR::get_transform(0) bypasses get_current_view_space_location")
print("B15 source contracts: ok")

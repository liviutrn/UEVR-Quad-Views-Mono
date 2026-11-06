#!/usr/bin/env python3
"""Tri-view B14 source contracts on the GENERATED backend (run after apply_triview_b14.py).

Fails on the B12/B13 tree: there the draw re-read the published target set in the
compact selection (a publish in between left the frozen layout without its set)
and requested a new build on every size step instead of through the settle gate.
"""
from pathlib import Path
import re
import sys


def fail(msg):
    raise SystemExit(f"B14 contract: {msg}")


def main():
    root = Path(sys.argv[1])
    vr = (root / "src/mods/VR.cpp").read_text(encoding="utf-8")
    hpp = (root / "src/mods/VR.hpp").read_text(encoding="utf-8")
    geo = (root / "src/mods/vr/QuadViewGeometry.hpp").read_text(encoding="utf-8")
    if "class ResizeGate" not in geo:
        fail("ResizeGate missing from the copied QuadViewGeometry.hpp")
    if "uevr::quadview::ResizeGate m_triview_resize_gate" not in hpp or "m_triview_hold_set{}" not in hpp:
        fail("VR members missing")
    if "m_triview_live_sizes" in vr:
        fail("B12 per-frame live-size path still used")
    start = vr.find("Tri-view B14: ONE read of the published set")
    end = vr.find("    m_triview_hold_set.reset();\n", start)
    if start < 0 or end < 0:
        fail("B14 draw region not found")
    region = vr[start:end]
    hold_text = "m_triview_hold_set=live_rtm ? live_rtm->get_quadview_native_target_set()"
    hold = region.find(hold_text)
    gate = region.find("m_triview_resize_gate.update(")
    select = region.find("const auto set=m_triview_hold_set;")
    confirm = region.find("m_triview_resize_gate.confirm_live(set->extents")
    freeze = region.find("layout=m_quadview_layout_latch.freeze(")
    ensure = region.find("rtm->ensure_quadview_native_target_set(requested_extents)")
    keep = region.find("native_target_set=hold;")
    order = [hold, gate, select, confirm, freeze, ensure, keep]
    if min(order) < 0 or order != sorted(order):
        fail(f"draw order wrong {order}")
    # Between the hold read and the freeze nothing may read the published set again.
    if region[hold + len(hold_text):freeze].count("get_quadview_native_target_set()"):
        fail("the published set is read twice before the layout freeze")
    if vr.count("m_triview_resize_gate.update(") != 1 or vr.count("m_triview_pending_extents_valid=true;") != 1:
        fail("a build request bypasses the settle gate")
    if not re.search(r"published->world_identity==hold->world_identity", region):
        fail("held set must be same-world")
    hook = (root / "src/mods/vr/FFakeStereoRenderingHook.hpp").read_text(encoding="utf-8")
    if "state == NativeStereoFixState::PairReady || state == NativeStereoFixState::Active" not in hook:
        fail("autostart readiness helper missing")
    auto = vr[vr.find("Tri-view B12: automatic Native Stereo Fix warm-up"):]
    auto = auto[:auto.find("if (!selection.pending()) { return; }")]
    if "is_native_stereo_fix_state_ready()" not in auto or "is_native_stereo_fix_state_active()" in auto:
        fail("autostart still waits for Active, which STALKER 2 never reports (always 25 s)")
    print("B14 source contracts: ok")


if __name__ == "__main__":
    main()

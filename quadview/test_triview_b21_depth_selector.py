#!/usr/bin/env python3
"""B21 checks real generated backend and comparison with pinned B15-27 logic."""
from pathlib import Path
import importlib.util
import sys
import unittest

overlay=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("b21",overlay/"apply_triview_b21_depth_selector.py")
b21=importlib.util.module_from_spec(spec)
spec.loader.exec_module(b21)
backend=Path(sys.argv[1]) if len(sys.argv)>1 else None

class B21DepthSelectorTests(unittest.TestCase):
    def test_b15_rule_in_b18_safe_header(self):
        original=(overlay/"QuadViewNgxDepthB18.hpp").read_text(encoding="utf-8")
        older=(overlay/"QuadViewNgxDepth.hpp").read_text(encoding="utf-8")
        new=b21.patch_depth(original)
        predicate="now - slot->submitted_at < std::chrono::milliseconds(250)"
        self.assertIn(predicate,older,"B15-27 was the recent-submitted reference")
        self.assertIn(predicate,new,"B21 must restore the same 250 ms window")
        self.assertIn("now >= slot->submitted_at",new)
        self.assertIn("latest_recent_submitted()",new)
        self.assertNotIn("depth_capture_in_window(slot->recorded,not_before,now)",new)
        self.assertIn("recording_epochs_.matches(",new,"B18 recording epoch safety retained")
        self.assertIn("submission_sequence_.acquire()",new,"B18 Reset/Execute safety retained")
        self.assertIn("depth_slot_reusable(",new,"B18 allocation safety retained")
        self.assertIn("(!slot->foreign_queue || depth_copy_complete(completed, slot->producer_fence_value))",new)
        self.assertNotIn("queue->Wait(",new,"B19 GPU wait must not be introduced")
        with self.assertRaises(RuntimeError): b21.patch_depth(new)

    def test_consumer_and_ui_transform(self):
        original="uevr::quadview::ngx::PeripheryDepth::self().latest_approximate_since(packet->depth_not_before)"
        new=b21.patch_consumer(original)
        self.assertEqual(new,"uevr::quadview::ngx::PeripheryDepth::self().latest_recent_submitted()")
        with self.assertRaises(RuntimeError): b21.patch_consumer(new)

    def test_generated_source(self):
        if backend is None: self.skipTest("No generated backend passed")
        root=backend/"src/mods"
        depth=(root/"vr/QuadViewNgxDepth.hpp").read_text(encoding="utf-8")
        dx=(root/"vr/D3D12Component.cpp").read_text(encoding="utf-8")
        hook=(root/"vr/FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
        vr=(root/"VR.cpp").read_text(encoding="utf-8")
        self.assertIn("latest_recent_submitted()",depth)
        self.assertIn("latest_recent_submitted()",dx)
        self.assertNotIn("latest_approximate_since(",depth)
        self.assertNotIn("latest_approximate_since(",dx)
        self.assertNotIn("queue->Wait(",dx)
        self.assertIn("depth_input.keepalive=snapshot;",dx)
        self.assertIn("qv_native_ready && native_callback &&",hook)
        self.assertIn("B21: recent submitted periphery depth",vr)

if __name__=="__main__":
    unittest.main(argv=sys.argv[:1],verbosity=2)

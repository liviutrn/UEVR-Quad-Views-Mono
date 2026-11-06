#!/usr/bin/env python3
"""B20 generated production checks and patch guards."""
import importlib.util
from pathlib import Path
import sys
import unittest
p=Path(__file__).with_name("apply_triview_b20_from_b18.py")
spec=importlib.util.spec_from_file_location("b20",p)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
class B20Tests(unittest.TestCase):
    def test_canonical_b18_guard_and_no_double_apply(self):
        original=p.with_name("QuadViewNgxDepthB18.hpp").read_text(encoding="utf-8")
        new=mod.transform(original)
        self.assertIn("expected_extent_.store((uint64_t(w) << 32) | h",new)
        self.assertIn("last_pruned_extent_.load(std::memory_order_acquire)==extent",new)
        self.assertIn("retirement_tick_.fetch_add(1",new)
        self.assertIn("prune_locked(uint32_t(extent>>32),uint32_t(extent),!enabled)",new)
        self.assertIn("depth_slot_reusable(",new)
        self.assertIn("depth_capture_in_window(",new)
        self.assertIn("queue->Signal(slot->producer_fence.Get(), value)",new)
        self.assertNotIn("queue->Wait(",new)
        with self.assertRaises(RuntimeError):mod.transform(new)
    def test_generated_backend(self):
        if len(sys.argv)<2:self.skipTest("No backend provided")
        root=Path(sys.argv[1])/"src/mods/vr"
        depth=(root/"QuadViewNgxDepth.hpp").read_text(encoding="utf-8")
        consumer=(root/"D3D12Component.cpp").read_text(encoding="utf-8")
        self.assertIn("const bool retry_retirement=",depth)
        self.assertIn("expected_extent_.load(std::memory_order_acquire)",depth)
        self.assertIn("enabled_.exchange(enabled,std::memory_order_acq_rel)",depth)
        self.assertIn("(!slot->foreign_queue || depth_copy_complete(completed, slot->producer_fence_value))",depth)
        self.assertNotIn("slot->producer_fence && slot->producer_fence_value && completed != ~uint64_t{}",depth)
        self.assertNotIn("[TriView][DepthSync] GPU-side cross-queue waits",consumer)
        self.assertNotIn("auto synced_depth=depth_input",consumer)
        self.assertIn("latest_approximate_since(packet->depth_not_before)",consumer)
        self.assertIn("depth_input.keepalive=snapshot;",consumer)
        self.assertNotIn("prune_locked(want_w_.load(),want_h_.load(),!on)",depth)

if __name__=="__main__":
    unittest.main(argv=sys.argv[:1],verbosity=2)

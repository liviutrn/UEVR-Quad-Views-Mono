#!/usr/bin/env python3
"""B19 generated-code gate and adversarial anchor regression tests."""
import importlib.util
from pathlib import Path
import sys
import unittest

overlay = Path(__file__).parent
spec = importlib.util.spec_from_file_location("depth_sync", overlay / "apply_triview_b19_depth_sync.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class B19DepthSyncTests(unittest.TestCase):
    def test_fail_closed_if_backend_has_changed(self):
        with self.assertRaises(RuntimeError):
            mod.patch_depth("unrelated")
        with self.assertRaises(RuntimeError):
            mod.patch_d3d12("unrelated")
        with self.assertRaises(RuntimeError):
            mod.patch_consumer("unrelated")

    def test_exactly_one_patch_occurrence(self):
        original = "    std::shared_ptr<const void> keepalive{};\n"
        patched = mod.patch_d3d12(original)
        self.assertIn("ComPtr<ID3D12Fence> producer_fence{}", patched)
        self.assertEqual(patched.count("ComPtr<ID3D12Fence> producer_fence{};"), 1)

    def test_b18_canonical_stays_unchanged(self):
        old = (overlay / "QuadViewNgxDepthB18.hpp").read_text(encoding="utf-8")
        self.assertIn("(!slot->foreign_queue || depth_copy_complete(completed, slot->producer_fence_value))", old)
        new = mod.patch_depth(old)
        self.assertNotIn("(!slot->foreign_queue || depth_copy_complete(completed, slot->producer_fence_value))", new)
        self.assertIn("slot->producer_fence && slot->producer_fence_value && completed != ~uint64_t{}", new)
        with self.assertRaises(RuntimeError):
            mod.patch_depth(new)

    def test_generated_backend(self):
        if len(sys.argv) < 2:
            self.skipTest("No production backend path (fixture tests only)")
        root = Path(sys.argv[1]) / "src/mods/vr"
        ngx = (root / "QuadViewNgxDepth.hpp").read_text(encoding="utf-8")
        dx = (root / "QuadViewD3D12.hpp").read_text(encoding="utf-8")
        c = (root / "D3D12Component.cpp").read_text(encoding="utf-8")
        self.assertIn("completed != ~uint64_t{}", ngx)
        self.assertIn("depth_capture_in_window(slot->recorded,not_before,now)", ngx)
        self.assertIn("ComPtr<ID3D12Fence> producer_fence{}", dx)
        self.assertIn("synced_depth.producer_fence->GetCompletedValue()", c)
        self.assertIn("queue->Wait(", c)
        self.assertIn("synced_depth.texture=nullptr", c)
        self.assertIn("synced_depth.reproject=false", c)
        self.assertIn("latest_approximate_since(packet->depth_not_before)", c)
        self.assertLess(c.index("queue->Wait("), c.index("recorded=comp.record_sources("))
        self.assertIn("(synced_depth.texture || synced_depth.show) ? &synced_depth : nullptr", c)
        self.assertNotIn("(depth_input.texture || depth_input.show) ? &depth_input : nullptr", c)
        self.assertNotIn("WaitForSingleObject", c[c.index("// B19: the game is executing DLSS depth copies"):c.index("recorded=comp.record_sources(")])


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1], verbosity=2)

#!/usr/bin/env python3
"""Generated-source checks for the B11 depth wiring (no NGX runtime proof)."""
import importlib.util
from pathlib import Path
import sys
import unittest

root=Path(sys.argv.pop(1)) if len(sys.argv)>1 else Path(__file__).resolve().parents[2]/'backend'
spec=importlib.util.spec_from_file_location('depth_live_overlay',Path(__file__).with_name('apply_triview_depth_live.py'))
overlay=importlib.util.module_from_spec(spec);spec.loader.exec_module(overlay)

class DepthLiveTests(unittest.TestCase):
    def setUp(self):
        self.c=(root/'src/mods/vr/D3D12Component.cpp').read_text()
        self.v=(root/'src/mods/VR.cpp').read_text()
        self.vh=(root/'src/mods/VR.hpp').read_text()
        self.g=(root/'src/mods/vr/QuadViewGeometry.hpp').read_text()
        self.n=(root/'src/mods/vr/QuadViewNgxDepth.hpp').read_text()
    def test_consumer_takes_newest_submitted_copy_with_jitter(self):
        self.assertIn('PeripheryDepth::self().latest()',self.c)
        self.assertIn('depth_input.jitter_valid=snapshot->jitter_valid;',self.c)
        self.assertNotIn('for_source(',self.c)
    def test_capture_enabled_and_logged(self):
        self.assertIn('capture_supported() noexcept { return true; }',self.n)
        self.assertNotIn('DepthOwnerScope::current()',self.n)
        self.assertIn('[TriView][Depth] hooks=',self.c)
        self.assertIn('generate_name("TriViewPeripheryDepthB11"), true)',self.vh)
    def test_unique_periphery_size_and_expected_size_published(self):
        self.assertIn('unique_context_factor',self.g)
        self.assertIn('PeripheryDepth::self().set_expected(',self.v)
    def test_game_submission_not_serialised_behind_lock(self):
        body=self.n.split('static void __stdcall execute_commands(',1)[1].split('static void install_group(',1)[0]
        self.assertLess(body.index('unsafe_call'),body.index('scoped_lock'))
    def test_id7_cold_start_runs_native_fix_bootstrap_until_settled(self):
        h=(root/'src/mods/vr/FFakeStereoRenderingHook.cpp').read_text()
        body=h.split('bool stalker2_uses_lazy_synced_viewstates() {',1)[1].split('\n}\n',1)[0]
        self.assertIn('vr->is_native_stereo_fix_enabled() || qv_cold_bootstrap',body)
        self.assertIn('!g_hook->is_localplayer_bootstrap_settled()',body)
        self.assertIn('is_localplayer_bootstrap_settled() const { return m_fixed_localplayer_view_count; }',
                      (root/'src/mods/vr/FFakeStereoRenderingHook.hpp').read_text())
    def test_replay_rejects_duplicate_application(self):
        with self.assertRaises(RuntimeError): overlay.consumer(self.c)

if __name__=='__main__': unittest.main()

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
    def test_startup_state_logged(self):
        self.assertIn('[TriView][Startup] selected',self.c)
    def test_b12_autostart_resize_and_gaze_menu(self):
        self.assertIn('[TriView][Autostart] saved ID7: warming up Native Stereo',self.v)
        self.assertIn('[TriView][Transition] requested=',self.v)
        self.assertIn('m_triview_pending_extents_valid=true;',self.v)
        self.assertIn('requested_extents=m_triview_pending_extents;',self.v)
        self.assertIn('rtm->quadview_native_targets_live(*live)) native_target_set=live;',self.v)
        self.assertIn('m_save_override >= 0 ? m_save_override : requested_value()',(root/'src/mods/vr/RenderingMethodSetting.hpp').read_text())
        h=(root/'src/mods/vr/FFakeStereoRenderingHook.cpp').read_text()
        self.assertIn('old->world_identity!=world_identity',h)
        self.assertIn('Stable gaze crop (OpenNR r10 policy)',self.v)
        self.assertIn('Restore DuoView gaze defaults',self.v)
        self.assertIn('is_depth_allowed() && !vr->triview_skips_xr_depth()',self.c)
    def test_b13_fences_shader_and_truthful_startup(self):
        self.assertIn('ComPtr<ID3D12Fence> producer_fence;', self.n)
        self.assertIn('slot->producer_fence->GetCompletedValue()', self.n)
        self.assertIn('candidate->producer_fence->GetCompletedValue()', self.n)
        self.assertIn('queue->Signal(slot->producer_fence.Get(), value)', self.n)
        self.assertNotIn('queue->Signal(fence_.Get(), value)', self.n)
        shader=Path(__file__).with_name('QuadViewComposite.hlsl').read_text()
        self.assertIn('if (i == 0u || previousF <= -0.5)',shader)
        self.assertIn('previousF = inside ? f : -1.0;',shader)
        self.assertIn('transition settled WITHOUT ID7',self.v)

    def test_replay_rejects_duplicate_application(self):
        with self.assertRaises(RuntimeError): overlay.consumer(self.c)

if __name__=='__main__': unittest.main()

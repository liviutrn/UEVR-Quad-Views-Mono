#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest
p=Path(__file__).with_name('apply_triview_b18_depth.py')
spec=importlib.util.spec_from_file_location('depth_b18',p)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class DepthTests(unittest.TestCase):
    def test_packet_bound_is_temporal_not_claimed_identity(self):
        header=mod.hook_header('    struct QuadViewSourcePacket {\n')
        self.assertIn('depth_not_before',header)
        self.assertIn('not proof of exact NGX source ownership',header)
        with self.assertRaises(RuntimeError):mod.hook_header(header)
    def test_old_unbounded_selector_is_removed(self):
        result=mod.consumer('uevr::quadview::ngx::PeripheryDepth::self().latest()')
        self.assertIn('latest_approximate_since(packet->depth_not_before)',result)
        with self.assertRaises(RuntimeError):mod.consumer(result)
    def test_production_recording_safety_wiring(self):
        source=Path(__file__).with_name('QuadViewNgxDepthB18.hpp').read_text()
        self.assertIn('slot->list_epoch = list_epoch;',source)
        self.assertIn('recording_epochs_.matches(',source)
        self.assertIn('s.recording_epochs_.reset(',source)
        self.assertNotIn('AbandonAfter',source)
        self.assertNotIn('graveyard_',source)
        self.assertNotIn('DepthFamily',source)
        reset=source.split('static HRESULT __stdcall reset_list(',1)[1].split('template <unsigned N> static uint32_t __cdecl evaluate',1)[0]
        execute=source.split('static void __stdcall execute_commands(',1)[1].split('static void install_group',1)[0]
        for body in (reset,execute):
            self.assertLess(body.index('submission_sequence_.acquire()'),body.index('unsafe_call'))
            self.assertLess(body.index('unsafe_call'),body.index('std::scoped_lock lock(s.mutex_)'))
        self.assertIn('slot->pending=false;slot->submitted=true;slot->valid_evaluation=false;',source)
        self.assertIn('depth_capture_in_window(slot->recorded,not_before,now)',source)
        self.assertIn('prune_locked(want_w_.load(),want_h_.load(),!on);',source)
if __name__=='__main__':unittest.main()

#!/usr/bin/env python3
"""Source-boundary regression checks; these do not prove NGX runtime coverage."""
import importlib.util
from pathlib import Path
import sys
import unittest

root=Path(sys.argv.pop(1)) if len(sys.argv)>1 else Path(__file__).resolve().parents[2]/'backend'
spec=importlib.util.spec_from_file_location('depth_owner_overlay',Path(__file__).with_name('apply_triview_depth_owner.py'))
overlay=importlib.util.module_from_spec(spec);spec.loader.exec_module(overlay)

class DepthOwnerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.h=(root/'src/mods/vr/FFakeStereoRenderingHook.cpp').read_text()
        self.c=(root/'src/mods/vr/D3D12Component.cpp').read_text()
        if 'const auto qv_depth_owner=[&]()' not in self.h:
            self.h=overlay.hook(self.h);self.c=overlay.consumer(self.c)
    def test_reject_mixed_roles_and_transaction_owners(self):
        body=self.h.split('const auto qv_depth_owner=[&]()',1)[1].split('auto call_orig',1)[0]
        for proof in ('owner.view!=0','owner.source.same_owner(first.source)',
                      'owner.engine.same_owner(first.engine)','owner.target_set!=first.target_set',
                      'owner.target!=first.target','quad_drain.count','first.source.engine_frame_bound',
                      'frozen->key.generation!=first.source.generation',
                      'frozen->key.draw_serial!=first.source.serial',
                      'native_target_set_generation!=first.target_set'):
            self.assertIn(proof,body)
        self.assertNotIn('quadview_producer_key()',body)
    def test_scope_brackets_only_original_callback(self):
        scoped=self.h.split('DepthOwnerScope depth_scope{qv_depth_owner}',1)[1].split('}();',1)[0]
        self.assertIn('return func(cmd, cmd_list,',scoped)
        self.assertNotIn('enqueue_render_poses',scoped)
        self.assertNotIn('RHIThreadWorker',scoped)
    def test_consumer_uses_selected_packet_identity(self):
        body=self.c.split('DepthOwner expected_depth{};',1)[1].split('depth_input.texture=',1)[0]
        for proof in ('source->generation','source->serial','source->engine_frame',
                      'packet->native_target_set_generation','frozen->projections[0]',
                      'for_source(expected_depth)'):
            self.assertIn(proof,body)
        self.assertNotIn('latest()',self.c)
    def test_replay_rejects_partial_or_duplicate_application(self):
        with self.assertRaises(RuntimeError): overlay.hook(self.h)
        with self.assertRaises(RuntimeError): overlay.consumer(self.c)

if __name__=='__main__': unittest.main()

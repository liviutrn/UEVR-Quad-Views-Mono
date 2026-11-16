#!/usr/bin/env python3
"""Negative controls for baseline measurement; no candidate renders."""
import random
import unittest
import numpy as np
import edge_baseline_score as e
from edge_math import PROFILES, envelope, knee, sample, solve, v2_map, v2_unmap

class Measurements(unittest.TestCase):
    def test_signed_temporal(self):
        a=np.array([[[250,1,100],[0,0,0]]],np.uint8)
        b=np.array([[[1,250,90],[0,0,0]]],np.uint8)
        m=np.array([[True,False]])
        self.assertEqual(e.temporal(a,b,a,b,m)['normalized'],0.)
        self.assertGreater(e.temporal(a,b,b,a,m)['normalized'],1.)
        self.assertIsNone(e.temporal(a,b,a,b,np.zeros((1,2),bool))['normalized'])

    def test_matched_transition_not_maxima(self):
        baselines=[{'count':1,'normalized':.1},{'count':1,'normalized':.2}]
        candidates=[{'count':1,'normalized':.11},{'count':1,'normalized':.19}]
        self.assertTrue(e.paired_delta(candidates[0],baselines[0])['regression'])
        self.assertFalse(e.paired_delta(candidates[1],baselines[1])['regression'])
        self.assertLess(max(z['normalized'] for z in candidates),max(z['normalized'] for z in baselines))
        with self.assertRaises(RuntimeError):
            e.paired_delta({'count':2,'normalized':.1},baselines[0])
        self.assertIsNone(e.paired_delta({'count':0},{'count':0})['regression'])

    def test_halo_directions_layers_and_full_radius(self):
        center=np.zeros((e.H,e.W),np.uint8)
        center[:,130:170]=2
        for eye,sign in (('left',1),('right',-1)):
            # Independent exact ID projection for this two-layer row.
            xx=np.arange(e.W)
            ids=np.zeros_like(center)
            ids[:,(xx+sign*13>=130)&(xx+sign*13<170)]=2
            mask,geometry=e.geometric_masks(ids,center,eye,False,PROFILES['P1'])
            self.assertEqual(int(mask['valid'].sum()),(e.W-8)*(e.H-8))
            self.assertGreater(mask['hole_id0'].sum(),0)
            self.assertEqual(mask['hole_id1'].sum(),0)
            self.assertFalse(np.any(mask['halo']&mask['disoccluded']))
            self.assertTrue(np.all(ids[mask['halo']]==0))
            hx=170-.5-sign*13*.12 if sign>0 else 130-.5-sign*13*.12
            positions=np.where(mask['halo'][e.H//2])[0]
            self.assertTrue(np.all(sign*(positions-hx)>=0))
            radius=(v2_map(1,PROFILES['P1'])-v2_map(.12,PROFILES['P1']))/(.99/13)+8
            self.assertAlmostEqual(geometry['max_source_radius_including_guard'],radius)
            # Radius begins after the hole, not at the foreground silhouette.
            self.assertGreater(len(positions),int((1-.12)*13))
        center[:]=1;center[:,130:170]=2
        ids=center.copy();ids[:]=1;ids[:,117:157]=2
        m,_=e.geometric_masks(ids,center,'left',False,PROFILES['P1'])
        self.assertGreater(m['hole_id1'].sum(),0)
        self.assertEqual(m['hole_id0'].sum(),0)
        self.assertGreater(m['halo_id1'].sum(),0)

    def test_iou_is_predicted_not_gt_area(self):
        ids=np.array([[0,2,2,0]],np.uint8);pred=np.array([[0,2,0,2]],np.uint8)
        v=e.integrity(pred,ids,np.ones_like(ids,bool))
        self.assertAlmostEqual(v['iou'],1/3)
        self.assertEqual(v['false_positive'],1)
        self.assertEqual(v['false_negative'],1)

    def test_actual_map_knee(self):
        for p in PROFILES.values():
            for d in (0,.01,1/p.end_m,1/p.start_m,.47,1.,2.5,20):
                self.assertAlmostEqual(v2_unmap(v2_map(d,p),p),d)
        self.assertAlmostEqual(knee(10,PROFILES['P1']),7.5)
        self.assertEqual(knee(20,PROFILES['P0']),12.5)

    def test_directional_oracle_and_monotone(self):
        rng=random.Random(261116)
        for eye in (-1,1):
            for r in (1,2,4,10):
                for _ in range(25):
                    h=[rng.random()*3 for _ in range(25)];pen=.99/13
                    got=envelope(h,pen,eye,r)
                    oracle=[max(0.,max(d-pen*abs(i-j)*(r if (i-j)*eye>0 else 1) for j,d in enumerate(h))) for i in range(len(h))]
                    self.assertLess(max(abs(a-b) for a,b in zip(got,oracle)),1e-10)
                    self.assertTrue(all(got[i]>=h[i]-1e-12 for i in range(len(h))))
                    projected=[i-eye*13*d for i,d in enumerate(got)]
                    self.assertTrue(all(b>a for a,b in zip(projected,projected[1:])))
                    for base in (0,5,10):
                        u=solve(base,eye*13,lambda x:sample(got,x),10)
                        self.assertTrue(np.isfinite(u))

if __name__=='__main__':
    unittest.main(verbosity=2)

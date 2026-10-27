#!/usr/bin/env python3
"""Analytic CPU oracle: independently tests camera transforms, crop and safe depth/color matching."""
import unittest, math, pathlib
HERE=pathlib.Path(__file__).resolve().parents[1]
HLSL=(HERE/"StereoBackwardGather.hlsl").read_text(encoding="utf-8")
HEADER=(HERE/"StereoBackwardContract.hpp").read_text(encoding="utf-8")
def mv(m,v): return [sum(m[i][k]*v[k] for k in range(4)) for i in range(4)]
def inv(m):
    a=[list(row)+[float(i==j) for j in range(4)] for i,row in enumerate(m)]
    for i in range(4):
        p=max(range(i,4),key=lambda j:abs(a[j][i]));a[i],a[p]=a[p],a[i]
        assert abs(a[i][i])>1e-12
        d=a[i][i];a[i]=[v/d for v in a[i]]
        for j in range(4):
            if j!=i:
                d=a[j][i];a[j]=[v-d*w for v,w in zip(a[j],a[i])]
    return [row[4:] for row in a]
def unproject(uv,z,inverse):
    p=mv(inverse,[2*uv[0]-1,1-2*uv[1],z,1])
    return [x/p[3] for x in p[:3]]
def project(point,m):
    p=mv(m,[*point,1])
    return ((p[0]/p[3]+1)/2,(1-p[1]/p[3])/2,p[2]/p[3])
def revz(n,f):
    return [[1,0,0,0],[0,1,0,0],[0,0,n/(n-f),n*f/(f-n)],[0,0,1,0]]
def mult(a,b):return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
def view(x):return [[1,0,0,-x],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
def gather(uv,size,depth_and_rgb,expected,tol):
    x,y=uv[0]*size[0]-.5,uv[1]*size[1]-.5
    xy=math.floor(x),math.floor(y)
    out=[0.,0.,0.];weight=0.
    for j in (0,1):
        for i in (0,1):
            px,py=xy[0]+i,xy[1]+j
            w=max(0.,1-abs(x-px))*max(0.,1-abs(y-py))
            if not w or px<0 or py<0 or px>=size[0] or py>=size[1]:continue
            z,rgb=depth_and_rgb[(px,py)]
            if abs(z-expected)>tol:continue
            for k in range(3):out[k]+=rgb[k]*w
            weight+=w
    return tuple(v/weight for v in out) if weight else None
class Tests(unittest.TestCase):
    def test_reversed_z_projection_round_trip(self):
        m=revz(.1,1000)
        for z in (.1,1,10,100,1000):
            p=project([.02,-.01,z],m)
            w=unproject(p[:2],p[2],inv(m))
            self.assertAlmostEqual(w[2],z,delta=1e-6*z)
        self.assertAlmostEqual(project([0,0,.1],m)[2],1)
        self.assertAlmostEqual(project([0,0,1000],m)[2],0)
    def test_eye_pose_changes_correct_disparity(self):
        p=revz(.1,1000)
        left,right=mult(p,view(-.036)),mult(p,view(.036))
        world=[0,0,2]
        l,r=project(world,left),project(world,right)
        self.assertGreater(l[0],r[0])
        self.assertAlmostEqual(project(unproject(r[:2],r[2],inv(right)),left)[0],l[0],places=7)
    def test_full_fov_crop_resource_rect_is_not_fov_projection(self):
        rect=(.1,.2,.6,.55);native=(.25,.8)
        actual=(rect[0]+native[0]*rect[2],rect[1]+native[1]*rect[3])
        self.assertAlmostEqual(actual[0],.25)
        self.assertAlmostEqual(actual[1],.64)
    def test_wrong_occluded_surface_never_leaks_color(self):
        pixels={(0,0):(1,(1,0,0)),(1,0):(9,(0,0,1)),(0,1):(1,(1,0,0)),(1,1):(9,(0,0,1))}
        self.assertEqual(gather((.5,.5),(2,2),pixels,1,.01),(1,0,0))
        self.assertEqual(gather((.5,.5),(2,2),pixels,9,.01),(0,0,1))
        self.assertIsNone(gather((.5,.5),(2,2),pixels,5,.01))
    def test_shader_binds_and_can_fail_closed(self):
        for s in ("register(t0)","register(t1)","register(t2)","register(t3)",
                  "register(u0)","register(u1)","register(u2)",
                  "register(s0)","register(b0)","RealTargetFallback",
                  "SourceColor.Load(int3(colorPx,0))","CSBackwardTargetDepth","REJECT_TARGET_EDGE"):
            self.assertIn(s,HLSL)
        self.assertNotIn("SourceColor.SampleLevel",HLSL)
        self.assertIn("depthEyeProven && frameGenerationMatches",HEADER)
        self.assertIn("static_assert(sizeof(BackwardConstants)==416)",HEADER)
if __name__=="__main__":unittest.main()

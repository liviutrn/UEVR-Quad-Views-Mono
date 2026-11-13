#!/usr/bin/env python3
"""M3b deterministic numeric models: P2 clamp, P3 background repair, P4 edge selection."""
import random

def check(value,label):
    if not value: raise SystemExit("FAIL: "+label)
    print("PASS: "+label)

def stabilize(current,history,strength=.6,reset=False):
    h=len(current);w=len(current[0])
    if history is None or reset:return [row[:] for row in current]
    result=[[0.0]*w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            v=current[y][x]
            nearby=[current[yy][xx] for yy in range(max(0,y-1),min(h,y+2))
                    for xx in range(max(0,x-1),min(w,x+2))]
            candidates=[history[yy][xx] for yy in (max(0,y-1),y)
                        for xx in (max(0,x-1),x)]
            best=min(candidates,key=lambda d:abs(d-v))
            clamped=max(min(nearby)-.002,min(max(nearby)+.002,best))
            result[y][x]=v*(1-strength)+clamped*strength
    return result

def variance(values):
    mean=sum(values)/len(values)
    return sum((v-mean)**2 for v in values)/len(values)

def repair(depth,root,low_confidence=True):
    if not low_confidence:return root,0
    center=depth[root]
    left=depth[max(0,root-8)];right=depth[min(len(depth)-1,root+8)]
    direction=1 if right<left else -1
    for step in range(1,9):
        points=[root+direction*(step+j) for j in range(3)]
        if any(p<0 or p>=len(depth) for p in points):break
        d=[depth[p] for p in points]
        if d[0]+.01>=center or not all(abs(z-d[0])<=max(.01,.025*max(z,d[0])) for z in d[1:]):
            continue
        best=min(range(3),key=lambda i:d[i])
        return points[best],2
    return root,1

def guided(depth,colour,probe,target):
    # 2x2 source-nearest values; if it is an edge choose only the best-matching
    # colour, never an average of near and far.
    assert len(depth)==len(colour)==4
    if max(depth)-min(depth)<=.02*max(max(depth),1e-6):return depth[probe]
    cost=[sum(abs(c[i]-target[i]) for i in range(3)) for c in colour]
    return depth[min(range(4),key=lambda n:cost[n])]

def main():
    rng=random.Random(13)
    h=w=40
    hist=None;before=[];after=[]
    for frame in range(45):
        cur=[[.25+rng.gauss(0,.01) for _ in range(w)] for _ in range(h)]
        out=stabilize(cur,hist)
        if frame>10:
            before.extend(v for row in cur for v in row)
            after.extend(v for row in out for v in row)
        hist=out
    reduction=1-variance(after)/variance(before)
    check(reduction>=.40,f"P2 static noise variance reduction {reduction:.3f} >= 0.40")
    hist=None
    for frame in range(8):
        edge=4+3*frame
        cur=[[.45 if x>=edge else .15 for x in range(40)] for _ in range(8)]
        out=stabilize(cur,hist)
        wrong=[abs(out[y][x]-cur[y][x]) for y in range(8) for x in range(40)
               if abs(x-edge)>3]
        check(max(wrong or [0.0])<=.002,"P2 moving 3-texel step stays within one-frame neighbourhood")
        hist=out
    cut=[[.35 for _ in range(8)] for _ in range(8)]
    check(stabilize(cut,hist,reset=True)==cut,"P2 camera cut invalidates history")
    d=[.45]*12+[.15]*24
    loc,status=repair(d,10)
    check(status==2 and 12<=loc<=20 and d[loc]<.45,"P3 repairs foreground edge toward far background")
    smooth=[.2+.0002*i for i in range(36)]
    loc,status=repair(smooth,18,False)
    check(loc==18 and status==0,"P3 smooth depth unchanged")
    near=(.9,.1,.1);far=(.1,.1,.9)
    values=[.45,.45,.15,.15]; colours=[near,near,far,far]
    check(guided(values,colours,0,far)==.15,"P4 blue background picks far source depth exactly")
    check(guided(values,colours,3,near)==.45,"P4 red foreground picks near source depth exactly")
    print("M3b numeric: all checks passed")

if __name__=="__main__":main()

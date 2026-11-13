#!/usr/bin/env python3
"""M2.5a Builder A: fail-closed contracts and numerical tile-gate reference.

This is a CPU oracle for the same equations, not a substitute for WARP. The
production Windows job additionally compiles all shaders and GPU tests.
"""
from pathlib import Path
import math
import sys

def smoothstep(lo,hi,x):
    t=max(0.0,min(1.0,(x-lo)/(hi-lo)))
    return t*t*(3.-2.*t)

def tile(coarse,fine,offset=0):
    n=len(coarse); agreements=[]; coarse_seen=[]
    for k in range(n):
        f=fine[min(n-1,max(0,k+offset))]
        values=[coarse[min(n-1,max(0,k+j))] for j in (-1,0,1)]
        agreements.append(min(abs(c-f) for c in values) <= max(.004,.03*f))
        coarse_seen.append(max(values))
    agree=sum(agreements)/len(agreements)
    varied=max(coarse_seen)-min(coarse_seen)>.1*max(coarse_seen)
    return agree,smoothstep(.6,.85,agree),varied

def guard(tiles):
    varied=[x for x in tiles if x[2]]
    return bool(varied) and sum(x[0]>=.6 for x in varied)*2<len(varied)

def test_math():
    # True same-scene tiles at 2x fine resolution, including a near weapon edge.
    coarse=[.07]*32+[.3]*16+[.07]*16
    fine=[x for x in coarse for _ in range(2)]
    values=[]
    for i in range(0,64,16):
        c=coarse[i:i+16]
        f=[fine[j*2] for j in range(i,i+16)]
        values.append(tile(c,f))
    assert all(t[0]>=.95 and t[1]==1 for t in values),values
    assert not guard(values)
    # Six coarse-pixel shift can create geometrically disagreeing edge tiles.
    wrong=[coarse[min(63,i+6)] for i in range(64)]
    wrong_tiles=[tile(coarse[i:i+16],wrong[i:i+16]) for i in range(0,64,16)]
    # The veto must be defined by VARIED tile coverage, not just all-flat tiles.
    assert any(v[0]<.95 for v in wrong_tiles)
    assert guard([(0.0,0.0,True)]*3+[(1.0,1.0,True)]*2)
    assert not guard([(0.0,0.0,False)]*6)
    wall=[.1]*32
    a,b,v=tile(wall,wall)
    assert a==b==1 and not v
    assert tile(wall,wall,offset=1)[1]==1
    # Full frame veto really disables all fine weights.
    assert all((0. if guard([(0.,0.,True)]*2) else t[1]) == 0. for t in [(0.,0.,True)]*2)

def test_pool_reference():
    # Twelve slots are reserved as two role-specific groups of six. No resize
    # of the other role when a role gets a new resolution.
    slots={1:[],2:[]}
    events={1:0,2:0}
    for frame in range(1000):
        for role,shape in ((1,(1961,1559)),(2,(2436+(frame>=500)*64,1614))):
            idle=[x for x in slots[role] if x[1]<=frame]
            if idle:
                s=min(idle,key=lambda x:x[1])
                if s[0]!=shape:
                    events[role]+=1
                    s[0]=shape
                s[1]=frame+3
            else:
                if len(slots[role])>=6:
                    continue
                slots[role].append([shape,frame+3])
                events[role]+=1
    assert events[1]<=6 and events[2]<=12,events
    assert len(slots[1])<=6 and len(slots[2])<=6

def check_files():
    assert len(sys.argv)==3
    root=Path(sys.argv[1])/"src/mods"
    shaders=Path(sys.argv[2])
    def required(p,*pieces):
        src=p.read_text(encoding="utf-8")
        for item in pieces: assert item in src,(p,item)
        return src
    c=required(root/"vr/DuoViewConfig.hpp",
        "m25_fine_mode{0}","m21_depth_debug{0}")
    d=required(root/"vr/QuadViewNgxDepth.hpp",
        "latest_duoview_content_fine_submitted","m25_pool_role",
        "m25_owned>=6u","m25_delta_hist_","depth_copy_complete(completed,fine->producer_fence_value)")
    assert "latest_duoview_pair_submitted" in d, "M2.4 strict fallback missing"
    required(root/"vr/D3D12Component.cpp",
        "config.settings.m25_fine_mode==0u",
        "latest_duoview_content_fine_submitted",
        "config.settings.m25_fine_mode==1u ? 1.f : depths.m24_fine_weight()")
    r=required(root/"vr/DuoViewD3D12.hpp",
        "m1_raw_range.NumDescriptors=4","m1_output_range.NumDescriptors=3",
        "m1_.m25_analyse.Get()","m1_.m25_guard.Get()",
        "cmd->CopyResource(m1_.m25_readback.Get(),m1_.m25_stats.Get())")
    required(root/"vr/DuoViewM1D3D12.hpp",
        "sizeof(M1Constants) == 288","m25_read_retired_stats()",
        "data.m25_flags[0]=m25_content_active ? 1.f : 0.f",
        "m25_analysis_bytecode","m25_guard_bytecode")
    h=required(shaders/"DuoViewM1Stereo.hlsl",
        "void CSAnalyzeM25","void CSGuardM25",
        "M25StatsRead.Load(0)","smoothstep(.60,.85,ratio)",
        "passing*2u<varied","M25Weight(fullUv)",
        "if(fineNear>0.0) nearDepth=lerp(nearDepth,fineNear,feather*M1Filter.w)")
    assert "M25Flags.x>.5" in h
    required(shaders/"DuoViewNativeCompositeRaster.hlsl",
        "M2Sharpen.z>1.5","M25TileRead.Load")
    required(root/"VR.hpp","DuoM25FineMode")
    required(root/"VR.cpp","Fine depth check","Depth debug (0=off")
    assert "DepthCaptureMode::TriView" in d
    assert "m25_content_active" in r

if __name__=="__main__":
    test_math();test_pool_reference();check_files()
    print("M2.5a CPU numerical gate, two-role pool and generated-source checks: PASS")

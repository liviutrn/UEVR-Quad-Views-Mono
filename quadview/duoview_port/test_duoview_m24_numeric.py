#!/usr/bin/env python3
"""M2.4 numeric two-axis depth guarantees, fade, corner and epoch tests.

Uses no third-party deps, suitable for Windows CI before compiling the SDK.
"""
import math
from pathlib import Path
import sys

def env_1d(values, penalty, cap):
    state=list(values)
    n=len(state)
    step=1
    while step<n and (step-1)*penalty<cap:
        nxt=[max(state[i],state[i-step]-step*penalty if i>=step else 0.,
                 state[i+step]-step*penalty if i+step<n else 0.) for i in range(n)]
        state=nxt
        step*=2
    return state

def model(w,h,sx,sy):
    D=[[8.0 for _ in range(w)] for _ in range(h)]
    for y in range(h//2,h):
        for x in range(w//3,2*w//3):
            D[y][x]=110.0
    H=[env_1d(row,sx,130.0) for row in D]
    if sy<=0: return H,H
    cols=[env_1d([H[y][x] for y in range(h)],sy,130.0) for x in range(w)]
    G=[[cols[x][y] for x in range(w)] for y in range(h)]
    return H,G

def test_envelope():
    for sx in (.25,.5,.9):
        for sy in (0.,.5,1.,2.,4.,8.):
            F,G=model(100,55,sx,sy)
            assert all(math.isfinite(v) and v>=0 for row in G for v in row)
            assert all(abs(G[y][x]-G[y][x-1])<=sx+1.e-5
                    for y in range(len(G)) for x in range(1,len(G[0]))),"horizontal fold bound"
            if sy:
                assert all(abs(G[y][x]-G[y-1][x])<=sy+1.e-5
                        for y in range(1,len(G)) for x in range(len(G[0]))),"vertical depth tear"
            else:
                assert F==G,"0 disables and reproduces M2.3 row-only"
    F,G=model(100,55,.25,2.)
    assert max(abs(F[y][x]-F[y-1][x]) for y in range(1,55) for x in range(100))>80
    assert max(abs(G[y][x]-G[y-1][x]) for y in range(1,55) for x in range(100))<=2.+1.e-6

def central_side(u,v,lo=(.2,.2),hi=(.8,.8)):
    cx,cy=(lo[0]+hi[0])/2,(lo[1]+hi[1])/2
    dx,dy=u-cx,v-cy
    if abs(dx)<1.e-7 and abs(dy)<1.e-7: dy=-1.e-6
    rx,ry=abs(dx)/(.5*(hi[0]-lo[0])),abs(dy)/(.5*(hi[1]-lo[1]))
    t=max(rx,ry,1.e-7)
    px,py=cx+dx/t,cy+dy/t
    ax,ay=(px-lo[0])/(hi[0]-lo[0]),(py-lo[1])/(hi[1]-lo[1])
    if rx>=ry:
        side=1 if dx>0 else 3
        along=ay if side==1 else 1-ay
    else:
        side=0 if dy<0 else 2
        along=ax if side==0 else 1-ax
    return side,along

def test_corner():
    for span in (.02,.20):
        # Trace across top/right corner bisector. Each side approaches the
        # same B40 periodic corner knot (top's endpoint = right's start).
        for i in range(1,100):
            v=.2+span*i/100.
            side,along=central_side(.8-span*.5,v)
            assert side in range(4) and 0<=along<=1+1.e-6
        # Boundary mappings preserve original side conventions.
        assert central_side(.5,.2)[0]==0
        assert central_side(.8,.5)[0]==1
        assert central_side(.5,.8)[0]==2
        assert central_side(.2,.5)[0]==3

def safe_pair(a,b,packet):
    return (a["epoch"]==b["epoch"]==packet["epoch"] and
            a["generation"]==b["generation"]==packet["generation"] and
            abs(a["sequence"]-b["sequence"])==1 and
            a["queue"]==b["queue"]==packet["queue"] and
            abs(a["ms"]-b["ms"])<=25 and a["fence"] and b["fence"])

def test_epoch():
    p=dict(epoch=9,generation=12,queue=1)
    a=dict(epoch=9,generation=12,queue=1,sequence=80,ms=100,fence=True)
    b=dict(epoch=9,generation=12,queue=1,sequence=81,ms=120,fence=True)
    assert safe_pair(a,b,p)
    assert not safe_pair(a,dict(b,epoch=10),p),"adjacent cross-frame forbidden"
    assert not safe_pair(a,dict(b,sequence=83),p),"Cheeky middle evaluation still fail closed"
    assert not safe_pair(a,dict(b,ms=150),p),"time guard still mandatory"
    assert not safe_pair(a,dict(b,generation=13),p),"generation guard"
    assert not safe_pair(a,dict(b,queue=2),p),"queue guard"

def test_fade():
    wtm=110.
    near,far=2.,15.
    Dn,Df=1/(near*wtm),1/(far*wtm)
    assert Dn>Df>0
    def taper(depth):
        t=max(0.,min(1.,(depth-Df)/(Dn-Df)))
        t=t*t*(3-2*t)
        return .4+.6*t,.2+.8*t
    assert taper(1/(1*wtm))==(1.,1.)
    assert taper(1/(30*wtm))==(.4,.2)
    assert taper(1/(near*wtm))==(1.,1.)

def test_shader_contracts():
    assert len(sys.argv)==4,"Usage: test_duoview_m24_numeric.py <backend> <shaders> <quadview>"
    root=Path(sys.argv[1])/"src/mods"
    sh=Path(sys.argv[2])
    def require(p,*need):
        s=p.read_text(encoding="utf-8")
        for n in need:
            assert n in s,f"{p}: missing {n}"
        return s
    require(root/"vr/DuoViewM1D3D12.hpp",
        "static_assert(sizeof(M1Constants) == 272)","output_width_px",
        "m24_vertical_bytecode","vertical_taper*float(output_height_px)",
        "data.m24_fade[0]=1.f/(fade_near_m*geometry.world_to_meters)",
        "data.filter[3]=(std::clamp)(focus->fine_weight,0.f,1.f);",
        "data.grid[0] = uint32_t(soft.Width)",
        "static_assert(sizeof(M1Constants) <= 2*D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT)")
    require(sh/"DuoViewM1Stereo.hlsl",
        "CSConditionM1Vertical","const float pv=M1Filter.z;",
        "nearDepth=lerp(nearDepth,fineNear,feather*M1Filter.w)",
        "float4 M24Fade")
    require(root/"vr/DuoViewD3D12.hpp",
        "cmd->SetPipelineState(m1_.vertical.Get())",
        "cmd->Dispatch(m1_.grid_columns,1,1)",
        "D3D12_RESOURCE_BARRIER_TYPE_UAV",
        "settings.m24_vertical_taper",
        "frame.config.settings.sharpen_wide ? frame.config.settings.m23_wide_strength")
    require(sh/"DuoViewNativeCompositeRaster.hlsl",
        "const float wideSharpen=FocusProfile.y;",
        "fineSharpen*=lerp(M24Fade.z,1.0,t);",
        "wideSharpen*=lerp(M24Fade.w,1.0,t);")
    require(sh/"DuoViewPhase2Effects.hlsl",
        "void DuoB40CentralSide(", "DuoB40CentralSide(uv,lo,hi,side,along);")
    require(root/"vr/QuadViewNgxDepth.hpp",
        "m24_present_epoch","coarse->m24_present_epoch!=fine->m24_present_epoch",
        "coarse->m24_present_epoch!=packet_epoch",
        "m24_good_streak_", "streak<5u", "m24_fine_weight_.store(0.f)")
    require(root/"vr/DuoViewState.hpp",
        "uint64_t present_epoch{};", "slot->present_epoch=present_epoch;")
    require(root/"vr/D3D12Component.cpp",
        "depth.m24_note_present();",
        "packet_frame->present_epoch)",
        "[DuoView][M2.4] epoch packet=",
        "[DuoView][M2.4] scale eye_sep_m=")
    require(root/"VR.cpp","m_duo_m24_vertical->draw","m_duo_m24_distance->draw",
        "m_duo_m24_regular_pct->draw","current.m24_distance_fade==candidate.m24_distance_fade")
    # TriView mode-7 shader source untouched across builds; M23 oracle verifies
    # byte identity before this M24 overlay, and nothing above edits it.

if __name__=="__main__":
    test_envelope()
    test_corner()
    test_epoch()
    test_fade()
    test_shader_contracts()
    print("M2.4 PASS 2D depth Lipschitz bounds, seam central projection, strict epoch gate, correct-worldscale fade, source contracts")

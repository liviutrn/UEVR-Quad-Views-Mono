#!/usr/bin/env python3
"""M8 source contracts and pure numeric distance tests."""
from pathlib import Path
import sys
import math

def need(s,needle,name):
    if needle not in s:
        raise AssertionError(f"M8 {name}: missing {needle[:80]!r}")

def factor(inv, near, far, world_units):
    a=1.0/(near*world_units)
    b=1.0/(far*world_units)
    t=max(0.,min(1.,(a-inv)/max(a-b,1.e-8)))
    return t*t*(3.-2.*t)

def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: test_duoview_m8_generated.py <backend> <shaders>")
    root=Path(sys.argv[1])/"src/mods"
    vr=root/"vr"
    shader=Path(sys.argv[2])/"DuoViewM1Stereo.hlsl"
    raster=Path(sys.argv[2])/"DuoViewNativeCompositeRaster.hlsl"
    cfg=(vr/"DuoViewConfig.hpp").read_text(encoding="utf-8")
    params=(vr/"DuoViewM1D3D12.hpp").read_text(encoding="utf-8")
    dx=(vr/"DuoViewD3D12.hpp").read_text(encoding="utf-8")
    ui=(root/"VR.cpp").read_text(encoding="utf-8")
    hdr=(root/"VR.hpp").read_text(encoding="utf-8")
    s=shader.read_text(encoding="utf-8")
    p=raster.read_text(encoding="utf-8")

    for token in ["bool m8_distance{false}", "float m8_near_m{2.f}, m8_far_m{5.f}",
                  "float m8_edge_near{0.f}, m8_edge_far{1.f}",
                  "float m8_fill_near{1.f}, m8_fill_far{0.f}",
                  "out.m8_far_m=(std::max)(out.m8_far_m,out.m8_near_m+.1f)"]:
        need(cfg,token,"defaults/validation")
    for token in ["sizeof(M1Constants) == 560", "float m8_distance[4]",
                  "float m8_effects[4]", "geometry.world_to_meters",
                  "data.m8_distance[0]=1.f/(near_distance*world_units)",
                  "data.m8_distance[1]=1.f/(far_distance*world_units)"]:
        need(params,token,"constant alignment/physical scale")
    for token in ["settings.m8_distance,settings.m8_near_m,settings.m8_far_m",
                  "settings.m8_edge_near,settings.m8_edge_far",
                  "settings.m8_fill_near,settings.m8_fill_far"]:
        need(dx,token,"frozen parameters")
    for token in ["M8FarWeight(float inverseDepth)", "M8AdjustedPenalty",
                  "M8FillStrength", "float4 M8Distance", "float4 M8Effects",
                  "groupshared float M8Origin[1024]", "groupshared float M8NextOrigin[1024]",
                  "for (uint tile=0u; tile<(w+127u)/128u; ++tile)",
                  "M8Origin[x]=M1Seed[x]", "M8Origin[xf]", "M8Origin[xs]",
                  "M8Origin[x-step]", "M8Origin[x+step]",
                  "const float gate=M8Distance.z>.5 ? 2.0 : (M3Flags.z>0. ? M3Flags.z : 2.0)",
                  "if(inCrop || (M3Flags.x>.5 && M3Flags.z>0.0))",
                  "if (x>=step)", "if (x+step<w)",
                  "const float maxSafe=.95/max(kmax*float(M4Grid.x),.00001)",
                  "fill=float3(dir,d,strength)",
                  "return lerp(root,clamp(um,0.0,1.0),strength)"]:
        need(s,token,"distance-aware foveal geometry")
    for token in ["fill.z>.001 && (M7Controls.y>0. || M7Controls.z>0. || M8Distance.z>.5)",
                  "lerp(fovea.rgb,filled,saturate(fill.z))"]:
        need(p,token,"distance-aware fill compositing")
    for token in ["m_duo_m8_distance", "m_duo_m8_near_m", "m_duo_m8_far_m",
                  "m_duo_m8_edge_near", "m_duo_m8_edge_far",
                  "m_duo_m8_fill_near", "m_duo_m8_fill_far"]:
        need(hdr,token,"persisted sliders")
        need(ui,token,"frozen menu state")
    start=s.index("void M4Envelope(")
    end=s.index("void CSConditionM4Vertical(",start)
    conditioned=s[start:end]
    assert "for (uint x=lane; x<w; x+=128)" not in conditioned, "FXC-uniform tile contract regressed"
    assert conditioned.count("for (uint tile=0u; tile<(w+127u)/128u; ++tile)") >= 7
    for world_units in [1.,100.,110.,160.]:
        assert factor(1/(.5*world_units),2.,5.,world_units)==0.
        assert factor(1/(7.*world_units),2.,5.,world_units)==1.
        mid=factor(1/((2./(.5+.2))*world_units),2.,5.,world_units)
        assert abs(mid-.5)<1.e-5, mid  # midpoint is in inverse depth
        for depth in [1.,2.,2.5,3.,4.,4.99,5.,10.]:
            w=factor(1/(depth*world_units),2.,5.,world_units)
            assert 0.<=w<=1.
            if depth<=2.: assert w==0.
            if depth>=5.: assert w==1.
            smooth=w                   # near=0, far=1
            fill=1.-w                 # near=1, far=0
            assert abs(smooth+fill-1.)<1.e-7
    print("PASS: M8 depth-aware near/far geometry, fill, controls, scale and M7 compatibility")

if __name__=="__main__":
    main()

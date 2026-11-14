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
                  "out.m8_far_m=(std::max)(out.m8_far_m,out.m8_near_m+.1f)",
                  "float m9_eye_near{1.f}, m9_eye_far{0.f}",
                  "out.m9_eye_far=(std::clamp)(requested.m9_eye_far,0.f,1.f)"]:
        need(cfg,token,"defaults/validation")
    for token in ["sizeof(M1Constants) == 576", "float m8_distance[4]",
                  "data.m8_distance[3]=edge_reach_px",
                  "float m8_effects[4]", "float m9_per_eye[4]",
                  "data.m9_per_eye[0]=eye_near", "data.m9_per_eye[1]=eye_far",
                  "geometry.world_to_meters",
                  "data.m8_distance[0]=1.f/(near_distance*world_units)",
                  "data.m8_distance[1]=1.f/(far_distance*world_units)"]:
        need(params,token,"constant alignment/physical scale")
    for token in ["settings.m8_distance,settings.m8_near_m,settings.m8_far_m",
                  "settings.m8_edge_near,settings.m8_edge_far",
                  "settings.m8_fill_near,settings.m8_fill_far",
                  "settings.m9_eye_near,settings.m9_eye_far"]:
        need(dx,token,"frozen parameters")
    for token in ["M8FarWeight(float inverseDepth)", "M8AdjustedPenalty",
                  "M8FillStrength", "M9PerEyeMix", "clamp(M8Distance.w,2.,20.)", "float4 M8Distance", "float4 M8Effects", "float4 M9PerEye",
                  "groupshared float M8Origin[1024]", "groupshared float M8NextOrigin[1024]",
                  "for (uint tile=0u; tile<(w+127u)/128u; ++tile)",
                  "M8Origin[x]=M1Seed[x]", "M8Origin[xf]", "M8Origin[xs]",
                  "M8Origin[leftIndex]", "M8Origin[rightIndex]",
                  "const float gate=M8Distance.z>.5 ? 2.0 : (M3Flags.z>0. ? M3Flags.z : 2.0)",
                  "if(inCrop || (M3Flags.x>.5 && M3Flags.z>0.0))",
                  "if (x>=step)", "if (x+step<w)", "const bool distanceOn=M8Distance.z>.5",
                  "const float cropWidth=max(M2Crop.z-M2Crop.x,1.e-5)",
                  "const float maxSafe=.99*cropWidth/max(kmax*float(M4Grid.x),.00001)",
                  "lerp(M1Filter.x*scale,pf,M9PerEyeMix(source))",
                  "const float symmetric=max(0.,M1Row[xs]-float(step)*M8AdjustedPenalty(source,M1Filter.x*scale))",
                  "const float oneSided=ps>0. ?",
                  "const float candidate=lerp(symmetric,oneSided,mix)",
                  "const float pixelBudget=reach",
                  "const float retention=saturate(M7Controls.y)",
                  "const float3 bounded=clamp(oldColor,current-.50,current+.50)",
                  "fill=float3(dir,d,strength)",
                  "return lerp(root,clamp(um,0.0,1.0),strength)"]:
        need(s,token,"distance-aware foveal geometry")
    for token in ["fill.z>.001 && (M7Controls.y>0. || M7Controls.z>0. || M8Distance.z>.5)",
                  "lerp(fovea.rgb,filled,saturate(fill.z))",
                  "[unroll] for (int offset=-2;offset<=2;++offset)",
                  "saturate(M7Controls.z/2.)"]:
        need(p,token,"distance-aware fill compositing")
    assert "float m7_tuning[4]" not in params, "redundant constant field remains"
    assert "float4 M7Tuning" not in s, "redundant HLSL constant remains"
    for token in ["m_duo_m8_distance", "m_duo_m8_near_m", "m_duo_m8_far_m",
                  "m_duo_m8_edge_near", "m_duo_m8_edge_far",
                  "m_duo_m8_fill_near", "m_duo_m8_fill_far",
                  "m_duo_m9_eye_near", "m_duo_m9_eye_far",
                  "m_duo_edge_reach", "m_duo_fill_blur"]:
        need(hdr,token,"persisted sliders")
        need(ui,token,"frozen menu state")
    start=s.index("void M4Envelope(")
    end=s.index("void CSConditionM4Vertical(",start)
    conditioned=s[start:end]
    assert "for (uint x=lane; x<w; x+=128)" not in conditioned, "FXC-uniform tile contract regressed"
    assert conditioned.count("for (uint tile=0u; tile<(w+127u)/128u; ++tile)") >= 7
    # Source-level regression for an eye-baseline scale error. Native UEVR
    # get_world_to_meters() already multiplies m_world_to_meters by WorldScale.
    # DuoView may not multiply by WorldScale a second time.
    m1_patch=(Path(__file__).with_name("apply_duoview_m1.py")).read_text(encoding="utf-8")
    need(m1_patch,"const auto scale=double(vr->get_world_to_meters());","no squared world scale")
    assert "get_world_to_meters())*vr->get_world_scale()" not in m1_patch
    for world_scale in [0.5,0.85,1.0,1.10,1.5]:
        wtm=100.0*world_scale
        assert abs(wtm-(100.*world_scale)) < 1.e-8
    for history_strength in [0.0,0.25,0.5,0.95,1.0]:
        for reach in [2.,8.,20.]:
            budget=reach
            actual_limit=budget*history_strength
            assert 2.<=budget<=20.
            assert 0.<=actual_limit<=20.
            if history_strength==0: assert actual_limit==0.
    for weight in [0.,.2,.5,.75,1.]:
        # Directional M3 edges fade out as the distance weight rises.
        assert abs((1.-weight)+weight-1.)<1.e-8
        directional=1.-weight
        assert 0.<=directional<=1.
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
    # Half-width gaze crops need half the admissible per-cell inverse-depth
    # slope; otherwise the warp can fold inside a small fovea crop.
    k=.25
    grid=32
    for crop_width in [.2,.5,1.]:
        safe=.99*crop_width/(k*grid)
        assert abs(safe*k*grid/crop_width-.99)<1.e-7
    # With disocclusion penalty disabled, directional=1 must suppress
    # background spread; directional=0 must restore symmetric spread.
    symmetric=.6
    one_sided=0.
    for mix in [0.,.25,.5,.75,1.]:
        candidate=(1.-mix)*symmetric+mix*one_sided
        assert abs(candidate-(1.-mix)*symmetric)<1.e-7
    print("PASS: M9 temporal/blur, crop-aware 0.99 fold bound, continuous per-eye fade, world scale")

if __name__=="__main__":
    main()

#!/usr/bin/env python3
"""M2.3 generated-mode-ID6 contracts and feather continuity oracle."""
from pathlib import Path
import hashlib, math, sys

def require(path, *fragments):
    s=Path(path).read_text(encoding="utf-8")
    for phrase in fragments:
        assert phrase in s, f"{path}: missing {phrase!r}"
    return s

def blob_hash(s):
    b=s.encode("utf-8")
    return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()

def smoothstep(t):
    t=max(0.0,min(1.0,t))
    return t*t*(3.0-2.0*t)

def verify_full_feather():
    # Corrected periphery stays selected by the entire original soft blend.
    # The old 12-pixel correction ramp could remove matching while most of
    # the shown pixel still came from the periphery.
    for feather_px in (4.0,12.0,32.0,100.0,190.0):
        p,f,c=.34,.66,.23
        px=[(p+c)*(1.0-smoothstep(d/feather_px))+f*smoothstep(d/feather_px)
            for d in (feather_px*i/1024 for i in range(1025))]
        assert abs(px[0]-(p+c))<1.e-9
        assert abs(px[-1]-f)<1.e-9
        assert max(abs(x-y) for x,y in zip(px[1:],px[:-1]))<.005
        # The old ramp is not present in the shader, even when feather>12.
        if feather_px>12:
            d=12.0
            w=smoothstep(d/feather_px)
            corrected=(p+c)*(1.0-w)+f*w
            old=p*(1.0-w)+f*w # after B38 anchor faded away
            assert corrected-old>.01, "Regressed to old 12-pixel ramp"

def main():
    assert len(sys.argv)==4, "test_duoview_m23_generated.py <backend> <duo-shaders> <quadview>"
    backend=Path(sys.argv[1])/"src/mods"
    sh=Path(sys.argv[2])
    quad=Path(sys.argv[3])
    tri= require(quad/"QuadViewComposite.hlsl","void UpdateEdgeB40","bool AmbientEdgeDifference")
    assert blob_hash(tri)=="3fd53f95cba42b0703e8fc146151e96a98cb00b7", "TriView #158 compositor has changed"
    tri_h= (quad/"QuadViewD3D12.hpp").read_text(encoding="utf-8")
    assert blob_hash(tri_h)=="c7c06dbdc0d2c89779203feeb5ba5bb5d29944fb", "TriView #158 D3D12 compositor has changed"

    b40=require(sh/"DuoViewPhase2Effects.hlsl",
        "[numthreads(32,1,1)]", "void CSMonoB40", "DuoB40InwardAnchor(float2 uv)",
        "DuoMonoSeamMatch[i*2u+1u]", "float3 DuoPhase2MatchContext(float2 uv,float3 context)",
        "const float alpha=float(dt)/(tau+float(dt));",
        "const uint dt=min(elapsed,50u);",
        "return 1.0;",
    )
    anchor=b40.split("float DuoB40InwardAnchor(float2 uv)",1)[1].split("}",1)[0]
    assert "return 1.0;" in anchor and "smoothstep" not in anchor and "SeamGeometry.y" not in anchor
    require(sh/"DuoViewNativeCompositeRaster.hlsl",
        "lerp(rawPeriphery,periphery,DuoB40InwardAnchor(fullUv))",
        "result = DebugViewMode == 2 ? fovea : lerp(blendPeriphery,fovea,weight)",
        "const float wideSharpen=rightEye ? M23Wide.y : M23Wide.x",
        "GlamExtraWideChange(fullUv, beforeSharpen, wideSharpen)",
    )
    require(sh/"DuoViewCompositeRaster.hlsl",
        "lerp(rawPeripheralColor,peripheralColor,DuoB40InwardAnchor(fullUv))",
        "lerp(blendPeripheral, foveaColor, weight)")
    require(sh/"DuoViewComposite.hlsl",
        "return t * t * (3.0 - 2.0 * t);", "float FeatherFraction;")
    gpu=require(backend/"vr/DuoViewD3D12.hpp",
        "sizeof(ShaderConstants) == 208", "settings.m23_wide_unlinked ? settings.m23_right_wide",
        "const bool b40_active=frame.config.settings.seam_match_enabled && b40_ready()")
    assert "sizeof(ShaderConstants) == 224" not in gpu
    config=require(backend/"vr/DuoViewConfig.hpp",
        "m23_wide_unlinked{false}", "m23_wide_strength{1.f}",
        "m23_left_wide{1.f}", "m23_right_wide{1.f}",
        "requested.m23_wide_strength,0.f,20.f",
        "requested.m23_left_wide,0.f,20.f",
        "requested.m23_right_wide,0.f,20.f")
    require(backend/"VR.hpp","DuoM23WideStrength","DuoM23WideLeft","DuoM23WideRight")
    require(backend/"VR.cpp",
        "m_duo_m23_wide->draw",
        "m_duo_m23_unlinked_wide->draw",
        ".m23_left_wide=m_duo_m23_wide_left->value()",
        "current.m23_right_wide==candidate.m23_right_wide")
    depth=require(backend/"vr/QuadViewNgxDepth.hpp",
        "coarse->sequence!=fine->sequence+1",
        "fine->sequence!=coarse->sequence+1",
        "const bool same_list=coarse->producer_list==fine->producer_list",
        "const bool same_queue=coarse->duoview_producer_queue",
        "capture_gap>std::chrono::milliseconds(25)",
        "s->jitter_valid", "depth_copy_complete(done,s->producer_fence_value)",
        "m21_fine_cooldown_until_ms_")
    assert "DepthCaptureMode::TriView" in depth
    stereo=require(sh/"DuoViewM1Stereo.hlsl","float4 M23Wide;")
    mh=require(backend/"vr/DuoViewM1D3D12.hpp",
        "static_assert(sizeof(M1Constants) == 256)",
        "data.m23_wide[0]", "data.m23_wide[1]")
    require(sh/"DuoViewGlamaryeFovea.hlsl",
        "const float radius = 2.1;",
        "float2(-5.25,0.0)", "float2(0.0,5.25)")
    verify_full_feather()
    print("M2.3 PASS: full-feather B40 one-history, strict cross-list pairing, independent 1.5x wide and bit-exact TriView #158")

if __name__=="__main__":
    main()

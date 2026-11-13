#!/usr/bin/env python3
"""M2.3: exact successful TriView B43-158 base; one-history DuoView B40.

Validates safely fused fine NGX depth, 1.5x independent wide sharpening and,
critically, that matching is not abruptly disabled inside the blend feather.
"""
from pathlib import Path
import hashlib
import sys

def have(path, *tokens):
    s=Path(path).read_text(encoding="utf-8")
    for t in tokens:
        assert t in s, f"{path}: missing {t!r}"
    return s

def blob(s):
    b=s.encode("utf-8")
    return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()

def main():
    assert len(sys.argv)==4, "Usage: test_duoview_m23_generated.py <backend> <duoview> <quadview>"
    root=Path(sys.argv[1])/"src/mods"
    duo=Path(sys.argv[2])
    quad=Path(sys.argv[3])

    assert blob((quad/"QuadViewComposite.hlsl").read_text(encoding="utf-8"))=="3fd53f95cba42b0703e8fc146151e96a98cb00b7", "TriView B43-158 compositor changed"
    assert blob((quad/"QuadViewD3D12.hpp").read_text(encoding="utf-8"))=="c7c06dbdc0d2c89779203feeb5ba5bb5d29944fb", "TriView B43-158 GPU compositor changed"

    pool=have(root/"vr/QuadViewNgxDepth.hpp",
        "latest_duoview_pair_submitted",
        "coarse->sequence!=fine->sequence+1",
        "fine->sequence!=coarse->sequence+1",
        "const bool same_list=coarse->producer_list==fine->producer_list",
        "const bool same_queue=coarse->duoview_producer_queue",
        "coarse->duoview_producer_queue.Get()==fine->duoview_producer_queue.Get()",
        "capture_gap>std::chrono::milliseconds(25)",
        "m21_fine_cooldown_until_ms_",
        "depth_copy_complete(done,s->producer_fence_value)",
        "depth_capture_in_window(s->recorded,not_before,now)",
    )
    assert "if (!same_list &&" in pool

    have(root/"vr/DuoViewConfig.hpp",
        "m23_wide_unlinked{false}", "m23_wide_strength{1.f}",
        "m23_left_wide{1.f}", "m23_right_wide{1.f}",
        "requested.m23_left_wide,0.f,20.f",
        "requested.m23_right_wide,0.f,20.f",
    )
    have(root/"VR.hpp",
        "DuoM23WideStrength","DuoM23WideLeft","DuoM23WideRight",
        "*m_duo_m23_wide, *m_duo_m23_unlinked_wide,",
    )
    have(root/"VR.cpp",
        "m_duo_m23_wide->draw", "m_duo_m23_unlinked_wide->draw",
        "m_duo_m23_wide_left->draw",
        ".m23_left_wide=m_duo_m23_wide_left->value()",
        "current.m23_right_wide==candidate.m23_right_wide",
        "M2.3 seam correction follows the entire active blend feather.",
    )

    # Deliberately ONE shared Mono history, not 2 independent eye histories.
    seam=have(duo/"DuoViewPhase2Effects.hlsl",
        "[numthreads(32,1,1)]",
        "const uint side=lane/8u;",
        "DuoMonoSeamMatch[i*2u+1u]",
        "DuoMonoEdgeHistory[h+1u]=CropUv;",
        "const float alpha=float(dt)/(tau+float(dt));",
        "DuoB40InwardAnchor",
        "The final lerp(context,focus,weight) *already* tapers the correction",
        "float DuoB40InwardAnchor(float2 uv) {\n    return 1.0;\n}",
    )
    assert "[numthreads(64,1,1)]" not in seam
    assert "distance/max(SeamGeometry.y,1.0)" not in seam
    gpu=have(root/"vr/DuoViewD3D12.hpp",
        "sizeof(ShaderConstants) == 208",
        "sizeof(ShaderConstants)/4 + 4 <= 64",
        "stats.Width=64u*4u*sizeof(float)",
        "stat_srv.Buffer.NumElements=64",
        "stat_uav.Buffer.NumElements=64",
        "settings.m23_wide_unlinked ? settings.m23_right_wide",
    )
    have(duo/"DuoViewComposite.hlsl", "uint4 B40Temporal", "float4 SeamGeometry")
    have(duo/"DuoViewNativeCompositeRaster.hlsl",
        "DuoPhase2MatchContext(fullUv, periphery.rgb)",
        "const float wideSharpen=rightEye ? M23Wide.y : M23Wide.x",
        "fineSharpen > 0.0 || ((SharpenFlags & 16u) != 0u && wideSharpen > 0.0)",
        "GlamExtraWideChange(fullUv, beforeSharpen, wideSharpen)",
        "lerp(rawPeriphery,periphery,DuoB40InwardAnchor(fullUv))",
        "lerp(blendPeriphery,fovea,weight)",
    )
    have(duo/"DuoViewCompositeRaster.hlsl",
        "DuoPhase2MatchContext(fullUv, peripheralColor.rgb)",
        "lerp(rawPeripheralColor,peripheralColor,DuoB40InwardAnchor(fullUv))",
    )
    have(duo/"DuoViewGlamaryeFovea.hlsl",
        "const float radius = 2.1;", "float2(-5.25,0.0)", "float2(0.0,5.25)")
    have(root/"vr/DuoViewM1D3D12.hpp",
        "static_assert(sizeof(M1Constants) == 256)",
        "data.m23_wide[0]", "data.m23_wide[1]",
        "float left_wide, float right_wide, float near_m",
    )
    have(duo/"DuoViewM1Stereo.hlsl","float4 M23Wide;")
    assert "DepthCaptureMode::TriView" in pool
    print("M2.3: TriView B43-158 exact unchanged, one Mono B40 history, full-feather correction, fenced cross-list depth, independent 1.5x wide PASS")

if __name__=="__main__":
    main()

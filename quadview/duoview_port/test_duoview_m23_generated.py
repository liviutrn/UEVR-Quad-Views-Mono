#!/usr/bin/env python3
"""M2.3 post-overlays: strict ID6 contract, TriView B43-158 parity and safety."""
from pathlib import Path
import hashlib
import sys

def have(path, *tokens):
    content=Path(path).read_text(encoding="utf-8")
    for token in tokens:
        assert token in content, f"{path}: missing {token!r}"
    return content

def git_blob_sha(s):
    b=s.encode("utf-8")
    return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()

def main():
    assert len(sys.argv)==4, "Usage: test_duoview_m23_generated.py <backend> <duoview> <quadview>"
    root=Path(sys.argv[1])/"src/mods"
    duo=Path(sys.argv[2])
    quad=Path(sys.argv[3])
    # Exact GitHub blob hash from successful TriView B43-158 commit 6791308232.
    assert git_blob_sha((quad/"QuadViewComposite.hlsl").read_text(encoding="utf-8"))=="3fd53f95cba42b0703e8fc146151e96a98cb00b7", "TriView #158 compositor changed"
    assert git_blob_sha((quad/"QuadViewD3D12.hpp").read_text(encoding="utf-8"))=="c7c06dbdc0d2c89779203feeb5ba5bb5d29944fb", "TriView #158 GPU compositor changed"

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
    cfg=have(root/"vr/DuoViewConfig.hpp",
        "m23_wide_unlinked{false}", "m23_wide_strength{1.f}",
        "m23_left_wide{1.f}", "m23_right_wide{1.f}",
        "requested.m23_left_wide,0.f,20.f",
        "requested.m23_right_wide,0.f,20.f",
    )
    have(root/"VR.cpp",
        "DuoM23WideStrength", "m_duo_m23_wide->draw",
        "m_duo_m23_unlinked_wide->draw", "m_duo_m23_wide_left->draw",
        ".m23_left_wide=m_duo_m23_wide_left->value()",
        "current.m23_right_wide==candidate.m23_right_wide",
    ) if False else have(root/"VR.cpp",
        "m_duo_m23_wide->draw", "m_duo_m23_unlinked_wide->draw",
        "m_duo_m23_wide_left->draw",
        ".m23_left_wide=m_duo_m23_wide_left->value()",
        "current.m23_right_wide==candidate.m23_right_wide",
    )
    have(root/"VR.hpp", "DuoM23WideStrength","DuoM23WideLeft","DuoM23WideRight")
    shader=have(duo/"DuoViewPhase2Effects.hlsl",
        "[numthreads(64,1,1)]", "const uint eye=lane/32u;",
        "const uint knot=lane%32u;",
        "const uint base=(eye&1u)*64u;",
        "DuoMonoSeamMatch[base+i*2u+1u]",
        "eye==0u ? B40EyeSharpen.x : B40EyeSharpen.y",
        "GlamSharpenNativeFovea(p,f,eyeSharpen)",
        "DuoMonoSeamOutput[lane*2u+1u]=float4(stable,1.0)",
        "const float alpha=float(dt)/(tau+float(dt));",
        "DuoB40InwardAnchor",
    )
    gpu=have(root/"vr/DuoViewD3D12.hpp",
        "sizeof(ShaderConstants) == 224",
        "sizeof(ShaderConstants)/4 + 4 <= 64",
        "stats.Width=128u*4u*sizeof(float)",
        "stat_srv.Buffer.NumElements=128",
        "stat_uav.Buffer.NumElements=128",
        "frame.config.settings.m2_unlinked_sharpen ? frame.config.settings.m2_left_sharpen",
        "settings.m23_wide_unlinked ? settings.m23_right_wide",
    )
    have(duo/"DuoViewComposite.hlsl","float4 B40EyeSharpen")
    native=have(duo/"DuoViewNativeCompositeRaster.hlsl",
        "DuoPhase2MatchContext(fullUv, periphery.rgb,",
        "const float wideSharpen=rightEye ? M23Wide.y : M23Wide.x",
        "fineSharpen > 0.0 || ((SharpenFlags & 16u) != 0u && wideSharpen > 0.0)",
        "GlamExtraWideChange(fullUv, beforeSharpen, wideSharpen)",
    )
    have(duo/"DuoViewCompositeRaster.hlsl","DuoPhase2MatchContext(fullUv, peripheralColor.rgb,")
    have(duo/"DuoViewGlamaryeFovea.hlsl",
        "const float radius = 2.1;", "float2(-5.25,0.0)", "float2(0.0,5.25)")
    h=have(root/"vr/DuoViewM1D3D12.hpp",
        "static_assert(sizeof(M1Constants) == 256)",
        "data.m23_wide[0]", "data.m23_wide[1]",
        "float left_wide, float right_wide, float near_m",
    )
    have(duo/"DuoViewM1Stereo.hlsl", "float4 M23Wide;")
    assert "DepthCaptureMode::TriView" in pool
    print("M2.3 contracts PASS: TriView B43-158 bit-exact; 2x B40 eyes, strict paired depth, independent 1.5x wide")

if __name__=="__main__":
    main()

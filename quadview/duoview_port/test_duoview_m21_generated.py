#!/usr/bin/env python3
"""M2.1 generated-backend source contracts after all M2 overlays."""
from pathlib import Path
import sys


def have(path: Path, *patterns: str):
    content=path.read_text(encoding="utf-8")
    for phrase in patterns:
        assert phrase in content, f"{path}: missing {phrase!r}"
    return content


def main():
    assert len(sys.argv)==3
    root=Path(sys.argv[1])/"src/mods"
    vr=root/"vr"
    shaders=Path(sys.argv[2])
    cfg=have(vr/"DuoViewConfig.hpp",
        "bool m2_fovea_depth{false};", "bool m21_depth_debug{false};", "bool m21_jitter_correct{false};",
        "requested.m2_right_sharpen,0.f,20.f")
    have(vr.parent/"VR.hpp", 'DuoM21DepthDebug')
    have(root/"VR.cpp", 'm_duo_m21_depth_debug->draw',
         'Depth edge sharpness (higher = harder edge)',
         'm21_depth_debug==candidate.m21_depth_debug',
         'm21_jitter_correct==candidate.m21_jitter_correct')
    pool=have(vr/"QuadViewNgxDepth.hpp",
         "latest_duoview_pair_submitted",
         "coarse->sequence!=fine->sequence+1",
         "coarse->producer_list!=fine->producer_list",
         "coarse->list_epoch!=fine->list_epoch",
         "m21_fine_cooldown_until_ms_",
         "const bool fits=candidate->texture",
         "m21_stats() const", "m21_alloc_", "m21_full_")
    have(vr/"D3D12Component.cpp",
         "depths.latest_duoview_pair_submitted",
         "pair.first ? pair.first",
         "pair.first==snapshot && pair.second",
         "[DuoView][M2.1]")
    assert "std::chrono::milliseconds(25)" not in (
        vr/"D3D12Component.cpp").read_text(encoding="utf-8"), "unsafe old M2 time-only pairing remains"
    have(vr/"DuoViewD3D12.hpp","settings.m21_depth_debug", "settings.m21_jitter_correct",
         "m1_raw_range.NumDescriptors=2", "m2_fovea_srv_")
    hdr=have(vr/"DuoViewM1D3D12.hpp",
         "bool depth_debug", "data.m2_sharpen[2]", "data.m2_sharpen[3]",
         "std::clamp)(right_sharpen,0.f,20.f)",
         "if(fine_ok)", "data.filter[0]=softness/")
    assert "sizeof(M1Constants) == 240" in hdr
    shader=have(shaders/"DuoViewM1Stereo.hlsl",
         "M2RawFoveaDepth : register(t5)",
         "DecodeM2Depth(fineCenter+int2(fx,fy))",
         "nearDepth=lerp(nearDepth,fineNear,feather)",
         "M1ConditionedDepth[uint2(x,group.x)] = M1Row[x]",
         "M1ReadConditioned", "const float2 unjittered=", "M2Sharpen.w>.5 ? M1Eye.zw",
         "for(uint iteration=1u;iteration<8u")
    raster=shader.split("#ifdef DUOVIEW_M1_RASTER",1)[-1]
    assert "M2RawFoveaDepth.Load" not in raster, "raw fine depth leaked into pixel warp"
    assert "M2FusedInverseDepth" not in raster, "unsafe post-limit fusion remains"
    have(shaders/"DuoViewNativeCompositeRaster.hlsl",
         "M2Sharpen.z > .5 ? outputUv : M1PullUv",
         "GlamExtraWideChange(fullUv, beforeSharpen, fineSharpen)",
         "M1ReadConditioned(pos+float2(delta.x,0))")
    have(shaders/"DuoViewGlamaryeFovea.hlsl",
         "float3 GlamExtraWideChange(float2 uv, float3 original, float strength)",
         "1.0/max(strength,.00001)+abs(detail)/possible")
    assert "DepthCaptureMode::TriView" in pool
    print("M2.1 generated pairing, diagnostics, 20-sharpen, compute-first fusion and TriView isolation contracts: PASS")


if __name__=="__main__":
    main()

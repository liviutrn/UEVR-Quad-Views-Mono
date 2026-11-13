#!/usr/bin/env python3
"""M2 regression contracts on the *generated* DX12 backend, not source snippets."""
from pathlib import Path
import sys


def require(path: Path, *phrases: str):
    text=path.read_text(encoding="utf-8")
    for fragment in phrases:
        assert fragment in text, f"{path}: missing {fragment!r}"


def main():
    if len(sys.argv)!=3: raise SystemExit("test_duoview_m2_generated.py <backend> <shader-source>")
    vr=Path(sys.argv[1])/"src/mods/vr"
    sh=Path(sys.argv[2])
    require(vr/"DuoViewConfig.hpp","m2_unlinked_sharpen","m2_fovea_depth",
            "m2_left_sharpen","m2_right_sharpen")
    require(vr.parent/"VR.cpp","Separate left/right sharpening",
            "M2 fine fovea depth (if matched)","m2_right_sharpen==candidate.m2_right_sharpen")
    require(vr/"QuadViewNgxDepth.hpp",
            "latest_duoview_fovea_submitted","slot->duoview_fovea = fine_output",
            "request && slot->duoview_fovea != want_fovea",
            "if (!duo) prune_locked(want_w,want_h,false)",
            "if (!coarse_output && !fine_output)")
    require(vr/"DuoViewD3D12.hpp",
            "const M1DepthInput* stereo_fovea_depth = nullptr",
            "m2_fovea_srv_","m1_raw_range.NumDescriptors=2",
            "m1_.fovea_depth_lease.reset()","m1_.fovea_depth_active",
            "settings.m2_fovea_depth ? stereo_fovea_depth : nullptr")
    require(vr/"DuoViewM1D3D12.hpp",
            "static_assert(sizeof(M1Constants) == 240)",
            "D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT",
            "fovea_depth_lease","fovea_depth_active=fine_ok",
            "CreateShaderResourceView(fine_ok ? focus->texture : nullptr")
    require(vr/"D3D12Component.cpp",
            "latest_duoview_fovea_submitted",
            "std::chrono::milliseconds(25)",
            "fine_depth ? &*fine_depth : nullptr")
    # M2.1 replaces unsafe post-limit raw fine fusion by conditioning the
    # blended near-max seed BEFORE the global slope envelope. Accept either
    # implementation here; the M2.1-specific suite requires the safe one.
    stereo=(sh/"DuoViewM1Stereo.hlsl").read_text(encoding="utf-8")
    if "M2FusedInverseDepth(uv,d)" in stereo:
        require(sh/"DuoViewM1Stereo.hlsl",
                "M2RawFoveaDepth : register(t5)",
                "M2FoveaFlags.w < .5",
                "return lerp(coarse,fine,feather)")
    else:
        require(sh/"DuoViewM1Stereo.hlsl",
                "M2RawFoveaDepth : register(t5)",
                "nearDepth=lerp(nearDepth,fineNear,feather)",
                "M1ReadConditioned")
    require(sh/"DuoViewNativeCompositeRaster.hlsl",
            "const float fineSharpen=i.pos.x>=OutputSize.x ? M2Sharpen.y : M2Sharpen.x",
            "GlamSharpenNativeFovea(fullUv,fovea.rgb,fineSharpen)")
    require(sh/"DuoViewGlamaryeFovea.hlsl",
            "float3 GlamSharpenNativeFovea(float2 fullUv, float3 center, float strength)",
            "return GlamSharpenNativeFovea(uv,c,SharpenStrength)")
    # Guard against accidental shader contributions in the TriView path.
    q=sh/"DuoViewNativeCompositeRaster.hlsl"
    shader=q.read_text(encoding="utf-8")
    assert shader.count("#ifdef DUOVIEW_M1_RASTER")>=2
    print("M2 generated settings/capture/ownership/SRV/FXC input contracts: PASS")


if __name__=="__main__":
    main()

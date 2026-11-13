#!/usr/bin/env python3
"""M2.2 generated shader contract checks after M2.1 and jitter overlays.

These are complementary to the real DX12 WARP fixture and 4000px numerical
oracle. Exact source assertions prevent silent regressions in build overlays.
"""
from pathlib import Path
import sys


def main():
    if len(sys.argv)!=2:
        raise SystemExit("Usage: test_duoview_m22_generated.py <duoview-shaders>")
    folder=Path(sys.argv[1])
    stereo=(folder/"DuoViewM1Stereo.hlsl").read_text(encoding="utf-8")
    raster=(folder/"DuoViewNativeCompositeRaster.hlsl").read_text(encoding="utf-8")

    for token in (
        "for(int fy=-2;fy<=2;++fy)",
        "for(int fx=-2;fx<=2;++fx)",
        "DecodeM2Depth(fineCenter+int2(fx,fy))",
        "if(fineNear>0.0) nearDepth=lerp(nearDepth,fineNear,feather)",
        "M1ConditionedDepth[uint2(x,group.x)] = M1Row[x]",
        "rLo-rHi>1.e-9",
        "root=lo+(hi-lo)*rLo/(rLo-rHi)",
        "uv.x=clamp(root,lo,hi)",
        "for(uint iteration=0u;iteration<8u;++iteration)",
    ):
        assert token in stereo, f"M2.2 stereo source missing: {token}"

    # No new depth texture lookup is permitted in the per-eye warp:
    # eight iterations, no per-eye raw-fovea reads, no second grid.
    warp=stereo.split("#ifdef DUOVIEW_M1_RASTER",1)[-1]
    assert "M2RawFoveaDepth.Load" not in warp
    assert warp.count("M1ReadConditioned(float2(mid,base.y))")==1

    for token in (
        "const float slopePerPixel=max(M1Filter.x*float(M1Grid.x)/",
        "const float relativeEdge=edge/slopePerPixel;",
        "smoothstep(0.08,0.32,relativeEdge)",
        "result.rgb=lerp(result.rgb,float3(1.0,0.02,0.04),emphasis*.95);",
    ):
        assert token in raster, f"M2.2 contrast diagnostic missing: {token}"
    assert "8.0*edge/max(mid,0.05)" not in raster
    print("M2.2 generated 5x5 fine depth, subpixel bracket, 4K overlay: PASS")


if __name__=="__main__":
    main()

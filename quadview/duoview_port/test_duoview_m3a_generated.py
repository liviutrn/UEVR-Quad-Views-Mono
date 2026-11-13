#!/usr/bin/env python3
"""Generated-source contracts for the M3a combined build."""
import re
import sys
from pathlib import Path


def need(text, needle, label, count=1):
    found = text.count(needle)
    if found != count:
        raise SystemExit(f"FAIL {label}: expected {count}, found {found}: {needle[:90]!r}")
    print(f"PASS {label}")


def main():
    backend, shaders = Path(sys.argv[1]), Path(sys.argv[2])
    vr = backend/"src/mods/vr"
    hlsl = (shaders/"DuoViewM1Stereo.hlsl").read_text(encoding="utf-8")
    m1 = (vr/"DuoViewM1D3D12.hpp").read_text(encoding="utf-8")
    dx = (vr/"DuoViewD3D12.hpp").read_text(encoding="utf-8")
    cfg = (vr/"DuoViewConfig.hpp").read_text(encoding="utf-8")
    vrh = (backend/"src/mods/VR.hpp").read_text(encoding="utf-8")
    vrc = (backend/"src/mods/VR.cpp").read_text(encoding="utf-8")
    ngx = (vr/"QuadViewNgxDepth.hpp").read_text(encoding="utf-8")
    d3d = (vr/"D3D12Component.cpp").read_text(encoding="utf-8")

    # Shared mapping between the M2.5a content gate and the fusion seed (review item 3).
    need(hlsl, "M1CoarseCorrection()", "coarse correction helper used by gate and seed", 3)
    need(hlsl, "M2FineJitter()", "fine jitter helper used by gate and seed", 3)
    need(hlsl, "M2Sharpen.w>.5 ? M1Eye.zw :", "no private copies of the coarse correction", 0)
    need(hlsl, "local+M2FoveaFlags.xy", "no private copies of the fine jitter", 0)
    # Parallel guard.
    need(hlsl, "[numthreads(256,1,1)]\nvoid CSGuardM25(", "guard runs as one 256-thread group")
    need(hlsl, "[numthreads(1,1,1)]", "no single-thread guard left", 0)
    # Per-eye conditioning.
    need(hlsl, "RWTexture2DArray<float> M1ConditionedDepth : register(u2);", "two-slice R32 UAV (typed load always supported)")
    need(hlsl, "Texture2DArray<float> M1SoftDepth : register(t3);", "two-slice SRV in raster")
    need(hlsl, "[branch] if (M3Flags.x < .5) {", "OFF keeps the original symmetric envelope")
    need(hlsl, "M3Envelope(w,lane,0u,limit);", "left-eye one-sided envelope")
    need(hlsl, "M3Envelope(w,lane,1u,limit);", "right-eye one-sided envelope")
    need(hlsl, "M1ReadConditionedEye(float2(mid,base.y),eye)", "bisection reads this eye's slice")
    need(hlsl, "if(M3Flags.x>.5 && M3Flags.z>0.0) uv.x=M3FillHole(", "fill only when M3 edges + fill are on")
    need(hlsl, "if(slices==1u) M1ConditionedDepth[uint3(col,y,1u)]=M1Row[y];", "vertical OFF path mirrors slice 0 into slice 1")
    if re.search(r"M1ConditionedDepth\[uint2\(", hlsl):
        raise SystemExit("FAIL a 2D index into the array UAV remains")
    print("PASS no 2D indices into the array UAV")
    # C++ constants and resources.
    need(m1, "static_assert(sizeof(M1Constants) == 320);", "constants grew by two float4")
    need(m1, "texture.DepthOrArraySize = 2; // M3a", "two-slice conditioned texture")
    need(m1, "data.m3_slopes[e]=fold/scale;", "per-eye occlusion penalty from |k_e|")
    need(m1, "data.m3_slopes[2+e]=m3_fill ? 0.f : softness/scale;", "membrane side only when fill is OFF")
    need(dx, "settings.m3_edges,settings.m3_fold_sharpness,settings.m3_fill,settings.m3_jitter_mode,", "writer receives settings")
    need(dx, "soft_array_srv.Texture2DArray.ArraySize=2;", "array SRV for the conditioned field")
    need(dx, "soft_uav.Texture2DArray.ArraySize=2;", "array UAV for the conditioned field")
    need(dx, "device->CreateShaderResourceView(nullptr,&soft_srv,", "null SRVs keep the Texture2D description", 2)
    # Settings and menu.
    need(cfg, "bool m3_edges{false};", "M3 edges default OFF")
    need(cfg, "uint32_t m3_jitter_mode{0};", "jitter mode default legacy")
    need(vrh, 'generate_name("DuoM25DepthDebug")', "debug selector has its own persistence key")
    need(vrh, 'generate_name("DuoM21DepthDebug")', "old bool key no longer re-typed", 0)
    need(vrc, 'm_duo_m24_distance->draw(', "distance fade drawn once (sharpening group)")
    need(vrc, 'm_duo_m2_unlinked->draw(', "per-eye sharpen drawn once (sharpening group)")
    # Contract C2 producer.
    need(ngx, '#include "UevrSourceRolesProducer.hpp"', "producer header included")
    need(ngx, "uevr::contracts::SourceRoleTable::self().note(", "roles published from the NGX hook")
    need(d3d, 'extern "C" __declspec(dllexport) int __cdecl UEVR_GetSourceRolesV1(UevrSourceRolesV1* out)', "C2 export")
    for name in ("UevrSourceRolesV1.h", "UevrSourceRolesProducer.hpp"):
        if not (vr/name).is_file():
            raise SystemExit(f"FAIL {name} not copied into the backend")
    print("PASS contract headers present")
    print("M3a generated contracts: all checks passed")


if __name__ == "__main__":
    main()

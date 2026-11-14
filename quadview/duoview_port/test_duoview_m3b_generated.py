#!/usr/bin/env python3
"""Generated-source contracts for the opt-in M3b feature batch."""
from pathlib import Path
import sys
import re

def need(s,needle,label,count=1):
    n=s.count(needle)
    if n!=count:raise SystemExit(f"FAIL {label}: {n} occurrences (expected {count}) of {needle!r}")
    print("PASS:",label)

def main():
    if len(sys.argv)!=3:raise SystemExit("usage: test_duoview_m3b_generated.py <backend> <shaders>")
    mods=Path(sys.argv[1])/"src/mods";sh=Path(sys.argv[2])
    vr=mods/"vr"
    cfg=(vr/"DuoViewConfig.hpp").read_text(encoding="utf-8")
    header=(mods/"VR.hpp").read_text(encoding="utf-8")
    ui=(mods/"VR.cpp").read_text(encoding="utf-8")
    dx=(vr/"DuoViewD3D12.hpp").read_text(encoding="utf-8")
    backend=(vr/"DuoViewM1D3D12.hpp").read_text(encoding="utf-8")
    hlsl=(sh/"DuoViewM1Stereo.hlsl").read_text(encoding="utf-8")
    raster=(sh/"DuoViewNativeCompositeRaster.hlsl").read_text(encoding="utf-8")
    embed=(Path(__file__).resolve().parent/"embed_duoview_b40.py").read_text(encoding="utf-8")
    keys={
        "DuoM3bTemporal":"m3b_temporal",
        "DuoM3bTemporalStrength":"m3b_temporal_strength",
        "DuoM3bEdgeRepair":"m3b_edge_repair",
        "DuoM3bEdgeRepairMask":"m3b_edge_mask",
        "DuoM3bColorEdges":"m3b_color_edges",
        "DuoM3bGateTune":"m3b_gate_tuning",
        "DuoM25AgreeTolerance":"m3b_agree_tolerance",
        "DuoM25RatioLow":"m3b_ratio_low",
        "DuoM25RatioHigh":"m3b_ratio_high",
        "DuoM25Contrast":"m3b_contrast",
    }
    for key,field in keys.items():
        need(header,f'generate_name("{key}")',key+" persisted key")
        need(cfg,field+"{",field+" default")
        need(cfg,"out."+field+"=",field+" validation",2 if field=="m3b_ratio_high" else 1)
        assert len(re.findall(r"(?m)^\s*\."+re.escape(field)+r"\s*=", ui)) == 1, field+" frozen assignment missing or duplicated"
        need(ui,"current."+field+"==candidate."+field,field+" equality")
    for s in ("bool m3b_gate_tuning{false};","bool m3b_edge_repair{false};",
              "bool m3b_color_edges{false};","bool m3b_temporal{false};"):
        need(cfg,s,"OFF default "+s)
    need(cfg,"float m3b_temporal_strength{.6f};","temporal stock strength")
    need(cfg,"float m3b_agree_tolerance{.03f};","agreement stock")
    need(cfg,"float m3b_ratio_low{.60f};","ratio low stock")
    need(cfg,"float m3b_ratio_high{.85f};","ratio high stock")
    need(cfg,"float m3b_contrast{.10f};","contrast stock")
    need(header,'"Auto (GPU score)"',"Auto menu option")
    need(backend,"static_assert(sizeof(M1Constants) == 448);","constant buffer grow")
    need(backend,"std::array<uint64_t,12> m25_take_gpu_window()","12 counters")
    for shader in ("CSJitterScoreM3b","CSSeedM3b","CSStabilizeM3b"):
        need(hlsl,"void "+shader+"(",shader+" shader")
        need(embed,'("'+shader+'","cs_5_0"',shader+" FXC registration")
    for a in ("m3b_seed_pipeline","m3b_stabilize_pipeline","m3b_jitter_score"):
        if not a in backend:raise SystemExit("FAIL missing pipeline "+a)
    for reg in ("register(t8)","register(t9)","register(t10)","register(u5)","register(u6)"):
        need(hlsl,reg,"temporal resource register "+reg)
    need(hlsl,"M3bStabilizedRead.Load(int3(x,group.x,0))","temporal seed branch")
    need(hlsl,"M3bGuidedCoarse(unjittered)","colour-guided conditional in legacy and temporal seed",2)
    need(hlsl,"M3bRepairRoot(uv,eye,rootClamped,repairStatus)","repair conditional")
    need(hlsl,"if(M3bTemporal.z>.5)","history-valid branch")
    need(hlsl,"M3bRepairFlags.x>.5","repair OFF gate")
    need(hlsl,"M3bColorFlags.x>.5","colour OFF gate",2)
    need(hlsl,"M3bTemporal.x>.5","temporal OFF gate")
    need(hlsl,"M3bOptions.x>.5","tuning OFF gate",5)
    need(dx,"m1_raw_range.NumDescriptors=7","t4..t10 range")
    need(dx,"m1_output_range.NumDescriptors=5","u2..u6 range")
    need(dx,"hd.NumDescriptors = 17;","17 shader-visible descriptors")
    need(raster,"const uint debugEye=i.pos.x>=OutputSize.x ? 1u : 0u;","per-eye depth visual")
    need(raster,"M1ReadConditionedEye(fullUv,rightEye ? 1u : 0u)","per-eye sharpen fade")
    delivery=(vr/"D3D12Component.cpp").read_text(encoding="utf-8")
    need(delivery,'[DuoView][M3b] gate',"one-second M3b runtime gate log")
    need(delivery,'m25_ms+1000',"gate log period 1 second")
    if "DuoFrameGenDepth" in cfg or "XrCompositionLayerDepthInfoKHR" in dx:
        raise SystemExit("FAIL P6 partial integration is forbidden")
    print("M3b generated contracts: all checks passed")

if __name__=="__main__":main()

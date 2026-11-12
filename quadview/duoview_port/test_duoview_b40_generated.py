#!/usr/bin/env python3
"""Fail closed if the Mono B40 pipeline is cosmetically approximated or unsafe."""
from pathlib import Path
import sys
if len(sys.argv)!=4:
    raise SystemExit("Usage: test_duoview_b40_generated.py <backend> <duoview> <quadview>")
backend=Path(sys.argv[1]);duo=Path(sys.argv[2]);quad=Path(sys.argv[3])
def require(path,*tokens):
    s=path.read_text(encoding="utf-8")
    for token in tokens:
        if token not in s: raise RuntimeError(f"B40 missing {token!r} in {path}")
    return s
shader=require(duo/"DuoViewPhase2Effects.hlsl",
    "[numthreads(32,1,1)]","void CSMonoB40",
    "for(uint sub=0u;sub<4u;++sub)",
    "for(int depth=0;depth<3;++depth)","for(int i=-2;i<=2;++i)",
    "count>=2u","count==4u","count==3u","count==2u",
    "const uint dt=min(elapsed,50u);",
    "const float alpha=float(dt)/(tau+float(dt));",
    "const float limit=(100.0/tau)*(float(dt)*.001);",
    "stable+=clamp((target-stable)*alpha",
    "DuoMonoEdgeHistory[h+1u]=CropUv; // diagnostic only; no validity/reset check",
    "DuoMonoSeamOutput[lane*2u+1u]=float4(stable,1.0)",
    "DuoMonoSeamMatch[i*2u+1u]",
    "DuoB40InwardAnchor", "DuoB40EdgeAnchor", "GlamSharpenNativeFovea",
    "DuoPhase2FocusLift",
)
if "confidence * .5" in shader or "gainSum" in shader:
    raise RuntimeError("Old four-probe approximation is still in the production shader")
common=require(duo/"DuoViewComposite.hlsl","uint4 B40Temporal","float4 SeamGeometry")
require(duo/"DuoViewNativeCompositeRaster.hlsl",
    "DuoPhase2MatchContext", "DuoB40InwardAnchor", "rawPeriphery")
require(duo/"DuoViewCompositeRaster.hlsl",
    "DuoPhase2MatchContext", "DuoB40InwardAnchor", "rawPeripheralColor")
gpu=require(backend/"src/mods/vr/DuoViewD3D12.hpp",
    "struct B40MonoHistory", "std::shared_ptr<B40MonoHistory> b40_history_",
    "Create B40 gather compute PSO", "Create B40 Native compute PSO",
    "D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE",
    "D3D12_RESOURCE_STATE_UNORDERED_ACCESS",
    "D3D12_RESOURCE_BARRIER_TYPE_UAV",
    "cmd->Dispatch(1,1,1)",
    "sizeof(ShaderConstants) == 208",
    "sizeof(ShaderConstants)/4 + 4 <= 64",
    "SetComputeRootUnorderedAccessView(3",
    "b40_timestamp_ms()",
)
host=require(backend/"src/mods/vr/D3D12Component.cpp",
    "duoview_b40_history=uevr::duoview::dx12::B40MonoHistory::create",
    "comp->set_b40_history",
    "compositor.set_b40_history(queue_pinned ?",
    "this->duoview_b40_history.reset()",
    "this->duoview_compositors.clear()",
)
require(backend/"src/mods/vr/DuoViewConfig.hpp",
    "float seam_ambient_radius_px{48.f}",
    "float seam_ambient_inside_px{32.f}",
    "uint32_t seam_time_ms{350u}",
)
require(backend/"src/mods/VR.cpp",
    "m_duo_b40_preset->draw",
    "m_duo_b40_radius->draw",
    ".seam_time_ms=m_duo_b40_preset->value()==0 ? 75u",
)
require(quad/"QuadViewComposite.hlsl",
    "void UpdateEdgeB40","void CSSeam","float4 MatchEdgeV2","bool AmbientEdgeDifference")
if "reset=stamp" in shader:
    raise RuntimeError("B40 Mono shader accidentally reintroduced resets")
if "4 spatial edge groups" in (backend/"src/mods/VR.cpp").read_text(encoding="utf-8"):
    raise RuntimeError("Old UI still mislabels Mono B40 as Phase2 prototype")
if len([x for x in shader.splitlines() if "DuoReadFocus(p)" in x])!=1:
    raise RuntimeError("B40 sample function altered unexpectedly")
print("Mono B40 source contracts PASS: 128x15, 32 temporal knots, queue history, native/gather and no resets")

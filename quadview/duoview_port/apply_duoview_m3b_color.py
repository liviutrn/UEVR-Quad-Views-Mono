#!/usr/bin/env python3
"""M3b P4: opt-in colour-guided depth selection without averaging a depth edge."""
from pathlib import Path
import sys
from apply_duoview_b40_pipeline import patch

def main():
    if len(sys.argv)!=3: raise SystemExit("Usage: apply_duoview_m3b_color.py <backend> <shaders>")
    mods=Path(sys.argv[1])/"src/mods"
    sh=Path(sys.argv[2])
    patch(sh/"DuoViewM1Stereo.hlsl",[
      ("P4 cbuffer",
       "    float4 M3bRepairFlags; // x: repair enabled, y: repair mask\n};",
       "    float4 M3bRepairFlags; // x: repair enabled, y: repair mask\n"
       "    float4 M3bColorFlags; // x: colour guided source depth\n};"),
      ("P4 source colour for condition compute",
       "#ifdef DUOVIEW_M1_CONDITION\nTexture2D<float> M1RawDepth : register(t4);",
       '#ifdef DUOVIEW_M1_CONDITION\n#include "DuoViewComposite.hlsl"\n'
       "Texture2D<float4> M3bPeripheralColor : register(t1);\n"
       "Texture2D<float> M1RawDepth : register(t4);"),
      ("P4 colour guided helper",
       "groupshared uint M25Valid[256],M25Agree[256];",
       """float3 M3bColorAt(float2 uv) {
    const float2 per=(clamp(uv*float2(PeripheralRect.zw),float2(.5,.5),float2(PeripheralRect.zw)-.5))
        /float2(NativePeripheryDimensions);
    [branch] if(all(uv>=M2Crop.xy) && all(uv<M2Crop.zw) && all(M2Crop.zw>M2Crop.xy)) {
        const float2 local=(uv-M2Crop.xy)/(M2Crop.zw-M2Crop.xy);
        const float2 foc=clamp(local*float2(FoveaRect.zw),float2(.5,.5),float2(FoveaRect.zw)-.5)
            /float2(NativeFoveaDimensions);
        return SourceAtlas.SampleLevel(LinearClamp,foc,0.0).rgb;
    }
    return M3bPeripheralColor.SampleLevel(LinearClamp,per,0.0).rgb;
}
float M3bGuidedCoarse(float2 uv) {
    const float2 pos=(uv+M1CoarseCorrection())*float2(M1Rect.zw)-.5;
    const int2 first=int2(floor(pos));
    const int2 nearest=clamp(int2(floor(pos+.5)),int2(0,0),int2(M1Rect.zw)-1);
    float z[4],cost[4];
    float lo=1.e20,hi=0.0;
    const float3 target=M3bColorAt(uv);
    [unroll] for(int y=0;y<2;++y)
      [unroll] for(int x=0;x<2;++x) {
        const uint n=uint(2*y+x);
        const int2 c=clamp(first+int2(x,y),int2(0,0),int2(M1Rect.zw)-1);
        z[n]=DecodeM1Depth(c);
        const float2 colourUv=(float2(c)+.5)/float2(M1Rect.zw)-M1CoarseCorrection();
        const float3 rgb=M3bColorAt(colourUv);
        cost[n]=abs(rgb.r-target.r)+abs(rgb.g-target.g)+abs(rgb.b-target.b);
        lo=min(lo,z[n]);hi=max(hi,z[n]);
      }
    if(hi-lo<=.02*max(hi,1.e-6)) return DecodeM1Depth(nearest);
    uint winner=0u;
    [unroll] for(uint i=1u;i<4u;++i) if(cost[i]<cost[winner]) winner=i;
    return z[winner];
}

groupshared uint M25Valid[256],M25Agree[256];"""),
      ("P4 seed branch",
       "        // Fuse raw seeds BEFORE the one global Lipschitz-envelope pass, so",
       """        [branch] if(M3bColorFlags.x>.5) nearDepth=M3bGuidedCoarse(unjittered);
        // Fuse raw seeds BEFORE the one global Lipschitz-envelope pass, so"""),
    ])
    patch(mods/"vr/DuoViewM1D3D12.hpp",[
      ("P4 cbuffer mirror",
       "    float m3b_repair_flags[4]{};\n};\nstatic_assert(sizeof(M1Constants) == 368);",
       "    float m3b_repair_flags[4]{};\n    float m3b_color_flags[4]{};\n};\nstatic_assert(sizeof(M1Constants) == 384);"),
      ("P4 writer flag",
       "                         bool edge_repair,bool edge_mask,",
       "                         bool edge_repair,bool edge_mask,bool color_edges,"),
      ("P4 writer set",
       "        data.m3b_repair_flags[0]=edge_repair ? 1.f : 0.f;",
       "        data.m3b_color_flags[0]=color_edges ? 1.f : 0.f;\n"
       "        data.m3b_repair_flags[0]=edge_repair ? 1.f : 0.f;"),
    ])
    patch(mods/"vr/DuoViewD3D12.hpp",[
      ("P4 writer argument",
       "                settings.m3b_edge_repair,settings.m3b_edge_mask,\n                m1_raw_srv_,m2_fovea_srv_);",
       "                settings.m3b_edge_repair,settings.m3b_edge_mask,settings.m3b_color_edges,\n"
       "                m1_raw_srv_,m2_fovea_srv_);"),
      ("P4 source colour table for compute",
       "            cmd->SetComputeRootConstantBufferView(4,m1_.constants->GetGPUVirtualAddress());",
       "            cmd->SetComputeRootConstantBufferView(4,m1_.constants->GetGPUVirtualAddress());\n"
       "            cmd->SetComputeRootDescriptorTable(0,srv_gpu_start_);\n"
       "            cmd->SetComputeRoot32BitConstants(1,sizeof(constants)/4,&constants,0);"),
    ])
    patch(mods/"vr/DuoViewConfig.hpp",[
      ("P4 setting",
       "    bool m3b_edge_mask{false};",
       "    bool m3b_edge_mask{false};\n    bool m3b_color_edges{false};"),
      ("P4 normalize",
       "    out.m3b_edge_mask=requested.m3b_edge_mask;",
       "    out.m3b_edge_mask=requested.m3b_edge_mask;\n    out.m3b_color_edges=requested.m3b_color_edges;"),
    ])
    patch(mods/"VR.hpp",[
      ("P4 toggle",
       '    const ModToggle::Ptr m_duo_m3b_repair{ModToggle::create(generate_name("DuoM3bEdgeRepair"),false)};',
       '    const ModToggle::Ptr m_duo_m3b_color{ModToggle::create(generate_name("DuoM3bColorEdges"),false)};\n'
       '    const ModToggle::Ptr m_duo_m3b_repair{ModToggle::create(generate_name("DuoM3bEdgeRepair"),false)};'),
      ("P4 persist",
       '            *m_duo_m3b_repair, *m_duo_m3b_mask,',
       '            *m_duo_m3b_color, *m_duo_m3b_repair, *m_duo_m3b_mask,'),
    ])
    patch(mods/"VR.cpp",[
      ("P4 reset",
       "                    m_duo_m3b_repair->value()=false; m_duo_m3b_mask->value()=false;",
       "                    m_duo_m3b_repair->value()=false; m_duo_m3b_mask->value()=false; m_duo_m3b_color->value()=false;"),
      ("P4 freeze",
       "        .m3b_edge_mask=m_duo_m3b_mask->value(),",
       "        .m3b_edge_mask=m_duo_m3b_mask->value(),\n"
       "        .m3b_color_edges=m_duo_m3b_color->value(),"),
      ("P4 comparison",
       "        current.m3b_edge_repair==candidate.m3b_edge_repair &&",
       "        current.m3b_color_edges==candidate.m3b_color_edges &&\n"
       "        current.m3b_edge_repair==candidate.m3b_edge_repair &&"),
      ("P4 menu",
       '                    ImGui::TextWrapped("Quality A/B (M3b):");',
       '                    ImGui::TextWrapped("Quality A/B (M3b):");\n'
       '                    m_duo_m3b_color->draw("Colour-guided depth edges (picks colour-matched source texel)");'),
    ])
    print("M3b P4 colour-guided, no-blend depth selection installed")

if __name__=="__main__":main()

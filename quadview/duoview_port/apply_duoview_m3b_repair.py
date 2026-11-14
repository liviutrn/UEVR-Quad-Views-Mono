#!/usr/bin/env python3
"""M3b P3: opt-in per-eye source-depth spatial repair, adapted from Joey DIBR."""
import sys
from pathlib import Path
from apply_duoview_b40_pipeline import patch

def main():
    if len(sys.argv)!=3: raise SystemExit("Usage: apply_duoview_m3b_repair.py <backend> <shader-dir>")
    mods=Path(sys.argv[1])/"src/mods"
    shaders=Path(sys.argv[2])
    patch(shaders/"DuoViewM1Stereo.hlsl",[
        ("P3 repair flags",
         "    float4 M3bOptions; // x: gate tuning active\n};",
         "    float4 M3bOptions; // x: gate tuning active\n"
         "    float4 M3bRepairFlags; // x: repair enabled, y: repair mask\n};"),
        ("P3 repair source and helpers",
         "float2 M1PullUv(float2 eyeUv, uint eye) {",
         """// The raw NGX SRVs share the existing t4..t7 root range with the M2.5a gate.
Texture2D<float> M3bCoarseRaw : register(t4);

float M3bDecodeInverse(float value) {
    const float inverse=(M1Depth.z*value-M1Depth.x)/M1Depth.y;
    return isfinite(inverse) ? max(inverse,0.0) : 0.0;
}
float M3bSourceDepth(float2 fullUv) {
    const float2 correction=M1CoarseCorrection();
    const int2 pos=clamp(int2((fullUv+correction)*float2(M1Rect.zw)),int2(0,0),int2(M1Rect.zw)-1);
    const float coarse=M3bDecodeInverse(M3bCoarseRaw.Load(int3(pos+int2(M1Rect.xy),0)));
    [branch] if(M2FoveaFlags.w>.5) {
        const float2 local=(fullUv-M2Crop.xy)/(M2Crop.zw-M2Crop.xy);
        if(all(local>=0.0) && all(local<1.0)) {
            float useFine=M1Filter.w;
            if(M25Flags.x>.5) {
                useFine=0.0;
                if(M25StatsRead.Load(0)==0u) {
                    const uint2 tile=min(uint2(fullUv*float2(M1Grid.xy)/16.0),(M1Grid.xy+15u)/16u-1u);
                    useFine=M25TileRead.Load(int3(tile,0)).x;
                }
            }
            if(useFine>.5) {
                const float2 dim=float2(M2FoveaRect.zw);
                const float2 fineUv=clamp(local+M2FineJitter(),.5/dim,1.0-.5/dim);
                const int2 fpos=clamp(int2(fineUv*dim),int2(0,0),int2(M2FoveaRect.zw)-1);
                return M3bDecodeInverse(M2RawFoveaDepth.Load(int3(fpos+int2(M2FoveaRect.xy),0)));
            }
        }
    }
    return coarse;
}
bool M3bRunCompatible(float a,float b) {
    return abs(a-b)<=max(.01, .025*max(abs(a),abs(b)));
}
// 0=confident, 1=low-confidence unchanged, 2=repaired.
float M3bRepairRoot(float2 sourceUv,uint eye,bool rootClamped,out uint status) {
    status=0u;
    const float du=1.0/max(float(M1Grid.x),1.0);
    const float target=M1ReadConditionedEye(sourceUv,eye);
    const float source=M3bSourceDepth(sourceUv);
    const float dl=M1ReadConditionedEye(sourceUv-float2(du,0),eye);
    const float dr=M1ReadConditionedEye(sourceUv+float2(du,0),eye);
    const float gradient=max(abs(target-dl),abs(target-dr));
    const float confidenceThreshold=max(.01,4.0*gradient);
    if(!rootClamped && abs(target-source)<=confidenceThreshold) return sourceUv.x;
    status=1u;
    const float rawLeft=M3bSourceDepth(sourceUv-float2(8.0*du,0));
    const float rawRight=M3bSourceDepth(sourceUv+float2(8.0*du,0));
    const float direction=rawRight<rawLeft ? 1.0 : -1.0;
    const float foreground=max(target,source);
    [loop] for(uint step=1u;step<=8u;++step) {
        const float x=sourceUv.x+direction*du*float(step);
        const float x1=x+direction*du,x2=x1+direction*du;
        if(x<0.0 || x>1.0 || x1<0.0 || x1>1.0 || x2<0.0 || x2>1.0) break;
        const float d0=M3bSourceDepth(float2(x,sourceUv.y));
        const float d1=M3bSourceDepth(float2(x1,sourceUv.y));
        const float d2=M3bSourceDepth(float2(x2,sourceUv.y));
        if(!(d0+.01<foreground) || !M3bRunCompatible(d0,d1) || !M3bRunCompatible(d0,d2)) continue;
        float chosenX=x,chosenD=d0;
        if(d1+.0025<chosenD) { chosenD=d1; chosenX=x1; }
        if(d2+.0025<chosenD) { chosenX=x2; }
        status=2u;
        return chosenX;
    }
    return sourceUv.x;
}

float2 M1PullUv(float2 eyeUv, uint eye, out uint repairStatus) {
    repairStatus=0u;"""),
        ("P3 repair after M3 fill",
         "        [branch] if(M3Flags.x>.5 && M3Flags.z>0.0) uv.x=M3FillHole(base.x,uv.x,base.y,k,eye);",
         """        const float sourceBeforeFill=uv.x;
        [branch] if(M3Flags.x>.5 && M3Flags.z>0.0) uv.x=M3FillHole(base.x,uv.x,base.y,k,eye);
        [branch] if(M3bRepairFlags.x>.5 && abs(uv.x-sourceBeforeFill)<1.e-7) {
            const bool rootClamped=(root<=lo+1.e-7 || root>=hi-1.e-7);
            uv.x=M3bRepairRoot(uv,eye,rootClamped,repairStatus);
        }"""),
        ("P3 legacy warp overload",
         "    return saturate(uv);\n}\n#endif",
         "    return saturate(uv);\n}\n"
         "float2 M1PullUv(float2 eyeUv,uint eye) { uint status=0u; return M1PullUv(eyeUv,eye,status); }\n"
         "#endif"),
    ])
    patch(shaders/"DuoViewNativeCompositeRaster.hlsl",[
        ("P3 carry mask from stereo mapping",
         "    const float2 fullUv = M2Sharpen.z > .5 ? outputUv : M1PullUv(outputUv, i.pos.x >= OutputSize.x ? 1u : 0u);",
         "    uint m3bRepairStatus=0u;\n"
         "    const float2 fullUv = M2Sharpen.z > .5 ? outputUv : M1PullUv(outputUv, i.pos.x >= OutputSize.x ? 1u : 0u,m3bRepairStatus);"),
        ("P3 debug mask",
         "#endif\n    return result;",
         """#endif
#ifdef DUOVIEW_M1_RASTER
    [branch] if(M3bRepairFlags.y>.5) {
        if(m3bRepairStatus==2u) result.rgb=lerp(result.rgb,float3(1.0,0.0,0.0),.85);
        else if(m3bRepairStatus==1u) result.rgb=lerp(result.rgb,float3(1.0,1.0,0.0),.85);
    }
#endif
    return result;"""),
    ])
    patch(mods/"vr/DuoViewM1D3D12.hpp",[
        ("P3 mirror cbuffer",
         "    float m3b_options[4]{};\n};\nstatic_assert(sizeof(M1Constants) == 352);",
         "    float m3b_options[4]{};\n    float m3b_repair_flags[4]{};\n};\nstatic_assert(sizeof(M1Constants) == 368);"),
        ("P3 writer args",
         "                         bool gate_tuning,float agree_tolerance,float ratio_low,float ratio_high,float contrast,",
         "                         bool gate_tuning,float agree_tolerance,float ratio_low,float ratio_high,float contrast,\n"
         "                         bool edge_repair,bool edge_mask,"),
        ("P3 writer flags",
         "        data.m3b_options[0]=gate_tuning ? 1.f : 0.f;",
         "        data.m3b_repair_flags[0]=edge_repair ? 1.f : 0.f;\n"
         "        data.m3b_repair_flags[1]=edge_repair && edge_mask ? 1.f : 0.f;\n"
         "        data.m3b_options[0]=gate_tuning ? 1.f : 0.f;"),
    ])
    patch(mods/"vr/DuoViewD3D12.hpp",[
        ("P3 writer wiring",
         "                settings.m3b_ratio_high,settings.m3b_contrast,\n                m1_raw_srv_,m2_fovea_srv_);",
         "                settings.m3b_ratio_high,settings.m3b_contrast,\n"
         "                settings.m3b_edge_repair,settings.m3b_edge_mask,\n"
         "                m1_raw_srv_,m2_fovea_srv_);"),
    ])
    patch(mods/"vr/DuoViewConfig.hpp",[
        ("P3 settings",
         "    float m3b_contrast{.10f};",
         "    float m3b_contrast{.10f};\n"
         "    bool m3b_edge_repair{false};\n    bool m3b_edge_mask{false};"),
        ("P3 validate",
         "    out.m3b_gate_tuning=requested.m3b_gate_tuning;",
         "    out.m3b_gate_tuning=requested.m3b_gate_tuning;\n"
         "    out.m3b_edge_repair=requested.m3b_edge_repair;\n"
         "    out.m3b_edge_mask=requested.m3b_edge_mask;"),
    ])
    patch(mods/"VR.hpp",[
        ("P3 UI controls",
         '    const ModToggle::Ptr m_duo_m3b_gate{ModToggle::create(generate_name("DuoM3bGateTune"),false)};',
         '    const ModToggle::Ptr m_duo_m3b_repair{ModToggle::create(generate_name("DuoM3bEdgeRepair"),false)};\n'
         '    const ModToggle::Ptr m_duo_m3b_mask{ModToggle::create(generate_name("DuoM3bEdgeRepairMask"),false)};\n'
         '    const ModToggle::Ptr m_duo_m3b_gate{ModToggle::create(generate_name("DuoM3bGateTune"),false)};'),
        ("P3 persistence",
         '            *m_duo_m3b_gate, *m_duo_m3b_agree, *m_duo_m3b_low, *m_duo_m3b_high, *m_duo_m3b_contrast, *m_duo_m2_fovea_depth,',
         '            *m_duo_m3b_repair, *m_duo_m3b_mask,\n'
         '            *m_duo_m3b_gate, *m_duo_m3b_agree, *m_duo_m3b_low, *m_duo_m3b_high, *m_duo_m3b_contrast, *m_duo_m2_fovea_depth,'),
    ])
    patch(mods/"VR.cpp",[
        ("P3 reset",
         "                    m_duo_m3b_gate->value()=false; m_duo_m3b_agree->value()=.03f;",
         "                    m_duo_m3b_repair->value()=false; m_duo_m3b_mask->value()=false;\n"
         "                    m_duo_m3b_gate->value()=false; m_duo_m3b_agree->value()=.03f;"),
        ("P3 freeze",
         "        .m3b_gate_tuning=m_duo_m3b_gate->value(),",
         "        .m3b_edge_repair=m_duo_m3b_repair->value(),\n"
         "        .m3b_edge_mask=m_duo_m3b_mask->value(),\n"
         "        .m3b_gate_tuning=m_duo_m3b_gate->value(),"),
        ("P3 equality",
         "        current.m3b_gate_tuning==candidate.m3b_gate_tuning &&",
         "        current.m3b_edge_repair==candidate.m3b_edge_repair &&\n"
         "        current.m3b_edge_mask==candidate.m3b_edge_mask &&\n"
         "        current.m3b_gate_tuning==candidate.m3b_gate_tuning &&"),
        ("P3 menu",
         '                    ImGui::TextWrapped("Quality A/B (M3b):");',
         '                    ImGui::TextWrapped("Quality A/B (M3b):");\n'
         '                    m_duo_m3b_repair->draw("Repair low-confidence depth edges from background (Joey method)");\n'
         '                    if(m_duo_m3b_repair->value()) m_duo_m3b_mask->draw("Debug repair: red=repaired, yellow=low confidence");'),
    ])
    print("M3b P3 source-depth edge repair and diagnostic mask installed")

if __name__=="__main__":main()

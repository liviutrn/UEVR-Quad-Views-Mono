#!/usr/bin/env python3
"""M3b P2: optional seed/history/stabilize passes with neighbourhood clamp.
Identity reprojection until a depth-frame-authenticated centre rotation is available.
"""
from pathlib import Path
import sys
from apply_duoview_b40_pipeline import patch

def main():
    if len(sys.argv)!=3:raise SystemExit("Usage: apply_duoview_m3b_temporal.py <backend> <shaders>")
    mods=Path(sys.argv[1])/"src/mods"; sh=Path(sys.argv[2])
    patch(sh/"DuoViewM1Stereo.hlsl",[
      ("P2 temporal cbuffer",
       "    float4 M3bColorFlags; // x: colour guided source depth\n};",
       "    float4 M3bColorFlags; // x: colour guided source depth\n"
       "    float4 M3bTemporal; // x: active, y: strength, z: history valid\n"
       "    float4 M3bHPrev[3]; // identity until depth-frame centre rotation is authenticated\n};"),
      ("P2 resource registers",
       "RWByteAddressBuffer M25StatsWrite : register(u4);",
       """RWByteAddressBuffer M25StatsWrite : register(u4);
Texture2D<float> M3bSeedRead : register(t8);
Texture2D<float> M3bHistoryRead : register(t9);
Texture2D<float> M3bStabilizedRead : register(t10);
RWTexture2D<float> M3bSeedWrite : register(u5);
RWTexture2D<float> M3bStabilizedWrite : register(u6);"""),
      ("P2 kernels",
       "groupshared uint M3bScoreReduction[384];",
       """[numthreads(8,8,1)]
void CSSeedM3b(uint3 tid:SV_DispatchThreadID) {
    if(any(tid.xy>=M1Grid.xy)) return;
    const float2 unjittered=(float2(tid.xy)+.5)/float2(M1Grid.xy);
    const float2 correction=M1CoarseCorrection();
    const int2 center=int2((unjittered+correction)*float2(M1Rect.zw));
    float nearDepth=0.0;
    [unroll] for(int y=-1;y<=1;++y)
      [unroll] for(int dx=-1;dx<=1;++dx)
        nearDepth=max(nearDepth,DecodeM1Depth(center+int2(dx,y)));
    [branch] if(M3bColorFlags.x>.5) nearDepth=M3bGuidedCoarse(unjittered);
    [branch] if(M2FoveaFlags.w>.5) {
        const float2 fullUv=unjittered;
        const float2 local=(fullUv-M2Crop.xy)/(M2Crop.zw-M2Crop.xy);
        if(all(local>=0.0) && all(local<1.0)) {
            const float2 dimension=float2(M2FoveaRect.zw);
            const float2 jit=clamp(local+M2FineJitter(),.5/dimension,1.0-.5/dimension);
            const int2 fineCenter=int2(jit*dimension);
            float fineNear=0.0;
            [unroll] for(int fy=-2;fy<=2;++fy)
              [unroll] for(int fx=-2;fx<=2;++fx)
                fineNear=max(fineNear,DecodeM2Depth(fineCenter+int2(fx,fy)));
            const float edge=min(min(local.x,local.y),min(1.0-local.x,1.0-local.y));
            const float t=saturate(edge/max(M2FoveaFlags.z,.0001));
            const float feather=t*t*(3.0-2.0*t);
            if(M25Flags.x>.5) {
                const float checkedWeight=M25Weight(fullUv);
                if(fineNear>0.0) nearDepth=lerp(nearDepth,fineNear,feather*checkedWeight);
            } else {
                if(fineNear>0.0) nearDepth=lerp(nearDepth,fineNear,feather*M1Filter.w);
            }
        }
    }
    const float knee=M1Depth.w;
    if(knee>0.0 && nearDepth>knee) {
        const float excess=nearDepth-knee;
        nearDepth=knee+excess/(1.0+excess/knee);
    }
    M3bSeedWrite[tid.xy]=knee>0.0 ? nearDepth : min(nearDepth,M1Filter.y);
}
[numthreads(8,8,1)]
void CSStabilizeM3b(uint3 tid:SV_DispatchThreadID) {
    if(any(tid.xy>=M1Grid.xy)) return;
    const int2 cell=int2(tid.xy), upper=int2(M1Grid.xy)-1;
    const float cur=M3bSeedRead.Load(int3(cell,0));
    float lo=cur,hi=cur;
    [unroll] for(int dy=-1;dy<=1;++dy)
      [unroll] for(int dx=-1;dx<=1;++dx) {
        const float d=M3bSeedRead.Load(int3(clamp(cell+int2(dx,dy),int2(0,0),upper),0));
        lo=min(lo,d);hi=max(hi,d);
    }
    float outDepth=cur;
    [branch] if(M3bTemporal.z>.5) {
        const float3 p=float3((float2(cell)+.5)/float2(M1Grid.xy),1.0);
        const float z=dot(M3bHPrev[2].xyz,p);
        const float2 previous=float2(dot(M3bHPrev[0].xyz,p),dot(M3bHPrev[1].xyz,p))/max(z,1.e-8);
        if(all(previous>=0.0) && all(previous<1.0)) {
            const float2 f=previous*float2(M1Grid.xy)-.5;
            const int2 corner=int2(floor(f));
            float best=cur,bestDistance=1.e20;
            [unroll] for(int y=0;y<2;++y)
              [unroll] for(int x=0;x<2;++x) {
                const float d=M3bHistoryRead.Load(int3(clamp(corner+int2(x,y),int2(0,0),upper),0));
                const float distance=abs(d-cur);
                if(distance<bestDistance) {bestDistance=distance;best=d;}
              }
            outDepth=lerp(cur,clamp(best,lo-.002,hi+.002),M3bTemporal.y);
        }
    }
    M3bStabilizedWrite[tid.xy]=outDepth;
}

groupshared uint M3bScoreReduction[384];"""),
      ("P2 use stabilized seed only when ON",
       "        M1Row[x] = knee > 0.0 ? nearDepth : min(nearDepth, M1Filter.y);",
       "        M1Row[x] = knee > 0.0 ? nearDepth : min(nearDepth, M1Filter.y);\n"
       "        [branch] if(M3bTemporal.x>.5) M1Row[x]=M3bStabilizedRead.Load(int3(x,group.x,0));"),
    ])
    patch(mods/"vr/DuoViewM1D3D12.hpp",[
      ("P2 temporal cbuffer",
       "    float m3b_color_flags[4]{};\n};\nstatic_assert(sizeof(M1Constants) == 384);",
       "    float m3b_color_flags[4]{};\n"
       "    float m3b_temporal[4]{};\n    float m3b_hprev[3][4]{};\n"
       "};\nstatic_assert(sizeof(M1Constants) == 448);"),
      ("P2 pipelines",
       "m3b_jitter_score;",
       "m3b_jitter_score, m3b_seed_pipeline, m3b_stabilize_pipeline;"),
      ("P2 resources and cache",
       "    bool m3b_auto_active{},m3b_pending_auto{},m3b_pending_gate{};",
       "    ComPtr<ID3D12Resource> m3b_seed,m3b_stabilized,m3b_history[2];\n"
       "    bool m3b_temporal_active{},m3b_history_valid{};\n"
       "    uint32_t m3b_history_index{},m3b_last_width{},m3b_last_height{};\n"
       "    float m3b_last_crop[4]{};\n"
       "    bool m3b_auto_active{},m3b_pending_auto{},m3b_pending_gate{};"),
      ("P2 pipelines optional",
       "        compute.CS={m3b_jitter_score_bytecode,sizeof(m3b_jitter_score_bytecode)};",
       "        compute.CS={m3b_seed_bytecode,sizeof(m3b_seed_bytecode)};\n"
       "        (void)device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m3b_seed_pipeline));\n"
       "        compute.CS={m3b_stabilize_bytecode,sizeof(m3b_stabilize_bytecode)};\n"
       "        (void)device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m3b_stabilize_pipeline));\n"
       "        compute.CS={m3b_jitter_score_bytecode,sizeof(m3b_jitter_score_bytecode)};"),
      ("P2 allocate bounded grid history",
       """        return SUCCEEDED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&stats,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&m25_readback)));""",
       """        if(FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&stats,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&m25_readback)))) return false;
        heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC temporal{};
        temporal.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        temporal.Width=(std::min)(eye_width,grid_limit);
        temporal.Height=(std::min)(eye_height,grid_limit);
        temporal.DepthOrArraySize=temporal.MipLevels=1;temporal.SampleDesc.Count=1;
        temporal.Format=DXGI_FORMAT_R32_FLOAT;
        temporal.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        constexpr auto temporalReads=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |
                                     D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        (void)device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&temporal,temporalReads,nullptr,IID_PPV_ARGS(&m3b_seed));
        (void)device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&temporal,temporalReads,nullptr,IID_PPV_ARGS(&m3b_stabilized));
        (void)device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&temporal,temporalReads,nullptr,IID_PPV_ARGS(&m3b_history[0]));
        (void)device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&temporal,temporalReads,nullptr,IID_PPV_ARGS(&m3b_history[1]));
        if(m3b_seed) m3b_seed->SetName(L"DuoView M3b seed");
        if(m3b_stabilized) m3b_stabilized->SetName(L"DuoView M3b stabilized");
        if(m3b_history[0]) m3b_history[0]->SetName(L"DuoView M3b history 0");
        if(m3b_history[1]) m3b_history[1]->SetName(L"DuoView M3b history 1");
        return true;"""),
      ("P2 writer flags signature",
       "                         bool edge_repair,bool edge_mask,bool color_edges,",
       "                         bool edge_repair,bool edge_mask,bool color_edges,bool temporal,float temporal_strength,"),
      ("P2 writer set identity fallback",
       "        data.m3b_color_flags[0]=color_edges ? 1.f : 0.f;",
       """        const bool history_resources=m3b_seed && m3b_stabilized && m3b_history[0] && m3b_history[1] &&
             m3b_seed_pipeline && m3b_stabilize_pipeline;
        m3b_temporal_active=temporal && history_resources && data.grid[0]>0u && data.grid[1]>0u;
        bool same_layout=m3b_history_valid && m3b_last_width==data.grid[0] &&
             m3b_last_height==data.grid[1];
        for(int i=0;i<4;++i) same_layout=same_layout && m3b_last_crop[i]==data.m2_crop[i];
        m3b_history_valid=m3b_temporal_active && same_layout;
        m3b_last_width=data.grid[0];m3b_last_height=data.grid[1];
        std::copy_n(data.m2_crop,4,m3b_last_crop);
        data.m3b_temporal[0]=m3b_temporal_active ? 1.f : 0.f;
        data.m3b_temporal[1]=(std::clamp)(temporal_strength,0.f,.9f);
        data.m3b_temporal[2]=m3b_history_valid ? 1.f : 0.f;
        data.m3b_hprev[0][0]=1.f;
        data.m3b_hprev[1][1]=1.f;
        data.m3b_hprev[2][2]=1.f;
        data.m3b_color_flags[0]=color_edges ? 1.f : 0.f;"""),
    ])
    patch(mods/"vr/DuoViewD3D12.hpp",[
      ("P2 writer args",
       "                settings.m3b_edge_repair,settings.m3b_edge_mask,settings.m3b_color_edges,",
       "                settings.m3b_edge_repair,settings.m3b_edge_mask,settings.m3b_color_edges,\n"
       "                settings.m3b_temporal,settings.m3b_temporal_strength,"),
      ("P2 root SRVs",
       "m1_raw_range.NumDescriptors=4;",
       "m1_raw_range.NumDescriptors=7;"),
      ("P2 root UAVs",
       "m1_output_range.NumDescriptors=3;",
       "m1_output_range.NumDescriptors=5;"),
      ("P2 descriptor heap",
       "hd.NumDescriptors = 12;",
       "hd.NumDescriptors = 17;"),
      ("P2 extra SRVs",
       """        device->CreateShaderResourceView(m1_.m25_stats.Get(),&stats_srv,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_UNORDERED_ACCESS_VIEW_DESC soft_uav{};""",
       """        device->CreateShaderResourceView(m1_.m25_stats.Get(),&stats_srv,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_SHADER_RESOURCE_VIEW_DESC temporalSrv=soft_srv;
        device->CreateShaderResourceView(m1_.m3b_seed.Get(),&temporalSrv,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        m3b_history_srv_cpu_=desc_cpu;
        device->CreateShaderResourceView(m1_.m3b_history[0].Get(),&temporalSrv,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        device->CreateShaderResourceView(m1_.m3b_stabilized.Get(),&temporalSrv,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_UNORDERED_ACCESS_VIEW_DESC soft_uav{};"""),
      ("P2 additional UAVs",
       "        device->CreateUnorderedAccessView(m1_.m25_stats.Get(),nullptr,&stats_uav,desc_cpu);",
       """        device->CreateUnorderedAccessView(m1_.m25_stats.Get(),nullptr,&stats_uav,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_UNORDERED_ACCESS_VIEW_DESC temporalUav{};
        temporalUav.Format=DXGI_FORMAT_R32_FLOAT;
        temporalUav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
        device->CreateUnorderedAccessView(m1_.m3b_seed.Get(),nullptr,&temporalUav,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        device->CreateUnorderedAccessView(m1_.m3b_stabilized.Get(),nullptr,&temporalUav,desc_cpu);"""),
      ("P2 output descriptor routing",
       "raw.ptr+=UINT64(4)*srv_descriptor_increment_;",
       "raw.ptr+=UINT64(7)*srv_descriptor_increment_;"),
      ("P2 select retired history SRV before dispatch",
       "            cmd->SetComputeRootSignature(root_.Get());\n            cmd->SetPipelineState(m1_.condition.Get());",
       """            if(m1_.m3b_temporal_active) {
                D3D12_SHADER_RESOURCE_VIEW_DESC historyView{};
                historyView.Format=DXGI_FORMAT_R32_FLOAT;
                historyView.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
                historyView.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
                historyView.Texture2D.MipLevels=1;
                device->CreateShaderResourceView(m1_.m3b_history[m1_.m3b_history_index].Get(),&historyView,m3b_history_srv_cpu_);
            }
            cmd->SetComputeRootSignature(root_.Get());
            cmd->SetPipelineState(m1_.condition.Get());"""),
      ("P2 dispatch seed and stabilize",
       "            if(m1_.m3b_auto_active) {",
       """            if(m1_.m3b_temporal_active) {
                constexpr auto reads=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |
                                     D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
                transition(cmd,m1_.m3b_seed.Get(),reads,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                transition(cmd,m1_.m3b_stabilized.Get(),reads,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                cmd->SetPipelineState(m1_.m3b_seed_pipeline.Get());
                cmd->Dispatch((m1_.grid_columns+7u)/8u,(m1_.rows+7u)/8u,1);
                D3D12_RESOURCE_BARRIER depthBarrier{};
                depthBarrier.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;
                depthBarrier.UAV.pResource=m1_.m3b_seed.Get();
                cmd->ResourceBarrier(1,&depthBarrier);
                transition(cmd,m1_.m3b_seed.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,reads);
                cmd->SetPipelineState(m1_.m3b_stabilize_pipeline.Get());
                cmd->Dispatch((m1_.grid_columns+7u)/8u,(m1_.rows+7u)/8u,1);
                depthBarrier.UAV.pResource=m1_.m3b_stabilized.Get();
                cmd->ResourceBarrier(1,&depthBarrier);
                transition(cmd,m1_.m3b_stabilized.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,reads);
                cmd->SetPipelineState(m1_.condition.Get());
            }
            if(m1_.m3b_auto_active) {"""),
      ("P2 copy current stabilized depth to next history",
       "            cmd->Dispatch(m1_.rows,1,1);",
       """            cmd->Dispatch(m1_.rows,1,1);
            if(m1_.m3b_temporal_active) {
                constexpr auto reads=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |
                                     D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
                auto* previous=m1_.m3b_history[1u-m1_.m3b_history_index].Get();
                transition(cmd,m1_.m3b_stabilized.Get(),reads,D3D12_RESOURCE_STATE_COPY_SOURCE);
                transition(cmd,previous,reads,D3D12_RESOURCE_STATE_COPY_DEST);
                cmd->CopyResource(previous,m1_.m3b_stabilized.Get());
                transition(cmd,previous,D3D12_RESOURCE_STATE_COPY_DEST,reads);
                transition(cmd,m1_.m3b_stabilized.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,reads);
                m1_.m3b_history_index=1u-m1_.m3b_history_index;
                m1_.m3b_history_valid=true;
            }"""),
      ("P2 store CPU history SRV handle",
       "    D3D12_CPU_DESCRIPTOR_HANDLE m1_raw_srv_{};",
       "    D3D12_CPU_DESCRIPTOR_HANDLE m3b_history_srv_cpu_{};\n"
       "    D3D12_CPU_DESCRIPTOR_HANDLE m1_raw_srv_{};"),
    ])
    patch(mods/"vr/DuoViewConfig.hpp",[
      ("P2 toggles",
       "    bool m3b_color_edges{false};",
       "    bool m3b_color_edges{false};\n    bool m3b_temporal{false};\n    float m3b_temporal_strength{.6f};"),
      ("P2 validation",
       "    out.m3b_color_edges=requested.m3b_color_edges;",
       "    out.m3b_color_edges=requested.m3b_color_edges;\n"
       "    out.m3b_temporal=requested.m3b_temporal;\n"
       "    if(std::isfinite(requested.m3b_temporal_strength))\n"
       "        out.m3b_temporal_strength=(std::clamp)(requested.m3b_temporal_strength,0.f,.9f);"),
    ])
    patch(mods/"VR.hpp",[
      ("P2 UI",
       '    const ModToggle::Ptr m_duo_m3b_color{ModToggle::create(generate_name("DuoM3bColorEdges"),false)};',
       '    const ModToggle::Ptr m_duo_m3b_temporal{ModToggle::create(generate_name("DuoM3bTemporal"),false)};\n'
       '    const ModSlider::Ptr m_duo_m3b_temporal_strength{ModSlider::create(generate_name("DuoM3bTemporalStrength"),0.f,.9f,.6f)};\n'
       '    const ModToggle::Ptr m_duo_m3b_color{ModToggle::create(generate_name("DuoM3bColorEdges"),false)};'),
      ("P2 persist",
       '            *m_duo_m3b_color, *m_duo_m3b_repair,',
       '            *m_duo_m3b_temporal, *m_duo_m3b_temporal_strength, *m_duo_m3b_color, *m_duo_m3b_repair,'),
    ])
    patch(mods/"VR.cpp",[
      ("P2 reset",
       "m_duo_m3b_color->value()=false;",
       "m_duo_m3b_color->value()=false; m_duo_m3b_temporal->value()=false; m_duo_m3b_temporal_strength->value()=.6f;"),
      ("P2 freeze",
       "        .m3b_color_edges=m_duo_m3b_color->value(),",
       "        .m3b_temporal=m_duo_m3b_temporal->value(),\n"
       "        .m3b_temporal_strength=m_duo_m3b_temporal_strength->value(),\n"
       "        .m3b_color_edges=m_duo_m3b_color->value(),"),
      ("P2 equality",
       "        current.m3b_color_edges==candidate.m3b_color_edges &&",
       "        current.m3b_temporal==candidate.m3b_temporal &&\n"
       "        current.m3b_temporal_strength==candidate.m3b_temporal_strength &&\n"
       "        current.m3b_color_edges==candidate.m3b_color_edges &&"),
      ("P2 menu",
       '                    ImGui::TextWrapped("Quality A/B (M3b):");',
       '                    ImGui::TextWrapped("Quality A/B (M3b):");\n'
       '                    m_duo_m3b_temporal->draw("Temporal depth (identity reprojection + 3x3 clamp)");\n'
       '                    if(m_duo_m3b_temporal->value()) m_duo_m3b_temporal_strength->draw("Depth history blend strength");'),
    ])
    patch(Path(__file__).resolve().parent/"embed_duoview_b40.py",[
      ("P2 compile kernels",
       '            ("CSJitterScoreM3b","cs_5_0","m3b_jitter_score_bytecode","DuoViewM1Stereo.hlsl",("DUOVIEW_M1_CONDITION",)),',
       '            ("CSJitterScoreM3b","cs_5_0","m3b_jitter_score_bytecode","DuoViewM1Stereo.hlsl",("DUOVIEW_M1_CONDITION",)),\n'
       '            ("CSSeedM3b","cs_5_0","m3b_seed_bytecode","DuoViewM1Stereo.hlsl",("DUOVIEW_M1_CONDITION",)),\n'
       '            ("CSStabilizeM3b","cs_5_0","m3b_stabilize_bytecode","DuoViewM1Stereo.hlsl",("DUOVIEW_M1_CONDITION",)),'),
    ])
    print("M3b P2 history ping-pong and clamped temporal seed; identity reprojection fallback")

if __name__=="__main__":main()

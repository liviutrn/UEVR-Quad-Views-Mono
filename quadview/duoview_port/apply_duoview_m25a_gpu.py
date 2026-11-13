#!/usr/bin/env python3
"""Builder A M2.5a GPU tile agreement, global guard, debug and nonblocking stats.

Must run after apply_duoview_m25a_cpu.py. The only new GPU allocations
are a 64x64 float4 tile texture plus two 32-byte buffers per fenced XR slot.
"""
import sys
from pathlib import Path
from apply_duoview_b40_pipeline import patch


def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: apply_duoview_m25a_gpu.py <backend> <shaders>")
    mods=Path(sys.argv[1])/"src/mods"
    sh=Path(sys.argv[2])

    patch(mods/"vr/DuoViewM1D3D12.hpp",[
        ("M25 constants",
         "    float m24_fade[4]{};",
         "    float m24_fade[4]{};\n    float m25_flags[4]{}; // x: GPU content gate"),
        ("M25 size",
         "static_assert(sizeof(M1Constants) == 272);",
         "static_assert(sizeof(M1Constants) == 288);"),
        ("M25 buffers and pipelines",
         "ComPtr<ID3D12PipelineState> raster, condition, vertical;",
         '''ComPtr<ID3D12PipelineState> raster, condition, vertical, m25_analyse, m25_guard;
    ComPtr<ID3D12Resource> m25_tiles, m25_stats, m25_readback;
    bool m25_content_active{},m25_pending{};
    uint32_t m25_tile_x{},m25_tile_y{};
    struct M25GpuCounters {uint32_t guard{},cells{},agree{},varied{},passing{},weight_x1000{},reserved[2]{};};
    inline static std::atomic<uint64_t> gpu_frames{},gpu_guard_off{},gpu_cells{},gpu_agree{},gpu_varied{},gpu_passing{},gpu_weight_x1000{},vertical_dispatches{};
    static void m25_count_vertical() {++vertical_dispatches;}
    void m25_read_retired_stats() {
        // Caller owns a retired XR command slot; never wait on the GPU.
        if(!m25_pending || !m25_readback) return;
        const D3D12_RANGE read{0,sizeof(M25GpuCounters)};
        void* p=nullptr;
        if(SUCCEEDED(m25_readback->Map(0,&read,&p)) && p) {
            const auto c=*static_cast<const M25GpuCounters*>(p);
            const D3D12_RANGE written{0,0};
            m25_readback->Unmap(0,&written);
            ++gpu_frames;gpu_guard_off+=c.guard;gpu_cells+=c.cells;
            gpu_agree+=c.agree;gpu_varied+=c.varied;gpu_passing+=c.passing;
            gpu_weight_x1000+=c.weight_x1000;
        }
        m25_pending=false;
    }
    static std::array<uint64_t,8> m25_take_gpu_window() {
        return {gpu_frames.exchange(0),gpu_guard_off.exchange(0),
                gpu_cells.exchange(0),gpu_agree.exchange(0),
                gpu_varied.exchange(0),gpu_passing.exchange(0),
                gpu_weight_x1000.exchange(0),vertical_dispatches.exchange(0)};
    }'''),
        ("M25 required pipelines",
         "bool ready() const { return raster && condition && vertical && soft_depth && constants; }",
         "bool ready() const { return raster && condition && vertical && m25_analyse && m25_guard && m25_tiles && m25_stats && m25_readback && soft_depth && constants; }"),
        ("M25 create analysis pipeline",
         "        output_width_px=eye_width; output_height_px=eye_height;",
         '''        compute.CS={m25_analysis_bytecode,sizeof(m25_analysis_bytecode)};
        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m25_analyse)))) return false;
        compute.CS={m25_guard_bytecode,sizeof(m25_guard_bytecode)};
        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m25_guard)))) return false;
        output_width_px=eye_width; output_height_px=eye_height;'''),
        ("M25 allocation once per slot",
         '''        return SUCCEEDED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer,
            D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&constants)));''',
         '''        if(FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&buffer,
            D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&constants)))) return false;
        // Prewarm a fixed 64x64 grid: no resize when gaze/fovea dimension changes.
        m25_tile_x=((std::min)(eye_width,grid_limit)+15u)/16u;
        m25_tile_y=((std::min)(eye_height,grid_limit)+15u)/16u;
        heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC tiles{};
        tiles.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        tiles.Width=m25_tile_x;tiles.Height=m25_tile_y;
        tiles.DepthOrArraySize=tiles.MipLevels=1;tiles.SampleDesc.Count=1;
        tiles.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
        tiles.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        constexpr auto srv_state=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |
                                 D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        if(FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&tiles,
            srv_state,nullptr,IID_PPV_ARGS(&m25_tiles)))) return false;
        D3D12_RESOURCE_DESC stats{};
        stats.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;stats.Width=sizeof(M25GpuCounters);
        stats.Height=stats.DepthOrArraySize=stats.MipLevels=1;
        stats.SampleDesc.Count=1;stats.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        stats.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        if(FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&stats,
            srv_state,nullptr,IID_PPV_ARGS(&m25_stats)))) return false;
        heap.Type=D3D12_HEAP_TYPE_READBACK;
        stats.Flags=D3D12_RESOURCE_FLAG_NONE;
        return SUCCEEDED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&stats,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&m25_readback)));'''),
        ("M25 writer argument",
         "float right_sharpen, bool depth_debug, bool jitter_correct,",
         "float right_sharpen, uint32_t depth_debug, bool jitter_correct,uint32_t fine_mode,"),
        ("M25 retained readback fence",
         "        M1Constants data{};",
         "        m25_read_retired_stats(); // The owning XR command slot has retired before reuse.\n        M1Constants data{};"),
        ("M25 precise debug",
         "        data.m2_sharpen[2] = depth_debug ? 1.f : 0.f;",
         "        data.m2_sharpen[2] = float((std::min)(depth_debug,3u));"),
        ("M25 debug gate",
         "        fovea_depth_active=fine_ok;",
         '''        fovea_depth_active=fine_ok;
        m25_content_active=fine_ok && fine_mode==1u;
        data.m25_flags[0]=m25_content_active ? 1.f : 0.f;'''),
    ])
    patch(mods/"vr/DuoViewD3D12.hpp",[
        ("M25 writer receives mode",
         'settings.m21_depth_debug,settings.m21_jitter_correct,',
         'settings.m21_depth_debug,settings.m21_jitter_correct,settings.m25_fine_mode,'),
        ("M25 raw SRV table",
         "m1_raw_range.NumDescriptors=2;",
         "m1_raw_range.NumDescriptors=4; // t4 coarse,t5 fine,t6 tiles,t7 guard/stats"),
        ("M25 output UAV table",
         "m1_output_range.NumDescriptors=1;",
         "m1_output_range.NumDescriptors=3; // u2 conditioned,u3 tiles,u4 stats"),
        ("M25 heap entries",
         "hd.NumDescriptors = 8;",
         "hd.NumDescriptors = 12;"),
        ("M25 descriptor table setup",
         '''        m2_fovea_srv_=desc_cpu;
        device->CreateShaderResourceView(nullptr,&soft_srv,m2_fovea_srv_);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_UNORDERED_ACCESS_VIEW_DESC soft_uav{};''',
         '''        m2_fovea_srv_=desc_cpu;
        device->CreateShaderResourceView(nullptr,&soft_srv,m2_fovea_srv_);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_SHADER_RESOURCE_VIEW_DESC tile_srv{};
        tile_srv.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
        tile_srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
        tile_srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        tile_srv.Texture2D.MipLevels=1;
        device->CreateShaderResourceView(m1_.m25_tiles.Get(),&tile_srv,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_SHADER_RESOURCE_VIEW_DESC stats_srv{};
        stats_srv.Format=DXGI_FORMAT_R32_TYPELESS;
        stats_srv.ViewDimension=D3D12_SRV_DIMENSION_BUFFER;
        stats_srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        stats_srv.Buffer.NumElements=sizeof(M1Resources::M25GpuCounters)/4;
        stats_srv.Buffer.Flags=D3D12_BUFFER_SRV_FLAG_RAW;
        device->CreateShaderResourceView(m1_.m25_stats.Get(),&stats_srv,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_UNORDERED_ACCESS_VIEW_DESC soft_uav{};'''),
        ("M25 output UAVs",
         "        device->CreateUnorderedAccessView(m1_.soft_depth.Get(),nullptr,&soft_uav,desc_cpu);",
         '''        device->CreateUnorderedAccessView(m1_.soft_depth.Get(),nullptr,&soft_uav,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_UNORDERED_ACCESS_VIEW_DESC tile_uav{};
        tile_uav.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
        tile_uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
        device->CreateUnorderedAccessView(m1_.m25_tiles.Get(),nullptr,&tile_uav,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_UNORDERED_ACCESS_VIEW_DESC stats_uav{};
        stats_uav.Format=DXGI_FORMAT_R32_TYPELESS;
        stats_uav.ViewDimension=D3D12_UAV_DIMENSION_BUFFER;
        stats_uav.Buffer.NumElements=sizeof(M1Resources::M25GpuCounters)/4;
        stats_uav.Buffer.Flags=D3D12_BUFFER_UAV_FLAG_RAW;
        device->CreateUnorderedAccessView(m1_.m25_stats.Get(),nullptr,&stats_uav,desc_cpu);'''),
        ("M25 descriptor routing",
         "raw.ptr+=UINT64(2)*srv_descriptor_increment_;",
         "raw.ptr+=UINT64(4)*srv_descriptor_increment_;"),
        ("M25 two-pass gate before existing row envelope",
         '''            cmd->SetComputeRootDescriptorTable(6,raw);
            cmd->Dispatch(m1_.rows,1,1);''',
         '''            cmd->SetComputeRootDescriptorTable(6,raw);
            if(m1_.m25_content_active) {
                constexpr auto reads=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |
                                     D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
                transition(cmd,m1_.m25_tiles.Get(),reads,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                transition(cmd,m1_.m25_stats.Get(),reads,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                cmd->SetPipelineState(m1_.m25_analyse.Get());
                cmd->Dispatch((m1_.grid_columns+15u)/16u,(m1_.rows+15u)/16u,1);
                D3D12_RESOURCE_BARRIER barrier{};
                barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;
                barrier.UAV.pResource=m1_.m25_tiles.Get();
                cmd->ResourceBarrier(1,&barrier);
                transition(cmd,m1_.m25_tiles.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,reads);
                cmd->SetPipelineState(m1_.m25_guard.Get());
                cmd->Dispatch(1,1,1);
                barrier.UAV.pResource=m1_.m25_stats.Get();
                cmd->ResourceBarrier(1,&barrier);
                transition(cmd,m1_.m25_stats.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,reads);
                cmd->SetPipelineState(m1_.condition.Get());
            }
            cmd->Dispatch(m1_.rows,1,1);'''),
        ("M25 stats copy no waiting",
         '''            transition(cmd,m1_.soft_depth.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                       D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);''',
         '''            if(m1_.m25_content_active) {
                constexpr auto reads=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE |
                                     D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
                transition(cmd,m1_.m25_stats.Get(),reads,D3D12_RESOURCE_STATE_COPY_SOURCE);
                cmd->CopyResource(m1_.m25_readback.Get(),m1_.m25_stats.Get());
                transition(cmd,m1_.m25_stats.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,reads);
                m1_.m25_pending=true;
            }
            transition(cmd,m1_.soft_depth.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                       D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);'''),
        ("M25 count real vertical passes",
         "                cmd->Dispatch(m1_.grid_columns,1,1);",
         "                cmd->Dispatch(m1_.grid_columns,1,1);\n                M1Resources::m25_count_vertical();"),
        ("M25 graphics reads bound",
         '''        if (m1_active) cmd->SetGraphicsRootConstantBufferView(4,m1_.constants->GetGPUVirtualAddress());''',
         '''        if (m1_active) {
            cmd->SetGraphicsRootConstantBufferView(4,m1_.constants->GetGPUVirtualAddress());
            auto raw=srv_gpu_start_;
            raw.ptr+=UINT64(5)*srv_descriptor_increment_;
            cmd->SetGraphicsRootDescriptorTable(5,raw);
        }'''),
    ])
    patch(sh/"DuoViewM1Stereo.hlsl",[
        ("M25 constant in shared b1",
         '    float4 M24Fade; // near inverse depth, far inverse depth, far normal/extra-wide ratios',
         '    float4 M24Fade; // near inverse depth, far inverse depth, far normal/extra-wide ratios\n    float4 M25Flags; // x: content-checked fine'),
        ("M25 read resources",
         'Texture2D<float> M2RawFoveaDepth : register(t5);',
         '''Texture2D<float> M2RawFoveaDepth : register(t5);
Texture2D<float4> M25TileRead : register(t6);
ByteAddressBuffer M25StatsRead : register(t7);'''),
        ("M25 new UAVs",
         'RWTexture2D<float> M1ConditionedDepth : register(u2);',
         '''RWTexture2D<float> M1ConditionedDepth : register(u2);
RWTexture2D<float4> M25TileWrite : register(u3);
RWByteAddressBuffer M25StatsWrite : register(u4);'''),
        ("M25 tile scan and guard shader",
         '''[numthreads(128,1,1)]
void CSConditionM1(uint3 group : SV_GroupID, uint lane : SV_GroupIndex) {''',
         '''groupshared uint M25Valid[256],M25Agree[256];
groupshared float M25Min[256],M25Max[256];

// One tile is 16x16 coarse-grid cells. Fine sampling uses the same 5x5
// near-max convention as the production seed path; no temporal CPU guesses.
[numthreads(16,16,1)]
void CSAnalyzeM25(uint3 group:SV_GroupID,uint3 tid:SV_GroupThreadID,
                  uint lane:SV_GroupIndex) {
    const uint2 cell=group.xy*16u+tid.xy;
    const bool inside=all(cell<M1Grid.xy);
    const float2 uv=(float2(cell)+.5)/float2(M1Grid.xy);
    const float2 local=(uv-M2Crop.xy)/(M2Crop.zw-M2Crop.xy);
    const bool crop=inside && all(local>=0.) && all(local<1.);
    float fine=0.,closest=1.e9,coarse=0.;
    if(crop) {
        const float2 dimension=float2(M2FoveaRect.zw);
        const float2 jit=clamp(local+M2FoveaFlags.xy,.5/dimension,1.-.5/dimension);
        const int2 fcenter=int2(jit*dimension);
        [unroll] for(int fy=-2;fy<=2;++fy)
            [unroll] for(int fx=-2;fx<=2;++fx)
                fine=max(fine,DecodeM2Depth(fcenter+int2(fx,fy)));
        const float2 correction=M2Sharpen.w>.5 ? M1Eye.zw : float2(0.,0.);
        const int2 ccenter=int2((uv+correction)*float2(M1Rect.zw));
        [unroll] for(int dy=-1;dy<=1;++dy)
            [unroll] for(int dx=-1;dx<=1;++dx) {
                const float d=DecodeM1Depth(ccenter+int2(dx,dy));
                coarse=max(coarse,d);
                closest=min(closest,abs(d-fine));
            }
    }
    const uint valid=crop && fine>0. ? 1u : 0u;
    M25Valid[lane]=valid;
    M25Agree[lane]=valid && closest<=max(.004, .03*fine) ? 1u : 0u;
    M25Min[lane]=valid ? coarse : 1.e9;
    M25Max[lane]=valid ? coarse : 0.;
    GroupMemoryBarrierWithGroupSync();
    for(uint step=128u;step>0u;step>>=1u) {
        if(lane<step) {
            M25Valid[lane]+=M25Valid[lane+step];
            M25Agree[lane]+=M25Agree[lane+step];
            M25Min[lane]=min(M25Min[lane],M25Min[lane+step]);
            M25Max[lane]=max(M25Max[lane],M25Max[lane+step]);
        }
        GroupMemoryBarrierWithGroupSync();
    }
    if(lane==0u) {
        const uint n=M25Valid[0];
        const float ratio=n>0u ? float(M25Agree[0])/float(n) : 0.;
        const float varied=(n>0u && M25Max[0]>0. &&
                            M25Max[0]-M25Min[0]>.1*M25Max[0]) ? 1. : 0.;
        M25TileWrite[group.xy]=float4(smoothstep(.60,.85,ratio),ratio,varied,float(n));
    }
}

// One lightweight GPU reduction after all tile writes. Its output is consumed
// by the row envelope and copied asynchronously into the retired XR slot.
[numthreads(1,1,1)]
void CSGuardM25(uint3 unused:SV_DispatchThreadID) {
    const uint2 sz=(M1Grid.xy+15u)/16u;
    uint cells=0u,agree=0u,varied=0u,passing=0u,weightSum=0u;
    for(uint y=0u;y<sz.y;++y) for(uint x=0u;x<sz.x;++x) {
        const float4 t=M25TileRead.Load(int3(x,y,0));
        const uint n=uint(t.w+.5);
        cells+=n;agree+=uint(t.y*float(n)+.5);
        const bool v=t.z>.5;
        varied+=v ? 1u : 0u;
        passing+=v && t.y>=.6 ? 1u : 0u;
        weightSum+=uint(t.x*1000.+.5);
    }
    const uint guard=varied>0u && passing*2u<varied ? 1u : 0u;
    M25StatsWrite.Store(0,guard);
    M25StatsWrite.Store(4,cells);
    M25StatsWrite.Store(8,agree);
    M25StatsWrite.Store(12,varied);
    M25StatsWrite.Store(16,passing);
    M25StatsWrite.Store(20,weightSum);
    M25StatsWrite.Store(24,0u);M25StatsWrite.Store(28,0u);
}
float M25Weight(float2 gridUv) {
    if(M25StatsRead.Load(0)!=0u) return 0.;
    const uint2 sz=(M1Grid.xy+15u)/16u;
    const float2 tilePos=gridUv*float2(M1Grid.xy)/16.-.5;
    const int2 i=int2(floor(tilePos));
    const float2 a=frac(tilePos);
    const int2 maxTile=int2(sz)-1;
    const float w00=M25TileRead.Load(int3(clamp(i,int2(0,0),maxTile),0)).x;
    const float w10=M25TileRead.Load(int3(clamp(i+int2(1,0),int2(0,0),maxTile),0)).x;
    const float w01=M25TileRead.Load(int3(clamp(i+int2(0,1),int2(0,0),maxTile),0)).x;
    const float w11=M25TileRead.Load(int3(clamp(i+int2(1,1),int2(0,0),maxTile),0)).x;
    return lerp(lerp(w00,w10,a.x),lerp(w01,w11,a.x),a.y);
}

[numthreads(128,1,1)]
void CSConditionM1(uint3 group : SV_GroupID, uint lane : SV_GroupIndex) {'''),
        ("M25 opt-in gated fusion",
         "if(fineNear>0.0) nearDepth=lerp(nearDepth,fineNear,feather*M1Filter.w);",
         '''if(M25Flags.x>.5) {
                    const float checkedWeight=M25Weight(fullUv);
                    if(fineNear>0.0) nearDepth=lerp(nearDepth,fineNear,feather*checkedWeight);
                } else {
                    // Original M2.4 path is unchanged when mode=0.
                    if(fineNear>0.0) nearDepth=lerp(nearDepth,fineNear,feather*M1Filter.w);
                }'''),
    ])
    # The dedicated fine-weight heat overlay reads only tiny tile/stats SRVs.
    patch(sh/"DuoViewNativeCompositeRaster.hlsl",[
        ("M25 raster debug overlays",
         '''#endif
    return result;''',
         '''#ifdef DUOVIEW_M1_RASTER
    if(M2Sharpen.z>1.5 && M1Grid.x>0u) {
        const float2 loc=(outputUv-M2Crop.xy)/(M2Crop.zw-M2Crop.xy);
        if(any(loc<0.) || any(loc>=1.) || M25Flags.x<.5)
            result.rgb=float3(.40,.40,.40);
        else {
            const uint2 tc=min(uint2(outputUv*float2(M1Grid.xy)/16.),
                               (M1Grid.xy+15u)/16u-1u);
            const float4 t=M25TileRead.Load(int3(tc,0));
            const bool rejected=M25StatsRead.Load(0)!=0u;
            if(M2Sharpen.z<2.5)
                result.rgb=rejected ? float3(1.,0.,0.) : lerp(float3(1.,0.,0.),float3(0.,1.,0.),t.x);
            else
                result.rgb=lerp(float3(1.,.1,0.),float3(0.,1.,0.),t.y);
        }
    }
#endif
    return result;'''),
    ])
    print("M2.5a GPU: per-tile agreement, full-frame veto, slot-owned readback, debug overlays")


if __name__=="__main__":
    main()

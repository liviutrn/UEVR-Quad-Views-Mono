#!/usr/bin/env python3
"""DuoView M4 (Claude, 14 Nov 2026): full-resolution fovea depth.

Until M3a the fine fovea depth was pooled (5x5 near-max) into the one shared
full-view conditioned grid (<=1024 wide for the WHOLE field of view), so the
fovea got only a few hundred depth cells across and fine ON looked like coarse.

M4 gives the fovea its own conditioned field, sized to the fine NGX depth
(<=1024 per side, aspect kept). Same seeds, knee, cap and (M3a per-eye or
symmetric) envelope as the shared grid, with every penalty rescaled from
shared-grid texels to fovea texels, so the fold bound in output pixels is the
same. The warp/debug/fill reads use the fovea field inside the gaze crop and
ease into the shared grid over the outer 15% of the crop.

One setting, DuoM4FoveaDepthGrid, default OFF. ON also turns fine depth on in
content-checked mode (the only mode that delivers fine snapshots). With it OFF
every value read by the shaders is unchanged. Depth debug 4 = depth picture.

Run after apply_duoview_m3a.py. Every edit is exact-once.
"""
import sys
from pathlib import Path
from apply_duoview_b40_pipeline import patch

M4_KERNELS = r"""
// ---- M4 (Claude): the fovea keeps its own conditioned depth field at fine-depth
// resolution instead of being pooled into the shared full-view grid. Same seed
// rules, knee and envelope as M1/M3a; penalties are rescaled from shared-grid
// texels to fovea texels (M4Flags.y/z), so the fold bound in output pixels holds.
void M4Envelope(uint w, uint lane, uint eye, float limit, float scale) {
    const float k=M1Eye[eye];
    const float pf=(eye==0u ? M3Slopes.x : M3Slopes.y)*scale;
    const float ps=(eye==0u ? M3Slopes.z : M3Slopes.w)*scale;
    const int fold=k>=0.0 ? 1 : -1;
    const float pmin=ps>0.0 ? min(pf,ps) : pf;
    for (uint step=1; step<w && float(step-1)*pmin<limit; step*=2) {
        for (uint x=lane; x<w; x+=128) {
            const int xf=int(x)+fold*int(step);
            const int xs=int(x)-fold*int(step);
            float v=M1Row[x];
            if (xf>=0 && xf<int(w)) v=max(v,M1Row[xf]-float(step)*pf);
            if (ps>0.0 && xs>=0 && xs<int(w)) v=max(v,M1Row[xs]-float(step)*ps);
            M1Next[x]=v;
        }
        GroupMemoryBarrierWithGroupSync();
        for (uint x=lane; x<w; x+=128) M1Row[x]=M1Next[x];
        GroupMemoryBarrierWithGroupSync();
    }
}

[numthreads(128,1,1)]
void CSConditionM4(uint3 group : SV_GroupID, uint lane : SV_GroupIndex) {
    const uint w=M4Grid.x;
    if (group.x>=M4Grid.y || w==0u || w>1024u) return;
    const float2 cropMin=M2Crop.xy;
    const float2 cropSize=M2Crop.zw-M2Crop.xy;
    const float2 dimension=float2(M2FoveaRect.zw);
    for (uint x=lane; x<w; x+=128) {
        const float2 local=(float2(x,group.x)+.5)/float2(M4Grid.xy);
        const float2 fullUv=cropMin+local*cropSize;
        // Shared-grid seed at the same place (identical mapping to CSConditionM1).
        const int2 center=int2((fullUv+M1CoarseCorrection())*float2(M1Rect.zw));
        float coarse=0.0;
        [unroll] for (int y=-1; y<=1; ++y)
            [unroll] for (int dx=-1; dx<=1; ++dx)
                coarse=max(coarse,DecodeM1Depth(center+int2(dx,y)));
        // One fovea texel covers ~1-1.3 fine texels: 2x2 near-max keeps thin
        // foreground without the 5x5 dilation the shared grid needs.
        const float2 jit=clamp(local+M2FineJitter(),.5/dimension,1.0-.5/dimension);
        const int2 f0=int2(floor(jit*dimension-.5));
        float fine=0.0;
        [unroll] for (int fy=0; fy<=1; ++fy)
            [unroll] for (int fx=0; fx<=1; ++fx)
                fine=max(fine,DecodeM2Depth(f0+int2(fx,fy)));
        const float edge=min(min(local.x,local.y),min(1.0-local.x,1.0-local.y));
        const float t=saturate(edge/max(M2FoveaFlags.z,.0001));
        const float feather=t*t*(3.0-2.0*t);
        // Invalid/empty NGX fine depth must never erase valid coarse depth.
        float nearDepth=fine>0.0 ? lerp(coarse,fine,feather) : coarse;
        const float knee=M1Depth.w;
        if (knee>0.0 && nearDepth>knee) {
            const float excess=nearDepth-knee;
            nearDepth=knee+excess/(1.0+excess/knee);
        }
        M1Row[x]=knee>0.0 ? nearDepth : min(nearDepth,M1Filter.y);
    }
    GroupMemoryBarrierWithGroupSync();

    const float limit=M1Depth.w>0.0 ? 2.0*M1Depth.w : M1Filter.y;
    const float scale=M4Flags.y;
    [branch] if (M3Flags.x<.5) {
        const float pen=M1Filter.x*scale;
        for (uint step=1; step<w && float(step-1)*pen<limit; step*=2) {
            for (uint x=lane; x<w; x+=128) {
                const float penalty=float(step)*pen;
                const float l=x>=step ? M1Row[x-step]-penalty : 0.0;
                const float r=x+step<w ? M1Row[x+step]-penalty : 0.0;
                M1Next[x]=max(M1Row[x],max(l,r));
            }
            GroupMemoryBarrierWithGroupSync();
            for (uint x=lane; x<w; x+=128) M1Row[x]=M1Next[x];
            GroupMemoryBarrierWithGroupSync();
        }
        for (uint x=lane; x<w; x+=128) {
            M4FoveaConditioned[uint3(x,group.x,0u)]=M1Row[x];
            M4FoveaConditioned[uint3(x,group.x,1u)]=M1Row[x];
        }
    } else {
        for (uint x=lane; x<w; x+=128) M1Seed[x]=M1Row[x];
        GroupMemoryBarrierWithGroupSync();
        M4Envelope(w,lane,0u,limit,scale);
        for (uint x=lane; x<w; x+=128) { M1Left[x]=M1Row[x]; M1Row[x]=M1Seed[x]; }
        GroupMemoryBarrierWithGroupSync();
        M4Envelope(w,lane,1u,limit,scale);
        for (uint x=lane; x<w; x+=128) {
            M4FoveaConditioned[uint3(x,group.x,0u)]=M1Left[x];
            M4FoveaConditioned[uint3(x,group.x,1u)]=M1Row[x];
        }
    }
}

[numthreads(128,1,1)]
void CSConditionM4Vertical(uint3 group:SV_GroupID,uint lane:SV_GroupIndex) {
    const uint h=M4Grid.y, col=group.x;
    if(col>=M4Grid.x || h==0u || h>1024u) return;
    const uint slices=M3Flags.x>.5 ? 2u : 1u;
    const float pv=M1Filter.z*M4Flags.z;
    const float limit=M1Depth.w>0.0 ? 2.0*M1Depth.w : M1Filter.y;
    for(uint slice=0u;slice<slices;++slice) {
    for(uint y=lane;y<h;y+=128u)
        M1Row[y]=M4FoveaConditioned[uint3(col,y,slice)];
    GroupMemoryBarrierWithGroupSync();
    [branch] if(pv>0.0) {
        for(uint step=1u;step<h && float(step-1u)*pv<limit;step*=2u) {
            for(uint y=lane;y<h;y+=128u) {
                const float penalty=float(step)*pv;
                const float above=y>=step ? M1Row[y-step]-penalty : 0.0;
                const float below=y+step<h ? M1Row[y+step]-penalty : 0.0;
                M1Next[y]=max(M1Row[y],max(above,below));
            }
            GroupMemoryBarrierWithGroupSync();
            for(uint y=lane;y<h;y+=128u) M1Row[y]=M1Next[y];
            GroupMemoryBarrierWithGroupSync();
        }
    }
    for(uint y=lane;y<h;y+=128u) {
        M4FoveaConditioned[uint3(col,y,slice)]=M1Row[y];
        if(slices==1u) M4FoveaConditioned[uint3(col,y,1u)]=M1Row[y];
    }
    GroupMemoryBarrierWithGroupSync();
    }
}
"""

M4_READ = r"""float M1ReadCoarseEye(float2 uv, uint eye) {
    const float2 aligned=uv+(M2Sharpen.w>.5 ? float2(0.0,0.0) : M1Eye.zw);
    const float2 cell=clamp(aligned*float2(M1Grid.xy),
                            float2(.5,.5),float2(M1Grid.xy)-.5);
    return M1SoftDepth.SampleLevel(LinearClamp,float3(cell/float2(M1Grid.zw),float(eye)),0);
}

// M4: inside the gaze crop read the fovea's own full-resolution field and ease
// into the shared grid over the outer band. OFF returns the shared grid exactly.
Texture2DArray<float> M4FoveaSoft : register(t8);
float M1ReadConditionedEye(float2 uv, uint eye) {
    const float coarse=M1ReadCoarseEye(uv,eye);
    [branch] if(M4Flags.x>.5 && M4Grid.x>0u && M4Grid.y>0u) {
        const float2 local=(uv-M2Crop.xy)/(M2Crop.zw-M2Crop.xy);
        if(all(local>0.0) && all(local<1.0)) {
            const float edge=min(min(local.x,local.y),min(1.0-local.x,1.0-local.y));
            const float t=saturate(edge/max(M4Flags.w,.0001));
            const float blend=t*t*(3.0-2.0*t);
            const float2 cell=clamp(local*float2(M4Grid.xy),float2(.5,.5),float2(M4Grid.xy)-.5);
            const float fovea=M4FoveaSoft.SampleLevel(LinearClamp,float3(cell/float2(M4Grid.zw),float(eye)),0);
            return lerp(coarse,fovea,blend);
        }
    }
    return coarse;
}"""


def shaders(sh):
    patch(sh/"DuoViewM1Stereo.hlsl", [
        ("M4 constants",
         "    float4 M3Slopes; // x/y: left/right occlusion-side penalty per grid texel, z/w: disocclusion side (0 = unbounded)\n};",
         "    float4 M3Slopes; // x/y: left/right occlusion-side penalty per grid texel, z/w: disocclusion side (0 = unbounded)\n"
         "    uint4 M4Grid; // M4 fovea field: active w,h; allocated w,h (0 = off)\n"
         "    float4 M4Flags; // x: on, y/z: shared-grid texels per fovea texel (x/y), w: read blend band (crop-local)\n"
         "};"),
        ("M4 fovea field UAV",
         "RWByteAddressBuffer M25StatsWrite : register(u4);\n",
         "RWByteAddressBuffer M25StatsWrite : register(u4);\n"
         "RWTexture2DArray<float> M4FoveaConditioned : register(u5);\n"),
        ("M4 kernels",
         "#endif\n\n#ifdef DUOVIEW_M1_RASTER\nTexture2DArray<float> M1SoftDepth : register(t3);",
         M4_KERNELS + "#endif\n\n#ifdef DUOVIEW_M1_RASTER\nTexture2DArray<float> M1SoftDepth : register(t3);"),
        ("M4 fovea-aware conditioned read",
         """float M1ReadConditionedEye(float2 uv, uint eye) {
    const float2 aligned=uv+(M2Sharpen.w>.5 ? float2(0.0,0.0) : M1Eye.zw);
    const float2 cell=clamp(aligned*float2(M1Grid.xy),
                            float2(.5,.5),float2(M1Grid.xy)-.5);
    return M1SoftDepth.SampleLevel(LinearClamp,float3(cell/float2(M1Grid.zw),float(eye)),0);
}""",
         M4_READ),
    ])
    patch(sh/"DuoViewNativeCompositeRaster.hlsl", [
        ("M4 depth picture debug view (4)",
         "                result.rgb=lerp(float3(1.,.1,0.),float3(0.,1.,0.),t.y);\n"
         "        }\n    }\n#endif\n    return result;",
         "                result.rgb=lerp(float3(1.,.1,0.),float3(0.,1.,0.),t.y);\n"
         "        }\n    }\n#endif\n"
         "#ifdef DUOVIEW_M1_RASTER\n"
         "    if(M2Sharpen.z>3.5 && M1Grid.x>0u) {\n"
         "        // Depth picture of the field the warp uses: 0.25 m white, 1 m mid grey, far black.\n"
         "        const float cap=M1Depth.w>0.0 ? 2.0*M1Depth.w : M1Filter.y;\n"
         "        const float ref=M25Flags.y>0.0 ? 1000.0*M25Flags.y : cap;\n"
         "        const float D=M1ReadConditionedEye(outputUv,i.pos.x>=OutputSize.x ? 1u : 0u);\n"
         "        result.rgb=sqrt(saturate(D/max(ref,1.e-8))).xxx;\n"
         "    }\n"
         "#endif\n"
         "    return result;"),
    ])


def backend(mods):
    vr = mods/"vr"
    patch(vr/"DuoViewM1D3D12.hpp", [
        ("M4 constants",
         "    float m3_flags[4]{};\n    float m3_slopes[4]{};\n};\nstatic_assert(sizeof(M1Constants) == 320);",
         "    float m3_flags[4]{};\n    float m3_slopes[4]{};\n"
         "    uint32_t m4_grid[4]{}; // M4 fovea field: active w,h; allocated w,h\n"
         "    float m4_flags[4]{};   // on, x/y texel ratios, read blend band\n"
         "};\nstatic_assert(sizeof(M1Constants) == 352);"),
        ("M4 members",
         "    ComPtr<ID3D12PipelineState> raster, condition, vertical, m25_analyse, m25_guard;\n",
         "    ComPtr<ID3D12PipelineState> raster, condition, vertical, m25_analyse, m25_guard;\n"
         "    // M4: optional; a failure here disables only M4, never the stereo path.\n"
         "    ComPtr<ID3D12PipelineState> m4_condition, m4_vertical;\n"
         "    ComPtr<ID3D12Resource> m4_depth;\n"
         "    bool m4_active{};\n"
         "    uint32_t m4_columns{},m4_rows{};\n"
         "    inline static std::atomic<uint64_t> m4_frames{};\n"
         "    inline static std::atomic<uint32_t> m4_last_w{},m4_last_h{},m4_fine_w{},m4_fine_h{};\n"
         "    static void m4_count_frame() {++m4_frames;}\n"),
        ("M4 pipelines",
         "        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m25_guard)))) return false;\n",
         "        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m25_guard)))) return false;\n"
         "        compute.CS={m4_condition_bytecode,sizeof(m4_condition_bytecode)};\n"
         "        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4_condition)))) m4_condition.Reset();\n"
         "        compute.CS={m4_vertical_bytecode,sizeof(m4_vertical_bytecode)};\n"
         "        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4_vertical)))) m4_vertical.Reset();\n"),
        ("M4 fovea field texture",
         "            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, nullptr, IID_PPV_ARGS(&soft_depth)))) return false;\n",
         "            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, nullptr, IID_PPV_ARGS(&soft_depth)))) return false;\n"
         "        // M4: fixed 1024x1024 two-slice fovea field (8 MiB), allocated once, never resized.\n"
         "        texture.Width = grid_limit;\n"
         "        texture.Height = grid_limit;\n"
         "        if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &texture,\n"
         "            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, nullptr, IID_PPV_ARGS(&m4_depth)))) m4_depth.Reset();\n"),
        ("M4 writer parameter (defaulted: fixtures keep their call)",
         "                         D3D12_CPU_DESCRIPTOR_HANDLE focus_srv) {",
         "                         D3D12_CPU_DESCRIPTOR_HANDLE focus_srv, bool m4_fovea_grid=false) {"),
        ("M4 reset per frame",
         "        fovea_depth_active=false;\n",
         "        fovea_depth_active=false;\n"
         "        m4_active=false; m4_columns=m4_rows=0;\n"),
        ("M4 constants after the final grid and M3 slopes",
         "        void* address{};\n        const D3D12_RANGE no_read{0,0};",
         "        if(m4_fovea_grid && fine_ok && focus && data.grid[0] && data.grid[1] &&\n"
         "           m4_condition && m4_vertical && m4_depth) {\n"
         "            const auto field=m4_depth->GetDesc();\n"
         "            const float fw=float(focus->rect[2]), fh=float(focus->rect[3]);\n"
         "            const float fit=(std::min)({1.f,float(field.Width)/fw,float(field.Height)/fh});\n"
         "            const uint32_t w4=(std::clamp)(uint32_t(fw*fit),1u,uint32_t(field.Width));\n"
         "            const uint32_t h4=(std::clamp)(uint32_t(fh*fit),1u,uint32_t(field.Height));\n"
         "            data.m4_grid[0]=w4; data.m4_grid[1]=h4;\n"
         "            data.m4_grid[2]=uint32_t(field.Width); data.m4_grid[3]=uint32_t(field.Height);\n"
         "            data.m4_flags[0]=1.f;\n"
         "            data.m4_flags[1]=float(data.grid[0])*(data.m2_crop[2]-data.m2_crop[0])/float(w4);\n"
         "            data.m4_flags[2]=float(data.grid[1])*(data.m2_crop[3]-data.m2_crop[1])/float(h4);\n"
         "            data.m4_flags[3]=.15f; // outer 15% of the crop eases into the shared grid\n"
         "            m4_active=true; m4_columns=w4; m4_rows=h4;\n"
         "            m4_last_w=w4; m4_last_h=h4; m4_fine_w=focus->rect[2]; m4_fine_h=focus->rect[3];\n"
         "        }\n"
         "        void* address{};\n        const D3D12_RANGE no_read{0,0};"),
        ("M4 depth picture debug value",
         "        data.m2_sharpen[2] = float((std::min)(depth_debug,3u));",
         "        data.m2_sharpen[2] = float((std::min)(depth_debug,4u));"),
    ])

    patch(vr/"DuoViewD3D12.hpp", [
        ("M4 writer receives setting",
         "                settings.m3_edges,settings.m3_fold_sharpness,settings.m3_fill,settings.m3_jitter_mode,\n"
         "                m1_raw_srv_,m2_fovea_srv_);",
         "                settings.m3_edges,settings.m3_fold_sharpness,settings.m3_fill,settings.m3_jitter_mode,\n"
         "                m1_raw_srv_,m2_fovea_srv_,settings.m4_fovea_grid);"),
        ("M4 root ranges",
         "        D3D12_ROOT_PARAMETER params[7]{};",
         "        D3D12_DESCRIPTOR_RANGE m4_field_range{};\n"
         "        m4_field_range.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_SRV;\n"
         "        m4_field_range.NumDescriptors=1; // t8 M4 fovea field (heap slot 12)\n"
         "        m4_field_range.BaseShaderRegister=8;\n"
         "        D3D12_DESCRIPTOR_RANGE m4_output_range{};\n"
         "        m4_output_range.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_UAV;\n"
         "        m4_output_range.NumDescriptors=1; // u5 M4 fovea field (heap slot 13)\n"
         "        m4_output_range.BaseShaderRegister=5;\n"
         "        D3D12_ROOT_PARAMETER params[9]{};"),
        ("M4 root parameters",
         "        params[6].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;\n",
         "        params[6].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;\n"
         "        params[7].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;\n"
         "        params[7].DescriptorTable={1,&m4_field_range};\n"
         "        params[7].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;\n"
         "        params[8].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;\n"
         "        params[8].DescriptorTable={1,&m4_output_range};\n"
         "        params[8].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;\n"),
        ("M4 root signature size",
         "D3D12_ROOT_SIGNATURE_DESC desc{7, params,",
         "D3D12_ROOT_SIGNATURE_DESC desc{9, params,"),
        ("M4 descriptor heap size",
         "hd.NumDescriptors = 12;",
         "hd.NumDescriptors = 14;"),
        ("M4 descriptors",
         "        device->CreateUnorderedAccessView(m1_.m25_stats.Get(),nullptr,&stats_uav,desc_cpu);\n",
         "        device->CreateUnorderedAccessView(m1_.m25_stats.Get(),nullptr,&stats_uav,desc_cpu);\n"
         "        desc_cpu.ptr+=srv_descriptor_increment_; // [12] t8 M4 fovea field\n"
         "        device->CreateShaderResourceView(m1_.m4_depth.Get(),&soft_array_srv,desc_cpu);\n"
         "        desc_cpu.ptr+=srv_descriptor_increment_; // [13] u5 M4 fovea field\n"
         "        device->CreateUnorderedAccessView(m1_.m4_depth.Get(),nullptr,&soft_uav,desc_cpu);\n"),
        ("M4 compute tables",
         "            raw.ptr+=UINT64(4)*srv_descriptor_increment_;\n"
         "            cmd->SetComputeRootDescriptorTable(6,raw);\n",
         "            raw.ptr+=UINT64(4)*srv_descriptor_increment_;\n"
         "            cmd->SetComputeRootDescriptorTable(6,raw);\n"
         "            auto m4_table=srv_gpu_start_;\n"
         "            m4_table.ptr+=UINT64(12)*srv_descriptor_increment_;\n"
         "            cmd->SetComputeRootDescriptorTable(7,m4_table);\n"
         "            m4_table.ptr+=srv_descriptor_increment_;\n"
         "            cmd->SetComputeRootDescriptorTable(8,m4_table);\n"),
        ("M4 dispatch after the shared field",
         "                M1Resources::m25_count_vertical();\n            }\n",
         "                M1Resources::m25_count_vertical();\n            }\n"
         "            if(m1_.m4_active) {\n"
         "                transition(cmd,m1_.m4_depth.Get(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,\n"
         "                           D3D12_RESOURCE_STATE_UNORDERED_ACCESS);\n"
         "                cmd->SetPipelineState(m1_.m4_condition.Get());\n"
         "                cmd->Dispatch(m1_.m4_rows,1,1);\n"
         "                if(m1_.vertical_active) {\n"
         "                    D3D12_RESOURCE_BARRIER m4_uav{};\n"
         "                    m4_uav.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;\n"
         "                    m4_uav.UAV.pResource=m1_.m4_depth.Get();\n"
         "                    cmd->ResourceBarrier(1,&m4_uav);\n"
         "                    cmd->SetPipelineState(m1_.m4_vertical.Get());\n"
         "                    cmd->Dispatch(m1_.m4_columns,1,1);\n"
         "                }\n"
         "                transition(cmd,m1_.m4_depth.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,\n"
         "                           D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);\n"
         "                M1Resources::m4_count_frame();\n"
         "            }\n"),
        ("M4 raster table",
         "            raw.ptr+=UINT64(5)*srv_descriptor_increment_;\n"
         "            cmd->SetGraphicsRootDescriptorTable(5,raw);\n",
         "            raw.ptr+=UINT64(5)*srv_descriptor_increment_;\n"
         "            cmd->SetGraphicsRootDescriptorTable(5,raw);\n"
         "            auto m4_field=srv_gpu_start_;\n"
         "            m4_field.ptr+=UINT64(12)*srv_descriptor_increment_;\n"
         "            cmd->SetGraphicsRootDescriptorTable(7,m4_field);\n"),
    ])

    patch(vr/"DuoViewConfig.hpp", [
        ("M4 setting",
         "    uint32_t m3_jitter_mode{0}; // 0=legacy toggle, 1=+jitter, 2=-jitter\n",
         "    uint32_t m3_jitter_mode{0}; // 0=legacy toggle, 1=+jitter, 2=-jitter\n"
         "    bool m4_fovea_grid{false}; // M4: fovea keeps its own full-resolution depth field\n"),
        ("M4 validate",
         "    out.m3_jitter_mode=(std::min)(requested.m3_jitter_mode,2u);\n",
         "    out.m3_jitter_mode=(std::min)(requested.m3_jitter_mode,2u);\n"
         "    out.m4_fovea_grid=requested.m4_fovea_grid;\n"),
    ])

    patch(vr/"D3D12Component.cpp", [
        ("M4 log line next to M2.5a",
         "                                                const auto s=depths.m25_take_window();\n",
         "                                                SPDLOG_INFO(\"[DuoView][M4] fovea_grid={} frames={} grid={}x{} fine_in={}x{}\",\n"
         "                                                    config.settings.m4_fovea_grid,\n"
         "                                                    uevr::duoview::dx12::M1Resources::m4_frames.exchange(0),\n"
         "                                                    uevr::duoview::dx12::M1Resources::m4_last_w.load(),\n"
         "                                                    uevr::duoview::dx12::M1Resources::m4_last_h.load(),\n"
         "                                                    uevr::duoview::dx12::M1Resources::m4_fine_w.load(),\n"
         "                                                    uevr::duoview::dx12::M1Resources::m4_fine_h.load());\n"
         "                                                const auto s=depths.m25_take_window();\n"),
    ])

    patch(mods/"VR.hpp", [
        ("M4 option",
         '    const ModToggle::Ptr m_duo_m3_edges{ModToggle::create(generate_name("DuoM3PerEyeEdges"),false)};\n',
         '    const ModToggle::Ptr m_duo_m3_edges{ModToggle::create(generate_name("DuoM3PerEyeEdges"),false)};\n'
         '    const ModToggle::Ptr m_duo_m4_fovea_grid{ModToggle::create(generate_name("DuoM4FoveaDepthGrid"),false)};\n'),
        ("M4 depth picture debug range",
         'generate_name("DuoM25DepthDebug"),0.f,3.f,0.f)',
         'generate_name("DuoM25DepthDebug"),0.f,4.f,0.f)'),
        ("M4 persist",
         '*m_duo_m3_jitter, *m_duo_m2_fovea_depth,',
         '*m_duo_m3_jitter, *m_duo_m4_fovea_grid, *m_duo_m2_fovea_depth,'),
    ])

    patch(mods/"VR.cpp", [
        ("M4 default",
         "                    m_duo_m3_fill->value()=true; m_duo_m3_jitter->value()=0;\n",
         "                    m_duo_m3_fill->value()=true; m_duo_m3_jitter->value()=0;\n"
         "                    m_duo_m4_fovea_grid->value()=false;\n"),
        ("M4 implies content-checked fine depth",
         "        .m2_fovea_depth=m_duo_m2_fovea_depth->value(),\n"
         "        .m25_fine_mode=uint32_t(m_duo_m25_fine_mode->value()>=.5f),\n",
         "        .m2_fovea_depth=m_duo_m2_fovea_depth->value() || m_duo_m4_fovea_grid->value(),\n"
         "        .m25_fine_mode=m_duo_m4_fovea_grid->value() ? 1u : uint32_t(m_duo_m25_fine_mode->value()>=.5f),\n"),
        ("M4 freeze (declaration order: right after m3_jitter_mode)",
         "        .m3_jitter_mode=uint32_t((std::clamp)(m_duo_m3_jitter->value(),0,2)),\n",
         "        .m3_jitter_mode=uint32_t((std::clamp)(m_duo_m3_jitter->value(),0,2)),\n"
         "        .m4_fovea_grid=m_duo_m4_fovea_grid->value(),\n"),
        ("M4 depth picture debug clamp",
         "(std::clamp)(m_duo_m21_depth_debug->value(),0.f,3.f)",
         "(std::clamp)(m_duo_m21_depth_debug->value(),0.f,4.f)"),
        ("M4 equality",
         "        current.m3_jitter_mode==candidate.m3_jitter_mode &&\n",
         "        current.m3_jitter_mode==candidate.m3_jitter_mode &&\n"
         "        current.m4_fovea_grid==candidate.m4_fovea_grid &&\n"),
        ("M4 menu (top of the depth group)",
         '                    ImGui::TextWrapped("Depth edges (stereo geometry, not image sharpening):");\n',
         '                    ImGui::TextWrapped("Depth edges (stereo geometry, not image sharpening):");\n'
         '                    m_duo_m4_fovea_grid->draw("M4 FULL-RES FOVEA DEPTH (fovea uses its own sharp depth; turns fine depth on)");\n'),
        ("M4 debug label",
         'm_duo_m21_depth_debug->draw("Depth debug (0=off, 1=conditioned, 2=fine weight, 3=disagreement)");',
         'm_duo_m21_depth_debug->draw("Depth debug (0=off, 1=red depth edges, 2=fine weight, 3=disagreement, 4=depth picture)");'),
    ])


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: apply_duoview_m4_fovea.py <backend> <shaders>")
    shaders(Path(sys.argv[2]))
    backend(Path(sys.argv[1])/"src/mods")
    print("M4: full-resolution fovea depth field, one setting (default OFF), depth picture debug 4")


if __name__ == "__main__":
    main()

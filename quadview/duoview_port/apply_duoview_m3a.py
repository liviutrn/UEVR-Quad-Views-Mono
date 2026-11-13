#!/usr/bin/env python3
"""DuoView M3a combined build (Claude): per-eye one-sided depth edges with
background fill, jitter-direction switch, M2.5a review fixes (parallel guard,
new debug key), sharpening menu grouping, and contract C2 producer.

Run after apply_duoview_m25a_gpu.py. Every edit is exact-once. With every new
setting at its default (M3 edges OFF, jitter mode 0) output is unchanged.
"""
import shutil
import sys
from pathlib import Path
from apply_duoview_b40_pipeline import patch


def shaders(sh):
    patch(sh/"DuoViewM1Stereo.hlsl", [
        ("M3 constants",
         "    float4 M25Flags; // x: content-checked fine\n};",
         "    float4 M25Flags; // x: content-checked fine\n"
         "    float4 M3Flags; // x: per-eye edges, y: jitter sign (0 = legacy +), z: fill stretch threshold (0 = off)\n"
         "    float4 M3Slopes; // x/y: left/right occlusion-side penalty per grid texel, z/w: disocclusion side (0 = unbounded)\n"
         "};\n\n"
         "float M1JitterSign() { return M3Flags.y!=0.0 ? M3Flags.y : 1.0; }\n"
         "float2 M1CoarseCorrection() { return M2Sharpen.w>.5 ? M1Eye.zw*M1JitterSign() : float2(0.0,0.0); }\n"
         "float2 M2FineJitter() { return M2FoveaFlags.xy*M1JitterSign(); }"),
        ("M3 per-eye conditioned slices",
         "RWTexture2D<float> M1ConditionedDepth : register(u2);",
         "RWTexture2DArray<float> M1ConditionedDepth : register(u2);"),
        ("M3 seed and left-eye rows",
         "groupshared float M1Row[1024];\ngroupshared float M1Next[1024];",
         "groupshared float M1Row[1024];\ngroupshared float M1Next[1024];\n"
         "groupshared float M1Seed[1024];\ngroupshared float M1Left[1024];"),
        ("M3 analysis uses shared fine jitter",
         "const float2 jit=clamp(local+M2FoveaFlags.xy,.5/dimension,1.-.5/dimension);",
         "const float2 jit=clamp(local+M2FineJitter(),.5/dimension,1.-.5/dimension);"),
        ("M3 analysis uses shared coarse correction",
         "const float2 correction=M2Sharpen.w>.5 ? M1Eye.zw : float2(0.,0.);",
         "const float2 correction=M1CoarseCorrection();"),
        ("M3 parallel guard reduction",
         """[numthreads(1,1,1)]
void CSGuardM25(uint3 unused:SV_DispatchThreadID) {
    const uint2 sz=(M1Grid.xy+15u)/16u;
    uint cells=0u,agree=0u,varied=0u,passing=0u,weightSum=0u,activeTiles=0u;
    for(uint y=0u;y<sz.y;++y) for(uint x=0u;x<sz.x;++x) {
        const float4 t=M25TileRead.Load(int3(x,y,0));""",
         """groupshared uint M25Sum[6*256];
[numthreads(256,1,1)]
void CSGuardM25(uint lane:SV_GroupIndex) {
    const uint2 sz=(M1Grid.xy+15u)/16u;
    uint cells=0u,agree=0u,varied=0u,passing=0u,weightSum=0u,activeTiles=0u;
    for(uint i=lane;i<sz.x*sz.y;i+=256u) {
        const uint x=i%sz.x,y=i/sz.x;
        const float4 t=M25TileRead.Load(int3(x,y,0));"""),
        ("M3 guard group sum",
         """        weightSum+=uint(t.x*1000.+.5);
    }
    const uint guard=varied>0u && passing*2u<varied ? 1u : 0u;""",
         """        weightSum+=uint(t.x*1000.+.5);
    }
    M25Sum[lane]=cells;M25Sum[256u+lane]=agree;M25Sum[512u+lane]=varied;
    M25Sum[768u+lane]=passing;M25Sum[1024u+lane]=weightSum;M25Sum[1280u+lane]=activeTiles;
    GroupMemoryBarrierWithGroupSync();
    for(uint step=128u;step>0u;step>>=1u) {
        if(lane<step)
            [unroll] for(uint j=0u;j<6u;++j) M25Sum[j*256u+lane]+=M25Sum[j*256u+lane+step];
        GroupMemoryBarrierWithGroupSync();
    }
    if(lane!=0u) return;
    cells=M25Sum[0];agree=M25Sum[256];varied=M25Sum[512];
    passing=M25Sum[768];weightSum=M25Sum[1024];activeTiles=M25Sum[1280];
    const uint guard=varied>0u && passing*2u<varied ? 1u : 0u;"""),
        ("M3 seed uses shared coarse correction",
         "        const float2 correction=M2Sharpen.w>.5 ? M1Eye.zw : float2(0.0,0.0);",
         "        const float2 correction=M1CoarseCorrection();"),
        ("M3 seed uses shared fine jitter",
         "const float2 jit=clamp(local+M2FoveaFlags.xy,.5/dimension,1.0-.5/dimension);",
         "const float2 jit=clamp(local+M2FineJitter(),.5/dimension,1.0-.5/dimension);"),
        ("M3 one-sided per-eye envelope helper",
         "[numthreads(128,1,1)]\nvoid CSConditionM1(uint3 group : SV_GroupID, uint lane : SV_GroupIndex) {",
         """// One eye's warp source = base + k*D(source) folds only where k*D' > 1, i.e.
// on ONE side of a near object. Bound that side (occlusion) to keep the warp
// monotone; the other side (disocclusion) may stay sharp and is filled later.
// Max-minus-linear-penalty by doubling stays exact with unequal penalties.
void M3Envelope(uint w, uint lane, uint eye, float limit) {
    const float k=M1Eye[eye];
    const float pf=eye==0u ? M3Slopes.x : M3Slopes.y;
    const float ps=eye==0u ? M3Slopes.z : M3Slopes.w;
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
void CSConditionM1(uint3 group : SV_GroupID, uint lane : SV_GroupIndex) {"""),
        ("M3 per-eye or symmetric envelope",
         """    const float limit = M1Depth.w > 0.0 ? 2.0*M1Depth.w : M1Filter.y;
    // Each pass doubles the reachable radius. Stop only when more distant
    // contributions would be <= 0, or all texels in the row are reachable.
    for (uint step = 1; step < w && float(step-1)*M1Filter.x < limit; step *= 2) {
        for (uint x = lane; x < w; x += 128) {
            const float penalty = float(step)*M1Filter.x;
            const float l = x >= step ? M1Row[x-step] - penalty : 0.0;
            const float r = x+step < w ? M1Row[x+step] - penalty : 0.0;
            M1Next[x] = max(M1Row[x], max(l,r));
        }
        GroupMemoryBarrierWithGroupSync();
        for (uint x = lane; x < w; x += 128) M1Row[x] = M1Next[x];
        GroupMemoryBarrierWithGroupSync();
    }
    for (uint x = lane; x < w; x += 128)
        M1ConditionedDepth[uint2(x,group.x)] = M1Row[x];
}""",
         """    const float limit = M1Depth.w > 0.0 ? 2.0*M1Depth.w : M1Filter.y;
    [branch] if (M3Flags.x < .5) {
        // Each pass doubles the reachable radius. Stop only when more distant
        // contributions would be <= 0, or all texels in the row are reachable.
        for (uint step = 1; step < w && float(step-1)*M1Filter.x < limit; step *= 2) {
            for (uint x = lane; x < w; x += 128) {
                const float penalty = float(step)*M1Filter.x;
                const float l = x >= step ? M1Row[x-step] - penalty : 0.0;
                const float r = x+step < w ? M1Row[x+step] - penalty : 0.0;
                M1Next[x] = max(M1Row[x], max(l,r));
            }
            GroupMemoryBarrierWithGroupSync();
            for (uint x = lane; x < w; x += 128) M1Row[x] = M1Next[x];
            GroupMemoryBarrierWithGroupSync();
        }
        for (uint x = lane; x < w; x += 128) {
            M1ConditionedDepth[uint3(x,group.x,0u)] = M1Row[x];
            M1ConditionedDepth[uint3(x,group.x,1u)] = M1Row[x];
        }
    } else {
        for (uint x = lane; x < w; x += 128) M1Seed[x] = M1Row[x];
        GroupMemoryBarrierWithGroupSync();
        M3Envelope(w,lane,0u,limit);
        for (uint x = lane; x < w; x += 128) { M1Left[x] = M1Row[x]; M1Row[x] = M1Seed[x]; }
        GroupMemoryBarrierWithGroupSync();
        M3Envelope(w,lane,1u,limit);
        for (uint x = lane; x < w; x += 128) {
            M1ConditionedDepth[uint3(x,group.x,0u)] = M1Left[x];
            M1ConditionedDepth[uint3(x,group.x,1u)] = M1Row[x];
        }
    }
}"""),
        ("M3 vertical pass per eye slice",
         """    for(uint y=lane;y<h;y+=128u)
        M1Row[y]=M1ConditionedDepth[uint2(col,y)];
    GroupMemoryBarrierWithGroupSync();
    const float pv=M1Filter.z;
    [branch] if(pv>0.0) {""",
         """    const uint slices=M3Flags.x>.5 ? 2u : 1u;
    for(uint slice=0u;slice<slices;++slice) {
    for(uint y=lane;y<h;y+=128u)
        M1Row[y]=M1ConditionedDepth[uint3(col,y,slice)];
    GroupMemoryBarrierWithGroupSync();
    const float pv=M1Filter.z;
    [branch] if(pv>0.0) {"""),
        ("M3 vertical writes per slice",
         "    for(uint y=lane;y<h;y+=128u) M1ConditionedDepth[uint2(col,y)]=M1Row[y];\n}",
         "    for(uint y=lane;y<h;y+=128u) {\n"
         "        M1ConditionedDepth[uint3(col,y,slice)]=M1Row[y];\n"
         "        if(slices==1u) M1ConditionedDepth[uint3(col,y,1u)]=M1Row[y];\n"
         "    }\n"
         "    GroupMemoryBarrierWithGroupSync();\n"
         "    }\n}"),
        ("M3 conditioned field is a two-slice array",
         "Texture2D<float> M1SoftDepth : register(t3);",
         "Texture2DArray<float> M1SoftDepth : register(t3);"),
        ("M3 per-eye conditioned read",
         """float M1ReadConditioned(float2 uv) {
    const float2 aligned=uv+(M2Sharpen.w>.5 ? float2(0.0,0.0) : M1Eye.zw);
    const float2 cell=clamp(aligned*float2(M1Grid.xy),
                            float2(.5,.5),float2(M1Grid.xy)-.5);
    return M1SoftDepth.SampleLevel(LinearClamp,cell/float2(M1Grid.zw),0);
}""",
         """float M1ReadConditionedEye(float2 uv, uint eye) {
    const float2 aligned=uv+(M2Sharpen.w>.5 ? float2(0.0,0.0) : M1Eye.zw);
    const float2 cell=clamp(aligned*float2(M1Grid.xy),
                            float2(.5,.5),float2(M1Grid.xy)-.5);
    return M1SoftDepth.SampleLevel(LinearClamp,float3(cell/float2(M1Grid.zw),float(eye)),0);
}
float M1ReadConditioned(float2 uv) { return M1ReadConditionedEye(uv,0u); }

// A target pixel whose solved source sits on a sharp disocclusion step was
// never seen by the centre camera. Mirror nearby background into it instead
// of stretching the edge texel across the hole (no new geometry, no streaks).
float M3FillHole(float baseX, float root, float y, float k, uint eye) {
    const float du=1.0/float(M1Grid.x);
    const float dl=M1ReadConditionedEye(float2(root-du,y),eye);
    const float dr=M1ReadConditionedEye(float2(root+du,y),eye);
    const float stretch=1.0-k*(dr-dl)/(2.0*du);
    if(!(stretch>M3Flags.z)) return root;
    const float dir=dr<dl ? 1.0 : -1.0;
    float ub=root;
    float d=M1ReadConditionedEye(float2(ub,y),eye);
    [loop] for(uint i=0u;i<32u;++i) {
        const float un=ub+dir*du;
        const float dn=M1ReadConditionedEye(float2(un,y),eye);
        const bool flat=abs(k*(dn-d))<.5*du;
        ub=un;
        d=dn;
        if(flat) break;
    }
    float um=2.0*ub-(baseX+k*d);
    if((um-ub)*dir<0.0) um=ub;
    const float dm=M1ReadConditionedEye(float2(um,y),eye);
    if(abs(dm-d)>max(.05*d,1.e-4)) um=ub;
    return clamp(um,0.0,1.0);
}"""),
        ("M3 bisection reads this eye's field",
         "const float residual=base.x+k*M1ReadConditioned(float2(mid,base.y))-mid;",
         "const float residual=base.x+k*M1ReadConditionedEye(float2(mid,base.y),eye)-mid;"),
        ("M3 hole fill after the monotone solve",
         "        uv.x=clamp(root,lo,hi);\n    }\n    return saturate(uv);",
         "        uv.x=clamp(root,lo,hi);\n"
         "        [branch] if(M3Flags.x>.5 && M3Flags.z>0.0) uv.x=M3FillHole(base.x,uv.x,base.y,k,eye);\n"
         "    }\n    return saturate(uv);"),
    ])


def backend(mods, here):
    vr = mods/"vr"
    for name in ("UevrSourceRolesV1.h", "UevrSourceRolesProducer.hpp"):
        shutil.copyfile(here/name, vr/name)

    patch(vr/"DuoViewM1D3D12.hpp", [
        ("M3 constants",
         "    float m25_flags[4]{}; // x: GPU content gate\n};\nstatic_assert(sizeof(M1Constants) == 288);",
         "    float m25_flags[4]{}; // x: GPU content gate\n"
         "    float m3_flags[4]{};\n    float m3_slopes[4]{};\n};\n"
         "static_assert(sizeof(M1Constants) == 320);"),
        ("M3 two slices",
         "        texture.Format = DXGI_FORMAT_R32_FLOAT;\n        texture.SampleDesc.Count = 1;",
         "        texture.Format = DXGI_FORMAT_R32_FLOAT;\n"
         "        texture.DepthOrArraySize = 2; // M3a: one conditioned slice per eye\n"
         "        texture.SampleDesc.Count = 1;"),
        ("M3 writer parameters",
         "                         float fade_far_m,float far_regular,float far_wide,\n",
         "                         float fade_far_m,float far_regular,float far_wide,\n"
         "                         bool m3_edges,float m3_fold,bool m3_fill,uint32_t jitter_mode,\n"),
        ("M3 constants filled after the final grid",
         "        data.m25_flags[1]=geometry.world_to_meters>0.f ? .004f/geometry.world_to_meters : 0.f; // 0.004 inverse metres\n",
         "        data.m25_flags[1]=geometry.world_to_meters>0.f ? .004f/geometry.world_to_meters : 0.f; // 0.004 inverse metres\n"
         "        if(jitter_mode==1u || jitter_mode==2u) {\n"
         "            data.m2_sharpen[3]=1.f;\n"
         "            data.m3_flags[1]=jitter_mode==1u ? 1.f : -1.f;\n"
         "        }\n"
         "        if(m3_edges && data.grid[0]) {\n"
         "            data.m3_flags[0]=1.f;\n"
         "            data.m3_flags[2]=m3_fill ? 2.f : 0.f;\n"
         "            const float fold=(std::clamp)(m3_fold,.5f,.98f);\n"
         "            for(int e=0;e<2;++e) {\n"
         "                const float scale=(std::max)(std::abs(data.eye[e]),.00001f)*float(data.grid[0]);\n"
         "                data.m3_slopes[e]=fold/scale;\n"
         "                data.m3_slopes[2+e]=m3_fill ? 0.f : softness/scale;\n"
         "            }\n"
         "        }\n"),
    ])

    patch(vr/"DuoViewD3D12.hpp", [
        ("M3 writer receives settings",
         "                settings.m24_fade_normal_far,settings.m24_fade_wide_far,\n                m1_raw_srv_,m2_fovea_srv_);",
         "                settings.m24_fade_normal_far,settings.m24_fade_wide_far,\n"
         "                settings.m3_edges,settings.m3_fold_sharpness,settings.m3_fill,settings.m3_jitter_mode,\n"
         "                m1_raw_srv_,m2_fovea_srv_);"),
        ("M3 two-slice SRV",
         "        device->CreateShaderResourceView(m1_.soft_depth.Get(),&soft_srv,desc_cpu);",
         "        D3D12_SHADER_RESOURCE_VIEW_DESC soft_array_srv{};\n"
         "        soft_array_srv.Format=DXGI_FORMAT_R32_FLOAT;\n"
         "        soft_array_srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2DARRAY;\n"
         "        soft_array_srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;\n"
         "        soft_array_srv.Texture2DArray.MipLevels=1;\n"
         "        soft_array_srv.Texture2DArray.ArraySize=2;\n"
         "        device->CreateShaderResourceView(m1_.soft_depth.Get(),&soft_array_srv,desc_cpu);"),
        ("M3 two-slice UAV",
         "        soft_uav.Format=DXGI_FORMAT_R32_FLOAT;\n        soft_uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;",
         "        soft_uav.Format=DXGI_FORMAT_R32_FLOAT;\n"
         "        soft_uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2DARRAY;\n"
         "        soft_uav.Texture2DArray.ArraySize=2;"),
    ])

    patch(vr/"DuoViewConfig.hpp", [
        ("M3 settings",
         "    uint32_t m25_fine_mode{0}; // 0=M2.4 strict, 1=GPU content gate\n",
         "    uint32_t m25_fine_mode{0}; // 0=M2.4 strict, 1=GPU content gate\n"
         "    bool m3_edges{false};\n"
         "    float m3_fold_sharpness{.95f};\n"
         "    bool m3_fill{true};\n"
         "    uint32_t m3_jitter_mode{0}; // 0=legacy toggle, 1=+jitter, 2=-jitter\n"),
        ("M3 validate",
         "    out.m25_fine_mode=(std::min)(requested.m25_fine_mode,1u);\n",
         "    out.m25_fine_mode=(std::min)(requested.m25_fine_mode,1u);\n"
         "    out.m3_edges=requested.m3_edges;\n"
         "    if(std::isfinite(requested.m3_fold_sharpness))\n"
         "        out.m3_fold_sharpness=(std::clamp)(requested.m3_fold_sharpness,.5f,.98f);\n"
         "    out.m3_fill=requested.m3_fill;\n"
         "    out.m3_jitter_mode=(std::min)(requested.m3_jitter_mode,2u);\n"),
    ])

    patch(mods/"VR.hpp", [
        ("M3 options",
         '    const ModSlider::Ptr m_duo_m25_fine_mode{ModSlider::create(generate_name("DuoM25FineMode"),0.f,1.f,0.f)};\n',
         '    const ModSlider::Ptr m_duo_m25_fine_mode{ModSlider::create(generate_name("DuoM25FineMode"),0.f,1.f,0.f)};\n'
         '    const ModToggle::Ptr m_duo_m3_edges{ModToggle::create(generate_name("DuoM3PerEyeEdges"),false)};\n'
         '    const ModSlider::Ptr m_duo_m3_fold{ModSlider::create(generate_name("DuoM3OcclusionSharpness"),.5f,.98f,.95f)};\n'
         '    const ModToggle::Ptr m_duo_m3_fill{ModToggle::create(generate_name("DuoM3BackgroundFill"),true)};\n'
         '    const ModCombo::Ptr m_duo_m3_jitter{ModCombo::create(generate_name("DuoM3JitterMode"),s_duo_m3_jitter_modes,0)};\n'),
        ("M3 jitter mode names",
         '    static const inline std::vector<std::string> s_quadview_b40_presets{',
         '    static const inline std::vector<std::string> s_duo_m3_jitter_modes{ "Legacy (M2.1 toggle)", "Align: + direction", "Align: - direction" };\n'
         '    static const inline std::vector<std::string> s_quadview_b40_presets{'),
        ("M3 debug selector gets its own key",
         'generate_name("DuoM21DepthDebug"),0.f,3.f,0.f)',
         'generate_name("DuoM25DepthDebug"),0.f,3.f,0.f)'),
        ("M3 persist",
         '            *m_duo_m25_fine_mode, *m_duo_m2_fovea_depth,',
         '            *m_duo_m25_fine_mode, *m_duo_m3_edges, *m_duo_m3_fold, *m_duo_m3_fill, *m_duo_m3_jitter, *m_duo_m2_fovea_depth,'),
    ])

    patch(mods/"VR.cpp", [
        ("M3 defaults",
         "                    m_duo_m25_fine_mode->value()=0.f;\n",
         "                    m_duo_m25_fine_mode->value()=0.f;\n"
         "                    m_duo_m3_edges->value()=false; m_duo_m3_fold->value()=.95f;\n"
         "                    m_duo_m3_fill->value()=true; m_duo_m3_jitter->value()=0;\n"),
        ("M3 freeze",
         "        .m25_fine_mode=uint32_t(m_duo_m25_fine_mode->value()>=.5f),\n",
         "        .m25_fine_mode=uint32_t(m_duo_m25_fine_mode->value()>=.5f),\n"
         "        .m3_edges=m_duo_m3_edges->value(),\n"
         "        .m3_fold_sharpness=m_duo_m3_fold->value(),\n"
         "        .m3_fill=m_duo_m3_fill->value(),\n"
         "        .m3_jitter_mode=uint32_t((std::clamp)(m_duo_m3_jitter->value(),0,2)),\n"),
        ("M3 equality",
         "        current.m25_fine_mode==candidate.m25_fine_mode &&\n",
         "        current.m25_fine_mode==candidate.m25_fine_mode &&\n"
         "        current.m3_edges==candidate.m3_edges &&\n"
         "        current.m3_fold_sharpness==candidate.m3_fold_sharpness &&\n"
         "        current.m3_fill==candidate.m3_fill &&\n"
         "        current.m3_jitter_mode==candidate.m3_jitter_mode &&\n"),
        ("Sharpening group: per-eye and distance fade join the other sharpen controls",
         """                if (m_duo_sharpen_wide->value()) {
                    m_duo_m23_wide->draw("Wide sharpen strength (independent of regular)");
                    m_duo_m23_unlinked_wide->draw("Separate left/right wide sharpen");
                    if (m_duo_m23_unlinked_wide->value()) {
                        m_duo_m23_wide_left->draw("Left eye wide sharpen strength");
                        m_duo_m23_wide_right->draw("Right eye wide sharpen strength");
                    }
                }
""",
         """                if (m_duo_sharpen_wide->value()) {
                    m_duo_m23_wide->draw("Wide sharpen strength (independent of regular)");
                    m_duo_m23_unlinked_wide->draw("Separate left/right wide sharpen");
                    if (m_duo_m23_unlinked_wide->value()) {
                        m_duo_m23_wide_left->draw("Left eye wide sharpen strength");
                        m_duo_m23_wide_right->draw("Right eye wide sharpen strength");
                    }
                }
                if (m_duo_stereo->value()) {
                    m_duo_m2_unlinked->draw("Separate left/right sharpening (synthetic stereo)");
                    if (m_duo_m2_unlinked->value()) {
                        m_duo_m2_left->draw("Left eye sharpen");
                        m_duo_m2_right->draw("Right eye sharpen");
                    }
                    m_duo_m24_distance->draw("Distance-faded sharpening (synthetic stereo)");
                    if(m_duo_m24_distance->value()) {
                        m_duo_m24_near->draw("Full sharpness nearer than (metres)");
                        m_duo_m24_far->draw("Fade complete at (metres)");
                        m_duo_m24_regular_pct->draw("Far normal sharpen (%)");
                        m_duo_m24_wide_pct->draw("Far wide sharpen (%)");
                    }
                }
"""),
        ("Stereo group: depth-edge geometry only, with M3a controls",
         """                    m_duo_stereo_softness->draw("Depth edge sharpness (higher = harder edge)");
                    m_duo_m2_fovea_depth->draw("M2 fine fovea depth (experimental: off by default)");
                    if (m_duo_m2_fovea_depth->value()) m_duo_m25_fine_mode->draw("Fine depth check (0=M2.4 strict, 1=content-checked)");
                    m_duo_m24_vertical->draw("M2.4 Vertical depth taper (0 = M2.3)");
                    m_duo_m24_distance->draw("M2.4 Distance-faded sharpening (synthetic stereo only)");
                    if(m_duo_m24_distance->value()) {
                        m_duo_m24_near->draw("Full sharpness nearer than (metres)");
                        m_duo_m24_far->draw("Fade complete at (metres)");
                        m_duo_m24_regular_pct->draw("Far normal sharpen (%)");
                        m_duo_m24_wide_pct->draw("Far wide sharpen (%)");
                    }
                    m_duo_m21_depth_debug->draw("Depth debug (0=off, 1=conditioned, 2=fine weight, 3=disagreement)");
                    m_duo_m21_jitter->draw("M2.1 align NGX depth jitter (A/B test; OFF is M1 baseline)");
                    m_duo_m2_unlinked->draw("Separate left/right sharpening");
                    if (m_duo_m2_unlinked->value()) {
                        m_duo_m2_left->draw("Left eye sharpen");
                        m_duo_m2_right->draw("Right eye sharpen");
                    }
""",
         """                    ImGui::TextWrapped("Depth edges (stereo geometry, not image sharpening):");
                    m_duo_m3_edges->draw("M3a per-eye edges (sharp occlusion side; OFF = M2.4 symmetric)");
                    if (m_duo_m3_edges->value()) {
                        m_duo_m3_fold->draw("Occlusion edge sharpness (0.98 = crispest)");
                        m_duo_m3_fill->draw("Fill revealed background (OFF = soft membrane on that side)");
                        if (!m_duo_m3_fill->value())
                            m_duo_stereo_softness->draw("Disocclusion softness (higher = harder edge)");
                    } else {
                        m_duo_stereo_softness->draw("Depth edge sharpness (higher = harder edge)");
                    }
                    m_duo_m3_jitter->draw("Depth jitter alignment (test + and -: pick the one with less edge flicker)");
                    if (m_duo_m3_jitter->value()==0)
                        m_duo_m21_jitter->draw("M2.1 align NGX depth jitter (legacy toggle)");
                    m_duo_m24_vertical->draw("Vertical depth taper (0 = row only)");
                    m_duo_m2_fovea_depth->draw("M2 fine fovea depth (experimental: off by default)");
                    if (m_duo_m2_fovea_depth->value()) m_duo_m25_fine_mode->draw("Fine depth check (0=M2.4 strict, 1=content-checked)");
                    m_duo_m21_depth_debug->draw("Depth debug (0=off, 1=conditioned, 2=fine weight, 3=disagreement)");
"""),
    ])

    patch(vr/"QuadViewNgxDepth.hpp", [
        ("C2 producer include",
         "#include <safetyhook.hpp>\n",
         "#include <safetyhook.hpp>\n#include \"UevrSourceRolesProducer.hpp\"\n"),
        ("C2 role publication from DuoView's own requested extents",
         "        if (!want_w || !want_h) { last_reason_.store(NoExpectedSize, std::memory_order_relaxed); return {}; }\n"
         "        const bool fine_output=duo && request &&",
         """        if (!want_w || !want_h) { last_reason_.store(NoExpectedSize, std::memory_order_relaxed); return {}; }
        {
            uint32_t role=UEVR_ROLE_UNKNOWN;
            if(duo && request) {
                const bool fovea=matches_periphery(out_w,out_h,request->fovea_width,request->fovea_height);
                const bool periphery=matches_periphery(out_w,out_h,want_w,want_h);
                if(fovea!=periphery) role=fovea ? UEVR_ROLE_DUO_FOVEA : UEVR_ROLE_DUO_PERIPHERY;
            } else if(!duo && matches_periphery(out_w,out_h,want_w,want_h)) {
                role=UEVR_ROLE_TRI_PERIPHERY;
            }
            bool known_other=false;
            if(role!=UEVR_ROLE_UNKNOWN) {
                std::scoped_lock lock(mutex_);
                const auto kind=feature_kind_.find(reinterpret_cast<uintptr_t>(feature));
                known_other=kind!=feature_kind_.end() && kind->second!=1u;
            }
            if(role!=UEVR_ROLE_UNKNOWN && !known_other) {
                uint32_t role_in_w=ngx_uint(p,"DLSS.Render.Subrect.Dimensions.Width");
                uint32_t role_in_h=ngx_uint(p,"DLSS.Render.Subrect.Dimensions.Height");
                if(!role_in_w) role_in_w=ngx_uint(p,"Width");
                if(!role_in_h) role_in_h=ngx_uint(p,"Height");
                uevr::contracts::SourceRoleTable::self().note(
                    uint64_t(reinterpret_cast<uintptr_t>(feature)),role,duo ? 6u : 7u,
                    duo ? uint64_t(request->generation) : (uint64_t(want_w)<<32 | want_h),
                    out_w,out_h,role_in_w,role_in_h);
            }
        }
        const bool fine_output=duo && request &&"""),
    ])

    d3d = vr/"D3D12Component.cpp"
    text = d3d.read_text(encoding="utf-8-sig")
    marker = "} // namespace vrmod"
    if not text.rstrip().endswith(marker) or text.count("UEVR_GetSourceRolesV1"):
        raise SystemExit("C2 export anchor drifted")
    text = text.rstrip() + """

#include "UevrSourceRolesProducer.hpp"
// Contract C2 v1: Cheeky resolves this export by name from UEVRBackend.dll.
extern "C" __declspec(dllexport) int __cdecl UEVR_GetSourceRolesV1(UevrSourceRolesV1* out) {
    return uevr::contracts::SourceRoleTable::self().snapshot(out);
}
"""
    d3d.write_text(text, encoding="utf-8", newline="\n")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: apply_duoview_m3a.py <backend> <shaders>")
    mods = Path(sys.argv[1])/"src/mods"
    shaders(Path(sys.argv[2]))
    backend(mods, Path(__file__).resolve().parent)
    print("M3a: per-eye edges + background fill, jitter direction, parallel guard, debug key, menu groups, C2 producer")


if __name__ == "__main__":
    main()

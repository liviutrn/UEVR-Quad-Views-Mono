#!/usr/bin/env python3
"""M2.4 visual changes after M2.3: vertical envelope, fade, and Mono-wide.

Exact-once edits intentionally fail on drift. Only generated DuoView ID6 files,
not TriView ID7, are edited; FXC emits M24 vertical bytecode offline.
"""
import sys
from pathlib import Path
from apply_duoview_b40_pipeline import patch


def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: apply_duoview_m24_visual.py <backend> <duoview-shaders>")
    mods=Path(sys.argv[1])/"src/mods"
    sh=Path(sys.argv[2])
    patch(mods/"vr/DuoViewConfig.hpp",[
        ("M24 settings", "    bool m23_wide_unlinked{false};",
         """    float m24_vertical_taper{2.f};
    bool m24_distance_fade{false};
    float m24_fade_near_m{2.f}, m24_fade_far_m{15.f};
    float m24_fade_normal_far{.4f},m24_fade_wide_far{.2f};
    bool m23_wide_unlinked{false};"""),
        ("M24 state reconciliation", "    out.m23_wide_unlinked=requested.m23_wide_unlinked;",
         """    out.m24_distance_fade=requested.m24_distance_fade;
    if(std::isfinite(requested.m24_vertical_taper))
        out.m24_vertical_taper=(std::clamp)(requested.m24_vertical_taper,0.f,8.f);
    if(std::isfinite(requested.m24_fade_near_m))
        out.m24_fade_near_m=(std::clamp)(requested.m24_fade_near_m,.25f,100.f);
    if(std::isfinite(requested.m24_fade_far_m))
        out.m24_fade_far_m=(std::clamp)(requested.m24_fade_far_m,.5f,200.f);
    if(std::isfinite(requested.m24_fade_normal_far))
        out.m24_fade_normal_far=(std::clamp)(requested.m24_fade_normal_far,0.f,1.f);
    if(std::isfinite(requested.m24_fade_wide_far))
        out.m24_fade_wide_far=(std::clamp)(requested.m24_fade_wide_far,0.f,1.f);
    out.m23_wide_unlinked=requested.m23_wide_unlinked;"""),
    ])
    patch(mods/"VR.hpp",[
        ("M24 sliders in original DuoView UI",
         '    const ModSlider::Ptr m_duo_m23_wide{',
         '''    const ModSlider::Ptr m_duo_m24_vertical{ModSlider::create(generate_name("DuoM24VerticalTaper"),0.f,8.f,2.f)};
    const ModToggle::Ptr m_duo_m24_distance{ModToggle::create(generate_name("DuoM24DistanceFade"),false)};
    const ModSlider::Ptr m_duo_m24_near{ModSlider::create(generate_name("DuoM24FadeNearM"),.25f,100.f,2.f)};
    const ModSlider::Ptr m_duo_m24_far{ModSlider::create(generate_name("DuoM24FadeFarM"),.5f,200.f,15.f)};
    const ModSlider::Ptr m_duo_m24_regular_pct{ModSlider::create(generate_name("DuoM24NormalFarPercent"),0.f,100.f,40.f)};
    const ModSlider::Ptr m_duo_m24_wide_pct{ModSlider::create(generate_name("DuoM24WideFarPercent"),0.f,100.f,20.f)};
    const ModSlider::Ptr m_duo_m23_wide{'''),
        ("M24 persist all settings",
         '*m_duo_m23_wide, *m_duo_m23_unlinked_wide,',
         '*m_duo_m24_vertical, *m_duo_m24_distance, *m_duo_m24_near, *m_duo_m24_far, *m_duo_m24_regular_pct, *m_duo_m24_wide_pct, *m_duo_m23_wide, *m_duo_m23_unlinked_wide,'),
    ])
    patch(mods/"VR.cpp",[
        ("M24 defaults", "m_duo_m23_wide->value()=1.f;",
         """m_duo_m24_vertical->value()=2.f;
                    m_duo_m24_distance->value()=false;
                    m_duo_m24_near->value()=2.f; m_duo_m24_far->value()=15.f;
                    m_duo_m24_regular_pct->value()=40.f; m_duo_m24_wide_pct->value()=20.f;
                    m_duo_m23_wide->value()=1.f;"""),
        ("M24 menu",
         'm_duo_m2_fovea_depth->draw("M2 fine fovea depth (experimental: off by default)");',
         '''m_duo_m2_fovea_depth->draw("M2 fine fovea depth (experimental: off by default)");
                    m_duo_m24_vertical->draw("M2.4 Vertical depth taper (0 = M2.3)");
                    m_duo_m24_distance->draw("M2.4 Distance-faded sharpening");
                    if(m_duo_m24_distance->value()) {
                        m_duo_m24_near->draw("Full sharpness nearer than (metres)");
                        m_duo_m24_far->draw("Fade complete at (metres)");
                        m_duo_m24_regular_pct->draw("Far normal sharpen (%)");
                        m_duo_m24_wide_pct->draw("Far wide sharpen (%)");
                    }'''),
        ("M24 freeze settings",
         '.m23_wide_unlinked=m_duo_m23_unlinked_wide->value(),',
         '''.m24_vertical_taper=m_duo_m24_vertical->value(),
        .m24_distance_fade=m_duo_m24_distance->value(),
        .m24_fade_near_m=m_duo_m24_near->value(),
        .m24_fade_far_m=m_duo_m24_far->value(),
        .m24_fade_normal_far=m_duo_m24_regular_pct->value()*.01f,
        .m24_fade_wide_far=m_duo_m24_wide_pct->value()*.01f,
        .m23_wide_unlinked=m_duo_m23_unlinked_wide->value(),'''),
        ("M24 settings equality",
         'current.m23_wide_unlinked==candidate.m23_wide_unlinked &&',
         '''current.m24_vertical_taper==candidate.m24_vertical_taper &&
        current.m24_distance_fade==candidate.m24_distance_fade &&
        current.m24_fade_near_m==candidate.m24_fade_near_m &&
        current.m24_fade_far_m==candidate.m24_fade_far_m &&
        current.m24_fade_normal_far==candidate.m24_fade_normal_far &&
        current.m24_fade_wide_far==candidate.m24_fade_wide_far &&
        current.m23_wide_unlinked==candidate.m23_wide_unlinked &&'''),
    ])
    # IMPORTANT: M1Resources is instantiated per fenced XR command slot.
    # The second compute shader executes on the same list, same UAV, same slot;
    # no new source texture is allocated, and no in-flight leases are modified.
    patch(mods/"vr/DuoViewM1D3D12.hpp",[
        ("M24 fade float4",
         "    float m23_wide[4]{};",
         "    float m23_wide[4]{};\n    float m24_fade[4]{};"),
        ("M24 constant 272 bytes",
         "static_assert(sizeof(M1Constants) == 256);",
         "static_assert(sizeof(M1Constants) == 272);"),
        ("M24 512 byte upload limit",
         "static_assert(sizeof(M1Constants) <= D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT);",
         "static_assert(sizeof(M1Constants) <= 2*D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT);"),
        ("M24 two shaders and stencil",
         "ComPtr<ID3D12PipelineState> raster, condition;",
         "ComPtr<ID3D12PipelineState> raster, condition, vertical;"),
        ("M24 real eye size for penalty",
         "    bool fovea_depth_active{};",
         """    bool fovea_depth_active{};
    bool vertical_active{};
    uint32_t grid_columns{};
    uint32_t output_width_px{},output_height_px{};"""),
        ("M24 ready requires vertical PSO",
         "bool ready() const { return raster && condition && soft_depth && constants; }",
         "bool ready() const { return raster && condition && vertical && soft_depth && constants; }"),
        ("M24 create vertical PSO",
         "        if (FAILED(device->CreateComputePipelineState(&compute, IID_PPV_ARGS(&condition)))) return false;",
         """        if (FAILED(device->CreateComputePipelineState(&compute, IID_PPV_ARGS(&condition)))) return false;
        compute.CS={m24_vertical_bytecode,sizeof(m24_vertical_bytecode)};
        if (FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&vertical)))) return false;
        output_width_px=eye_width; output_height_px=eye_height;"""),
        ("M24 512 upload bytes",
         "        buffer.Width = D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT;",
         "        buffer.Width = 2*D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT;"),
        ("M24 writer controls",
         'float left_wide, float right_wide, float near_m, float softness,',
         '''float left_wide, float right_wide, float near_m, float softness,
                         float vertical_taper,bool distance_fade,float fade_near_m,
                         float fade_far_m,float far_regular,float far_wide,'''),
        ("M24 fade input",
         '        data.m23_wide[1]=(std::clamp)(right_wide,0.f,20.f);',
         '''        data.m23_wide[1]=(std::clamp)(right_wide,0.f,20.f);
        // geometry.world_to_meters ALREADY includes world scale: do not multiply twice.
        if(distance_fade && fade_far_m>fade_near_m && fade_near_m>0.f &&
           geometry.world_to_meters>0.f) {
            data.m24_fade[0]=1.f/(fade_near_m*geometry.world_to_meters);
            data.m24_fade[1]=1.f/(fade_far_m*geometry.world_to_meters);
            data.m24_fade[2]=(std::clamp)(far_regular,0.f,1.f);
            data.m24_fade[3]=(std::clamp)(far_wide,0.f,1.f);
        }'''),
        ("M24 full grid coarse-on",
         'data.grid[0] = (std::min)(uint32_t(soft.Width), input->rect[2]);',
         'data.grid[0] = uint32_t(soft.Width); // M2.4 constant 1024 grid, fine ON/OFF invariant'),
        ("M24 full grid coarse-on height",
         'data.grid[1] = (std::min)(soft.Height, input->rect[3]);',
         'data.grid[1] = soft.Height; // frame-constant resolution avoids fine ON/OFF jump'),
        ("M24 vertical penalty at coarse",
         'data.filter[0] = softness / ((std::max)(kmax, .00001f) * float(data.grid[0]));',
         '''data.filter[0] = softness / ((std::max)(kmax, .00001f) * float(data.grid[0]));
                data.filter[2] = vertical_taper>0.f && output_width_px && output_height_px ?
                    vertical_taper*float(output_height_px)/
                    ((std::max)(kmax,.00001f)*float(output_width_px)*float(data.grid[1])) : 0.f;'''),
        ("M24 fine weight",
         '                data.m2_fovea_flags[3]=1.f;',
         '''                data.m2_fovea_flags[3]=1.f;
                data.filter[3]=(std::clamp)(focus->fine_weight,0.f,1.f);'''),
        ("M24 condition columns",
         "        rows = data.grid[1];",
         """        rows = data.grid[1];
        grid_columns = data.grid[0];
        vertical_active = grid_columns>0 && rows>0 && data.filter[2]>0.f;"""),
        ("M24 fine input metadata",
         "    std::shared_ptr<const void> lease;",
         "    std::shared_ptr<const void> lease;\n    float fine_weight{1.f};"),
    ])
    # M24 vertical pass runs on same per-slot UAV following a real UAV barrier.
    # No cross-list resource ownership changes, and when taper=0 the pass is
    # skipped to reproduce the M2.3 row-only field.
    patch(mods/"vr/DuoViewD3D12.hpp",[
        ("M24 writer controls",
         'settings.stereo_near_m,settings.stereo_softness,',
         '''settings.stereo_near_m,settings.stereo_softness,
                settings.m24_vertical_taper, settings.m24_distance_fade,
                settings.m24_fade_near_m,settings.m24_fade_far_m,
                settings.m24_fade_normal_far,settings.m24_fade_wide_far,'''),
        ("M24 vertical dispatch",
         '''            cmd->Dispatch(m1_.rows,1,1);
            transition(cmd,m1_.soft_depth.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                       D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);''',
         '''            cmd->Dispatch(m1_.rows,1,1);
            if(m1_.vertical_active) {
                D3D12_RESOURCE_BARRIER uav{};
                uav.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;
                uav.UAV.pResource=m1_.soft_depth.Get();
                cmd->ResourceBarrier(1,&uav);
                cmd->SetPipelineState(m1_.vertical.Get());
                cmd->Dispatch(m1_.grid_columns,1,1);
            }
            transition(cmd,m1_.soft_depth.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                       D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);'''),
        ("M24 gather linked wide strength",
         '{frame.settings.focus_power, 0.f, 0.f, 0.f}',
         '{frame.settings.focus_power, frame.settings.sharpen_wide ? frame.settings.m23_wide_strength : 0.f, 0.f, 0.f}'),
        ("M24 native linked wide strength",
         '{frame.config.settings.focus_power, 0.f, 0.f, 0.f}',
         '{frame.config.settings.focus_power, frame.config.settings.sharpen_wide ? frame.config.settings.m23_wide_strength : 0.f, 0.f, 0.f}'),
        ("M24 direct-XR Mono wide must use compositor",
         'settings.sharpen_strength<=0.f && !settings.focus_lift_enabled && !settings.seam_match_enabled',
         'settings.sharpen_strength<=0.f && (!settings.sharpen_wide || settings.m23_wide_strength<=0.f) && !settings.focus_lift_enabled && !settings.seam_match_enabled'),
    ])
    patch(sh/"DuoViewM1Stereo.hlsl",[
        ("M24 fade HLSL constant",
         '    float4 M23Wide; // independent left/right extra-wide strength, 0=OFF',
         '    float4 M23Wide; // independent left/right extra-wide strength, 0=OFF\n    float4 M24Fade; // near inverse depth, far inverse depth, far normal/extra-wide ratios'),
        ("M24 fine valid ramp inside original global envelope",
         'if(fineNear>0.0) nearDepth=lerp(nearDepth,fineNear,feather);',
         'if(fineNear>0.0) nearDepth=lerp(nearDepth,fineNear,feather*M1Filter.w);'),
        ("M24 vertical compute shader",
         '''#endif

#ifdef DUOVIEW_M1_RASTER
Texture2D<float> M1SoftDepth''',
         '''// Vertical max-minus-penalty envelope after the row pass. Max over
// translated rowwise Lipschitz fields preserves the horizontal bound.
// A second UAV barrier is required between dispatches on the SAME queue.
[numthreads(128,1,1)]
void CSConditionM1Vertical(uint3 group:SV_GroupID,uint lane:SV_GroupIndex) {
    const uint h=M1Grid.y, col=group.x;
    if(col>=M1Grid.x || h==0u) return;
    for(uint y=lane;y<h;y+=128u)
        M1Row[y]=M1ConditionedDepth[uint2(col,y)];
    GroupMemoryBarrierWithGroupSync();
    const float pv=M1Filter.z;
    [branch] if(pv>0.0) {
        const float limit=M1Depth.w>0.0 ? 2.0*M1Depth.w : M1Filter.y;
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
    for(uint y=lane;y<h;y+=128u) M1ConditionedDepth[uint2(col,y)]=M1Row[y];
}
#endif

#ifdef DUOVIEW_M1_RASTER
Texture2D<float> M1SoftDepth'''),
    ])
    patch(sh/"DuoViewNativeCompositeRaster.hlsl",[
        ("M24 normal variable",
         'const float fineSharpen=rightEye ? M2Sharpen.y : M2Sharpen.x;',
         'float fineSharpen=rightEye ? M2Sharpen.y : M2Sharpen.x;'),
        ("M24 wide variable",
         'const float wideSharpen=rightEye ? M23Wide.y : M23Wide.x;',
         'float wideSharpen=rightEye ? M23Wide.y : M23Wide.x;'),
        ("M24 Mono wide independent",
         'const float wideSharpen=SharpenStrength;',
         'const float wideSharpen=FocusProfile.y; // M24 linked Mono-wide source, independent of regular'),
        ("M24 fade normal and wide only in stereo",
         '''        float wideSharpen=rightEye ? M23Wide.y : M23Wide.x;
#else''',
         '''        float wideSharpen=rightEye ? M23Wide.y : M23Wide.x;
        [branch] if(M24Fade.x>M24Fade.y && M1Grid.x>0u) {
            // Full near detail, separate far fractions. Conditioned depth only.
            const float D=M1ReadConditioned(fullUv);
            const float t=smoothstep(M24Fade.y,M24Fade.x,D);
            fineSharpen*=lerp(M24Fade.z,1.0,t);
            wideSharpen*=lerp(M24Fade.w,1.0,t);
        }
#else'''),
    ])
    # Packed Mono's dispatch selection must not skip wide with normal==0.
    patch(mods/"vr/DuoViewD3D12.hpp",[
        ("M24 Mono packed wide-on routing",
         'frame.settings.sharpen_strength>0.f;',
         'frame.settings.sharpen_strength>0.f || (frame.settings.sharpen_wide && frame.settings.m23_wide_strength>0.f);'),
    ])
    print("M2.4 visual: 2D depth envelope + central B40 corners + scaled distance fading + true Mono-wide")
if __name__=="__main__":
    main()

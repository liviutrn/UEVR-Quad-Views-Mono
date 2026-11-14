#!/usr/bin/env python3
"""Accumulate eye-crop edge depth and disocclusion fill on the compositor queue."""
from pathlib import Path
import sys

from apply_duoview_b40_pipeline import patch


def shaders(sh):
    helper = Path(__file__).with_name("DuoViewFoveaTemporal.hlsl").read_text(encoding="utf-8")
    path = sh / "DuoViewM1Stereo.hlsl"
    old = path.read_text(encoding="utf-8")
    start = old.index("// Raw fine depth from the previous accepted transaction.")
    end = old.index("[numthreads(128,1,1)]", start)
    patch(path, [
        ("temporal parameters", "    float4 M5Sharpen;",
         "    float4 M7Controls;\n    uint4 M7ColorExtent;\n    float4 M7Tuning; // x: maximum temporal edge correction in output pixels\n    float4 M5Sharpen;"),
        ("accumulated history kernels", old[start:end], helper + "\n"),
        ("feed each stabilized seed back into history",
         "        fine=M6StabilizeFineEdge(local,fine,farDepth);",
         """        [branch] if (M7Controls.w>.5) {
            const float2 fullUv=lerp(M2Crop.xy,M2Crop.zw,local);
            const float rawNear=fine;
            fine=M7StabilizeEdge(fullUv,rawNear,farDepth);
            float representativeDepth=0., packed=0.;
            [branch] if (M7Controls.y>0.) {
                representativeDepth=DecodeM2Depth(int2(jit*dimension));
                packed=M7PackColor(M7AccumulateFillColor(local,fullUv,representativeDepth));
            }
            M7CurrentWrite[uint2(x,group.x)]=float4(fine,representativeDepth,packed,rawNear);
        }"""),
        ("fill records signed background direction and original root",
         """                  out float2 fill) {
    fill=0.;""",
         """                  out float3 fill, bool inCrop) {
    fill=0.;"""),
        ("expose only classified holes in the fine crop",
         """    if (M4Flags.x>.5) {
        const float tap=um+dir*M6PreviousJitter.w;
        const float tapDepth=M1ReadConditionedEye(float2(tap,y),eye);
        if(tap>=0. && tap<=1. && abs(tapDepth-d)<=max(.05*d,1.e-4))
            fill=float2(tap,saturate((stretch-2.0)*.5)*.25);
    }""",
         """    if (inCrop && um>M2Crop.x && um<M2Crop.z)
        fill=float3(dir,d,1.);"""),
        ("send disocclusion metadata to the raster", "out float2 fill) {", "out float3 fill) {"),
        ("apply M4 hole treatment only inside the gaze crop",
         """        [branch] if(M4Flags.x>.5 || (M3Flags.x>.5 && M3Flags.z>0.0))
            uv.x=M3FillHole(base.x,uv.x,base.y,k,eye,fill);""",
         """        const bool inCrop=M4Flags.x>.5 && all(uv>M2Crop.xy) && all(uv<M2Crop.zw);
        [branch] if(inCrop || (M3Flags.x>.5 && M3Flags.z>0.0))
            uv.x=M3FillHole(base.x,uv.x,base.y,k,eye,fill,inCrop);"""),
    ])
    raster = sh / "DuoViewNativeCompositeRaster.hlsl"
    old = raster.read_text(encoding="utf-8")
    start = old.index("#ifdef DUOVIEW_M1_RASTER\n    [branch] if (DebugViewMode==0 && fill.y>0.)")
    end = old.index("    if (DebugBorder", start)
    patch(raster, [
        ("current accumulated colour is visible to raster",
         '#include "DuoViewM1Stereo.hlsl"',
         """#include "DuoViewM1Stereo.hlsl"
Texture2D<float4> M7CurrentHistory : register(t10);
float3 M7UnpackColor(float packed) {
    const uint bits=uint(packed);
    const float3 encoded=float3(bits&255u,(bits>>8u)&255u,(bits>>16u)&255u)/255.;
    return encoded*encoded;
}
"""),
        ("hole metadata", "    float2 fill=0.;", "    float3 fill=0.;"),
        ("replace only the foveal component of the uncovered background", old[start:end],
         ""),
        ("blend history only into fill and keep its spatial blur independent",
         """        if (DebugViewMode == 0) fovea.rgb = DuoPhase2FocusLift(fovea.rgb, localFovea);""",
         """#ifdef DUOVIEW_M1_RASTER
        [branch] if (DebugViewMode==0 && fill.z>.5 && (M7Controls.y>0. || M7Controls.z>0.)) {
            float3 filled=DuoReadFocus(fullUv);
            [branch] if (M7Controls.y>0. && M7Controls.w>.5) {
                const int2 cell=min(int2(saturate(localFovea)*float2(M4Grid.xy)),int2(M4Grid.xy)-1);
                const float4 history=M7CurrentHistory.Load(int3(cell,0));
                const float3 accumulated=M7UnpackColor(history.z);
                // The conditioned fill depth can differ from the raw source.
                // Compare colours here as well to reject a foreground tap.
                const float3 diff=abs(accumulated-filled);
                const float agreement=1.-smoothstep(.12,.45,max(diff.x,max(diff.y,diff.z)));
                filled=lerp(filled,accumulated,agreement);
            }
            [branch] if (M7Controls.z>.001) {
                // Real depth-aware 5-tap blur of the newly uncovered background.
                // Unlike the old 25% single-neighbour tap, the max 12px
                // radius covers an appreciable area and can reach full strength.
                // Foreground taps never enter the average.
                float3 sum=filled*1.5;
                float sumWeight=1.5;
                const uint eye=i.pos.x>=OutputSize.x ? 1u : 0u;
                [unroll] for (int offset=-2;offset<=2;++offset) {
                    if (offset==0) continue;
                    const float2 tap=fullUv+
                        float2(fill.x*M7Controls.z/M23Wide.z*(float(offset)*.5),0.);
                    if (all(tap>M2Crop.xy) && all(tap<M2Crop.zw)) {
                        const float tapDepth=M1ReadConditionedEye(tap,eye);
                        if (abs(tapDepth-fill.y)<=max(.08*fill.y,1.e-4)) {
                            const float weight=abs(offset)==1 ? 1.0 : .7;
                            sum+=DuoReadFocus(tap)*weight;
                            sumWeight+=weight;
                        }
                    }
                }
                filled=lerp(filled,sum/max(sumWeight,.01),saturate(M7Controls.z/2.));
            }
            fovea.rgb=filled;
        }
#endif
        if (DebugViewMode == 0) fovea.rgb = DuoPhase2FocusLift(fovea.rgb, localFovea);"""),
    ])


def controls(mods):
    cfg = mods / "vr/DuoViewConfig.hpp"
    patch(cfg, [
        ("saved fovea-only temporal settings",
         "    float m5_left_max{.10f}, m5_right_max{.10f}; // M5: per-eye sharpen limiter",
         """    float m5_left_max{.10f}, m5_right_max{.10f}; // M5: per-eye sharpen limiter
    float edge_history{.70f}, fill_history{.65f}, fill_blur_px{1.25f}, edge_reach_px{8.f};"""),
        ("validate controls",
         "    out.m4_fovea_grid=requested.m4_fovea_grid;",
         """    out.m4_fovea_grid=requested.m4_fovea_grid;
    if (std::isfinite(requested.edge_history))
        out.edge_history=(std::clamp)(requested.edge_history,0.f,.95f);
    if (std::isfinite(requested.fill_history))
        out.fill_history=(std::clamp)(requested.fill_history,0.f,.95f);
    if (std::isfinite(requested.fill_blur_px))
        out.fill_blur_px=(std::clamp)(requested.fill_blur_px,0.f,32.f);
    if (std::isfinite(requested.edge_reach_px))
        out.edge_reach_px=(std::clamp)(requested.edge_reach_px,2.f,20.f);"""),
    ])
    patch(mods / "VR.hpp", [
        ("three persistent sliders", '    const ModSlider::Ptr m_duo_m5_right_max{',
         """    const ModSlider::Ptr m_duo_edge_history{ModSlider::create(generate_name("DuoEdgeHistory"),0.f,.95f,.70f)};
    const ModSlider::Ptr m_duo_edge_reach{ModSlider::create(generate_name("DuoEdgeHistoryReachPixels"),2.f,20.f,8.f)};
    const ModSlider::Ptr m_duo_fill_history{ModSlider::create(generate_name("DuoFillHistory"),0.f,.95f,.65f)};
    const ModSlider::Ptr m_duo_fill_blur{ModSlider::create(generate_name("DuoFillBlurPixels"),0.f,32.f,1.25f)};
    const ModSlider::Ptr m_duo_m5_right_max{"""),
        ("save and load the three controls", "*m_duo_m5_right_max,",
         "*m_duo_m5_right_max, *m_duo_edge_history, *m_duo_fill_history, *m_duo_fill_blur, *m_duo_edge_reach,"),
    ])
    patch(mods / "VR.cpp", [
        ("reset default values",
         "                    m_duo_m5_left_max->value()=.10f; m_duo_m5_right_max->value()=.10f;",
         """                    m_duo_m5_left_max->value()=.10f; m_duo_m5_right_max->value()=.10f;
                    m_duo_edge_history->value()=.70f;
                    m_duo_edge_reach->value()=8.f;
                    m_duo_fill_history->value()=.65f;
                    m_duo_fill_blur->value()=1.25f;"""),
        ("freeze controls with the packet",
         "        .m5_right_max=m_duo_m5_right_max->value(),",
         """        .m5_right_max=m_duo_m5_right_max->value(),
        .edge_history=m_duo_edge_history->value(),
        .fill_history=m_duo_fill_history->value(),
        .fill_blur_px=m_duo_fill_blur->value(),
        .edge_reach_px=m_duo_edge_reach->value(),"""),
        ("live setting equality",
         "        current.m5_right_max==candidate.m5_right_max &&",
         """        current.m5_right_max==candidate.m5_right_max &&
        current.edge_history==candidate.edge_history &&
        current.fill_history==candidate.fill_history &&
        current.fill_blur_px==candidate.fill_blur_px &&
        current.edge_reach_px==candidate.edge_reach_px &&"""),
        ("show in the existing M4 controls",
         '                    m_duo_m4_fovea_grid->draw("M4 FULL-RES FOVEA DEPTH (fovea uses its own sharp depth; turns fine depth on)");',
         """                    m_duo_m4_fovea_grid->draw("M4 FULL-RES FOVEA DEPTH (fovea uses its own sharp depth; turns fine depth on)");
                    if (m_duo_m4_fovea_grid->value()) {
                        m_duo_edge_history->draw("Fovea depth edge history (0 = off)");
                        if (m_duo_edge_history->value()>0.f)
                            m_duo_edge_reach->draw("Maximum temporal edge correction (2..20 output px)");
                        m_duo_fill_history->draw("Revealed background history (0 = off)");
                        m_duo_fill_blur->draw("Revealed background blur radius (output px, 0..32)");
                    }"""),
    ])


def backend(mods):
    controls(mods)
    vr = mods / "vr"
    hdr = vr / "DuoViewM1D3D12.hpp"
    old = hdr.read_text(encoding="utf-8")
    start = old.index("        previous_fovea_lease.reset();")
    end = old.index("        void* address{};", start)
    patch(hdr, [
        ("history stores a GPU-written image, not an NGX input",
         """    M1DepthInput depth;
    float jitter_sign{};""",
         """    std::array<uint32_t,2> extent{};
    unsigned index{};
    bool color_valid{};
    float edge_history{};
    uint32_t fovea_view{}, jitter_mode{};"""),
        ("parameter block layout", "    float m5_sharpen[4]{};",
         "    float m7_controls[4]{};\n    uint32_t m7_color_extent[4]{};\n    float m7_tuning[4]{};\n    float m5_sharpen[4]{};"),
        ("parameter block and CBV remain aligned",
         """sizeof(M1Constants) == 496);
static_assert(sizeof(M1Constants) <= 2*D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT);""",
         """sizeof(M1Constants) == 544);
inline constexpr UINT m1_constant_bytes =
    (sizeof(M1Constants)+D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT-1) &
    ~(D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT-1);"""),
        ("allocate aligned CBV bytes", "buffer.Width = 2*D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT;",
         "buffer.Width = m1_constant_bytes;"),
        ("old per-NGX lease is unnecessary", ", previous_fovea_lease;", ";"),
        ("complete inputs for the shared history",
         """                         const FineDepthHistoryFrame* previous=nullptr,
                         D3D12_CPU_DESCRIPTOR_HANDLE previous_srv={}) {""",
         """                         const FineDepthHistoryFrame* previous,
                         bool write_history, float edge_history, float fill_history, float fill_blur,
                         float edge_reach_px, const std::array<uint32_t,4>& color_extent) {"""),
        ("required arguments follow required sharpening",
         "float left_max_change=.10f, float right_max_change=.10f,",
         "float left_max_change, float right_max_change,"),
        ("required arguments follow required M4 flag", "bool m4_fovea_grid=false,", "bool m4_fovea_grid,"),
        ("write independent history controls", old[start:end],
         """        data.m23_wide[2]=float(output_width_px);
        data.m7_controls[0]=edge_history;
        data.m7_controls[1]=fill_history;
        data.m7_controls[2]=fill_blur;
        data.m7_controls[3]=write_history ? 1.f : 0.f;
        data.m7_tuning[0]=edge_reach_px;
        std::copy(color_extent.begin(),color_extent.end(),data.m7_color_extent);
        if (m4_active && previous) {
            const auto motion=stereo::fine_depth_reprojection(geometry.fine_depth_camera,previous->camera);
            std::memcpy(data.m6_view,motion.rows.data(),sizeof(data.m6_view));
            std::copy(geometry.fine_depth_camera.projection.begin(),geometry.fine_depth_camera.projection.end(),
                      data.m6_current_projection);
            std::copy(motion.previous_projection.begin(),motion.previous_projection.end(),data.m6_previous_projection);
            std::copy(previous->crop.begin(),previous->crop.end(),data.m6_previous_crop);
            data.m6_previous_rect[2]=previous->extent[0];
            data.m6_previous_rect[3]=previous->extent[1];
            data.m6_previous_jitter[2]=previous->edge_history>0.f ? 1.f : 0.f;
            data.m6_previous_jitter[3]=previous->color_valid ? 1.f : 0.f;
        }
"""),
    ])
    path = vr / "DuoViewD3D12.hpp"
    old = path.read_text(encoding="utf-8")
    start = old.index("        const auto now=std::chrono::steady_clock::now();",old.index("bool record_native("))
    end = old.index("        const bool m1_active=",start)
    patch(path, [
        ("double buffered history belongs to the same compositor queue",
         "    FineDepthHistoryFrame fine_depth;",
         """    FineDepthHistoryFrame fine_depth;
    std::array<ComPtr<ID3D12Resource>,2> temporal;"""),
        ("preallocate both images and leave base M4 available if allocation fails",
         '        state->buffer->SetName(L"DuoView B40 Mono queue-owned history");',
         """        state->buffer->SetName(L"DuoView B40 Mono queue-owned history");
        desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width=desc.Height=M1Resources::grid_limit;
        desc.Layout=D3D12_TEXTURE_LAYOUT_UNKNOWN;
        desc.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
        D3D12_FEATURE_DATA_FORMAT_SUPPORT support{};
        support.Format=desc.Format;
        if (FAILED(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT,&support,sizeof(support))) ||
            (support.Support2&D3D12_FORMAT_SUPPORT2_UAV_TYPED_STORE)==0) return state;
        constexpr auto readable=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE |
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
        for (auto& image : state->temporal) {
            if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
                readable,nullptr,IID_PPV_ARGS(&image)))) {
                state->temporal={};
                break;
            }
        }"""),
        ("advance history only for newly rendered frames",
         """        if (!b40_history_) return;
        next_fine_depth_.time=std::chrono::steady_clock::now();""",
         """        if (!b40_history_) return;
        if (next_fine_depth_.extent[0] && next_fine_depth_.key==b40_history_->fine_depth.key) {
            next_fine_depth_={};
            return;
        }
        next_fine_depth_.time=std::chrono::steady_clock::now();"""),
        ("history binding flags and GPU lifetime",
         "    bool last_fine_depth_history_used() const { return bool(m1_.previous_fovea_lease); }",
         "    bool last_fine_depth_history_used() const { return history_read_; }"),
        ("retain queue shared resources through the retired slot and clear only local state",
         "        m1_.previous_fovea_lease.reset();",
         """        history_lease_.reset();
        history_read_=false;"""),
        ("validate history, choose output image, and freeze source extent",
         old[start:end],
         """        const auto now=std::chrono::steady_clock::now();
        const auto* last=b40_history_ ? &b40_history_->fine_depth : nullptr;
        const bool write_history=settings.synthetic_stereo && settings.m4_fovea_grid &&
            settings.m21_depth_debug==0 && (settings.edge_history>0.f || settings.fill_history>0.f) &&
            b40_history_ && b40_history_->temporal[0] && b40_history_->temporal[1] &&
            b40_history_->device.Get()==device;
        const auto* previous=write_history && last->extent[0] && stereo_geometry &&
            last->key.generation==frame.config.key.generation && frame.config.key.frame>=last->key.frame &&
            now>=last->time && now-last->time < std::chrono::milliseconds(180) &&
            last->camera.world_to_meters>0.f &&
            last->camera.world_to_meters==stereo_geometry->fine_depth_camera.world_to_meters &&
            last->depth_coefficients==stereo_geometry->depth_coefficients &&
            last->fovea_view==settings.fovea_view && last->jitter_mode==settings.m3_jitter_mode &&
            std::abs(last->camera.projection[0])>1.e-6f && std::abs(last->camera.projection[2])>1.e-6f &&
            std::abs(stereo_geometry->fine_depth_camera.projection[0])>1.e-6f &&
            std::abs(stereo_geometry->fine_depth_camera.projection[2])>1.e-6f
            ? last : nullptr;
        const unsigned write_index=last ? 1u-last->index : 0u;
        const auto& color_desc=settings.fovea_view==0 ? p : s;
        const std::array<uint32_t,4> color_extent{layout.fovea.width,layout.fovea.height,
            static_cast<uint32_t>(color_desc.Width),color_desc.Height};
"""),
        ("pass the frozen settings and texture extent into constants",
         "settings.m5_left_max,settings.m5_right_max,previous,m6_previous_srv_);",
         """settings.m5_left_max,settings.m5_right_max,previous,write_history,
                settings.edge_history,settings.fill_history,settings.fill_blur_px,
                settings.edge_reach_px,color_extent);"""),
        ("bind current and previous history for the retired compositor slot",
         "        ensure_srvs(device,fovea,periphery,sampling_format);",
         """        ensure_srvs(device,fovea,periphery,sampling_format);
        auto* history_output=write_history && m1_active && m1_.m4_active
            ? b40_history_->temporal[write_index].Get() : nullptr;
        history_read_=history_output && previous;
        if (history_output) history_lease_=b40_history_;
        D3D12_SHADER_RESOURCE_VIEW_DESC history_srv{};
        history_srv.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
        history_srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
        history_srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        history_srv.Texture2D.MipLevels=1;
        device->CreateShaderResourceView(history_read_ ? b40_history_->temporal[previous->index].Get() : nullptr,
            &history_srv,m6_previous_srv_);
        device->CreateShaderResourceView(history_output,&history_srv,m7_current_srv_);
        D3D12_UNORDERED_ACCESS_VIEW_DESC history_uav{};
        history_uav.Format=history_srv.Format;
        history_uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
        device->CreateUnorderedAccessView(history_output,nullptr,&history_uav,m7_current_uav_);"""),
        ("fovea can be sampled from the compute pass",
         """        update_timing(timed,direct_xr);
        const auto sample_state=b40_active ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE :
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;""",
         """        update_timing(timed,direct_xr);
        const auto sample_state=b40_active ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE :
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
        const auto fovea_sample_state=history_output && settings.fill_history>0.f
            ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE : sample_state;"""),
        ("only fovea needs compute visibility for temporal colour",
         """        transition(cmd,fovea,fovea_state,sample_state);""",
         """        transition(cmd,fovea,fovea_state,fovea_sample_state);"""),
        ("restore the actual fovea resource state",
         """        transition(cmd,fovea,sample_state,fovea_state);""",
         """        transition(cmd,fovea,fovea_sample_state,fovea_state);"""),
        ("GPU reads the latest completed write on the same queue",
         """                cmd->SetPipelineState(m1_.m4_condition.Get());
                cmd->Dispatch(m1_.m4_rows,1,1);""",
         """                constexpr auto history_read=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE |
                    D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
                if (history_output) transition(cmd,history_output,history_read,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                cmd->SetComputeRootDescriptorTable(0,srv_gpu_start_);
                cmd->SetPipelineState(m1_.m4_condition.Get());
                cmd->Dispatch(m1_.m4_rows,1,1);
                if (history_output) transition(cmd,history_output,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,history_read);"""),
        ("publish the actual written extent, image index and channel validity",
         """        if (b40_history_ && m1_active && m1_.m4_active) {
            next_fine_depth_={frame.config.key,stereo_geometry->fine_depth_camera,
                {layout.u0,layout.v0,layout.u1,layout.v1},stereo_geometry->depth_coefficients,
                *stereo_fovea_depth,settings.m3_jitter_mode==2u ? -1.f : 1.f,now};
        }""",
         """        if (history_output) {
            next_fine_depth_={frame.config.key,stereo_geometry->fine_depth_camera,
                {layout.u0,layout.v0,layout.u1,layout.v1},stereo_geometry->depth_coefficients,
                {m1_.m4_columns,m1_.m4_rows},write_index,settings.fill_history>0.f,
                settings.edge_history,settings.fovea_view,settings.m3_jitter_mode,now};
        } else {
            next_fine_depth_.index=last ? last->index : 0u;
        }"""),
        ("current history lives at t10", "m4_field_range.NumDescriptors=2; // t8 current field, t9 previous fine input",
         "m4_field_range.NumDescriptors=3; // t8 current depth, t9 old history, t10 current history"),
        ("history output at u6", "m4_output_range.NumDescriptors=1; // u5 M4 fovea field (heap slot 13)",
         "m4_output_range.NumDescriptors=2; // u5 M4 fovea field, u6 new history"),
        ("heap space for both descriptors", "hd.NumDescriptors = 15;", "hd.NumDescriptors = 17;"),
        ("UAV table follows three SRVs", "            m4_table.ptr+=2u*srv_descriptor_increment_;",
         "            m4_table.ptr+=3u*srv_descriptor_increment_;"),
        ("allocate descriptor handles in the retired slot",
         """        desc_cpu.ptr+=srv_descriptor_increment_; // [13] t9 previous raw fine depth
        m6_previous_srv_=desc_cpu;
        auto history_srv=soft_srv;
        device->CreateShaderResourceView(nullptr,&history_srv,m6_previous_srv_);
        desc_cpu.ptr+=srv_descriptor_increment_; // [14] u5 M4 fovea field
        device->CreateUnorderedAccessView(m1_.m4_depth.Get(),nullptr,&soft_uav,desc_cpu);""",
         """        desc_cpu.ptr+=srv_descriptor_increment_; // [13] t9 previous history
        m6_previous_srv_=desc_cpu;
        desc_cpu.ptr+=srv_descriptor_increment_; // [14] t10 new history
        m7_current_srv_=desc_cpu;
        desc_cpu.ptr+=srv_descriptor_increment_; // [15] u5 M4 fovea field
        device->CreateUnorderedAccessView(m1_.m4_depth.Get(),nullptr,&soft_uav,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_; // [16] u6 new history
        m7_current_uav_=desc_cpu;"""),
        ("keep shared images leased through the command slot fence",
         "    D3D12_CPU_DESCRIPTOR_HANDLE m2_fovea_srv_{}, m6_previous_srv_{};",
         """    D3D12_CPU_DESCRIPTOR_HANDLE m2_fovea_srv_{}, m6_previous_srv_{}, m7_current_srv_{}, m7_current_uav_{};
    std::shared_ptr<B40MonoHistory> history_lease_;
    bool history_read_{};"""),
    ])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: apply_duoview_m7_accumulation.py <backend> <shaders>")
    shaders(Path(sys.argv[2]))
    backend(Path(sys.argv[1]) / "src/mods")
    print("DuoView M4: accumulated fovea edges, accumulated fill, and independent fill blur")

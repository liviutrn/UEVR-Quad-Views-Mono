#!/usr/bin/env python3
"""Integrate M1 in the generated mode 6 compositor and OpenXR submission."""
import argparse
from pathlib import Path
import shutil

from apply_duoview_b40_pipeline import patch


def patch_settings(mods):
    patch(mods / "vr/DuoViewConfig.hpp", [
        ("M1 frame settings", "    bool shared_eye_image{false};",
         """    bool shared_eye_image{false};
    bool synthetic_stereo{};
    float stereo_strength{.8f};
    float stereo_near_m{1.f};
    float stereo_softness{.5f};"""),
        ("M1 reconcile", "    out.shared_eye_image=requested.shared_eye_image;",
         """    out.synthetic_stereo=requested.synthetic_stereo;
    out.shared_eye_image=!out.synthetic_stereo && requested.shared_eye_image;
    if (std::isfinite(requested.stereo_strength))
        out.stereo_strength=(std::clamp)(requested.stereo_strength,0.f,1.f);
    if (std::isfinite(requested.stereo_near_m))
        out.stereo_near_m=(std::clamp)(requested.stereo_near_m,0.f,2.f);
    if (std::isfinite(requested.stereo_softness))
        out.stereo_softness=(std::clamp)(requested.stereo_softness,.25f,.9f);"""),
    ])
    patch(mods / "VR.hpp", [
        ("M1 controls", "    const ModToggle::Ptr m_duo_shared_eye{",
         """    const ModToggle::Ptr m_duo_stereo{ModToggle::create(generate_name("DuoViewSyntheticStereo"), false)};
    const ModSlider::Ptr m_duo_stereo_strength{ModSlider::create(generate_name("DuoViewStereoStrength"), 0.f, 1.f, .8f)};
    const ModSlider::Ptr m_duo_stereo_near{ModSlider::create(generate_name("DuoViewStereoNearMeters"), 0.f, 2.f, 1.f)};
    const ModSlider::Ptr m_duo_stereo_softness{ModSlider::create(generate_name("DuoViewStereoEdgeSoftness"), .25f, .9f, .5f)};
    const ModToggle::Ptr m_duo_shared_eye{"""),
        ("persist M1 options", "            *m_duo_shared_eye,",
         """            *m_duo_shared_eye, *m_duo_stereo, *m_duo_stereo_strength,
            *m_duo_stereo_near, *m_duo_stereo_softness,"""),
    ])
    patch(mods / "VR.cpp", [
        ("restore Mono presets", "                    m_duo_shared_eye->value()=false; // v208",
         """                    m_duo_shared_eye->value()=false; // v208
                    m_duo_stereo->value()=false; m_duo_stereo_strength->value()=.8f;
                    m_duo_stereo_near->value()=1.f; m_duo_stereo_softness->value()=.5f;"""),
        ("M1 UI", '                m_duo_shared_eye->draw("Same image for both eyes (v208)");',
         """                m_duo_stereo->draw("Synthetic stereo (M1, experimental)");
                if (m_duo_stereo->value()) {
                    m_duo_stereo_strength->draw("Stereo strength");
                    m_duo_stereo_near->draw("Near depth limit (m, 0 = off)");
                    m_duo_stereo_softness->draw("Depth edge softness");
                    ImGui::TextWrapped("M1 uses DLSS periphery depth. Try 0.6 fovea and 0.5 periphery.");
                } else {
                    m_duo_shared_eye->draw("Same image for both eyes (v208)");
                }"""),
        ("freeze M1 values", "        .shared_eye_image=m_duo_shared_eye->value()};",
         """        .shared_eye_image=m_duo_shared_eye->value(),
        .synthetic_stereo=m_duo_stereo->value(),
        .stereo_strength=m_duo_stereo_strength->value(),
        .stereo_near_m=m_duo_stereo_near->value(),
        .stereo_softness=m_duo_stereo_softness->value()};"""),
        ("detect M1 changes", "        current.shared_eye_image==candidate.shared_eye_image) return;",
         """        current.shared_eye_image==candidate.shared_eye_image &&
        current.synthetic_stereo==candidate.synthetic_stereo &&
        current.stereo_strength==candidate.stereo_strength &&
        current.stereo_near_m==candidate.stereo_near_m &&
        current.stereo_softness==candidate.stereo_softness) return;"""),
    ])


def patch_compositor(vr):
    patch(vr / "DuoViewD3D12.hpp", [
        ("M1 resource helper", "#include <string>", '#include <string>\n#include "DuoViewM1D3D12.hpp"'),
        ("M1 root budget", "sizeof(ShaderConstants)/4 + 4 <= 64", "sizeof(ShaderConstants)/4 + 8 <= 64"),
        ("M1 draw arguments",
         "                std::shared_ptr<const void> packet_lifetime, UINT64 frequency = 0) {\n        recorded_commands_=false;",
         """                std::shared_ptr<const void> packet_lifetime, UINT64 frequency = 0,
                const stereo::Geometry* stereo_geometry = nullptr, const M1DepthInput* stereo_depth = nullptr) {
        recorded_commands_=false;
        last_stereo_output_=false;
        m1_.depth_lease.reset();"""),
        ("direct XR route",
         """        const bool direct_xr=frame.config.settings.direct_xr_output &&
            frame.config.settings.sharpen_strength <= 0.0f &&
            !frame.config.settings.focus_lift_enabled &&
            !frame.config.settings.seam_match_enabled &&
            xrd.Dimension""",
         "        const bool xr_raster_compatible=xrd.Dimension"),
        ("stereo admission",
         "        const auto& pr=frame.config.settings.fovea_view==0 ? layout.fovea : layout.periphery;",
         """        const auto& settings=frame.config.settings;
        const bool m1_active=settings.synthetic_stereo && stereo_geometry && xr_raster_compatible &&
            m1_.ready() && m1_.write_constants(device,*stereo_geometry,stereo_depth,
                settings.stereo_near_m,settings.stereo_softness,m1_raw_srv_);
        const bool direct_xr=m1_active || (xr_raster_compatible && settings.direct_xr_output &&
            settings.sharpen_strength<=0.f && !settings.focus_lift_enabled && !settings.seam_match_enabled);
        const auto& pr=frame.config.settings.fovea_view==0 ? layout.fovea : layout.periphery;"""),
        ("B40 UAV descriptor offset", "uav.ptr+=UINT64(3)*srv_descriptor_increment_;",
         "uav.ptr+=UINT64(4)*srv_descriptor_increment_;"),
        ("M1 compute and raster selection",
         """        if (b40_active) dispatch_b40(cmd,constants,true);
        cmd->SetGraphicsRootSignature(root_.Get());
        cmd->SetPipelineState(native_pipeline_.Get());""",
         """        if (b40_active) dispatch_b40(cmd,constants,true);
        if (m1_active && m1_.rows) {
            transition(cmd,m1_.soft_depth.Get(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,
                       D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            cmd->SetComputeRootSignature(root_.Get());
            cmd->SetPipelineState(m1_.condition.Get());
            cmd->SetComputeRootConstantBufferView(4,m1_.constants->GetGPUVirtualAddress());
            auto raw=srv_gpu_start_;
            raw.ptr+=UINT64(5)*srv_descriptor_increment_;
            cmd->SetComputeRootDescriptorTable(5,raw);
            raw.ptr+=srv_descriptor_increment_;
            cmd->SetComputeRootDescriptorTable(6,raw);
            cmd->Dispatch(m1_.rows,1,1);
            transition(cmd,m1_.soft_depth.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                       D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        }
        cmd->SetGraphicsRootSignature(root_.Get());
        cmd->SetPipelineState(m1_active ? m1_.raster.Get() : native_pipeline_.Get());
        if (m1_active) cmd->SetGraphicsRootConstantBufferView(4,m1_.constants->GetGPUVirtualAddress());"""),
        ("always raster both M1 eyes", "const UINT direct_width=frame.config.settings.shared_eye_image ? width_ : width_*2;",
         "const UINT direct_width=!m1_active && frame.config.settings.shared_eye_image ? width_ : width_*2;"),
        ("report actual stereo result", "        last_native_direct_xr_=direct_xr;",
         "        last_native_direct_xr_=direct_xr;\n        last_stereo_output_=m1_active;"),
        ("M1 result query", "    bool last_native_direct_xr() const",
         """    bool last_stereo_output() const { return last_stereo_output_; }
    bool last_stereo_depth() const { return last_stereo_output_ && m1_.rows!=0; }
    bool last_native_direct_xr() const"""),
        ("release M1 resources on slot rebuild", "        b40_warning_.clear();",
         "        b40_warning_.clear();\n        legacy_packed_pipeline_.Reset();\n        m1_={};"),
        ("M1 SRV count", "        range.NumDescriptors = 3;", "        range.NumDescriptors = 4;"),
        ("M1 root ranges", "        D3D12_ROOT_PARAMETER params[4]{};",
         """        D3D12_DESCRIPTOR_RANGE m1_raw_range{};
        m1_raw_range.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        m1_raw_range.NumDescriptors=1;
        m1_raw_range.BaseShaderRegister=4;
        D3D12_DESCRIPTOR_RANGE m1_output_range{};
        m1_output_range.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
        m1_output_range.NumDescriptors=1;
        m1_output_range.BaseShaderRegister=2;
        D3D12_ROOT_PARAMETER params[7]{};"""),
        ("M1 root parameters", "        D3D12_STATIC_SAMPLER_DESC sampler{};",
         """        params[4].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV;
        params[4].Descriptor={1,0};
        params[4].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
        params[5].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        params[5].DescriptorTable={1,&m1_raw_range};
        params[5].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
        params[6].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        params[6].DescriptorTable={1,&m1_output_range};
        params[6].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
        D3D12_STATIC_SAMPLER_DESC sampler{};"""),
        ("M1 root parameter count", "D3D12_ROOT_SIGNATURE_DESC desc{4, params",
         "D3D12_ROOT_SIGNATURE_DESC desc{7, params"),
        ("M1 shader and scratch prewarm",
         '        D3D12_COMPUTE_PIPELINE_STATE_DESC compute{};',
         """        if (!m1_.prepare(device,root_.Get(),graphics,width,height)) m1_={};
        D3D12_COMPUTE_PIPELINE_STATE_DESC compute{};"""),
        ("M1 slot heap size", "hd.NumDescriptors = 4;", "hd.NumDescriptors = 7;"),
        ("bind M1 soft-depth SRV", "        D3D12_UNORDERED_ACCESS_VIEW_DESC stat_uav{};",
         """        D3D12_SHADER_RESOURCE_VIEW_DESC soft_srv{};
        soft_srv.Format=DXGI_FORMAT_R32_FLOAT;
        soft_srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
        soft_srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        soft_srv.Texture2D.MipLevels=1;
        device->CreateShaderResourceView(m1_.soft_depth.Get(),&soft_srv,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_UNORDERED_ACCESS_VIEW_DESC stat_uav{};"""),
        ("bind M1 compute descriptors",
         "        device->CreateUnorderedAccessView(b40_stats_.Get(),nullptr,&stat_uav,desc_cpu);",
         """        device->CreateUnorderedAccessView(b40_stats_.Get(),nullptr,&stat_uav,desc_cpu);
        desc_cpu.ptr+=srv_descriptor_increment_;
        m1_raw_srv_=desc_cpu;
        device->CreateShaderResourceView(nullptr,&soft_srv,m1_raw_srv_);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_UNORDERED_ACCESS_VIEW_DESC soft_uav{};
        soft_uav.Format=DXGI_FORMAT_R32_FLOAT;
        soft_uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
        device->CreateUnorderedAccessView(m1_.soft_depth.Get(),nullptr,&soft_uav,desc_cpu);"""),
        ("pinned packed raster for plain Mono",
         "        cmd->SetPipelineState(pipeline_.Get());",
         """        const bool packed_effects=b40_active || frame.settings.focus_lift_enabled ||
            frame.settings.sharpen_strength>0.f;
        cmd->SetPipelineState(packed_effects ? pipeline_.Get() : legacy_packed_pipeline_.Get());"""),
        ("build pinned packed raster PSO",
         '        graphics.PS = {native_pixel_shader_bytecode, sizeof(native_pixel_shader_bytecode)};',
         """        graphics.PS = {legacy_packed_pixel_bytecode, sizeof(legacy_packed_pixel_bytecode)};
        if (!check(device->CreateGraphicsPipelineState(&graphics, IID_PPV_ARGS(&legacy_packed_pipeline_)),
            "Create pinned packed raster PSO")) return false;
        graphics.PS = {native_pixel_shader_bytecode, sizeof(native_pixel_shader_bytecode)};"""),
        ("M1 slot state", "    std::string b40_warning_;",
         """    std::string b40_warning_;
    ComPtr<ID3D12PipelineState> legacy_packed_pipeline_;
    M1Resources m1_{};
    D3D12_CPU_DESCRIPTOR_HANDLE m1_raw_srv_{};
    bool last_stereo_output_{};"""),
    ])


def patch_delivery(vr):
    patch(vr / "D3D12Component.cpp", [
        ("track recorded M1 scene", "                            bool callback_attempted = false;",
         "                            bool stereo_output = false;\n                            bool callback_attempted = false;"),
        ("capture recorded route", "&output_direct, &source_extents, &recorded_secondary, &recorded_target](",
         "&output_direct, &source_extents, &recorded_secondary, &recorded_target, &stereo_output]("),
        ("M1 exact packet camera and depth", "                                    recorded = compositor.record_native(device, commands.cmd_list.Get(),",
         """                                    std::optional<uevr::duoview::stereo::Geometry> stereo_geometry;
                                    std::optional<uevr::duoview::dx12::M1DepthInput> stereo_depth;
                                    if (packet_frame->config.settings.synthetic_stereo && current_queue) {
                                        std::array<uevr::duoview::stereo::Eye,2> eyes{};
                                        for (size_t i=0;i<eyes.size();++i) {
                                            const auto& view=packet->duoview_views[i];
                                            const auto& q=view.pose.orientation;
                                            const auto& t=view.pose.position;
                                            const auto& f=view.fov;
                                            eyes[i]={{q.x,q.y,q.z,q.w},{t.x,t.y,t.z},
                                                {std::tan(f.angleLeft),std::tan(f.angleRight),std::tan(f.angleUp),std::tan(f.angleDown)}};
                                        }
                                        const auto scale=double(vr->get_world_to_meters())*vr->get_world_scale();
                                        stereo_geometry=uevr::duoview::stereo::make_geometry(packet_frame->projection,eyes,
                                            scale,packet_frame->config.settings.stereo_strength);
                                        if (stereo_geometry) {
                                            const auto& config=packet_frame->config;
                                            const auto& periphery=config.layout.periphery;
                                            const auto snapshot=uevr::quadview::ngx::PeripheryDepth::self().latest_duoview_submitted(
                                                config.key.generation,periphery.width,periphery.height,current_queue);
                                            if (snapshot) stereo_depth=uevr::duoview::dx12::M1DepthInput{
                                                snapshot->texture.Get(),snapshot->srv_format,
                                                {snapshot->rect[0],snapshot->rect[1],snapshot->rect[2],snapshot->rect[3]},
                                                snapshot->jitter_valid ? snapshot->jitter_uv : std::array<float,2>{},snapshot};
                                            // Use the same queue that the depth selection verified.
                                            commands.seam_submission_queue=current_queue;
                                        }
                                    }
                                    recorded = compositor.record_native(device, commands.cmd_list.Get(),"""),
        ("pass M1 draw inputs and report depth state",
         """                                        packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0);
                                    if (recorded) {""",
         """                                        packet_frame->config.settings.gpu_timing ? compositor.timing_frequency() : 0,
                                        stereo_geometry ? &*stereo_geometry : nullptr,stereo_depth ? &*stereo_depth : nullptr);
                                    if (recorded) {
                                        stereo_output=compositor.last_stereo_output();
                                        if (packet_frame->config.settings.synthetic_stereo) {
                                            SPDLOG_INFO_EVERY_N_SEC(2,"[DuoView][M1] stereo={} DLSS depth={} strength={:.2f}",
                                                stereo_output,compositor.last_stereo_depth(),packet_frame->config.settings.stereo_strength);
                                        }"""),
        ("copy M1 submit metadata", "                                pose.duoview_shared_image=packet_frame->config.settings.shared_eye_image;",
         """                                pose.duoview_stereo_output=stereo_output;
                                pose.duoview_shared_image=!stereo_output && packet_frame->config.settings.shared_eye_image;"""),
    ])
    patch(vr / "runtimes/OpenXR.hpp", [
        ("M1 metadata follows frame", "        bool duoview_shared_image{};",
         "        bool duoview_stereo_output{};\n        bool duoview_shared_image{};"),
    ])
    patch(vr / "runtimes/OpenXR.cpp", [
        ("apply legacy centered geometry only to Mono pixels",
         "    const auto mono_projection = mono ? mono_geometry(pipelined_stage_views) : std::nullopt;",
         """    const bool duo_stereo=mono && vr->is_duoview_renderer_active() &&
        submit_state.duoview_stereo_output && pipelined_stage_views.size()==2;
    if (duo_stereo) stalker_pair.reset();
    const auto mono_projection = mono && !duo_stereo ? mono_geometry(pipelined_stage_views) : std::nullopt;"""),
        ("accept recorded stereo scene", "        (!mono || (mono_projection && mono_crops[0] && mono_crops[1])) &&",
         "        (!mono || duo_stereo || (mono_projection && mono_crops[0] && mono_crops[1])) &&"),
        ("full stereo eye subrect", "            if (mono_projection) {\n                const auto& crop",
         """            if (duo_stereo) {
                offset_x=static_cast<int32_t>(i)*(swapchain->width/2);
                offset_y=0;
                extent_x=swapchain->width/2;
                extent_y=swapchain->height;
            }
            if (mono_projection) {
                const auto& crop"""),
    ])


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("backend",type=Path)
    ap.add_argument("shaders",type=Path)
    args=ap.parse_args()
    mods=args.backend/"src/mods"
    here=Path(__file__).resolve().parent
    for header in ("DuoViewStereoGeometry.hpp","DuoViewM1D3D12.hpp"):
        shutil.copyfile(here/header,mods/"vr"/header)
    shutil.copyfile(here/"DuoViewM1Stereo.hlsl",args.shaders/"DuoViewM1Stereo.hlsl")
    patch(args.shaders/"DuoViewNativeCompositeRaster.hlsl", [
        ("share proven Native raster with packed source path",
         "float2 NativeSampleUV(float2 local, uint2 active, uint2 resourceSize) {\n",
         """float2 NativeSampleUV(float2 local, uint2 active, uint2 resourceSize) {
#ifdef DUOVIEW_ATLAS_GATHER
    return AtlasSampleUV(FoveaRect,local);
#else
"""),
        ("close the packed fovea sampler",
         "    return texels / float2(resourceSize);\n}",
         """    return texels / float2(resourceSize);
#endif
}

float2 NativePeripheryUV(float2 uv) {
#ifdef DUOVIEW_ATLAS_GATHER
    return AtlasSampleUV(PeripheralRect,uv);
#else
    const float2 texels=clamp(saturate(uv)*float2(PeripheralRect.zw),
        float2(.5,.5),float2(PeripheralRect.zw)-.5);
    return texels/float2(NativePeripheryDimensions);
#endif
}"""),
        ("route seam periphery sampling through exact packed rect",
         "PeripheralNativeSource.SampleLevel(LinearClamp, NativeSampleUV(uv, PeripheralRect.zw, NativePeripheryDimensions), 0.0)",
         "PeripheralNativeSource.SampleLevel(LinearClamp, NativePeripheryUV(uv), 0.0)"),
        ("route display periphery through the same rect",
         """    const float2 peripherySample = NativeSampleUV(
        fullUv, PeripheralRect.zw, NativePeripheryDimensions);""",
         "    const float2 peripherySample=NativePeripheryUV(fullUv);"),
        ("packed periphery remains bilinear",
         "    float4 periphery = (SharpenFlags & 8u)",
         """#ifdef DUOVIEW_ATLAS_GATHER
    float4 periphery=PeripheralNativeSource.SampleLevel(LinearClamp,peripherySample,0.0);
#else
    float4 periphery = (SharpenFlags & 8u)"""),
        ("close packed periphery branch",
         "    const float4 rawPeriphery = periphery;",
         "#endif\n    const float4 rawPeriphery = periphery;"),
        ("M1 warp before original composite", "float4 PSNativeMain(VertexOut i) : SV_TARGET0 {",
         """#ifdef DUOVIEW_M1_RASTER
#include "DuoViewM1Stereo.hlsl"
#endif

float4 PSNativeMain(VertexOut i) : SV_TARGET0 {"""),
        ("per-eye center-camera lookup",
         "    const float2 fullUv = outputPixel / float2(OutputSize);",
         """    const float2 outputUv = outputPixel / float2(OutputSize);
#ifdef DUOVIEW_M1_RASTER
    const float2 fullUv = M1PullUv(outputUv, i.pos.x >= OutputSize.x ? 1u : 0u);
#else
    const float2 fullUv = outputUv;
#endif"""),
    ])
    patch_settings(mods)
    patch_compositor(mods/"vr")
    patch_delivery(mods/"vr")
    print("DuoView M1 per-eye raster, settings and recorded-frame OpenXR presentation installed")


if __name__=="__main__":
    main()

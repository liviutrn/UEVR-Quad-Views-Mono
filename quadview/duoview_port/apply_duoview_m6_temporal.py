#!/usr/bin/env python3
"""Reproject previous fine NGX depth at silhouettes and soften only hole fill."""
import sys
from pathlib import Path

from apply_duoview_b40_pipeline import patch


def shaders(sh):
    helpers = Path(__file__).with_name("DuoViewFineDepthTemporal.hlsl").read_text()
    patch(sh / "DuoViewM1Stereo.hlsl", [
        ("history constants",
         "    float4 M5Sharpen;",
         """    float4 M6View[3];
    float4 M6CurrentProjection, M6PreviousProjection, M6PreviousCrop;
    uint4 M6PreviousRect;
    float4 M6PreviousJitter;
    float4 M5Sharpen;"""),
        ("history sampling",
         "[numthreads(128,1,1)]\nvoid CSConditionM4(",
         helpers + "\n[numthreads(128,1,1)]\nvoid CSConditionM4("),
        ("find edge while loading the current fine samples",
         """        float fine=0.0;
        [unroll] for (int fy=0; fy<=1; ++fy)
            [unroll] for (int fx=0; fx<=1; ++fx)
                fine=max(fine,DecodeM2Depth(f0+int2(fx,fy)));""",
         """        float fine=0.0, farDepth=1.e9;
        [unroll] for (int fy=0; fy<=1; ++fy) {
            [unroll] for (int fx=0; fx<=1; ++fx) {
                const float d=DecodeM2Depth(f0+int2(fx,fy));
                fine=max(fine,d);
                farDepth=min(farDepth,d);
            }
        }
        fine=M6StabilizeFineEdge(local,fine,farDepth);"""),
        ("return the fill anchor and away-from-foreground direction",
         """float M3FillHole(float baseX, float root, float y, float k, uint eye) {""",
         """float M3FillHole(float baseX, float root, float y, float k, uint eye,
                  out float2 fill) {
    fill=0.;"""),
        ("minimum disocclusion stretches even with M3 disabled",
         "    if(!(stretch>M3Flags.z)) return root;",
         "    if(!(stretch>(M3Flags.z>0. ? M3Flags.z : 2.0))) return root;"),
        ("use a background-side tap only if depth agrees",
         """    if(abs(dm-d)>max(.05*d,1.e-4)) um=ub;
    return clamp(um,0.0,1.0);""",
         """    if(abs(dm-d)>max(.05*d,1.e-4)) um=ub;
    if (M4Flags.x>.5) {
        const float tap=um+dir*M6PreviousJitter.w;
        const float tapDepth=M1ReadConditionedEye(float2(tap,y),eye);
        if(tap>=0. && tap<=1. && abs(tapDepth-d)<=max(.05*d,1.e-4))
            fill=float2(tap,saturate((stretch-2.0)*.5)*.25);
    }
    return clamp(um,0.0,1.0);"""),
        ("pass fill metadata to raster",
         "float2 M1PullUv(float2 eyeUv, uint eye) {",
         "float2 M1PullUv(float2 eyeUv, uint eye, out float2 fill) {\n    fill=0.;"),
        ("apply targeted fill in M4 independently of softness",
         "[branch] if(M3Flags.x>.5 && M3Flags.z>0.0) uv.x=M3FillHole(base.x,uv.x,base.y,k,eye);",
         """[branch] if(M4Flags.x>.5 || (M3Flags.x>.5 && M3Flags.z>0.0))
            uv.x=M3FillHole(base.x,uv.x,base.y,k,eye,fill);"""),
    ])
    patch(sh / "DuoViewNativeCompositeRaster.hlsl", [
        ("point-fill anchor",
         "    const float2 fullUv = M2Sharpen.z > .5 ? outputUv : M1PullUv(outputUv, i.pos.x >= OutputSize.x ? 1u : 0u);",
         """    float2 fill=0.;
    float2 fullUv=outputUv;
    [branch] if (M2Sharpen.z <= .5)
        fullUv=M1PullUv(outputUv,i.pos.x >= OutputSize.x ? 1u : 0u,fill);"""),
        ("soften only the background in the detected hole",
         "    if (DebugBorder && weight > 0.01 && weight < 0.1)",
         """#ifdef DUOVIEW_M1_RASTER
    [branch] if (DebugViewMode==0 && fill.y>0.) {
        const float2 fillUv=float2(fill.x,fullUv.y);
        const float fillWeight=BlendWeight(fillUv);
        float3 fillColor=PeripheralNativeSource.SampleLevel(LinearClamp,NativePeripheryUV(fillUv),0.).rgb;
        if (fillWeight<1. && SeamOptions.x>.5)
            fillColor=DuoPhase2MatchContext(fillUv,fillColor);
        if (fillWeight>0.) {
            const float2 local=(fillUv-CropUv.xy)/(CropUv.zw-CropUv.xy);
            const float2 sampleUv=NativeSampleUV(local,FoveaRect.zw,NativeFoveaDimensions);
            const float3 color=SourceAtlas.SampleLevel(LinearClamp,sampleUv,0.).rgb;
            fillColor=lerp(fillColor,DuoPhase2FocusLift(color,local),fillWeight);
        }
        result.rgb=lerp(result.rgb,fillColor,fill.y);
    }
#endif
    if (DebugBorder && weight > 0.01 && weight < 0.1)"""),
    ])


def backend(mods):
    vr = mods / "vr"
    (vr / "DuoViewFineDepthHistory.hpp").write_bytes(Path(__file__).with_name("DuoViewFineDepthHistory.hpp").read_bytes())
    patch(vr / "DuoViewStereoGeometry.hpp", [
        ("history camera type", '#include "QuadViewGeometry.hpp"',
         '#include "QuadViewGeometry.hpp"\n#include "DuoViewFineDepthHistory.hpp"'),
        ("freeze center camera", "    float world_to_meters{};",
         "    FineDepthCamera fine_depth_camera{};\n    float world_to_meters{};"),
        ("record mono projection and center pose", "    return result;",
         """    result.fine_depth_camera={layout.depth_projection,orientations[0],
        { (eyes[0].position[0]+eyes[1].position[0])*.5f,
          (eyes[0].position[1]+eyes[1].position[1])*.5f,
          (eyes[0].position[2]+eyes[1].position[2])*.5f },result.world_to_meters};
    return result;"""),
    ])
    patch(vr / "DuoViewM1D3D12.hpp", [
        ("chrono and frame key dependencies",
         '#include "DuoViewStereoGeometry.hpp"',
         '#include "DuoViewStereoGeometry.hpp"\n#include "DuoViewFrame.hpp"\n#include <chrono>'),
        ("previous fine input",
         "struct M1Constants {",
         """struct FineDepthHistoryFrame {
    FrameKey key{};
    stereo::FineDepthCamera camera{};
    std::array<float,4> crop{};
    std::array<float,3> depth_coefficients{};
    M1DepthInput depth;
    float jitter_sign{};
    std::chrono::steady_clock::time_point time{};
};

struct M1Constants {"""),
        ("history buffer layout", "    float m5_sharpen[4]{};",
         """    float m6_view[3][4]{};
    float m6_current_projection[4]{}, m6_previous_projection[4]{}, m6_previous_crop[4]{};
    uint32_t m6_previous_rect[4]{};
    float m6_previous_jitter[4]{};
    float m5_sharpen[4]{};"""),
        ("history buffer size", "sizeof(M1Constants) == 368", "sizeof(M1Constants) == 496"),
        ("history lease", "    std::shared_ptr<const void> depth_lease, fovea_depth_lease;",
         "    std::shared_ptr<const void> depth_lease, fovea_depth_lease, previous_fovea_lease;"),
        ("history inputs",
         "float left_max_change=.10f, float right_max_change=.10f) {",
         """float left_max_change=.10f, float right_max_change=.10f,
                         const FineDepthHistoryFrame* previous=nullptr,
                         D3D12_CPU_DESCRIPTOR_HANDLE previous_srv={}) {"""),
        ("write last accepted fine descriptor and camera transform",
         "        void* address{};\n        const D3D12_RANGE no_read{0,0};",
         """        previous_fovea_lease.reset();
        data.m23_wide[2]=float(output_width_px);
        data.m6_previous_jitter[3]=output_width_px ? 1.25f/float(output_width_px) : 0.f;
        if (previous_srv.ptr) {
            auto history_view=fine_view;
            history_view.Format=DXGI_FORMAT_R32_FLOAT;
            ID3D12Resource* history_texture{};
            if (m4_active && previous) {
                const auto motion=stereo::fine_depth_reprojection(geometry.fine_depth_camera,previous->camera);
                std::memcpy(data.m6_view,motion.rows.data(),sizeof(data.m6_view));
                std::copy(geometry.fine_depth_camera.projection.begin(),geometry.fine_depth_camera.projection.end(),
                          data.m6_current_projection);
                std::copy(motion.previous_projection.begin(),motion.previous_projection.end(),data.m6_previous_projection);
                std::copy(previous->crop.begin(),previous->crop.end(),data.m6_previous_crop);
                std::copy(previous->depth.rect.begin(),previous->depth.rect.end(),data.m6_previous_rect);
                data.m6_previous_jitter[0]=previous->depth.jitter[0]*previous->jitter_sign;
                data.m6_previous_jitter[1]=previous->depth.jitter[1]*previous->jitter_sign;
                data.m6_previous_jitter[2]=1.f;
                history_texture=previous->depth.texture;
                history_view.Format=previous->depth.format;
                previous_fovea_lease=previous->depth.lease;
            }
            device->CreateShaderResourceView(history_texture,&history_view,previous_srv);
        }
        void* address{};
        const D3D12_RANGE no_read{0,0};"""),
    ])
    patch(vr / "DuoViewD3D12.hpp", [
        ("exchange staged metadata", "#include <string>", "#include <string>\n#include <utility>"),
        ("queue-shared fine history", "    ComPtr<ID3D12Resource> buffer;",
         "    ComPtr<ID3D12Resource> buffer;\n    FineDepthHistoryFrame fine_depth;"),
        ("remember fine history only after actual command enqueue",
         "    void set_b40_history(",
         """    bool last_fine_depth_history_used() const { return bool(m1_.previous_fovea_lease); }

    void note_fine_depth_enqueued() {
        if (!b40_history_) return;
        next_fine_depth_.time=std::chrono::steady_clock::now();
        b40_history_->fine_depth=std::exchange(next_fine_depth_,{});
    }

    void set_b40_history("""),
        ("discard leftover metadata before recording",
         "        last_stereo_output_=false;",
         """        last_stereo_output_=false;
        m1_.previous_fovea_lease.reset();
        next_fine_depth_={};"""),
        ("validate previous camera and depth history before sampling",
         "        const bool m1_active=settings.synthetic_stereo",
         """        const auto now=std::chrono::steady_clock::now();
        const auto* last=b40_history_ ? &b40_history_->fine_depth : nullptr;
        const auto previous=last && last->depth.texture && stereo_geometry &&
            last->key.generation==frame.config.key.generation && frame.config.key.frame>last->key.frame &&
            now>=last->time && now-last->time < std::chrono::milliseconds(90) &&
            last->camera.world_to_meters>0.f &&
            last->camera.world_to_meters==stereo_geometry->fine_depth_camera.world_to_meters &&
            std::abs(stereo_geometry->fine_depth_camera.projection[0])>1.e-6f &&
            std::abs(stereo_geometry->fine_depth_camera.projection[2])>1.e-6f &&
            last->depth_coefficients==stereo_geometry->depth_coefficients &&
            std::abs(last->camera.projection[0])>1.e-6f && std::abs(last->camera.projection[2])>1.e-6f
            ? last : nullptr;
        const bool m1_active=settings.synthetic_stereo"""),
        ("bind history inputs", "                settings.m5_left_max,settings.m5_right_max);",
         "                settings.m5_left_max,settings.m5_right_max,previous,m6_previous_srv_);"),
        ("stage future history after successful recording",
         """        if (!copied) return reject("Direct Native blend succeeded but Mono XR output validation failed");
        return true;""",
         """        if (!copied) return reject("Direct Native blend succeeded but Mono XR output validation failed");
        if (b40_history_ && m1_active && m1_.m4_active) {
            next_fine_depth_={frame.config.key,stereo_geometry->fine_depth_camera,
                {layout.u0,layout.v0,layout.u1,layout.v1},stereo_geometry->depth_coefficients,
                *stereo_fovea_depth,settings.m3_jitter_mode==2u ? -1.f : 1.f,now};
        }
        return true;"""),
        ("t9 shares the t8 table", "m4_field_range.NumDescriptors=1; // t8 M4 fovea field (heap slot 12)",
         "m4_field_range.NumDescriptors=2; // t8 current field, t9 previous fine input"),
        ("heap allocation", "hd.NumDescriptors = 14;", "hd.NumDescriptors = 15;"),
        ("t9 descriptor precedes UAV",
         "        desc_cpu.ptr+=srv_descriptor_increment_; // [13] u5 M4 fovea field",
         """        desc_cpu.ptr+=srv_descriptor_increment_; // [13] t9 previous raw fine depth
        m6_previous_srv_=desc_cpu;
        auto history_srv=soft_srv;
        device->CreateShaderResourceView(nullptr,&history_srv,m6_previous_srv_);
        desc_cpu.ptr+=srv_descriptor_increment_; // [14] u5 M4 fovea field"""),
        ("UAV table now follows two SRVs",
         """            cmd->SetComputeRootDescriptorTable(7,m4_table);
            m4_table.ptr+=srv_descriptor_increment_;""",
         """            cmd->SetComputeRootDescriptorTable(7,m4_table);
            m4_table.ptr+=2u*srv_descriptor_increment_;"""),
        ("history descriptor and staged state",
         "    D3D12_CPU_DESCRIPTOR_HANDLE m2_fovea_srv_{};",
         "    D3D12_CPU_DESCRIPTOR_HANDLE m2_fovea_srv_{}, m6_previous_srv_{};\n    FineDepthHistoryFrame next_fine_depth_;"),
    ])
    patch(vr / "D3D12Component.cpp", [
        ("remember the slot that recorded the next history candidate",
         "                            bool stereo_output = false;",
         """                            bool stereo_output = false;
                            uevr::duoview::dx12::Compositor* recorded_compositor{};"""),
        ("record the accepted slot",
         "&recorded_target, &stereo_output](",
         "&recorded_target, &stereo_output, &recorded_compositor]("),
        ("stage only after valid output",
         "                                        stereo_output=compositor.last_stereo_output();",
         """                                        recorded_compositor=&compositor;
                                        stereo_output=compositor.last_stereo_output();"""),
        ("publish history only after successful enqueue",
         "                                native_stereo_hook->duoview_delivery.result(uevr::duoview::DeliveryEvent::copy,",
         """                                recorded_compositor->note_fine_depth_enqueued();
                                native_stereo_hook->duoview_delivery.result(uevr::duoview::DeliveryEvent::copy,"""),
    ])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: apply_duoview_m6_temporal.py <backend> <shaders>")
    shaders(Path(sys.argv[2]))
    backend(Path(sys.argv[1]) / "src/mods")
    print("DuoView: camera-reprojected fine depth at silhouettes and blur confined to hole fill")

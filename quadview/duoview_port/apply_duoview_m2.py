#!/usr/bin/env python3
"""M2 overlay on the pinned, verified M1 generated backend. Mode 7 untouched.

No mutations to the pinned DuoView git tree are committed. The CI working copy
is patched only after M1 overlays; all anchors must match exactly once.
"""
import sys
from pathlib import Path
from apply_duoview_b40_pipeline import patch


def m2_settings(mods):
    patch(mods/"vr/DuoViewConfig.hpp", [
        ("M2 settings", "    float stereo_softness{.5f};",
         """    float stereo_softness{.5f};
    bool m2_fovea_depth{true};
    bool m2_unlinked_sharpen{false};
    float m2_left_sharpen{1.f}, m2_right_sharpen{1.f};"""),
        ("M2 settings validation", "        out.stereo_softness=(std::clamp)(requested.stereo_softness,.25f,.9f);",
         """        out.stereo_softness=(std::clamp)(requested.stereo_softness,.25f,.9f);
    out.m2_fovea_depth=requested.m2_fovea_depth;
    out.m2_unlinked_sharpen=requested.m2_unlinked_sharpen;
    if (std::isfinite(requested.m2_left_sharpen))
        out.m2_left_sharpen=(std::clamp)(requested.m2_left_sharpen,0.f,5.f);
    if (std::isfinite(requested.m2_right_sharpen))
        out.m2_right_sharpen=(std::clamp)(requested.m2_right_sharpen,0.f,5.f);"""),
    ])
    patch(mods/"VR.hpp",[
        ("M2 persistent controls", "    const ModToggle::Ptr m_duo_shared_eye{",
         """    const ModToggle::Ptr m_duo_m2_fovea_depth{ModToggle::create(generate_name("DuoM2FoveaDepth"),true)};
    const ModToggle::Ptr m_duo_m2_unlinked{ModToggle::create(generate_name("DuoM2IndependentSharpen"),false)};
    const ModSlider::Ptr m_duo_m2_left{ModSlider::create(generate_name("DuoM2LeftSharpen"),0.f,5.f,1.f)};
    const ModSlider::Ptr m_duo_m2_right{ModSlider::create(generate_name("DuoM2RightSharpen"),0.f,5.f,1.f)};
    const ModToggle::Ptr m_duo_shared_eye{"""),
        ("M2 persist controls", "            *m_duo_stereo_near, *m_duo_stereo_softness,",
         """            *m_duo_stereo_near, *m_duo_stereo_softness,
            *m_duo_m2_fovea_depth, *m_duo_m2_unlinked,
            *m_duo_m2_left, *m_duo_m2_right,"""),
    ])
    patch(mods/"VR.cpp",[
        ("M2 reset", "m_duo_stereo_near->value()=1.f; m_duo_stereo_softness->value()=.5f;",
         """m_duo_stereo_near->value()=1.f; m_duo_stereo_softness->value()=.5f;
                    m_duo_m2_fovea_depth->value()=true;
                    m_duo_m2_unlinked->value()=false;
                    m_duo_m2_left->value()=1.f; m_duo_m2_right->value()=1.f;"""),
        ("M2 UI", '                    m_duo_stereo_softness->draw("Depth edge softness");',
         """                    m_duo_stereo_softness->draw("Depth edge softness");
                    m_duo_m2_fovea_depth->draw("M2 fine fovea depth (if matched)");
                    m_duo_m2_unlinked->draw("Separate left/right sharpening");
                    if (m_duo_m2_unlinked->value()) {
                        m_duo_m2_left->draw("Left eye sharpen");
                        m_duo_m2_right->draw("Right eye sharpen");
                    }"""),
        ("M2 help", '"M1 uses DLSS periphery depth. Try 0.6 fovea and 0.5 periphery."',
         '"M2: fine DLSS fovea depth overrides periphery inside the eye-tracked crop when captures match; otherwise M1 depth remains."'),
        ("M2 frozen settings", "        .stereo_softness=m_duo_stereo_softness->value()};",
         """        .stereo_softness=m_duo_stereo_softness->value(),
        .m2_fovea_depth=m_duo_m2_fovea_depth->value(),
        .m2_unlinked_sharpen=m_duo_m2_unlinked->value(),
        .m2_left_sharpen=m_duo_m2_left->value(),
        .m2_right_sharpen=m_duo_m2_right->value()};"""),
        ("M2 frame changes", "        current.stereo_softness==candidate.stereo_softness) return;",
         """        current.stereo_softness==candidate.stereo_softness &&
        current.m2_fovea_depth==candidate.m2_fovea_depth &&
        current.m2_unlinked_sharpen==candidate.m2_unlinked_sharpen &&
        current.m2_left_sharpen==candidate.m2_left_sharpen &&
        current.m2_right_sharpen==candidate.m2_right_sharpen) return;"""),
    ])


def m2_capture(mods):
    # Existing PeripheryDepth remains exactly the TriView producer in mode 7.
    # M2 expands only DuoView's request-owned capture selection.
    patch(mods/"vr/QuadViewNgxDepth.hpp",[
        ("M2 role-tag snapshot", "    std::shared_ptr<const DuoViewDepthRequest> duoview_request;",
         """    std::shared_ptr<const DuoViewDepthRequest> duoview_request;
    bool duoview_fovea{};"""),
        ("M2 skip fovea pruning", "        prune_locked(want_w,want_h,false);",
         "        if (!duo) prune_locked(want_w,want_h,false);"),
        ("M2 allow unique-role outputs",
         """        if (!matches_periphery(out_w, out_h, want_w, want_h) ||
            (request && matches_periphery(out_w, out_h, request->fovea_width, request->fovea_height))) {""",
         """        const bool fine_output=duo && request &&
            matches_periphery(out_w,out_h,request->fovea_width,request->fovea_height);
        const bool coarse_output=matches_periphery(out_w,out_h,want_w,want_h);
        if (!coarse_output && !fine_output) {"""),
        ("M2 tag actual role", "        slot->duoview_request = request;",
         """        slot->duoview_request = request;
        slot->duoview_fovea = fine_output;"""),
        ("M2 TriView lookup", "        return select_recent(w, h, {}, nullptr);",
         "        return select_recent(w, h, {}, nullptr, false);"),
        ("M2 DuoView coarse lookup",
         "        return select_recent(width, height, request, consumer_queue);",
         """        return select_recent(width, height, request, consumer_queue, false);
    }

    // Do not infer the fovea from atlas position, the output must match the
    // separately requested DLSS foveal dimensions and the same generation.
    std::shared_ptr<const DepthSnapshot> latest_duoview_fovea_submitted(
            uint64_t generation, uint32_t width, uint32_t height,
            ID3D12CommandQueue* consumer_queue) {
        const auto request=duoview_expected_.load(std::memory_order_acquire);
        if (capture_mode_.load(std::memory_order_acquire)!=DepthCaptureMode::DuoView ||
            !request || request->generation!=generation ||
            request->fovea_width!=width || request->fovea_height!=height ||
            !consumer_queue) return {};
        return select_recent(width,height,request,consumer_queue,true);"""),
        ("M2 role-specific selection",
         """            uint32_t w, uint32_t h, const std::shared_ptr<const DuoViewDepthRequest>& request,
            ID3D12CommandQueue* consumer_queue) {""",
         """            uint32_t w, uint32_t h, const std::shared_ptr<const DuoViewDepthRequest>& request,
            ID3D12CommandQueue* consumer_queue, bool want_fovea) {"""),
        ("M2 role isolation", "            if (slot->duoview_request != request) continue;",
         """            if (slot->duoview_request != request) continue;
            if (request && slot->duoview_fovea != want_fovea) continue;"""),
    ])


def m2_compositor(mods):
    patch(mods/"vr/DuoViewD3D12.hpp",[
        ("M2 focus input", "const stereo::Geometry* stereo_geometry = nullptr, const M1DepthInput* stereo_depth = nullptr) {",
         "const stereo::Geometry* stereo_geometry = nullptr, const M1DepthInput* stereo_depth = nullptr,\n                const M1DepthInput* stereo_fovea_depth = nullptr) {"),
        ("M2 lease retire", "        m1_.depth_lease.reset();",
         "        m1_.depth_lease.reset();\n        m1_.fovea_depth_lease.reset();"),
        ("M2 constants and focus descriptor",
         """m1_.ready() && m1_.write_constants(device,*stereo_geometry,stereo_depth,
                settings.stereo_near_m,settings.stereo_softness,m1_raw_srv_);""",
         """m1_.ready() && m1_.write_constants(device,*stereo_geometry,stereo_depth,
                settings.m2_fovea_depth ? stereo_fovea_depth : nullptr,
                {layout.u0,layout.v0,layout.u1,layout.v1},
                settings.m2_unlinked_sharpen ? settings.m2_left_sharpen : settings.sharpen_strength,
                settings.m2_unlinked_sharpen ? settings.m2_right_sharpen : settings.sharpen_strength,
                settings.stereo_near_m,settings.stereo_softness,m1_raw_srv_,m2_fovea_srv_);"""),
        ("M2 raw registers", "m1_raw_range.NumDescriptors=1;",
         "m1_raw_range.NumDescriptors=2;"),
        ("M2 scratch descriptor count", "hd.NumDescriptors = 7;",
         "hd.NumDescriptors = 8;"),
        ("M2 shader input descriptor",
         """        m1_raw_srv_=desc_cpu;
        device->CreateShaderResourceView(nullptr,&soft_srv,m1_raw_srv_);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_UNORDERED_ACCESS_VIEW_DESC soft_uav{};""",
         """        m1_raw_srv_=desc_cpu;
        device->CreateShaderResourceView(nullptr,&soft_srv,m1_raw_srv_);
        desc_cpu.ptr+=srv_descriptor_increment_;
        m2_fovea_srv_=desc_cpu;
        device->CreateShaderResourceView(nullptr,&soft_srv,m2_fovea_srv_);
        desc_cpu.ptr+=srv_descriptor_increment_;
        D3D12_UNORDERED_ACCESS_VIEW_DESC soft_uav{};"""),
        ("M2 GPU descriptor routing",
         """            raw.ptr+=srv_descriptor_increment_;
            cmd->SetComputeRootDescriptorTable(6,raw);""",
         """            raw.ptr+=UINT64(2)*srv_descriptor_increment_;
            cmd->SetComputeRootDescriptorTable(6,raw);"""),
        ("M2 resource state", "    D3D12_CPU_DESCRIPTOR_HANDLE m1_raw_srv_{};",
         """    D3D12_CPU_DESCRIPTOR_HANDLE m1_raw_srv_{};
    D3D12_CPU_DESCRIPTOR_HANDLE m2_fovea_srv_{};"""),
        ("M2 state diagnostic", "    bool last_stereo_depth() const {",
         "    bool last_stereo_fovea_depth() const { return last_stereo_output_ && m1_.fovea_depth_active; }\n    bool last_stereo_depth() const {"),
    ])


def m2_delivery(mods):
    path=mods/"vr/D3D12Component.cpp"
    patch(path,[
        ("M2 focus object", "                                    std::optional<uevr::duoview::dx12::M1DepthInput> stereo_depth;",
         """                                    std::optional<uevr::duoview::dx12::M1DepthInput> stereo_depth;
                                    std::optional<uevr::duoview::dx12::M1DepthInput> fine_depth;"""),
        ("M2 source pair selection",
         """                                                snapshot->jitter_valid ? snapshot->jitter_uv : std::array<float,2>{},snapshot};
                                            // Use the same queue that the depth selection verified.""",
         """                                                snapshot->jitter_valid ? snapshot->jitter_uv : std::array<float,2>{},snapshot};
                                            if (snapshot && config.settings.m2_fovea_depth) {
                                                const auto& fovea=config.layout.fovea;
                                                const auto focus=uevr::quadview::ngx::PeripheryDepth::self()
                                                    .latest_duoview_fovea_submitted(config.key.generation,
                                                        fovea.width,fovea.height,current_queue);
                                                // A cross-frame depth pair is worse than coarse-only
                                                // stereo. No guessed provenance, no stale mixed views.
                                                if (focus && focus->jitter_valid &&
                                                    focus->recorded <= std::chrono::steady_clock::now() &&
                                                    (focus->recorded > snapshot->recorded
                                                        ? focus->recorded-snapshot->recorded
                                                        : snapshot->recorded-focus->recorded) <=
                                                        std::chrono::milliseconds(25)) {
                                                    fine_depth=uevr::duoview::dx12::M1DepthInput{
                                                        focus->texture.Get(),focus->srv_format,
                                                        {focus->rect[0],focus->rect[1],focus->rect[2],focus->rect[3]},
                                                        focus->jitter_uv,focus};
                                                }
                                            }
                                            // Use the same queue that the depth selection verified."""),
        ("M2 pass paired raw depth",
         """stereo_geometry ? &*stereo_geometry : nullptr,stereo_depth ? &*stereo_depth : nullptr);""",
         """stereo_geometry ? &*stereo_geometry : nullptr,stereo_depth ? &*stereo_depth : nullptr,
                                        fine_depth ? &*fine_depth : nullptr);"""),
        ("M2 diagnostic source",
         """SPDLOG_INFO_EVERY_N_SEC(2,"[DuoView][M1] stereo={} DLSS depth={} strength={:.2f}",
                                                stereo_output,compositor.last_stereo_depth(),packet_frame->config.settings.stereo_strength);""",
         """SPDLOG_INFO_EVERY_N_SEC(2,"[DuoView][M2] stereo={} coarse_depth={} fovea_depth={} strength={:.2f}",
                                                stereo_output,compositor.last_stereo_depth(),
                                                compositor.last_stereo_fovea_depth(),packet_frame->config.settings.stereo_strength);"""),
    ])


def m2_shader(shaders):
    patch(shaders/"DuoViewGlamaryeFovea.hlsl",[
        ("M2 explicit strength overload", "float3 GlamSharpenNativeFovea(float2 fullUv, float3 center) {",
         "float3 GlamSharpenNativeFovea(float2 fullUv, float3 center, float strength) {"),
        ("M2 strength denominator", "max(SharpenStrength, 0.00001) + abs(diff) / possible",
         "max(strength, 0.00001) + abs(diff) / possible"),
        ("M2 legacy entry", "    return GlamEncode(c + change);\n}",
         """    return GlamEncode(c + change);
}
// Preserve every B40 / Mono non-M2 caller with the original linked strength.
float3 GlamSharpenNativeFovea(float2 uv, float3 c) {
    return GlamSharpenNativeFovea(uv,c,SharpenStrength);
}"""),
    ])
    patch(shaders/"DuoViewNativeCompositeRaster.hlsl",[
        ("M2 per-eye raster strength",
         """        if (SharpenStrength > 0.0 && DebugViewMode == 0)
            fovea.rgb = GlamSharpenNativeFovea(fullUv, fovea.rgb);""",
         """#ifdef DUOVIEW_M1_RASTER
        const float fineSharpen=i.pos.x>=OutputSize.x ? M2Sharpen.y : M2Sharpen.x;
        if (fineSharpen > 0.0 && DebugViewMode == 0)
            fovea.rgb=GlamSharpenNativeFovea(fullUv,fovea.rgb,fineSharpen);
#else
        if (SharpenStrength > 0.0 && DebugViewMode == 0)
            fovea.rgb = GlamSharpenNativeFovea(fullUv, fovea.rgb);
#endif"""),
    ])


def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: apply_duoview_m2.py <backend> <duoview-shaders>")
    mods=Path(sys.argv[1])/"src/mods"
    shaders=Path(sys.argv[2])
    m2_settings(mods)
    m2_capture(mods)
    m2_compositor(mods)
    m2_delivery(mods)
    m2_shader(shaders)
    print("M2: per-eye sharp, fine depth selection, guarded GPU SRV and crop fusion ready")


if __name__=="__main__":
    main()

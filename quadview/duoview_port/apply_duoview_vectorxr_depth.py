#!/usr/bin/env python3
"""Isolated DuoView -> VectorXR XR_KHR_composition_layer_depth output.

Apply AFTER M8. Color is unchanged when no valid depth swapchain is available.
No modifications to the separate M4 conditioner or VectorXR's validator/pacer.
Each color draw writes the corresponding reversed-Z eye depth into a D32_FLOAT
scratch DSV. Its actual selected source UV is shared with the color output.
A second, queue-ordered OpenXR transfer submits the exact scratch and must
succeed before either eye receives XrCompositionLayerDepthInfoKHR.
"""
import sys
from pathlib import Path

def patch(path, label, old, new):
    src=path.read_text(encoding="utf-8-sig")
    n=src.count(old)
    if n!=1:
        if label == "enable only synthetic-depth swapchain":
            p=src.find("auto depth_swapchain_create_info")
            print("XRDepth depth creation context:",repr(src[max(0,p-1200):p+120]))
        raise RuntimeError(f"XRDepth {label}: expected one anchor, found {n} in {path}: {old[:115]!r}")
    path.write_text(src.replace(old,new,1),encoding="utf-8",newline="\n")

def patch_all(path, label, old, new, count):
    src=path.read_text(encoding="utf-8-sig")
    n=src.count(old)
    if n!=count: raise RuntimeError(f"XRDepth {label}: wanted {count}, got {n}")
    path.write_text(src.replace(old,new),encoding="utf-8",newline="\n")

def settings(mods):
    p=mods/"vr/DuoViewConfig.hpp"
    patch(p,"setting", "    float m8_fill_near{1.f}, m8_fill_far{0.f};",
        "    float m8_fill_near{1.f}, m8_fill_far{0.f};\n"
        "    bool xr_depth_output{true}; // armed by default; valid stereo only")
    patch(p,"reconciliation", "    out.m8_fill_far=(std::clamp)(requested.m8_fill_far,0.f,1.f);",
        "    out.m8_fill_far=(std::clamp)(requested.m8_fill_far,0.f,1.f);\n"
        "    out.xr_depth_output=requested.xr_depth_output;")
    p=mods/"VR.hpp"
    patch(p,"default skip unused depth ON",
        'ModToggle::create(generate_name("DuoViewSkipDepthSwapchain"), false)',
        'ModToggle::create(generate_name("DuoViewSkipDepthSwapchain"), true)')
    patch(p,"toggle", '    const ModToggle::Ptr m_duo_m8_distance{',
        '    const ModToggle::Ptr m_duo_xr_depth{ModToggle::create(generate_name("DuoVectorXRDepth"),true)};\n'
        '    const ModToggle::Ptr m_duo_m8_distance{')
    patch(p,"persistence", "            *m_duo_m8_distance, *m_duo_m8_near_m,",
        "            *m_duo_xr_depth,\n            *m_duo_m8_distance, *m_duo_m8_near_m,")
    p=mods/"VR.cpp"
    patch(p,"reset skip unused depth ON",
        "m_duo_skip_depth->value()=false; // v208d",
        "m_duo_skip_depth->value()=true; // v208d: skip unused on by default")
    patch(p,"reset", "                    m_duo_m8_distance->value()=false;",
        "                    m_duo_xr_depth->value()=true;\n"
        "                    m_duo_m8_distance->value()=false;")
    patch(p,"frozen setting", "        .m8_fill_near=m_duo_m8_fill_near->value(), .m8_fill_far=m_duo_m8_fill_far->value(),",
        "        .m8_fill_near=m_duo_m8_fill_near->value(), .m8_fill_far=m_duo_m8_fill_far->value(),\n"
        "        .xr_depth_output=m_duo_xr_depth->value(),")
    patch(p,"settings comparison", "current.m8_fill_far==candidate.m8_fill_far &&",
        "        current.m8_fill_far==candidate.m8_fill_far &&\n"
        "        current.xr_depth_output==candidate.xr_depth_output &&")
    patch(p,"UI", '                        m_duo_m8_distance->draw("Distance-based depth edges and background fill");',
        '                        m_duo_xr_depth->draw("VectorXR: submit per-eye synthesized depth (experimental)");\n'
        '                        m_duo_m8_distance->draw("Distance-based depth edges and background fill");')

def shader(shader_dir):
    p=shader_dir/"DuoViewM1Stereo.hlsl"
    patch(p,"cbuffer", "    float4 M5Sharpen;",
        "    float4 M5Sharpen;\n"
        "    float4 M9XRDepth; // x: engine near*depth scale, y: stereo strength, z/w reserved")
    p=shader_dir/"DuoViewNativeCompositeRaster.hlsl"
    patch(p,"raster signature", "float4 PSNativeMain(VertexOut i) : SV_TARGET0 {",
        """#if defined(DUOVIEW_M1_RASTER) && defined(DUOVIEW_M1_EXPORT_DEPTH)
struct DuoXRDepthOutput {
    float4 color : SV_TARGET0;
    float depth : SV_Depth;
};
DuoXRDepthOutput PSNativeMain(VertexOut i) {
#else
float4 PSNativeMain(VertexOut i) : SV_TARGET0 {
#endif""")
    # The same fullUv and hole fill metadata used to display color must select
    # depth. No separate second warp / second source-coordinate reconstruction.
    patch(p,"final stereo output", "    return result;\n}",
        """#if defined(DUOVIEW_M1_RASTER) && defined(DUOVIEW_M1_EXPORT_DEPTH)
    DuoXRDepthOutput xrResult;
    xrResult.color=result;
    const uint xrEye=i.pos.x>=OutputSize.x ? 1u : 0u;
    // The existing M1PullUv already applied Near Depth Limit, foveal field
    // conditioning and the M3/M8 background selection to fullUv.
    // fill.y records the accepted background inverse depth when disoccluded.
    const float selectedInv=fill.z>.001 ? fill.y : M1ReadConditionedEye(fullUv,xrEye);
    // OpenXR receives physical IPD poses. Reduced synthetic stereo strength
    // is therefore represented by apparent inverse depth reduced by strength.
    xrResult.depth=saturate(max(0.,selectedInv)*M9XRDepth.x*M9XRDepth.y);
    return xrResult;
#else
    return result;
#endif
}""")

def compositor(mods):
    p=mods/"vr/DuoViewM1D3D12.hpp"
    patch(p,"constants C++", "    float m5_sharpen[4]{}; // left/right max change (negative = shared)",
        "    float m5_sharpen[4]{}; // left/right max change (negative = shared)\n"
        "    float m9_xr_depth[4]{};")
    patch(p,"constant size", "static_assert(sizeof(M1Constants) == 560);",
        "static_assert(sizeof(M1Constants) == 576);")
    patch(p,"scratch resource members",
        "    ComPtr<ID3D12Resource> soft_depth, constants;",
        """    ComPtr<ID3D12Resource> soft_depth, constants;
    ComPtr<ID3D12Resource> xr_depth_scratch;
    ComPtr<ID3D12DescriptorHeap> xr_depth_dsv_heap;
    ComPtr<ID3D12PipelineState> xr_depth_raster;
    D3D12_CPU_DESCRIPTOR_HANDLE xr_depth_dsv{};
    ComPtr<ID3D12Fence> xr_depth_consumer_fence;
    UINT64 xr_depth_consumer_value{};
    bool xr_depth_reusable() const {
        return !xr_depth_consumer_fence ||
            xr_depth_consumer_fence->GetCompletedValue()>=xr_depth_consumer_value;
    }
    void note_xr_depth_consumer(ID3D12Fence* fence, UINT64 value) {
        xr_depth_consumer_fence=fence;
        xr_depth_consumer_value=value;
    }
    bool write_xr_depth_constants(float engine_near, float scale, float strength) {
        if(!constants || !std::isfinite(engine_near) || engine_near<=0.f ||
           !std::isfinite(scale) || scale<=0.f ||
           !std::isfinite(strength) || strength<0.f || strength>1.f)
            return false;
        const float depth[4]{engine_near*scale,strength,0.f,0.f};
        void* target=nullptr; const D3D12_RANGE read{0,0};
        if(FAILED(constants->Map(0,&read,&target)) || !target) return false;
        std::memcpy(static_cast<uint8_t*>(target)+offsetof(M1Constants,m9_xr_depth),
                    depth,sizeof(depth));
        constants->Unmap(0,nullptr);
        return true;
    }""")
    patch(p,"prewarmed PSO and depth scratch", "        graphics.PS = {m1_raster_bytecode, sizeof(m1_raster_bytecode)};",
        """        // Optional depth PSO and DSV: always prewarm, NEVER allocate on XR copy.
        // Failure leaves color stereo fully operational.
        xr_depth_raster.Reset(); xr_depth_scratch.Reset();
        xr_depth_dsv_heap.Reset(); xr_depth_dsv={};
        {
            auto depth_graphics=graphics;
            depth_graphics.PS={m1_depth_raster_bytecode,sizeof(m1_depth_raster_bytecode)};
            depth_graphics.DepthStencilState.DepthEnable=TRUE;
            depth_graphics.DepthStencilState.DepthWriteMask=D3D12_DEPTH_WRITE_MASK_ALL;
            depth_graphics.DepthStencilState.DepthFunc=D3D12_COMPARISON_FUNC_ALWAYS;
            depth_graphics.DSVFormat=DXGI_FORMAT_D32_FLOAT;
            if(SUCCEEDED(device->CreateGraphicsPipelineState(&depth_graphics,
                  IID_PPV_ARGS(&xr_depth_raster)))) {
                D3D12_HEAP_PROPERTIES depth_heap{};
                depth_heap.Type=D3D12_HEAP_TYPE_DEFAULT;
                depth_heap.CreationNodeMask=depth_heap.VisibleNodeMask=1;
                D3D12_RESOURCE_DESC depth_desc{};
                depth_desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
                depth_desc.Width=uint64_t(eye_width)*2u; depth_desc.Height=eye_height;
                depth_desc.DepthOrArraySize=depth_desc.MipLevels=1;
                depth_desc.SampleDesc.Count=1; depth_desc.Format=DXGI_FORMAT_R32_TYPELESS;
                depth_desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL;
                D3D12_CLEAR_VALUE clear{};
                clear.Format=DXGI_FORMAT_D32_FLOAT; clear.DepthStencil.Depth=0.f;
                if(SUCCEEDED(device->CreateCommittedResource(&depth_heap,D3D12_HEAP_FLAG_NONE,
                    &depth_desc,D3D12_RESOURCE_STATE_DEPTH_WRITE,&clear,
                    IID_PPV_ARGS(&xr_depth_scratch)))) {
                    D3D12_DESCRIPTOR_HEAP_DESC heap_desc{};
                    heap_desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_DSV;
                    heap_desc.NumDescriptors=1;
                    if(SUCCEEDED(device->CreateDescriptorHeap(&heap_desc,
                            IID_PPV_ARGS(&xr_depth_dsv_heap)))) {
                        xr_depth_dsv=xr_depth_dsv_heap->GetCPUDescriptorHandleForHeapStart();
                        D3D12_DEPTH_STENCIL_VIEW_DESC view{};
                        view.Format=DXGI_FORMAT_D32_FLOAT;
                        view.ViewDimension=D3D12_DSV_DIMENSION_TEXTURE2D;
                        device->CreateDepthStencilView(xr_depth_scratch.Get(),&view,xr_depth_dsv);
                    }
                }
            }
        }
        if(!xr_depth_dsv_heap) {xr_depth_scratch.Reset(); xr_depth_raster.Reset();}
        graphics.PS = {m1_raster_bytecode, sizeof(m1_raster_bytecode)};""")
    p=mods/"vr/DuoViewD3D12.hpp"
    patch(p,"record inputs",
        "                const M1DepthInput* stereo_fovea_depth = nullptr) {",
        """                const M1DepthInput* stereo_fovea_depth = nullptr,
                float xr_near_engine=0.f, float xr_depth_scale=0.f) {""")
    patch(p,"clear depth per record",
        "        last_stereo_output_=false;",
        "        last_stereo_output_=false;\n        last_xr_depth_output_=false;")
    patch(p,"arm depth PSO",
        "        cmd->SetGraphicsRootSignature(root_.Get());\n        cmd->SetPipelineState(m1_active ? m1_.raster.Get() : native_pipeline_.Get());",
        """        const bool xr_depth_active=m1_active && settings.xr_depth_output &&
            m1_.rows!=0 && m1_.depth_lease && m1_.xr_depth_scratch &&
            m1_.xr_depth_raster && m1_.xr_depth_dsv_heap &&
            m1_.xr_depth_reusable() &&
            m1_.write_xr_depth_constants(xr_near_engine,xr_depth_scale,settings.stereo_strength);
        cmd->SetGraphicsRootSignature(root_.Get());
        cmd->SetPipelineState(xr_depth_active ? m1_.xr_depth_raster.Get() :
                              m1_active ? m1_.raster.Get() : native_pipeline_.Get());""")
    # The full render target is drawn by both the direct Native and fallback
    # branches; only the stereo depth path supplies a DSV.
    patch_all(p,"two Native draw DSV bindings",
        "            cmd->OMSetRenderTargets(1,&handle,FALSE,nullptr);",
        """            if(xr_depth_active)
                cmd->ClearDepthStencilView(m1_.xr_depth_dsv,D3D12_CLEAR_FLAG_DEPTH,0.f,0,0,nullptr);
            cmd->OMSetRenderTargets(1,&handle,FALSE,
                xr_depth_active ? &m1_.xr_depth_dsv : nullptr);""",2)
    patch(p,"record produced GPU depth",
        "        last_stereo_output_=m1_active;",
        """        last_stereo_output_=m1_active;
        last_xr_depth_output_=xr_depth_active;""")
    patch(p,"public accessors",
        "    bool last_stereo_output() const { return last_stereo_output_; }",
        """    bool last_stereo_output() const { return last_stereo_output_; }
    ID3D12Resource* last_xr_depth_resource() const {
        return last_xr_depth_output_ ? m1_.xr_depth_scratch.Get() : nullptr;
    }
    void note_xr_depth_consumer(ID3D12Fence* fence, UINT64 value) {
        m1_.note_xr_depth_consumer(fence,value);
    }""")
    patch(p,"per-slot record metadata",
        "    bool last_stereo_output_{};",
        "    bool last_stereo_output_{}, last_xr_depth_output_{};")

def xr_submission(mods):
    p=mods/"vr/runtimes/OpenXR.hpp"
    patch(p,"frozen depth metadata",
        "        bool duoview_stereo_output{};",
        """        bool duoview_depth_output{};
        uint64_t duoview_depth_generation{};
        float duoview_depth_far_m{};
        bool duoview_stereo_output{};""")
    p=mods/"vr/runtimes/OpenXR.cpp"
    patch(p,"mono must not globally suppress DuoView depth",
        "    if (mono) { has_depth = false; }",
        "    if (mono) { has_depth = false; } // DuoView opt-in evaluated after frozen packet selection")
    patch(p,"DuoView strict depth packet gate",
        "    if (duo_stereo) stalker_pair.reset();",
        """    if (duo_stereo) stalker_pair.reset();
    // Keep the original XR frame pacing, and fail closed on the entire pair.
    const auto depth_it=this->swapchains.find((uint32_t)OpenXR::SwapchainIndex::DEPTH);
    const auto color_it=this->swapchains.find((uint32_t)OpenXR::SwapchainIndex::DOUBLE_WIDE);
    const bool duo_depth=duo_stereo && !duoview_holding &&
        submit_state.duoview_depth_output &&
        submit_state.duoview_depth_generation==vr->mono_generation() &&
        std::isfinite(submit_state.duoview_depth_far_m) &&
        submit_state.duoview_depth_far_m>0.f && this->is_depth_allowed() &&
        depth_it!=this->swapchains.end() && color_it!=this->swapchains.end() &&
        depth_it->second.width==color_it->second.width &&
        depth_it->second.height==color_it->second.height &&
        depth_it->second.width>0 && (depth_it->second.width%2)==0;
    if(duo_stereo) {
        has_depth=duo_depth;
        if(!duo_depth) {
            SPDLOG_WARNING_EVERY_N_SEC(2,
                "[DuoView][XRDepth] color-only: held={} producer={} generation_ok={} depth_swapchain={} extension={}",
                duoview_holding,submit_state.duoview_depth_output,
                submit_state.duoview_depth_generation==vr->mono_generation(),
                depth_it!=this->swapchains.end(),this->is_depth_allowed());
        }
    }""")
    patch(p,"use frozen near-far metadata",
        "                depth_layers[i].farZ = nearz * VR::get()->get_depth_scale();",
        """                depth_layers[i].farZ = duo_depth ? submit_state.duoview_depth_far_m :
                    nearz * VR::get()->get_depth_scale();""")
    patch(p,"diagnose actual bilateral depth attachment",
        "                projection_layer_views[i].next = &depth_layers[i];",
        """                projection_layer_views[i].next = &depth_layers[i];
                if(duo_depth) SPDLOG_INFO_EVERY_N_SEC(2,
                    "[DuoView][XRDepth] submitted eye={} rect={}x{}+{},{} slice={} depth_chain={} generation={} farZ={}",
                    i,extent_x,extent_y,offset_x,offset_y,
                    depth_layers[i].subImage.imageArrayIndex,
                    reinterpret_cast<uintptr_t>(depth_layers[i].subImage.swapchain),
                    submit_state.duoview_depth_generation,depth_layers[i].farZ);""")

def producer(mods):
    p=mods/"vr/D3D12Component.cpp"
    patch(p,"honor existing skip-depth toggle, but allocate automatically when used",
        "    const bool skip_unused_depth_swapchain =\n"
        "        vr->get_openxr_runtime()->is_depth_allowed() && vr->should_skip_unused_depth_swapchain();",
        """    const bool duo_depth_chain=vr->is_duoview_renderer_active() &&
        vr->duoview_state().settings().synthetic_stereo &&
        vr->duoview_state().settings().xr_depth_output;
    const bool skip_unused_depth_swapchain =
        vr->get_openxr_runtime()->is_depth_allowed() &&
        vr->should_skip_unused_depth_swapchain() && !duo_depth_chain;""")
    patch(p,"use runtime-supported single-sample D32_FLOAT for DuoView",
        "        if (!create_afr_depth) {\n            spdlog::info(\"[VR] Creating double wide depth swapchain\");",
        """        if(duo_depth_chain) {
            const auto formats=vr->get_openxr_runtime()->get_supported_swapchain_formats();
            const bool d32_supported=std::find(formats.begin(),formats.end(),
                DXGI_FORMAT_D32_FLOAT)!=formats.end();
            if(d32_supported) {
                auto duo_ci=standard_swapchain_create_info;
                duo_ci.format=DXGI_FORMAT_D32_FLOAT; duo_ci.createFlags=0;
                duo_ci.sampleCount=1;
                duo_ci.usageFlags=XR_SWAPCHAIN_USAGE_SAMPLED_BIT |
                    XR_SWAPCHAIN_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT |
                    XR_SWAPCHAIN_USAGE_MUTABLE_FORMAT_BIT;
                duo_ci.width=vr->get_hmd_width()*2u; duo_ci.height=vr->get_hmd_height();
                D3D12_RESOURCE_DESC duo_desc=backbuffer_desc;
                duo_desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
                duo_desc.Width=duo_ci.width; duo_desc.Height=duo_ci.height;
                duo_desc.DepthOrArraySize=duo_desc.MipLevels=1;
                duo_desc.SampleDesc.Count=1; duo_desc.SampleDesc.Quality=0;
                duo_desc.Format=DXGI_FORMAT_R32_TYPELESS;
                duo_desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL;
                if(auto error=create_swapchain(
                    (uint32_t)runtimes::OpenXR::SwapchainIndex::DEPTH,duo_ci,duo_desc)) {
                    SPDLOG_WARNING("[DuoView][XRDepth] runtime rejected D32 depth swapchain; color-only");
                } else {
                    SPDLOG_INFO("[DuoView][XRDepth] D32_FLOAT sampleable single-sample depth swapchain {}x{}",
                        duo_ci.width,duo_ci.height);
                }
            } else {
                SPDLOG_WARNING("[DuoView][XRDepth] runtime lacks D32_FLOAT; color-only");
            }
        } else if (!create_afr_depth) {
            spdlog::info("[VR] Creating double wide depth swapchain");""")
    patch(p,"track depth copy input",
        "                            bool stereo_output = false;",
        """                            bool stereo_output = false;
                            Microsoft::WRL::ComPtr<ID3D12Resource> xr_depth_scratch;
                            uevr::duoview::dx12::Compositor* xr_depth_owner=nullptr;""")
    patch(p,"capture producer metadata",
        "&recorded_target, &stereo_output, &recorded_compositor](",
        "&recorded_target, &stereo_output, &xr_depth_scratch, &xr_depth_owner](")
    patch(p,"freeze depth scale alongside final color",
        "                                        fine_depth ? &*fine_depth : nullptr);",
        """                                        fine_depth ? &*fine_depth : nullptr,
                                        sdk::globals::get_near_clipping_plane(),
                                        vr->get_depth_scale());""")
    patch(p,"read same slot depth output",
        "                                        stereo_output=compositor.last_stereo_output();",
        """                                        stereo_output=compositor.last_stereo_output();
                                        xr_depth_scratch=compositor.last_xr_depth_resource();
                                        xr_depth_owner=&compositor;""")
    patch(p,"submit depth after color, before accepting frozen pose",
        "                            if (submitted && recorded) {\n                                runtimes::OpenXR::PipelineState pose{};",
        """                            bool xr_depth_copied=false;
                            if(submitted && recorded && stereo_output && xr_depth_scratch &&
                                xr_depth_owner && packet_frame->config.settings.xr_depth_output) {
                                const auto depth_index=(uint32_t)runtimes::OpenXR::SwapchainIndex::DEPTH;
                                const auto depth_chain=m_openxr.contexts.find(depth_index);
                                if(depth_chain!=m_openxr.contexts.end() &&
                                    vr->get_openxr_runtime()->swapchains.contains(depth_index)) {
                                    // One queue: the copy of depth runs after this frame's
                                    // stereo draw. The same depth values were written by PS.
                                    xr_depth_copied=m_openxr.copy(depth_index,xr_depth_scratch.Get(),
                                        std::nullopt,std::nullopt,D3D12_RESOURCE_STATE_DEPTH_WRITE,nullptr);
                                    if(xr_depth_copied) {
                                        const auto& dc=depth_chain->second;
                                        if(dc.last_acquired_texture<dc.texture_contexts.size() &&
                                           dc.texture_contexts[dc.last_acquired_texture]) {
                                            auto& commands=dc.texture_contexts[dc.last_acquired_texture]->commands;
                                            if(commands.fence && !commands.poisoned) {
                                                xr_depth_owner->note_xr_depth_consumer(
                                                    commands.fence.Get(),commands.fence_value);
                                            } else xr_depth_copied=false;
                                        } else xr_depth_copied=false;
                                    }
                                }
                            }
                            if(submitted && recorded) {
                                runtimes::OpenXR::PipelineState pose{};""")
    patch(p,"frozen packet depth proof",
        "                                pose.duoview_stereo_output=stereo_output;",
        """                                pose.duoview_depth_output=xr_depth_copied;
                                pose.duoview_depth_generation=packet_frame->config.key.generation;
                                const float world_units=vr->get_world_to_meters();
                                pose.duoview_depth_far_m=world_units>0.f ?
                                    sdk::globals::get_near_clipping_plane()/world_units *
                                    vr->get_depth_scale() : 0.f;
                                SPDLOG_INFO_EVERY_N_SEC(2,
                                    "[DuoView][XRDepth] depth produced/copy-queued both-eyes={} coarse={} fine={} source={} generation={}",
                                    xr_depth_copied,bool(xr_depth_scratch),require_fine,
                                    *packet_source,packet_frame->config.key.generation);
                                pose.duoview_stereo_output=stereo_output;""")

def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: apply_duoview_vectorxr_depth.py <backend> <shader-dir>")
    backend=Path(sys.argv[1]); shaders=Path(sys.argv[2]); mods=backend/"src/mods"
    settings(mods)
    shader(shaders)
    compositor(mods)
    xr_submission(mods)
    producer(mods)
    print("DuoView VectorXR: one-pass eye depth DSV, guarded XR copy and bilateral submit applied")

if __name__=="__main__":
    main()

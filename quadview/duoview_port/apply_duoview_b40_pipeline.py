#!/usr/bin/env python3
"""DuoView ID6 B40 production GPU port — queue-owned history and one dispatch.
Never patch mode7; applies to Joey-generated mode6 after Phase2/B43 overlays.
No allocations or shader compilation inside xrAcquire/copy/present callback.
"""
from pathlib import Path
import sys

def once(text,before,after,label):
    n=text.count(before)
    if n!=1: raise RuntimeError(f"B40 GPU {label}: expected one anchor, got {n}: {before[:110]!r}")
    return text.replace(before,after,1)

def patch(path,edits):
    t=path.read_text(encoding="utf-8-sig")
    for label,old,new in edits:
        t=once(t,old,new,label)
    path.write_text(t,encoding="utf-8",newline="\n")

def main():
    if len(sys.argv)!=2: raise SystemExit("Usage: apply_duoview_b40_pipeline.py <backend>")
    root=Path(sys.argv[1])
    dxh=root/"src/mods/vr/DuoViewD3D12.hpp"

    history_struct="""
// B40's original queue-owned shared history, adapted to ONE Mono fovea.
// Allocation in setup/prewarm only; all compositor slots share the same buffer.
// OpenXR command slots are fence retired before lifetime release.
struct B40MonoHistory {
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12Resource> buffer;
    static std::shared_ptr<B40MonoHistory> create(ID3D12Device* device,ID3D12CommandQueue* queue) {
        if (!device || !queue) return {};
        auto state=std::make_shared<B40MonoHistory>();
        state->device=device; state->queue=queue;
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC desc{};
        desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width=32u*3u*4u*sizeof(float);
        desc.Height=desc.DepthOrArraySize=desc.MipLevels=1;
        desc.SampleDesc.Count=1; desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        // Committed buffer initially zeroed; B40 startup ramps from neutral.
        if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&state->buffer)))) return {};
        state->buffer->SetName(L"DuoView B40 Mono queue-owned history");
        return state;
    }
};
"""
    dispatch="""
    uint32_t b40_timestamp_ms() const {
        if (b40_test_timestamp_ms_) return b40_test_timestamp_ms_;
        return static_cast<uint32_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
    }
    bool b40_ready() const {
        return b40_history_ && b40_history_->buffer &&
            b40_history_->device.Get()==device_.Get() &&
            b40_stats_ && b40_native_pipeline_ && b40_gather_pipeline_;
    }
    void dispatch_b40(ID3D12GraphicsCommandList* cmd,const ShaderConstants& constants,bool native) {
        // Caller already transitioned source SRVs to ALL_SHADER_RESOURCE.
        // Same fenced OpenXR slot owns its read/write descriptors and output.
        transition(cmd,b40_stats_.Get(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,
                   D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        cmd->SetComputeRootSignature(root_.Get());
        cmd->SetPipelineState(native ? b40_native_pipeline_.Get() : b40_gather_pipeline_.Get());
        cmd->SetComputeRootDescriptorTable(0,srv_gpu_start_);
        cmd->SetComputeRoot32BitConstants(1,sizeof(constants)/4,&constants,0);
        auto uav=srv_gpu_start_;
        uav.ptr+=UINT64(3)*srv_descriptor_increment_;
        cmd->SetComputeRootDescriptorTable(2,uav);
        auto* history=b40_history_->buffer.Get();
        cmd->SetComputeRootUnorderedAccessView(3,history->GetGPUVirtualAddress());
        D3D12_RESOURCE_BARRIER order{};
        order.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;
        order.UAV.pResource=history;
        cmd->ResourceBarrier(1,&order); // prior XR slot's history writes
        cmd->Dispatch(1,1,1); // one Mono image: 32 knots, 128 groups, 1920 paired patches
        cmd->ResourceBarrier(1,&order); // next XR slot sees this history
        transition(cmd,b40_stats_.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                   D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE); // pixel sees stable 32 knots
    }
"""
    patch(dxh,[
        ("chrono header", '#include <memory>',
         '#include <memory>\n#include <chrono>'),
        ("B40 constant layout",
         "    float seam_geometry[4];\n};\nstatic_assert(sizeof(ShaderConstants) == 192);",
         "    float seam_geometry[4];\n    uint32_t b40_temporal[4];\n};\n"
         "static_assert(sizeof(ShaderConstants) == 208);"),
        ("B40 root DWORD assertion",
         "static_assert(sizeof(ShaderConstants)/4 <= 64); // D3D12 root DWORD budget",
         "static_assert(sizeof(ShaderConstants)/4 + 4 <= 64); // b0 + SRV table + UAV table + history root UAV"),
        ("queue state struct",
         "class Compositor {\npublic:",
         history_struct+"\nclass Compositor {\npublic:\n"
         "    void set_b40_history(std::shared_ptr<B40MonoHistory> state) {\n"
         "        // Never allocate or destroy GPU history on the XR frame callback.\n"
         "        b40_history_=std::move(state);\n"
         "    }\n"
         "    void set_b40_test_timestamp_ms(uint32_t stamp) { b40_test_timestamp_ms_=stamp; }\n"
         "    const std::string& b40_warning() const { return b40_warning_; }"),
        ("gather b40 active",
         "        ShaderConstants constants{\n            {l.atlas_width / 2, l.atlas_height},",
         "        const bool b40_active=frame.settings.seam_match_enabled && b40_ready();\n"
         "        ShaderConstants constants{\n            {l.atlas_width / 2, l.atlas_height},"),
        ("gather b40 enabled uniform",
         "{frame.settings.seam_match_enabled ? 1.f : 0.f,\n                frame.settings.seam_strength, frame.settings.seam_limit, 0.f}",
         "{b40_active ? 1.f : 0.f,\n                frame.settings.seam_strength, frame.settings.seam_limit, frame.settings.seam_ambient_inside_px}"),
        ("gather B40 constants",
         "{frame.settings.seam_reach_px, frame.settings.seam_inward_px,\n                frame.settings.seam_color_strength, 0.f}};",
         "{frame.settings.seam_reach_px, frame.settings.seam_inward_px,\n"
         "                frame.settings.seam_color_strength, frame.settings.seam_ambient_radius_px},\n"
         "            {b40_timestamp_ms(),frame.settings.seam_time_ms,b40_active?1u:0u,0u}};"),
        ("gather shader state all stages",
         "        transition(cmd, atlas, atlas_state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);",
         "        const auto sample_state=b40_active ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE :\n"
         "            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;\n"
         "        transition(cmd, atlas, atlas_state, sample_state);"),
        ("gather dispatch before raster",
         "        cmd->SetDescriptorHeaps(1, heaps);\n        cmd->SetGraphicsRootSignature(root_.Get());",
         "        cmd->SetDescriptorHeaps(1, heaps);\n"
         "        if (b40_active) dispatch_b40(cmd,constants,false);\n"
         "        cmd->SetGraphicsRootSignature(root_.Get());"),
        ("gather source return state",
         "        transition(cmd, atlas, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, atlas_state);",
         "        transition(cmd, atlas, sample_state, atlas_state);"),
        ("native B40 active",
         "        ShaderConstants constants{\n            {layout.atlas_width/2,layout.atlas_height},",
         "        const bool b40_active=frame.config.settings.seam_match_enabled && b40_ready();\n"
         "        ShaderConstants constants{\n            {layout.atlas_width/2,layout.atlas_height},"),
        ("native shader b40 uniform",
         "{frame.config.settings.seam_match_enabled ? 1.f : 0.f,\n                frame.config.settings.seam_strength, frame.config.settings.seam_limit, 0.f}",
         "{b40_active ? 1.f : 0.f,\n"
         "                frame.config.settings.seam_strength, frame.config.settings.seam_limit,\n"
         "                frame.config.settings.seam_ambient_inside_px}"),
        ("native B40 root constants",
         "{frame.config.settings.seam_reach_px, frame.config.settings.seam_inward_px,\n                frame.config.settings.seam_color_strength, 0.f}",
         "{frame.config.settings.seam_reach_px, frame.config.settings.seam_inward_px,\n"
         "                frame.config.settings.seam_color_strength, frame.config.settings.seam_ambient_radius_px},\n"
         "            {b40_timestamp_ms(),frame.config.settings.seam_time_ms,b40_active?1u:0u,0u}"),
        ("native source state for compute",
         "        transition(cmd,fovea,fovea_state,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);\n"
         "        transition(cmd,periphery,peripheral_state,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);",
         "        const auto sample_state=b40_active ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE :\n"
         "            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;\n"
         "        transition(cmd,fovea,fovea_state,sample_state);\n"
         "        transition(cmd,periphery,peripheral_state,sample_state);"),
        ("native dispatch before pixel",
         "        cmd->SetDescriptorHeaps(1,heaps);\n        cmd->SetGraphicsRootSignature(root_.Get());",
         "        cmd->SetDescriptorHeaps(1,heaps);\n"
         "        if (b40_active) dispatch_b40(cmd,constants,true);\n"
         "        cmd->SetGraphicsRootSignature(root_.Get());"),
        ("native source restoration",
         "        transition(cmd,fovea,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,fovea_state);\n"
         "        transition(cmd,periphery,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,peripheral_state);",
         "        transition(cmd,fovea,sample_state,fovea_state);\n"
         "        transition(cmd,periphery,sample_state,peripheral_state);"),
        ("shared B40 dispatch helper",
         "private:\n    void ensure_srvs(",
         "private:\n"+dispatch+"\n    void ensure_srvs("),
        ("no in-frame pipeline recreation",
         "if (device_.Get() == device && output_ && pipeline_ && native_pipeline_ && root_ && srv_ && rtv_ && width == width_ && height == height_ && srgb == srgb_) return true;",
         "if (device_.Get() == device && output_ && pipeline_ && native_pipeline_ &&\n"
         "            root_ &&\n"
         "            srv_ && rtv_ && width == width_ && height == height_ && srgb == srgb_) return true;"),
        ("B40 resources owned by prewarm",
         "output_.Reset(); atlas_.Reset(); pipeline_.Reset(); native_pipeline_.Reset(); root_.Reset(); srv_.Reset(); rtv_.Reset();",
         "output_.Reset(); atlas_.Reset(); pipeline_.Reset(); native_pipeline_.Reset();\n"
         "        b40_native_pipeline_.Reset(); b40_gather_pipeline_.Reset(); b40_stats_.Reset();\n"
         "        b40_warning_.clear();\n"
         "        root_.Reset(); srv_.Reset(); rtv_.Reset();"),
        ("three SRV descriptors", "range.NumDescriptors = 2;",
         "range.NumDescriptors = 3; // t0 fovea, t1 periphery, t2 B40 32-knot stats"),
        ("root parameters + UAV range",
         "        D3D12_ROOT_PARAMETER params[2]{};",
         "        D3D12_DESCRIPTOR_RANGE uav_range{};\n"
         "        uav_range.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_UAV;\n"
         "        uav_range.NumDescriptors=1;\n"
         "        D3D12_ROOT_PARAMETER params[4]{};"),
        ("compute-visible SRVs",
         "params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;",
         "params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;"),
        ("UAV descriptor/root address",
         "        params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;\n"
         "        D3D12_STATIC_SAMPLER_DESC sampler{};",
         "        params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;\n"
         "        params[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;\n"
         "        params[2].DescriptorTable={1,&uav_range};\n"
         "        params[2].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;\n"
         "        params[3].ParameterType=D3D12_ROOT_PARAMETER_TYPE_UAV;\n"
         "        params[3].Descriptor={1,0}; // u1 queue-shared history root descriptor\n"
         "        params[3].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;\n"
         "        D3D12_STATIC_SAMPLER_DESC sampler{};"),
        ("compute-visible sampler",
         "sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;",
         "sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;"),
        ("four-parameter root signature",
         "D3D12_ROOT_SIGNATURE_DESC desc{2, params, 1, &sampler, D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT};",
         "D3D12_ROOT_SIGNATURE_DESC desc{4, params, 1, &sampler, D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT};"),
        ("production seam compute PSOs",
         'if (!check(device->CreateGraphicsPipelineState(&graphics, IID_PPV_ARGS(&native_pipeline_)), "Create direct Native raster PSO")) return false;',
         'if (!check(device->CreateGraphicsPipelineState(&graphics, IID_PPV_ARGS(&native_pipeline_)), "Create direct Native raster PSO")) return false;\n'
         '        D3D12_COMPUTE_PIPELINE_STATE_DESC compute{};\n'
         '        compute.pRootSignature=root_.Get();\n'
         '        compute.CS={gather_b40_compute_bytecode,sizeof(gather_b40_compute_bytecode)};\n'
         '        if (!check(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&b40_gather_pipeline_)),"Create B40 gather compute PSO")) b40_warning_=std::move(error_);\n'
         '        compute.CS={native_b40_compute_bytecode,sizeof(native_b40_compute_bytecode)};\n'
         '        if (!check(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&b40_native_pipeline_)),"Create B40 Native compute PSO")) b40_warning_=std::move(error_);'),
        ("prewarm stats alloc before heaps",
         '        D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.NumDescriptors = 2; hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;',
         '        // Per-fenced-slot analysis output; queue-owned EMA lives separately.\n'
         '        D3D12_RESOURCE_DESC stats{};\n'
         '        stats.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;\n'
         '        stats.Width=64u*4u*sizeof(float); // 32 knots * target+stable float4\n'
         '        stats.Height=stats.DepthOrArraySize=stats.MipLevels=1;\n'
         '        stats.SampleDesc.Count=1; stats.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;\n'
         '        stats.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;\n'
         '        if (!check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&stats,\n'
         '            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,nullptr,IID_PPV_ARGS(&b40_stats_)),"Create B40 slot stats")) b40_warning_=std::move(error_);\n'
         '        D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.NumDescriptors = 2; hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;'),
        ("4 heap descriptors",
         "hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE; hd.NumDescriptors = 2;",
         "hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE; hd.NumDescriptors = 4;"),
        ("bind stats SRV and output UAV",
         "        srv_descriptor_increment_=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);",
         "        srv_descriptor_increment_=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);\n"
         "        D3D12_SHADER_RESOURCE_VIEW_DESC stat_srv{};\n"
         "        stat_srv.Format=DXGI_FORMAT_UNKNOWN;\n"
         "        stat_srv.ViewDimension=D3D12_SRV_DIMENSION_BUFFER;\n"
         "        stat_srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;\n"
         "        stat_srv.Buffer.NumElements=64;\n"
         "        stat_srv.Buffer.StructureByteStride=4*sizeof(float);\n"
         "        auto desc_cpu=srv_cpu_start_;\n"
         "        desc_cpu.ptr+=SIZE_T(2)*srv_descriptor_increment_;\n"
         "        device->CreateShaderResourceView(b40_stats_.Get(),&stat_srv,desc_cpu);\n"
         "        desc_cpu.ptr+=srv_descriptor_increment_;\n"
         "        D3D12_UNORDERED_ACCESS_VIEW_DESC stat_uav{};\n"
         "        stat_uav.Format=DXGI_FORMAT_UNKNOWN;\n"
         "        stat_uav.ViewDimension=D3D12_UAV_DIMENSION_BUFFER;\n"
         "        stat_uav.Buffer.NumElements=64;\n"
         "        stat_uav.Buffer.StructureByteStride=4*sizeof(float);\n"
         "        device->CreateUnorderedAccessView(b40_stats_.Get(),nullptr,&stat_uav,desc_cpu);"),
        ("resource members",
         "    ComPtr<ID3D12RootSignature> root_;\n    ComPtr<ID3D12PipelineState> pipeline_, native_pipeline_;",
         "    ComPtr<ID3D12RootSignature> root_;\n"
         "    ComPtr<ID3D12PipelineState> pipeline_, native_pipeline_, b40_native_pipeline_, b40_gather_pipeline_;\n"
         "    ComPtr<ID3D12Resource> b40_stats_;\n"
         "    std::shared_ptr<B40MonoHistory> b40_history_{};\n"
         "    uint32_t b40_test_timestamp_ms_{};\n"
         "    std::string b40_warning_;"),
    ])
    # Add one shared queue-owned history pointer at the OpenXR runtime owner,
    # never inside an individual frame's temporary C++ stack state.
    dxheader=root/"src/mods/vr/D3D12Component.hpp"
    patch(dxheader,[
        ("shared history owner in XR session",
         "        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;",
         "        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;\n"
         "        std::shared_ptr<uevr::duoview::dx12::B40MonoHistory> duoview_b40_history;"),
    ])
    cpp=root/"src/mods/vr/D3D12Component.cpp"
    patch(cpp,[
        ("retire activation slot before changing GPU resources",
         '                if (!tc) continue;\n'
         '                auto& comp = m_openxr.duoview_compositors[&tc->commands];',
         '                if (!tc || !tc->commands.references_retired()) continue;\n'
         '                auto& comp = m_openxr.duoview_compositors[&tc->commands];'),
        ("log fallback after swapchain prewarm",
         '            log_duoview_compose_sharing(this->duoview_compositors);',
         '            for (const auto& [commands, comp] : this->duoview_compositors) {\n'
         '                if (comp && !comp->b40_warning().empty()) spdlog::warn("[DuoView][B40] Seam unavailable: {}",comp->b40_warning());\n'
         '            }\n'
         '            log_duoview_compose_sharing(this->duoview_compositors);'),
        ("activation queue history before slots",
         '            const bool srgb = false; // Existing Joey BGRA8 UNORM render source.\n'
         '            uint32_t prepared = 0;',
         '            const bool srgb = false; // Existing Joey BGRA8 UNORM render source.\n'
         '            // Allocate once on the real XR submission queue; never on a live copy.\n'
         '            if (auto queue=g_framework->get_d3d12_hook()->get_command_queue(); queue) {\n'
         '                if (!m_openxr.duoview_b40_history ||\n'
         '                    m_openxr.duoview_b40_history->device.Get()!=device ||\n'
         '                    m_openxr.duoview_b40_history->queue.Get()!=queue)\n'
         '                    m_openxr.duoview_b40_history=uevr::duoview::dx12::B40MonoHistory::create(device,queue);\n'
         '            }\n'
         '            uint32_t prepared = 0;'),
        ("activation pass shared state to slots",
         '                if (comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), srgb, frequency))\n'
         '                    ++prepared;',
         '                if (comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), srgb, frequency)) {\n'
         '                    comp->set_b40_history(m_openxr.duoview_b40_history);\n'
         '                    if (!comp->b40_warning().empty()) spdlog::warn("[DuoView][B40] Seam unavailable: {}",comp->b40_warning());\n'
         '                    ++prepared;\n'
         '                }'),
        ("retire history only after all command slots",
         '    vr->get_openxr_runtime()->invalidate_duoview_scene();\n'
         '    this->duoview_compositors.clear();',
         '    vr->get_openxr_runtime()->invalidate_duoview_scene();\n'
         '    this->duoview_compositors.clear();\n'
         '    this->duoview_b40_history.reset(); // command slots and their GPU refs already retired'),
        ("create swapchain history on actual queue",
         '            for (auto& tc : duo_ctx.texture_contexts) {',
         '            if (auto queue=g_framework->get_d3d12_hook()->get_command_queue(); queue) {\n'
         '                if (!this->duoview_b40_history ||\n'
         '                    this->duoview_b40_history->device.Get()!=device ||\n'
         '                    this->duoview_b40_history->queue.Get()!=queue)\n'
         '                    this->duoview_b40_history=uevr::duoview::dx12::B40MonoHistory::create(device,queue);\n'
         '            }\n'
         '            for (auto& tc : duo_ctx.texture_contexts) {'),
        ("pass shared history in swapchain prewarm",
         '                if (!comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), duo_srgb, duo_frequency)) {\n'
         '                    SPDLOG_WARNING_EVERY_N_SEC(2,',
         '                if (!comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), duo_srgb, duo_frequency)) {\n'
         '                    SPDLOG_WARNING_EVERY_N_SEC(2,'),
        ("bind shared history before swapchain prewarm",
         '                if (!comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), duo_srgb, duo_frequency)) {',
         '                comp->set_b40_history(this->duoview_b40_history);\n'
         '                if (!comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), duo_srgb, duo_frequency)) {'),
        ("enforce queue identity in live callback (never alloc)",
         '                                    auto& compositor = *found->second;\n'
         '                                    recorded = compositor.record_native(device, commands.cmd_list.Get(),',
         '                                    if (!commands.references_retired()) return;\n'
         '                                    auto& compositor = *found->second;\n'
         '                                    const auto current_queue=g_framework->get_d3d12_hook()->get_command_queue();\n'
         '                                    const bool queue_pinned=current_queue && m_openxr.duoview_b40_history &&\n'
         '                                        m_openxr.duoview_b40_history->device.Get()==device &&\n'
         '                                        m_openxr.duoview_b40_history->queue.Get()==current_queue;\n'
         '                                    // Fail closed if the queue changes; never share history across queues.\n'
         '                                    compositor.set_b40_history(queue_pinned ? m_openxr.duoview_b40_history : nullptr);\n'
         '                                    if (queue_pinned) commands.seam_submission_queue=current_queue;\n'
         '                                    recorded = compositor.record_native(device, commands.cmd_list.Get(),'),
    ])
    print("B40 queue-owned GPU history/PSOs/compute + Native/gather command slots patched; mode7 untouched")

if __name__=="__main__":
    main()

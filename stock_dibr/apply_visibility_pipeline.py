"""Guarded R7 visibility GPU integration; apply after R7 visibility shader.

Every anchor is checked before either generated backend file is written.
The R5 recording transaction still opens only after all allocations and views.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
changes = {}


def require(path, anchor):
    text = changes.get(path, (root / path).read_text(encoding="utf-8"))
    if text.count(anchor) != 1:
        raise RuntimeError(f"{path}: expected one R7 pipeline prerequisite, found {text.count(anchor)}: {anchor[:100]}")


def edit(path, old, new):
    require(path, old)
    text = changes.get(path, (root / path).read_text(encoding="utf-8"))
    changes[path] = text.replace(old, new)


h = "src/mods/vr/d3d12/DIBRPreview.hpp"
c = "src/mods/vr/d3d12/DIBRPreview.cpp"
# The shader stage owns the shared 256-byte constants layout and selector.
require(h, "        float depth_repair_threshold{};\n        uint32_t reconstruction_mode{};")
require(c, "void ClearVisibility(")
require(c, "void ScatterDepth(")
require(c, "void ScatterSource(")

edit(h, "    Microsoft::WRL::ComPtr<ID3D12PipelineState> m_pipeline_state{};", """    Microsoft::WRL::ComPtr<ID3D12PipelineState> m_pipeline_state{};
    Microsoft::WRL::ComPtr<ID3D12PipelineState> m_visibility_clear_pipeline{};
    Microsoft::WRL::ComPtr<ID3D12PipelineState> m_visibility_depth_pipeline{};
    Microsoft::WRL::ComPtr<ID3D12PipelineState> m_visibility_source_pipeline{};
    // Per frame slot, eye-sized, permanently in UNORDERED_ACCESS state.
    ComPtr m_visibility_depth{};
    ComPtr m_visibility_source{};
    std::string m_visibility_failure_reason{};""")
edit(h, "    bool ensure_output(ID3D12Device* device, uint32_t width, uint32_t height, DXGI_FORMAT format);", """    bool ensure_output(ID3D12Device* device, uint32_t width, uint32_t height, DXGI_FORMAT format);
    bool ensure_visibility(ID3D12Device* device, uint32_t width, uint32_t height);""")
edit(h, "    std::string failure_reason() const;", """    std::string failure_reason() const;
    std::string visibility_failure_reason() const {
        std::scoped_lock lock{m_status_mutex};
        return m_visibility_failure_reason;
    }""")
edit(c, "        m_failure_reason.clear();\n        m_traced_depth_resources.clear();", """        m_failure_reason.clear();
        m_visibility_failure_reason.clear();
        m_traced_depth_resources.clear();""")
edit(c, "    m_output.reset();\n    m_source_staging.Reset();", """    m_output.reset();
    m_visibility_depth.Reset();
    m_visibility_source.Reset();
    m_source_staging.Reset();""")
edit(c, "    m_pipeline_state.Reset();\n    m_root_signature.Reset();", """    m_pipeline_state.Reset();
    m_visibility_clear_pipeline.Reset();
    m_visibility_depth_pipeline.Reset();
    m_visibility_source_pipeline.Reset();
    m_root_signature.Reset();""")
edit(c, "    retain_untracked_com_object(m_pipeline_state.Get());", """    retain_untracked_com_object(m_pipeline_state.Get());
    retain_untracked_com_object(m_visibility_clear_pipeline.Get());
    retain_untracked_com_object(m_visibility_depth_pipeline.Get());
    retain_untracked_com_object(m_visibility_source_pipeline.Get());
    retain_untracked_com_object(m_visibility_depth.Get());
    retain_untracked_com_object(m_visibility_source.Get());""")
edit(c, "    descriptor_ranges[1].NumDescriptors = 1;", "    descriptor_ranges[1].NumDescriptors = 3;")
edit(c, "    heap_desc.NumDescriptors = 4;", "    heap_desc.NumDescriptors = 6;")
edit(c, "    m_output.reset();\n    m_output_width = 0;", """    m_output.reset();
    m_visibility_depth.Reset();
    m_visibility_source.Reset();
    m_output_width = 0;""")
edit(c, "bool DIBRPreview::ensure_output(ID3D12Device* device, uint32_t width, uint32_t height, DXGI_FORMAT format) {", """bool DIBRPreview::ensure_visibility(ID3D12Device* device, uint32_t width, uint32_t height) {
    // This optional preparation never changes preview Status or invalidates
    // the working R6 pipeline/output. Cache failures until reset, so a failing
    // driver or allocation is not retried every frame.
    if (!visibility_failure_reason().empty()) return false;
    if (m_visibility_depth != nullptr && m_visibility_source != nullptr &&
        m_visibility_clear_pipeline != nullptr && m_visibility_depth_pipeline != nullptr &&
        m_visibility_source_pipeline != nullptr) return true;
    const auto unavailable = [&](std::string reason) {
        {
            std::scoped_lock lock{m_status_mutex};
            m_visibility_failure_reason = reason;
        }
        SPDLOG_WARN("[DIBR] Forward visibility unavailable; using legacy R6 reconstruction: {}", reason);
        return false;
    };
    D3D12_FEATURE_DATA_FORMAT_SUPPORT support{};
    support.Format = DXGI_FORMAT_R32_UINT;
    const auto required = D3D12_FORMAT_SUPPORT2_UAV_TYPED_LOAD | D3D12_FORMAT_SUPPORT2_UAV_TYPED_STORE |
        D3D12_FORMAT_SUPPORT2_UAV_ATOMIC_UNSIGNED_MIN_OR_MAX;
    if (width < 2 || (width & 1u) != 0 || height == 0 ||
        FAILED(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &support, sizeof(support))) ||
        (support.Support2 & required) != required) {
        return unavailable("R32_UINT typed UAV/unsigned min-max atomics or eye extent unsupported");
    }
    const auto create_pipeline = [&](const char* entry, Microsoft::WRL::ComPtr<ID3D12PipelineState>& result) {
        if (result != nullptr) return true;
        Microsoft::WRL::ComPtr<ID3DBlob> shader{};
        Microsoft::WRL::ComPtr<ID3DBlob> errors{};
        const auto hr = D3DCompile(DIBR_PREVIEW_SHADER, strlen(DIBR_PREVIEW_SHADER), "UEVR_DIBRPreview",
            nullptr, nullptr, entry, "cs_5_0", D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_OPTIMIZATION_LEVEL3,
            0, &shader, &errors);
        if (FAILED(hr) || shader == nullptr)
            return unavailable(std::string("shader compilation (") + entry + "): " + shader_error_text(errors.Get(), hr));
        D3D12_COMPUTE_PIPELINE_STATE_DESC desc{};
        desc.pRootSignature = m_root_signature.Get();
        desc.CS = {shader->GetBufferPointer(), shader->GetBufferSize()};
        if (FAILED(device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&result))))
            return unavailable(std::string("compute pipeline creation: ") + entry);
        return true;
    };
    if (!create_pipeline("ClearVisibility", m_visibility_clear_pipeline) ||
        !create_pipeline("ScatterDepth", m_visibility_depth_pipeline) ||
        !create_pipeline("ScatterSource", m_visibility_source_pipeline)) return false;
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = width / 2;
    desc.Height = height;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.Format = DXGI_FORMAT_R32_UINT;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
    desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
    ComPtr depth{};
    ComPtr source{};
    if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS, nullptr, IID_PPV_ARGS(&depth))) ||
        FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS, nullptr, IID_PPV_ARGS(&source))))
        return unavailable("eye-sized R32_UINT scratch allocation failed");
    depth->SetName(L"DIBR Visibility Depth");
    source->SetName(L"DIBR Visibility Source");
    m_visibility_depth = std::move(depth);
    m_visibility_source = std::move(source);
    return true;
}

bool DIBRPreview::ensure_output(ID3D12Device* device, uint32_t width, uint32_t height, DXGI_FORMAT format) {""")
edit(c, "    if (!ensure_output(device, output_width, output_height, output_format) ||\n        !create_descriptors(device, depth, use_ui_alpha ? ui_alpha : nullptr)) {", """    if (!ensure_output(device, output_width, output_height, output_format)) return false;
    const auto prepared_inspector = (std::min)(parameters.inspector_view, 6u);
    const auto visibility_requested = parameters.reconstruction_mode != 0 && parameters.use_true_reprojection &&
        (prepared_inspector == 0 || prepared_inspector == 6);
    if (visibility_requested && !ensure_visibility(device, output_width, output_height)) {
        // Parameters is a value copy; constants and dispatch must agree on the
        // effective mode, while the user's saved requested mode stays intact.
        parameters.reconstruction_mode = 0;
    }
    if (!create_descriptors(device, depth, use_ui_alpha ? ui_alpha : nullptr)) {""")
edit(c, "    device->CreateUnorderedAccessView(m_output.texture.Get(), nullptr, &output_uav, cpu);\n    return true;", """    device->CreateUnorderedAccessView(m_output.texture.Get(), nullptr, &output_uav, cpu);
    D3D12_UNORDERED_ACCESS_VIEW_DESC visibility_uav{};
    visibility_uav.Format = DXGI_FORMAT_R32_UINT;
    visibility_uav.ViewDimension = D3D12_UAV_DIMENSION_TEXTURE2D;
    cpu.ptr += m_descriptor_increment;
    device->CreateUnorderedAccessView(m_visibility_depth.Get(), nullptr, &visibility_uav, cpu);
    cpu.ptr += m_descriptor_increment;
    device->CreateUnorderedAccessView(m_visibility_source.Get(), nullptr, &visibility_uav, cpu);
    return true;""")
edit(c, "    command_list->SetComputeRootConstantBufferView(2, m_constants->GetGPUVirtualAddress());\n    command_list->Dispatch((output_width + 7) / 8, (output_height + 7) / 8, 1);", """    command_list->SetComputeRootConstantBufferView(2, m_constants->GetGPUVirtualAddress());
    const auto use_visibility = parameters.reconstruction_mode != 0 && parameters.use_true_reprojection &&
        (constants.inspector_view == 0 || constants.inspector_view == 6);
    if (use_visibility) {
        // Both scratch UAVs stay in UAV state for their entire lifetime. A
        // global UAV barrier orders both resources between these dependent passes.
        D3D12_RESOURCE_BARRIER visibility_barrier{};
        visibility_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_UAV;
        visibility_barrier.UAV.pResource = nullptr;
        const auto groups_x = (m_source_staging_width + 7) / 8;
        const auto groups_y = (output_height + 7) / 8;
        command_list->SetPipelineState(m_visibility_clear_pipeline.Get());
        command_list->Dispatch(groups_x, groups_y, 1);
        command_list->ResourceBarrier(1, &visibility_barrier);
        command_list->SetPipelineState(m_visibility_depth_pipeline.Get());
        command_list->Dispatch(groups_x, groups_y, 1);
        command_list->ResourceBarrier(1, &visibility_barrier);
        command_list->SetPipelineState(m_visibility_source_pipeline.Get());
        command_list->Dispatch(groups_x, groups_y, 1);
        command_list->ResourceBarrier(1, &visibility_barrier);
        command_list->SetPipelineState(m_pipeline_state.Get());
    }
    command_list->Dispatch((output_width + 7) / 8, (output_height + 7) / 8, 1);""")

for path, text in changes.items():
    (root / path).write_text(text, encoding="utf-8")
print("R7 visibility GPU pipeline overlay applied:", ", ".join(changes))

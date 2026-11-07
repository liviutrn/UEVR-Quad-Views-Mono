#pragma once

#include <d3d12.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include "QuadViewGeometry.hpp"
#include "QuadViewSettings.hpp"
#include "QuadViewSnapshot.hpp"
#include "QuadViewShaderBytecode.hpp"
#include <array>
#include <atomic>
#include <cmath>
#include <cstring>
#include <memory>
#include <utility>
#include <chrono>
#include <ctime>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace uevr::quadview::dx12 {

using Microsoft::WRL::ComPtr;

inline std::atomic<float>& last_seam_analysis_milliseconds() {
    static std::atomic<float> value{-1.f};
    return value;
}

struct alignas(16) ShaderConstants {
    uint32_t eye_and_atlas[4]{};
    uint32_t rectangles[4][4]{};
    float crops[2][4]{};
    float options[4]{};
    float sharpen[4]{};
    float sharpen_eye[4]{}; // left/right strength, left/right change limiter
    float context_h[2][12]{{1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f},
                           {1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f}};
    uint32_t context_source[4]{0, 1, 0, 0};
    float depth_shift[4]{};     // B7
    uint32_t depth_rect[4]{};   // B7
    uint32_t depth_options[4]{}; // B7
    float depth_eye_origin[2][4]{};
    float depth_projection[4]{};
    float depth_coefficients[4]{};
    float depth_jitter[4]{};
    float seam[4]{};
    float seam_options[4]{};
    float seam_local[4]{};
    float focus_lift[4]{};
    float focus_profile[4]{};
};
static_assert(sizeof(ShaderConstants) == 480);
static_assert(sizeof(ShaderConstants) <= 512); // slot-local, CB-aligned allocation

// B7: optional periphery depth for reprojection. texture is R32_TYPELESS and
// stays in D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE between uses.

struct SnapshotItem {
    Microsoft::WRL::ComPtr<ID3D12Resource> buffer;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT rows{};
    UINT64 row_bytes{};
    std::string name;
};

// Concrete DXGI format for a viewer (typeless -> the view format we sample with).
inline DXGI_FORMAT snapshot_file_format(DXGI_FORMAT f) {
    switch (f) {
    case DXGI_FORMAT_R8G8B8A8_TYPELESS: return DXGI_FORMAT_R8G8B8A8_UNORM;
    case DXGI_FORMAT_B8G8R8A8_TYPELESS: return DXGI_FORMAT_B8G8R8A8_UNORM;
    case DXGI_FORMAT_R10G10B10A2_TYPELESS: return DXGI_FORMAT_R10G10B10A2_UNORM;
    case DXGI_FORMAT_R16G16B16A16_TYPELESS: return DXGI_FORMAT_R16G16B16A16_FLOAT;
    case DXGI_FORMAT_R32_TYPELESS: return DXGI_FORMAT_R32_FLOAT;
    default: return f;
    }
}

inline bool write_snapshot_dds(const std::filesystem::path& file, const SnapshotItem& item) {
    void* data{};
    const UINT64 wanted = item.footprint.Offset + UINT64(item.footprint.Footprint.RowPitch) * (item.rows ? item.rows - 1 : 0) + item.row_bytes;
    const D3D12_RANGE range{0, SIZE_T((std::min)(wanted, item.buffer->GetDesc().Width))};
    if (FAILED(item.buffer->Map(0, &range, &data)) || !data) return false;
    std::ofstream out(file, std::ios::binary);
    uint32_t header[32]{};
    header[0] = 124; header[1] = 0x1 | 0x2 | 0x4 | 0x8 | 0x1000; // caps|height|width|pitch|pixelformat
    header[2] = item.footprint.Footprint.Height; header[3] = item.footprint.Footprint.Width;
    header[4] = uint32_t(item.row_bytes);
    header[18] = 32; header[19] = 0x4; header[20] = 0x30315844; // DDPF_FOURCC 'DX10'
    header[26] = 0x1000;
    const uint32_t dx10[5]{uint32_t(snapshot_file_format(item.footprint.Footprint.Format)), 3u, 0u, 1u, 0u};
    out.write("DDS ", 4);
    out.write(reinterpret_cast<const char*>(header), 124);
    out.write(reinterpret_cast<const char*>(dx10), sizeof(dx10));
    const auto* bytes = static_cast<const char*>(data) + item.footprint.Offset;
    for (UINT row = 0; row < item.rows; ++row)
        out.write(bytes + UINT64(row) * item.footprint.Footprint.RowPitch, std::streamsize(item.row_bytes));
    const D3D12_RANGE no_write{0, 0};
    item.buffer->Unmap(0, &no_write);
    return bool(out);
}

struct DepthInput {
    ID3D12Resource* texture{};
    DXGI_FORMAT srv_format{DXGI_FORMAT_R32_FLOAT}; // R32_FLOAT or R32_FLOAT_X8X24_TYPELESS
    uint32_t rect[4]{};
    float shift[4]{};
    bool reproject{}, show{};
    // Offset from unjittered context color UV to the matching depth sample UV.
    // Capture must provide the NGX jitter sign/normalization; unknown disables warp.
    float jitter_uv[2]{};
    bool jitter_valid{};
    std::shared_ptr<const void> keepalive{};
};

// Each instance belongs to one fence-retired OpenXR command slot. Descriptor
// and upload storage cannot be reused until the owning slot's fence retires.
class Compositor {
public:
    Compositor() = default;
    Compositor(const Compositor&) = delete;
    Compositor& operator=(const Compositor&) = delete;
    ~Compositor() { if (constants_ && mapped_) constants_->Unmap(0, nullptr); }

    static DXGI_FORMAT sampling_format(DXGI_FORMAT format) {
        switch (format) {
        case DXGI_FORMAT_R8G8B8A8_TYPELESS: return DXGI_FORMAT_R8G8B8A8_UNORM;
        case DXGI_FORMAT_B8G8R8A8_TYPELESS: return DXGI_FORMAT_B8G8R8A8_UNORM;
        case DXGI_FORMAT_R10G10B10A2_TYPELESS: return DXGI_FORMAT_R10G10B10A2_UNORM;
        case DXGI_FORMAT_R16G16B16A16_TYPELESS: return DXGI_FORMAT_R16G16B16A16_FLOAT;
        default: return format;
        }
    }

    const char* error() const { return error_; }
    bool prepared() const { return device_ && root_ && pipeline_ && seam_pipeline_ && seam_stats_ && mapped_; }
    bool commands_recorded() const { return recorded_; }

    bool prewarm(ID3D12Device* device, DXGI_FORMAT source_srv_format, DXGI_FORMAT output_format,
                 UINT64 timestamp_frequency = 0) {
        if (!device || source_srv_format == DXGI_FORMAT_UNKNOWN || output_format == DXGI_FORMAT_UNKNOWN)
            return fail("Invalid prewarm device or formats");
        if (owner_) return fail("Cannot recreate an in-flight compositor");
        if (prepared() && device_.Get() == device && source_format_ == source_srv_format && output_format_ == output_format) {
            setup_timing(device,timestamp_frequency);
            return true;
        }
        if (mapped_ && constants_) constants_->Unmap(0, nullptr);
        mapped_ = nullptr;
        constants_.Reset(); root_.Reset(); pipeline_.Reset(); srv_heap_.Reset(); rtv_heap_.Reset();
        seam_pipeline_.Reset(); seam_stats_.Reset();
        queries_.Reset(); timestamps_.Reset(); frequency_=0; timing_pending_=false; gpu_ms_=-1.f; seam_gpu_ms_=-1.f; timed_seam_active_=false;
        device_ = device;
        source_format_ = source_srv_format;
        output_format_ = output_format;

        D3D12_FEATURE_DATA_FORMAT_SUPPORT source_support{source_srv_format};
        D3D12_FEATURE_DATA_FORMAT_SUPPORT output_support{output_format};
        if (FAILED(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &source_support, sizeof(source_support))) ||
            FAILED(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &output_support, sizeof(output_support))) ||
            !(source_support.Support1 & D3D12_FORMAT_SUPPORT1_SHADER_SAMPLE) ||
            !(output_support.Support1 & D3D12_FORMAT_SUPPORT1_RENDER_TARGET))
            return fail("Unsupported source sampling or output render-target format");

        D3D12_DESCRIPTOR_RANGE range{};
        range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        range.NumDescriptors = 6; // 4 colors, depth, seam gain/confidence
        D3D12_DESCRIPTOR_RANGE seam_uav{};
        seam_uav.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
        seam_uav.NumDescriptors = 1;
        D3D12_ROOT_PARAMETER parameters[3]{};
        parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
        parameters[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        parameters[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        parameters[1].DescriptorTable.NumDescriptorRanges = 1;
        parameters[1].DescriptorTable.pDescriptorRanges = &range;
        parameters[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        parameters[2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        parameters[2].DescriptorTable.NumDescriptorRanges = 1;
        parameters[2].DescriptorTable.pDescriptorRanges = &seam_uav;
        parameters[2].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        D3D12_STATIC_SAMPLER_DESC sampler{};
        sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
        sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
        sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        sampler.MaxAnisotropy = 1;
        sampler.MaxLOD = D3D12_FLOAT32_MAX;
        sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        D3D12_ROOT_SIGNATURE_DESC signature{};
        signature.NumParameters = 3;
        signature.pParameters = parameters;
        signature.NumStaticSamplers = 1;
        signature.pStaticSamplers = &sampler;
        signature.Flags = D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT;
        ComPtr<ID3DBlob> serialized, diagnostics;
        if (FAILED(D3D12SerializeRootSignature(&signature, D3D_ROOT_SIGNATURE_VERSION_1, &serialized, &diagnostics)) ||
            FAILED(device->CreateRootSignature(0, serialized->GetBufferPointer(), serialized->GetBufferSize(), IID_PPV_ARGS(&root_))))
            return fail("Could not create QuadView root signature");

        D3D12_GRAPHICS_PIPELINE_STATE_DESC description{};
        description.pRootSignature = root_.Get();
        description.VS = {shaders::vertex, sizeof(shaders::vertex)};
        description.PS = {shaders::pixel, sizeof(shaders::pixel)};
        auto& blend = description.BlendState.RenderTarget[0];
        blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
        blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
        blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
        blend.LogicOp = D3D12_LOGIC_OP_NOOP;
        blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
        description.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
        description.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
        description.RasterizerState.DepthClipEnable = TRUE;
        description.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ZERO;
        description.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        auto& stencil = description.DepthStencilState.FrontFace;
        stencil.StencilFailOp = stencil.StencilDepthFailOp = stencil.StencilPassOp = D3D12_STENCIL_OP_KEEP;
        stencil.StencilFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        description.DepthStencilState.BackFace = stencil;
        description.SampleMask = UINT32_MAX;
        description.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        description.NumRenderTargets = 1;
        description.RTVFormats[0] = output_format;
        description.SampleDesc.Count = 1;
        if (FAILED(device->CreateGraphicsPipelineState(&description, IID_PPV_ARGS(&pipeline_))))
            return fail("Could not create QuadView raster pipeline");
        D3D12_COMPUTE_PIPELINE_STATE_DESC analysis{};
        analysis.pRootSignature = root_.Get();
        analysis.CS = {shaders::seam, sizeof(shaders::seam)};
        if (FAILED(device->CreateComputePipelineState(&analysis, IID_PPV_ARGS(&seam_pipeline_))))
            return fail("Could not create QuadView seam analysis pipeline");

        D3D12_DESCRIPTOR_HEAP_DESC heap{};
        heap.NumDescriptors = 7; // six SRVs followed by one seam UAV
        heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        if (FAILED(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&srv_heap_)))) return fail("Could not create QuadView SRV heap");
        heap.NumDescriptors = 1;
        heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
        if (FAILED(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&rtv_heap_)))) return fail("Could not create QuadView RTV heap");
        D3D12_HEAP_PROPERTIES upload{};
        upload.Type = D3D12_HEAP_TYPE_UPLOAD;
        upload.CreationNodeMask = upload.VisibleNodeMask = 1;
        D3D12_RESOURCE_DESC buffer{};
        buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width = 512;
        buffer.Height = buffer.DepthOrArraySize = buffer.MipLevels = 1;
        buffer.SampleDesc.Count = 1;
        buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(device->CreateCommittedResource(&upload, D3D12_HEAP_FLAG_NONE, &buffer,
            D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&constants_)))) return fail("Could not create QuadView constants");
        D3D12_HEAP_PROPERTIES gpu{};
        gpu.Type = D3D12_HEAP_TYPE_DEFAULT;
        gpu.CreationNodeMask = gpu.VisibleNodeMask = 1;
        buffer.Width = 18 * 4 * sizeof(float);
        buffer.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        if (FAILED(device->CreateCommittedResource(&gpu, D3D12_HEAP_FLAG_NONE, &buffer,
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, nullptr, IID_PPV_ARGS(&seam_stats_))))
            return fail("Could not create QuadView slot-local seam statistics");
        D3D12_SHADER_RESOURCE_VIEW_DESC match_srv{};
        match_srv.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
        match_srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        match_srv.Buffer.NumElements = 18;
        match_srv.Buffer.StructureByteStride = 4 * sizeof(float);
        const auto descriptor_stride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        auto match_descriptor = srv_heap_->GetCPUDescriptorHandleForHeapStart();
        match_descriptor.ptr += SIZE_T(5) * descriptor_stride;
        device->CreateShaderResourceView(seam_stats_.Get(), &match_srv, match_descriptor);
        match_descriptor.ptr += descriptor_stride;
        D3D12_UNORDERED_ACCESS_VIEW_DESC match_uav{};
        match_uav.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        match_uav.Buffer.NumElements = 18;
        match_uav.Buffer.StructureByteStride = 4 * sizeof(float);
        device->CreateUnorderedAccessView(seam_stats_.Get(), nullptr, &match_uav, match_descriptor);
        D3D12_RANGE no_read{0, 0};
        if (FAILED(constants_->Map(0, &no_read, &mapped_))) return fail("Could not map QuadView constants");
        constants_->SetName(L"QuadView slot constants");
        seam_stats_->SetName(L"QuadView slot seam gain and confidence");
        root_->SetName(L"QuadView root signature");
        pipeline_->SetName(L"QuadView stereo raster pipeline");
        srv_heap_->SetName(L"QuadView slot SRV");
        rtv_heap_->SetName(L"QuadView slot RTV");
        setup_timing(device,timestamp_frequency);
        error_ = "";
        return true;
    }

    void on_slot_retired() {
        // Call only after the owning command-context fence proves every query
        // and resource reference in this slot has completed.
        read_timing();
        flush_snapshot();
        owner_.reset();
        depth_keepalive_.reset();
        for (auto& source : sources_) source.Reset();
        destination_.Reset();
        recorded_ = false;
    }
    float gpu_milliseconds() const { return gpu_ms_; }
    float seam_gpu_milliseconds() const { return seam_gpu_ms_; }
    UINT64 timing_frequency() const { return frequency_; }
    bool timing_ready() const { return queries_ && timestamps_ && frequency_; }

    bool record(ID3D12GraphicsCommandList* commands, ID3D12Resource* source, ID3D12Resource* destination,
                const Layout& layout, const Settings& settings,
                D3D12_RESOURCE_STATES source_state, D3D12_RESOURCE_STATES destination_state,
                std::shared_ptr<const void> owner, UINT64 timestamp_frequency = 0) {
        return record_sources(commands, {source, source, source, source}, destination, layout, settings,
            source_state, destination_state, std::move(owner), timestamp_frequency);
    }

    bool record_sources(ID3D12GraphicsCommandList* commands,
                const std::array<ID3D12Resource*, 4>& sources, ID3D12Resource* destination,
                const Layout& layout, const Settings& settings,
                D3D12_RESOURCE_STATES source_state, D3D12_RESOURCE_STATES destination_state,
                std::shared_ptr<const void> owner, UINT64 timestamp_frequency = 0,
                const DepthInput* depth = nullptr) {
        recorded_ = false;
        if (!prepared() || !commands || !destination || !sources[0] || !sources[1] || !sources[2] || !sources[3] || !owner)
            return fail("Unprepared compositor or invalid source/destination ownership");
        if (owner_) return fail("Compositor command slot has not retired");
        if (timing_pending_) return fail("Previous timestamp query has not retired");
        const auto checked_settings = reconcile_settings(settings, settings,
            layout.eye_width,layout.eye_height);
        if (!valid_layout(layout) || checked_settings.rejected || !same_settings(checked_settings.settings, settings))
            return fail("Invalid QuadView layout or debug controls");
        const auto output = destination->GetDesc();
        // B6: compact sources have per-role extents; atlas layouts keep 2W x H for all four.
        const auto extents = source_extents(layout);
        for (size_t index = 0; index != sources.size(); ++index) {
            auto* source = sources[index];
            if (source == destination) return fail("Source aliases the compositor destination");
            const auto input = source->GetDesc();
            if (input.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || output.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
                input.Width != extents[index][0] || input.Height != extents[index][1] ||
                output.Width != layout.eye_width * 2ull || output.Height != layout.eye_height ||
                input.SampleDesc.Count != 1 || output.SampleDesc.Count != 1 ||
                input.DepthOrArraySize != 1 || output.DepthOrArraySize != 1 ||
                (input.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
                !(output.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) || !compatible_source(output.Format, output_format_) ||
                !compatible_source(input.Format, source_format_)) return fail("Source or destination texture does not match prepared QuadView layout/formats");
        }

        ShaderConstants constants{};
        constants.eye_and_atlas[0] = layout.eye_width; constants.eye_and_atlas[1] = layout.eye_height;
        constants.eye_and_atlas[2] = layout.atlas_width; constants.eye_and_atlas[3] = layout.atlas_height;
        for (unsigned view = 0; view < 4; ++view) {
            // Tri-view: both eyes read the one shared centre context (view 0).
            const auto& rect = layout.views[view == 1 && layout.shared_context ? 0 : view];
            constants.rectangles[view][0] = rect.x; constants.rectangles[view][1] = rect.y;
            constants.rectangles[view][2] = rect.width; constants.rectangles[view][3] = rect.height;
        }
        for (unsigned eye = 0; eye != 2; ++eye) {
            const auto& crop = layout.focus_crops[eye];
            constants.crops[eye][0] = crop.u0; constants.crops[eye][1] = crop.v0;
            constants.crops[eye][2] = crop.u1; constants.crops[eye][3] = crop.v1;
        }
        for (unsigned eye = 0; eye != 2; ++eye)
            for (unsigned i = 0; i != 12; ++i) constants.context_h[eye][i] = layout.context_h[eye][i];
        constants.context_source[1] = layout.shared_context ? 0u : 1u;
        constants.options[0] = settings.feather_fraction;
        constants.options[1] = static_cast<float>(settings.diagnostic_view);
        const bool output_srgb = output_format_ == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
                                 output_format_ == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
        const bool encoded_unorm = source_format_ == DXGI_FORMAT_B8G8R8A8_UNORM ||
                                   source_format_ == DXGI_FORMAT_R8G8B8A8_UNORM;
        constants.options[2] = output_srgb && encoded_unorm ? 1.f : 0.f;
        constants.options[3] = settings.debug_border ? 1.f : 0.f;
        constants.sharpen[0] = settings.sharpen_strength;
        constants.sharpen[1] = 1.f + 2.f + (encoded_unorm ? 4.f : 0.f);
        constants.sharpen[2] = .10f;
        constants.sharpen[3] = .02f;
        // B8: initial stereo-matched defaults for portable compositor tests.
        // The post-B7 B8 backend patch replaces these with independent saved eye settings.
        constants.sharpen_eye[0] = settings.sharpen_strength;
        constants.sharpen_eye[1] = settings.sharpen_strength;
        constants.sharpen_eye[2] = .10f;
        constants.sharpen_eye[3] = .10f;
        // Requested and bound are independent: missing/invalid depth must still
        // produce the explicit diagnostic, including non-shared layouts.
        constants.depth_options[1] = depth && depth->show ? 1u : 0u;
        bool depth_bound = false;
        if (depth && (depth->reproject || depth->show) && !depth->texture) last_depth_state().store(3u, std::memory_order_relaxed);
        if (depth && depth->texture && layout.shared_context && (depth->reproject || depth->show)) {
            const auto d = depth->texture->GetDesc();
            const bool finite = std::isfinite(depth->shift[0]) && std::isfinite(depth->shift[1]) &&
                std::isfinite(depth->shift[2]) && std::isfinite(depth->shift[3]);
            const bool format_ok = (d.Format == DXGI_FORMAT_R32_TYPELESS && depth->srv_format == DXGI_FORMAT_R32_FLOAT) ||
                (d.Format == DXGI_FORMAT_R32G8X24_TYPELESS && depth->srv_format == DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS);
            if (d.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && format_ok &&
                depth->rect[2] && depth->rect[3] && finite &&
                uint64_t(depth->rect[0]) + depth->rect[2] <= d.Width && uint64_t(depth->rect[1]) + depth->rect[3] <= d.Height) {
                for (unsigned i = 0; i != 4; ++i) { constants.depth_shift[i] = depth->shift[i]; constants.depth_rect[i] = depth->rect[i]; }
                // B11: missing jitter is treated as zero (sub-texel error on the
                // low-resolution periphery depth) instead of silently disabling the warp.
                const bool jitter_ok=depth->jitter_valid && std::isfinite(depth->jitter_uv[0]) && std::isfinite(depth->jitter_uv[1]) &&
                    std::abs(depth->jitter_uv[0]) < 0.25f && std::abs(depth->jitter_uv[1]) < 0.25f;
                constants.depth_options[0] = depth->reproject && layout.depth_geometry_valid ? 1u : 0u;
                last_depth_state().store(!depth->reproject ? 4u : layout.depth_geometry_valid ? 1u : 2u, std::memory_order_relaxed);
                for (unsigned eye=0;eye<2;++eye) for (unsigned axis=0;axis<4;++axis)
                    constants.depth_eye_origin[eye][axis]=layout.depth_eye_origin[eye][axis];
                for (unsigned axis=0;axis<4;++axis) {
                    constants.depth_projection[axis]=layout.depth_projection[axis];
                    constants.depth_coefficients[axis]=layout.depth_coefficients[axis];
                }
                constants.depth_jitter[0]=jitter_ok ? depth->jitter_uv[0] : 0.f;
                constants.depth_jitter[1]=jitter_ok ? depth->jitter_uv[1] : 0.f;
                constants.depth_options[2] = 1u; // validated depth is bound
                depth_bound = true;
            }
        }
        constants.seam[0] = static_cast<float>(settings.seam_mode);
        constants.seam[1] = settings.seam_strength;
        constants.seam[2] = settings.seam_max_gain;
        // Approximate EV control in encoded UNORM; no per-pixel pow. Adaptive
        // estimates themselves compare/apply in the exact same sampled domain.
        constants.seam[3] = std::exp2(settings.seam_brightness_ev / (encoded_unorm ? 2.2f : 1.f));
        constants.seam_options[0] = settings.seam_color_strength;
        constants.seam_options[1] = settings.seam_transition_px;
        constants.seam_options[2] = settings.seam_debug ? 1.f : 0.f;
        constants.seam_options[3] = depth && depth->reproject && layout.shared_context &&
            !constants.depth_options[0] ? 0.f : 1.f;
        constants.seam_local[0] = settings.seam_radius_px;
        constants.seam_local[1] = settings.seam_local_strength;
        constants.focus_lift[0]=settings.focus_lift_enabled ? 1.f : 0.f;
        constants.focus_lift[1]=settings.focus_brightness;
        constants.focus_lift[2]=settings.focus_corner_gain-1.f;
        constants.focus_lift[3]=settings.focus_lift_onset;
        constants.focus_profile[0]=settings.focus_lift_power;
        constants.focus_profile[1]=settings.focus_lift_strength;
        std::memcpy(mapped_, &constants, sizeof(constants));
        D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
        srv.Format = source_format_;
        srv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
        srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        srv.Texture2D.MipLevels = 1;
        // Tri-view never renders source 1: alias its slot to source 0 so it is
        // neither sampled nor transitioned from a state it may not be in.
        auto active = sources;
        if (layout.shared_context) active[1] = sources[0];
        auto descriptor = srv_heap_->GetCPUDescriptorHandleForHeapStart();
        const auto stride = device_->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        for (auto* source : active) {
            device_->CreateShaderResourceView(source, &srv, descriptor);
            descriptor.ptr += stride;
        }
        D3D12_SHADER_RESOURCE_VIEW_DESC depth_srv = srv;
        depth_srv.Format = depth_bound ? depth->srv_format : DXGI_FORMAT_R32_FLOAT;
        depth_srv.Texture2D.PlaneSlice = 0;
        device_->CreateShaderResourceView(depth_bound ? depth->texture : nullptr, &depth_srv, descriptor);
        depth_keepalive_ = depth_bound ? depth->keepalive : nullptr;
        D3D12_RENDER_TARGET_VIEW_DESC rtv_description{};
        rtv_description.Format = output_format_;
        rtv_description.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
        const auto rtv = rtv_heap_->GetCPUDescriptorHandleForHeapStart();
        device_->CreateRenderTargetView(destination, &rtv_description, rtv);
        owner_ = std::move(owner);
        for (size_t i = 0; i != 4; ++i) sources_[i] = sources[i];
        destination_ = destination;
        // Strength zero is visually neutral; skip statistics work unless the
        // confidence diagnostic explicitly needs these values.
        const bool analyze = settings.seam_mode == 2 &&
            (settings.seam_strength > 0.f || settings.seam_debug) &&
            settings.diagnostic_view == 0 && !(depth && depth->show);
        const auto sample_state = analyze ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE
                                         : D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
        for (size_t i = 0; i != 4; ++i) {
            bool duplicate = false;
            for (size_t j = 0; j < i; ++j) duplicate = duplicate || active[j] == active[i];
            if (!duplicate) barrier(commands, active[i], source_state, sample_state);
        }
        barrier(commands, destination, destination_state, D3D12_RESOURCE_STATE_RENDER_TARGET);
        ID3D12DescriptorHeap* heaps[]{srv_heap_.Get()};
        commands->SetDescriptorHeaps(1, heaps);
        const bool timed=settings.gpu_timing && timestamp_frequency &&
            timestamp_frequency==frequency_ && timing_ready();
        if (timed) {
            timed_seam_active_ = analyze;
            commands->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
        }
        if (analyze) {
            barrier(commands, seam_stats_.Get(), D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
            commands->SetPipelineState(seam_pipeline_.Get());
            commands->SetComputeRootSignature(root_.Get());
            commands->SetComputeRootConstantBufferView(0, constants_->GetGPUVirtualAddress());
            commands->SetComputeRootDescriptorTable(1, srv_heap_->GetGPUDescriptorHandleForHeapStart());
            auto uav = srv_heap_->GetGPUDescriptorHandleForHeapStart();
            uav.ptr += UINT64(6) * stride;
            commands->SetComputeRootDescriptorTable(2, uav);
            commands->Dispatch(2, 1, 1);
            // The transition orders UAV writes before the pixel SRV read.
            barrier(commands, seam_stats_.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        }
        if (timed) commands->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
        commands->SetPipelineState(pipeline_.Get());
        commands->SetGraphicsRootSignature(root_.Get());
        commands->SetGraphicsRootConstantBufferView(0, constants_->GetGPUVirtualAddress());
        commands->SetGraphicsRootDescriptorTable(1, srv_heap_->GetGPUDescriptorHandleForHeapStart());
        const D3D12_VIEWPORT viewport{0, 0, static_cast<float>(layout.eye_width * 2), static_cast<float>(layout.eye_height), 0, 1};
        const D3D12_RECT scissor{0, 0, static_cast<LONG>(layout.eye_width * 2), static_cast<LONG>(layout.eye_height)};
        commands->RSSetViewports(1, &viewport);
        commands->RSSetScissorRects(1, &scissor);
        commands->OMSetRenderTargets(1, &rtv, FALSE, nullptr);
        commands->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        commands->DrawInstanced(3, 1, 0, 0);
        if (timed) {
            commands->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,2);
            commands->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,3,timestamps_.Get(),0);
            timing_pending_=true;
        }
        if (analyze) for (size_t i = 0; i != 4; ++i) {
            bool duplicate = false;
            for (size_t j = 0; j < i; ++j) duplicate = duplicate || active[j] == active[i];
            if (!duplicate) barrier(commands, active[i], sample_state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        }
        if (snapshot_.empty() && snapshot_requested().exchange(false))
            capture_snapshot(commands, active, destination, depth_bound ? depth : nullptr, layout, constants);
        for (size_t i = 0; i != 4; ++i) {
            bool duplicate = false;
            for (size_t j = 0; j < i; ++j) duplicate = duplicate || active[j] == active[i];
            if (!duplicate) barrier(commands, active[i], D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, source_state);
        }
        barrier(commands, destination, D3D12_RESOURCE_STATE_RENDER_TARGET, destination_state);
        recorded_ = true;
        error_ = "";
        return true;
    }

private:
    bool fail(const char* message) { error_ = message; return false; }

    template <typename Constants>
    void capture_snapshot(ID3D12GraphicsCommandList* commands, const std::array<ID3D12Resource*, 4>& active,
                          ID3D12Resource* destination, const DepthInput* depth, const Layout& layout, const Constants& constants) {
        struct Source { ID3D12Resource* resource; D3D12_RESOURCE_STATES state; const char* name; };
        std::vector<Source> list{{destination, D3D12_RESOURCE_STATE_RENDER_TARGET, "eyes_final"},
                                 {active[0], D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, "src0_periphery"},
                                 {active[2], D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, "src2_fovea_left"},
                                 {active[3], D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, "src3_fovea_right"}};
        if (depth && depth->texture) list.push_back({depth->texture, D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE, "periphery_depth"});
        std::ostringstream info;
        info << "TriView B11 snapshot\neye " << layout.eye_width << "x" << layout.eye_height
             << " shared_context " << layout.shared_context << " native_local " << layout.native_local
             << " context_scale " << layout.context_scale << "\n";
        for (size_t i = 0; i != 4; ++i)
            info << "view" << i << " x " << layout.views[i].x << " y " << layout.views[i].y << " w " << layout.views[i].width << " h " << layout.views[i].height << "\n";
        for (size_t e = 0; e != 2; ++e) {
            const auto& c = layout.focus_crops[e];
            info << "focus_crop" << e << " " << c.u0 << " " << c.v0 << " " << c.u1 << " " << c.v1 << "\ncontext_h" << e;
            for (float v : layout.context_h[e]) info << " " << v;
            info << "\ndepth_eye_origin" << e;
            for (float v : layout.depth_eye_origin[e]) info << " " << v;
            info << "\n";
        }
        info << "context_projection"; for (double v : layout.context_projection) info << " " << v;
        info << "\ndepth_geometry_valid " << layout.depth_geometry_valid << "\ndepth_projection";
        for (float v : layout.depth_projection) info << " " << v;
        info << "\ndepth_coefficients"; for (float v : layout.depth_coefficients) info << " " << v;
        info << "\nshader depth_options"; for (auto v : constants.depth_options) info << " " << v;
        info << "\nshader depth_rect"; for (auto v : constants.depth_rect) info << " " << v;
        info << "\nshader depth_jitter"; for (auto v : constants.depth_jitter) info << " " << v;
        info << "\nsource_format " << int(source_format_) << " output_format " << int(output_format_) << "\n";
        D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_READBACK; heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        std::vector<SnapshotItem> items;
        for (const auto& source : list) {
            if (!source.resource) continue;
            const auto desc = source.resource->GetDesc();
            SnapshotItem item{}; UINT64 total{};
            device_->GetCopyableFootprints(&desc, 0, 1, 0, &item.footprint, &item.rows, &item.row_bytes, &total);
            if (!total || total > (UINT64(1) << 31)) continue;
            D3D12_RESOURCE_DESC buffer{};
            buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; buffer.Width = total;
            buffer.Height = buffer.DepthOrArraySize = buffer.MipLevels = 1; buffer.SampleDesc.Count = 1;
            buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
            if (FAILED(device_->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer, D3D12_RESOURCE_STATE_COPY_DEST,
                    nullptr, IID_PPV_ARGS(&item.buffer)))) continue;
            item.name = source.name;
            info << source.name << " format " << int(desc.Format) << " " << desc.Width << "x" << desc.Height << "\n";
            barrier(commands, source.resource, source.state, D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION from{}, to{};
            from.pResource = source.resource; from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX; from.SubresourceIndex = 0;
            to.pResource = item.buffer.Get(); to.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; to.PlacedFootprint = item.footprint;
            commands->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
            barrier(commands, source.resource, D3D12_RESOURCE_STATE_COPY_SOURCE, source.state);
            items.push_back(std::move(item));
        }
        snapshot_ = std::move(items);
        snapshot_text_ = info.str();
    }

    // Slot retired => the readback copies completed. Files are written off-thread.
    void flush_snapshot() {
        if (snapshot_.empty()) return;
        auto items = std::move(snapshot_); snapshot_.clear();
        auto text = std::move(snapshot_text_);
        const auto dir = snapshot_directory();
        std::thread([items = std::move(items), text = std::move(text), dir]() {
            std::error_code ec;
            const auto base = dir.empty() ? std::filesystem::path{"."} : dir;
            std::filesystem::create_directories(base, ec);
            char stamp[32]{};
            const auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
            std::tm local{}; localtime_s(&local, &now);
            std::strftime(stamp, sizeof(stamp), "%Y%m%d-%H%M%S", &local);
            unsigned ok = 0;
            for (const auto& item : items) ok += write_snapshot_dds(base / (std::string("triview_") + stamp + "_" + item.name + ".dds"), item);
            std::ofstream(base / (std::string("triview_") + stamp + "_info.txt")) << text;
            snapshots_written().fetch_add(1);
            std::scoped_lock l(snapshot_mutex());
            last_snapshot_message_storage() = std::string(stamp) + ": " + std::to_string(ok) + "/" + std::to_string(items.size()) +
                " images saved to " + base.string();
        }).detach();
    }

    void read_timing() {
        if (!timing_pending_ || !timestamps_ || !frequency_) return;
        gpu_ms_=-1.f;
        seam_gpu_ms_=-1.f;
        D3D12_RANGE range{0,sizeof(UINT64)*3};
        UINT64* values{};
        if (SUCCEEDED(timestamps_->Map(0,&range,reinterpret_cast<void**>(&values)))) {
            if (values[2]>=values[1] && values[1]>=values[0]) {
                gpu_ms_=static_cast<float>(double(values[2]-values[0])*1000.0/double(frequency_));
                // No adaptive dispatch -> no seam-analysis work; ignore the
                // timestamp gap that would otherwise include setup overhead.
                seam_gpu_ms_=timed_seam_active_ ?
                    static_cast<float>(double(values[1]-values[0])*1000.0/double(frequency_)) : 0.f;
                last_seam_analysis_milliseconds().store(seam_gpu_ms_, std::memory_order_relaxed);
            }
            D3D12_RANGE no_write{0,0};
            timestamps_->Unmap(0,&no_write);
        }
        timing_pending_=false;
        timed_seam_active_=false;
    }
    void setup_timing(ID3D12Device* device, UINT64 frequency) {
        if (!device || !frequency || (queries_ && timestamps_ && frequency_==frequency)) return;
        queries_.Reset(); timestamps_.Reset(); frequency_=0; timing_pending_=false; gpu_ms_=-1.f; seam_gpu_ms_=-1.f; timed_seam_active_=false;
        D3D12_QUERY_HEAP_DESC query{};
        query.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
        query.Count=3;
        if (FAILED(device->CreateQueryHeap(&query,IID_PPV_ARGS(&queries_)))) return;
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type=D3D12_HEAP_TYPE_READBACK;
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC buffer{};
        buffer.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width=sizeof(UINT64)*3;
        buffer.Height=buffer.DepthOrArraySize=buffer.MipLevels=1;
        buffer.SampleDesc.Count=1;
        buffer.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&buffer,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&timestamps_)))) {
            queries_.Reset();
            return;
        }
        frequency_=frequency;
        queries_->SetName(L"QuadView slot timestamp queries");
        timestamps_->SetName(L"QuadView slot timestamp readback");
    }
    static bool compatible_source(DXGI_FORMAT resource, DXGI_FORMAT view) {
        if (resource == view) return true;
        if (resource == DXGI_FORMAT_R8G8B8A8_TYPELESS) return view == DXGI_FORMAT_R8G8B8A8_UNORM || view == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
        if (resource == DXGI_FORMAT_B8G8R8A8_TYPELESS) return view == DXGI_FORMAT_B8G8R8A8_UNORM || view == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        if (resource == DXGI_FORMAT_R10G10B10A2_TYPELESS) return view == DXGI_FORMAT_R10G10B10A2_UNORM;
        if (resource == DXGI_FORMAT_R16G16B16A16_TYPELESS) return view == DXGI_FORMAT_R16G16B16A16_FLOAT;
        return false;
    }
    static bool valid_layout(const Layout& layout) {
        if (!layout.eye_width || !layout.eye_height || layout.eye_width > 8192 || layout.eye_height > 8192 ||
            layout.atlas_width != layout.eye_width * 2 || layout.atlas_height != layout.eye_height) return false;
        for (const auto& c : layout.focus_crops) {
            if (!(std::isfinite(c.u0) && std::isfinite(c.v0) && std::isfinite(c.u1) && std::isfinite(c.v1)) ||
                c.u0 < 0.f || c.v0 < 0.f || c.u1 > 1.f || c.v1 > 1.f || c.u1 <= c.u0 || c.v1 <= c.v0) return false;
        }
        for (unsigned i = 0; i < 4; ++i) {
            const auto& rect = layout.views[i];
            if (!rect.width || !rect.height || uint64_t(rect.x) + rect.width > layout.atlas_width ||
                uint64_t(rect.y) + rect.height > layout.atlas_height) return false;
            if (layout.native_local) {
                // B6: each rectangle lives in its own target; it must fit that target.
                const auto extents = source_extents(layout);
                if (uint64_t(rect.x) + rect.width > extents[i][0] || uint64_t(rect.y) + rect.height > extents[i][1]) return false;
                continue;
            }
            for (unsigned j = 0; j < i; ++j) {
                const auto& other = layout.views[j];
                if (uint64_t(rect.x) < uint64_t(other.x) + other.width && uint64_t(other.x) < uint64_t(rect.x) + rect.width &&
                    uint64_t(rect.y) < uint64_t(other.y) + other.height && uint64_t(other.y) < uint64_t(rect.y) + rect.height) return false;
            }
        }
        return true;
    }
    static void barrier(ID3D12GraphicsCommandList* commands, ID3D12Resource* resource,
                         D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
        if (before == after) return;
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition.pResource = resource;
        barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        barrier.Transition.StateBefore = before; barrier.Transition.StateAfter = after;
        commands->ResourceBarrier(1, &barrier);
    }
    ComPtr<ID3D12Device> device_;
    ComPtr<ID3D12RootSignature> root_;
    ComPtr<ID3D12PipelineState> pipeline_;
    ComPtr<ID3D12PipelineState> seam_pipeline_;
    ComPtr<ID3D12DescriptorHeap> srv_heap_, rtv_heap_;
    ComPtr<ID3D12Resource> constants_, destination_, timestamps_;
    ComPtr<ID3D12Resource> seam_stats_;
    std::array<ComPtr<ID3D12Resource>, 4> sources_;
    ComPtr<ID3D12QueryHeap> queries_;
    void* mapped_{};
    std::shared_ptr<const void> depth_keepalive_{};
    std::shared_ptr<const void> owner_;
    std::vector<SnapshotItem> snapshot_;
    std::string snapshot_text_;
    DXGI_FORMAT source_format_{DXGI_FORMAT_UNKNOWN}, output_format_{DXGI_FORMAT_UNKNOWN};
    const char* error_{"Compositor not prewarmed"};
    bool recorded_{};
    bool timing_pending_{};
    bool timed_seam_active_{}; // pending timestamp interval includes CSSeam
    UINT64 frequency_{};
    float gpu_ms_{-1.f};
    float seam_gpu_ms_{-1.f};
};

} // namespace uevr::quadview::dx12

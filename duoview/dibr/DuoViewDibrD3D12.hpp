#pragma once

#include "ManualDibrContract.hpp"
#include "../DuoViewD3D12.hpp"
#include <array>
#include <memory>
#include <string>
#include <d3d12.h>
#include <wrl.h>

namespace uevr::duoview::dibr::dx12 {
using Microsoft::WRL::ComPtr;

struct OwnedDepthTexture {
    Candidate candidate{};
    OwnedDepthSample sample{};
    ComPtr<ID3D12Resource> texture{};
    uint64_t latest_update_serial{};
};

struct ProjectionPair {
    std::array<float, 16> left{};
    std::array<float, 16> right{};
    // Reversed-Z scene values remain valid throughout [0,1]. Exact clear
    // values are excluded separately; do not drop the useful near-zero tail.
    float depth_min{0.f};
    float depth_max{1.f};
    float depth_clear{};
    float depth_clear_epsilon{};
    uint32_t iterations{3};
    Rect color_rect{};
    std::array<float, 4> fovea_uv_rect{0.f, 0.f, 1.f, 1.f};
    bool use_fovea_depth{};
    bool center_color_srgb{};
};

struct ConsumerReceipt {
    uint64_t queue{};
    uint64_t submission_order{};
    uint64_t waited_producer_fence{};
};

struct alignas(16) ShaderConstants {
    uint32_t output_size[2]{};
    uint32_t color_size[2]{};
    uint32_t periphery_depth_size[2]{};
    uint32_t periphery_padding[2]{};
    uint32_t periphery_depth_rect[4]{};
    uint32_t fovea_depth_size[2]{};
    uint32_t fovea_padding[2]{};
    uint32_t fovea_depth_rect[4]{};
    uint32_t color_rect[4]{};
    uint32_t config[4]{};
    float depth_validity[4]{};
    float fovea_uv_rect[4]{};
    float source_ndc_to_target_clip[16]{};
};
static_assert(sizeof(ShaderConstants) == 208);

class Compositor {
public:
    bool prewarm(ID3D12Device* device, UINT per_eye_width, UINT height, DXGI_FORMAT target_format) {
        if (!device || !per_eye_width || !height || !supported_color(target_format) ||
            FAILED(device->GetDeviceRemovedReason())) return false;
        const auto format = render_target_format(target_format);
        if (device_.Get() == device && width_ == per_eye_width && height_ == height &&
            output_format_ == format && root_ && pipeline_ && srv_heap_ && rtv_heap_) return true;
        device_ = device;
        width_ = per_eye_width;
        height_ = height;
        output_format_ = format;
        root_.Reset(); pipeline_.Reset(); srv_heap_.Reset(); rtv_heap_.Reset();
        color_reference_.Reset(); periphery_reference_.Reset(); fovea_reference_.Reset(); output_reference_.Reset();
        rtv_valid_ = false;
        error_.clear();

        D3D12_DESCRIPTOR_RANGE range{};
        range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        range.NumDescriptors = 3;
        range.BaseShaderRegister = 0;
        range.RegisterSpace = 0;
        range.OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
        D3D12_ROOT_PARAMETER params[2]{};
        params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        params[0].DescriptorTable = {1, &range};
        params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
        params[1].Constants = {0, 0, sizeof(ShaderConstants) / sizeof(uint32_t)};
        params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        D3D12_STATIC_SAMPLER_DESC sampler{};
        sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
        sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
        sampler.MipLODBias = 0.f;
        sampler.MaxAnisotropy = 1;
        sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        sampler.BorderColor = D3D12_STATIC_BORDER_COLOR_TRANSPARENT_BLACK;
        sampler.MinLOD = 0.f;
        sampler.MaxLOD = D3D12_FLOAT32_MAX;
        sampler.ShaderRegister = 0;
        sampler.RegisterSpace = 0;
        sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        D3D12_ROOT_SIGNATURE_DESC root_desc{2, params, 1, &sampler,
            D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT};
        ComPtr<ID3DBlob> serialized, errors;
        if (!check(D3D12SerializeRootSignature(&root_desc, D3D_ROOT_SIGNATURE_VERSION_1,
                &serialized, &errors), "serialize DIBR root signature") ||
            !check(device->CreateRootSignature(0, serialized->GetBufferPointer(),
                serialized->GetBufferSize(), IID_PPV_ARGS(&root_)), "create DIBR root signature")) return false;

        D3D12_GRAPHICS_PIPELINE_STATE_DESC pso{};
        pso.pRootSignature = root_.Get();
        pso.VS = {::uevr::duoview::dx12::dibr_vertex_shader_bytecode,
            sizeof(::uevr::duoview::dx12::dibr_vertex_shader_bytecode)};
        pso.PS = {::uevr::duoview::dx12::dibr_pixel_shader_bytecode,
            sizeof(::uevr::duoview::dx12::dibr_pixel_shader_bytecode)};
        auto& blend = pso.BlendState.RenderTarget[0];
        blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
        blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
        blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
        blend.LogicOp = D3D12_LOGIC_OP_NOOP;
        blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
        pso.SampleMask = UINT_MAX;
        pso.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
        pso.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
        pso.RasterizerState.DepthClipEnable = TRUE;
        pso.DepthStencilState.DepthEnable = FALSE;
        pso.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ZERO;
        pso.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        pso.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        pso.NumRenderTargets = 1;
        pso.RTVFormats[0] = format;
        pso.SampleDesc.Count = 1;
        if (!check(device->CreateGraphicsPipelineState(&pso, IID_PPV_ARGS(&pipeline_)),
            "create DIBR raster PSO")) return false;

        D3D12_DESCRIPTOR_HEAP_DESC heap{};
        heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        heap.NumDescriptors = 3;
        if (!check(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&srv_heap_)),
            "create DIBR SRV heap")) return false;
        srv_increment_ = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        srv_cpu_ = srv_heap_->GetCPUDescriptorHandleForHeapStart();
        srv_gpu_ = srv_heap_->GetGPUDescriptorHandleForHeapStart();
        heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
        heap.NumDescriptors = 1;
        if (!check(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&rtv_heap_)),
            "create DIBR RTV heap")) return false;
        rtv_cpu_ = rtv_heap_->GetCPUDescriptorHandleForHeapStart();
        return true;
    }

    bool record(
        ID3D12Device* device,
        ID3D12GraphicsCommandList* command_list,
        ID3D12Resource* center_color,
        D3D12_RESOURCE_STATES color_state,
        const OwnedDepthTexture& periphery,
        D3D12_RESOURCE_STATES periphery_state,
        const OwnedDepthTexture* fovea,
        D3D12_RESOURCE_STATES fovea_state,
        const RoleAssignments& roles,
        ProducerKey output_frame,
        ConsumerReceipt consumer,
        ID3D12Resource* double_wide_output,
        D3D12_RESOURCE_STATES output_state,
        const ProjectionPair& projection,
        std::shared_ptr<const void> packet_lifetime = {})
    {
        recorded_commands_ = false;
        error_.clear();
        auto sample_for_consumer = periphery.sample;
        apply_consumer_receipt(sample_for_consumer, consumer);
        const auto gate = validate_selected_sample(periphery.candidate, roles, sample_for_consumer,
            output_frame, periphery.latest_update_serial);
        gate_reason_ = gate.reason;
        if (!gate) return reject(gate_message(gate.reason));
        auto* periphery_resource = periphery.texture.Get();
        bool use_fovea = projection.use_fovea_depth && fovea != nullptr;
        if (projection.use_fovea_depth && fovea == nullptr) {
            // Periphery-only is a valid first path while the optional fovea
            // source is waiting for a current same-frame owned copy.
            use_fovea = false;
        }
        // Never keep a descriptor to a caller-owned optional resource when
        // this draw falls back to periphery-only. t2 always aliases a retained
        // periphery snapshot unless the fovea lineage gate passes.
        auto* fovea_resource = use_fovea ? fovea->texture.Get() : periphery_resource;
        OwnedDepthSample fovea_sample_for_consumer{};
        if (use_fovea) {
            if (!roles.fovea || *roles.fovea != fovea->candidate.key)
                return reject("fovea snapshot does not match the manual fovea assignment");
            fovea_sample_for_consumer = fovea->sample;
            apply_consumer_receipt(fovea_sample_for_consumer, consumer);
            const auto fovea_gate = validate_owned_sample(fovea->candidate,
                fovea_sample_for_consumer, output_frame, fovea->latest_update_serial);
            if (!fovea_gate) return reject(gate_message(fovea_gate.reason));
        }
        if (!device || !command_list || !center_color || !periphery_resource || !fovea_resource || !double_wide_output ||
            center_color == periphery_resource || center_color == fovea_resource || center_color == double_wide_output ||
            periphery_resource == double_wide_output || fovea_resource == double_wide_output ||
            command_list->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT ||
            FAILED(device->GetDeviceRemovedReason())) return reject("invalid device, command list, or DIBR textures");

        const auto color_desc = center_color->GetDesc();
        const auto periphery_desc = periphery_resource->GetDesc();
        const auto fovea_desc = fovea_resource->GetDesc();
        const auto output_desc = double_wide_output->GetDesc();
        if (!texture2d(color_desc) || !texture2d(periphery_desc) || !texture2d(fovea_desc) || !texture2d(output_desc) ||
            !supported_color(color_desc.Format) || !supported_depth(periphery_desc.Format) ||
            !supported_depth(fovea_desc.Format) ||
            !compatible_color_view(output_desc.Format, output_format_) ||
            color_desc.Width != width_ || color_desc.Height != height_ ||
            output_desc.Width != static_cast<uint64_t>(width_) * 2 || output_desc.Height != height_ ||
            periphery.candidate.width != periphery_desc.Width || periphery.candidate.height != periphery_desc.Height ||
            periphery.candidate.format != static_cast<uint32_t>(periphery_desc.Format) ||
            fovea_desc.Width > UINT32_MAX || fovea_desc.Height > UINT32_MAX ||
            periphery_desc.Width > UINT32_MAX || periphery_desc.Height > UINT32_MAX ||
            (color_desc.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            (periphery_desc.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            (fovea_desc.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            !(output_desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) ||
            !rect_valid(periphery.candidate.active_rect, static_cast<uint32_t>(periphery_desc.Width), periphery_desc.Height) ||
            (use_fovea && (!rect_valid(fovea->candidate.active_rect, static_cast<uint32_t>(fovea_desc.Width), fovea_desc.Height) ||
                !std::all_of(projection.fovea_uv_rect.begin(), projection.fovea_uv_rect.end(),
                    [](float v) { return std::isfinite(v); }) ||
                projection.fovea_uv_rect[0] < 0.f || projection.fovea_uv_rect[1] < 0.f ||
                projection.fovea_uv_rect[0] >= projection.fovea_uv_rect[2] ||
                projection.fovea_uv_rect[1] >= projection.fovea_uv_rect[3] ||
                projection.fovea_uv_rect[2] > 1.f || projection.fovea_uv_rect[3] > 1.f)) ||
            !rect_valid(projection.color_rect, static_cast<uint32_t>(color_desc.Width), color_desc.Height))
            return reject("unsupported texture description, active rect, or double-wide output layout");
        if (periphery_desc.DepthOrArraySize != 1 || periphery_desc.MipLevels != 1 ||
            periphery_desc.SampleDesc.Count != 1 || periphery_desc.SampleDesc.Quality != 0 ||
            fovea_desc.DepthOrArraySize != 1 || fovea_desc.MipLevels != 1 ||
            fovea_desc.SampleDesc.Count != 1 || fovea_desc.SampleDesc.Quality != 0 ||
            color_desc.DepthOrArraySize != 1 || color_desc.MipLevels != 1 ||
            color_desc.SampleDesc.Count != 1 || color_desc.SampleDesc.Quality != 0 ||
            output_desc.DepthOrArraySize != 1 || output_desc.MipLevels != 1 ||
            output_desc.SampleDesc.Count != 1 || output_desc.SampleDesc.Quality != 0)
            return reject("DIBR adapter requires owned single-sample 2D subresource-zero snapshots");
        if (!matrix_valid(projection.left) || !matrix_valid(projection.right) ||
            !std::isfinite(projection.depth_min) || !std::isfinite(projection.depth_max) ||
            !std::isfinite(projection.depth_clear) || !std::isfinite(projection.depth_clear_epsilon) ||
            projection.depth_min < 0.f || projection.depth_max > 1.f ||
            projection.depth_min >= projection.depth_max || projection.depth_clear_epsilon < 0.f ||
            projection.iterations < 1 || projection.iterations > 4)
            return reject("invalid frozen source-to-eye projection or depth encoding");
        if (device_.Get() != device || width_ == 0 || height_ == 0 ||
            !compatible_color_view(output_desc.Format, output_format_) || !root_ || !pipeline_ ||
            !srv_heap_ || !rtv_heap_)
            return reject("DIBR adapter was not prewarmed for this output format");

        const auto color_view_format = color_srv_format(color_desc.Format, projection.center_color_srgb);
        if (color_view_format == DXGI_FORMAT_UNKNOWN || color_view_format != output_format_)
            return reject("center color sRGB encoding does not match the stereo output encoding");
        ComPtr<ID3D12Device> color_device, periphery_device, fovea_device, output_device, command_device;
        if (FAILED(center_color->GetDevice(IID_PPV_ARGS(&color_device))) ||
            FAILED(periphery_resource->GetDevice(IID_PPV_ARGS(&periphery_device))) ||
            FAILED(fovea_resource->GetDevice(IID_PPV_ARGS(&fovea_device))) ||
            FAILED(double_wide_output->GetDevice(IID_PPV_ARGS(&output_device))) ||
            FAILED(command_list->GetDevice(IID_PPV_ARGS(&command_device))) ||
            color_device.Get() != device || periphery_device.Get() != device || fovea_device.Get() != device ||
            output_device.Get() != device || command_device.Get() != device)
            return reject("DIBR resources belong to different D3D12 devices");

        ensure_rtv(device, double_wide_output, output_desc.Format);
        create_srvs(device, center_color, color_view_format, periphery_resource, periphery_desc.Format,
            fovea_resource, fovea_desc.Format);
        color_reference_ = center_color;
        periphery_reference_ = periphery_resource;
        fovea_reference_ = use_fovea ? fovea_resource : nullptr;
        output_reference_ = double_wide_output;
        packet_lifetime_ = std::move(packet_lifetime);

        if (!(color_state & D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE))
            transition(command_list, center_color, color_state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        if (!(periphery_state & D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE))
            transition(command_list, periphery_resource, periphery_state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        if (use_fovea && !(fovea_state & D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE))
            transition(command_list, fovea_resource, fovea_state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        if (output_state != D3D12_RESOURCE_STATE_RENDER_TARGET)
            transition(command_list, double_wide_output, output_state, D3D12_RESOURCE_STATE_RENDER_TARGET);
        recorded_commands_ = true;

        ID3D12DescriptorHeap* heaps[]{srv_heap_.Get()};
        command_list->SetDescriptorHeaps(1, heaps);
        command_list->SetGraphicsRootSignature(root_.Get());
        command_list->SetPipelineState(pipeline_.Get());
        command_list->SetGraphicsRootDescriptorTable(0, srv_gpu_);
        command_list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        command_list->OMSetRenderTargets(1, &rtv_cpu_, FALSE, nullptr);
        const auto make_constants = [&](uint32_t eye, const std::array<float, 16>& matrix) {
            ShaderConstants constants{};
            constants.output_size[0] = width_; constants.output_size[1] = height_;
            constants.color_size[0] = static_cast<uint32_t>(color_desc.Width);
            constants.color_size[1] = color_desc.Height;
            constants.periphery_depth_size[0] = static_cast<uint32_t>(periphery_desc.Width);
            constants.periphery_depth_size[1] = periphery_desc.Height;
            const auto& dr = periphery.candidate.active_rect;
            constants.periphery_depth_rect[0] = dr.x; constants.periphery_depth_rect[1] = dr.y;
            constants.periphery_depth_rect[2] = dr.width; constants.periphery_depth_rect[3] = dr.height;
            constants.fovea_depth_size[0] = static_cast<uint32_t>(fovea_desc.Width);
            constants.fovea_depth_size[1] = fovea_desc.Height;
            const auto& fr = use_fovea ? fovea->candidate.active_rect : periphery.candidate.active_rect;
            constants.fovea_depth_rect[0] = fr.x; constants.fovea_depth_rect[1] = fr.y;
            constants.fovea_depth_rect[2] = fr.width; constants.fovea_depth_rect[3] = fr.height;
            const auto& cr = projection.color_rect;
            constants.color_rect[0] = cr.x; constants.color_rect[1] = cr.y;
            constants.color_rect[2] = cr.width; constants.color_rect[3] = cr.height;
            constants.config[0] = eye; constants.config[1] = projection.iterations;
            constants.config[2] = use_fovea ? 1u : 0u;
            constants.depth_validity[0] = projection.depth_min;
            constants.depth_validity[1] = projection.depth_max;
            constants.depth_validity[2] = projection.depth_clear;
            constants.depth_validity[3] = projection.depth_clear_epsilon;
            std::copy(projection.fovea_uv_rect.begin(), projection.fovea_uv_rect.end(), constants.fovea_uv_rect);
            std::copy(matrix.begin(), matrix.end(), constants.source_ndc_to_target_clip);
            return constants;
        };
        for (uint32_t eye = 0; eye != 2; ++eye) {
            const D3D12_VIEWPORT viewport{static_cast<float>(eye * width_), 0.f,
                static_cast<float>(width_), static_cast<float>(height_), 0.f, 1.f};
            const D3D12_RECT scissor{static_cast<LONG>(eye * width_), 0,
                static_cast<LONG>((eye + 1) * width_), static_cast<LONG>(height_)};
            command_list->RSSetViewports(1, &viewport);
            command_list->RSSetScissorRects(1, &scissor);
            const auto constants = make_constants(eye, eye == 0 ? projection.left : projection.right);
            command_list->SetGraphicsRoot32BitConstants(1, sizeof(constants) / sizeof(uint32_t), &constants, 0);
            command_list->DrawInstanced(3, 1, 0, 0);
        }

        if (output_state != D3D12_RESOURCE_STATE_RENDER_TARGET)
            transition(command_list, double_wide_output, D3D12_RESOURCE_STATE_RENDER_TARGET, output_state);
        if (use_fovea && !(fovea_state & D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE))
            transition(command_list, fovea_resource, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, fovea_state);
        if (!(periphery_state & D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE))
            transition(command_list, periphery_resource, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, periphery_state);
        if (!(color_state & D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE))
            transition(command_list, center_color, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, color_state);
        return true;
    }

    void retire_after_fence() { color_reference_.Reset(); periphery_reference_.Reset(); fovea_reference_.Reset(); output_reference_.Reset(); packet_lifetime_.reset(); }
    bool recorded_commands() const { return recorded_commands_; }
    GateReason gate_reason() const { return gate_reason_; }
    const std::string& error() const { return error_; }

private:
    bool check(HRESULT hr, const char* operation) {
        if (SUCCEEDED(hr)) return true;
        error_ = std::string(operation) + " failed (HRESULT " + std::to_string(static_cast<uint32_t>(hr)) + ")";
        return false;
    }
    bool reject(const char* reason) { error_ = reason; return false; }
    static bool texture2d(const D3D12_RESOURCE_DESC& d) {
        return d.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && d.Width && d.Height;
    }
    static bool supported_color(DXGI_FORMAT f) {
        return f == DXGI_FORMAT_B8G8R8A8_TYPELESS || f == DXGI_FORMAT_B8G8R8A8_UNORM ||
            f == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
    }
    static DXGI_FORMAT color_srv_format(DXGI_FORMAT f, bool srgb) {
        const auto desired = srgb ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        if (f == DXGI_FORMAT_B8G8R8A8_TYPELESS) return desired;
        if (f == desired) return f;
        return DXGI_FORMAT_UNKNOWN;
    }
    static DXGI_FORMAT render_target_format(DXGI_FORMAT f) {
        return f == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ? f :
            (supported_color(f) ? DXGI_FORMAT_B8G8R8A8_UNORM : DXGI_FORMAT_UNKNOWN);
    }
    static bool compatible_color_view(DXGI_FORMAT resource_format, DXGI_FORMAT view_format) {
        if (resource_format == DXGI_FORMAT_B8G8R8A8_TYPELESS)
            return view_format == DXGI_FORMAT_B8G8R8A8_UNORM ||
                view_format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        return resource_format == view_format;
    }
    static bool supported_depth(DXGI_FORMAT f) {
        return f == DXGI_FORMAT_R32_TYPELESS || f == DXGI_FORMAT_R32_FLOAT;
    }
    static void apply_consumer_receipt(OwnedDepthSample& sample, const ConsumerReceipt& consumer) {
        sample.queue.consumer_queue = consumer.queue;
        sample.queue.consumer_order = consumer.submission_order;
        sample.queue.consumer_wait = consumer.waited_producer_fence;
        if (sample.queue.producer_queue && consumer.queue && sample.queue.producer_queue == consumer.queue) {
            sample.queue.relation = QueueRelation::same_queue;
            sample.queue.consumer_wait = 0;
        } else if (sample.queue.producer_queue && consumer.queue) {
            sample.queue.relation = QueueRelation::cross_queue;
        } else sample.queue.relation = QueueRelation::unknown;
    }
    static bool matrix_valid(const std::array<float, 16>& m) {
        return std::all_of(m.begin(), m.end(), [](float v) { return std::isfinite(v); });
    }
    static const char* gate_message(GateReason reason) {
        switch (reason) {
        case GateReason::choose_full_view_depth: return "choose full-view/periphery depth";
        case GateReason::source_changed: return "selected depth resource changed; reselect";
        case GateReason::no_current_sample: return "waiting for a current owned depth snapshot";
        case GateReason::sample_not_owned: return "depth sample is borrowed or incomplete";
        case GateReason::stage_unverified: return "selected capture stage is timing-unverified";
        case GateReason::frame_mismatch: return "depth and center color frame tokens differ";
        case GateReason::producer_generation_mismatch: return "depth and center color generations differ";
        case GateReason::unsupported_subresource: return "selected depth format/subresource is unsupported";
        case GateReason::queue_unproven: return "producer/consumer queue relationship is unknown";
        case GateReason::queue_order_unproven: return "same-queue producer order is unverified";
        case GateReason::producer_fence_missing: return "cross-queue producer fence is missing";
        case GateReason::consumer_wait_missing: return "consumer queue has not waited for producer fence";
        case GateReason::invalid_rect: return "selected depth active rectangle is invalid";
        default: return "depth packet is not ready";
        }
    }
    static void transition(ID3D12GraphicsCommandList* cmd, ID3D12Resource* resource,
        D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
        D3D12_RESOURCE_BARRIER b{};
        b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition = {resource, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before, after};
        cmd->ResourceBarrier(1, &b);
    }
    void ensure_rtv(ID3D12Device* device, ID3D12Resource* output, DXGI_FORMAT resource_format) {
        if (rtv_valid_ && output_reference_.Get() == output && rtv_format_ == resource_format) return;
        D3D12_RENDER_TARGET_VIEW_DESC view{};
        view.Format = output_format_;
        view.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
        device->CreateRenderTargetView(output, &view, rtv_cpu_);
        rtv_format_ = resource_format;
        rtv_valid_ = true;
    }
    void create_srvs(ID3D12Device* device, ID3D12Resource* color, DXGI_FORMAT color_format,
        ID3D12Resource* periphery, DXGI_FORMAT periphery_format,
        ID3D12Resource* fovea, DXGI_FORMAT fovea_format) {
        D3D12_SHADER_RESOURCE_VIEW_DESC view{};
        view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
        view.Texture2D.MipLevels = 1;
        view.Format = color_format;
        device->CreateShaderResourceView(color, &view, srv_cpu_);
        view.Format = periphery_format == DXGI_FORMAT_R32_TYPELESS ? DXGI_FORMAT_R32_FLOAT : periphery_format;
        auto periphery_cpu = srv_cpu_; periphery_cpu.ptr += srv_increment_;
        device->CreateShaderResourceView(periphery, &view, periphery_cpu);
        view.Format = fovea_format == DXGI_FORMAT_R32_TYPELESS ? DXGI_FORMAT_R32_FLOAT : fovea_format;
        auto fovea_cpu = srv_cpu_; fovea_cpu.ptr += 2 * srv_increment_;
        device->CreateShaderResourceView(fovea, &view, fovea_cpu);
    }

    ComPtr<ID3D12Device> device_{};
    ComPtr<ID3D12RootSignature> root_{};
    ComPtr<ID3D12PipelineState> pipeline_{};
    ComPtr<ID3D12DescriptorHeap> srv_heap_{}, rtv_heap_{};
    ComPtr<ID3D12Resource> color_reference_{}, periphery_reference_{}, fovea_reference_{}, output_reference_{};
    std::shared_ptr<const void> packet_lifetime_{};
    D3D12_CPU_DESCRIPTOR_HANDLE srv_cpu_{}, rtv_cpu_{};
    D3D12_GPU_DESCRIPTOR_HANDLE srv_gpu_{};
    UINT srv_increment_{};
    UINT width_{}, height_{};
    DXGI_FORMAT output_format_{DXGI_FORMAT_UNKNOWN}, rtv_format_{DXGI_FORMAT_UNKNOWN};
    bool rtv_valid_{}, recorded_commands_{};
    GateReason gate_reason_{GateReason::choose_full_view_depth};
    std::string error_{};
};
}

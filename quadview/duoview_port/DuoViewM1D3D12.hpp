#pragma once

#include "DuoViewStereoGeometry.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <memory>

namespace uevr::duoview::dx12 {
using Microsoft::WRL::ComPtr;
struct M1DepthInput {
    ID3D12Resource* texture{};
    DXGI_FORMAT format{DXGI_FORMAT_UNKNOWN};
    std::array<uint32_t,4> rect{};
    std::array<float,2> jitter{};
    std::shared_ptr<const void> lease;
};

struct M1Constants {
    float homography[6][4]{};
    float eye[4]{};
    float depth[4]{};
    uint32_t rect[4]{};
    uint32_t grid[4]{};
    float filter[4]{};
};
static_assert(sizeof(M1Constants) == 176);

// Each instance belongs to a fenced XR command slot. Descriptors, upload data
// and the retained NGX copy live until that slot is safe to record again.
class M1Resources {
public:
    static constexpr uint32_t grid_limit = 1024;
    ComPtr<ID3D12PipelineState> raster, condition;
    ComPtr<ID3D12Resource> soft_depth, constants;
    std::shared_ptr<const void> depth_lease;

    bool ready() const { return raster && condition && soft_depth && constants; }

    bool prepare(ID3D12Device* device, ID3D12RootSignature* root,
                 D3D12_GRAPHICS_PIPELINE_STATE_DESC graphics,
                 uint32_t eye_width, uint32_t eye_height) {
        graphics.PS = {m1_raster_bytecode, sizeof(m1_raster_bytecode)};
        if (FAILED(device->CreateGraphicsPipelineState(&graphics, IID_PPV_ARGS(&raster)))) return false;
        D3D12_COMPUTE_PIPELINE_STATE_DESC compute{};
        compute.pRootSignature = root;
        compute.CS = {m1_condition_bytecode, sizeof(m1_condition_bytecode)};
        if (FAILED(device->CreateComputePipelineState(&compute, IID_PPV_ARGS(&condition)))) return false;

        D3D12_HEAP_PROPERTIES heap{};
        heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC texture{};
        texture.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        texture.Width = (std::min)(eye_width, grid_limit);
        texture.Height = (std::min)(eye_height, grid_limit);
        texture.DepthOrArraySize = texture.MipLevels = 1;
        texture.Format = DXGI_FORMAT_R32_FLOAT;
        texture.SampleDesc.Count = 1;
        texture.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &texture,
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, nullptr, IID_PPV_ARGS(&soft_depth)))) return false;

        heap.Type = D3D12_HEAP_TYPE_UPLOAD;
        D3D12_RESOURCE_DESC buffer{};
        buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width = D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT;
        buffer.Height = buffer.DepthOrArraySize = buffer.MipLevels = 1;
        buffer.SampleDesc.Count = 1;
        buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        return SUCCEEDED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer,
            D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&constants)));
    }

    bool write_constants(ID3D12Device* device, const stereo::Geometry& geometry,
                         const M1DepthInput* input, float near_m, float softness,
                         D3D12_CPU_DESCRIPTOR_HANDLE raw_srv) {
        M1Constants data{};
        static_assert(sizeof(geometry.context_h) == sizeof(data.homography));
        std::memcpy(data.homography, geometry.context_h.data(), sizeof(data.homography));
        data.eye[0] = geometry.k[0];
        data.eye[1] = geometry.k[1];
        std::copy_n(geometry.depth_coefficients.begin(), 3, data.depth);
        data.depth[3] = near_m > 0.f ? 1.f / (near_m * geometry.world_to_meters) : 0.f;
        data.filter[1] = 12.5f / geometry.world_to_meters;
        const auto soft = soft_depth->GetDesc();
        depth_lease.reset();
        if (input && input->texture && input->lease && input->rect[2] && input->rect[3]) {
            const auto raw = input->texture->GetDesc();
            const bool format_ok =
                (raw.Format == DXGI_FORMAT_R32_TYPELESS && input->format == DXGI_FORMAT_R32_FLOAT) ||
                (raw.Format == DXGI_FORMAT_R32G8X24_TYPELESS && input->format == DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS);
            ComPtr<ID3D12Device> owner;
            if (format_ok && raw.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
                raw.DepthOrArraySize == 1 && raw.SampleDesc.Count == 1 &&
                uint64_t(input->rect[0]) + input->rect[2] <= raw.Width &&
                uint64_t(input->rect[1]) + input->rect[3] <= raw.Height &&
                SUCCEEDED(input->texture->GetDevice(IID_PPV_ARGS(&owner))) && owner.Get() == device) {
                std::copy(input->rect.begin(), input->rect.end(), data.rect);
                data.eye[2] = input->jitter[0];
                data.eye[3] = input->jitter[1];
                data.grid[0] = (std::min)(uint32_t(soft.Width), input->rect[2]);
                data.grid[1] = (std::min)(soft.Height, input->rect[3]);
                data.grid[2] = uint32_t(soft.Width);
                data.grid[3] = soft.Height;
                const float kmax = (std::max)(std::abs(data.eye[0]), std::abs(data.eye[1]));
                data.filter[0] = softness / ((std::max)(kmax, .00001f) * float(data.grid[0]));
                D3D12_SHADER_RESOURCE_VIEW_DESC view{};
                view.Format = input->format;
                view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
                view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
                view.Texture2D.MipLevels = 1;
                device->CreateShaderResourceView(input->texture, &view, raw_srv);
                depth_lease = input->lease;
            }
        }
        void* address{};
        const D3D12_RANGE no_read{0,0};
        if (FAILED(constants->Map(0, &no_read, &address))) return false;
        std::memcpy(address, &data, sizeof(data));
        constants->Unmap(0, nullptr);
        rows = data.grid[1];
        return true;
    }

    uint32_t rows{};
};
} // namespace uevr::duoview::dx12

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
    float m2_crop[4]{};
    uint32_t m2_fovea_rect[4]{};
    float m2_fovea_flags[4]{};
    float m2_sharpen[4]{};
};
static_assert(sizeof(M1Constants) == 240);
static_assert(sizeof(M1Constants) <= D3D12_CONSTANT_BUFFER_DATA_PLACEMENT_ALIGNMENT);

// Each instance belongs to a fenced XR command slot. Descriptors, upload data
// and the retained NGX copy live until that slot is safe to record again.
class M1Resources {
public:
    static constexpr uint32_t grid_limit = 1024;
    ComPtr<ID3D12PipelineState> raster, condition;
    ComPtr<ID3D12Resource> soft_depth, constants;
    std::shared_ptr<const void> depth_lease, fovea_depth_lease;
    bool fovea_depth_active{};

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
                         const M1DepthInput* input, const M1DepthInput* focus,
                         const std::array<float,4>& crop, float left_sharpen,
                         float right_sharpen, float near_m, float softness,
                         D3D12_CPU_DESCRIPTOR_HANDLE raw_srv,
                         D3D12_CPU_DESCRIPTOR_HANDLE focus_srv) {
        M1Constants data{};
        static_assert(sizeof(geometry.context_h) == sizeof(data.homography));
        std::memcpy(data.homography, geometry.context_h.data(), sizeof(data.homography));
        data.eye[0] = geometry.k[0];
        data.eye[1] = geometry.k[1];
        std::copy_n(geometry.depth_coefficients.begin(), 3, data.depth);
        data.depth[3] = near_m > 0.f ? 1.f / (near_m * geometry.world_to_meters) : 0.f;
        data.filter[1] = 12.5f / geometry.world_to_meters;
        data.m2_sharpen[0] = (std::clamp)(left_sharpen,0.f,5.f);
        data.m2_sharpen[1] = (std::clamp)(right_sharpen,0.f,5.f);
        const bool crop_ok = crop[0] >= 0.f && crop[1] >= 0.f &&
            crop[2] <= 1.f && crop[3] <= 1.f &&
            crop[2] > crop[0] && crop[3] > crop[1] &&
            std::all_of(crop.begin(),crop.end(),[](float v){return std::isfinite(v);});
        if (crop_ok) std::copy(crop.begin(),crop.end(),data.m2_crop);
        const auto soft = soft_depth->GetDesc();
        depth_lease.reset();
        fovea_depth_lease.reset();
        fovea_depth_active=false;
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
        // Optional fine depth is a separate SRV, not a downsampled M1 grid.
        // All validation and D3D12 ownership is independent from periphery.
        D3D12_SHADER_RESOURCE_VIEW_DESC fine_view{};
        fine_view.Format=DXGI_FORMAT_R32_FLOAT;
        fine_view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
        fine_view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        fine_view.Texture2D.MipLevels=1;
        bool fine_ok=false;
        if (depth_lease && data.grid[0] && data.grid[1] && crop_ok &&
            focus && focus->texture && focus->lease &&
            focus->rect[2] && focus->rect[3]) {
            const auto fine=focus->texture->GetDesc();
            const bool format_ok =
                (fine.Format==DXGI_FORMAT_R32_TYPELESS && focus->format==DXGI_FORMAT_R32_FLOAT) ||
                (fine.Format==DXGI_FORMAT_R32G8X24_TYPELESS &&
                 focus->format==DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS);
            ComPtr<ID3D12Device> owner;
            if (format_ok && fine.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
                fine.DepthOrArraySize==1 && fine.SampleDesc.Count==1 &&
                uint64_t(focus->rect[0])+focus->rect[2]<=fine.Width &&
                uint64_t(focus->rect[1])+focus->rect[3]<=fine.Height &&
                std::isfinite(focus->jitter[0]) && std::isfinite(focus->jitter[1]) &&
                std::abs(focus->jitter[0])<=.5f && std::abs(focus->jitter[1])<=.5f &&
                SUCCEEDED(focus->texture->GetDevice(IID_PPV_ARGS(&owner))) &&
                owner.Get()==device) {
                std::copy(focus->rect.begin(),focus->rect.end(),data.m2_fovea_rect);
                data.m2_fovea_flags[0]=focus->jitter[0];
                data.m2_fovea_flags[1]=focus->jitter[1];
                data.m2_fovea_flags[2]=.075f; // fade through outer 7.5% of crop
                data.m2_fovea_flags[3]=1.f;
                fine_view.Format=focus->format;
                fovea_depth_lease=focus->lease;
                fine_ok=true;
            }
        }
        device->CreateShaderResourceView(fine_ok ? focus->texture : nullptr,&fine_view,focus_srv);
        fovea_depth_active=fine_ok;
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

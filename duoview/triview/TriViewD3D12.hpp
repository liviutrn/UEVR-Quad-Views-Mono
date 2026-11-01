#pragma once
// Tri-View Stage 1 D3D12 compositor (rendering method ID 7).
// One instance per OpenXR command slot, like DuoView's compositor: its descriptors and the
// resource references it holds stay alive until that slot's fence has retired.
// Writes the double-wide XR image in one draw; the XR pose/submission stays Joey's Native Stereo.
#include <d3d12.h>
#include <wrl/client.h>
#include <climits>
#include <cstdint>
#include <string>
#include "TriViewGeometry.hpp"
#include "TriViewShaderSource.hpp"

namespace uevr::triview::dx12 {
using Microsoft::WRL::ComPtr;

struct Constants {
    float eye_and_fovea[4];
    float fovea_window[4];
    float map_left[4];
    float map_right[4];
    float periphery_rect[4];
    float source_sizes[4];
    float params[4];
};
static_assert(sizeof(Constants) == 112, "Must match TriViewConstants in TriViewComposite.hlsl");

class Compositor {
public:
    // main / capture: Joey's Native Fix targets in RENDER_TARGET state (as his copy expects).
    // destination: the double-wide XR image in RENDER_TARGET state. All are left in those states.
    bool record(ID3D12Device* device, ID3D12GraphicsCommandList* cmd, ID3D12Resource* main,
                ID3D12Resource* capture, ID3D12Resource* destination, const PacketLayout& frame,
                bool border) {
        error_.clear();
        if (!device || !cmd || !main || !capture || !destination || main == capture ||
            main == destination || capture == destination || !frame.valid ||
            cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT) return reject("invalid inputs");
        const auto& l = frame.layout;
        const auto md = main->GetDesc(), cd = capture->GetDesc(), dd = destination->GetDesc();
        const auto plain = [](const D3D12_RESOURCE_DESC& d) {
            return d.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && d.DepthOrArraySize == 1 &&
                d.MipLevels == 1 && d.SampleDesc.Count == 1 && d.Width <= 32768 && d.Height <= 32768;
        };
        if (!plain(md) || !plain(cd) || !plain(dd) || (dd.Width & 1) || dd.Width < 2 ||
            !(dd.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) ||
            (md.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            (cd.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE)) return reject("unsupported resource shape");
        if (!l.fovea_width || !l.fovea_height || !l.periphery_width || !l.periphery_height ||
            md.Width < uint64_t(l.periphery_x) + l.periphery_width || md.Height < l.periphery_height ||
            md.Width < l.fovea_width || md.Height < l.fovea_height ||
            cd.Width < l.fovea_width || cd.Height < l.fovea_height) return reject("source smaller than layout");
        // Pixels must reach the XR image unchanged, like Joey's byte copy. Typeless images adopt the
        // other side's encoding (1 UNORM, 2 sRGB). A typed view cannot be recast, so if typed source
        // and XR encodings differ the shader undoes the conversion the hardware will apply.
        int source = 0;
        for (const auto f : {md.Format, cd.Format}) {
            const int e = encoding_of(f);
            if (e < 0) return reject("unsupported source colour format");
            if (e == 0) continue;
            if (source != 0 && source != e) return reject("main and capture colour encodings differ");
            source = e;
        }
        int output = encoding_of(dd.Format);
        if (output < 0) return reject("unsupported XR colour format");
        if (source == 0) source = output != 0 ? output : 1;
        if (output == 0) output = source;
        const auto rtv = typed(dd.Format, output == 2), main_srv = typed(md.Format, source == 2),
            capture_srv = typed(cd.Format, source == 2);
        const float convert = source == output ? 0.f : (output == 2 ? 1.f : 2.f); // 1 decode, 2 encode
        ComPtr<ID3D12Device> a, b, c, d;
        if (FAILED(main->GetDevice(IID_PPV_ARGS(&a))) || FAILED(capture->GetDevice(IID_PPV_ARGS(&b))) ||
            FAILED(destination->GetDevice(IID_PPV_ARGS(&c))) || FAILED(cmd->GetDevice(IID_PPV_ARGS(&d))) ||
            a.Get() != device || b.Get() != device || c.Get() != device || d.Get() != device)
            return reject("device mismatch");
        if (!prepare(device, rtv)) return false;

        if (main_ref_.Get() != main || capture_ref_.Get() != capture ||
            main_srv_ != main_srv || capture_srv_ != capture_srv) {
            D3D12_SHADER_RESOURCE_VIEW_DESC view{};
            view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
            view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            view.Texture2D.MipLevels = 1;
            auto cpu = srv_->GetCPUDescriptorHandleForHeapStart();
            view.Format = main_srv;
            device->CreateShaderResourceView(main, &view, cpu);
            cpu.ptr += device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
            view.Format = capture_srv;
            device->CreateShaderResourceView(capture, &view, cpu);
            main_ref_ = main; capture_ref_ = capture; main_srv_ = main_srv; capture_srv_ = capture_srv;
        }
        if (destination_ref_.Get() != destination || destination_rtv_ != rtv) {
            D3D12_RENDER_TARGET_VIEW_DESC view{};
            view.Format = rtv;
            view.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
            device->CreateRenderTargetView(destination, &view, rtv_->GetCPUDescriptorHandleForHeapStart());
            destination_ref_ = destination; destination_rtv_ = rtv;
        }

        const auto ml = periphery_map(l, 0), mr = periphery_map(l, 1);
        const Constants k{
            {float(dd.Width / 2), float(dd.Height), float(l.fovea_width), float(l.fovea_height)},
            {l.u0, l.v0, l.u1, l.v1},
            {ml.ax, ml.bx, ml.ay, ml.by},
            {mr.ax, mr.bx, mr.ay, mr.by},
            {float(l.periphery_x), 0.f, float(l.periphery_width), float(l.periphery_height)},
            {float(md.Width), float(md.Height), float(cd.Width), float(cd.Height)},
            {0.08f, frame.third ? 1.f : 0.f, border ? 1.f : 0.f, convert}};

        transition(cmd, main, D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        transition(cmd, capture, D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        ID3D12DescriptorHeap* heaps[]{srv_.Get()};
        cmd->SetDescriptorHeaps(1, heaps);
        cmd->SetGraphicsRootSignature(root_.Get());
        cmd->SetPipelineState(pipeline_.Get());
        cmd->SetGraphicsRootDescriptorTable(0, srv_->GetGPUDescriptorHandleForHeapStart());
        cmd->SetGraphicsRoot32BitConstants(1, sizeof(Constants) / 4, &k, 0);
        const D3D12_VIEWPORT viewport{0.f, 0.f, float(dd.Width), float(dd.Height), 0.f, 1.f};
        const D3D12_RECT scissor{0, 0, LONG(dd.Width), LONG(dd.Height)};
        cmd->RSSetViewports(1, &viewport);
        cmd->RSSetScissorRects(1, &scissor);
        const auto target = rtv_->GetCPUDescriptorHandleForHeapStart();
        cmd->OMSetRenderTargets(1, &target, FALSE, nullptr);
        cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        cmd->DrawInstanced(3, 1, 0, 0);
        transition(cmd, main, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
        transition(cmd, capture, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
        return true;
    }
    const std::string& error() const { return error_; }

private:
    bool reject(const char* why) { error_ = why; return false; }
    bool check(HRESULT hr, const char* what) {
        if (SUCCEEDED(hr)) return true;
        error_ = std::string(what) + " failed, HRESULT " + std::to_string(static_cast<uint32_t>(hr));
        return false;
    }
    static int encoding_of(DXGI_FORMAT f) {
        switch (f) {
        case DXGI_FORMAT_B8G8R8A8_TYPELESS: case DXGI_FORMAT_R8G8B8A8_TYPELESS: return 0;
        case DXGI_FORMAT_B8G8R8A8_UNORM: case DXGI_FORMAT_R8G8B8A8_UNORM: return 1;
        case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB: case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB: return 2;
        default: return -1;
        }
    }
    // The view format for an 8-bit BGRA/RGBA image (typeless or typed) in the chosen encoding.
    static DXGI_FORMAT typed(DXGI_FORMAT f, bool srgb) {
        const bool bgra = f == DXGI_FORMAT_B8G8R8A8_TYPELESS || f == DXGI_FORMAT_B8G8R8A8_UNORM ||
            f == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        if (bgra) return srgb ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        return srgb ? DXGI_FORMAT_R8G8B8A8_UNORM_SRGB : DXGI_FORMAT_R8G8B8A8_UNORM;
    }
    static void transition(ID3D12GraphicsCommandList* cmd, ID3D12Resource* r,
                           D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
        D3D12_RESOURCE_BARRIER b{};
        b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition = {r, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before, after};
        cmd->ResourceBarrier(1, &b);
    }
    // Root signature and heaps once per slot; the PSO again only if the XR format changes.
    bool prepare(ID3D12Device* device, DXGI_FORMAT rtv) {
        if (device_.Get() != device) {
            device_.Reset(); root_.Reset(); pipeline_.Reset(); srv_.Reset(); rtv_.Reset();
            main_ref_.Reset(); capture_ref_.Reset(); destination_ref_.Reset();
            pipeline_rtv_ = destination_rtv_ = main_srv_ = capture_srv_ = DXGI_FORMAT_UNKNOWN;
            D3D12_DESCRIPTOR_RANGE range{};
            range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
            range.NumDescriptors = 2;
            D3D12_ROOT_PARAMETER params[2]{};
            params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
            params[0].DescriptorTable = {1, &range};
            params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
            params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
            params[1].Constants = {0, 0, sizeof(Constants) / 4};
            params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
            D3D12_STATIC_SAMPLER_DESC sampler{};
            sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
            sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
            sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_ALWAYS;
            sampler.MaxAnisotropy = 1;
            sampler.MaxLOD = D3D12_FLOAT32_MAX;
            sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
            const D3D12_ROOT_SIGNATURE_DESC desc{2, params, 1, &sampler, D3D12_ROOT_SIGNATURE_FLAG_NONE};
            ComPtr<ID3DBlob> blob, errors;
            if (!check(D3D12SerializeRootSignature(&desc, D3D_ROOT_SIGNATURE_VERSION_1, &blob, &errors), "Root signature") ||
                !check(device->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(),
                    IID_PPV_ARGS(&root_)), "CreateRootSignature")) return false;
            D3D12_DESCRIPTOR_HEAP_DESC heap{};
            heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
            heap.NumDescriptors = 2;
            heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
            if (!check(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&srv_)), "SRV heap")) return false;
            heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
            heap.NumDescriptors = 1;
            heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
            if (!check(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&rtv_)), "RTV heap")) return false;
            device_ = device;
        }
        if (pipeline_ && pipeline_rtv_ == rtv) return true;
        pipeline_.Reset();
        D3D12_GRAPHICS_PIPELINE_STATE_DESC g{};
        g.pRootSignature = root_.Get();
        g.VS = {triview_vertex_shader_bytecode, sizeof(triview_vertex_shader_bytecode)};
        g.PS = {triview_pixel_shader_bytecode, sizeof(triview_pixel_shader_bytecode)};
        auto& blend = g.BlendState.RenderTarget[0];
        blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
        blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
        blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
        blend.LogicOp = D3D12_LOGIC_OP_NOOP;
        blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
        g.SampleMask = UINT_MAX;
        g.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
        g.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
        g.RasterizerState.DepthClipEnable = TRUE;
        g.DepthStencilState.DepthEnable = FALSE;
        g.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ZERO;
        g.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        g.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        g.NumRenderTargets = 1;
        g.RTVFormats[0] = rtv;
        g.SampleDesc.Count = 1;
        if (!check(device->CreateGraphicsPipelineState(&g, IID_PPV_ARGS(&pipeline_)), "Tri-View PSO")) return false;
        pipeline_rtv_ = rtv;
        return true;
    }

    ComPtr<ID3D12Device> device_;
    ComPtr<ID3D12RootSignature> root_;
    ComPtr<ID3D12PipelineState> pipeline_;
    ComPtr<ID3D12DescriptorHeap> srv_, rtv_;
    ComPtr<ID3D12Resource> main_ref_, capture_ref_, destination_ref_;
    DXGI_FORMAT pipeline_rtv_{DXGI_FORMAT_UNKNOWN}, destination_rtv_{DXGI_FORMAT_UNKNOWN};
    DXGI_FORMAT main_srv_{DXGI_FORMAT_UNKNOWN}, capture_srv_{DXGI_FORMAT_UNKNOWN};
    std::string error_;
};

} // namespace uevr::triview::dx12

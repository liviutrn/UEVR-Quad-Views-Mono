#pragma once
#include "SurfaceGeometry.hpp"
#include "DuoViewShaderSource.hpp"
#include <d3d12.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <cstdint>
#include <cstring>
#include <string>

namespace uevr::duoview::dx12 {
struct alignas(16) SurfaceConstants {
    float source_eye_from_clip[16]{};
    float target_clip_from_source_eye[16]{};
    float target_full_clip_from_source_eye[16]{};
    float target_eye_from_clip[16]{},source_clip_from_target_eye[16]{};
    uint32_t mesh_config[4]{};
    float edge[4]{2.f,.025f,.01f,1.e8f};
    float visibility[4]{2.f,.025f,1.f,0.f};
    float jitter[4]{};
    float quality[4]{1.f,.015f,1.f,1.f};
};
static_assert(sizeof(SurfaceConstants)==400);

// One instance belongs to one already-fenced XR command slot. The first opt-in
// use (or a layout change) allocates exact-sized maps before recording commands.
// Normal frames reuse all GPU objects; mode 0 allocates no surface resources.
class SurfaceReprojector {
    template<class T> using Ptr=Microsoft::WRL::ComPtr<T>;
    Ptr<ID3D12Device> device_;
    Ptr<ID3D12RootSignature> root_;
    Ptr<ID3D12PipelineState> reverse_,forward_,backward_;
    Ptr<ID3D12DescriptorHeap> rtv_,dsv_;
    Ptr<ID3D12Resource> color_[2],depth_[2],constants_;
    UINT width_[2]{},height_[2]{};
    UINT rtv_stride_{},dsv_stride_{};
    bool srgb_{};
    std::string error_;
    bool check(HRESULT hr,const char* reason) {
        if(SUCCEEDED(hr))return true;
        error_=std::string(reason)+" HRESULT="+std::to_string(uint32_t(hr));return false;
    }
    D3D12_CPU_DESCRIPTOR_HANDLE rtv(UINT pass) const {auto h=rtv_->GetCPUDescriptorHandleForHeapStart();h.ptr+=pass*rtv_stride_;return h;}
    D3D12_CPU_DESCRIPTOR_HANDLE dsv(UINT pass) const {auto h=dsv_->GetCPUDescriptorHandleForHeapStart();h.ptr+=pass*dsv_stride_;return h;}
    static void transition(ID3D12GraphicsCommandList* cmd,ID3D12Resource* resource,
            D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after) {
        D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition={resource,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};cmd->ResourceBarrier(1,&b);
    }
    bool create_objects(ID3D12Device* device,bool srgb) {
        device_=device;srgb_=srgb;
        D3D12_DESCRIPTOR_RANGE range{};range.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_SRV;range.NumDescriptors=6;
        D3D12_ROOT_PARAMETER params[3]{};
        params[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;params[0].DescriptorTable={1,&range};
        params[0].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
        params[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;params[1].Constants={0,0,60};
        params[1].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
        params[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV;params[2].Descriptor={1,0};
        params[2].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
        static_assert(1+60+2<=64);
        D3D12_STATIC_SAMPLER_DESC sampler{};sampler.Filter=D3D12_FILTER_MIN_MAG_MIP_LINEAR;
        sampler.AddressU=sampler.AddressV=sampler.AddressW=D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
        sampler.ComparisonFunc=D3D12_COMPARISON_FUNC_ALWAYS;sampler.MaxLOD=D3D12_FLOAT32_MAX;
        sampler.MaxAnisotropy=1;sampler.ShaderVisibility=D3D12_SHADER_VISIBILITY_PIXEL;
        const D3D12_ROOT_SIGNATURE_DESC desc{3,params,1,&sampler,D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT};
        Ptr<ID3DBlob> serialized,errors;
        if(!check(D3D12SerializeRootSignature(&desc,D3D_ROOT_SIGNATURE_VERSION_1,&serialized,&errors),"Surface root serialization")||
           !check(device->CreateRootSignature(0,serialized->GetBufferPointer(),serialized->GetBufferSize(),IID_PPV_ARGS(&root_)),"Surface root"))return false;
        D3D12_GRAPHICS_PIPELINE_STATE_DESC p{};p.pRootSignature=root_.Get();
        p.VS={surface_vertex_shader_bytecode,sizeof(surface_vertex_shader_bytecode)};
        p.PS={surface_pixel_shader_bytecode,sizeof(surface_pixel_shader_bytecode)};
        auto& blend=p.BlendState.RenderTarget[0];blend.SrcBlend=blend.SrcBlendAlpha=D3D12_BLEND_ONE;
        blend.DestBlend=blend.DestBlendAlpha=D3D12_BLEND_ZERO;blend.BlendOp=blend.BlendOpAlpha=D3D12_BLEND_OP_ADD;
        blend.LogicOp=D3D12_LOGIC_OP_NOOP;blend.RenderTargetWriteMask=D3D12_COLOR_WRITE_ENABLE_ALL;
        p.SampleMask=UINT_MAX;p.SampleDesc.Count=1;p.NumRenderTargets=1;
        p.RTVFormats[0]=srgb?DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:DXGI_FORMAT_B8G8R8A8_UNORM;
        p.DSVFormat=DXGI_FORMAT_D32_FLOAT;p.PrimitiveTopologyType=D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        p.RasterizerState.FillMode=D3D12_FILL_MODE_SOLID;p.RasterizerState.CullMode=D3D12_CULL_MODE_NONE;
        p.RasterizerState.DepthClipEnable=TRUE;
        p.DepthStencilState.DepthEnable=TRUE;p.DepthStencilState.DepthWriteMask=D3D12_DEPTH_WRITE_MASK_ALL;
        p.DepthStencilState.DepthFunc=D3D12_COMPARISON_FUNC_GREATER_EQUAL;
        if(!check(device->CreateGraphicsPipelineState(&p,IID_PPV_ARGS(&reverse_)),"Reverse-depth surface PSO"))return false;
        p.DepthStencilState.DepthFunc=D3D12_COMPARISON_FUNC_LESS_EQUAL;
        if(!check(device->CreateGraphicsPipelineState(&p,IID_PPV_ARGS(&forward_)),"Forward-depth surface PSO"))return false;
        p.VS={vertex_shader_bytecode,sizeof(vertex_shader_bytecode)};
        p.PS={backward_pixel_shader_bytecode,sizeof(backward_pixel_shader_bytecode)};
        p.DepthStencilState.DepthFunc=D3D12_COMPARISON_FUNC_ALWAYS;
        if(!check(device->CreateGraphicsPipelineState(&p,IID_PPV_ARGS(&backward_)),"Backward dual-depth fovea PSO"))return false;
        D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.NumDescriptors=2;hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        if(!check(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&rtv_)),"Surface RTV heap"))return false;
        hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_DSV;
        if(!check(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&dsv_)),"Surface DSV heap"))return false;
        rtv_stride_=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
        dsv_stride_=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_DSV);
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_UPLOAD;heap.CreationNodeMask=heap.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC buffer{};buffer.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;buffer.Width=1024;
        buffer.Height=buffer.DepthOrArraySize=buffer.MipLevels=1;buffer.SampleDesc.Count=1;buffer.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        return check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&buffer,D3D12_RESOURCE_STATE_GENERIC_READ,
            nullptr,IID_PPV_ARGS(&constants_)),"Surface constant upload");
    }
    bool create_map(UINT pass,UINT width,UINT height) {
        if(color_[pass]&&depth_[pass]&&width_[pass]==width&&height_[pass]==height)return true;
        color_[pass].Reset();depth_[pass].Reset();
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;heap.CreationNodeMask=heap.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;desc.Width=width;desc.Height=height;
        desc.DepthOrArraySize=desc.MipLevels=1;desc.SampleDesc.Count=1;desc.Format=DXGI_FORMAT_B8G8R8A8_TYPELESS;
        desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
        if(!check(device_->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,
            nullptr,IID_PPV_ARGS(&color_[pass])),"Surface color map"))return false;
        D3D12_RENDER_TARGET_VIEW_DESC view{};view.Format=srgb_?DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:DXGI_FORMAT_B8G8R8A8_UNORM;
        view.ViewDimension=D3D12_RTV_DIMENSION_TEXTURE2D;device_->CreateRenderTargetView(color_[pass].Get(),&view,rtv(pass));
        desc.Format=DXGI_FORMAT_D32_FLOAT;desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL;
        if(!check(device_->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,D3D12_RESOURCE_STATE_DEPTH_WRITE,
            nullptr,IID_PPV_ARGS(&depth_[pass])),"Surface visibility depth"))return false;
        device_->CreateDepthStencilView(depth_[pass].Get(),nullptr,dsv(pass));
        width_[pass]=width;height_[pass]=height;return true;
    }
public:
    const std::string& error() const {return error_;}
    ID3D12Resource* color(UINT pass) const {return color_[pass].Get();}
    bool prepare(ID3D12Device* device,bool srgb,UINT fw,UINT fh,UINT pw,UINT ph,
            const std::array<SurfaceConstants,2>& constants) {
        if(!device||!fw||!fh||!pw||!ph||fw>16384||fh>16384||pw>16384||ph>16384)return false;
        if(device_.Get()!=device||srgb_!=srgb||!root_||!reverse_||!forward_||!backward_||!constants_||!rtv_||!dsv_) {
            *this=SurfaceReprojector{};
            if(!create_objects(device,srgb))return false;
        }
        if(!create_map(0,fw,fh)||!create_map(1,pw,ph))return false;
        void* data{};D3D12_RANGE read{0,0};
        if(!check(constants_->Map(0,&read,&data),"Surface constant map"))return false;
        for(size_t pass=0;pass<2;++pass)
            std::memcpy(static_cast<uint8_t*>(data)+pass*512,&constants[pass],sizeof(SurfaceConstants));
        D3D12_RANGE written{0,1024};constants_->Unmap(0,&written);return true;
    }
    void record(ID3D12GraphicsCommandList* cmd,ID3D12DescriptorHeap* heap,
            D3D12_GPU_DESCRIPTOR_HANDLE srvs,const void* composite_constants,
            const std::array<SurfaceConstants,2>& constants,const std::array<bool,2>& reverse,
            bool periphery) {
        ID3D12DescriptorHeap* heaps[]{heap};cmd->SetDescriptorHeaps(1,heaps);
        cmd->SetGraphicsRootSignature(root_.Get());cmd->SetGraphicsRootDescriptorTable(0,srvs);
        cmd->SetGraphicsRoot32BitConstants(1,60,composite_constants,0);
        for(UINT pass=0;pass<(periphery?2u:1u);++pass) {
            transition(cmd,color_[pass].Get(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
            const float clear[4]{};const auto color_handle=rtv(pass),depth_handle=dsv(pass);
            cmd->ClearRenderTargetView(color_handle,clear,0,nullptr);
            cmd->ClearDepthStencilView(depth_handle,D3D12_CLEAR_FLAG_DEPTH,reverse[pass]?0.f:1.f,0,0,nullptr);
            const D3D12_VIEWPORT viewport{0,0,float(width_[pass]),float(height_[pass]),0,1};
            const D3D12_RECT rect{0,0,LONG(width_[pass]),LONG(height_[pass])};
            cmd->RSSetViewports(1,&viewport);cmd->RSSetScissorRects(1,&rect);
            cmd->OMSetRenderTargets(1,&color_handle,FALSE,&depth_handle);
            cmd->SetPipelineState(reverse[pass]?reverse_.Get():forward_.Get());
            cmd->SetGraphicsRootConstantBufferView(2,constants_->GetGPUVirtualAddress()+pass*512);
            cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            const auto& config=constants[pass].mesh_config;
            const bool backward=pass==0 && (config[3]&2u)!=0;
            if(backward) {
                cmd->SetPipelineState(backward_.Get());cmd->DrawInstanced(3,1,0,0);
                cmd->SetPipelineState(reverse[pass]?reverse_.Get():forward_.Get());
            }
            if(!backward || constants[pass].quality[3]>.5f)
                cmd->DrawInstanced((config[0]-1)*(config[1]-1)*6,1,0,0);
            transition(cmd,color_[pass].Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        }
    }
};
}

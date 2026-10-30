#pragma once
#include "DuoViewGeometry.hpp"
#include "DuoViewNgxGuide.hpp"
#include "DuoViewShaderSource.hpp"
#include "DuoViewState.hpp"
#include "SurfaceGeometry.hpp"
#include <d3d12.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <chrono>
#include <string>

namespace uevr::duoview::dx12 {

struct alignas(16) DepthStabilizeConstants {
    float current_eye_from_clip[16]{};
    float previous_clip_from_current_eye[16]{};
    float previous_eye_from_clip[16]{};
    float current_eye_from_previous_eye[16]{};
    float current_clip_from_current_eye[16]{};
    float active_rect[4]{};
    float current_projection[4]{};
    float previous_projection[4]{};
    float current_range_jitter[4]{};
    float previous_range_weight[4]{};
    float edge_tolerances[4]{};
    float previous_rect[4]{};
};
static_assert(sizeof(DepthStabilizeConstants)==432);

// Per-command-slot, per-eye jitter removal and conservative temporal history.
// The owner is one fenced compositor slot; history never crosses eye or slot.
// It writes full-allocation R32_FLOAT maps whose values remain in the input
// device-depth range, so every downstream depth reader can use the same rect.
class DepthStabilizer {
    template<class T> using Ptr=Microsoft::WRL::ComPtr<T>;
    using Matrix=surface::Matrix;
    Ptr<ID3D12Device> device_;
    Ptr<ID3D12RootSignature> root_;
    Ptr<ID3D12PipelineState> pipeline_;
    Ptr<ID3D12DescriptorHeap> srv_heap_,rtv_heap_;
    Ptr<ID3D12Resource> constants_;
    Ptr<ID3D12Resource> raw_[2];
    Ptr<ID3D12Resource> history_[2][2];
    UINT width_[2]{},height_[2]{};
    DXGI_FORMAT raw_format_[2]{DXGI_FORMAT_UNKNOWN,DXGI_FORMAT_UNKNOWN};
    UINT srv_stride_{},rtv_stride_{};
    int history_index_[2]{-1,-1};
    int write_index_[2]{-1,-1};
    bool history_valid_[2]{};
    bool previous_temporal_[2]{};
    uint64_t previous_generation_{},previous_frame_{};
    uint64_t previous_feature_generation_[2]{};
    uintptr_t previous_feature_[2]{};
    uint32_t previous_reset_[2]{};
    CameraPose previous_camera_[2]{};
    std::array<float,16> previous_projection_[2]{};
    DepthViewport previous_viewport_[2]{};
    std::array<float,4> previous_crop_{};
    bool have_previous_frame_{};
    std::chrono::steady_clock::time_point previous_record_time_{};
    uint64_t pending_generation_{},pending_frame_{};
    uint64_t pending_feature_generation_[2]{};
    uintptr_t pending_feature_[2]{};
    uint32_t pending_reset_[2]{};
    CameraPose pending_camera_[2]{};
    std::array<float,16> pending_projection_[2]{};
    DepthViewport pending_viewport_[2]{};
    std::array<float,4> pending_crop_{};
    bool pending_temporal_{};
    std::string error_;

    static DXGI_FORMAT depth_srv_format(DXGI_FORMAT f) {
        switch(f) {
        case DXGI_FORMAT_R32_TYPELESS: case DXGI_FORMAT_R32_FLOAT:return DXGI_FORMAT_R32_FLOAT;
        case DXGI_FORMAT_R24G8_TYPELESS:return DXGI_FORMAT_R24_UNORM_X8_TYPELESS;
        case DXGI_FORMAT_R32G8X24_TYPELESS:return DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS;
        case DXGI_FORMAT_R16_TYPELESS:return DXGI_FORMAT_R16_UNORM;
        case DXGI_FORMAT_R16_FLOAT:return DXGI_FORMAT_R16_FLOAT;
        default:return DXGI_FORMAT_UNKNOWN;
        }
    }
    bool check(HRESULT hr,const char* operation) {
        if(SUCCEEDED(hr))return true;
        error_=std::string(operation)+" HRESULT="+std::to_string(uint32_t(hr));return false;
    }
    D3D12_CPU_DESCRIPTOR_HANDLE srv_cpu(UINT index) const {
        auto h=srv_heap_->GetCPUDescriptorHandleForHeapStart();h.ptr+=SIZE_T(index)*srv_stride_;return h;
    }
    D3D12_GPU_DESCRIPTOR_HANDLE srv_gpu(UINT index) const {
        auto h=srv_heap_->GetGPUDescriptorHandleForHeapStart();h.ptr+=UINT64(index)*srv_stride_;return h;
    }
    D3D12_CPU_DESCRIPTOR_HANDLE rtv_cpu(UINT index) const {
        auto h=rtv_heap_->GetCPUDescriptorHandleForHeapStart();h.ptr+=SIZE_T(index)*rtv_stride_;return h;
    }
    static void transition(ID3D12GraphicsCommandList* cmd,ID3D12Resource* resource,
            D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after) {
        if(before==after)return;
        D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition={resource,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};cmd->ResourceBarrier(1,&b);
    }
    bool create_objects(ID3D12Device* device) {
        device_=device;
        D3D12_DESCRIPTOR_RANGE range{};range.RangeType=D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        range.NumDescriptors=2;range.BaseShaderRegister=0;range.RegisterSpace=0;
        range.OffsetInDescriptorsFromTableStart=D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
        D3D12_ROOT_PARAMETER params[2]{};
        params[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        params[0].DescriptorTable={1,&range};params[0].ShaderVisibility=D3D12_SHADER_VISIBILITY_PIXEL;
        params[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV;params[1].Descriptor={0,0};
        params[1].ShaderVisibility=D3D12_SHADER_VISIBILITY_PIXEL;
        const D3D12_ROOT_SIGNATURE_DESC root_desc{2,params,0,nullptr,D3D12_ROOT_SIGNATURE_FLAG_NONE};
        Ptr<ID3DBlob> serialized,errors;
        if(!check(D3D12SerializeRootSignature(&root_desc,D3D_ROOT_SIGNATURE_VERSION_1,&serialized,&errors),
                    "Depth stabilizer root serialization")||
           !check(device->CreateRootSignature(0,serialized->GetBufferPointer(),serialized->GetBufferSize(),
                    IID_PPV_ARGS(&root_)),"Depth stabilizer root signature"))return false;
        D3D12_GRAPHICS_PIPELINE_STATE_DESC p{};p.pRootSignature=root_.Get();
        p.VS={vertex_shader_bytecode,sizeof(vertex_shader_bytecode)};
        p.PS={depth_stabilize_pixel_shader_bytecode,sizeof(depth_stabilize_pixel_shader_bytecode)};
        auto& blend=p.BlendState.RenderTarget[0];blend.SrcBlend=blend.SrcBlendAlpha=D3D12_BLEND_ONE;
        blend.DestBlend=blend.DestBlendAlpha=D3D12_BLEND_ZERO;
        blend.BlendOp=blend.BlendOpAlpha=D3D12_BLEND_OP_ADD;blend.LogicOp=D3D12_LOGIC_OP_NOOP;
        blend.RenderTargetWriteMask=D3D12_COLOR_WRITE_ENABLE_ALL;
        p.SampleMask=UINT_MAX;p.NumRenderTargets=1;p.RTVFormats[0]=DXGI_FORMAT_R32_FLOAT;
        p.SampleDesc.Count=1;p.PrimitiveTopologyType=D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        p.RasterizerState.FillMode=D3D12_FILL_MODE_SOLID;p.RasterizerState.CullMode=D3D12_CULL_MODE_NONE;
        p.RasterizerState.DepthClipEnable=TRUE;
        p.DepthStencilState.DepthEnable=FALSE;p.DepthStencilState.DepthWriteMask=D3D12_DEPTH_WRITE_MASK_ZERO;
        p.DepthStencilState.DepthFunc=D3D12_COMPARISON_FUNC_ALWAYS;
        if(!check(device->CreateGraphicsPipelineState(&p,IID_PPV_ARGS(&pipeline_)),"Depth stabilizer PSO"))return false;
        D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        hd.NumDescriptors=4;hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        if(!check(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&srv_heap_)),"Depth stabilizer SRV heap"))return false;
        hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_RTV;hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
        if(!check(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&rtv_heap_)),"Depth stabilizer RTV heap"))return false;
        srv_stride_=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        rtv_stride_=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_UPLOAD;
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC buffer{};buffer.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width=1024;buffer.Height=1;buffer.DepthOrArraySize=1;buffer.MipLevels=1;
        buffer.SampleDesc.Count=1;buffer.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if(!check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&buffer,
                D3D12_RESOURCE_STATE_GENERIC_READ,nullptr,IID_PPV_ARGS(&constants_)),
                "Depth stabilizer constants"))return false;
        return true;
    }
    bool create_history(UINT eye,UINT width,UINT height) {
        history_[eye][0].Reset();history_[eye][1].Reset();
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width=width;desc.Height=height;desc.DepthOrArraySize=1;desc.MipLevels=1;
        desc.Format=DXGI_FORMAT_R32_FLOAT;desc.SampleDesc.Count=1;
        desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
        const D3D12_RESOURCE_STATES initial=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|
                                               D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        for(UINT ping=0;ping<2;++ping) {
            if(!check(device_->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,initial,
                    nullptr,IID_PPV_ARGS(&history_[eye][ping])),"Depth stabilizer output"))return false;
            D3D12_RENDER_TARGET_VIEW_DESC view{};view.Format=DXGI_FORMAT_R32_FLOAT;
            view.ViewDimension=D3D12_RTV_DIMENSION_TEXTURE2D;
            device_->CreateRenderTargetView(history_[eye][ping].Get(),&view,rtv_cpu(eye*2+ping));
        }
        width_[eye]=width;height_[eye]=height;history_index_[eye]=-1;write_index_[eye]=-1;
        previous_temporal_[eye]=false;return true;
    }
    static void copy_matrix(float dst[16],const Matrix& src) {
        for(size_t k=0;k<16;++k)dst[k]=float(src[k]);
    }
    static bool finite_matrix(const Matrix& m) {
        for(double x:m)if(!std::isfinite(x))return false;return true;
    }
    static bool same_rect(const DepthViewport& a,const DepthViewport& b,bool allow_translation) {
        return (allow_translation||(std::abs(a.x-b.x)<1.e-4f&&std::abs(a.y-b.y)<1.e-4f))&&
               std::abs(a.width-b.width)<1.e-4f&&std::abs(a.height-b.height)<1.e-4f&&
               std::abs(a.min_depth-b.min_depth)<1.e-7f&&std::abs(a.max_depth-b.max_depth)<1.e-7f;
    }
    static bool same_projection(const std::array<float,16>& a,const std::array<float,16>& b) {
        for(size_t k=0;k<16;++k)if(!std::isfinite(a[k])||!std::isfinite(b[k])||std::abs(a[k]-b[k])>1.e-5f)return false;
        return true;
    }
    bool temporal_history_valid(UINT eye,const ViewFrame& frame,const ngx::Guide& guide,
            const DepthViewport& viewport,const std::array<float,4>& crop,float weight) const {
        if(weight<=0.f||!have_previous_frame_||history_index_[eye]<0||!previous_temporal_[eye])return false;
        const uint64_t generation=uint64_t(frame.config.key.generation),number=uint64_t(frame.config.key.frame);
        if(!generation||!number||generation!=previous_generation_||number<=previous_frame_||number-previous_frame_>8)return false;
        if(guide.reset!=0||guide.feature!=previous_feature_[eye]||
           guide.feature_generation!=previous_feature_generation_[eye]||
           guide.reset!=previous_reset_[eye])return false;
        if(!same_rect(viewport,previous_viewport_[eye],eye==0))return false;
        if(eye==0 && (std::abs((crop[1]-crop[0])-(previous_crop_[1]-previous_crop_[0]))>1.e-6f||
                      std::abs((crop[3]-crop[2])-(previous_crop_[3]-previous_crop_[2]))>1.e-6f))return false;
        const auto& projection=eye==0?frame.projection:frame.projection_right;
        if(!same_projection(projection,previous_projection_[eye]))return false;
        if(std::chrono::steady_clock::now()-previous_record_time_>std::chrono::milliseconds(250))return false;
        return true;
    }
public:
    const std::string& error() const {return error_;}
    ID3D12Resource* left() const {return write_index_[0]>=0?history_[0][write_index_[0]].Get():nullptr;}
    ID3D12Resource* right() const {return write_index_[1]>=0?history_[1][write_index_[1]].Get():nullptr;}
    bool ready() const {return write_index_[0]>=0&&write_index_[1]>=0;}
    void reset() {
        history_index_[0]=history_index_[1]=-1;
        write_index_[0]=write_index_[1]=-1;
        previous_temporal_[0]=previous_temporal_[1]=false;
        have_previous_frame_=false;previous_generation_=previous_frame_=0;
    }

    bool prepare(ID3D12Device* device,const ViewFrame& frame,const std::array<ngx::Guide,2>& guides,
            ID3D12Resource* raw_left,ID3D12Resource* raw_right,
            const DepthViewport& left_view,const DepthViewport& right_view,float history_weight) {
        error_.clear();write_index_[0]=write_index_[1]=-1;
        if(!device||!raw_left||!raw_right||raw_left==raw_right||!guides[0]||!guides[1]) {
            error_="Depth stabilization requires a valid device, distinct per-eye depths, and paired NGX guides";return false;
        }
        if(frame.invalid||!frame.camera_valid||!frame.projections[0]||!frame.projections[1]||
           !frame.cameras[0]||!frame.cameras[1]) {
            error_="Depth stabilization requires frozen per-eye camera and projection metadata";return false;
        }
        history_weight=std::isfinite(history_weight)?std::clamp(history_weight,0.f,.9f):0.f;
        ID3D12Resource* raw[]{raw_left,raw_right};
        const DepthViewport views[]{left_view,right_view};
        const std::array<float,16>* projections[]{&frame.projection,&frame.projection_right};
        bool recreate=device_.Get()!=device||!root_||!pipeline_||!constants_||!srv_heap_||!rtv_heap_;
        for(UINT eye=0;eye<2;++eye) {
            if(!raw[eye])return false;
            const auto d=raw[eye]->GetDesc();
            const DXGI_FORMAT input_format=depth_srv_format(d.Format);
            if(d.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D||d.SampleDesc.Count!=1||
               !d.Width||!d.Height||d.Width>16384||d.Height>16384||input_format==DXGI_FORMAT_UNKNOWN||
               !depth_viewport_valid(views[eye],d.Width,UINT(d.Height))) {
                error_="Depth stabilizer received unsupported depth texture or invalid viewport";return false;
            }
            if(width_[eye]!=UINT(d.Width)||height_[eye]!=UINT(d.Height)||raw_format_[eye]!=d.Format)recreate=true;
        }
        if(recreate) {
            *this=DepthStabilizer{};
            if(!create_objects(device))return false;
            for(UINT eye=0;eye<2;++eye) {
                const auto d=raw[eye]->GetDesc();raw_format_[eye]=d.Format;
                if(!create_history(eye,UINT(d.Width),UINT(d.Height)))return false;
            }
        }
        const float crop[4]{frame.config.layout.u0,frame.config.layout.u1,
                            frame.config.layout.v0,frame.config.layout.v1};
        pending_crop_={crop[0],crop[1],crop[2],crop[3]};
        pending_generation_=uint64_t(frame.config.key.generation);
        pending_frame_=uint64_t(frame.config.key.frame);
        pending_temporal_=history_weight>0.f;
        const CameraPose* current_camera[]{&frame.eye_cameras[0],&frame.eye_cameras[1]};
        DepthStabilizeConstants constants[2]{};
        for(UINT eye=0;eye<2;++eye) {
            auto projection=surface::projection(*projections[eye]);
            // LEFT depth belongs to the frozen foveal crop. Its raw device-Z
            // coefficients are unchanged by crop(), while X/Y ray mapping is.
            if(eye==0)projection=surface::crop(projection,
                frame.config.layout.u0,frame.config.layout.v0,
                frame.config.layout.u1,frame.config.layout.v1);
            const auto inverse_projection=surface::inverse(projection);
            if(!inverse_projection||!finite_matrix(projection)) {
                error_="Depth stabilizer camera projection is singular";return false;
            }
            const bool use_history=temporal_history_valid(eye,frame,guides[eye],views[eye],
                {crop[0],crop[1],crop[2],crop[3]},history_weight);
            history_valid_[eye]=use_history;
            write_index_[eye]=history_index_[eye]<0?0:(history_index_[eye]^1);
            const auto* old_camera=use_history?&previous_camera_[eye]:current_camera[eye];
            const auto& old_projection_data=use_history?previous_projection_[eye]:*projections[eye];
            auto old_projection=surface::projection(old_projection_data);
            if(eye==0)old_projection=surface::crop(old_projection,
                use_history?previous_crop_[0]:crop[0],use_history?previous_crop_[2]:crop[2],
                use_history?previous_crop_[1]:crop[1],use_history?previous_crop_[3]:crop[3]);
            const auto old_inverse=surface::inverse(old_projection);
            if(!old_inverse) {history_valid_[eye]=false;}
            const auto previous_eye_from_clip=history_valid_[eye]?*old_inverse:*inverse_projection;
            const auto previous_from_current=surface::target_eye_from_source(
                current_camera[eye]->rotation,current_camera[eye]->position,
                old_camera->rotation,old_camera->position,1.0);
            const auto current_from_previous=surface::target_eye_from_source(
                old_camera->rotation,old_camera->position,
                current_camera[eye]->rotation,current_camera[eye]->position,1.0);
            if(!finite_matrix(previous_from_current)||!finite_matrix(current_from_previous)) {
                error_="Depth stabilizer camera reprojection transform is invalid";return false;
            }
            const auto old_clip=surface::multiply(old_projection,previous_from_current);
            auto& c=constants[eye];
            copy_matrix(c.current_eye_from_clip,*inverse_projection);
            copy_matrix(c.previous_clip_from_current_eye,old_clip);
            copy_matrix(c.previous_eye_from_clip,previous_eye_from_clip);
            copy_matrix(c.current_eye_from_previous_eye,current_from_previous);
            copy_matrix(c.current_clip_from_current_eye,projection);
            c.active_rect[0]=views[eye].x;c.active_rect[1]=views[eye].y;
            c.active_rect[2]=views[eye].width;c.active_rect[3]=views[eye].height;
            c.current_projection[0]=(*projections[eye])[10];c.current_projection[1]=(*projections[eye])[14];
            c.current_projection[2]=(*projections[eye])[11];c.current_projection[3]=(*projections[eye])[15];
            c.previous_projection[0]=old_projection_data[10];c.previous_projection[1]=old_projection_data[14];
            c.previous_projection[2]=old_projection_data[11];c.previous_projection[3]=old_projection_data[15];
            c.current_range_jitter[0]=views[eye].min_depth;c.current_range_jitter[1]=views[eye].max_depth;
            // Guide jitter is expressed in the NGX input grid. Convert it to
            // the active raw-depth grid exactly as the reconstruction shader's
            // normalized jitter UV is scaled by DepthViewport dimensions.
            c.current_range_jitter[2]=guides[eye].jitter_x*views[eye].width/float(guides[eye].input_width);
            c.current_range_jitter[3]=guides[eye].jitter_y*views[eye].height/float(guides[eye].input_height);
            const auto previous_view=history_valid_[eye]?previous_viewport_[eye]:views[eye];
            c.previous_range_weight[0]=previous_view.min_depth;c.previous_range_weight[1]=previous_view.max_depth;
            c.previous_range_weight[2]=history_valid_[eye]?history_weight:0.f;
            c.previous_range_weight[3]=history_valid_[eye]?1.f:0.f;
            c.edge_tolerances[0]=2.f;c.edge_tolerances[1]=.015f;
            c.edge_tolerances[2]=1.5f;c.edge_tolerances[3]=80.f;
            const auto old_view=history_valid_[eye]?previous_viewport_[eye]:views[eye];
            c.previous_rect[0]=old_view.x;c.previous_rect[1]=old_view.y;
            c.previous_rect[2]=old_view.width;c.previous_rect[3]=old_view.height;
            pending_camera_[eye]=*current_camera[eye];
            pending_projection_[eye]=*projections[eye];
            pending_viewport_[eye]=views[eye];
            pending_feature_[eye]=guides[eye].feature;
            pending_feature_generation_[eye]=guides[eye].feature_generation;
            pending_reset_[eye]=guides[eye].reset;
            raw_[eye]=raw[eye];
            D3D12_SHADER_RESOURCE_VIEW_DESC view{};view.Format=depth_srv_format(raw_format_[eye]);
            view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;view.Texture2D.MipLevels=1;
            const UINT base=eye*2;
            device->CreateShaderResourceView(raw[eye],&view,srv_cpu(base));
            view.Format=DXGI_FORMAT_R32_FLOAT;
            ID3D12Resource* old=history_[eye][history_index_[eye]<0?1:history_index_[eye]].Get();
            device->CreateShaderResourceView(old,&view,srv_cpu(base+1));
        }
        void* mapped{};D3D12_RANGE read{0,0};
        if(!check(constants_->Map(0,&read,&mapped),"Depth stabilizer constant map"))return false;
        for(UINT eye=0;eye<2;++eye)
            std::memcpy(static_cast<uint8_t*>(mapped)+eye*512,&constants[eye],sizeof(DepthStabilizeConstants));
        D3D12_RANGE written{0,1024};constants_->Unmap(0,&written);
        return true;
    }

    // Raw inputs must already be in a shader-readable state. The output maps
    // finish in the combined state required by both pixel and vertex stages.
    bool record(ID3D12GraphicsCommandList* cmd) {
        if(!cmd||!ready()||cmd->GetType()!=D3D12_COMMAND_LIST_TYPE_DIRECT) {
            error_="Depth stabilizer record called without a prepared direct command list";return false;
        }
        ID3D12DescriptorHeap* heaps[]{srv_heap_.Get()};cmd->SetDescriptorHeaps(1,heaps);
        cmd->SetGraphicsRootSignature(root_.Get());cmd->SetPipelineState(pipeline_.Get());
        cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        const D3D12_RESOURCE_STATES readable=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|
                                               D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        for(UINT eye=0;eye<2;++eye) {
            auto* output=history_[eye][write_index_[eye]].Get();
            transition(cmd,output,readable,D3D12_RESOURCE_STATE_RENDER_TARGET);
            const auto target=rtv_cpu(eye*2+write_index_[eye]);
            const float clear[4]{};cmd->ClearRenderTargetView(target,clear,0,nullptr);
            const D3D12_VIEWPORT viewport{0,0,float(width_[eye]),float(height_[eye]),0,1};
            const D3D12_RECT rect{0,0,LONG(width_[eye]),LONG(height_[eye])};
            cmd->RSSetViewports(1,&viewport);cmd->RSSetScissorRects(1,&rect);
            cmd->OMSetRenderTargets(1,&target,FALSE,nullptr);
            cmd->SetGraphicsRootDescriptorTable(0,srv_gpu(eye*2));
            cmd->SetGraphicsRootConstantBufferView(1,constants_->GetGPUVirtualAddress()+UINT64(eye)*512);
            cmd->DrawInstanced(3,1,0,0);
            transition(cmd,output,D3D12_RESOURCE_STATE_RENDER_TARGET,readable);
        }
        for(UINT eye=0;eye<2;++eye)history_index_[eye]=write_index_[eye];
        previous_generation_=pending_generation_;previous_frame_=pending_frame_;
        previous_crop_=pending_crop_;have_previous_frame_=previous_generation_!=0&&previous_frame_!=0;
        previous_record_time_=std::chrono::steady_clock::now();
        for(UINT eye=0;eye<2;++eye) {
            previous_camera_[eye]=pending_camera_[eye];
            previous_projection_[eye]=pending_projection_[eye];
            previous_viewport_[eye]=pending_viewport_[eye];
            previous_feature_[eye]=pending_feature_[eye];
            previous_feature_generation_[eye]=pending_feature_generation_[eye];
            previous_reset_[eye]=pending_reset_[eye];
            previous_temporal_[eye]=pending_temporal_;
        }
        return true;
    }
};
}

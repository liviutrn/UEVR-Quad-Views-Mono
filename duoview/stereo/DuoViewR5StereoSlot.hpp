#pragma once
// DuoView B3: two exact R5 engines, one for each real UE producer camera.
// Owned by a specific OpenXR command slot and reused ONLY after its prior GPU
// command list is retired. No independent GPU submission or temporal depth reuse.
#include "d3d12/DIBRPreview.hpp"
#include "DuoViewState.hpp"
#include <array>
#include <cmath>
#include <wrl/client.h>

namespace uevr::duoview::r5 {
struct StereoSlot {
    d3d12::DIBRPreview fovea, periphery;
    Microsoft::WRL::ComPtr<ID3D12Resource> packed_fovea, packed_periphery;
    Microsoft::WRL::ComPtr<ID3D12Resource> native_fovea, native_periphery;
    Microsoft::WRL::ComPtr<ID3D12Resource> depth_fovea, depth_periphery;
    uint64_t applied_generation{};
    bool output_recorded{}, submitted_pending{};
    bool quarantine{};
    std::string last_error{};
    static constexpr auto read_state = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE |
        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;

    void retired() {
        if (submitted_pending) {
            fovea.note_submission_retired();
            periphery.note_submission_retired();
            submitted_pending=false;
        }
        native_fovea.Reset(); native_periphery.Reset();
        depth_fovea.Reset(); depth_periphery.Reset();
    }
    void committed() {
        if (output_recorded) {
            fovea.commit_recording(); periphery.commit_recording();
            fovea.note_submission_started(); periphery.note_submission_started();
            submitted_pending=true;
            output_recorded=false;
        }
    }
    static bool pack_source(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
        ID3D12Resource* source, D3D12_RESOURCE_STATES source_state,
        uint32_t w,uint32_t h, Microsoft::WRL::ComPtr<ID3D12Resource>& pack) {
        if (!device || !cmd || !source || !w || !h || w>16384) return false;
        const auto src=source->GetDesc();
        if (src.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            src.Width<w || src.Height<h || src.DepthOrArraySize!=1 ||
            src.SampleDesc.Count!=1 || src.MipLevels!=1 ||
            (src.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE)) return false;
        if (src.Format!=DXGI_FORMAT_B8G8R8A8_UNORM &&
            src.Format!=DXGI_FORMAT_B8G8R8A8_UNORM_SRGB &&
            src.Format!=DXGI_FORMAT_B8G8R8A8_TYPELESS) return false;
        if (pack) {
            const auto old=pack->GetDesc();
            if (old.Width!=uint64_t(w)*2 || old.Height!=h || old.Format!=src.Format) pack.Reset();
        }
        if (!pack) {
            D3D12_HEAP_PROPERTIES heap{}; heap.Type=D3D12_HEAP_TYPE_DEFAULT;
            heap.CreationNodeMask=heap.VisibleNodeMask=1;
            auto desc=src;
            desc.Width=uint64_t(w)*2; desc.Height=h;
            desc.Flags=D3D12_RESOURCE_FLAG_NONE;
            if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,
                &desc,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,nullptr,
                IID_PPV_ARGS(&pack)))) return false;
        }
        D3D12_RESOURCE_BARRIER barrier[2]{};
        barrier[0].Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier[0].Transition={source, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
            source_state, D3D12_RESOURCE_STATE_COPY_SOURCE};
        barrier[1].Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier[1].Transition={pack.Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_DEST};
        if(source_state!=D3D12_RESOURCE_STATE_COPY_SOURCE)
            cmd->ResourceBarrier(1,barrier);
        cmd->ResourceBarrier(1,barrier+1);
        const D3D12_TEXTURE_COPY_LOCATION from{source,D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
        const D3D12_TEXTURE_COPY_LOCATION to{pack.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
        const D3D12_BOX rect{0,0,0,w,h,1};
        cmd->CopyTextureRegion(&to,0,0,0,&from,&rect);
        for(auto& t:barrier) std::swap(t.Transition.StateBefore,t.Transition.StateAfter);
        if(source_state!=D3D12_RESOURCE_STATE_COPY_SOURCE)
            cmd->ResourceBarrier(1,barrier);
        cmd->ResourceBarrier(1,barrier+1);
        return true;
    }
    static bool finite_matrix(const Matrix4x4f& m) {
        for (int c=0;c<4;++c) for(int row=0;row<4;++row)
            if(!std::isfinite(m[c][row]))return false;
        return true;
    }
    bool synthesize(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
        ID3D12Resource* foveal_rgb, ID3D12Resource* peripheral_rgb,
        ID3D12Resource* foveal_z, ID3D12Resource* peripheral_z,
        const std::array<float,4>& foveal_uv, const std::array<float,4>& peripheral_uv,
        const ViewFrame& frame, VR* vr) {
        output_recorded=false;
        last_error.clear();
        if (!device || !cmd || !vr || !frame.binocular_enabled || !foveal_rgb ||
            !peripheral_rgb || !foveal_z || !peripheral_z || submitted_pending) {
            last_error="missing current binocular RGB/Z packet or outstanding GPU work";return false;
        }
        if (frame.config.settings.fovea_view!=0) {
            last_error="this build requires fovea UE0 / periphery UE1";return false;
        }
        const auto& f=frame.config.layout.fovea;
        const auto& p=frame.config.layout.periphery;
        // Preflight R5 depth-to-color dimensions and distinct producer sources.
        if(foveal_z==peripheral_z || foveal_rgb==peripheral_rgb ||
           f.width==p.width && f.height==p.height) {
            last_error="ambiguous pair of producer resources or source viewports";return false;
        }
        const auto eyeL=glm::vec3{vr->get_eye_offset(VRRuntime::Eye::LEFT)};
        const auto eyeR=glm::vec3{vr->get_eye_offset(VRRuntime::Eye::RIGHT)};
        const float world=vr->get_world_to_meters()*vr->get_world_scale();
        const float ipd=glm::length(eyeR-eyeL)*world;
        if (!std::isfinite(ipd) || ipd<0.001f || ipd>1000.f) {
            last_error="invalid world-scaled IPD";return false;
        }
        auto left=vr->get_projection_matrix(VRRuntime::Eye::LEFT);
        auto right=vr->get_projection_matrix(VRRuntime::Eye::RIGHT);
        const float near=sdk::globals::get_near_clipping_plane();
        if (!std::isfinite(near)||near<=0.f) {
            last_error="invalid near plane";return false;
        }
        left[3][2]=near;right[3][2]=near;
        auto fLeft=left, fRight=right;
        uevr::duoview::apply_foveal_crop(fLeft,frame.config.layout);
        uevr::duoview::apply_foveal_crop(fRight,frame.config.layout);
        if (!finite_matrix(fLeft)||!finite_matrix(fRight)||
            !finite_matrix(left)||!finite_matrix(right)) {
            last_error="invalid stereo projection matrices";return false;
        }
        const auto mLR=fRight*glm::translate(Matrix4x4f{1.f},glm::vec3{-ipd,0,0})*glm::inverse(fLeft);
        const auto mRL=left*glm::translate(Matrix4x4f{1.f},glm::vec3{ipd,0,0})*glm::inverse(right);
        if (!finite_matrix(mLR)||!finite_matrix(mRL)) {
            last_error="failed DIBR reprojection matrix validation";return false;
        }
        if (!pack_source(device,cmd,foveal_rgb,D3D12_RESOURCE_STATE_RENDER_TARGET,
                         f.width,f.height,packed_fovea) ||
            !pack_source(device,cmd,peripheral_rgb,D3D12_RESOURCE_STATE_RENDER_TARGET,
                         p.width,p.height,packed_periphery)) {
            last_error="native RGB to double-wide R5 input copy not supported";return false;
        }
        native_fovea=foveal_rgb;native_periphery=peripheral_rgb;
        depth_fovea=foveal_z;depth_periphery=peripheral_z;
        auto param=[&](bool reverse,const std::array<float,4>& uv,const Matrix4x4f& matrix) {
            d3d12::DIBRPreview::Parameters v{};
            v.right_eye_source=reverse;
            v.depth_uv_scale_bias=uv;
            v.disparity_pixels=vr->get_dibr_disparity_pixels();
            v.reversed_depth=vr->is_dibr_reversed_depth_enabled();
            v.reprojection_strength=vr->get_dibr_reprojection_strength();
            v.legacy_depth_curve=vr->get_dibr_legacy_depth_curve();
            v.legacy_near_depth_cap=vr->get_dibr_legacy_near_depth_cap();
            v.depth_edge_stabilization=vr->is_dibr_depth_edge_stabilization_enabled();
            v.depth_edge_threshold=vr->get_dibr_depth_edge_threshold();
            v.depth_edge_stabilization_strength=vr->get_dibr_depth_edge_stabilization_strength();
            v.spatial_repair=vr->is_dibr_spatial_repair_enabled();
            v.show_spatial_repair_mask=vr->is_dibr_spatial_repair_debug_mask_enabled();
            v.use_true_reprojection=true;
            std::memcpy(v.source_to_right.data(), &matrix[0][0],sizeof(float)*16);
            return v;
        };
        if (!fovea.synthesize(device,cmd,packed_fovea.Get(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,
            foveal_z,read_state,nullptr,param(false,foveal_uv,mLR),true)) {
            last_error="R5 left fovea synthesis: "+fovea.failure_reason();return false;
        }
        if (!periphery.synthesize(device,cmd,packed_periphery.Get(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,
            peripheral_z,read_state,nullptr,param(true,peripheral_uv,mRL),true)) {
            fovea.abort_recording();
            last_error="R5 right periphery synthesis: "+periphery.failure_reason();return false;
        }
        output_recorded=true;
        return true;
    }
};
}

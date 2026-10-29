#pragma once
#include "DuoViewConfig.hpp"
#include "DuoViewNgxGuide.hpp"
#include "DuoViewMonoCopyD3D12.hpp"
#include "DuoViewState.hpp"
#include "DuoViewShaderSource.hpp"
#include "DuoViewSurfaceD3D12.hpp"
#include <memory>
#include <string>

namespace uevr::duoview::dx12 {
using Microsoft::WRL::ComPtr;
struct ShaderConstants {
    uint32_t output[2], atlas[2], fovea[4], periphery[4];
    float crop[4], feather;
    uint32_t border;
    uint32_t diagnostic;
    float reserved;
    uint32_t fovea_source_size[2], peripheral_source_size[2];
    uint32_t output_offset[2];
    float sharpen_strength, sharpen_max_change, sharpen_fxaa_bias;
    uint32_t sharpen_flags;
    uint32_t stereo_padding[2]{};
    float stereo_depth_z[4], stereo_eye_x[4], stereo_check[4];
    float stereo_left_depth_z[4], left_depth_rect[4], right_depth_rect[4], depth_viewport_ranges[4];
};
static_assert(sizeof(ShaderConstants) == 240);
static_assert(sizeof(ShaderConstants) / 4 + 1 <= 64); // constants + SRV table

class Compositor {
public:
    static bool split_eye_frame(const ViewFrame& frame) {
#if defined(UEVR_DUOVIEW_V3_CAMERA_FIELDS)
        return frame.split_eye;
#else
        (void)frame;
        return false; // base/legacy DuoView standalone GPU tests
#endif
    }
    bool last_true_stereo() const { return last_true_stereo_; }
    ID3D12Resource* surface_color(UINT pass) const {return pass<2?surfaces_.color(pass):nullptr;}
    // Prebuild the per-slot PSO, descriptors and output outside OpenXR frame copy.
    // Called after swapchain images and their command contexts are constructed.
    bool prewarm(ID3D12Device* device, UINT width, UINT height, bool srgb, UINT64 frequency = 0) {
        if (!device || !width || !height || FAILED(device->GetDeviceRemovedReason())) return false;
        if (!prepare(device, width, height, srgb)) return false;
        setup_timing(device, frequency);
        return true;
    }
    // One instance per retired OpenXR command slot; descriptors/resources must
    // stay alive until that slot's GPU fence completes.
    bool record(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
                ID3D12Resource* atlas, ID3D12Resource* destination,
                D3D12_RESOURCE_STATES atlas_state, const FrameConfig& frame, UINT64 frequency = 0) {
        recorded_commands_ = false;
        if (!device || !cmd || !atlas || !destination || atlas == destination ||
            cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT ||
            FAILED(device->GetDeviceRemovedReason()) || !layout_valid(frame.layout)) return false;
        const auto source = atlas->GetDesc(), target = destination->GetDesc();
        const auto& l = frame.layout;
        if (source.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            target.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            source.Width != l.atlas_width || source.Height != l.atlas_height ||
            target.Width != l.atlas_width || target.Height != l.atlas_height ||
            source.DepthOrArraySize != 1 || target.DepthOrArraySize != 1 ||
            source.SampleDesc.Count != 1 || target.SampleDesc.Count != 1 ||
            source.SampleDesc.Quality != 0 || target.SampleDesc.Quality != 0 ||
            !(target.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) ||
            l.atlas_width / 2 > 16384 ||
            source.MipLevels != 1 || target.MipLevels != 1 ||
            (source.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) || !bgra8(target.Format)) return false;
        const auto format = srv_format(source.Format);
        if (format == DXGI_FORMAT_UNKNOWN) return false;
        ComPtr<ID3D12Device> sd, dd, cd;
        if (FAILED(atlas->GetDevice(IID_PPV_ARGS(&sd))) ||
            FAILED(destination->GetDevice(IID_PPV_ARGS(&dd))) ||
            FAILED(cmd->GetDevice(IID_PPV_ARGS(&cd))) ||
            sd.Get() != device || dd.Get() != device || cd.Get() != device) return false;
        const bool srgb = format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB || format == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
        if (!prepare(device, l.atlas_width / 2, l.atlas_height, srgb)) return false;
        const bool timed = frequency && frequency == frequency_ && queries_ && timestamps_;
        update_timing(timed,false);
        ShaderConstants constants{
            {l.atlas_width / 2, l.atlas_height}, {l.atlas_width, l.atlas_height},
            {l.fovea.x, l.fovea.y, l.fovea.width, l.fovea.height},
            {l.periphery.x, l.periphery.y, l.periphery.width, l.periphery.height},
            {l.u0, l.v0, l.u1, l.v1}, frame.settings.feather_fraction,
            frame.settings.debug_border ? 1u : 0u, frame.settings.diagnostic_view, 0.f};
        ensure_srvs(device,atlas,atlas,format);
        source_ = atlas;
        transition(cmd, atlas, atlas_state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        recorded_commands_ = true;
        if (timed) cmd->EndQuery(queries_.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0);
        ID3D12DescriptorHeap* heaps[]{srv_.Get()};
        cmd->SetDescriptorHeaps(1, heaps);
        cmd->SetGraphicsRootSignature(root_.Get());
        cmd->SetPipelineState(pipeline_.Get());
        cmd->SetGraphicsRootDescriptorTable(0, srv_gpu_start_);
        cmd->SetGraphicsRoot32BitConstants(1, sizeof(constants) / 4, &constants, 0);
        const D3D12_VIEWPORT viewport{0, 0, static_cast<float>(width_), static_cast<float>(height_), 0, 1};
        const D3D12_RECT rect{0, 0, static_cast<LONG>(width_), static_cast<LONG>(height_)};
        cmd->RSSetViewports(1, &viewport);
        cmd->RSSetScissorRects(1, &rect);
        const auto handle = rtv_cpu_start_;
        cmd->OMSetRenderTargets(1, &handle, FALSE, nullptr);
        cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        cmd->DrawInstanced(3, 1, 0, 0);
        transition(cmd, atlas, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, atlas_state);
        const auto copied = copy_composite_to_stereo(cmd, device, output_.Get(), destination,
            D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_RENDER_TARGET);
        if (timed) {
            cmd->EndQuery(queries_.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 1);
            cmd->ResolveQueryData(queries_.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0, 2, timestamps_.Get(), 0);
            timing_pending_ = true; pending_direct_xr_=false;
        }
        return copied;
    }
    // Direct Native Fix composition: keep Joey's exact UE rendering and
    // captures, but sample the existing view rectangles as two SRVs instead
    // of copying them to a third (doublewide) render texture first.
    // Legacy/V3 uses prewarmed objects. New opt-in surface modes lazily prepare
    // their exact-sized maps once per retired slot (and on layout changes).
    bool record_native(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
                ID3D12Resource* primary, ID3D12Resource* secondary,
                ID3D12Resource* destination, D3D12_RESOURCE_STATES primary_state,
                D3D12_RESOURCE_STATES secondary_state, const ViewFrame& frame,
                std::shared_ptr<const void> packet_lifetime, UINT64 frequency = 0,
                ID3D12Resource* leftDepth = nullptr, ID3D12Resource* rightDepth = nullptr,
                uint32_t previewMode = 0, uint32_t stereoMode = 0,
                float stereoSign = 1.0f,
                DepthViewport leftViewport = {}, DepthViewport rightViewport = {},
                const std::array<ngx::Guide,2>& ngxGuides = {},
                const std::array<float,4>& quality = {1.f,.015f,1.f,1.f}) {
        recorded_commands_=false;
        error_.clear();
        last_native_direct_xr_=false;
        last_true_stereo_=false;
        const auto reject=[this](const char* reason) { error_=reason; return false; };
        if(stereoMode>6u)return reject("Unknown experimental stereo mode");
        if (!device || !cmd || !primary || !secondary || !destination ||
            primary==secondary || primary==destination || secondary==destination ||
            cmd->GetType()!=D3D12_COMMAND_LIST_TYPE_DIRECT ||
            FAILED(device->GetDeviceRemovedReason()) || !layout_valid(frame.config.layout))
            return reject("Invalid direct Native source resources or DuoView layout");
        const auto& layout=frame.config.layout;
        if (frame.config.settings.fovea_view>1)
            return reject("Invalid frozen Native fovea source index");
        if (device_.Get()!=device || width_!=layout.atlas_width/2 ||
            height_!=layout.atlas_height || !output_ || !native_pipeline_ ||
            !root_ || !srv_ || !rtv_)
            return reject("Direct Native compositor not prewarmed for frozen source extent");
        const auto p=primary->GetDesc(), s=secondary->GetDesc();
        const auto xrd=destination->GetDesc();
        last_native_source_extents_=
            (uint64_t(static_cast<uint32_t>(p.Width)&0xffffu)<<48)|
            (uint64_t(p.Height&0xffffu)<<32)|
            (uint64_t(static_cast<uint32_t>(s.Width)&0xffffu)<<16)|
            uint64_t(s.Height&0xffffu);
        const auto xr_format=srgb_ ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        // Render directly to the doublewide OpenXR texture only when its
        // render-target format matches the precompiled PSO. Keep a bit-for-bit
        // old compositor+copy fallback for incompatible swapchain formats.
        if (!stereo_destination_valid(xrd,width_,height_))
            return reject("Invalid Mono XR output dimensions, format, or render-target flags");
        // Direct double-wide raster would run sharpening twice on the same
        // monoscopic foveal content. Use the existing single-Mono compose+copy
        // when fused sharpening is enabled; leave v182 behavior otherwise.
        if(stereoMode && (!split_eye_frame(frame) || frame.config.settings.fovea_view!=0))
            return reject("SplitEye V3 UE0-left/UE1-right must be ON for actual stereo; fix settings, not a Mono fallback");
        const bool requested_stereo = stereoMode != 0 && split_eye_frame(frame) &&
            frame.config.settings.fovea_view == 0;
        const bool direct_xr=(frame.config.settings.direct_xr_output || requested_stereo ||
                            previewMode!=0) &&
            (frame.config.settings.sharpen_strength <= 0.0f || requested_stereo ||
             previewMode!=0) &&
            xrd.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
            xrd.Width==static_cast<uint64_t>(width_)*2 && xrd.Height==height_ &&
            xrd.DepthOrArraySize==1 && xrd.MipLevels==1 &&
            xrd.SampleDesc.Count==1 && xrd.SampleDesc.Quality==0 &&
            (xrd.Flags&D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET)!=0 &&
            (xrd.Format==xr_format || xrd.Format==DXGI_FORMAT_B8G8R8A8_TYPELESS);
        const auto& pr=frame.config.settings.fovea_view==0 ? layout.fovea : layout.periphery;
        const auto& sr=frame.config.settings.fovea_view==1 ? layout.fovea : layout.periphery;
        const auto is_bgra_family=[](DXGI_FORMAT f) {
            return f==DXGI_FORMAT_B8G8R8A8_TYPELESS ||
                   f==DXGI_FORMAT_B8G8R8A8_UNORM ||
                   f==DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        };
        const auto valid_source=[&](const D3D12_RESOURCE_DESC& d,const Rect& rect) {
            return d.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
                is_bgra_family(d.Format) && d.Width>=rect.width && d.Height>=rect.height &&
                d.DepthOrArraySize==1 && d.MipLevels==1 &&
                d.SampleDesc.Count==1 && d.SampleDesc.Quality==0 &&
                true;
        };
        if (!valid_source(p,pr) || !valid_source(s,sr) ||
            p.Width>UINT32_MAX || s.Width>UINT32_MAX ||
            p.Height>UINT32_MAX || s.Height>UINT32_MAX)
            return reject("Direct Native source format / rect incompatible with frozen view");
        const auto sampling_format=srgb_
            ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB
            : DXGI_FORMAT_B8G8R8A8_UNORM;
        // A typed resource cannot legally be reinterpreted as a different
        // sRGB class. This deliberately fails closed rather than silently
        // changing shading, unlike a typeless Native Fix capture.
        if ((p.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            (s.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            (p.Format!=DXGI_FORMAT_B8G8R8A8_TYPELESS && p.Format!=sampling_format) ||
            (s.Format!=DXGI_FORMAT_B8G8R8A8_TYPELESS && s.Format!=sampling_format)) {
            // Uncommon sources can still be copied safely. Never turn an
            // optimization compatibility failure into a black headset frame.
            if(stereoMode || previewMode)
                return reject("Stereo requires shader-readable native color sources; R5 candidate selector cannot repair this source type");
            return record_native_gather(device,cmd,primary,secondary,destination,
                primary_state,secondary_state,frame,std::move(packet_lifetime),frequency);
        }
        ComPtr<ID3D12Device> pd,sd,dd,cd;
        if (FAILED(primary->GetDevice(IID_PPV_ARGS(&pd))) ||
            FAILED(secondary->GetDevice(IID_PPV_ARGS(&sd))) ||
            FAILED(destination->GetDevice(IID_PPV_ARGS(&dd))) ||
            FAILED(cmd->GetDevice(IID_PPV_ARGS(&cd))) ||
            pd.Get()!=device || sd.Get()!=device || dd.Get()!=device || cd.Get()!=device)
            return reject("Native primary/secondary/XR resource device mismatch");

        auto* fovea=frame.config.settings.fovea_view==0 ? primary : secondary;
        auto* periphery=frame.config.settings.fovea_view==0 ? secondary : primary;
        const auto& fd=frame.config.settings.fovea_view==0 ? p : s;
        const auto& vd=frame.config.settings.fovea_view==0 ? s : p;
        const auto fovea_state=frame.config.settings.fovea_view==0 ? primary_state : secondary_state;
        const auto peripheral_state=frame.config.settings.fovea_view==0 ? secondary_state : primary_state;

        const auto depth_resource_valid=[&](ID3D12Resource* depth) {
            if(!depth || depth==primary || depth==secondary || depth==destination ||
               depth==atlas_.Get() || depth==output_.Get())return false;
            const auto d=depth->GetDesc();
            if(d.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
               !d.Width || !d.Height || d.DepthOrArraySize!=1 || d.MipLevels!=1 ||
               d.SampleDesc.Count!=1 || d.SampleDesc.Quality!=0 ||
               (d.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
               valid_depth_srv(d.Format)==DXGI_FORMAT_UNKNOWN)return false;
            ComPtr<ID3D12Device> owner;
            return SUCCEEDED(depth->GetDevice(IID_PPV_ARGS(&owner))) && owner.Get()==device;
        };
        const bool depth_compatible=leftDepth!=rightDepth &&
            depth_resource_valid(leftDepth) && depth_resource_valid(rightDepth);
        // An active stereo request must never be silently replaced by the
        // depth-preview PSO while reporting last_true_stereo=true.
        const bool depthPreview=!requested_stereo && previewMode>=1u && previewMode<=3u &&
            depth_compatible && depth_pipeline_;
        const bool stereoReady=requested_stereo && depth_compatible && stereo_pipeline_;
        const bool indirect_eye_output=(stereoReady || depthPreview) && !direct_xr;
        if(requested_stereo && !stereoReady)
            return reject("Stereo source pair missing/invalid: choose another foveal or peripheral DSV");
        if((depthPreview || stereoReady) &&
           (!depth_viewport_valid(leftViewport,leftDepth->GetDesc().Width,leftDepth->GetDesc().Height) ||
            !depth_viewport_valid(rightViewport,rightDepth->GetDesc().Width,rightDepth->GetDesc().Height)))
            return reject("Stereo depth viewport unknown, outside resource, or invalid depth range");
        if(requested_stereo && !std::isfinite(stereoSign))
            return reject("Nonfinite stereo reversal setting");
        if(indirect_eye_output && !atlas_)
            return reject("True-stereo doublewide Native atlas unavailable");
        ShaderConstants constants{
            {layout.atlas_width/2,layout.atlas_height},
            {layout.atlas_width,layout.atlas_height},
            {layout.fovea.x,layout.fovea.y,layout.fovea.width,layout.fovea.height},
            {layout.periphery.x,layout.periphery.y,layout.periphery.width,layout.periphery.height},
            {layout.u0,layout.v0,layout.u1,layout.v1},
            frame.config.settings.feather_fraction,
            frame.config.settings.debug_border ? 1u : 0u,
            depthPreview ? previewMode + 2u : frame.config.settings.diagnostic_view, 0.f,
            {static_cast<uint32_t>(fd.Width),fd.Height},
            {static_cast<uint32_t>(vd.Width),vd.Height},
            {0u,0u},
            frame.config.settings.sharpen_strength, 0.10f, 0.02f,
            3u | (srgb_ ? 0u : 4u) // larger radius, edge protection, SDR conversion
        };
        if(depthPreview || stereoReady) {
            const DepthViewport views[]{leftViewport,rightViewport};
            float* rects[]{constants.left_depth_rect,constants.right_depth_rect};
            for(int eye=0;eye<2;++eye) {
                const auto& v=views[eye];auto* rect=rects[eye];
                rect[0]=v.x;rect[1]=v.y;rect[2]=v.width;rect[3]=v.height;
                constants.depth_viewport_ranges[eye*2]=v.min_depth;
                constants.depth_viewport_ranges[eye*2+1]=v.max_depth;
            }
        }
#if defined(UEVR_DUOVIEW_V3_CAMERA_FIELDS)
        if(stereoReady) {
            // V3's frozen LEFT and RIGHT native OpenXR matrices are col-major.
            const auto& l=frame.projection;
            const auto& r=frame.projection_right;
            for(size_t k=0;k<16;++k)
                if(!std::isfinite(l[k]) || !std::isfinite(r[k]))
                    return reject("Stereo optical matrix contains nonfinite values");
            const float cL=l[11], cR=r[11];
            if(std::abs(cL)<1.e-7f || std::abs(cR)<1.e-7f ||
               std::abs(l[0])<1.e-7f || std::abs(r[0])<1.e-7f)
                return reject("Stereo optical matrix coefficients degenerate");
            const float aR=r[0]/cR, bR=r[8]/cR;
            const float aL=l[0]/cL, bL=l[8]/cL;
            const auto& lp=frame.eye_cameras[0].position;
            const auto& rp=frame.eye_cameras[1].position;
            double sum=0.0;
            for(int k=0;k<3;++k) {
                if(!std::isfinite(lp[k]) || !std::isfinite(rp[k]))
                    return reject("Native left/right camera poses not finite");
                const double d=rp[k]-lp[k];sum+=d*d;
            }
            const float baseline=static_cast<float>(std::sqrt(sum))*stereoSign;
            if(!std::isfinite(baseline) ||
               std::abs(baseline)>1000.f) return reject("Native stereo baseline rejected");
            constants.stereo_depth_z[0]=r[10];
            constants.stereo_depth_z[1]=r[14];
            constants.stereo_depth_z[2]=r[11];
            constants.stereo_depth_z[3]=r[15];
            constants.stereo_left_depth_z[0]=l[10];
            constants.stereo_left_depth_z[1]=l[14];
            constants.stereo_left_depth_z[2]=l[11];
            constants.stereo_left_depth_z[3]=l[15];
            constants.stereo_eye_x[0]=aL/aR;
            constants.stereo_eye_x[1]=bL-(aL/aR)*bR;
            constants.stereo_eye_x[2]=aL*baseline;
            constants.stereo_eye_x[3]=1.f;
            constants.stereo_check[0]=1.f;       // absolute world units
            constants.stereo_check[1]=0.015f;    // relative world error
            constants.stereo_check[2]=.20f;      // maximum peripheral UV shift
            constants.stereo_check[3]=stereoMode>=4?float(stereoMode):stereoMode==2?1.f:stereoMode==3?3.f:0.f;
        }
#endif // UEVR_DUOVIEW_V3_CAMERA_FIELDS
        const bool surface_mode=stereoReady && stereoMode>=4u;
        std::array<SurfaceConstants,2> surface_constants{};
        std::array<bool,2> surface_reverse{};
        if(surface_mode) {
            if(!make_surface_constants(frame,leftViewport,rightViewport,stereoSign,
                    surface_constants,surface_reverse,ngxGuides,quality))
                return reject("Surface camera transform / depth sample grid invalid");
            if(!surfaces_.prepare(device,srgb_,layout.fovea.width,layout.fovea.height,
                    layout.periphery.width,layout.periphery.height,surface_constants)) {
                error_=surfaces_.error();return false;
            }
            ensure_surface_srvs(device,sampling_format);
        }
        ensure_srvs(device,fovea,periphery,sampling_format);
        if(depthPreview || stereoReady) ensure_depth_srvs(device,leftDepth,rightDepth);
        // GPU lifetime remains bound to the exact retired OpenXR command slot,
        // never to whichever engine packet happens to arrive next.
        primary_reference_=primary; secondary_reference_=secondary;
        packet_lifetime_=std::move(packet_lifetime);
        const bool timed=frequency && frequency==frequency_ && queries_ && timestamps_;
        update_timing(timed,direct_xr);
        transition(cmd,fovea,fovea_state,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        transition(cmd,periphery,peripheral_state,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        recorded_commands_=true;
        if (timed) cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
        if(depthPreview || stereoReady) {
            constexpr auto read=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
            if(ngxGuides[0])transition(cmd,leftDepth,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,read);
            if(ngxGuides[1])transition(cmd,rightDepth,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,read);
        }
        if(surface_mode)surfaces_.record(cmd,srv_.Get(),srv_gpu_start_,&constants,
            surface_constants,surface_reverse,stereoMode>=5u);
        ID3D12DescriptorHeap* heaps[]{srv_.Get()};
        cmd->SetDescriptorHeaps(1,heaps);
        cmd->SetGraphicsRootSignature(root_.Get());
        cmd->SetPipelineState(depthPreview ? depth_pipeline_.Get() : stereoReady ? stereo_pipeline_.Get() : native_pipeline_.Get());
        cmd->SetGraphicsRootDescriptorTable(0,srv_gpu_start_);
        cmd->SetGraphicsRoot32BitConstants(1,sizeof(constants)/4,&constants,0);
        auto handle=rtv_cpu_start_;
        if(indirect_eye_output) {
            // Reuse the existing DOUBLEWIDE Native gather atlas: no extra
            // high-resolution eye texture allocation and never a MONO copy.
            transition(cmd,atlas_.Get(),D3D12_RESOURCE_STATE_COPY_DEST,
                       D3D12_RESOURCE_STATE_RENDER_TARGET);
            handle=stereo_atlas_rtv_cpu_;
        }
        if(direct_xr || indirect_eye_output) {
            // Each Compositor is owned by one fenced XR command slot, so its
            // second RTV descriptor cannot be overwritten while GPU-active.
            if(direct_xr) {
            handle=direct_xr_rtv_cpu_;
            if (xr_rtv_reference_.Get()!=destination || xr_rtv_format_!=xr_format) {
                D3D12_RENDER_TARGET_VIEW_DESC xr_view{};
                xr_view.Format=xr_format; xr_view.ViewDimension=D3D12_RTV_DIMENSION_TEXTURE2D;
                device->CreateRenderTargetView(destination,&xr_view,handle);
                xr_rtv_reference_=destination;
                xr_rtv_format_=xr_format;
                ++xr_rtv_refresh_count_;
            }
            }
            const D3D12_VIEWPORT viewport{
                0,0,static_cast<float>(width_*2),static_cast<float>(height_),0,1};
            const D3D12_RECT rect{
                0,0,static_cast<LONG>(width_*2),static_cast<LONG>(height_)};
            cmd->RSSetViewports(1,&viewport);
            cmd->RSSetScissorRects(1,&rect);
            cmd->OMSetRenderTargets(1,&handle,FALSE,nullptr);
            cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            cmd->DrawInstanced(3,1,0,0);
        } else {
            const D3D12_VIEWPORT viewport{
                0,0,static_cast<float>(width_),static_cast<float>(height_),0,1};
            const D3D12_RECT rect{
                0,0,static_cast<LONG>(width_),static_cast<LONG>(height_)};
            cmd->RSSetViewports(1,&viewport);
            cmd->RSSetScissorRects(1,&rect);
            cmd->OMSetRenderTargets(1,&handle,FALSE,nullptr);
            cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            cmd->DrawInstanced(3,1,0,0);
        }
        transition(cmd,fovea,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,fovea_state);
        transition(cmd,periphery,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,peripheral_state);
        if(depthPreview || stereoReady) {
            constexpr auto read=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
            if(ngxGuides[0])transition(cmd,leftDepth,read,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            if(ngxGuides[1])transition(cmd,rightDepth,read,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        }
        // Always submit independent eye halves. For a typed XR target whose
        // RTV encoding differs from the prewarmed shader PSO, copy the ENTIRE
        // doublewide atlas instead of duplicating an old Mono texture.
        bool copied=false;
        if(direct_xr) copied=true;
        else if(indirect_eye_output) {
            const auto a=atlas_->GetDesc();
            if(a.Width==xrd.Width && a.Height==xrd.Height &&
               xrd.SampleDesc.Count==1 && xrd.DepthOrArraySize==1) {
                transition(cmd,atlas_.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,
                           D3D12_RESOURCE_STATE_COPY_SOURCE);
                transition(cmd,destination,D3D12_RESOURCE_STATE_RENDER_TARGET,
                           D3D12_RESOURCE_STATE_COPY_DEST);
                D3D12_TEXTURE_COPY_LOCATION src{atlas_.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
                D3D12_TEXTURE_COPY_LOCATION dst{destination,D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
                cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
                transition(cmd,destination,D3D12_RESOURCE_STATE_COPY_DEST,
                           D3D12_RESOURCE_STATE_RENDER_TARGET);
                transition(cmd,atlas_.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,
                           D3D12_RESOURCE_STATE_COPY_DEST);
                copied=true;
            }
        } else copied=copy_composite_to_stereo(cmd,device,output_.Get(),destination,
                D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET);
        last_native_direct_xr_=direct_xr;
        last_true_stereo_=stereoReady && copied;
        if (timed) {
            cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
            cmd->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timestamps_.Get(),0);
            timing_pending_=true; pending_direct_xr_=direct_xr;
        }
        if (!copied) return reject("Direct Native blend succeeded but Mono XR output validation failed");
        return true;
    }
    // Fallback for capture resources that cannot be sampled as SRVs.
    // Keep the original bit-for-bit gather path for format and GPU safety.
    // Gather Joey's actual Native Stereo Fix primary and secondary render
    // targets into this command slot's atlas, then run the same Mono compositor.
    bool record_native_gather(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
                ID3D12Resource* primary, ID3D12Resource* secondary,
                ID3D12Resource* destination, D3D12_RESOURCE_STATES primary_state,
                D3D12_RESOURCE_STATES secondary_state, const ViewFrame& frame,
                std::shared_ptr<const void> packet_lifetime, UINT64 frequency = 0) {
        recorded_commands_ = false;
        error_.clear();
        const auto reject = [this](const char* reason) { error_ = reason; return false; };
        if (!device || !cmd || !primary || !secondary || !destination || primary == secondary ||
            primary == destination || secondary == destination || cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT ||
            FAILED(device->GetDeviceRemovedReason()) || !layout_valid(frame.config.layout))
            return reject("Invalid Native resources, D3D12 device, or DuoView layout");
        last_native_direct_xr_=false;
        if (!stereo_destination_valid(destination->GetDesc(),frame.config.layout.atlas_width/2,
                                      frame.config.layout.atlas_height))
            return reject("Invalid gather XR destination before source copy");
        if (!atlas_) return reject("Missing prewarmed Native gather atlas (ID6 activation setup)");
        const auto p = primary->GetDesc(), s = secondary->GetDesc(), a = atlas_->GetDesc();
        const auto& l = frame.config.layout;
        const auto& primary_rect = frame.config.settings.fovea_view == 0 ? l.fovea : l.periphery;
        const auto& secondary_rect = frame.config.settings.fovea_view == 1 ? l.fovea : l.periphery;
        const auto valid_source = [&](const D3D12_RESOURCE_DESC& d, const Rect& r) {
            return d.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && bgra8(d.Format) &&
                d.Width >= r.width && d.Height >= r.height && d.DepthOrArraySize == 1 &&
                d.MipLevels == 1 && d.SampleDesc.Count == 1 && d.SampleDesc.Quality == 0;
        };
        if (!valid_source(p, primary_rect) || !valid_source(s, secondary_rect) ||
            a.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || a.Width != l.atlas_width ||
            a.Height != l.atlas_height || a.DepthOrArraySize != 1 || a.MipLevels != 1 ||
            a.SampleDesc.Count != 1 || a.SampleDesc.Quality != 0 ||
            (a.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            primary == atlas_.Get() || secondary == atlas_.Get() || destination == atlas_.Get())
            return reject("Native capture extent/format incompatible with frozen atlas rectangles");
        ComPtr<ID3D12Device> pd, sd, dd, cd;
        if (FAILED(primary->GetDevice(IID_PPV_ARGS(&pd))) ||
            FAILED(secondary->GetDevice(IID_PPV_ARGS(&sd))) ||
            FAILED(destination->GetDevice(IID_PPV_ARGS(&dd))) ||
            FAILED(cmd->GetDevice(IID_PPV_ARGS(&cd))) ||
            pd.Get() != device || sd.Get() != device || dd.Get() != device || cd.Get() != device)
            return reject("Native source / XR destination command-list device mismatch");
        const auto is_bgra_family = [](DXGI_FORMAT f) {
            return f == DXGI_FORMAT_B8G8R8A8_TYPELESS ||
                   f == DXGI_FORMAT_B8G8R8A8_UNORM ||
                   f == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        };
        if (!is_bgra_family(p.Format) || !is_bgra_family(s.Format) ||
            !bgra8(a.Format) ||
            a.Format != (srgb_ ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM))
            return reject("Native BGRA8 format/sRGB mismatch with prewarmed atlas");
        // record_native must use the exact prewarmed objects. Rebuilding here
        // would release atlas_ after CopyTextureRegion has already been queued.
        if (device_.Get() != device || width_ != l.atlas_width / 2 ||
            height_ != l.atlas_height || !output_ || !pipeline_ || !root_ || !srv_ || !rtv_)
            return reject("Native mode dimensions or shader state differ from prewarmed command slot");
        if (!copy_source_to_atlas(cmd, primary, atlas_.Get(), primary_state,
                                  primary_rect.x, primary_rect.y, primary_rect.width, primary_rect.height) ||
            !copy_source_to_atlas(cmd, secondary, atlas_.Get(), secondary_state,
                                  secondary_rect.x, secondary_rect.y, secondary_rect.width, secondary_rect.height)) {
            return reject("Failed recording Native primary/secondary source atlas copy");
        }
        recorded_commands_ = true;
        // These references live in the OpenXR command slot's compositor object.
        // Its slot is replaced only after the prior command fence has retired.
        primary_reference_ = primary;
        secondary_reference_ = secondary;
        packet_lifetime_ = std::move(packet_lifetime);
        const bool composed = record(device, cmd, atlas_.Get(), destination,
            D3D12_RESOURCE_STATE_COPY_DEST, frame.config, frequency);
        // record() clears its own command marker at entry. Preserve the gather
        // commands even if it rejects the later composite pass.
        const bool gather_recorded = true;
        recorded_commands_ = recorded_commands_ || gather_recorded;
        if (!composed && error_.empty()) error_ = "Native gather succeeded but Mono raster/copy validation failed";
        return composed;
    }
    const std::string& error() const { return error_; }
    bool recorded_commands() const { return recorded_commands_; }
    float gpu_milliseconds() const { return gpu_ms_; }
    bool last_native_direct_xr() const { return last_native_direct_xr_; }
    uint64_t last_native_source_extents() const { return last_native_source_extents_; }
    uint64_t srv_descriptor_refresh_count() const { return srv_descriptor_refresh_count_; }
    uint64_t xr_rtv_refresh_count() const { return xr_rtv_refresh_count_; }
    UINT64 timing_frequency() const { return frequency_; }
private:
    static bool make_surface_constants(const ViewFrame& frame,const DepthViewport& left,
            const DepthViewport& right,float sign,std::array<SurfaceConstants,2>& output,
            std::array<bool,2>& reverse,const std::array<ngx::Guide,2>& guides,
            const std::array<float,4>& quality) {
#if defined(UEVR_DUOVIEW_V3_CAMERA_FIELDS)
        const auto& l=frame.config.layout;
        const auto left_full=surface::projection(frame.projection);
        const auto right_full=surface::projection(frame.projection_right);
        const auto left_crop=surface::crop(left_full,l.u0,l.v0,l.u1,l.v1);
        const auto right_crop=surface::crop(right_full,l.u0,l.v0,l.u1,l.v1);
        const auto& a=frame.eye_cameras[0];const auto& b=frame.eye_cameras[1];
        const auto to_right=surface::build(left_crop,right_crop,right_full,
            a.rotation,a.position,b.rotation,b.position,sign);
        const auto to_left=surface::build(right_full,left_full,left_full,
            b.rotation,b.position,a.rotation,a.position,sign);
        if(!to_right||!to_left)return false;
        const auto right_inverse=surface::inverse(right_full);
        const auto left_from_right=surface::multiply(left_crop,surface::target_eye_from_source(
            b.rotation,b.position,a.rotation,a.position,sign));
        if(!right_inverse)return false;
        const surface::Geometry* geometry[]{&*to_right,&*to_left};
        const DepthViewport views[]{left,right};
        const std::array<float,16>* projections[]{&frame.projection_right,&frame.projection};
        for(size_t pass=0;pass<2;++pass) {
            auto& c=output[pass];const auto& g=*geometry[pass];const auto& v=views[pass];
            std::copy(g.source_eye_from_clip.begin(),g.source_eye_from_clip.end(),c.source_eye_from_clip);
            std::copy(g.target_clip_from_source_eye.begin(),g.target_clip_from_source_eye.end(),c.target_clip_from_source_eye);
            std::copy(g.target_full_clip_from_source_eye.begin(),g.target_full_clip_from_source_eye.end(),c.target_full_clip_from_source_eye);
            const double columns=std::ceil(double(v.x)+v.width-.5)-std::ceil(double(v.x)-.5);
            const double rows=std::ceil(double(v.y)+v.height-.5)-std::ceil(double(v.y)-.5);
            if(columns<2||rows<2||columns>16384||rows>16384)return false;
            c.mesh_config[0]=UINT(columns);c.mesh_config[1]=UINT(rows);
            c.mesh_config[2]=pass==0?1u:0u;
            c.mesh_config[3]=pass==0?1u:0u; // left depth is CROPPED, never a full-field veto
            if(pass==0 && guides[0] && guides[1])c.mesh_config[3]|=2u; // backward base + optional foreground refinement
            if(g.reverse_depth)c.mesh_config[3]|=4u;
            for(size_t k=0;k<16;++k) {
                c.target_eye_from_clip[k]=float((*right_inverse)[k]);
                c.source_clip_from_target_eye[k]=float(left_from_right[k]);
            }
            const auto src_jitter=guides[pass]?guides[pass].jitter_uv():std::array<float,2>{};
            const auto dst_jitter=guides[1-pass]?guides[1-pass].jitter_uv():std::array<float,2>{};
            c.jitter[0]=src_jitter[0];c.jitter[1]=src_jitter[1];
            c.jitter[2]=dst_jitter[0];c.jitter[3]=dst_jitter[1];
            std::copy(quality.begin(),quality.end(),c.quality);
            c.visibility[0]=quality[0];c.visibility[1]=quality[1];
            if(guides[pass].flags_known && ((guides[pass].flags&8u)!=0)!=g.reverse_depth)return false;
            c.visibility[2]=(*projections[pass])[11];c.visibility[3]=(*projections[pass])[15];
            if(std::abs(c.visibility[2])<1.e-7f)return false;
            reverse[pass]=g.reverse_depth;
        }
        return true;
#else
        (void)frame;(void)left;(void)right;(void)sign;(void)output;(void)reverse;(void)guides;(void)quality;
        return false;
#endif
    }
    void ensure_surface_srvs(ID3D12Device* device,DXGI_FORMAT format) {
        if(surface_srv_[0].Get()==surfaces_.color(0)&&surface_srv_[1].Get()==surfaces_.color(1))return;
        D3D12_SHADER_RESOURCE_VIEW_DESC view{};view.Format=format;
        view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;view.Texture2D.MipLevels=1;
        auto handle=srv_cpu_start_;handle.ptr+=4*srv_descriptor_increment_;
        for(UINT pass=0;pass<2;++pass) {
            surface_srv_[pass]=surfaces_.color(pass);device->CreateShaderResourceView(surface_srv_[pass].Get(),&view,handle);
            handle.ptr+=srv_descriptor_increment_;
        }
    }
    void ensure_srvs(ID3D12Device* device, ID3D12Resource* first,
                     ID3D12Resource* second, DXGI_FORMAT format) {
        if (srv_descriptors_valid_ && srv_first_reference_.Get()==first &&
            srv_second_reference_.Get()==second && srv_cached_format_==format) return;
        D3D12_SHADER_RESOURCE_VIEW_DESC view{};
        view.Format=format;
        view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
        view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        view.Texture2D.MipLevels=1;
        auto cpu=srv_cpu_start_;
        device->CreateShaderResourceView(first,&view,cpu);
        cpu.ptr+=srv_descriptor_increment_;
        device->CreateShaderResourceView(second,&view,cpu);
        srv_first_reference_=first; srv_second_reference_=second;
        srv_cached_format_=format; srv_descriptors_valid_=true;
        ++srv_descriptor_refresh_count_;
    }
    static DXGI_FORMAT valid_depth_srv(DXGI_FORMAT f) {
        switch(f) {
        case DXGI_FORMAT_R32_TYPELESS: case DXGI_FORMAT_R32_FLOAT: return DXGI_FORMAT_R32_FLOAT;
        case DXGI_FORMAT_R24G8_TYPELESS: return DXGI_FORMAT_R24_UNORM_X8_TYPELESS;
        case DXGI_FORMAT_R32G8X24_TYPELESS: return DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS;
        case DXGI_FORMAT_R16_TYPELESS: return DXGI_FORMAT_R16_UNORM;
        case DXGI_FORMAT_R16_FLOAT: return DXGI_FORMAT_R16_FLOAT;
        default: return DXGI_FORMAT_UNKNOWN;
        }
    }
    void ensure_depth_srvs(ID3D12Device* device,ID3D12Resource* left,ID3D12Resource* right) {
        if(depth_first_.Get()==left && depth_second_.Get()==right)return;
        auto cpu=srv_cpu_start_; cpu.ptr+=2*srv_descriptor_increment_;
        D3D12_SHADER_RESOURCE_VIEW_DESC view{};
        view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
        view.Texture2D.MipLevels=1;
        view.Format=valid_depth_srv(left->GetDesc().Format);
        device->CreateShaderResourceView(left,&view,cpu);
        cpu.ptr+=srv_descriptor_increment_;
        view.Format=valid_depth_srv(right->GetDesc().Format);
        device->CreateShaderResourceView(right,&view,cpu);
        depth_first_=left;depth_second_=right;
    }
    void update_timing(bool timed, bool direct_xr) {
        if (!timed || (timing_pending_ && pending_direct_xr_!=direct_xr)) {
            timing_pending_=false;
            gpu_ms_=-1.f;
        }
        if (timed) read_timing();
    }
    void read_timing() {
        if (!timing_pending_ || !timestamps_ || !frequency_) return;
        D3D12_RANGE range{0, sizeof(UINT64) * 2};
        UINT64* data{};
        if (SUCCEEDED(timestamps_->Map(0, &range, reinterpret_cast<void**>(&data)))) {
            if (data[1] >= data[0]) gpu_ms_ = static_cast<float>((data[1] - data[0]) * 1000.0 / frequency_);
            D3D12_RANGE no_write{0, 0}; timestamps_->Unmap(0, &no_write);
        }
        timing_pending_ = false;
    }
    void setup_timing(ID3D12Device* device, UINT64 frequency) {
        if (!frequency || queries_) return;
        D3D12_QUERY_HEAP_DESC q{}; q.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP; q.Count = 2;
        if (FAILED(device->CreateQueryHeap(&q, IID_PPV_ARGS(&queries_)))) return;
        D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_READBACK;
        heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        D3D12_RESOURCE_DESC buffer{}; buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width = sizeof(UINT64) * 2; buffer.Height = buffer.DepthOrArraySize = buffer.MipLevels = 1;
        buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer,
            D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&timestamps_)))) { queries_.Reset(); return; }
        frequency_ = frequency;
        queries_->SetName(L"DuoView::GPUQueries"); timestamps_->SetName(L"DuoView::GPUTimestamps");
    }
    static DXGI_FORMAT srv_format(DXGI_FORMAT f) {
        switch (f) {
        case DXGI_FORMAT_B8G8R8A8_TYPELESS: return DXGI_FORMAT_B8G8R8A8_UNORM;
        case DXGI_FORMAT_R8G8B8A8_TYPELESS: return DXGI_FORMAT_R8G8B8A8_UNORM;
        case DXGI_FORMAT_B8G8R8A8_UNORM: case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
        case DXGI_FORMAT_R8G8B8A8_UNORM: case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
        case DXGI_FORMAT_R10G10B10A2_UNORM: case DXGI_FORMAT_R16G16B16A16_FLOAT: return f;
        default: return DXGI_FORMAT_UNKNOWN;
        }
    }
    static void transition(ID3D12GraphicsCommandList* cmd, ID3D12Resource* r,
                           D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
        if (before == after) return;
        D3D12_RESOURCE_BARRIER b{};
        b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition = {r, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before, after};
        cmd->ResourceBarrier(1, &b);
    }
    static bool copy_source_to_atlas(ID3D12GraphicsCommandList* cmd, ID3D12Resource* source,
        ID3D12Resource* atlas, D3D12_RESOURCE_STATES source_state, UINT x, UINT y, UINT width, UINT height) {
        if (!width || !height) return false;
        transition(cmd, source, source_state, D3D12_RESOURCE_STATE_COPY_SOURCE);
        const D3D12_TEXTURE_COPY_LOCATION from{source, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX, {0}};
        const D3D12_TEXTURE_COPY_LOCATION to{atlas, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX, {0}};
        const D3D12_BOX box{0, 0, 0, width, height, 1};
        cmd->CopyTextureRegion(&to, x, y, 0, &from, &box);
        transition(cmd, source, D3D12_RESOURCE_STATE_COPY_SOURCE, source_state);
        return true;
    }
    bool check(HRESULT hr, const char* operation) {
        if (SUCCEEDED(hr)) return true;
        error_ = std::string(operation) + " HRESULT " + std::to_string(static_cast<uint32_t>(hr));
        return false;
    }
    bool prepare(ID3D12Device* device, UINT width, UINT height, bool srgb) {
        if (device_.Get() == device && output_ && atlas_ && pipeline_ && native_pipeline_ && stereo_pipeline_ && depth_pipeline_ && root_ && srv_ && rtv_ && width == width_ && height == height_ && srgb == srgb_) return true;
        output_.Reset(); atlas_.Reset(); pipeline_.Reset(); native_pipeline_.Reset(); stereo_pipeline_.Reset(); depth_pipeline_.Reset(); root_.Reset(); srv_.Reset(); rtv_.Reset();
        surfaces_=SurfaceReprojector{};surface_srv_[0].Reset();surface_srv_[1].Reset();
        depth_first_.Reset();depth_second_.Reset();
        srv_first_reference_.Reset(); srv_second_reference_.Reset(); xr_rtv_reference_.Reset();
        srv_descriptors_valid_=false; srv_cached_format_=DXGI_FORMAT_UNKNOWN;
        xr_rtv_format_=DXGI_FORMAT_UNKNOWN;
        srv_cpu_start_={}; srv_gpu_start_={}; rtv_cpu_start_={}; direct_xr_rtv_cpu_={}; stereo_atlas_rtv_cpu_={};
        srv_descriptor_increment_=0;
        queries_.Reset(); timestamps_.Reset(); timing_pending_ = false; gpu_ms_ = -1.f; frequency_ = 0;
        device_ = device; width_ = width; height_ = height; srgb_ = srgb;
        D3D12_DESCRIPTOR_RANGE range{};
        range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        range.NumDescriptors = 6;
        D3D12_ROOT_PARAMETER params[2]{};
        params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        params[0].DescriptorTable = {1, &range};
        params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
        params[1].Constants = {0, 0, sizeof(ShaderConstants) / 4};
        params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        D3D12_STATIC_SAMPLER_DESC sampler{};
        sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
        sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
        sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        sampler.MaxAnisotropy = 1;
        sampler.MaxLOD = D3D12_FLOAT32_MAX;
        sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        D3D12_ROOT_SIGNATURE_DESC desc{2, params, 1, &sampler, D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT};
        ComPtr<ID3DBlob> serialized, errors;
        if (!check(D3D12SerializeRootSignature(&desc, D3D_ROOT_SIGNATURE_VERSION_1, &serialized, &errors), "Root signature") ||
            !check(device->CreateRootSignature(0, serialized->GetBufferPointer(), serialized->GetBufferSize(), IID_PPV_ARGS(&root_)), "Create root signature")) return false;
        // Compile shaders in CI and load DXBC directly. Never invoke HLSL compiler on a live XR frame.
        const auto output_format = srgb ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        D3D12_GRAPHICS_PIPELINE_STATE_DESC graphics{};
        graphics.pRootSignature = root_.Get();
        graphics.VS = {vertex_shader_bytecode, sizeof(vertex_shader_bytecode)};
        graphics.PS = {pixel_shader_bytecode, sizeof(pixel_shader_bytecode)};
        auto& blend = graphics.BlendState.RenderTarget[0];
        blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
        blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
        blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
        blend.LogicOp = D3D12_LOGIC_OP_NOOP;
        blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
        graphics.SampleMask = UINT_MAX;
        graphics.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
        graphics.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
        graphics.RasterizerState.DepthClipEnable = TRUE;
        graphics.DepthStencilState.DepthEnable = FALSE;
        graphics.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ZERO;
        graphics.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        graphics.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        graphics.NumRenderTargets = 1; graphics.RTVFormats[0] = output_format; graphics.SampleDesc.Count = 1;
        if (!check(device->CreateGraphicsPipelineState(&graphics, IID_PPV_ARGS(&pipeline_)), "Create raster PSO")) return false;
        graphics.PS = {native_pixel_shader_bytecode, sizeof(native_pixel_shader_bytecode)};
        if (!check(device->CreateGraphicsPipelineState(&graphics, IID_PPV_ARGS(&native_pipeline_)), "Create direct Native raster PSO")) return false;
        graphics.PS = {native_stereo_shader_bytecode, sizeof(native_stereo_shader_bytecode)};
        if (!check(device->CreateGraphicsPipelineState(&graphics, IID_PPV_ARGS(&stereo_pipeline_)), "Create true per-eye Native stereo raster PSO")) return false;
        graphics.PS = {native_depth_debug_shader_bytecode, sizeof(native_depth_debug_shader_bytecode)};
        if (!check(device->CreateGraphicsPipelineState(&graphics, IID_PPV_ARGS(&depth_pipeline_)), "Create Native depth diagnostic PSO")) return false;
        D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_DEFAULT; heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        D3D12_RESOURCE_DESC texture{};
        texture.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        texture.Width = width; texture.Height = height; texture.DepthOrArraySize = 1; texture.MipLevels = 1;
        texture.Format = DXGI_FORMAT_B8G8R8A8_TYPELESS; texture.SampleDesc.Count = 1;
        texture.Flags = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
        if (!check(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &texture,
            D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr, IID_PPV_ARGS(&output_)), "Create output")) return false;
        output_->SetName(L"DuoView::MonoComposite");
        D3D12_RESOURCE_DESC atlas_desc=texture;
        atlas_desc.Width=static_cast<uint64_t>(width)*2;
        atlas_desc.Height=height;
        atlas_desc.Format=srgb ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        atlas_desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
        if (!check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&atlas_desc,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&atlas_)),"Create Native gather atlas")) return false;
        atlas_->SetName(L"DuoView::NativeGatherAtlasFallback");
        D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.NumDescriptors = 3; hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        if (!check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&rtv_)), "Create RTV heap")) return false;
        hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE; hd.NumDescriptors = 6;
        if (!check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&srv_)), "Create SRV heap")) return false;
        srv_cpu_start_=srv_->GetCPUDescriptorHandleForHeapStart();
        srv_gpu_start_=srv_->GetGPUDescriptorHandleForHeapStart();
        rtv_cpu_start_=rtv_->GetCPUDescriptorHandleForHeapStart();
        srv_descriptor_increment_=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        const auto rtv_inc=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
        direct_xr_rtv_cpu_=rtv_cpu_start_;
        direct_xr_rtv_cpu_.ptr+=rtv_inc;
        stereo_atlas_rtv_cpu_=rtv_cpu_start_;
        stereo_atlas_rtv_cpu_.ptr+=2*rtv_inc;
        D3D12_RENDER_TARGET_VIEW_DESC view{}; view.Format = output_format; view.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
        device->CreateRenderTargetView(output_.Get(), &view, rtv_cpu_start_);
        device->CreateRenderTargetView(atlas_.Get(), &view, stereo_atlas_rtv_cpu_);
        D3D12_SHADER_RESOURCE_VIEW_DESC null_view{};null_view.Format=output_format;
        null_view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        null_view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;null_view.Texture2D.MipLevels=1;
        auto null_handle=srv_cpu_start_;null_handle.ptr+=4*srv_descriptor_increment_;
        for(int slot=0;slot<2;++slot) {
            device->CreateShaderResourceView(nullptr,&null_view,null_handle);null_handle.ptr+=srv_descriptor_increment_;
        }
        return true;
    }
    ComPtr<ID3D12Device> device_;
    ComPtr<ID3D12Resource> output_, source_, atlas_, primary_reference_, secondary_reference_;
    ComPtr<ID3D12Resource> srv_first_reference_, srv_second_reference_, xr_rtv_reference_, depth_first_,depth_second_;
    SurfaceReprojector surfaces_;
    ComPtr<ID3D12Resource> surface_srv_[2];
    std::shared_ptr<const void> packet_lifetime_{};
    ComPtr<ID3D12RootSignature> root_;
    ComPtr<ID3D12PipelineState> pipeline_, native_pipeline_,stereo_pipeline_,depth_pipeline_;
    ComPtr<ID3D12DescriptorHeap> srv_, rtv_;
    D3D12_CPU_DESCRIPTOR_HANDLE srv_cpu_start_{}, rtv_cpu_start_{}, direct_xr_rtv_cpu_{}, stereo_atlas_rtv_cpu_{};
    D3D12_GPU_DESCRIPTOR_HANDLE srv_gpu_start_{};
    UINT srv_descriptor_increment_{};
    ComPtr<ID3D12QueryHeap> queries_;
    ComPtr<ID3D12Resource> timestamps_;
    UINT64 frequency_{};
    float gpu_ms_{-1.f};
    bool timing_pending_{}, pending_direct_xr_{}, recorded_commands_{}, last_native_direct_xr_{}, last_true_stereo_{};
    uint64_t last_native_source_extents_{};
    uint64_t srv_descriptor_refresh_count_{}, xr_rtv_refresh_count_{};
    DXGI_FORMAT srv_cached_format_{DXGI_FORMAT_UNKNOWN}, xr_rtv_format_{DXGI_FORMAT_UNKNOWN};
    bool srv_descriptors_valid_{};
    UINT width_{}, height_{};
    bool srgb_{};
    std::string error_;
};
}


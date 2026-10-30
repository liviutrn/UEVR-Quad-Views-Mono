#pragma once
// One-shot offline diagnostics. Never used by the stereo renderer.
#include <d3d12.h>
#include "../DuoViewNgxGuide.hpp"
#include <wrl/client.h>
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <filesystem>
#include <fstream>
#include <thread>
#include <mutex>
#include <memory>
#include <vector>
#include <string>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <limits>
#include <sstream>
#include <array>
#include <iomanip>

namespace uevr::duoview::diag {
using Microsoft::WRL::ComPtr;
using GuidePlane=ngx::Plane;
struct Image {
    std::string label;
    uint64_t serial{};
    GuidePlane plane{};
    ngx::Guide ngx_guide{};
    ComPtr<ID3D12Resource> source, readback;
    D3D12_RESOURCE_STATES source_state{};
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT64 storage_bytes{};
    UINT width{}, height{}, bytes_per_pixel{};
    DXGI_FORMAT format{DXGI_FORMAT_UNKNOWN};
    bool depth{};
    std::string details;
};
struct SelectionRecord {
    uint64_t color_packet{},producer_frame{},layout_generation{};
    uint64_t left_serial{},right_serial{},left_epoch{},right_epoch{};
    uint32_t left_pass{},right_pass{},requested_mode{},effective_mode{};
    std::uintptr_t left_dsv{},right_dsv{};
    bool split_eye{},left_backup_latched{},right_backup_latched{};
    std::string depth_decision;
    // These are frozen COLOR packet cameras/projections, not authenticated
    // source-depth matrices. Keep numerical values for offline reprojection.
    std::array<double,3> left_position{},right_position{},left_rotation{},right_rotation{};
    std::array<float,16> left_projection{},right_projection{};
    std::array<float,4> crop_uv{};
    std::array<uint32_t,4> color_active_sizes{};
    std::array<float,6> left_depth_viewport{},right_depth_viewport{};
};
struct Candidate {
    ComPtr<ID3D12Resource> source;
    D3D12_RESOURCE_STATES state{};
    std::string details;
    std::string label;
    bool depth{true};
    uint64_t serial{};
    GuidePlane plane{};
    ngx::Guide ngx_guide{};
};
class Session : public std::enable_shared_from_this<Session> {
    uint64_t id_{};
    std::string metadata_, inventory_;
    SelectionRecord selection_{};
    bool selection_submission_seen_{}, selection_stereo_recorded_{}, selection_xr_copy_released_{};
    std::vector<Image> images_;
    std::vector<std::string> excluded_;
    ComPtr<ID3D12Fence> fence_;
    bool recorded_{};
    static constexpr UINT64 MaxBytes = 512ull * 1024 * 1024;
    UINT64 total_bytes_{};
    bool reserve_headset_output_{};
    bool require_complete_snapshot_{};
    bool require_ngx_{};
    bool final_output_attached_{};
    // When command recording may already have been submitted, a failed Signal
    // can NEVER authorize release of the GPU-owned source/readback buffers.
    // Deliberately quarantine the exceptional case until process teardown.
    static void quarantine_unproven(std::shared_ptr<Session> pending) {
        static auto* guard = new std::mutex;
        static auto* records = new std::vector<std::shared_ptr<Session>>;
        std::scoped_lock lock{*guard};
        records->push_back(std::move(pending));
    }
    static bool supported_depth(DXGI_FORMAT f) {
        return f==DXGI_FORMAT_R32G8X24_TYPELESS || f==DXGI_FORMAT_R32_TYPELESS ||
            f==DXGI_FORMAT_R24G8_TYPELESS || f==DXGI_FORMAT_R16_TYPELESS ||
            f==DXGI_FORMAT_R32_FLOAT || f==DXGI_FORMAT_R16_FLOAT;
    }
    static UINT bpp(DXGI_FORMAT f, bool depth) {
        if(depth && f==DXGI_FORMAT_R16_TYPELESS)return 2;
        switch(f) {
        case DXGI_FORMAT_R8G8B8A8_UNORM: case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
        case DXGI_FORMAT_R8G8B8A8_TYPELESS: case DXGI_FORMAT_B8G8R8A8_UNORM:
        case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB: case DXGI_FORMAT_B8G8R8A8_TYPELESS:
        case DXGI_FORMAT_R32_FLOAT: case DXGI_FORMAT_R32_TYPELESS:
        case DXGI_FORMAT_R32G8X24_TYPELESS:
        case DXGI_FORMAT_R11G11B10_FLOAT: case DXGI_FORMAT_R10G10B10A2_UNORM: case DXGI_FORMAT_B8G8R8X8_UNORM: case DXGI_FORMAT_R16G16_FLOAT:
        case DXGI_FORMAT_R24G8_TYPELESS: case DXGI_FORMAT_R16G16_SNORM: return 4;
        case DXGI_FORMAT_R16G16B16A16_FLOAT: case DXGI_FORMAT_R32G32_FLOAT: return 8;
        case DXGI_FORMAT_R32G32B32A32_FLOAT: return 16;
        case DXGI_FORMAT_R16_FLOAT: case DXGI_FORMAT_R16_TYPELESS: return 2;
        default:return 0;
        }
    }
    static float half_to_float(uint16_t h) {
        const int sign=h&0x8000 ? -1:1;
        const int e=(h>>10)&31, m=h&1023;
        if(e==31)return m?std::numeric_limits<float>::quiet_NaN():sign*std::numeric_limits<float>::infinity();
        if(e==0)return sign*std::ldexp(float(m),-24);
        return sign*std::ldexp(float(m+1024),e-25);
    }
    static float component(const uint8_t* p,DXGI_FORMAT f,int lane) {
        if(f==DXGI_FORMAT_R11G11B10_FLOAT) {
            uint32_t word{};std::memcpy(&word,p,4);
            const unsigned bits=lane==2?5u:6u;
            const unsigned raw=lane==0 ? (word & 2047u) :
                (lane==1 ? ((word>>11)&2047u) : ((word>>22)&1023u));
            const unsigned exponent=raw>>bits, mantissa=raw&((1u<<bits)-1u);
            if(exponent==31u)return mantissa?std::numeric_limits<float>::quiet_NaN():std::numeric_limits<float>::infinity();
            if(exponent==0u)return std::ldexp(float(mantissa),1-15-int(bits));
            return std::ldexp(float((1u<<bits)+mantissa),int(exponent)-15-int(bits));
        }
        if(f==DXGI_FORMAT_R16G16_FLOAT || f==DXGI_FORMAT_R16G16B16A16_FLOAT || f==DXGI_FORMAT_R16_FLOAT) {
            uint16_t h{};std::memcpy(&h,p+lane*2,2);return half_to_float(h);
        }
        if(f==DXGI_FORMAT_R16G16_SNORM) {
            int16_t v{};std::memcpy(&v,p+lane*2,2);
            return (std::max)(-1.f,float(v)/32767.f);
        }
        if(f==DXGI_FORMAT_R32G32_FLOAT || f==DXGI_FORMAT_R32G32B32A32_FLOAT || f==DXGI_FORMAT_R32_FLOAT) {
            float v{};std::memcpy(&v,p+lane*4,4);return v;
        }
        return 0.f;
    }
    static bool write_bytes(const std::filesystem::path& file, const void* p, size_t n) {
        std::ofstream f(file, std::ios::binary);
        if (!f) return false;
        f.write(reinterpret_cast<const char*>(p), static_cast<std::streamsize>(n));
        return bool(f);
    }
    static void write_u16(std::ofstream& f,uint16_t x) {
        char b[2]{char(x),char(x>>8)};f.write(b,2);
    }
    static void write_u32(std::ofstream& f,uint32_t x) {
        char b[4]{char(x),char(x>>8),char(x>>16),char(x>>24)};f.write(b,4);
    }
    static bool write_bmp(const std::filesystem::path& file, const std::vector<uint8_t>& bgra, UINT w,UINT h) {
        if (bgra.size()!=size_t(w)*h*4 || !w || !h || bgra.size()>UINT32_MAX-54) return false;
        std::ofstream f(file,std::ios::binary); if(!f) return false;
        f.put('B');f.put('M');write_u32(f,54+uint32_t(bgra.size()));write_u16(f,0);write_u16(f,0);
        write_u32(f,54);write_u32(f,40);write_u32(f,w);write_u32(f,h);
        write_u16(f,1);write_u16(f,32);write_u32(f,0);write_u32(f,uint32_t(bgra.size()));
        write_u32(f,2835);write_u32(f,2835);write_u32(f,0);write_u32(f,0);
        for(UINT y=h;y>0;--y)f.write(reinterpret_cast<const char*>(bgra.data()+size_t(y-1)*w*4),size_t(w)*4);
        return bool(f);
    }
    static float decode_depth(const uint8_t* p,DXGI_FORMAT fmt) {
        if(fmt==DXGI_FORMAT_R16_FLOAT) {
            uint16_t half{};std::memcpy(&half,p,2);return half_to_float(half);
        }
        if (fmt==DXGI_FORMAT_R16_TYPELESS) {
            uint16_t x{};std::memcpy(&x,p,2);return float(x)/65535.f;
        }
        if (fmt==DXGI_FORMAT_R24G8_TYPELESS) {
            uint32_t x{};std::memcpy(&x,p,4);return float(x & 0xffffffu)/16777215.f;
        }
        float z{}; std::memcpy(&z,p,4);return z;
    }
    static std::string quoted(const std::string& s) {
        std::string r="\"";
        for(char c:s) {if(c=='\"'||c=='\\') {r+='\\';r+=c;}
           else if(c=='\n')r+="\\n"; else if(c=='\r')r+="\\r"; else if(static_cast<unsigned char>(c)<32)r+='?';else r+=c;}
        return r+"\"";
    }
    bool add_image(ID3D12Device* dev, ID3D12Resource* src,
                   D3D12_RESOURCE_STATES state, std::string label, bool depth,std::string details) {
        if(!dev||!src) {excluded_.push_back(label+": missing resource");return false;}
        const auto d=src->GetDesc();
        if(d.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D || d.SampleDesc.Count!=1 ||
           d.DepthOrArraySize!=1 || d.MipLevels!=1 || d.Width>32768 || d.Height>32768 ||
           (depth ? !supported_depth(d.Format) : bpp(d.Format,false)==0)) {
            excluded_.push_back(label+": incompatible format/dimensions/MSAA");return false;
        }
        const UINT b=bpp(d.Format,depth);
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};UINT64 bytes{};
        dev->GetCopyableFootprints(&d,0,1,0,&footprint,nullptr,nullptr,&bytes);
        // Reject plane formats with unexpected layouts rather than writing falsely labeled depth.
        if(!bytes || !b || footprint.Footprint.Width!=d.Width || footprint.Footprint.Height!=d.Height ||
           footprint.Footprint.RowPitch<uint64_t(d.Width)*b ||
           total_bytes_+bytes>MaxBytes-(reserve_headset_output_ ? 128ull*1024*1024 : 0ull)) {
            excluded_.push_back(label+": readback footprint invalid or 512MiB session budget exceeded");return false;
        }
        D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_READBACK;
        hp.CreationNodeMask=hp.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC bd{};bd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;bd.Width=bytes;
        bd.Height=1;bd.DepthOrArraySize=1;bd.MipLevels=1;bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        bd.SampleDesc.Count=1;
        ComPtr<ID3D12Resource> rb;
        if(FAILED(dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&bd,
           D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&rb)))) {
            excluded_.push_back(label+": readback allocation failed");return false;
        }
        Image v;v.source=src;v.readback=std::move(rb);v.source_state=state;v.label=std::move(label);
        v.width=UINT(d.Width);v.height=d.Height;v.format=d.Format;v.depth=depth;
        v.footprint=footprint;v.storage_bytes=bytes;v.bytes_per_pixel=b;v.details=std::move(details);
        images_.push_back(std::move(v));total_bytes_+=bytes;
        return true;
    }
    void save() {
        std::filesystem::path folder;
        try {
            folder=std::filesystem::temp_directory_path()/"UEVR_DuoViewCaptures"/("capture_"+std::to_string(id_)+"_"+std::to_string(GetCurrentProcessId())+"_"+std::to_string(GetTickCount64()));
            std::filesystem::create_directories(folder);
        } catch (...) {return;}
        const auto selected_label=[&](uint64_t serial) -> std::string {
            for(const auto& image:images_)if(image.depth && serial && image.serial==serial)return image.label;
            return {};
        };
        std::ostringstream manifest;
        manifest<<std::setprecision(17);
        manifest<<"{\n \"capture_id\": "<<id_<<",\n \"frame_info\": "<<quoted(metadata_)
            <<",\n \"candidate_inventory\": "<<quoted(inventory_)
            <<",\n \"registration\": {\n"
            <<"  \"role_convention\": \"LEFT_fovea_from_UE0_RIGHT_periphery_from_UE1_UNVERIFIED\",\n"
            <<"  \"depth_to_color_frame_authenticated\": false,\n"
            <<"  \"depth_render_stage_authenticated\": false,\n"
            <<"  \"depth_eye_authenticated\": false,\n"
            <<"  \"selection_reason\": "<<quoted(selection_.depth_decision)<<",\n"
            <<"  \"left_backup_latched\": "<<(selection_.left_backup_latched?"true":"false")<<",\n"
            <<"  \"right_backup_latched\": "<<(selection_.right_backup_latched?"true":"false")<<",\n"
            <<"  \"color_packet_serial\": "<<selection_.color_packet<<",\n"
            <<"  \"producer_frame_hint\": "<<selection_.producer_frame<<",\n"
            <<"  \"layout_generation\": "<<selection_.layout_generation<<",\n"
            <<"  \"requested_mode\": "<<selection_.requested_mode<<",\n"
            <<"  \"effective_mode\": "<<selection_.effective_mode<<",\n"
            <<"  \"split_eye\": "<<(selection_.split_eye?"true":"false")<<",\n"
            <<"  \"submission_result_observed\": "<<(selection_submission_seen_?"true":"false")<<",\n"
            <<"  \"stereo_commands_recorded\": "<<(selection_stereo_recorded_?"true":"false")<<",\n"
            <<"  \"xr_copy_released\": "<<(selection_xr_copy_released_?"true":"false")<<",\n"
            <<"  \"headset_presentation_verified\": false,\n"
            <<"  \"left_depth\": {\"serial\": "<<selection_.left_serial
            <<", \"observed_pass\": "<<selection_.left_pass
            <<", \"copy_epoch\": "<<selection_.left_epoch
            <<", \"source_dsv_identity\": "<<selection_.left_dsv
            <<", \"image_label\": "<<quoted(selected_label(selection_.left_serial))<<"},\n"
            <<"  \"right_depth\": {\"serial\": "<<selection_.right_serial
            <<", \"observed_pass\": "<<selection_.right_pass
            <<", \"copy_epoch\": "<<selection_.right_epoch
            <<", \"source_dsv_identity\": "<<selection_.right_dsv
            <<", \"image_label\": "<<quoted(selected_label(selection_.right_serial))<<"},\n"
            <<"  \"selected_depth_same_copy_epoch\": "<<(selection_.left_epoch==selection_.right_epoch?"true":"false")<<",\n"
            <<"  \"selected_depth_serial_distance\": "
            <<(selection_.left_serial>selection_.right_serial
                ?selection_.left_serial-selection_.right_serial
                :selection_.right_serial-selection_.left_serial)<<",\n"
            <<"  \"color_images\": [\"left_fovea\", \"right_periphery\"],\n";
        const auto arr=[&](const auto& values) {
            manifest<<"[";
            for(size_t k=0;k<values.size();++k) {
                if(k)manifest<<",";
                if(std::isfinite(static_cast<double>(values[k])))manifest<<values[k];
                else manifest<<"null"; // malformed camera values must not invalidate JSON
            }
            manifest<<"]";
        };
        manifest<<"  \"color_packet_geometry_not_depth_authenticated\": {\n";
        manifest<<"   \"left_position\": ";arr(selection_.left_position);manifest<<",\n";
        manifest<<"   \"right_position\": ";arr(selection_.right_position);manifest<<",\n";
        manifest<<"   \"left_rotation\": ";arr(selection_.left_rotation);manifest<<",\n";
        manifest<<"   \"right_rotation\": ";arr(selection_.right_rotation);manifest<<",\n";
        manifest<<"   \"left_projection_column_major\": ";arr(selection_.left_projection);manifest<<",\n";
        manifest<<"   \"right_projection_column_major\": ";arr(selection_.right_projection);manifest<<",\n";
        manifest<<"   \"fovea_crop_uv\": ";arr(selection_.crop_uv);manifest<<",\n";
        manifest<<"   \"color_active_sizes_LwLhRwRh\": ";arr(selection_.color_active_sizes);manifest<<",\n";
        manifest<<"   \"selected_left_depth_viewport_XYWHminmax_NOT_producer_authenticated\": ";arr(selection_.left_depth_viewport);manifest<<",\n";
        manifest<<"   \"selected_right_depth_viewport_XYWHminmax_NOT_producer_authenticated\": ";arr(selection_.right_depth_viewport);manifest<<"\n";
        manifest<<"  },\n"
            <<"  \"same_engine_frame_verified\": false\n"
            <<" },\n \"images\": [\n";
        bool left_raw_written=false;
        unsigned ngx_raw_planes=0;
        bool right_raw_written=false;
        for(size_t i=0;i<images_.size();++i) {
            auto& im=images_[i];
            std::vector<uint8_t> packed(size_t(im.width)*im.height*im.bytes_per_pixel);
            D3D12_RANGE read{0,static_cast<SIZE_T>(im.storage_bytes)};void* map{};
            bool ok=SUCCEEDED(im.readback->Map(0,&read,&map))&&map;
            if(ok) {
                for(UINT y=0;y<im.height;++y) std::memcpy(
                    packed.data()+size_t(y)*im.width*im.bytes_per_pixel,
                    static_cast<const uint8_t*>(map)+size_t(y)*im.footprint.Footprint.RowPitch,
                    size_t(im.width)*im.bytes_per_pixel);
                D3D12_RANGE nw{0,0};im.readback->Unmap(0,&nw);
            }
            const auto base="image_"+std::to_string(i)+"_"+im.label;
            bool raw=ok && write_bytes(folder/(base+".raw"),packed.data(),packed.size());
            if(raw && im.depth && selection_.left_serial && im.serial==selection_.left_serial)
                left_raw_written=true;
            if(raw && im.depth && selection_.right_serial && im.serial==selection_.right_serial)
                right_raw_written=true;
            if(raw && im.ngx_guide && im.ngx_guide.role>=1 && im.ngx_guide.role<=2 && im.plane!=GuidePlane::none)
                ngx_raw_planes|=1u<<((im.ngx_guide.role-1u)*3u+unsigned(im.plane)-1u);
            bool bmp=false;
            if(ok&&!im.depth) {
                const bool mv=im.label.find("_motion")!=std::string::npos;
                const bool rgba8=im.format==DXGI_FORMAT_R8G8B8A8_UNORM ||
                    im.format==DXGI_FORMAT_R8G8B8A8_UNORM_SRGB || im.format==DXGI_FORMAT_R8G8B8A8_TYPELESS;
                const bool packed10=im.format==DXGI_FORMAT_R10G10B10A2_UNORM;
                const bool bgra8=im.format==DXGI_FORMAT_B8G8R8A8_UNORM ||
                    im.format==DXGI_FORMAT_B8G8R8X8_UNORM ||
                    im.format==DXGI_FORMAT_B8G8R8A8_UNORM_SRGB || im.format==DXGI_FORMAT_B8G8R8A8_TYPELESS;
                const bool floating=im.format==DXGI_FORMAT_R11G11B10_FLOAT || im.format==DXGI_FORMAT_R16G16_SNORM || im.format==DXGI_FORMAT_R16G16_FLOAT ||
                    im.format==DXGI_FORMAT_R32G32_FLOAT || im.format==DXGI_FORMAT_R16G16B16A16_FLOAT ||
                    im.format==DXGI_FORMAT_R32G32B32A32_FLOAT || im.format==DXGI_FORMAT_R32_FLOAT;
                if(rgba8 || bgra8 || floating || packed10) {
                    std::vector<uint8_t> display(size_t(im.width)*im.height*4,255);
                    float mvmax=1.f;
                    if(mv && floating){
                        std::vector<float> v;v.reserve(size_t(im.width)*im.height);
                        for(size_t j=0;j<size_t(im.width)*im.height;++j){
                            const auto* p=packed.data()+j*im.bytes_per_pixel;
                            const float x=component(p,im.format,0),
                                y=im.format==DXGI_FORMAT_R32_FLOAT ? x : component(p,im.format,1);
                            if(std::isfinite(x)&&std::isfinite(y))v.push_back((std::max)(std::abs(x),std::abs(y)));
                        }
                        if(!v.empty()){
                            auto it=v.begin()+size_t(double(v.size())*.99);
                            std::nth_element(v.begin(),it,v.end());mvmax=(std::max)(1e-5f,*it);
                        }
                    }
                    for(size_t j=0;j<size_t(im.width)*im.height;++j){
                        const auto* p=packed.data()+j*im.bytes_per_pixel;
                        auto* q=display.data()+j*4;
                        if(rgba8){q[0]=p[2];q[1]=p[1];q[2]=p[0];q[3]=255;}
                        else if(bgra8){q[0]=p[0];q[1]=p[1];q[2]=p[2];q[3]=255;}
                        else if(packed10){
                            uint32_t word{};std::memcpy(&word,p,4);
                            q[2]=uint8_t((word&1023u)*255u/1023u);
                            q[1]=uint8_t(((word>>10)&1023u)*255u/1023u);
                            q[0]=uint8_t(((word>>20)&1023u)*255u/1023u);
                            q[3]=255;
                        }
                        else if(floating){
                            const float x=component(p,im.format,0),
                                y=im.format==DXGI_FORMAT_R32_FLOAT ? x : component(p,im.format,1);
                            if(mv){
                                q[2]=uint8_t(std::clamp(.5f+.5f*x/mvmax,0.f,1.f)*255.f);
                                q[1]=uint8_t(std::clamp(.5f+.5f*y/mvmax,0.f,1.f)*255.f);
                                q[0]=127;q[3]=255;
                            } else {
                                const auto encode=[](float x) {x=std::isfinite(x)?(std::max)(0.f,x):0.f;return uint8_t(std::clamp(std::pow(x/(1.f+x),1.f/2.2f),0.f,1.f)*255.f);};
                                q[2]=encode(x);q[1]=encode(y);
                                q[0]=encode((im.format==DXGI_FORMAT_R11G11B10_FLOAT || im.format==DXGI_FORMAT_R16G16B16A16_FLOAT || im.format==DXGI_FORMAT_R32G32B32A32_FLOAT) ? component(p,im.format,2) : x);
                                q[3]=255;
                            }
                        }
                    }
                    bmp=write_bmp(folder/(base+(mv?"_mv_preview.bmp":"_color_preview.bmp")),display,im.width,im.height);
                }
            }
            if(ok&&im.depth) {
                // Contrast visualization is for visual checking ONLY; raw remains authoritative.
                std::vector<float> z(size_t(im.width)*im.height);
                std::vector<float> sorted;sorted.reserve(z.size());
                for(size_t p=0;p<z.size();++p) {
                    z[p]=decode_depth(packed.data()+p*im.bytes_per_pixel,im.format);
                    if(std::isfinite(z[p]) && z[p]>=0.f && z[p]<=1.f) sorted.push_back(z[p]);
                }
                if(!sorted.empty()) {
                    auto lo=sorted.begin()+sorted.size()/100;
                    auto hi=sorted.begin()+sorted.size()*99/100;
                    std::nth_element(sorted.begin(),lo,sorted.end());float v0=*lo;
                    std::nth_element(sorted.begin(),hi,sorted.end());float v1=*hi;
                    const float span=(std::max)(1e-6f,v1-v0);
                    std::vector<uint8_t> gray(z.size()*4,255);
                    for(size_t p=0;p<z.size();++p) {
                        uint8_t q=(std::isfinite(z[p])&&z[p]>=0&&z[p]<=1)
                            ? uint8_t(std::clamp((z[p]-v0)/span,0.f,1.f)*255.f) : 0;
                        gray[p*4]=gray[p*4+1]=gray[p*4+2]=q;
                    }
                    bmp=write_bmp(folder/(base+"_depth_preview.bmp"),gray,im.width,im.height);
                }
            }
            manifest<<"  {\"label\": "<<quoted(im.label)<<", \"width\": "<<im.width
                <<", \"height\": "<<im.height<<", \"DXGI_format\": "<<unsigned(im.format)
                <<", \"bytes_per_pixel\": "<<im.bytes_per_pixel
                <<", \"depth\": "<<(im.depth?"true":"false")
                <<", \"raw\": "<<(raw?"true":"false")<<", \"bmp\": "<<(bmp?"true":"false")
                <<", \"raw_row_stride\": "<<im.width*im.bytes_per_pixel
                <<", \"details\": "<<quoted(im.details);
            manifest<<", \"serial\": "<<im.serial;
            if(im.ngx_guide) {
                const auto& g=im.ngx_guide;
                manifest<<", \"ngx\": {\"packet\": "<<g.producer.packet
                    <<", \"generation\": "<<g.producer.generation<<", \"draw\": "<<g.producer.draw
                    <<", \"render_frame\": "<<g.producer.render_frame<<", \"role\": "<<g.role
                    <<", \"evaluation\": "<<g.evaluation<<", \"feature_generation\": "<<g.feature_generation
                    <<", \"feature_kind\": "<<g.feature_kind<<", \"create_observed\": "<<(g.create_observed?"true":"false")
                    <<", \"flags_known\": "<<(g.flags_known?"true":"false")<<", \"flags\": "<<g.flags
                    <<", \"reset\": "<<g.reset<<", \"input_size\": ["<<g.input_width<<","<<g.input_height
                    <<"], \"output_size\": ["<<g.output_width<<","<<g.output_height
                    <<"], \"depth_base\": ["<<g.depth_x<<","<<g.depth_y
                    <<"], \"color_base\": ["<<g.color_x<<","<<g.color_y
                    <<"], \"motion_base\": ["<<g.motion_x<<","<<g.motion_y
                    <<"], \"jitter_pixels\": ["<<g.jitter_x<<","<<g.jitter_y
                    <<"], \"motion_scale\": ["<<g.motion_scale_x<<","<<g.motion_scale_y
                    <<"], \"motion_low_resolution\": "<<(g.motion_low_resolution?"true":"false")
                    <<", \"motion_extent_known\": "<<(g.motion_extent_known?"true":"false")
                    <<", \"rhi_packet_associated\": true, \"per_pass_camera_authenticated\": false}";
            }
            if(ok && !im.depth && im.bytes_per_pixel==4 && im.label.starts_with("surface_")) {
                uint64_t accepted=0;
                for(size_t p=3;p<packed.size();p+=4)accepted+=packed[p]==255;
                manifest<<", \"surface_covered_pixels\": "<<accepted
                    <<", \"surface_total_pixels\": "<<uint64_t(im.width)*im.height
                    <<", \"surface_coverage\": "<<double(accepted)/(uint64_t(im.width)*im.height);
            }
            manifest<<"}";
            if(i+1<images_.size())manifest<<",";
            manifest<<"\n";
        }
        manifest<<" ],\n \"selected_depth_raw_complete\": "
                <<(left_raw_written && right_raw_written ? "true" : "false")
                <<",\n \"ngx_six_raw_complete\": "<<(ngx_raw_planes==63u?"true":"false")
                <<",\n \"excluded\": [";
        for(size_t j=0;j<excluded_.size();++j) {
            if(j)manifest<<", ";
            manifest<<quoted(excluded_[j]);
        }
        manifest<<"]\n}\n";
        const auto v=manifest.str();write_bytes(folder/"manifest.json",v.data(),v.size());
    }
public:
    explicit Session(uint64_t id,std::string metadata,std::string inventory)
       : id_(id),metadata_(std::move(metadata)),inventory_(std::move(inventory)) {}
    void set_selection(SelectionRecord value) {selection_=value;}
    bool prepare(ID3D12Device* dev,ID3D12Resource* left,ID3D12Resource* right,
           const std::vector<Candidate>& depths,
           bool reserveHeadsetOutput=false,bool requireNgx=false) {
        reserve_headset_output_=reserveHeadsetOutput;
        require_complete_snapshot_=reserveHeadsetOutput;
        require_ngx_=requireNgx;
        add_image(dev,left,D3D12_RESOURCE_STATE_RENDER_TARGET,"left_fovea",false,"UE0 split-left color; allocation (may include inactive pixels)");
        add_image(dev,right,D3D12_RESOURCE_STATE_RENDER_TARGET,"right_periphery",false,"UE1 split-right color; allocation (may include inactive pixels)");
        size_t n=0;
        for(const auto& candidate:depths) {
            ++n;
            if(add_image(dev,candidate.source.Get(),candidate.state,
                      candidate.label.empty()?"depth_"+std::to_string(candidate.serial):candidate.label,
                      candidate.depth,candidate.details)) {
                auto& image=images_.back();image.serial=candidate.serial;
                image.plane=candidate.plane;image.ngx_guide=candidate.ngx_guide;
            }
        }
        if(n==0)excluded_.push_back("No eligible submitted DSV source available in this capture interval");
        // A capture with unrelated depth previews cannot diagnose the selected stereo
        // pair. Refuse the session rather than silently shipping a misleading manifest.
        if(selection_.effective_mode >= 4 && selection_.left_serial && selection_.right_serial) {
            const auto contains_depth=[&](uint64_t serial) {
                return std::any_of(images_.begin(),images_.end(),[&](const Image& im) {
                    return im.depth && im.serial==serial;
                });
            };
            if(!contains_depth(selection_.left_serial) || !contains_depth(selection_.right_serial)) {
                excluded_.push_back("SELECTED_STEREO_DEPTH_NOT_CAPTURED: readback budget or source mismatch");
                return false;
            }
        }
        const bool left_ready=std::any_of(images_.begin(),images_.end(),
            [](const Image& i){return i.label=="left_fovea";});
        const bool right_ready=std::any_of(images_.begin(),images_.end(),
            [](const Image& i){return i.label=="right_periphery";});
        const bool depth_ready=std::any_of(images_.begin(),images_.end(),
            [](const Image& i){return i.depth;});
        if(require_ngx_) {
            std::vector<ngx::SnapshotIdentity> identities;
            identities.reserve(images_.size());
            for(const auto& image:images_)identities.push_back({image.ngx_guide,image.serial,image.plane});
            if(!ngx::complete_snapshot(identities,selection_.left_serial,selection_.right_serial,
                selection_.color_packet,selection_.layout_generation)) {
                excluded_.push_back("Incomplete or mismatched NGX six-input capture");
                return false;
            }
        }
        return left_ready && right_ready && (!require_complete_snapshot_ || depth_ready);
    }
    void attach_surface_outputs(ID3D12Device* dev,ID3D12Resource* right,ID3D12Resource* left) {
        if(right)add_image(dev,right,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,
            "surface_right_fovea",false,"Source-depth RIGHT fovea. Alpha 255 = reconstructed geometry; alpha 0 = real-R fallback. Frozen matrices are NOT depth-pass authenticated.");
        if(left)add_image(dev,left,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,
            "surface_left_periphery",false,"Source-depth LEFT periphery. Alpha 255 = reconstructed geometry; alpha 0 = unavailable target surface (unwarped real-R fallback).");
    }
    void note_submission(bool xrCopyReleased,unsigned outcome,bool stereoRecorded) {
        selection_submission_seen_=true;
        selection_stereo_recorded_=stereoRecorded;
        selection_xr_copy_released_=xrCopyReleased;
        metadata_+=" readbackCommandsEnqueued=true xrCopyReleased=";
        metadata_+=xrCopyReleased ? "true" : "false";
        metadata_+=" executeOutcome="+std::to_string(outcome);
        metadata_+=" actualStereoRecorded=";metadata_+=stereoRecorded ? "true" : "false";
        metadata_+=" headsetPresentationVerified=false";
    }
    bool attach_headset_output(ID3D12Device* dev,ID3D12Resource* destination) {
        if(final_output_attached_)return true;
        reserve_headset_output_=false;
        // GPU copy occurs only after actual stereo pixel shader has drawn.
        // The R5 sources and final headset target share the same OpenXR
        // command-list and fence, so the manifest describes ONE frame.
        if(!add_image(dev,destination,D3D12_RESOURCE_STATE_RENDER_TARGET,
                         "xr_submitted_doublewide",false,
                         "FINAL headset image. LEFT x=0..W-1, RIGHT x=W..2W-1; same copy command as source color and depth."))return false;
        final_output_attached_=true;
        return true;
    }
    bool record(ID3D12GraphicsCommandList* cmd) {
        if(!cmd||recorded_||images_.empty() ||
           (require_complete_snapshot_ && !final_output_attached_))return false;
        for(auto& im:images_) {
            D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barrier.Transition={im.source.Get(),0,im.source_state,D3D12_RESOURCE_STATE_COPY_SOURCE};
            if(im.source_state!=D3D12_RESOURCE_STATE_COPY_SOURCE)cmd->ResourceBarrier(1,&barrier);
            D3D12_TEXTURE_COPY_LOCATION from{},to{};
            from.pResource=im.source.Get();from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            from.SubresourceIndex=0;
            to.pResource=im.readback.Get();to.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            to.PlacedFootprint=im.footprint;
            cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
            if(im.source_state!=D3D12_RESOURCE_STATE_COPY_SOURCE) {
                std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter);
                cmd->ResourceBarrier(1,&barrier);
            }
        }
        recorded_=true;return true;
    }
    bool launch(ID3D12Device* dev,ID3D12CommandQueue* q) {
        if(!recorded_) return false;
        const auto self=shared_from_this();
        if(!dev || !q ||
           FAILED(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence_))) ||
           FAILED(q->Signal(fence_.Get(),1))) {
            quarantine_unproven(self); // copy may already be enqueued
            return false;
        }
        try {
            std::thread([self] {
                // No GPU waits and no file I/O on the OpenXR render thread.
                HANDLE e=CreateEventW(nullptr,FALSE,FALSE,nullptr);
                bool event_waited=false;
                if(e) {
                    if(SUCCEEDED(self->fence_->SetEventOnCompletion(1,e)))
                        event_waited=(WaitForSingleObject(e,INFINITE)==WAIT_OBJECT_0);
                    CloseHandle(e);
                }
                if(!event_waited) {
                    for(;;) {
                        const auto done=self->fence_->GetCompletedValue();
                        if(done>=1) break; // UINT64_MAX also indicates device removed
                        Sleep(25);
                    }
                }
                const auto done=self->fence_->GetCompletedValue();
                if(done>=1 && done!=UINT64_MAX) {
                    try { self->save(); }
                    catch(...) { OutputDebugStringA("DuoView: capture file saving failed\n"); }
                }
            }).detach();
        } catch(...) {
            quarantine_unproven(self);
            return false;
        }
        return true;
    }
};
} // namespace

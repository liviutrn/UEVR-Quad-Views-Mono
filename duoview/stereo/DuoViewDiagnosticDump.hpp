#pragma once
// One-shot offline diagnostics. Never used by the stereo renderer.
#include <d3d12.h>
#include <wrl/client.h>
#include <windows.h>
#include <filesystem>
#include <fstream>
#include <thread>
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

namespace uevr::duoview::diag {
using Microsoft::WRL::ComPtr;
struct Image {
    std::string label;
    ComPtr<ID3D12Resource> source, readback;
    D3D12_RESOURCE_STATES source_state{};
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT64 storage_bytes{};
    UINT width{}, height{}, bytes_per_pixel{};
    DXGI_FORMAT format{DXGI_FORMAT_UNKNOWN};
    bool depth{};
    std::string details;
};
struct Candidate {
    ComPtr<ID3D12Resource> source;
    D3D12_RESOURCE_STATES state{};
    std::string details;
    uint64_t serial{};
};
class Session : public std::enable_shared_from_this<Session> {
    uint64_t id_{};
    std::string metadata_, inventory_;
    std::vector<Image> images_;
    std::vector<std::string> excluded_;
    ComPtr<ID3D12Fence> fence_;
    bool recorded_{};
    static constexpr UINT64 MaxBytes = 512ull * 1024 * 1024;
    UINT64 total_bytes_{};
    static bool supported_depth(DXGI_FORMAT f) {
        return f==DXGI_FORMAT_R32G8X24_TYPELESS || f==DXGI_FORMAT_R32_TYPELESS ||
            f==DXGI_FORMAT_R24G8_TYPELESS || f==DXGI_FORMAT_R16_TYPELESS;
    }
    static UINT bpp(DXGI_FORMAT f, bool depth) {
        if (!depth) return 4;
        if (f == DXGI_FORMAT_R16_TYPELESS) return 2;
        return 4; // depth plane zero for D32S8 and D32; packed D24 for D24S8
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
           (depth ? !supported_depth(d.Format) :
               !(d.Format==DXGI_FORMAT_B8G8R8A8_UNORM || d.Format==DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
                 d.Format==DXGI_FORMAT_B8G8R8A8_TYPELESS))) {
            excluded_.push_back(label+": incompatible format/dimensions/MSAA");return false;
        }
        const UINT b=bpp(d.Format,depth);
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};UINT64 bytes{};
        dev->GetCopyableFootprints(&d,0,1,0,&footprint,nullptr,nullptr,&bytes);
        // Reject plane formats with unexpected layouts rather than writing falsely labeled depth.
        if(!bytes || !b || footprint.Footprint.Width!=d.Width || footprint.Footprint.Height!=d.Height ||
           footprint.Footprint.RowPitch<uint64_t(d.Width)*b ||
           total_bytes_+bytes>MaxBytes) {
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
        std::ostringstream manifest;
        manifest<<"{\n \"capture_id\": "<<id_<<",\n \"frame_info\": "<<quoted(metadata_)
            <<",\n \"candidate_inventory\": "<<quoted(inventory_)<<",\n \"images\": [\n";
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
            bool bmp=false;
            if(ok&&!im.depth) bmp=write_bmp(folder/(base+".bmp"),packed,im.width,im.height);
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
                    const float span=std::max(1e-6f,v1-v0);
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
                <<", \"details\": "<<quoted(im.details)<<"}";
            if(i+1<images_.size())manifest<<",";
            manifest<<"\n";
        }
        manifest<<" ],\n \"excluded\": [";
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
    bool prepare(ID3D12Device* dev,ID3D12Resource* left,ID3D12Resource* right,
           const std::vector<Candidate>& depths) {
        add_image(dev,left,D3D12_RESOURCE_STATE_RENDER_TARGET,"left_fovea",false,"UE0 split-left color; allocation (may include inactive pixels)");
        add_image(dev,right,D3D12_RESOURCE_STATE_RENDER_TARGET,"right_periphery",false,"UE1 split-right color; allocation (may include inactive pixels)");
        size_t n=0;
        for(const auto& candidate:depths) {
            ++n;
            add_image(dev,candidate.source.Get(),candidate.state,"depth_"+std::to_string(candidate.serial),
                      true,candidate.details);
        }
        if(n==0)excluded_.push_back("No eligible submitted DSV source available in this capture interval");
        return images_.size()>=2; // do not alter the original XR output if some depth allocations fail
    }
    bool record(ID3D12GraphicsCommandList* cmd) {
        if(!cmd||recorded_||images_.empty())return false;
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
        if(!recorded_||!dev||!q) return false;
        if(FAILED(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence_))))return false;
        if(FAILED(q->Signal(fence_.Get(),1)))return false;
        auto self=shared_from_this();
        std::thread([self] {
            // GPU completion is waited ONLY on a worker thread.
            HANDLE e=CreateEventW(nullptr,FALSE,FALSE,nullptr);
            if(e) {
                if(SUCCEEDED(self->fence_->SetEventOnCompletion(1,e)))
                    WaitForSingleObject(e,INFINITE);
                CloseHandle(e);
            } else {
                while(self->fence_->GetCompletedValue()<1) Sleep(25);
            }
            if(self->fence_->GetCompletedValue()>=1)self->save();
        }).detach();
        return true;
    }
};
} // namespace

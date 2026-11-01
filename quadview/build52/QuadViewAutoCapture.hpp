#pragma once
// Build 52 only: one-shot, read-only GPU capture, no headset-image modifications.
// The command-list slot owns this object until its GPU fence retires.
#include <d3d12.h>
#include <wrl/client.h>
#include <spdlog/spdlog.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace uevr::quadview::diagnostics {
using Microsoft::WRL::ComPtr;

struct ZipEntry {
    std::string name, data;
    uint32_t crc{}, offset{};
};
inline uint32_t crc32(const std::string& s) {
    uint32_t crc = 0xffffffffu;
    for (const unsigned char ch : s) {
        crc ^= ch;
        for (int k=0;k<8;k++) crc = (crc>>1) ^ ((crc&1u) ? 0xedb88320u : 0u);
    }
    return ~crc;
}
inline void zip16(std::ostream& s,uint16_t v) { s.put(char(v));s.put(char(v>>8)); }
inline void zip32(std::ostream& s,uint32_t v) { zip16(s,uint16_t(v));zip16(s,uint16_t(v>>16)); }
inline bool write_store_zip(const std::filesystem::path& path,std::vector<ZipEntry>& entries) {
    std::ofstream out(path,std::ios::binary|std::ios::trunc);
    if (!out) return false;
    for (auto& e:entries) {
        e.crc=crc32(e.data);
        e.offset=static_cast<uint32_t>(static_cast<std::streamoff>(out.tellp()));
        zip32(out,0x04034b50);zip16(out,20);zip16(out,0);zip16(out,0);
        zip16(out,0);zip16(out,0);zip32(out,e.crc);
        zip32(out,static_cast<uint32_t>(e.data.size()));zip32(out,static_cast<uint32_t>(e.data.size()));
        zip16(out,static_cast<uint16_t>(e.name.size()));zip16(out,0);
        out.write(e.name.data(),static_cast<std::streamsize>(e.name.size()));
        out.write(e.data.data(),static_cast<std::streamsize>(e.data.size()));
    }
    const auto central_start=static_cast<uint32_t>(static_cast<std::streamoff>(out.tellp()));
    for (const auto& e:entries) {
        zip32(out,0x02014b50);zip16(out,20);zip16(out,20);zip16(out,0);zip16(out,0);
        zip16(out,0);zip16(out,0);zip32(out,e.crc);
        zip32(out,static_cast<uint32_t>(e.data.size()));zip32(out,static_cast<uint32_t>(e.data.size()));
        zip16(out,static_cast<uint16_t>(e.name.size()));
        zip16(out,0);zip16(out,0);zip16(out,0);zip16(out,0);zip32(out,0);zip32(out,e.offset);
        out.write(e.name.data(),static_cast<std::streamsize>(e.name.size()));
    }
    const auto central_end=static_cast<uint32_t>(static_cast<std::streamoff>(out.tellp()));
    zip32(out,0x06054b50);zip16(out,0);zip16(out,0);
    zip16(out,static_cast<uint16_t>(entries.size()));zip16(out,static_cast<uint16_t>(entries.size()));
    zip32(out,central_end-central_start);zip32(out,central_start);zip16(out,0);
    out.flush();
    return out.good();
}

class AutoCapture {
public:
    // Invoked AFTER the existing shader draw. Sources are still in PIXEL_SHADER_RESOURCE state.
    // Never change the image sent to the headset, and never fail the render on capture failure.
    void queue(ID3D12GraphicsCommandList* cmd,ID3D12Device* device,
               const std::array<ID3D12Resource*,4>& src,const Layout& layout) {
        if (pending_ || !cmd || !device || frames_.fetch_add(1,std::memory_order_relaxed)<120) return;
        unsigned expected=0;
        if (!global_.compare_exchange_strong(expected,1,std::memory_order_acq_rel)) return;
        if (!prepare(device,src,layout)) {
            spdlog::warn("[QuadViews][Build52] GPU diagnostic staging failed, retrying later");
            buffer_.Reset();
            global_.store(0,std::memory_order_release);
            return;
        }
        for (size_t role=0;role<4;++role) {
            transition(cmd,src[role],D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE);
            for (size_t band=0;band<BANDS;++band) {
                const auto& fp=footprints_[role*BANDS+band];
                D3D12_TEXTURE_COPY_LOCATION dst{};
                dst.pResource=buffer_.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
                dst.PlacedFootprint=fp;
                D3D12_TEXTURE_COPY_LOCATION from{};
                from.pResource=src[role];from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;from.SubresourceIndex=0;
                D3D12_BOX box{0,ys_[band],0,width_,ys_[band]+ROWS,1};
                cmd->CopyTextureRegion(&dst,0,0,0,&from,&box);
            }
            transition(cmd,src[role],D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        }
        pending_=true;
        spdlog::info("[QuadViews][Build52] GPU copy queued: width={} height={} format={} rows/band={} bands={} roles=4",
                     width_,height_,static_cast<int>(format_),ROWS,BANDS);
    }

    // Called ONLY after the command slot's confirmed completed GPU fence.
    void finish() {
        if (!pending_) return;
        pending_=false;
        if (!buffer_) { global_.store(0,std::memory_order_release);return; }
        try {
            D3D12_RANGE range{0,static_cast<SIZE_T>(bytes_)};
            const uint8_t* memory{};
            if (FAILED(buffer_->Map(0,&range,reinterpret_cast<void**>(const_cast<uint8_t**>(&memory)))) || !memory) {
                spdlog::warn("[QuadViews][Build52] readback Map failed");
                global_.store(0,std::memory_order_release);
                buffer_.Reset();return;
            }
            std::vector<ZipEntry> entries;
            std::ostringstream summary, tiles;
            summary<<"role,band,y,first_nonblack_x,last_nonblack_x,nonblack_left_half,nonblack_right_half,"
                     "nonblack_expected_rect,nonblack_zero_origin,source_width,source_height,expected_x,expected_width\n";
            tiles<<"role,band,y,tile_x,tile_width,nonblack_pixels\n";
            for (size_t role=0;role<4;++role) {
                std::string ppm="P6\n"+std::to_string(width_)+" "+std::to_string(ROWS*BANDS)+"\n255\n";
                ppm.reserve(ppm.size()+size_t(width_)*ROWS*BANDS*3);
                for (size_t band=0;band<BANDS;++band) {
                    const auto& fp=footprints_[role*BANDS+band];
                    const uint8_t* const start=memory+fp.Offset;
                    uint64_t left=0,right=0,expected=0,from_zero=0;
                    int first=-1,last=-1;
                    std::vector<uint32_t> coverage((width_+63)/64,0);
                    for (uint32_t row=0;row<ROWS;++row) {
                        const auto* line=start+size_t(row)*fp.Footprint.RowPitch;
                        for (uint32_t x=0;x<width_;++x) {
                            const auto rgb=pixel(line+size_t(x)*bpp_);
                            ppm.push_back(char(rgb[0]));ppm.push_back(char(rgb[1]));ppm.push_back(char(rgb[2]));
                            const bool nonblack=rgb[0]>10 || rgb[1]>10 || rgb[2]>10;
                            if (!nonblack) continue;
                            if (first<0) first=int(x);
                            last=int(x);
                            ++coverage[x/64];
                            if (x<layout_.eye_width) ++left; else ++right;
                            const auto& rect=layout_.views[role];
                            if (x>=rect.x && uint64_t(x)<uint64_t(rect.x)+rect.width) ++expected;
                            if (x<rect.width) ++from_zero;
                        }
                    }
                    summary<<role<<','<<band<<','<<ys_[band]<<','<<first<<','<<last<<','
                           <<left<<','<<right<<','<<expected<<','<<from_zero<<','
                           <<width_<<','<<height_<<','<<layout_.views[role].x<<','
                           <<layout_.views[role].width<<'\n';
                    for (size_t i=0;i<coverage.size();++i)
                        tiles<<role<<','<<band<<','<<ys_[band]<<','<<(i*64)<<','
                             <<(std::min)(size_t(64),size_t(width_)-i*64)<<','
                             <<coverage[i]<<'\n';
                }
                entries.push_back({"role_"+std::to_string(role)+".ppm",std::move(ppm)});
            }
            D3D12_RANGE no_write{0,0};
            buffer_->Unmap(0,&no_write);
            entries.push_back({"coverage_summary.csv",summary.str()});
            entries.push_back({"coverage_tiles_64px.csv",tiles.str()});
            std::ostringstream meta;
            meta<<"Build 52 GPU source probe; capture once after 120 accepted composites.\n"
                <<"Source positions are RAW pixels, not headset observations. Seven 8-pixel horizontal strips\n"
                <<"at different source Y positions, stacked into each role_N.ppm (P6 format).\n"
                <<"Role 0 = left periphery, 1 = right periphery, 2 = left fovea, 3 = right fovea.\n"
                <<"Expected view X offsets are the original Build51 layout. Compare nonblack_expected_rect\n"
                <<"against nonblack_zero_origin and inspect coverage_tiles_64px.csv.\n"
                <<"A zero/nonzero reading alone cannot prove a render was skipped: dark scenes and GPU state\n"
                <<"may require comparison with UEVR hook logs. No DLSS or shader image changes are made.\n"
                <<"width="<<width_<<" height="<<height_<<" dxgi_format="<<int(format_)
                <<" bytes_per_pixel="<<bpp_<<" role_width="<<layout_.eye_width<<"\n";
            for (size_t role=0;role<4;++role)
                meta<<"role="<<role<<" expected_x="<<layout_.views[role].x
                    <<" expected_y="<<layout_.views[role].y
                    <<" expected_w="<<layout_.views[role].width
                    <<" expected_h="<<layout_.views[role].height<<"\n";
            entries.push_back({"README.txt",meta.str()});
            std::error_code ec;
            auto folder=std::filesystem::temp_directory_path(ec);
            if (ec) folder=std::filesystem::current_path();
            const auto path=folder/("UEVR_Build52_Diagnostics_"+std::to_string(GetCurrentProcessId())+".zip");
            const bool ok=write_store_zip(path,entries);
            spdlog::info("[QuadViews][Build52] {} diagnostics ZIP: {}",ok?"saved":"FAILED saving",path.string());
            global_.store(ok?2u:0u,std::memory_order_release);
        } catch (const std::exception& e) {
            spdlog::error("[QuadViews][Build52] diagnostic serialization failed: {}",e.what());
            global_.store(0,std::memory_order_release);
        } catch (...) {
            spdlog::error("[QuadViews][Build52] unknown diagnostic serialization failure");
            global_.store(0,std::memory_order_release);
        }
        buffer_.Reset();
    }

private:
    static constexpr uint32_t ROWS=8;
    static constexpr size_t BANDS=7;
    static inline std::atomic<unsigned> global_{0};
    static inline std::atomic<uint64_t> frames_{0};
    std::array<D3D12_PLACED_SUBRESOURCE_FOOTPRINT,4*BANDS> footprints_{};
    std::array<uint32_t,BANDS> ys_{};
    ComPtr<ID3D12Resource> buffer_;
    Layout layout_{};
    DXGI_FORMAT format_{DXGI_FORMAT_UNKNOWN};
    uint32_t width_{},height_{},bpp_{};
    uint64_t bytes_{};
    bool pending_{};

    static uint64_t align(uint64_t n,uint64_t a) {return (n+a-1)&~(a-1);}
    static void transition(ID3D12GraphicsCommandList* cmd,ID3D12Resource* res,
                           D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after) {
        D3D12_RESOURCE_BARRIER b{};
        b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition.pResource=res;
        b.Transition.Subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        b.Transition.StateBefore=before;b.Transition.StateAfter=after;
        cmd->ResourceBarrier(1,&b);
    }
    bool prepare(ID3D12Device* device,const std::array<ID3D12Resource*,4>& src,const Layout& layout) {
        if (!layout.eye_width || !layout.eye_height) return false;
        for (auto* r:src) if (!r) return false;
        const auto d=src[0]->GetDesc();
        if (d.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D || d.DepthOrArraySize!=1 ||
            d.MipLevels!=1 || d.SampleDesc.Count!=1 || d.Width>16384 || d.Height<ROWS) return false;
        for (size_t i=1;i<4;++i) {
            const auto other=src[i]->GetDesc();
            if (other.Width!=d.Width || other.Height!=d.Height || other.Format!=d.Format ||
                other.SampleDesc.Count!=1) return false;
        }
        switch (d.Format) {
        case DXGI_FORMAT_R8G8B8A8_UNORM:case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
        case DXGI_FORMAT_R8G8B8A8_TYPELESS:case DXGI_FORMAT_B8G8R8A8_UNORM:
        case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:case DXGI_FORMAT_B8G8R8A8_TYPELESS:
        case DXGI_FORMAT_R10G10B10A2_UNORM:case DXGI_FORMAT_R10G10B10A2_TYPELESS:
            bpp_=4;break;
        case DXGI_FORMAT_R16G16B16A16_FLOAT:case DXGI_FORMAT_R16G16B16A16_TYPELESS:
            bpp_=8;break;
        default:spdlog::warn("[QuadViews][Build52] unsupported source format {}",int(d.Format));return false;
        }
        width_=static_cast<uint32_t>(d.Width);height_=d.Height;format_=d.Format;layout_=layout;
        const std::array<float,BANDS> fractions{{.03f,.13f,.25f,.50f,.75f,.87f,.97f}};
        for (size_t band=0;band<BANDS;++band)
            ys_[band]=(std::min)(static_cast<uint32_t>(height_*fractions[band]),height_-ROWS);
        const uint64_t row_pitch=align(uint64_t(width_)*bpp_,D3D12_TEXTURE_DATA_PITCH_ALIGNMENT);
        bytes_=0;
        for (auto& footprint:footprints_) {
            bytes_=align(bytes_,D3D12_TEXTURE_DATA_PLACEMENT_ALIGNMENT);
            footprint.Offset=bytes_;
            footprint.Footprint.Format=format_;
            footprint.Footprint.Width=width_;
            footprint.Footprint.Height=ROWS;
            footprint.Footprint.Depth=1;
            footprint.Footprint.RowPitch=static_cast<uint32_t>(row_pitch);
            bytes_+=row_pitch*ROWS;
        }
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_READBACK;
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC desc{};
        desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width=bytes_;desc.Height=desc.DepthOrArraySize=desc.MipLevels=1;
        desc.SampleDesc.Count=1;
        desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        return SUCCEEDED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
                         D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&buffer_)));
    }
    static uint8_t half_byte(uint16_t h) {
        const int e=(h>>10)&31;const int m=h&1023;
        if (e==31) return 255;
        float f=e ? std::ldexp(1.f+m/1024.f,e-15) : std::ldexp(float(m)/1024.f,-14);
        return static_cast<uint8_t>((std::clamp)(f*255.f,0.f,255.f));
    }
    std::array<uint8_t,3> pixel(const uint8_t* p) const {
        if (bpp_==8) {
            uint16_t rgb[3]{};
            std::memcpy(rgb,p,sizeof(rgb));
            return {half_byte(rgb[0]),half_byte(rgb[1]),half_byte(rgb[2])};
        }
        if (format_==DXGI_FORMAT_R10G10B10A2_UNORM || format_==DXGI_FORMAT_R10G10B10A2_TYPELESS) {
            uint32_t packed{};
            std::memcpy(&packed,p,sizeof(packed));
            return {uint8_t(((packed)&1023u)*255u/1023u),
                    uint8_t(((packed>>10)&1023u)*255u/1023u),
                    uint8_t(((packed>>20)&1023u)*255u/1023u)};
        }
        const bool bgra=format_==DXGI_FORMAT_B8G8R8A8_UNORM ||
                        format_==DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
                        format_==DXGI_FORMAT_B8G8R8A8_TYPELESS;
        return bgra?std::array<uint8_t,3>{p[2],p[1],p[0]}:
                    std::array<uint8_t,3>{p[0],p[1],p[2]};
    }
};
} // namespace uevr::quadview::diagnostics

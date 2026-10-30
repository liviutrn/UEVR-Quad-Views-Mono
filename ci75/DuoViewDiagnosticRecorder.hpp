#pragma once
// CI75 targeted native-pixel, lossless numerical sequence capture.
// No compression, allocation, mapping or fence wait in the XR copy callback.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <d3d12.h>
#include <wincodec.h>
#include <wrl/client.h>
#include <objidl.h>
#include <array>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <thread>
#include "DuoViewCaptureArchive.hpp"
#pragma comment(lib,"windowscodecs.lib")
#pragma comment(lib,"ole32.lib")
#pragma comment(lib,"uuid.lib")

namespace uevr::duoview::capture75 {
using Microsoft::WRL::ComPtr;
constexpr unsigned NativeCrop=192,DepthCrop=192,SmallCrop=128,MotionCrop=96;
constexpr unsigned MaxFrames=96,MinFrames=16;
constexpr uint64_t ReadbackBudget=256ull*1024ull*1024ull;
inline constexpr const char* BuildCommit="@BUILD_COMMIT@";
struct Rect {UINT x{},y{},width{},height{};};
struct Source {
    std::string name;
    ComPtr<ID3D12Resource> resource;
    D3D12_RESOURCE_STATES state{D3D12_RESOURCE_STATE_RENDER_TARGET};
    Rect active{};
    float u{.5f},v{.5f};
    unsigned extent{NativeCrop};
    bool required{},full{};
};
struct Plane {
    Source input;
    ComPtr<ID3D12Resource> readback;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    D3D12_BOX box{};
    DXGI_FORMAT format{DXGI_FORMAT_UNKNOWN};
    UINT width{},height{},resource_width{},resource_height{};
    UINT64 row_bytes{},capacity{};
    std::string omitted;
};
struct Frame {
    std::vector<Plane> planes;
    ComPtr<ID3D12Fence> fence;
    ComPtr<ID3D12Device> device;
    uint64_t packet{},time_ms{},qpc{},readback_bytes{};
    unsigned capture_index{};
    std::string metadata{"{}"};
    bool recorded{},accepted{};
};
inline bool format_supported(DXGI_FORMAT f) {
    switch(f) {
    case DXGI_FORMAT_R8G8B8A8_TYPELESS:case DXGI_FORMAT_R8G8B8A8_UNORM:case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
    case DXGI_FORMAT_B8G8R8A8_TYPELESS:case DXGI_FORMAT_B8G8R8A8_UNORM:case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
    case DXGI_FORMAT_B8G8R8X8_UNORM:case DXGI_FORMAT_R10G10B10A2_UNORM:
    case DXGI_FORMAT_R32_TYPELESS:case DXGI_FORMAT_R32_FLOAT:case DXGI_FORMAT_D32_FLOAT:
    case DXGI_FORMAT_R16_TYPELESS:case DXGI_FORMAT_R16_FLOAT:case DXGI_FORMAT_R16_UNORM:case DXGI_FORMAT_D16_UNORM:
    case DXGI_FORMAT_R24G8_TYPELESS:case DXGI_FORMAT_D24_UNORM_S8_UINT:case DXGI_FORMAT_R24_UNORM_X8_TYPELESS:
    case DXGI_FORMAT_R32G8X24_TYPELESS:case DXGI_FORMAT_D32_FLOAT_S8X24_UINT:case DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS:
    case DXGI_FORMAT_R16G16_FLOAT:case DXGI_FORMAT_R32G32_FLOAT:case DXGI_FORMAT_R16G16_SNORM:return true;
    default:return false;
    }
}
inline bool encode_packed_png(IWICImagingFactory* factory,const Plane& p,std::vector<uint8_t>& result) {
    if(!factory||!p.readback||!p.row_bytes||!p.height||p.row_bytes>16*1024*1024)return false;
    const UINT png_width=UINT((p.row_bytes+3)/4),stride=png_width*4;
    if(uint64_t(stride)*p.height>ReadbackBudget)return false;
    std::vector<uint8_t> packed(size_t(stride)*p.height,0);
    void* mapped{};D3D12_RANGE range{0,SIZE_T(p.footprint.Offset+uint64_t(p.footprint.Footprint.RowPitch)*p.height)};
    if(FAILED(p.readback->Map(0,&range,&mapped))||!mapped)return false;
    for(UINT y=0;y<p.height;++y)
        std::memcpy(packed.data()+size_t(y)*stride,static_cast<const uint8_t*>(mapped)+p.footprint.Offset+
                    size_t(y)*p.footprint.Footprint.RowPitch,size_t(p.row_bytes));
    D3D12_RANGE write{0,0};p.readback->Unmap(0,&write);
    ComPtr<IStream> stream;ComPtr<IWICBitmapEncoder> encoder;
    ComPtr<IWICBitmapFrameEncode> frame;
    if(FAILED(CreateStreamOnHGlobal(nullptr,TRUE,&stream))||
       FAILED(factory->CreateEncoder(GUID_ContainerFormatPng,nullptr,&encoder))||
       FAILED(encoder->Initialize(stream.Get(),WICBitmapEncoderNoCache))||
       FAILED(encoder->CreateNewFrame(&frame,nullptr))||FAILED(frame->Initialize(nullptr))||
       FAILED(frame->SetSize(png_width,p.height)))return false;
    WICPixelFormatGUID pixel=GUID_WICPixelFormat32bppRGBA;
    if(FAILED(frame->SetPixelFormat(&pixel)))return false;
    // Preserve arbitrary bytes, including RGB beneath zero alpha. No
    // normalization, float conversion, tone mapping or premultiplication.
    if(pixel==GUID_WICPixelFormat32bppBGRA)
        for(size_t i=0;i<packed.size();i+=4)std::swap(packed[i],packed[i+2]);
    else if(pixel!=GUID_WICPixelFormat32bppRGBA)return false;
    if(FAILED(frame->WritePixels(p.height,stride,UINT(packed.size()),packed.data()))||
       FAILED(frame->Commit())||FAILED(encoder->Commit()))return false;
    STATSTG stat{};
    if(FAILED(stream->Stat(&stat,STATFLAG_NONAME))||!stat.cbSize.QuadPart||stat.cbSize.QuadPart>int64_t(ReadbackBudget))return false;
    HGLOBAL global{};if(FAILED(GetHGlobalFromStream(stream.Get(),&global)))return false;
    auto* bytes=static_cast<const uint8_t*>(GlobalLock(global));if(!bytes)return false;
    result.assign(bytes,bytes+size_t(stat.cbSize.QuadPart));GlobalUnlock(global);return true;
}
class Recorder:public std::enable_shared_from_this<Recorder> {
    const uint64_t id_,start_,arm_ms_,window_ms_;
    const unsigned max_frames_;
    mutable std::mutex mutex_;
    std::vector<std::shared_ptr<Frame>> frames_;
    std::atomic<unsigned> state_{0}; // 0 armed/capture,1 encode/retire,2 ready,3 failed
    uint64_t reserved_bytes_{},last_packet_{};
    bool window_complete_{},memory_limited_{};
    unsigned issued_{},rejected_{},encoded_{};
    std::string status_detail_,output_;
    inline static std::atomic<bool> retirement_unproven_{false};
    static void quarantine(const std::shared_ptr<Frame>& f) {
        // One ambiguous submission disables subsequent sessions: never grow
        // an unbounded retirement leak and never free referenced GPU memory.
        retirement_unproven_=true;
        static auto* retained=new std::vector<std::shared_ptr<Frame>>;
        static auto* guard=new std::mutex;
        std::lock_guard lock(*guard);retained->push_back(f);
    }
    static bool configure(ID3D12Device* dev,Plane& p) {
        if(!dev||!p.input.resource)return false;
        const auto d=p.input.resource->GetDesc();
        if(d.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D||d.SampleDesc.Count!=1||d.MipLevels!=1||
           d.DepthOrArraySize!=1||d.Width>16384||!format_supported(d.Format)||
           (d.Flags&D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL))return false;
        // The source depth is the selected owned NGX copy, not a live DSV.
        auto active=p.input.active;
        if(!active.width||!active.height)active={0,0,UINT(d.Width),d.Height};
        if(uint64_t(active.x)+active.width>d.Width||uint64_t(active.y)+active.height>d.Height||
           !std::isfinite(p.input.u)||!std::isfinite(p.input.v))return false;
        p.width=p.input.full?active.width:std::min(p.input.extent,active.width);
        p.height=p.input.full?active.height:std::min(p.input.extent,active.height);
        if(!p.width||!p.height)return false;
        const auto origin=[](UINT base,UINT size,UINT extent,float uv) {
            const int64_t center=int64_t(std::floor(std::clamp(uv,0.f,1.f)*float(size)));
            return base+UINT(std::clamp(center-int64_t(extent/2),int64_t(0),int64_t(size-extent)));
        };
        const UINT x=p.input.full?active.x:origin(active.x,active.width,p.width,p.input.u);
        const UINT y=p.input.full?active.y:origin(active.y,active.height,p.height,p.input.v);
        p.box={x,y,0,x+p.width,y+p.height,1};p.format=d.Format;
        p.resource_width=UINT(d.Width);p.resource_height=d.Height;
        auto crop=d;crop.Width=p.width;crop.Height=p.height;crop.Flags=D3D12_RESOURCE_FLAG_NONE;
        UINT rows{};UINT64 bytes{};
        dev->GetCopyableFootprints(&crop,0,1,0,&p.footprint,&rows,&p.row_bytes,&bytes);
        if(rows!=p.height||!p.row_bytes||p.row_bytes>uint64_t(p.width)*8||bytes>16ull*1024*1024)return false;
        return !p.readback||bytes<=p.capacity;
    }
    static bool allocate(ID3D12Device* dev,Plane& p) {
        if(p.input.resource) {
            if(!configure(dev,p))return false;
            p.capacity=p.footprint.Offset+uint64_t(p.footprint.Footprint.RowPitch)*p.height;
        } else {
            const uint64_t pitch=(uint64_t(p.input.extent)*8+255)&~uint64_t(255);
            p.capacity=pitch*p.input.extent;
        }
        if(!p.capacity||p.capacity>16ull*1024*1024)return false;
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_READBACK;
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width=p.capacity;desc.Height=1;desc.DepthOrArraySize=desc.MipLevels=1;
        desc.SampleDesc.Count=1;desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        return SUCCEEDED(dev->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&p.readback)));
    }
    static void copy(ID3D12GraphicsCommandList* cmd,Plane& p) {
        D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition={p.input.resource.Get(),0,p.input.state,D3D12_RESOURCE_STATE_COPY_SOURCE};
        cmd->ResourceBarrier(1,&b);
        D3D12_TEXTURE_COPY_LOCATION src{},dst{};
        src.pResource=p.input.resource.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.pResource=p.readback.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=p.footprint;
        cmd->CopyTextureRegion(&dst,0,0,0,&src,&p.box);
        std::swap(b.Transition.StateBefore,b.Transition.StateAfter);cmd->ResourceBarrier(1,&b);
    }
    std::string manifest(const std::vector<std::string>& frames,unsigned part,unsigned parts,unsigned total,unsigned dropped)const {
        LARGE_INTEGER frequency{};QueryPerformanceFrequency(&frequency);
        std::ostringstream out;out<<"{\"schema\":\"duoview-diagnostic-sequence-2\",\"build_commit\":"<<quote(BuildCommit)
            <<",\"capture_id\":"<<id_<<",\"session_start_ms\":"<<start_
            <<",\"part_index\":"<<part<<",\"part_count\":"<<parts<<",\"total_encoded_frames\":"<<total<<",\"max_zip_bytes\":"<<MaxZipBytes
            <<",\"max_readback_bytes\":"<<ReadbackBudget<<",\"readback_bytes\":"<<reserved_bytes_
            <<",\"minimum_analyzable_frames\":"<<MinFrames<<",\"encoded_frames\":"<<frames.size()
            <<",\"frames_recorded\":"<<frames_.size()<<",\"rejected_frames\":"<<rejected_
            <<",\"dropped_frames\":"<<dropped<<",\"truncated_by_size\":false"
            <<",\"depth_provenance_authenticated\":false,\"native_pixel_crops\":true,\"lossless\":true"
            <<",\"qpc_frequency\":"<<frequency.QuadPart
            <<",\"diagnostic_scope\":\"local ROI temporal/geometry diagnosis; no full-stereo ground truth or SteamVR smoothing capture\""
            <<",\"capture_complete\":"<<(window_complete_&&!memory_limited_&&!dropped&&!rejected_&&total>=MinFrames?"true":"false")
            <<",\"memory_limited\":"<<(memory_limited_?"true":"false")
            <<",\"requested_window_ms\":"<<window_ms_
            <<",\"sufficient_sequence\":"<<(total>=MinFrames?"true":"false")<<",\"frames\":[";
        for(size_t k=0;k<frames.size();++k){if(k)out<<",";out<<frames[k];}
        return out.str()+"]}";
    }
    bool retire(const std::shared_ptr<Frame>& f) {
        if(!f->recorded)return true;
        if(!f->fence)return false;
        const auto started=GetTickCount64();
        while(f->fence->GetCompletedValue()<1) {
            if(f->fence->GetCompletedValue()==UINT64_MAX||FAILED(f->device->GetDeviceRemovedReason()))return false;
            if(GetTickCount64()-started>10000) {
                std::lock_guard lock(mutex_);status_detail_="Waiting for GPU retirement; new capture blocked";
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        return f->fence->GetCompletedValue()!=UINT64_MAX;
    }
    void encode() {
        // Retire EVERY submitted copy, including rejected final output. Only
        // then may this session release readbacks or source texture references.
        for(const auto& f:frames_)if(!retire(f)) {
            std::lock_guard lock(mutex_);status_detail_="GPU removed/retirement failed";state_=3;return;
        }
        const HRESULT initialized=CoInitializeEx(nullptr,COINIT_MULTITHREADED);
        if(FAILED(initialized)){std::lock_guard lock(mutex_);status_detail_="COM initialization failed";state_=3;return;}
        struct ComScope {~ComScope(){CoUninitialize();}} com_scope;
        ComPtr<IWICImagingFactory> factory;
        if(FAILED(CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&factory))))
            throw std::runtime_error("PNG encoder unavailable");
        auto dir=std::filesystem::temp_directory_path()/"UEVR_DuoViewDiagnostics";
        std::filesystem::create_directories(dir);
        const std::string stem="diagnostic_"+std::to_string(GetCurrentProcessId())+"_"+std::to_string(start_)+"_"+std::to_string(id_);
        struct Encoded {std::vector<Payload> payloads;std::string json;};
        std::vector<Encoded> encoded;
        unsigned dropped=0;
        for(const auto& f:frames_) {
            if(!f->accepted){++dropped;continue;}
            Encoded data;std::ostringstream entry;
            entry<<"{\"index\":"<<f->capture_index<<",\"packet\":"<<f->packet<<",\"time_ms\":"<<f->time_ms
                <<",\"qpc\":"<<f->qpc<<",\"metadata\":"<<f->metadata<<",\"planes\":[";
            bool first=true,good=true;
            std::vector<std::pair<std::string,std::string>> omitted;
            for(auto& p:f->planes) {
                if(!p.omitted.empty()){omitted.emplace_back(p.input.name,p.omitted);continue;}
                Payload payload{"frames/f"+std::to_string(f->capture_index)+"_"+p.input.name+".png",{}};
                if(!encode_packed_png(factory.Get(),p,payload.bytes)) {
                    omitted.emplace_back(p.input.name,"lossless encoder failure");
                    if(p.input.required){good=false;break;}continue;
                }
                if(!first)entry<<",";first=false;
                entry<<"{\"name\":"<<quote(p.input.name)<<",\"file\":"<<quote(payload.name)
                    <<",\"encoding\":\"png-packed-bytes\",\"width\":"<<p.width<<",\"height\":"<<p.height
                    <<",\"row_bytes\":"<<p.row_bytes<<",\"resource_id\":"<<quote(std::to_string(reinterpret_cast<uintptr_t>(p.input.resource.Get())))<<",\"format\":"<<int(p.format)
                    <<",\"footprint_format\":"<<int(p.footprint.Footprint.Format)
                    <<",\"resource_size\":["<<p.resource_width<<","<<p.resource_height<<"]"
                    <<",\"required\":"<<(p.input.required?"true":"false")
                    <<",\"box\":["<<p.box.left<<","<<p.box.top<<","<<p.box.right<<","<<p.box.bottom<<"]}";
                data.payloads.push_back(std::move(payload));
                p.readback.Reset();p.input.resource.Reset();
            }
            if(!good){++dropped;continue;}
            entry<<"],\"omitted\":[";first=true;
            for(const auto& item:omitted) {
                if(!first)entry<<",";first=false;
                entry<<"{\"name\":"<<quote(item.first)<<",\"reason\":"<<quote(item.second)<<"}";
            }
            entry<<"]}";data.json=entry.str();encoded.push_back(std::move(data));
        }
        // Partition only AFTER recording and lossless encoding. Nothing is
        // discarded to meet an upload cap, and frames never span ZIP parts.
        std::vector<std::pair<size_t,size_t>> groups;
        size_t begin=0;uint64_t part_size=22,manifest_size=65536;
        for(size_t i=0;i<encoded.size();++i) {
            uint64_t frame_size=encoded[i].json.size()+1;
            for(const auto& p:encoded[i].payloads)frame_size+=76+2*p.name.size()+p.bytes.size();
            if(frame_size+65536+22>MaxZipBytes)throw std::runtime_error("One complete frame exceeds upload part limit");
            if(part_size+manifest_size+frame_size>MaxZipBytes&&i>begin) {
                groups.emplace_back(begin,i);begin=i;part_size=22;manifest_size=65536;
            }
            part_size+=frame_size;
        }
        if(begin<encoded.size())groups.emplace_back(begin,encoded.size());
        std::vector<std::string> part_names;
        for(size_t part=0;part<groups.size();++part) {
            std::ostringstream filename;filename<<stem<<"_part"<<std::setfill('0')<<std::setw(2)<<part+1
                <<"of"<<std::setw(2)<<groups.size()<<".zip";
            const auto path=dir/filename.str();auto partial=path;partial+=".partial";
            Zip zip(partial);if(!zip.ok())throw std::runtime_error("Cannot create diagnostic ZIP part");
            std::vector<std::string> json_frames;
            for(size_t i=groups[part].first;i<groups[part].second;++i) {
                for(const auto& p:encoded[i].payloads)if(!zip.add(p.name,p.bytes))throw std::runtime_error("ZIP plane write failed");
                json_frames.push_back(encoded[i].json);
            }
            const auto json=manifest(json_frames,unsigned(part+1),unsigned(groups.size()),unsigned(encoded.size()),dropped);
            if(!zip.add("manifest.json",std::vector<uint8_t>(json.begin(),json.end()))||!zip.finish()||
               std::filesystem::file_size(partial)>MaxZipBytes)throw std::runtime_error("ZIP part finalization/size failed");
            std::filesystem::rename(partial,path);part_names.push_back(filename.str());
        }
        if(encoded.empty())throw std::runtime_error("No usable frames: verify live stereo and selected NGX depth pair");
        const auto index=dir/(stem+"_index.json");
        std::ofstream index_out(index);index_out<<"{\"schema\":\"duoview-sequence-parts-1\",\"capture_id\":"<<id_
            <<",\"session_start_ms\":"<<start_<<",\"total_frames\":"<<encoded.size()<<",\"parts\":[";
        for(size_t i=0;i<part_names.size();++i){if(i)index_out<<",";index_out<<quote(part_names[i]);}
        index_out<<"]}";index_out.close();if(!index_out)throw std::runtime_error("Part index write failed");
        std::lock_guard lock(mutex_);encoded_=unsigned(encoded.size());output_=index.string();
        const bool sufficient=encoded_>=MinFrames&&window_complete_&&!memory_limited_&&!dropped&&!rejected_;
        status_detail_=sufficient?"READY: upload ALL numbered ZIP parts + index; no size truncation":"INCOMPLETE: usable data saved, inspect dropped frames/duration in manifest";
        state_=sufficient?2u:3u;frames_.clear();reserved_bytes_=0;

    }
public:
    explicit Recorder(uint64_t id,uint64_t arm_ms=3000,unsigned max_frames=MaxFrames,uint64_t window_ms=2000)
        :id_(id),start_(GetTickCount64()),arm_ms_(arm_ms),window_ms_(window_ms),max_frames_(std::min(max_frames,MaxFrames)){}
    bool wants_guides()const{return state_.load()==0&&GetTickCount64()-start_<arm_ms_+window_ms_;}
    bool active()const{return state_.load()<=1||retirement_unproven_.load();}
    std::shared_ptr<Frame> stage(ID3D12Device* dev,std::vector<Source> sources,uint64_t packet=0) {
        const auto elapsed=GetTickCount64()-start_;
        if(!dev||state_.load()!=0||retirement_unproven_||elapsed<arm_ms_||elapsed>=arm_ms_+window_ms_)return {};
        {std::lock_guard lock(mutex_);if(issued_>=max_frames_||(packet&&packet==last_packet_))return {};}
        auto f=std::make_shared<Frame>();f->device=dev;
        for(auto& s:sources) {
            if(s.full&&issued_%16!=0)continue; // complete active depth keyframes
            Plane p;p.input=std::move(s);
            if(!p.input.resource&&p.input.name!="xr_left"&&p.input.name!="xr_right"&&
               p.input.name!="synthetic_right"&&p.input.name!="synthetic_left") {
                p.omitted="resource unavailable on selected evaluation";
                if(p.input.required){std::lock_guard lock(mutex_);++rejected_;return {};}
            } else if(!allocate(dev,p)) {
                p.omitted="unsupported format/active rectangle/allocation";
                if(p.input.required){std::lock_guard lock(mutex_);++rejected_;return {};}
            }
            // Optional full-depth keyframes must not consume memory reserved
            // for the rest of the consecutive core sequence (<=2 MiB/frame).
            if(p.readback&&p.input.full&&reserved_bytes_+f->readback_bytes+p.capacity+
                    uint64_t(max_frames_-issued_)*2*1024*1024>ReadbackBudget) {
                p.readback.Reset();p.omitted="optional keyframe skipped to reserve complete core sequence";
            }
            if(p.readback)f->readback_bytes+=p.capacity;
            f->planes.push_back(std::move(p));
        }
        if(FAILED(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&f->fence))))return {};
        std::lock_guard lock(mutex_);
        if(reserved_bytes_+f->readback_bytes>ReadbackBudget){status_detail_="Readback budget reached: capture incomplete";memory_limited_=true;issued_=max_frames_;return {};}
        f->capture_index=issued_++;f->packet=packet;last_packet_=packet;reserved_bytes_+=f->readback_bytes;return f;
    }
    bool record(ID3D12GraphicsCommandList* cmd,const std::shared_ptr<Frame>& f,ID3D12Resource* xr,
                ID3D12Resource* synthetic_right=nullptr,ID3D12Resource* synthetic_left=nullptr) {
        if(!cmd||!f||!xr||state_.load()!=0)return false;
        const auto d=xr->GetDesc();if(d.Width%2||d.Width>32768)return false;
        for(auto& p:f->planes) {
            if(!p.omitted.empty())continue;
            if(p.input.name=="xr_left"||p.input.name=="xr_right") {
                p.input.resource=xr;
                p.input.active={p.input.name=="xr_right"?UINT(d.Width/2):0u,0,UINT(d.Width/2),d.Height};
            } else if(p.input.name=="synthetic_right")p.input.resource=synthetic_right;
            else if(p.input.name=="synthetic_left")p.input.resource=synthetic_left;
            if(!configure(f->device.Get(),p)) {
                p.omitted="resource/format/crop unavailable at recorded output";
                if(p.input.required)return false;
            }
        }
        // All fallible validation finishes BEFORE the first copy is recorded.
        f->recorded=true;
        for(auto& p:f->planes)if(p.omitted.empty())copy(cmd,p);
        return true;
    }
    void submit(const std::shared_ptr<Frame>& f,ID3D12CommandQueue* queue,bool commands_submitted,
                bool accepted,uint64_t packet,std::string metadata) {
        if(!f)return;
        if(f->recorded&&(!commands_submitted||!queue||FAILED(queue->Signal(f->fence.Get(),1)))) {
            quarantine(f);std::lock_guard lock(mutex_);status_detail_="Submission retirement unproven; further capture disabled";state_=3;return;
        }
        f->accepted=f->recorded&&commands_submitted&&accepted;f->packet=packet;
        f->time_ms=GetTickCount64()-start_-arm_ms_;
        LARGE_INTEGER qpc{};QueryPerformanceCounter(&qpc);f->qpc=uint64_t(qpc.QuadPart);f->metadata=std::move(metadata);
        std::lock_guard lock(mutex_);frames_.push_back(f);if(!f->accepted)++rejected_;
    }
    void finish_if_ready() {
        if(state_.load()!=0)return;
        bool complete=GetTickCount64()-start_>=arm_ms_+window_ms_;
        window_complete_=complete;
        {std::lock_guard lock(mutex_);complete=complete||issued_>=max_frames_;}
        if(!complete)return;
        unsigned expected=0;if(!state_.compare_exchange_strong(expected,1))return;
        try {auto self=shared_from_this();std::thread([self]{try {self->encode();}
            catch(const std::exception& e){std::lock_guard lock(self->mutex_);self->status_detail_=e.what();self->state_=3;}
            catch(...){std::lock_guard lock(self->mutex_);self->status_detail_="Unexpected recorder failure";self->state_=3;}}).detach();}
        catch(...){for(const auto& f:frames_)if(f->recorded)quarantine(f);
            std::lock_guard lock(mutex_);status_detail_="Encoder thread creation failed";state_=3;}
    }
    std::string status()const {
        std::lock_guard lock(mutex_);std::ostringstream out;
        out<<"CI75 "<<(state_==0?(GetTickCount64()-start_<arm_ms_?"3s COUNTDOWN":"RECORDING"):state_==1?"ENCODING":state_==2?"READY":"FAILED")
           <<" frames="<<frames_.size()<<" saved="<<encoded_<<" rejected="<<rejected_;
        if(!status_detail_.empty())out<<" | "<<status_detail_;
        if(!output_.empty())out<<" | "<<output_;return out.str();
    }
};
}

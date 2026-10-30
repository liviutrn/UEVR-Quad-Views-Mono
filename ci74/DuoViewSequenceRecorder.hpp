#pragma once
// CI74 - diagnostic-only, bounded, short-sequence stereo recorder.
// Does not access the HMD compositor or modify pixel ownership.
// CPU JPEG/ZIP encoding is done off the XR render thread after GPU queue fences.
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <wincodec.h>
#include <ocidl.h>
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "windowscodecs.lib")
#pragma comment(lib, "uuid.lib")
#include <objidl.h>
#include <d3d12.h>
#include <wrl/client.h>
#include <filesystem>
#include <fstream>
#include <vector>
#include <array>
#include <mutex>
#include <memory>
#include <thread>
#include <atomic>
#include <sstream>
#include <iomanip>
#include <string>
#include <cstdint>
#include <cstring>
#include <algorithm>
#include <cmath>
#include <utility>
#include <limits>

namespace uevr::duoview::sequence {
using Microsoft::WRL::ComPtr;
constexpr unsigned OutputCrop=512, SourceCrop=256;
constexpr size_t MaxFrames=64;
constexpr uint64_t CaptureMillis=2000, ArmDelayMillis=3000, MaxZipBytes=18ull*1024ull*1024ull;
struct Patch {
    ComPtr<ID3D12Resource> readback;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    D3D12_BOX box{};
    DXGI_FORMAT format{DXGI_FORMAT_UNKNOWN};
    unsigned width{},height{};
    bool output{};
};
struct Frame {
    std::array<Patch,4> patches;
    ComPtr<ID3D12Fence> fence;
    uint64_t frame_serial{}, captured_ms{};
    std::string metadata;
    bool recorded{}, accepted{};
};
inline bool supported(DXGI_FORMAT f) {
    switch(f) {
    case DXGI_FORMAT_R8G8B8A8_UNORM:case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
    case DXGI_FORMAT_R8G8B8A8_TYPELESS:
    case DXGI_FORMAT_B8G8R8A8_UNORM:case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
    case DXGI_FORMAT_B8G8R8A8_TYPELESS:case DXGI_FORMAT_B8G8R8X8_UNORM:
    case DXGI_FORMAT_R10G10B10A2_UNORM:return true;
    default:return false;
    }
}
inline std::string quote(const std::string& s) {
    std::string result="\"";
    for(unsigned char c:s) {
        if(c=='"'||c=='\\'){result+='\\';result+=char(c);}
        else if(c=='\n')result+="\\n";
        else if(c=='\r')result+="\\r";
        else if(c<32){result+='?';}
        else result+=char(c);
    }
    return result+'"';
}
inline uint32_t crc32(const uint8_t* p,size_t n) {
    uint32_t c=0xffffffffu;
    for(size_t i=0;i<n;++i){c^=p[i];for(int j=0;j<8;++j)c=(c>>1)^((c&1u)?0xedb88320u:0u);}
    return ~c;
}
class Zip {
    struct Entry { std::string name; uint32_t crc{},size{},offset{}; };
    std::ofstream out_;std::vector<Entry> entries_;
    uint64_t position_{};
    void u16(uint16_t n){char b[]={char(n),char(n>>8)};out_.write(b,2);position_+=2;}
    void u32(uint32_t n){u16(uint16_t(n));u16(uint16_t(n>>16));}
    void bytes(const void* p,size_t n){out_.write(static_cast<const char*>(p),static_cast<std::streamsize>(n));position_+=n;}
public:
    explicit Zip(const std::filesystem::path& file):out_(file,std::ios::binary){}
    bool ok() const{return bool(out_);}
    uint64_t bytes_written() const{return position_;}
    // Stored ZIP, JPEG already compressed; compatible with Windows Explorer and Python.
    bool add(const std::string& name,const std::vector<uint8_t>& payload) {
        if(!ok()||entries_.size()>=65534||name.size()>65535||payload.size()>UINT32_MAX||position_>UINT32_MAX)return false;
        Entry e{name,crc32(payload.data(),payload.size()),uint32_t(payload.size()),uint32_t(position_)};
        u32(0x04034b50);u16(20);u16(0);u16(0);u16(0);u16(0);
        u32(e.crc);u32(e.size);u32(e.size);u16(uint16_t(name.size()));u16(0);
        bytes(name.data(),name.size());if(!payload.empty())bytes(payload.data(),payload.size());
        entries_.push_back(e);return ok();
    }
    bool finish() {
        if(!ok()||position_>UINT32_MAX)return false;
        uint32_t offset=uint32_t(position_);
        for(const auto& e:entries_) {
            u32(0x02014b50);u16(20);u16(20);u16(0);u16(0);u16(0);u16(0);
            u32(e.crc);u32(e.size);u32(e.size);u16(uint16_t(e.name.size()));
            u16(0);u16(0);u16(0);u16(0);u32(0);u32(e.offset);bytes(e.name.data(),e.name.size());
        }
        if(position_>UINT32_MAX)return false;
        u32(0x06054b50);u16(0);u16(0);u16(uint16_t(entries_.size()));
        u16(uint16_t(entries_.size()));u32(uint32_t(position_-offset));u32(offset);u16(0);
        out_.flush();return ok();
    }
};
inline bool jpeg(IWICImagingFactory* factory,const Patch& p,std::vector<uint8_t>& result) {
    if(!factory||!p.readback||!supported(p.format))return false;
    const size_t stride=size_t(p.width)*3;
    std::vector<uint8_t> pixels(stride*p.height);
    void* ptr{};D3D12_RANGE read{0,SIZE_T(p.footprint.Footprint.RowPitch)*p.height};
    if(FAILED(p.readback->Map(0,&read,&ptr))||!ptr)return false;
    const auto* mem=static_cast<const uint8_t*>(ptr);
    const bool bgra=p.format==DXGI_FORMAT_B8G8R8A8_UNORM||p.format==DXGI_FORMAT_B8G8R8A8_UNORM_SRGB||
        p.format==DXGI_FORMAT_B8G8R8A8_TYPELESS||p.format==DXGI_FORMAT_B8G8R8X8_UNORM;
    const bool ten=p.format==DXGI_FORMAT_R10G10B10A2_UNORM;
    for(unsigned y=0;y<p.height;++y)for(unsigned x=0;x<p.width;++x){
        const uint8_t* b=mem+size_t(y)*p.footprint.Footprint.RowPitch+size_t(x)*4;
        uint8_t* q=pixels.data()+size_t(y)*stride+x*3;
        if(ten){uint32_t packed{};std::memcpy(&packed,b,4);
            q[2]=uint8_t(((packed>>0)&1023u)*255u/1023u);
            q[1]=uint8_t(((packed>>10)&1023u)*255u/1023u);
            q[0]=uint8_t(((packed>>20)&1023u)*255u/1023u);
        } else if(bgra){q[0]=b[0];q[1]=b[1];q[2]=b[2];}
        else {q[0]=b[2];q[1]=b[1];q[2]=b[0];}
    }
    D3D12_RANGE write{0,0};p.readback->Unmap(0,&write);
    ComPtr<IStream> stream;
    if(FAILED(CreateStreamOnHGlobal(nullptr,TRUE,&stream)))return false;
    ComPtr<IWICBitmapEncoder> enc;
    if(FAILED(factory->CreateEncoder(GUID_ContainerFormatJpeg,nullptr,&enc))||
       FAILED(enc->Initialize(stream.Get(),WICBitmapEncoderNoCache)))return false;
    ComPtr<IWICBitmapFrameEncode> frame;ComPtr<IPropertyBag2> bag;
    if(FAILED(enc->CreateNewFrame(&frame,&bag)))return false;
    if(bag){PROPBAG2 prop{};prop.pstrName=const_cast<LPOLESTR>(L"ImageQuality");
        VARIANT val{};val.vt=VT_R4;val.fltVal=0.88f;bag->Write(1,&prop,&val);}
    WICPixelFormatGUID fmt=GUID_WICPixelFormat24bppBGR;
    if(FAILED(frame->Initialize(bag.Get()))||FAILED(frame->SetSize(p.width,p.height))||
       FAILED(frame->SetPixelFormat(&fmt))||fmt!=GUID_WICPixelFormat24bppBGR||
       FAILED(frame->WritePixels(p.height,UINT(stride),UINT(pixels.size()),pixels.data()))||
       FAILED(frame->Commit())||FAILED(enc->Commit()))return false;
    STATSTG st{};if(FAILED(stream->Stat(&st,STATFLAG_NONAME))||st.cbSize.QuadPart<=0||
                    st.cbSize.QuadPart>int64_t(2*1024*1024))return false;
    HGLOBAL global{};if(FAILED(GetHGlobalFromStream(stream.Get(),&global)))return false;
    void* data=GlobalLock(global);if(!data)return false;
    result.assign(static_cast<const uint8_t*>(data),static_cast<const uint8_t*>(data)+size_t(st.cbSize.QuadPart));
    GlobalUnlock(global);return true;
}
class Recorder:public std::enable_shared_from_this<Recorder> {
    const uint64_t id_,start_ms_;
    mutable std::mutex mutex_;
    std::vector<std::shared_ptr<Frame>> frames_;
    std::atomic<unsigned> state_{0}; // 0 capture,1 encoding,2 done,3 failed
    unsigned rejected_{},dropped_{},encoded_{};
    std::string error_,output_;
    static void quarantine(std::shared_ptr<Frame> frame) {
        static auto* mutex=new std::mutex;
        static auto* leaked=new std::vector<std::shared_ptr<Frame>>;
        std::lock_guard lock(*mutex);leaked->push_back(std::move(frame));
    }
    static bool allocate(ID3D12Device* dev,Patch& p,unsigned dim,bool output){
        D3D12_HEAP_PROPERTIES hp{};hp.Type=D3D12_HEAP_TYPE_READBACK;hp.CreationNodeMask=hp.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width=uint64_t(dim)*dim*4;desc.Height=1;desc.DepthOrArraySize=1;desc.MipLevels=1;
        desc.SampleDesc.Count=1;desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if(FAILED(dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,
                  D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&p.readback))))return false;
        p.width=p.height=dim;p.output=output;
        p.footprint.Offset=0;p.footprint.Footprint.Width=dim;
        p.footprint.Footprint.Height=dim;p.footprint.Footprint.Depth=1;
        p.footprint.Footprint.RowPitch=dim*4; // 256-aligned for 256/512 crop
        return true;
    }
    static bool copy(ID3D12GraphicsCommandList* cmd,Patch& p,ID3D12Resource* src,
                     unsigned cx,unsigned cy){
        if(!cmd||!src||!p.readback)return false;
        auto d=src->GetDesc();
        if(d.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D||d.SampleDesc.Count!=1||
           d.DepthOrArraySize!=1||!supported(d.Format)||cx<p.width/2||cy<p.height/2||
           uint64_t(cx)+p.width/2>d.Width||uint64_t(cy)+p.height/2>d.Height)return false;
        p.format=d.Format;p.footprint.Footprint.Format=d.Format;
        const unsigned x=cx-p.width/2,y=cy-p.height/2;
        p.box={x,y,0,x+p.width,y+p.height,1};
        D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition={src,0,D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE};
        cmd->ResourceBarrier(1,&barrier);
        D3D12_TEXTURE_COPY_LOCATION from{},to{};
        from.pResource=src;from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;from.SubresourceIndex=0;
        to.pResource=p.readback.Get();to.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;to.PlacedFootprint=p.footprint;
        cmd->CopyTextureRegion(&to,0,0,0,&from,&p.box);
        std::swap(barrier.Transition.StateBefore,barrier.Transition.StateAfter);
        cmd->ResourceBarrier(1,&barrier);return true;
    }
    void encode() {
        HRESULT init=CoInitializeEx(nullptr,COINIT_MULTITHREADED);
        const bool com=SUCCEEDED(init);
        ComPtr<IWICImagingFactory> factory;
        if(!com||FAILED(CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&factory)))){
            std::lock_guard lock(mutex_);error_="WIC COM initialization failed";state_=3;if(com)CoUninitialize();return;
        }
        std::filesystem::path target;
        try {auto dir=std::filesystem::temp_directory_path()/"UEVR_DuoViewSequences";
             std::filesystem::create_directories(dir);
             target=dir/("sequence_"+std::to_string(id_)+"_"+std::to_string(GetCurrentProcessId())+"_"+
                         std::to_string(start_ms_)+".zip");}
        catch(...){std::lock_guard lock(mutex_);error_="Cannot create output path";state_=3;CoUninitialize();return;}
        Zip zip(target);
        if(!zip.ok()){std::lock_guard lock(mutex_);error_="Cannot create ZIP";state_=3;CoUninitialize();return;}
        unsigned encoded=0;bool limit=false;std::ostringstream metadata;
        metadata<<"{\"schema\":\"duoview-sequence-1\",\"capture_id\":"<<id_
                <<",\"start_ms\":"<<start_ms_<<",\"duration_requested_ms\":"<<CaptureMillis
                <<",\"arming_delay_ms\":"<<ArmDelayMillis<<",\"max_zip_bytes\":"<<MaxZipBytes
                <<",\"native_depth_captured\":false,\"source_depth_eye_frame_authenticated\":false,\"frames\":[";
        const char* names[]={"xr_left","xr_right","source_left","source_right"};
        for(const auto& f:frames_) {
            if(!f||!f->accepted)continue;
            if(!f->fence||f->fence->GetCompletedValue()!=1u) {
                if(f->fence){HANDLE e=CreateEventW(nullptr,FALSE,FALSE,nullptr);
                    if(e){if(SUCCEEDED(f->fence->SetEventOnCompletion(1,e)))WaitForSingleObject(e,10000);CloseHandle(e);}}
            }
            if(!f->fence||f->fence->GetCompletedValue()!=1u){++dropped_;continue;}
            std::array<std::vector<uint8_t>,4> jpegs;
            bool good=true;uint64_t total=0;
            for(size_t k=0;k<4;++k){if(!jpeg(factory.Get(),f->patches[k],jpegs[k])){good=false;break;}
                total+=jpegs[k].size()+150;}
            if(!good){++dropped_;continue;}
            // Reserve 96 KiB for JSON and ZIP central directory. Stop BEFORE an incomplete frame.
            if(zip.bytes_written()+total+98304>MaxZipBytes){limit=true;break;}
            for(size_t k=0;k<4;++k){std::string file="frames/f"+std::to_string(encoded)+"_"+names[k]+".jpg";
                if(!zip.add(file,jpegs[k])){good=false;break;}}
            if(!good){++dropped_;break;}
            if(encoded)metadata<<",";
            metadata<<"{\"index\":"<<encoded<<",\"packet\":"<<f->frame_serial
                    <<",\"time_ms\":"<<f->captured_ms<<",\"metadata\":"<<quote(f->metadata)<<",\"patches\":[";
            for(size_t k=0;k<4;++k){const auto& p=f->patches[k];if(k)metadata<<",";
                metadata<<"{\"name\":"<<quote(names[k])<<",\"format\":"<<int(p.format)
                        <<",\"box\":["<<p.box.left<<","<<p.box.top<<","<<p.box.right<<","<<p.box.bottom<<"]}";}
            metadata<<"]}";
            ++encoded;
        }
        metadata<<"],\"encoded_frames\":"<<encoded<<",\"frames_recorded\":"<<frames_.size()
                <<",\"skipped_or_failed\":"<<dropped_<<",\"rejected\":"<<rejected_
                <<",\"truncated_by_size\":"<<(limit?"true":"false")
                <<",\"encoding\":\"JPEG_Q88_4patches_per_frame_ZIP_STORED\"}";
        auto str=metadata.str();
        std::vector<uint8_t> m(str.begin(),str.end());
        bool good=zip.add("manifest.json",m)&&zip.finish();
        {std::lock_guard lock(mutex_);encoded_=encoded;output_=target.string();
            if(!good||encoded<2){error_=good?"Fewer than 2 consecutive frames saved":"ZIP write failed";state_=3;}
            else state_=2;}
        CoUninitialize();
    }
public:
    explicit Recorder(uint64_t id):id_(id),start_ms_(GetTickCount64()){}
    std::shared_ptr<Frame> stage(ID3D12Device* dev){
        if(!dev||state_.load()!=0)return {};
        const auto elapsed=GetTickCount64()-start_ms_;
        if(elapsed<ArmDelayMillis||elapsed>=ArmDelayMillis+CaptureMillis)return {};
        {std::lock_guard lock(mutex_);if(frames_.size()>=MaxFrames)return {};}
        auto frame=std::make_shared<Frame>();
        for(size_t k=0;k<4;++k)if(!allocate(dev,frame->patches[k],k<2?OutputCrop:SourceCrop,k<2)){
            std::lock_guard lock(mutex_);++rejected_;return {};}
        if(FAILED(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&frame->fence)))){
            std::lock_guard lock(mutex_);++rejected_;return {};}
        return frame;
    }
    bool record(ID3D12GraphicsCommandList* cmd,const std::shared_ptr<Frame>& f,
                ID3D12Resource* xr,ID3D12Resource* left,ID3D12Resource* right,
                unsigned activeLeftW,unsigned activeLeftH,unsigned activeRightW,unsigned activeRightH){
        if(!cmd||!f||!xr||!left||!right||state_.load()!=0)return false;
        const auto x=xr->GetDesc(),l=left->GetDesc(),r=right->GetDesc();
        if(x.Width<2*OutputCrop||x.Height<OutputCrop||x.Width%2||
           activeLeftW<SourceCrop||activeLeftH<SourceCrop||
           activeRightW<SourceCrop||activeRightH<SourceCrop||
           activeLeftW>l.Width||activeLeftH>l.Height||activeRightW>r.Width||activeRightH>r.Height||
           !supported(x.Format)||!supported(l.Format)||!supported(r.Format))return false;
        const unsigned eyeW=unsigned(x.Width/2),eyeY=unsigned(x.Height/2);
        const unsigned cx=eyeW/2;
        // Native same-pixel crops in each final XR eye, not JPEG resizes.
        if(!copy(cmd,f->patches[0],xr,cx,eyeY)||
           !copy(cmd,f->patches[1],xr,eyeW+cx,eyeY)||
           !copy(cmd,f->patches[2],left,activeLeftW/2,activeLeftH/2)||
           !copy(cmd,f->patches[3],right,activeRightW/2,activeRightH/2))return false;
        f->recorded=true;return true;
    }
    void submit(const std::shared_ptr<Frame>& frame,ID3D12CommandQueue* queue,
                bool submitted,uint64_t packet_serial,std::string metadata){
        if(!frame)return;
        if(!submitted||!frame->recorded||!queue){if(frame->recorded)quarantine(frame);std::lock_guard lock(mutex_);++rejected_;return;}
        if(FAILED(queue->Signal(frame->fence.Get(),1))){quarantine(frame);std::lock_guard lock(mutex_);++rejected_;return;}
        frame->frame_serial=packet_serial;frame->captured_ms=GetTickCount64()-start_ms_-ArmDelayMillis;
        frame->metadata=std::move(metadata);frame->accepted=true;
        std::lock_guard lock(mutex_);frames_.push_back(frame);
    }
    void finish_if_ready(){
        if(state_.load()!=0)return;
        bool complete=GetTickCount64()-start_ms_>=ArmDelayMillis+CaptureMillis;
        {std::lock_guard lock(mutex_);complete=complete||frames_.size()>=MaxFrames;}
        if(!complete)return;
        unsigned expected=0;if(!state_.compare_exchange_strong(expected,1))return;
        try {auto self=shared_from_this();std::thread([self]{self->encode();}).detach();}
        catch(...){std::lock_guard lock(mutex_);error_="Could not start encoder thread";state_=3;}
    }
    std::string status() const {
        std::lock_guard lock(mutex_);std::ostringstream s;
        s<<"sequence "<<id_<<" frames="<<frames_.size()<<" state=";
        switch(state_.load()){case 0:s<<(GetTickCount64()-start_ms_<ArmDelayMillis ? "ARMED_3s_COUNTDOWN" : "RECORDING");break;case 1:s<<"ENCODING";break;
            case 2:s<<"READY";break;default:s<<"FAILED";break;}
        if(!output_.empty())s<<" file="<<output_;
        if(!error_.empty())s<<" reason="<<error_;
        if(state_.load()==2)s<<" encoded="<<encoded_;
        return s.str();
    }
    bool active() const{return state_.load()<=1;}
};
} // namespace uevr::duoview::sequence

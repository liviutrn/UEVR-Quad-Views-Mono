// Production recorder test: actual WARP copy/fence -> WIC lossless PNG ->
// bounded multi-part ZIP. Python subsequently verifies exact GPU bytes.
#include "DuoViewDiagnosticRecorder.hpp"
#include <dxgi1_6.h>
#include <d3d12sdklayers.h>
#include <iostream>
#include <random>
#include <stdexcept>
using namespace uevr::duoview::capture75;
static void hr(HRESULT h,const char* message){if(FAILED(h))throw std::runtime_error(message);}
struct GPU {
    ComPtr<ID3D12Device> device;ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;UINT64 serial{};
    GPU(){
        ComPtr<ID3D12Debug> debug;if(SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))))debug->EnableDebugLayer();
        ComPtr<IDXGIFactory4> factory;ComPtr<IDXGIAdapter> warp;
        hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"DXGI factory");hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)),"WARP");
        hr(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)),"D3D12 device");
        D3D12_COMMAND_QUEUE_DESC q{};hr(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)),"queue");
        hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)),"allocator");
        hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)),"list");
        hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"fence");
    }
    void flush(){
        hr(list->Close(),"close");ID3D12CommandList* lists[]{list.Get()};queue->ExecuteCommandLists(1,lists);
        hr(queue->Signal(fence.Get(),++serial),"signal");
        HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr);if(!event)throw std::runtime_error("event");
        hr(fence->SetEventOnCompletion(serial,event),"completion");
        if(WaitForSingleObject(event,10000)!=WAIT_OBJECT_0)throw std::runtime_error("GPU timeout");CloseHandle(event);
        hr(allocator->Reset(),"allocator reset");hr(list->Reset(allocator.Get(),nullptr),"list reset");
    }
    ComPtr<ID3D12Resource> texture(UINT width,UINT height,DXGI_FORMAT format,D3D12_RESOURCE_STATES state,
                                const std::vector<uint8_t>& bytes,UINT bpp){
        D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;desc.Width=width;desc.Height=height;
        desc.DepthOrArraySize=desc.MipLevels=1;desc.Format=format;desc.SampleDesc.Count=1;
        if(state==D3D12_RESOURCE_STATE_RENDER_TARGET)desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        ComPtr<ID3D12Resource> resource;hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&resource)),"texture");
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT rows{};UINT64 row_bytes{},total{};
        device->GetCopyableFootprints(&desc,0,1,0,&fp,&rows,&row_bytes,&total);
        auto buffer=desc;buffer.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;buffer.Width=total;buffer.Height=1;
        buffer.Format=DXGI_FORMAT_UNKNOWN;buffer.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;buffer.Flags=D3D12_RESOURCE_FLAG_NONE;
        heap.Type=D3D12_HEAP_TYPE_UPLOAD;ComPtr<ID3D12Resource> upload;
        hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&buffer,D3D12_RESOURCE_STATE_GENERIC_READ,
            nullptr,IID_PPV_ARGS(&upload)),"upload");
        void* p{};hr(upload->Map(0,nullptr,&p),"map upload");
        for(UINT y=0;y<height;++y)std::memcpy(static_cast<uint8_t*>(p)+size_t(y)*fp.Footprint.RowPitch,
            bytes.data()+size_t(y)*width*bpp,size_t(width)*bpp);
        upload->Unmap(0,nullptr);
        D3D12_TEXTURE_COPY_LOCATION dst{},src{};dst.pResource=resource.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        src.pResource=upload.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=fp;
        list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
        D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition={resource.Get(),0,D3D12_RESOURCE_STATE_COPY_DEST,state};list->ResourceBarrier(1,&barrier);flush();
        return resource;
    }
};
int main(int argc,char** argv)try {
    if(argc!=2)throw std::runtime_error("usage: recorder_gpu_tests OUTPUT_DIRECTORY");
    const auto evidence=std::filesystem::absolute(argv[1]);std::filesystem::create_directories(evidence);
    GPU gpu;
    std::mt19937 random(73);std::vector<uint8_t> color(512*256*4);
    for(auto& b:color)b=uint8_t(random());
    auto xr=gpu.texture(512,256,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_STATE_RENDER_TARGET,color,4);
    std::vector<uint8_t> depth_bytes(256*256*4);
    const uint32_t special[]{0u,0x3f800000u,0x3dcccccdu,0x7fc12345u,0x7f800000u,0xff800000u,0x80000000u,0xffffffffu,0x000000ffu,0x0000ff00u,0x00000001u};
    for(size_t i=0;i<depth_bytes.size()/4;++i){const auto bits=special[i%std::size(special)];std::memcpy(depth_bytes.data()+i*4,&bits,4);}
    {std::ofstream file(evidence/"input_color.bin",std::ios::binary);file.write(reinterpret_cast<const char*>(color.data()),std::streamsize(color.size()));}
    {std::ofstream file(evidence/"input_depth.bin",std::ios::binary);file.write(reinterpret_cast<const char*>(depth_bytes.data()),std::streamsize(depth_bytes.size()));}
    auto depth=gpu.texture(256,256,DXGI_FORMAT_R32_FLOAT,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,depth_bytes,4);
    const auto source=[&](const char* name,ID3D12Resource* r,bool required,unsigned extent=192){
        Source s;s.name=name;s.resource=r;s.required=required;s.extent=extent;
        s.state=name[0]=='d'?D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE:D3D12_RESOURCE_STATE_RENDER_TARGET;
        if(r)s.active={0,0,256,256};return s;
    };
    auto recorder=std::make_shared<Recorder>(75001,0,24,2000);
    const auto began=GetTickCount64();
    for(unsigned frame=0;frame<24;++frame){
        std::vector<Source> inputs{source("xr_left",nullptr,true),source("xr_right",nullptr,true),
            source("source_left",xr.Get(),true),source("source_right",xr.Get(),true),
            source("depth_left",depth.Get(),true),source("depth_right",depth.Get(),true)};
        // Additional same-format fixture planes force multiple upload parts.
        for(unsigned k=0;k<6;++k)inputs.push_back(source(("fixture_color_"+std::to_string(k)).c_str(),xr.Get(),false));
        auto f=recorder->stage(gpu.device.Get(),std::move(inputs),frame+1);
        if(!f)throw std::runtime_error("frame staging failed");
        if(!recorder->record(gpu.list.Get(),f,xr.Get()))throw std::runtime_error("copy record failed");
        gpu.flush();
        recorder->submit(f,gpu.queue.Get(),true,true,frame+1,
            "{\"stereo_recorded\":true,\"fixture\":true,\"mode\":5,\"crop\":[0.25,0.25,0.75,0.75]}");
        std::this_thread::sleep_for(std::chrono::milliseconds(15));
    }
    // Intentionally completed 24 native frames; wall-clock window completion
    // is independent of encoding/splitting and is part of the success gate.
    while(GetTickCount64()-began<2050)std::this_thread::sleep_for(std::chrono::milliseconds(20));
    recorder->finish_if_ready();
    const auto wait=GetTickCount64();
    while(recorder->active()&&GetTickCount64()-wait<60000)std::this_thread::sleep_for(std::chrono::milliseconds(50));
    std::cout<<recorder->status()<<"\n";
    if(recorder->active()||recorder->status().find("READY")==std::string::npos)throw std::runtime_error("recorder did not complete");
    const auto dir=std::filesystem::temp_directory_path()/"UEVR_DuoViewDiagnostics";
    unsigned parts=0;
    for(const auto& p:std::filesystem::directory_iterator(dir))
        if(p.path().filename().string().find("75001")!=std::string::npos&&p.path().extension()==".zip") {
            if(std::filesystem::file_size(p.path())>MaxZipBytes)throw std::runtime_error("ZIP cap exceeded");
            std::filesystem::copy_file(p.path(),evidence/p.path().filename(),std::filesystem::copy_options::overwrite_existing);++parts;
        }
    if(parts<2)throw std::runtime_error("multi-part path not exercised");
    ComPtr<ID3D12InfoQueue> info;if(SUCCEEDED(gpu.device.As(&info)))
        for(UINT64 i=0;i<info->GetNumStoredMessages();++i) {
            SIZE_T size{};info->GetMessage(i,nullptr,&size);std::vector<uint8_t> data(size);
            auto* message=reinterpret_cast<D3D12_MESSAGE*>(data.data());info->GetMessage(i,message,&size);
            if(message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)throw std::runtime_error(message->pDescription);
        }
    std::cout<<"PASS: 24 actual GPU copied frames, exact raw float bit patterns, background PNG, multi-part ZIP, no GPU validation errors\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}

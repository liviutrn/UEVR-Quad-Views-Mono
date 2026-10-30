// CI77 D3D12/WARP integration check for the real depth stabilization class.
#include "DuoViewDepthStabilization.hpp"
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <cmath>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>
using namespace uevr::duoview;
using namespace uevr::duoview::dx12;
static void hr(HRESULT h,const char* what){if(FAILED(h))throw std::runtime_error(what);}
static void need(bool ok,const char* what){if(!ok)throw std::runtime_error(what);}
struct GPU {
    Microsoft::WRL::ComPtr<ID3D12Device> device;
    Microsoft::WRL::ComPtr<ID3D12CommandQueue> queue;
    Microsoft::WRL::ComPtr<ID3D12CommandAllocator> allocator;
    Microsoft::WRL::ComPtr<ID3D12GraphicsCommandList> list;
    Microsoft::WRL::ComPtr<ID3D12Fence> fence;
    UINT64 serial{};
    GPU(){
        Microsoft::WRL::ComPtr<ID3D12Debug> debug;
        if(SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))))debug->EnableDebugLayer();
        Microsoft::WRL::ComPtr<IDXGIFactory4> factory;Microsoft::WRL::ComPtr<IDXGIAdapter> warp;
        hr(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"factory");
        hr(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)),"WARP adapter");
        hr(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)),"device");
        D3D12_COMMAND_QUEUE_DESC q{};hr(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)),"queue");
        hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)),"allocator");
        hr(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&list)),"list");
        hr(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"fence");
    }
    void submit(){
        hr(list->Close(),"close");ID3D12CommandList* lists[]{list.Get()};queue->ExecuteCommandLists(1,lists);
        hr(queue->Signal(fence.Get(),++serial),"signal");HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        if(!event)throw std::runtime_error("event");hr(fence->SetEventOnCompletion(serial,event),"completion");
        if(WaitForSingleObject(event,10000)!=WAIT_OBJECT_0)throw std::runtime_error("GPU timeout");CloseHandle(event);
        Microsoft::WRL::ComPtr<ID3D12InfoQueue> info;
        if(SUCCEEDED(device.As(&info)))for(UINT64 i=0;i<info->GetNumStoredMessages();++i){
            SIZE_T size{};info->GetMessage(i,nullptr,&size);std::vector<uint8_t> bytes(size);
            auto* m=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());info->GetMessage(i,m,&size);
            if(m->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)throw std::runtime_error(m->pDescription);
        }
        hr(allocator->Reset(),"allocator reset");hr(list->Reset(allocator.Get(),nullptr),"list reset");
    }
    Microsoft::WRL::ComPtr<ID3D12Resource> depth(UINT width,UINT height,float value){
        std::vector<float> pixels(size_t(width)*height,value);
        D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Width=width;d.Height=height;
        d.DepthOrArraySize=d.MipLevels=1;d.Format=DXGI_FORMAT_R32_FLOAT;d.SampleDesc.Count=1;
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
        Microsoft::WRL::ComPtr<ID3D12Resource> out;hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&out)),"depth texture");
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT rows{};UINT64 rowBytes{},total{};
        device->GetCopyableFootprints(&d,0,1,0,&fp,&rows,&rowBytes,&total);
        D3D12_RESOURCE_DESC bd{};bd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;bd.Width=total;bd.Height=1;
        bd.DepthOrArraySize=bd.MipLevels=1;bd.SampleDesc.Count=1;bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        heap.Type=D3D12_HEAP_TYPE_UPLOAD;Microsoft::WRL::ComPtr<ID3D12Resource> upload;
        hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&bd,D3D12_RESOURCE_STATE_GENERIC_READ,
            nullptr,IID_PPV_ARGS(&upload)),"depth upload");void* p{};hr(upload->Map(0,nullptr,&p),"upload map");
        for(UINT y=0;y<height;++y)std::memcpy(static_cast<uint8_t*>(p)+size_t(y)*fp.Footprint.RowPitch,
            pixels.data()+size_t(y)*width,size_t(width)*sizeof(float));upload->Unmap(0,nullptr);
        D3D12_TEXTURE_COPY_LOCATION dst{},src{};dst.pResource=out.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        src.pResource=upload.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=fp;
        list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
        D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition={out.Get(),0,D3D12_RESOURCE_STATE_COPY_DEST,
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE};
        list->ResourceBarrier(1,&b);submit();return out;
    }
    float center(ID3D12Resource* texture,UINT width,UINT height){
        const auto d=texture->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT rows{};UINT64 rowBytes{},total{};
        device->GetCopyableFootprints(&d,0,1,0,&fp,&rows,&rowBytes,&total);
        D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_READBACK;
        D3D12_RESOURCE_DESC bd{};bd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;bd.Width=total;bd.Height=1;
        bd.DepthOrArraySize=bd.MipLevels=1;bd.SampleDesc.Count=1;bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        Microsoft::WRL::ComPtr<ID3D12Resource> readback;
        hr(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&bd,D3D12_RESOURCE_STATE_COPY_DEST,
            nullptr,IID_PPV_ARGS(&readback)),"readback");
        D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition={texture,0,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
            D3D12_RESOURCE_STATE_COPY_SOURCE};list->ResourceBarrier(1,&b);
        D3D12_TEXTURE_COPY_LOCATION src{},dst{};src.pResource=texture;src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.pResource=readback.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=fp;
        list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
        b.Transition={texture,0,D3D12_RESOURCE_STATE_COPY_SOURCE,
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE};list->ResourceBarrier(1,&b);
        submit();void* p{};D3D12_RANGE read{0,SIZE_T(total)};hr(readback->Map(0,&read,&p),"readback map");
        float value{};std::memcpy(&value,static_cast<uint8_t*>(p)+size_t(height/2)*fp.Footprint.RowPitch+
            size_t(width/2)*sizeof(float),sizeof(value));D3D12_RANGE written{0,0};readback->Unmap(0,&written);return value;
    }
};
static ViewFrame make_frame(uint32_t number){
    ViewFrame f{};f.config.key.generation=1;f.config.key.frame=number;
    f.config.layout.u0=0.f;f.config.layout.v0=0.f;f.config.layout.u1=1.f;f.config.layout.v1=1.f;
    f.camera_valid=true;f.projections={true,true};f.cameras={true,true};
    f.projection[0]=f.projection[5]=1.f;
    f.projection[10]=0.f;f.projection[11]=1.f;f.projection[14]=100.f;f.projection[15]=0.f;
    f.projection_right=f.projection;return f;
}
static std::array<ngx::Guide,2> make_guides(UINT width,UINT height){
    std::array<ngx::Guide,2> g{};for(UINT e=0;e<2;++e){g[e].manual_source=true;g[e].feature_generation=7;
        g[e].evaluation=11;g[e].role=e+1;g[e].input_width=g[e].output_width=width;
        g[e].input_height=g[e].output_height=height;g[e].jitter_x=e?-.25f:.25f;g[e].jitter_y=0.f;}
    return g;
}
int main()try{
    GPU gpu;DepthStabilizer stabilizer;
    auto left=gpu.depth(8,8,.25f),right=gpu.depth(8,8,.75f);
    auto frame=make_frame(100);auto guides=make_guides(8,8);
    const DepthViewport leftView{0,0,8,8,0,1},rightView{0,0,8,8,0,1};
    need(stabilizer.prepare(gpu.device.Get(),frame,guides,left.Get(),right.Get(),leftView,rightView,.75f),
         "first-frame prepare failed");
    need(stabilizer.record(gpu.list.Get()),"first-frame record failed");
    need(stabilizer.left()!=stabilizer.right(),"left/right history maps alias");
    const float l0=gpu.center(stabilizer.left(),8,8),r0=gpu.center(stabilizer.right(),8,8);
    need(std::abs(l0-.25f)<1.e-5f&&std::abs(r0-.75f)<1.e-5f,"first-frame spatial output incorrect");

    left=gpu.depth(8,8,.30f);right=gpu.depth(8,8,.70f);frame=make_frame(101);
    guides[0].jitter_x=-.2f;guides[1].jitter_x=.2f;
    need(stabilizer.prepare(gpu.device.Get(),frame,guides,left.Get(),right.Get(),leftView,rightView,.75f),
         "history-frame prepare failed");
    need(stabilizer.record(gpu.list.Get()),"history-frame record failed");
    const float l1=gpu.center(stabilizer.left(),8,8),r1=gpu.center(stabilizer.right(),8,8);
    need(std::abs(l1-.30f)<1.e-5f&&std::abs(r1-.70f)<1.e-5f,"history blended across incompatible depth");

    // Temporal disabled, then resize: both are required history-reset cases.
    frame=make_frame(102);
    need(stabilizer.prepare(gpu.device.Get(),frame,guides,left.Get(),right.Get(),leftView,rightView,0.f),
         "temporal-off prepare failed");
    need(stabilizer.record(gpu.list.Get()),"temporal-off record failed");
    auto widerLeft=gpu.depth(10,8,.4f),widerRight=gpu.depth(10,8,.6f);
    frame=make_frame(103);guides=make_guides(10,8);
    const DepthViewport wideView{0,0,10,8,0,1};
    need(stabilizer.prepare(gpu.device.Get(),frame,guides,widerLeft.Get(),widerRight.Get(),wideView,wideView,.75f),
         "resize prepare failed");
    need(stabilizer.record(gpu.list.Get()),"resize record failed");
    need(std::abs(gpu.center(stabilizer.left(),10,8)-.4f)<1.e-5f&&
         std::abs(gpu.center(stabilizer.right(),10,8)-.6f)<1.e-5f,"resize output incorrect");
    std::cout<<"PASS: D3D12/WARP first frame, independent eye maps, temporal rejection, toggle, resize, no validation errors\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}

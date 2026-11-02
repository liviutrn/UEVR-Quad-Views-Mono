// Windows WARP end-to-end proof for live NGX depth -> GPU snapshot -> native
// fovea shader and exact-frame fallback. No game SDK, NR, CPU depth readback or
// hooked NGX DLL is required. This exercises real DX12 copy/descriptor/PSO.
#include <windows.h>
#include <dxgi1_6.h>
#include <array>
#include <cstdint>
#include <cstring>
#include <functional>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>
#include "DuoViewD3D12.hpp"
using Microsoft::WRL::ComPtr;
using namespace uevr::duoview;

static void ck(HRESULT result) {
    if(FAILED(result))throw std::runtime_error("HRESULT "+std::to_string(uint32_t(result)));
}
static D3D12_HEAP_PROPERTIES heap(D3D12_HEAP_TYPE t) {
    D3D12_HEAP_PROPERTIES h{};h.Type=t;h.CreationNodeMask=h.VisibleNodeMask=1;return h;
}
static D3D12_RESOURCE_DESC texture(uint32_t w,uint32_t h,DXGI_FORMAT fmt,D3D12_RESOURCE_FLAGS flags) {
    D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width=w;d.Height=h;d.DepthOrArraySize=d.MipLevels=1;
    d.Format=fmt;d.SampleDesc.Count=1;d.Flags=flags;return d;
}
static D3D12_RESOURCE_DESC buffer(uint64_t bytes) {
    D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
    d.Width=bytes;d.Height=d.DepthOrArraySize=d.MipLevels=1;
    d.SampleDesc.Count=1;d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;return d;
}
static ComPtr<ID3D12Resource> res(ID3D12Device* device,const D3D12_RESOURCE_DESC& d,
                                D3D12_HEAP_TYPE h,D3D12_RESOURCE_STATES state) {
    auto hp=heap(h);ComPtr<ID3D12Resource> out;
    ck(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,state,nullptr,IID_PPV_ARGS(&out)));
    return out;
}
static void barrier(ID3D12GraphicsCommandList* cmd,ID3D12Resource* resource,
                    D3D12_RESOURCE_STATES from,D3D12_RESOURCE_STATES to) {
    D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition={resource,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,from,to};
    cmd->ResourceBarrier(1,&b);
}
static ComPtr<ID3D12Resource> upload(ID3D12Device* device,ID3D12GraphicsCommandList* cmd,
    ID3D12Resource* target,uint32_t width,uint32_t height,
    const std::function<void(uint32_t,uint32_t,void*)>& fill) {
    const auto desc=target->GetDesc();
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};uint64_t bytes{};
    device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&bytes);
    auto staged=res(device,buffer(bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    void* ptr{};D3D12_RANGE none{0,0};ck(staged->Map(0,&none,&ptr));
    std::memset(ptr,0,size_t(bytes));
    for(uint32_t y=0;y<height;++y)for(uint32_t x=0;x<width;++x) {
        void* pixel=static_cast<uint8_t*>(ptr)+fp.Offset+y*fp.Footprint.RowPitch+x*4;
        fill(x,y,pixel);
    }
    staged->Unmap(0,nullptr);
    D3D12_TEXTURE_COPY_LOCATION src{},dst{};
    src.pResource=staged.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=fp;
    dst.pResource=target;dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
    return staged;
}
static void wait(ID3D12CommandQueue* queue,ID3D12Fence* fence,uint64_t value) {
    ck(queue->Signal(fence,value));
    if(fence->GetCompletedValue()>=value)return;
    HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
    if(!event)throw std::runtime_error("CreateEvent failed");
    ck(fence->SetEventOnCompletion(value,event));
    const auto result=WaitForSingleObject(event,30000);
    CloseHandle(event);
    if(result!=WAIT_OBJECT_0)throw std::runtime_error("WARP test timeout");
}
int main() try {
    ComPtr<IDXGIFactory4> factory;ck(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIAdapter> adapter;ck(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
    ComPtr<ID3D12Device> device;ck(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)));
    D3D12_COMMAND_QUEUE_DESC dq{};dq.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;ck(device->CreateCommandQueue(&dq,IID_PPV_ARGS(&queue)));
    ComPtr<ID3D12CommandAllocator> producer_alloc,composite_alloc;
    ck(device->CreateCommandAllocator(dq.Type,IID_PPV_ARGS(&producer_alloc)));
    ck(device->CreateCommandAllocator(dq.Type,IID_PPV_ARGS(&composite_alloc)));
    ComPtr<ID3D12GraphicsCommandList> producer,consumer;
    ck(device->CreateCommandList(0,dq.Type,producer_alloc.Get(),nullptr,IID_PPV_ARGS(&producer)));
    ck(device->CreateCommandList(0,dq.Type,composite_alloc.Get(),nullptr,IID_PPV_ARGS(&consumer)));
    ck(consumer->Close());
    constexpr uint32_t W=64,H=64;
    auto focus=res(device.Get(),texture(W,H,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),
        D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    auto context=res(device.Get(),texture(W,H,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),
        D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    auto depth=res(device.Get(),texture(32,32,DXGI_FORMAT_R32_FLOAT,D3D12_RESOURCE_FLAG_NONE),
        D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    auto stereo=res(device.Get(),texture(W*2,H,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),
        D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
    std::vector<ComPtr<ID3D12Resource>> uploads;
    uploads.push_back(upload(device.Get(),producer.Get(),focus.Get(),W,H,
        [](uint32_t,uint32_t,void* p){const uint8_t bgra[]{0,0,255,255};std::memcpy(p,bgra,4);}));
    uploads.push_back(upload(device.Get(),producer.Get(),context.Get(),W,H,
        [](uint32_t,uint32_t,void* p){const uint8_t bgra[]{255,0,0,255};std::memcpy(p,bgra,4);}));
    uploads.push_back(upload(device.Get(),producer.Get(),depth.Get(),32,32,
        [](uint32_t x,uint32_t,void* p){const float d=x<16?0.5f:0.01f;std::memcpy(p,&d,4);}));
    barrier(producer.Get(),focus.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
    barrier(producer.Get(),context.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
    barrier(producer.Get(),depth.Get(),D3D12_RESOURCE_STATE_COPY_DEST,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);

    const auto layout=make_layout(W,H,.5f,.5f,.25f,1.f,.5f,.5f);
    if(!layout || layout->fovea.width!=32 || layout->periphery.width!=16)
        throw std::runtime_error("Unexpected test fovea geometry");
    ngx::DepthCandidate sample{};
    sample.feature=0xface;
    sample.output_width=32;sample.output_height=32;
    sample.render_width=32;sample.render_height=32;
    sample.depth_width=32;sample.depth_height=32;
    sample.depth_present=sample.color_present=true;
    sample.create_observed=true;sample.feature_kind=1;
    ngx::candidates().set_expected(32,32,16,16);
    ngx::candidates().observe(sample);
    if(!ngx::candidates().choose().exact)throw std::runtime_error("NGX auto source missing");
    auto& pool=ngx::depth_snapshots();
    pool.set_enabled(true);
    if(!pool.bind_queue(queue.Get()))throw std::runtime_error("WARP producer queue rejected");
    const FrameKey frame_key{1,10};
    pool.capture(producer.Get(),depth.Get(),sample,frame_key);
    ck(producer->Close());
    ID3D12CommandList* prod[]{producer.Get()};
    queue->ExecuteCommandLists(1,prod);
    pool.submitted(queue.Get(),1,prod);
    if(pool.captures()!=1 || pool.submits()!=1)
        throw std::runtime_error("NGX depth producer copy not submitted");

    dx12::Compositor compositor;
    if(!compositor.prewarm(device.Get(),W,H,false))
        throw std::runtime_error("Native compositor prewarm failed");
    ViewFrame frame{};
    frame.config.key=frame_key;frame.config.layout=*layout;
    frame.config.settings.fovea_view=0;
    frame.config.settings.feather_fraction=0;
    frame.config.settings.sharpen_strength=1.f;
    frame.config.settings.distance_sharpen_enabled=true;
    frame.config.settings.sharpen_near_strength=5.f;
    frame.config.settings.sharpen_far_strength=1.f;
    frame.config.settings.sharpen_near_m=.5f;
    frame.config.settings.sharpen_far_m=4.f;
    frame.config.settings.depth_preview_mode=2; // metres ramp, near black / far white
    frame.config.settings.depth_reversed_z=true;
    frame.projection[14]=10.f; // UE centimeters: 10 cm near -> 0.1 m
    auto readback_desc=stereo->GetDesc();
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT out_fp{};uint64_t readback_bytes{};
    device->GetCopyableFootprints(&readback_desc,0,1,0,&out_fp,nullptr,nullptr,&readback_bytes);
    auto readback=res(device.Get(),buffer(readback_bytes),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
    const auto record=[&](uint64_t frame_index) {
        frame.config.key.frame=frame_index;
        if(!compositor.record_native(device.Get(),consumer.Get(),focus.Get(),context.Get(),stereo.Get(),
            D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,
            frame,std::static_pointer_cast<const void>(std::make_shared<int>(11)),0,queue.Get()))
            throw std::runtime_error(compositor.error());
        barrier(consumer.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,
            D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION from{},to{};
        from.pResource=stereo.Get();from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        to.pResource=readback.Get();to.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;to.PlacedFootprint=out_fp;
        consumer->CopyTextureRegion(&to,0,0,0,&from,nullptr);
        ck(consumer->Close());
        ID3D12CommandList* lists[]{consumer.Get()};queue->ExecuteCommandLists(1,lists);
    };
    ComPtr<ID3D12Fence> fence;ck(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));
    ck(consumer->Reset(composite_alloc.Get(),nullptr));
    record(10);
    wait(queue.Get(),fence.Get(),1);
    D3D12_RANGE readable{0,size_t(readback_bytes)};
    void* mapped{};ck(readback->Map(0,&readable,&mapped));
    const auto pix=[&](uint32_t x,uint32_t y) {
        return static_cast<uint8_t*>(mapped)+out_fp.Offset+y*out_fp.Footprint.RowPitch+x*4;
    };
    // fovea crop is output x=16..48, interior x=24 (near) / 40 (far).
    const auto near=pix(24,32),far=pix(40,32);
    for(int ch=0;ch<3;++ch)if(near[ch]>12 || far[ch]<240)
        throw std::runtime_error("Live depth preview did not sample near/far on WARP");
    for(uint32_t x:{24u,40u})for(int ch=0;ch<4;++ch)
        if(pix(x,32)[ch]!=pix(x+W,32)[ch])
            throw std::runtime_error("Mono preview not duplicated equally to two eyes");
    readback->Unmap(0,nullptr);

    // NO new producer depth for frame 11: stale frame 10 is never used!
    ck(composite_alloc->Reset());
    ck(consumer->Reset(composite_alloc.Get(),nullptr));
    barrier(consumer.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,
        D3D12_RESOURCE_STATE_RENDER_TARGET);
    record(11);
    wait(queue.Get(),fence.Get(),2);
    ck(readback->Map(0,&readable,&mapped));
    for(uint32_t x:{24u,40u}) {
        const auto p=pix(x,32);
        if(p[2]<180 || p[0]>60)
            throw std::runtime_error("Missing depth did not fall back to native red fovea");
    }
    readback->Unmap(0,nullptr);
    std::cout<<"PASS: DX12 WARP NGX depth copy, foveal meters ramp, mono two-eye copy, exact-frame fallback\n";
    return 0;
} catch(const std::exception& e) {
    std::cerr<<"FAIL v211 WARP depth: "<<e.what()<<"\n";
    return 1;
}

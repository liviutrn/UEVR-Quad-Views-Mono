#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <mods/vr/d3d12/StockDibrDepth.hpp>
#include <hooks/QueueSubmitHook.hpp>
#include <array>
#include <vector>
#include <iostream>
#include <stdexcept>
#include <cstring>
using Microsoft::WRL::ComPtr;
using stock_dibr::DepthCapture;
namespace {
DepthCapture* observer{};
void WINAPI submitted(ID3D12CommandQueue* q,UINT n,ID3D12CommandList* const* lists) {
    if(observer)observer->on_command_lists_executed(q,n,lists);
}
void check(HRESULT h){if(FAILED(h))throw std::runtime_error("HRESULT="+std::to_string(uint32_t(h)));}
void require(bool v,const char* why){if(!v)throw std::runtime_error(why);}
D3D12_HEAP_PROPERTIES heap(D3D12_HEAP_TYPE t){D3D12_HEAP_PROPERTIES p{};p.Type=t;return p;}
ComPtr<ID3D12Resource> resource(ID3D12Device* d,D3D12_RESOURCE_DESC desc,D3D12_HEAP_TYPE type,D3D12_RESOURCE_STATES state) {
    auto hp=heap(type);ComPtr<ID3D12Resource> r;
    check(d->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&r)));return r;
}
void transition(ID3D12GraphicsCommandList* cmd,DepthCapture& cap,ID3D12Resource* r,D3D12_RESOURCE_STATES a,D3D12_RESOURCE_STATES b) {
    D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,a,b};
    cmd->ResourceBarrier(1,&barrier);cap.on_post_resource_barriers(cmd,1,&barrier);
}
struct Readback {ComPtr<ID3D12Resource> resource;D3D12_PLACED_SUBRESOURCE_FOOTPRINT foot{};UINT64 bytes{};};
}
int main() try {
    ComPtr<ID3D12Debug> debug;if(SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))))debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIAdapter> adapter;check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
    ComPtr<ID3D12Device> device;check(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)));
    ComPtr<ID3D12InfoQueue> info;device.As(&info);
    D3D12_COMMAND_QUEUE_DESC qd{};qd.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;check(device->CreateCommandQueue(&qd,IID_PPV_ARGS(&queue)));
    ComPtr<ID3D12CommandAllocator> allocator;check(device->CreateCommandAllocator(qd.Type,IID_PPV_ARGS(&allocator)));
    ComPtr<ID3D12GraphicsCommandList> cmd;check(device->CreateCommandList(0,qd.Type,allocator.Get(),nullptr,IID_PPV_ARGS(&cmd)));
    ComPtr<ID3D12Fence> fence;check(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));uint64_t serial{};
    auto wait=[&] {
        check(queue->Signal(fence.Get(),++serial));HANDLE e=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        require(e!=nullptr,"event creation failed");check(fence->SetEventOnCompletion(serial,e));
        const auto done=WaitForSingleObject(e,30000);CloseHandle(e);require(done==WAIT_OBJECT_0,"WARP timeout");
    };
    DepthCapture cap;cap.configure(device.Get(),queue.Get(),8120,3228,true);
    cap.configure_duoview_sources(2030,1614,812,646);observer=&cap;
    stock_dibr::QueueSubmitHook hook{&submitted};require(hook.install(queue.Get()),"actual queue hook install failed");
    D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_DSV;hd.NumDescriptors=2;
    ComPtr<ID3D12DescriptorHeap> dsv;check(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&dsv)));
    const auto stride=device->GetDescriptorHandleIncrementSize(hd.Type);
    std::array<ComPtr<ID3D12Resource>,2> source;
    const std::array<D3D12_VIEWPORT,2> viewports{{{11,7,1015,807,0,1},{5,3,406,323,0,1}}};
    std::array<D3D12_CPU_DESCRIPTOR_HANDLE,2> handle;
    for(size_t eye=0;eye<2;++eye) {
        D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        d.Width=eye?416:1030;d.Height=eye?332:824;d.DepthOrArraySize=d.MipLevels=1;
        d.Format=DXGI_FORMAT_R32_TYPELESS;d.SampleDesc.Count=1;d.Flags=D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL;
        source[eye]=resource(device.Get(),d,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_DEPTH_WRITE);
        handle[eye]=dsv->GetCPUDescriptorHandleForHeapStart();handle[eye].ptr+=eye*stride;
        D3D12_DEPTH_STENCIL_VIEW_DESC view{};view.Format=DXGI_FORMAT_D32_FLOAT;view.ViewDimension=D3D12_DSV_DIMENSION_TEXTURE2D;
        device->CreateDepthStencilView(source[eye].Get(),&view,handle[eye]);
        cap.on_depth_stencil_view_created(source[eye].Get(),&view,handle[eye]);
    }
    constexpr auto read=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    auto write_pass=[&](size_t eye,float value,bool was_read) {
        if(was_read)transition(cmd.Get(),cap,source[eye].Get(),read,D3D12_RESOURCE_STATE_DEPTH_WRITE);
        const auto v=viewports[eye];cmd->RSSetViewports(1,&v);cap.on_viewports(cmd.Get(),1,&v);
        cmd->OMSetRenderTargets(0,nullptr,FALSE,&handle[eye]);cap.on_render_targets(cmd.Get(),0,handle[eye]);
        cmd->ClearDepthStencilView(handle[eye],D3D12_CLEAR_FLAG_DEPTH,.9f,0,0,nullptr);
        const D3D12_RECT rect{LONG(v.TopLeftX),LONG(v.TopLeftY),LONG(v.TopLeftX+v.Width),LONG(v.TopLeftY+v.Height)};
        cmd->ClearDepthStencilView(handle[eye],D3D12_CLEAR_FLAG_DEPTH,value,0,1,&rect);
        cmd->OMSetRenderTargets(0,nullptr,FALSE,nullptr);cap.on_render_targets(cmd.Get(),0,{});
        transition(cmd.Get(),cap,source[eye].Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE,read);
    };
    write_pass(0,.25f,false);
    // Former policy could fill all 12 slots with read-only copies before the
    // right peripheral pass. No write version is lost by ignoring these.
    for(int repeat=0;repeat<20;++repeat) {
        transition(cmd.Get(),cap,source[0].Get(),read,read|D3D12_RESOURCE_STATE_DEPTH_READ);
        transition(cmd.Get(),cap,source[0].Get(),read|D3D12_RESOURCE_STATE_DEPTH_READ,read);
    }
    write_pass(1,.125f,false);
    write_pass(0,.5f,true); // same original DSV, distinct real write/content version
    require(cap.preview_count()==0,"recorded-but-unsubmitted source was published");
    check(cmd->Close());ID3D12CommandList* lists[]{cmd.Get()};queue->ExecuteCommandLists(1,lists);wait();
    require(cap.preview_count()==3,"DuoView lost periphery or deduplicated distinct DSV write versions");
    auto pair=cap.select_preview(0,0,2030,1614,812,646);
    require(pair.left && pair.right && pair.left.Get()!=pair.right.Get(),"DLSS-scaled Auto pair unavailable");
    require(pair.left_viewport.TopLeftX==11 && pair.right_viewport.TopLeftX==5,"per-source depth viewport metadata lost");
    cap.arm_diagnostic_capture();auto candidates=cap.snapshot_candidates();
    require(candidates.size()==3,"snapshot lost selected leased depth sources");
    check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));cap.on_command_list_reset(cmd.Get());
    std::vector<Readback> copies;
    for(const auto& candidate:candidates) {
        const auto desc=candidate.source->GetDesc();Readback rb;
        device->GetCopyableFootprints(&desc,0,1,0,&rb.foot,nullptr,nullptr,&rb.bytes);
        D3D12_RESOURCE_DESC b{};b.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;b.Width=rb.bytes;
        b.Height=b.DepthOrArraySize=b.MipLevels=1;b.SampleDesc.Count=1;b.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        rb.resource=resource(device.Get(),b,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
        transition(cmd.Get(),cap,candidate.source.Get(),read,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION from{candidate.source.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
        D3D12_TEXTURE_COPY_LOCATION to{rb.resource.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};to.PlacedFootprint=rb.foot;
        cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
        transition(cmd.Get(),cap,candidate.source.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,read);copies.push_back(std::move(rb));
    }
    check(cmd->Close());queue->ExecuteCommandLists(1,lists);
    // This call belongs AFTER both compositor/snapshot consumers. Keeping a
    // pending request armed changes discovery budget only, never source age.
    cap.finish_frame(true);wait();
    require(cap.preview_count()==0,"old epoch depth remained eligible after tail retirement");
    require(cap.snapshot_candidates().empty(),"old snapshot leaked into next color frame");
    std::array<bool,3> found{};
    for(const auto& rb:copies) {
        void* data{};D3D12_RANGE range{0,static_cast<SIZE_T>(rb.bytes)};check(rb.resource->Map(0,&range,&data));
        const bool left=rb.foot.Footprint.Width==1030;const size_t x=left?11:5,y=left?7:3;
        float active{},padding{};std::memcpy(&active,static_cast<uint8_t*>(data)+rb.foot.Offset+y*rb.foot.Footprint.RowPitch+x*4,4);
        std::memcpy(&padding,static_cast<uint8_t*>(data)+rb.foot.Offset,4);rb.resource->Unmap(0,nullptr);
        require(std::abs(padding-.9f)<1.e-6f,"depth allocation padding not preserved");
        if(left && active==.25f)found[0]=true;
        if(left && active==.5f)found[1]=true;
        if(!left && active==.125f)found[2]=true;
    }
    require(found[0]&&found[1]&&found[2],"owned depth snapshots did not preserve distinct source contents");
    cap.finish_frame();wait();observer=nullptr;hook.clear();
    if(info)for(UINT64 i=0;i<info->GetNumStoredMessages();++i) {
        SIZE_T n{};check(info->GetMessage(i,nullptr,&n));std::vector<uint8_t> bytes(n);
        auto* message=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());check(info->GetMessage(i,message,&n));
        if(message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)throw std::runtime_error(message->pDescription);
    }
    std::cout<<"PASS: production R5 DuoView interval preserves 3 actual GPU copies, DLSS periphery at 10% HMD, nonzero rects, 20 read-only transitions do not starve sources, reused DSV write versions stay distinct, raw readbacks match, tail invalidation rejects stale depth\n";
    return 0;
} catch(const std::exception& e){observer=nullptr;std::cerr<<"FAIL: "<<e.what()<<"\n";return 1;}

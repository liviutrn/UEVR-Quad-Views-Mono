#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <d3dcompiler.h>
#include <wrl.h>
#include <mods/vr/d3d12/StockDibrDepth.hpp>
#include <hooks/QueueSubmitHook.hpp>
#include <array>
#include <vector>
#include <iostream>
#include <stdexcept>
#include <cstring>
#include <memory>
#include <atomic>
#include <algorithm>
#include <cmath>
#include <limits>
#include <chrono>
#include "production_shader.hpp"
#include "production_constants.hpp"
using Microsoft::WRL::ComPtr;
void check(HRESULT hr) { if(FAILED(hr)) throw std::runtime_error("HRESULT="+std::to_string(uint32_t(hr))); }
void require(bool test,const char* text) { if(!test) throw std::runtime_error(text); }
D3D12_HEAP_PROPERTIES heap(D3D12_HEAP_TYPE t) { D3D12_HEAP_PROPERTIES p{};p.Type=t;return p; }
D3D12_RESOURCE_DESC tex(UINT w,UINT h,DXGI_FORMAT f,D3D12_RESOURCE_FLAGS flags=D3D12_RESOURCE_FLAG_NONE) {
    D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Width=w;d.Height=h;
    d.DepthOrArraySize=d.MipLevels=1;d.SampleDesc.Count=1;d.Format=f;d.Flags=flags;return d;
}
D3D12_RESOURCE_DESC buf(UINT64 n) { auto d=tex(1,1,DXGI_FORMAT_UNKNOWN);d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;d.Width=n;d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;return d; }
ComPtr<ID3D12Resource> make(ID3D12Device* dev,D3D12_RESOURCE_DESC d,D3D12_HEAP_TYPE t,D3D12_RESOURCE_STATES state) {
    auto hp=heap(t);ComPtr<ID3D12Resource> r;check(dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,state,nullptr,IID_PPV_ARGS(&r)));return r;
}
D3D12_RESOURCE_BARRIER barrier(ID3D12Resource* r,D3D12_RESOURCE_STATES a,D3D12_RESOURCE_STATES b) {
    D3D12_RESOURCE_BARRIER v{};v.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;v.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,a,b};return v;
}
namespace {
stock_dibr::DepthCapture* g_capture{};
uint64_t g_submit_callbacks{};
ID3D12CommandQueue* g_last_submit_queue{};
UINT g_last_submit_count{};
ID3D12CommandQueue* g_opaque_outer_queue{};
uint64_t g_proxy_execute_calls{};
uint64_t g_native_unwrap_queries{};
ID3D12CommandList* g_observer_private_probe{};

// A valid COM interface can have a different address but the same IUnknown.
// The real queue receives native lists; the observer sees equivalent aliases.
// This reproduces a wrapper/tear-off mismatch without asking D3D12 to execute
// a synthetic command-list implementation.
class SubmissionAlias final : public ID3D12CommandList {
    ComPtr<ID3D12CommandList> inner;
    bool opaque;
public:
    explicit SubmissionAlias(ID3D12CommandList* p,bool separate=false):inner{p},opaque{separate} {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out) override {
        if(!opaque)return inner->QueryInterface(iid,out);
        if(!out)return E_POINTER;*out=nullptr;
        if(iid==__uuidof(IUnknown)||iid==__uuidof(ID3D12Object)||
           iid==__uuidof(ID3D12DeviceChild)||iid==__uuidof(ID3D12CommandList)) {
            *out=static_cast<ID3D12CommandList*>(this);AddRef();return S_OK;
        }
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return inner->AddRef(); }
    ULONG STDMETHODCALLTYPE Release() override { return inner->Release(); }
    HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID g,UINT* n,void* p) override { return inner->GetPrivateData(g,n,p); }
    HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID g,UINT n,const void* p) override { return inner->SetPrivateData(g,n,p); }
    HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID g,const IUnknown* p) override { return inner->SetPrivateDataInterface(g,p); }
    HRESULT STDMETHODCALLTYPE SetName(LPCWSTR n) override { return inner->SetName(n); }
    HRESULT STDMETHODCALLTYPE GetDevice(REFIID iid,void** out) override { return inner->GetDevice(iid,out); }
    D3D12_COMMAND_LIST_TYPE STDMETHODCALLTYPE GetType() override { return inner->GetType(); }
};
uint64_t g_alias_callbacks{};
void WINAPI forward_queue_submit(ID3D12CommandQueue* queue,UINT count,ID3D12CommandList* const* lists) {
    ++g_submit_callbacks;
    g_last_submit_queue=queue;
    g_last_submit_count=count;
    if(g_observer_private_probe) {
        auto* private_list=g_observer_private_probe;g_observer_private_probe=nullptr;
        queue->ExecuteCommandLists(1,&private_list);
    }
    if(g_capture) {
        std::vector<std::unique_ptr<SubmissionAlias>> aliases;
        std::vector<ID3D12CommandList*> alias_lists;
        for(UINT i=0;i<count;++i) {
            aliases.push_back(std::make_unique<SubmissionAlias>(lists[i],queue==g_opaque_outer_queue));
            alias_lists.push_back(aliases.back().get());
            require(alias_lists.back()!=lists[i],"alias fixture did not produce a distinct pointer");
        }
        ++g_alias_callbacks;
        g_capture->on_command_lists_executed(queue,count,alias_lists.data());
    }
}

// A genuine COM proxy has an independent public vtable without modifying
// any native runtime object's private implementation layout. Its cached
// native Execute target also reproduces calls that bypass a dummy slot hook.
class QueueProxy final : public ID3D12CommandQueue {
    ComPtr<ID3D12CommandQueue> inner;
    stock_dibr::QueueSubmitHook::Callback native_execute;
    std::atomic<ULONG> references{1};
public:
    bool forward_via_virtual{};
    bool fail_signals{};
    explicit QueueProxy(ID3D12CommandQueue* q):inner{q},
        native_execute{reinterpret_cast<stock_dibr::QueueSubmitHook::Callback>((*(void***)q)[10])} {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid,void** out) override {
        if(!out)return E_POINTER;*out=nullptr;
        if(iid==stock_dibr::StreamlineNativeInterface) {
            ++g_native_unwrap_queries;return inner->QueryInterface(__uuidof(IUnknown),out);
        }
        if(iid==__uuidof(IUnknown)||iid==__uuidof(ID3D12Object)||iid==__uuidof(ID3D12DeviceChild)||
           iid==__uuidof(ID3D12Pageable)||iid==__uuidof(ID3D12CommandQueue)) {
            *out=static_cast<ID3D12CommandQueue*>(this);AddRef();return S_OK;
        }
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++references; }
    ULONG STDMETHODCALLTYPE Release() override {const auto n=--references;if(!n)delete this;return n;}
    HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID g,UINT* n,void* p) override {return inner->GetPrivateData(g,n,p);}
    HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID g,UINT n,const void* p) override {return inner->SetPrivateData(g,n,p);}
    HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID g,const IUnknown* p) override {return inner->SetPrivateDataInterface(g,p);}
    HRESULT STDMETHODCALLTYPE SetName(LPCWSTR n) override {return inner->SetName(n);}
    HRESULT STDMETHODCALLTYPE GetDevice(REFIID iid,void** out) override {return inner->GetDevice(iid,out);}
    void STDMETHODCALLTYPE UpdateTileMappings(ID3D12Resource* r,UINT n,const D3D12_TILED_RESOURCE_COORDINATE* c,
        const D3D12_TILE_REGION_SIZE* z,ID3D12Heap* h,UINT ranges,const D3D12_TILE_RANGE_FLAGS* f,
        const UINT* offsets,const UINT* counts,D3D12_TILE_MAPPING_FLAGS flags) override {
        inner->UpdateTileMappings(r,n,c,z,h,ranges,f,offsets,counts,flags);
    }
    void STDMETHODCALLTYPE CopyTileMappings(ID3D12Resource* d,const D3D12_TILED_RESOURCE_COORDINATE* dc,
        ID3D12Resource* r,const D3D12_TILED_RESOURCE_COORDINATE* rc,const D3D12_TILE_REGION_SIZE* z,
        D3D12_TILE_MAPPING_FLAGS flags) override {inner->CopyTileMappings(d,dc,r,rc,z,flags);}
    void STDMETHODCALLTYPE ExecuteCommandLists(UINT n,ID3D12CommandList* const* lists) override {
        ++g_proxy_execute_calls;
        if(forward_via_virtual)inner->ExecuteCommandLists(n,lists);
        else native_execute(inner.Get(),n,lists);
    }
    void STDMETHODCALLTYPE SetMarker(UINT m,const void* p,UINT n) override {inner->SetMarker(m,p,n);}
    void STDMETHODCALLTYPE BeginEvent(UINT m,const void* p,UINT n) override {inner->BeginEvent(m,p,n);}
    void STDMETHODCALLTYPE EndEvent() override {inner->EndEvent();}
    HRESULT STDMETHODCALLTYPE Signal(ID3D12Fence* f,UINT64 n) override {return fail_signals ? E_FAIL : inner->Signal(f,n);}
    HRESULT STDMETHODCALLTYPE Wait(ID3D12Fence* f,UINT64 n) override {return inner->Wait(f,n);}
    HRESULT STDMETHODCALLTYPE GetTimestampFrequency(UINT64* n) override {return inner->GetTimestampFrequency(n);}
    HRESULT STDMETHODCALLTYPE GetClockCalibration(UINT64* g,UINT64* c) override {return inner->GetClockCalibration(g,c);}
    D3D12_COMMAND_QUEUE_DESC STDMETHODCALLTYPE GetDesc() override {return inner->GetDesc();}
};
}
int main() try {
    std::cout<<std::unitbuf;std::cerr<<std::unitbuf;
    std::cout<<"STAGE create device and proxy queues\n";
    ComPtr<ID3D12Debug> debug; if(SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)))) debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIAdapter> adapter;check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
    ComPtr<ID3D12Device> dev;check(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&dev)));
    D3D12_COMMAND_QUEUE_DESC qd{};qd.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> q,native_queue,other;
    check(dev->CreateCommandQueue(&qd,IID_PPV_ARGS(&native_queue)));
    check(dev->CreateCommandQueue(&qd,IID_PPV_ARGS(&other)));
    auto* proxy=new QueueProxy(native_queue.Get());q.Attach(proxy);
    ComPtr<ID3D12CommandAllocator> allocator;check(dev->CreateCommandAllocator(qd.Type,IID_PPV_ARGS(&allocator)));
    ComPtr<ID3D12GraphicsCommandList> cmd;check(dev->CreateCommandList(0,qd.Type,allocator.Get(),nullptr,IID_PPV_ARGS(&cmd)));
    ComPtr<ID3D12CommandAllocator> probe_allocator;check(dev->CreateCommandAllocator(qd.Type,IID_PPV_ARGS(&probe_allocator)));
    ComPtr<ID3D12GraphicsCommandList> probe;check(dev->CreateCommandList(0,qd.Type,probe_allocator.Get(),nullptr,IID_PPV_ARGS(&probe)));check(probe->Close());
    ComPtr<ID3D12CommandAllocator> private_allocator;check(dev->CreateCommandAllocator(qd.Type,IID_PPV_ARGS(&private_allocator)));
    ComPtr<ID3D12GraphicsCommandList> private_probe;check(dev->CreateCommandList(0,qd.Type,private_allocator.Get(),nullptr,IID_PPV_ARGS(&private_probe)));check(private_probe->Close());
    g_observer_private_probe=private_probe.Get();
    ComPtr<ID3D12Fence> done;check(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&done)));UINT64 signal{};
    auto wait=[&](ID3D12CommandQueue* queue){check(queue->Signal(done.Get(),++signal));HANDLE e=CreateEventW(nullptr,FALSE,FALSE,nullptr);check(done->SetEventOnCompletion(signal,e));require(WaitForSingleObject(e,30000)==WAIT_OBJECT_0,"GPU timeout");CloseHandle(e);};
    constexpr auto read=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    stock_dibr::DepthCapture capture;capture.configure(dev.Get(),q.Get(),64,32,true);g_capture=&capture;
    stock_dibr::QueueSubmitHook queue_submit_hook{&forward_queue_submit};
    std::cout<<"STAGE dummy-only hook coverage\n";
    require(queue_submit_hook.install(other.Get()),"dummy queue submit hook install failed");
    require(queue_submit_hook.size()==1,"dummy queue hook count incorrect");
    ID3D12CommandList* probe_lists[]{probe.Get()};
    q->ExecuteCommandLists(1,probe_lists);wait(q.Get());
    require(g_submit_callbacks==0,"dummy-only hook covered a distinct live queue vtable");
    other->ExecuteCommandLists(1,probe_lists);wait(other.Get());
    require(g_submit_callbacks==1 && g_last_submit_queue==other.Get() && g_last_submit_count==1,
        "dummy queue submit callback was not observed");
    check(probe_allocator->Reset());check(probe->Reset(probe_allocator.Get(),nullptr));check(probe->Close());
    std::cout<<"STAGE register actual proxy queue\n";
    require(queue_submit_hook.install(q.Get()),"live queue submit hook install failed");
    require(g_native_unwrap_queries>0,"documented native-interface discovery was not used");
    require(queue_submit_hook.size()>=2 && queue_submit_hook.size()<=3,"proxy/native queue vtables were not registered");
    q->ExecuteCommandLists(1,probe_lists);wait(q.Get());
    require(g_submit_callbacks==2 && g_last_submit_queue==q.Get() && g_last_submit_count==1,
        "live queue submit callback was not observed");
    check(probe_allocator->Reset());check(probe->Reset(probe_allocator.Get(),nullptr));check(probe->Close());
    std::cout<<"STAGE record depth on delayed producer\n";
    static_assert(DXGI_FORMAT_R32G8X24_TYPELESS==19 && DXGI_FORMAT_R32_TYPELESS==39);
    auto depth=make(dev.Get(),tex(48,24,DXGI_FORMAT_R32G8X24_TYPELESS,D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_DESCRIPTOR_HEAP_DESC dsv_heap_desc{};dsv_heap_desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_DSV;dsv_heap_desc.NumDescriptors=1;
    ComPtr<ID3D12DescriptorHeap> dsv_heap;check(dev->CreateDescriptorHeap(&dsv_heap_desc,IID_PPV_ARGS(&dsv_heap)));
    auto dsv_handle=dsv_heap->GetCPUDescriptorHandleForHeapStart();D3D12_DEPTH_STENCIL_VIEW_DESC dsv_desc{};dsv_desc.Format=DXGI_FORMAT_D32_FLOAT_S8X24_UINT;dsv_desc.ViewDimension=D3D12_DSV_DIMENSION_TEXTURE2D;
    dev->CreateDepthStencilView(depth.Get(),&dsv_desc,dsv_handle);capture.on_depth_stencil_view_created(depth.Get(),&dsv_desc,dsv_handle);
    // A larger valid viewport for the same allocation exists only on an
    // unsubmitted list. It must not change the submitted capture's sample UV.
    ComPtr<ID3D12CommandAllocator> decoy_allocator;check(dev->CreateCommandAllocator(qd.Type,IID_PPV_ARGS(&decoy_allocator)));
    ComPtr<ID3D12GraphicsCommandList> decoy;check(dev->CreateCommandList(0,qd.Type,decoy_allocator.Get(),nullptr,IID_PPV_ARGS(&decoy)));
    D3D12_VIEWPORT decoy_vp{0,0,24,24,0,1};decoy->RSSetViewports(1,&decoy_vp);capture.on_viewports(decoy.Get(),1,&decoy_vp);
    decoy->OMSetRenderTargets(0,nullptr,FALSE,&dsv_handle);capture.on_render_targets(decoy.Get(),0,dsv_handle);check(decoy->Close());
    auto main_binding=[&](){
        D3D12_VIEWPORT vp{0,0,16,16,0,1};cmd->RSSetViewports(1,&vp);capture.on_viewports(cmd.Get(),1,&vp);
        cmd->OMSetRenderTargets(0,nullptr,FALSE,&dsv_handle);capture.on_render_targets(cmd.Get(),0,dsv_handle);
        // A -> B -> A must retain the final A, not deduplicate it against
        // the earlier A and incorrectly publish the intervening rectangle.
        D3D12_VIEWPORT intermediate_vp{0,0,24,24,0,1};cmd->RSSetViewports(1,&intermediate_vp);capture.on_viewports(cmd.Get(),1,&intermediate_vp);
        cmd->RSSetViewports(1,&vp);capture.on_viewports(cmd.Get(),1,&vp);
        // Final barriers are often recorded after unbinding the render pass.
        cmd->OMSetRenderTargets(0,nullptr,FALSE,nullptr);capture.on_render_targets(cmd.Get(),0,{});
    };
    auto color=make(dev.Get(),tex(32,32,DXGI_FORMAT_R8G8B8A8_UNORM),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    auto output=make(dev.Get(),tex(64,32,DXGI_FORMAT_R8G8B8A8_UNORM,D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    std::vector<ComPtr<ID3D12Resource>> uploads;
    auto upload=[&](ID3D12Resource* target,auto pixel){
        auto d=target->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};UINT64 size{};dev->GetCopyableFootprints(&d,0,1,0,&footprint,nullptr,nullptr,&size);
        auto u=make(dev.Get(),buf(size),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);void* p{};check(u->Map(0,nullptr,&p));
        for(UINT y=0;y<d.Height;++y) for(UINT x=0;x<d.Width;++x){auto v=pixel(x,y);std::memcpy(static_cast<char*>(p)+y*footprint.Footprint.RowPitch+x*4,&v,4);}u->Unmap(0,nullptr);
        D3D12_TEXTURE_COPY_LOCATION from{},to{};from.pResource=u.Get();from.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;from.PlacedFootprint=footprint;
        to.pResource=target;to.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);uploads.push_back(u);
    };
    upload(depth.Get(),[](UINT x,UINT){return x<16?.5f:0.f;});
    upload(color.Get(),[](UINT x,UINT y){return (x*8)|((y*8)<<8)|(64<<16);}); // alpha deliberately zero
    auto b=barrier(depth.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_DEPTH_WRITE);cmd->ResourceBarrier(1,&b);
    main_binding();b=barrier(depth.Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE,read);cmd->ResourceBarrier(1,&b);capture.on_post_resource_barriers(cmd.Get(),1,&b);
    b=barrier(color.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);cmd->ResourceBarrier(1,&b);
    require(!capture.acquire(),"unsubmitted capture accepted");check(cmd->Close());ID3D12CommandList* lists[]{cmd.Get()};
    ComPtr<ID3D12Fence> producer_gate;check(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&producer_gate)));
    check(other->Wait(producer_gate.Get(),1));other->ExecuteCommandLists(1,lists);
    require(g_last_submit_queue==other.Get() && g_last_submit_count==1,"alternate queue submit callback missing");
    // Reset on another allocator immediately after Execute. The owned depth
    // copy must survive reset, and acquire must enqueue a consumer GPU wait.
    ComPtr<ID3D12CommandAllocator> post_submit_allocator;check(dev->CreateCommandAllocator(qd.Type,IID_PPV_ARGS(&post_submit_allocator)));
    check(cmd->Reset(post_submit_allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
    std::cout<<"STAGE acquire after reset with GPU handoff\n";
    auto snapshot=capture.acquire();require(snapshot!=nullptr,"alternate submitted depth was lost on immediate list reset");
    require(capture.summary().find("crossQueueUsed=1")!=std::string::npos,"cross-queue wait path not exercised");
    const auto depth_uv=capture.sample_uv();require(std::abs(depth_uv[0]-1.f/3.f)<.0001f && std::abs(depth_uv[1]-2.f/3.f)<.0001f,"published viewport borrowed a larger unsubmitted binding instead of the actual producer rectangle");
    // No CPU wait on other: the production Wait is the ordering dependency
    // that makes the next compute dispatch see this queue's depth pixels.

    std::cout<<"STAGE production shader dispatch\n";
    ComPtr<ID3DBlob> bytecode,error;const auto compiled=D3DCompile(shader,std::strlen(shader),"production DIBR",nullptr,nullptr,"main","cs_5_0",D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&bytecode,&error);
    if(FAILED(compiled)){if(error)std::cerr<<static_cast<const char*>(error->GetBufferPointer());check(compiled);}
    D3D12_DESCRIPTOR_RANGE ranges[2]{};ranges[0]={D3D12_DESCRIPTOR_RANGE_TYPE_SRV,3,0,0,0};ranges[1]={D3D12_DESCRIPTOR_RANGE_TYPE_UAV,3,0,0,0};
    D3D12_ROOT_PARAMETER params[3]{};for(UINT i=0;i<2;++i){params[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;params[i].DescriptorTable={1,&ranges[i]};}
    params[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV;params[2].Descriptor.ShaderRegister=0;
    D3D12_STATIC_SAMPLER_DESC sampler{};sampler.Filter=D3D12_FILTER_MIN_MAG_MIP_LINEAR;sampler.AddressU=sampler.AddressV=sampler.AddressW=D3D12_TEXTURE_ADDRESS_MODE_CLAMP;sampler.MaxLOD=D3D12_FLOAT32_MAX;sampler.ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
    D3D12_ROOT_SIGNATURE_DESC rsd{3,params,1,&sampler,D3D12_ROOT_SIGNATURE_FLAG_NONE};ComPtr<ID3DBlob> rsblob;
    check(D3D12SerializeRootSignature(&rsd,D3D_ROOT_SIGNATURE_VERSION_1,&rsblob,&error));ComPtr<ID3D12RootSignature> rs;check(dev->CreateRootSignature(0,rsblob->GetBufferPointer(),rsblob->GetBufferSize(),IID_PPV_ARGS(&rs)));
    D3D12_COMPUTE_PIPELINE_STATE_DESC pd{};pd.pRootSignature=rs.Get();pd.CS={bytecode->GetBufferPointer(),bytecode->GetBufferSize()};ComPtr<ID3D12PipelineState> pso;check(dev->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pso)));
    std::array<ComPtr<ID3D12PipelineState>,3> visibility_pso;
    const char* visibility_entries[]{"ClearVisibility","ScatterDepth","ScatterSource"};
    for(UINT i=0;i<3;++i) {
        ComPtr<ID3DBlob> code,compile_errors;
        const auto hr=D3DCompile(shader,std::strlen(shader),"production visibility",nullptr,nullptr,visibility_entries[i],"cs_5_0",
            D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&code,&compile_errors);
        if(FAILED(hr)){if(compile_errors)std::cerr<<static_cast<const char*>(compile_errors->GetBufferPointer());check(hr);}
        pd.CS={code->GetBufferPointer(),code->GetBufferSize()};check(dev->CreateComputePipelineState(&pd,IID_PPV_ARGS(&visibility_pso[i])));
    }
    auto visibility_depth=make(dev.Get(),tex(32,32,DXGI_FORMAT_R32_UINT,D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    auto visibility_source=make(dev.Get(),tex(32,32,DXGI_FORMAT_R32_UINT,D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hd.NumDescriptors=6;hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> descriptors;check(dev->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&descriptors)));const auto stride=dev->GetDescriptorHandleIncrementSize(hd.Type);auto cpu=descriptors->GetCPUDescriptorHandleForHeapStart();
    D3D12_SHADER_RESOURCE_VIEW_DESC srv{};srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;srv.Texture2D.MipLevels=1;srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    srv.Format=DXGI_FORMAT_R8G8B8A8_UNORM;dev->CreateShaderResourceView(color.Get(),&srv,cpu);cpu.ptr+=stride;
    srv.Format=DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS;dev->CreateShaderResourceView(snapshot.Get(),&srv,cpu);cpu.ptr+=stride;
    srv.Format=DXGI_FORMAT_R8G8B8A8_UNORM;dev->CreateShaderResourceView(color.Get(),&srv,cpu);cpu.ptr+=stride;
    D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;uav.Format=DXGI_FORMAT_R8G8B8A8_UNORM;dev->CreateUnorderedAccessView(output.Get(),nullptr,&uav,cpu);
    uav.Format=DXGI_FORMAT_R32_UINT;cpu.ptr+=stride;dev->CreateUnorderedAccessView(visibility_depth.Get(),nullptr,&uav,cpu);
    cpu.ptr+=stride;dev->CreateUnorderedAccessView(visibility_source.Get(),nullptr,&uav,cpu);
    auto cb=make(dev.Get(),buf(256),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);TestConstants constants{};
    constants.output_width=64;constants.output_height=constants.source_eye_width=constants.source_height=32;
    constants.depth_width=48;constants.depth_height=24;std::memcpy(constants.depth_uv_scale_bias,depth_uv.data(),sizeof(constants.depth_uv_scale_bias));constants.depth_is_double_wide=1;constants.reversed_depth=1;
    constants.use_true_reprojection=1;constants.true_reprojection_strength=1;
    constants.source_to_right[0]=constants.source_to_right[5]=constants.source_to_right[10]=constants.source_to_right[15]=1;
    constants.source_to_right[8]=-.5f;void* mapped{};check(cb->Map(0,nullptr,&mapped));std::memcpy(mapped,&constants,256);cb->Unmap(0,nullptr);
    ID3D12DescriptorHeap* heaps[]{descriptors.Get()};cmd->SetDescriptorHeaps(1,heaps);cmd->SetComputeRootSignature(rs.Get());cmd->SetPipelineState(pso.Get());auto gpu=descriptors->GetGPUDescriptorHandleForHeapStart();cmd->SetComputeRootDescriptorTable(0,gpu);gpu.ptr+=stride*3;cmd->SetComputeRootDescriptorTable(1,gpu);cmd->SetComputeRootConstantBufferView(2,cb->GetGPUVirtualAddress());cmd->Dispatch(8,4,1);
    b=barrier(output.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);cmd->ResourceBarrier(1,&b);
    auto od=output->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};UINT64 bytes{};dev->GetCopyableFootprints(&od,0,1,0,&footprint,nullptr,nullptr,&bytes);
    auto readback=make(dev.Get(),buf(bytes),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_TEXTURE_COPY_LOCATION from{},to{};from.pResource=output.Get();from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;to.pResource=readback.Get();to.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;to.PlacedFootprint=footprint;cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    check(cmd->Close());q->ExecuteCommandLists(1,lists);capture.finish_frame();check(producer_gate->Signal(1));wait(q.Get());
    check(readback->Map(0,nullptr,&mapped));auto pixel=[&](UINT x,UINT y){return static_cast<uint8_t*>(mapped)+y*footprint.Footprint.RowPitch+x*4;};
    unsigned different{};for(UINT y=0;y<32;++y)for(UINT x=0;x<32;++x){require(pixel(x,y)[0]==x*8,"left eye color changed");require(pixel(x,y)[3]==255 && pixel(x+32,y)[3]==255,"scene alpha not opaque");different+=pixel(x,y)[0]!=pixel(x+32,y)[0];}
    require(different>512,"production shader did not create distinct L/R images");
    require(pixel(56,16)[0]>pixel(24,16)[0]+15,"packed left depth not used on right side of image");readback->Unmap(0,nullptr);
    require(!capture.acquire(),"stale depth reused in next interval");

    std::cout<<"STAGE monotonic strength control pixel effect\n";
    // A constant-depth plane and linear red ramp give an exact displacement
    // oracle away from the image edge: strength 1 moves four source pixels.
    int previous_red=-1;
    for (const float strength : {0.f, .5f, 1.f, 1.5f, 2.f}) {
        check(post_submit_allocator->Reset());check(cmd->Reset(post_submit_allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
        constants.true_reprojection_strength=strength;check(cb->Map(0,nullptr,&mapped));std::memcpy(mapped,&constants,256);cb->Unmap(0,nullptr);
        b=barrier(output.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);cmd->ResourceBarrier(1,&b);
        cmd->SetDescriptorHeaps(1,heaps);cmd->SetComputeRootSignature(rs.Get());cmd->SetPipelineState(pso.Get());
        gpu=descriptors->GetGPUDescriptorHandleForHeapStart();cmd->SetComputeRootDescriptorTable(0,gpu);gpu.ptr+=stride*3;cmd->SetComputeRootDescriptorTable(1,gpu);cmd->SetComputeRootConstantBufferView(2,cb->GetGPUVirtualAddress());cmd->Dispatch(8,4,1);
        b=barrier(output.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);cmd->ResourceBarrier(1,&b);
        from.pResource=output.Get();to.pResource=readback.Get();to.PlacedFootprint=footprint;cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
        check(cmd->Close());q->ExecuteCommandLists(1,lists);wait(q.Get());
        check(readback->Map(0,nullptr,&mapped));
        const int red=pixel(40,16)[0];
        require(std::abs(red-int(64+32*strength))<=1,"strength does not scale known plane displacement linearly");
        require(red>previous_red,"strength above 1 reverses or collapses stereo");previous_red=red;
        if(strength==0) for(UINT y=0;y<32;++y)for(UINT x=0;x<32;++x)
            require(pixel(x,y)[0]==pixel(x+32,y)[0],"strength zero is not neutral");
        readback->Unmap(0,nullptr);
    }


    std::cout<<"STAGE R6 production inspector, sampling, repair and preserve controls\n";
    // Exercise the production bytecode directly with a padded producer rect.
    // Poison outside that rect makes accidental allocation-wide loads visible.
    auto fixture_depth=make(dev.Get(),tex(48,24,DXGI_FORMAT_R32_FLOAT),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    auto fixture_ui=make(dev.Get(),tex(32,32,DXGI_FORMAT_R8G8B8A8_UNORM),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    auto fixture_cpu=descriptors->GetCPUDescriptorHandleForHeapStart();fixture_cpu.ptr+=stride;
    srv.Format=DXGI_FORMAT_R32_FLOAT;dev->CreateShaderResourceView(fixture_depth.Get(),&srv,fixture_cpu);
    fixture_cpu.ptr+=stride;srv.Format=DXGI_FORMAT_R8G8B8A8_UNORM;dev->CreateShaderResourceView(fixture_ui.Get(),&srv,fixture_cpu);
    bool fixture_ready=false;
    using Image=std::vector<uint8_t>;
    auto fixture=[&](auto value) {
        std::vector<float> values(48*24,.99f);
        for(UINT y=0;y<16;++y)for(UINT x=0;x<16;++x)values[(y+4)*48+x+8]=value(x,y);
        return values;
    };
    auto run_fixture=[&](const TestConstants& c,const std::vector<float>* values=nullptr) {
        check(post_submit_allocator->Reset());check(cmd->Reset(post_submit_allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
        if(values) {
            if(fixture_ready){b=barrier(fixture_depth.Get(),D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_DEST);cmd->ResourceBarrier(1,&b);}
            upload(fixture_depth.Get(),[&](UINT x,UINT y){return (*values)[y*48+x];});
            b=barrier(fixture_depth.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);cmd->ResourceBarrier(1,&b);
        }
        if(!fixture_ready) {
            require(values!=nullptr,"first R6 dispatch needs a depth fixture");
            upload(fixture_ui.Get(),[](UINT x,UINT){return x<16?0xff000000u:0u;});
            b=barrier(fixture_ui.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);cmd->ResourceBarrier(1,&b);
            fixture_ready=true;
        }
        check(cb->Map(0,nullptr,&mapped));std::memcpy(mapped,&c,256);cb->Unmap(0,nullptr);
        b=barrier(output.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);cmd->ResourceBarrier(1,&b);
        cmd->SetDescriptorHeaps(1,heaps);cmd->SetComputeRootSignature(rs.Get());cmd->SetPipelineState(pso.Get());
        gpu=descriptors->GetGPUDescriptorHandleForHeapStart();cmd->SetComputeRootDescriptorTable(0,gpu);gpu.ptr+=stride*3;cmd->SetComputeRootDescriptorTable(1,gpu);cmd->SetComputeRootConstantBufferView(2,cb->GetGPUVirtualAddress());
        if(c.reconstruction_mode!=0 && c.use_true_reprojection && (c.inspector_view==0 || c.inspector_view==6)) {
            D3D12_RESOURCE_BARRIER order{};order.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;
            for(auto& auxiliary:visibility_pso){cmd->SetPipelineState(auxiliary.Get());cmd->Dispatch(4,4,1);cmd->ResourceBarrier(1,&order);}
            cmd->SetPipelineState(pso.Get());
        }
        cmd->Dispatch(8,4,1);
        b=barrier(output.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);cmd->ResourceBarrier(1,&b);
        from.pResource=output.Get();to.pResource=readback.Get();to.PlacedFootprint=footprint;cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
        check(cmd->Close());q->ExecuteCommandLists(1,lists);wait(q.Get());
        Image result(64*32*4);check(readback->Map(0,nullptr,&mapped));
        for(UINT y=0;y<32;++y)std::memcpy(result.data()+y*64*4,pixel(0,y),64*4);
        readback->Unmap(0,nullptr);return result;
    };
    auto channel=[](const Image& image,UINT x,UINT y,UINT c=0){return int(image[(y*64+x)*4+c]);};
    auto binocular=[&](const Image& image) {
        for(UINT y=0;y<32;++y)for(UINT x=0;x<32;++x) {
            for(UINT c=0;c<4;++c)require(channel(image,x,y,c)==channel(image,x+32,y,c),"inspector differs between eyes");
            require(channel(image,x,y,3)==255,"inspector alpha is not opaque");
        }
    };
    TestConstants r6=constants;r6.true_reprojection_strength=1;
    r6.depth_uv_scale_bias[0]=16.f/48;r6.depth_uv_scale_bias[1]=16.f/24;
    r6.depth_uv_scale_bias[2]=8.f/48;r6.depth_uv_scale_bias[3]=4.f/24;
    auto plane=fixture([](UINT,UINT){return .5f;});
    const auto legacy_plane=run_fixture(r6,&plane);
    r6.depth_scale=1;require(run_fixture(r6)==legacy_plane,"calibration 1 is not neutral against zero-initialized R5 controls");
    r6.depth_display_gain=8;require(run_fixture(r6)==legacy_plane,"display exposure changed normal stereo");r6.depth_display_gain=0;
    r6.depth_scale=2;auto scaled=run_fixture(r6);
    require(std::abs(channel(scaled,40,16)-128)<=1,"calibration 2 did not double reversed near-device depth displacement");
    r6.depth_scale=1;r6.reversed_depth=0;
    auto conventional=fixture([](UINT,UINT){return .75f;});
    r6.depth_scale=2;auto forward_scaled=run_fixture(r6,&conventional);
    require(std::abs(channel(forward_scaled,40,16)-96)<=1,"calibration scaled forward device Z instead of near-device depth");
    r6.reversed_depth=1;r6.depth_scale=1;
    auto boundary=fixture([](UINT x,UINT){return x<8?.25f:.75f;});
    r6.use_true_reprojection=0;r6.disparity_pixels=8;r6.legacy_depth_curve=1;r6.legacy_near_depth_cap=1;
    r6.depth_sampling_mode=0;auto linear_boundary=run_fixture(r6,&boundary);
    r6.depth_sampling_mode=1;auto point_boundary=run_fixture(r6);
    r6.depth_sampling_mode=2;r6.depth_repair_threshold=.01f;auto edge_boundary=run_fixture(r6);
    require(std::abs(channel(point_boundary,47,16)-136)<=1,"point depth did not select the producer texel at a silhouette");
    require(std::abs(channel(linear_boundary,47,16)-144)<=1,"legacy linear depth boundary oracle changed");
    require(edge_boundary==point_boundary,"edge-aware depth interpolated across a silhouette");
    auto ramp=fixture([](UINT x,UINT){return .2f+.01f*x;});
    r6.depth_sampling_mode=0;auto coherent_linear=run_fixture(r6,&ramp);
    r6.depth_sampling_mode=2;r6.depth_repair_threshold=.02f;
    require(run_fixture(r6)==coherent_linear,"edge-aware depth did not retain bilinear sampling on a coherent ramp");

    r6.inspector_view=1;r6.depth_scale=3;r6.depth_repair_mode=1;r6.depth_display_gain=8;
    auto raw=run_fixture(r6,&boundary);binocular(raw);
    require(std::abs(channel(raw,15,16)-64)<=1 && std::abs(channel(raw,16,16)-191)<=1,"raw inspector did not use uncalibrated point samples");
    for(UINT y=0;y<32;++y)for(UINT x=0;x<32;++x)
        require(std::abs(channel(raw,x,y)-(x<16?64:191))<=1,"raw inspector sampled poison outside the padded producer rectangle");
    auto raw_controls=r6;raw_controls.true_reprojection_strength=2;
    raw_controls.enable_depth_edge_stabilization=raw_controls.enable_spatial_repair=1;
    raw_controls.enable_ui_edge_guard=raw_controls.enable_ui_footprint_reprojection=1;
    require(run_fixture(raw_controls)==raw,"raw inspector changed under legacy stereo controls");
    r6.depth_scale=1;r6.depth_repair_mode=0;r6.depth_display_gain=-8;r6.depth_sampling_mode=0;
    require(run_fixture(r6)==raw,"raw inspector changed with sampling, calibration, repair or exposure");
    r6.inspector_view=2;r6.depth_display_gain=0;auto readable=run_fixture(r6);binocular(readable);
    // Inspector 2 maps the raw point samples, independent of normal-pass filtering.
    r6.depth_sampling_mode=1;readable=run_fixture(r6);
    require(std::abs(channel(readable,8,16)-int(std::lround(255*std::log2(1.25))))<=1,"readable inverse depth exposure-zero formula mismatch");
    r6.depth_display_gain=2;auto exposed=run_fixture(r6);
    require(std::abs(channel(exposed,8,16)-int(std::lround(255*std::log2(2.)/std::log2(5.))))<=1,"readable inverse depth exposure formula mismatch");
    require(exposed!=readable,"readable depth exposure has no pixel effect");
    for(UINT mode=2;mode<=5;++mode){r6.inspector_view=mode;binocular(run_fixture(r6));}
    r6.inspector_view=3;auto edges=run_fixture(r6);
    require(channel(edges,8,16)==0 && channel(edges,14,16)==255,"edge inspector did not distinguish a flat region from a silhouette");
    r6.inspector_view=5;r6.use_true_reprojection=1;r6.true_reprojection_strength=2;
    auto confidence=run_fixture(r6,&plane);binocular(confidence);
    require(channel(confidence,8,16)==0 && channel(confidence,8,16,1)==255 &&
        channel(confidence,31,16)==255 && channel(confidence,31,16,1)==0,
        "confidence inspector did not distinguish a converged inverse solve from source clamping");
    r6.use_true_reprojection=0;r6.true_reprojection_strength=1;

    // A single bad texel is repairable; a one-texel-wide foreground strand
    // and a silhouette have incoherent neighbors and must survive intact.
    r6.inspector_view=0;r6.depth_display_gain=0;r6.depth_sampling_mode=1;r6.depth_repair_threshold=.05f;
    auto outlier=fixture([](UINT x,UINT y){return x==7&&y==8?.9f:.25f;});
    r6.depth_repair_mode=0;auto dirty=run_fixture(r6,&outlier);
    r6.depth_repair_mode=1;auto repaired=run_fixture(r6);
    auto clean=fixture([](UINT,UINT){return .25f;});auto clean_image=run_fixture(r6,&clean);
    require(repaired==clean_image && dirty!=clean_image,"isolated coherent-neighborhood depth outlier was not repaired");
    auto strand=fixture([](UINT x,UINT){return x==7?.9f:.25f;});
    r6.depth_repair_mode=0;auto strand_before=run_fixture(r6,&strand);r6.depth_repair_mode=1;
    require(run_fixture(r6)==strand_before,"depth repair erased a thin foreground strand");
    r6.depth_repair_mode=0;auto silhouette_before=run_fixture(r6,&boundary);r6.depth_repair_mode=1;
    require(run_fixture(r6)==silhouette_before,"depth repair moved a silhouette");
    r6.inspector_view=1;auto raw_clean=run_fixture(r6,&outlier);r6.depth_repair_mode=0;
    require(run_fixture(r6)==raw_clean && channel(raw_clean,14,16)>220,"raw inspector concealed a repairable outlier");

    r6.inspector_view=0;r6.use_true_reprojection=1;r6.true_reprojection_strength=2;r6.depth_repair_mode=0;
    r6.preserve_stereo_strength=1;auto preserved=run_fixture(r6,&plane);
    require(std::abs(channel(preserved,40,16)-128)<=1,"preserve at 2x failed the known-plane displacement oracle");
    r6.enable_depth_edge_stabilization=1;r6.depth_edge_threshold=.0001f;r6.depth_edge_stabilization_strength=1;
    r6.enable_spatial_repair=1;r6.repair_residual_pixels=0;r6.repair_depth_threshold=.0001f;
    r6.enable_ui_edge_guard=1;r6.ui_edge_guard_strength=1;
    r6.enable_ui_footprint_reprojection=1;r6.ui_footprint_reprojection_strength=0;
    require(run_fixture(r6)==preserved,"preserve failed to bypass legacy local strength/color modifications");
    r6.preserve_stereo_strength=0;require(run_fixture(r6)!=preserved,"legacy flattening fixture did not activate any local controls");
    // The optional visibility preflight can fail while the R6 pipeline remains
    // usable. Its absent scratch resources are represented by typed null UAVs.
    const auto fallback_reference=run_fixture(r6,&plane);
    auto optional_cpu=descriptors->GetCPUDescriptorHandleForHeapStart();optional_cpu.ptr+=stride*4;
    D3D12_UNORDERED_ACCESS_VIEW_DESC optional_uav{};optional_uav.Format=DXGI_FORMAT_R32_UINT;optional_uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
    dev->CreateUnorderedAccessView(nullptr,nullptr,&optional_uav,optional_cpu);optional_cpu.ptr+=stride;
    dev->CreateUnorderedAccessView(nullptr,nullptr,&optional_uav,optional_cpu);
    require(run_fixture(r6)==fallback_reference,"legacy fallback changed with absent optional visibility scratch UAVs");
    optional_cpu=descriptors->GetCPUDescriptorHandleForHeapStart();optional_cpu.ptr+=stride*4;
    dev->CreateUnorderedAccessView(visibility_depth.Get(),nullptr,&optional_uav,optional_cpu);optional_cpu.ptr+=stride;
    dev->CreateUnorderedAccessView(visibility_source.Get(),nullptr,&optional_uav,optional_cpu);
    std::cout<<"STAGE R7 production forward visibility analytic scenes\n";
    // Inspect the actual atomic buffers as well as resolved color. This makes
    // the occlusion oracle independent of the shader's color reconstruction.
    auto read_visibility=[&](ID3D12Resource* resource) {
        const auto desc=resource->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT64 size{};
        dev->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&size);
        auto result=make(dev.Get(),buf(size),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
        check(post_submit_allocator->Reset());check(cmd->Reset(post_submit_allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
        auto transition=barrier(resource,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);cmd->ResourceBarrier(1,&transition);
        D3D12_TEXTURE_COPY_LOCATION source{},destination{};source.pResource=resource;source.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        destination.pResource=result.Get();destination.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;destination.PlacedFootprint=fp;
        cmd->CopyTextureRegion(&destination,0,0,0,&source,nullptr);
        transition=barrier(resource,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);cmd->ResourceBarrier(1,&transition);
        check(cmd->Close());q->ExecuteCommandLists(1,lists);wait(q.Get());
        void* data{};check(result->Map(0,nullptr,&data));std::vector<uint32_t> values(32*32);
        for(UINT y=0;y<32;++y)std::memcpy(values.data()+y*32,static_cast<char*>(data)+y*fp.Footprint.RowPitch,32*sizeof(uint32_t));
        result->Unmap(0,nullptr);return values;
    };
    TestConstants r7=constants;r7.reconstruction_mode=1;r7.preserve_stereo_strength=1;r7.true_reprojection_strength=1;
    r7.depth_scale=1;r7.depth_sampling_mode=1;r7.depth_repair_mode=0;
    r7.visibility_fill_radius=16;r7.visibility_depth_tolerance=.03f;
    std::memcpy(r7.depth_uv_scale_bias,r6.depth_uv_scale_bias,sizeof(r7.depth_uv_scale_bias));
    // Analytic projection: x' = x - 8*near_depth pixels, y'=y.
    // The character occupies source x16..23, y8..23; background continues
    // on either side. A slope in y makes this more than a constant-plane test.
    auto character=fixture([](UINT x,UINT y){return x>=8&&x<12&&y>=4&&y<12?.75f+.005f*(float(y)-8):.25f;});
    auto verify_winners=[&](const TestConstants& c,const std::vector<float>& depths) {
        const auto indices=read_visibility(visibility_source.Get());
        const auto keys=read_visibility(visibility_depth.Get());
        std::vector<uint32_t> expected(32*32,UINT32_MAX);std::vector<float> closest(32*32,-1.f);
        for(UINT y=0;y<32;++y)for(UINT x=0;x<32;++x) {
            const float z=depths[(y/2+4)*48+x/2+8];
            const float point[]{(float(x)+.5f)/16.f-1.f,1.f-(float(y)+.5f)/16.f,z,1.f};
            float projected[4]{};for(UINT row=0;row<4;++row)for(UINT column=0;column<4;++column)
                projected[row]+=c.source_to_right[column*4+row]*point[column];
            if(!std::isfinite(z)||z<0||z>1||!std::isfinite(projected[3])||projected[3]<=1e-6f)continue;
            const float target_depth=projected[2]/projected[3];
            const float tx=(float(x)+.5f)+c.true_reprojection_strength*((projected[0]/projected[3]+1.f)*16.f-(float(x)+.5f));
            const float ty=(float(y)+.5f)+c.true_reprojection_strength*((1.f-projected[1]/projected[3])*16.f-(float(y)+.5f));
            if(!std::isfinite(target_depth)||target_depth<0||target_depth>1||!std::isfinite(tx)||!std::isfinite(ty)||tx<0||tx>=32||ty<0||ty>=32)continue;
            const UINT target=UINT(std::floor(ty))*32+UINT(std::floor(tx));
            const float near_value=c.reversed_depth?target_depth:1.f-target_depth;
            const UINT index=y*32+x;
            if(near_value>closest[target] || (near_value==closest[target] && index<expected[target])){closest[target]=near_value;expected[target]=index;}
        }
        for(UINT i=0;i<32*32;++i) {
            require(indices[i]==expected[i],"R7 forward source-index oracle failed (projection, target-Z ordering or deterministic tie)");
            float actual_depth{};std::memcpy(&actual_depth,&keys[i],sizeof(actual_depth));
            require(expected[i]==UINT32_MAX?keys[i]==0:std::abs(actual_depth-closest[i])<.000001f,"R7 forward target-depth key oracle failed");
        }
        return indices;
    };
    auto character_image=run_fixture(r7,&character);auto character_indices=verify_winners(r7,character);
    require(character_indices[16*32+12]==16*32+18,"slanted foreground did not occlude the overlapping background");
    // Character moves six pixels and background moves two. x18..21 is newly
    // exposed, so only the right visible background (source x24) may fill it.
    for(UINT x=18;x<=21;++x)require(channel(character_image,x+32,16)==192,
        (std::string("disocclusion background boundary moved: x=")+std::to_string(x)+", red="+std::to_string(channel(character_image,x+32,16))).c_str());
    for(UINT y=0;y<32;++y)for(UINT x=0;x<32;++x) {
        require(channel(character_image,x,y)==int(x*8),"R7 changed the source eye");
        require(channel(character_image,x,y,3)==255 && channel(character_image,x+32,y,3)==255,"R7 alpha is not opaque");
    }
    // Conventional Z with the same near-oriented x displacement must produce
    // exactly the same visibility and color as reversed Z.
    auto conventional_character=character;for(UINT y=4;y<20;++y)for(UINT x=8;x<24;++x)conventional_character[y*48+x]=1.f-character[y*48+x];
    r7.reversed_depth=0;r7.source_to_right[8]=.5f;r7.source_to_right[12]=-.5f;
    auto conventional_image=run_fixture(r7,&conventional_character);verify_winners(r7,conventional_character);
    for(size_t i=0;i<character_image.size();++i)require(std::abs(int(conventional_image[i])-int(character_image[i]))<=1,"normal/reversed Z changed the same geometric scene");
    // Flip only target Z while preserving the source projection. Source-near
    // becomes target-far: source Z ordering would select the wrong surface.
    r7.reversed_depth=1;r7.source_to_right[8]=-.5f;r7.source_to_right[12]=0;
    r7.source_to_right[10]=-1;r7.source_to_right[14]=1;
    run_fixture(r7,&character);auto flipped_indices=verify_winners(r7,character);
    require(flipped_indices[16*32+12]==16*32+14,"occlusion used source Z instead of projected target Z");
    r7.source_to_right[10]=1;r7.source_to_right[14]=0;
    // A 4.25-pixel translation on a coherent plane has an exact linear-ramp
    // color oracle. Refinement must recover fractional sampling, not stair steps.
    auto fractional_plane=fixture([](UINT,UINT){return .53125f;});
    auto fractional=run_fixture(r7,&fractional_plane);verify_winners(r7,fractional_plane);
    for(UINT x=2;x<24;++x)require(std::abs(channel(fractional,x+32,16)-(int(x*8)+34))<=1,"fractional-plane forward reconstruction lost subpixel displacement");
    // Far reversed-Z zero is valid and must not be confused with clear key 0.
    auto far_plane=fixture([](UINT,UINT){return 0.f;});
    auto far_image=run_fixture(r7,&far_plane);auto far_indices=verify_winners(r7,far_plane);
    for(UINT i=0;i<32*32;++i)require(far_indices[i]==i,"valid zero-depth far plane became uncovered");
    for(UINT x=0;x<32;++x)require(channel(far_image,x+32,16)==int(x*8),"zero-depth far plane lost its source pixels");
    auto normal_far=fixture([](UINT,UINT){return 1.f;});r7.reversed_depth=0;r7.source_to_right[8]=.5f;r7.source_to_right[12]=-.5f;
    run_fixture(r7,&normal_far);verify_winners(r7,normal_far);
    r7.reversed_depth=1;r7.source_to_right[8]=-.5f;r7.source_to_right[12]=0;
    // Compression makes multiple equal-depth texels land in each target pixel.
    // Source index must deterministically choose the first, independent of GPU order.
    r7.source_to_right[0]=.5f;run_fixture(r7,&plane);verify_winners(r7,plane);r7.source_to_right[0]=1;
    // Inspector colors encode direct coverage, verified fill and unresolved
    // pixels explicitly. Every visualization is binocular and opaque.
    r7.inspector_view=6;auto coverage=run_fixture(r7,&character);binocular(coverage);
    require(channel(coverage,12,16,1)>180 && channel(coverage,12,16,2)<40,"coverage inspector direct sample is not green");
    require(channel(coverage,19,16,0)==0 && channel(coverage,19,16,2)==255,"coverage inspector verified background fill is not cyan");
    r7.visibility_fill_radius=0;auto unfilled=run_fixture(r7);binocular(unfilled);
    require(channel(unfilled,19,16,0)==255 && channel(unfilled,19,16,1)<20,"coverage inspector unresolved pixel is not red");
    r7.visibility_fill_radius=16;
    auto invalid_projection=[&](const TestConstants& invalid) {
        const auto image=run_fixture(invalid,&plane);const auto indices=verify_winners(invalid,plane);binocular(image);
        for(UINT i=0;i<32*32;++i)require(indices[i]==UINT32_MAX,"invalid projection emitted a phantom covered source");
        require(channel(image,16,16,0)==255 && channel(image,16,16,1)<20,"invalid projection was not visibly unresolved");
    };
    auto invalid=r7;invalid.source_to_right[15]=-1;invalid_projection(invalid);
    invalid=r7;invalid.source_to_right[0]=std::numeric_limits<float>::quiet_NaN();invalid_projection(invalid);
    invalid=r7;invalid.source_to_right[14]=2;invalid_projection(invalid);
    // Report this deliberately as CPU-observed WARP dispatch/readback latency;
    // it is not a physical GPU/headset performance measurement.
    r7.inspector_view=0;const auto timing_start=std::chrono::steady_clock::now();
    for(UINT iteration=0;iteration<5;++iteration)run_fixture(r7,iteration==0?&character:nullptr);
    const auto warp_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-timing_start).count()/5.;
    std::cout<<"R7 WARP CPU-observed dispatch/wait/readback mean (5 frames): "<<warp_ms<<" ms (not hardware GPU timing)\n";
    // Restore capture SRVs before the queue/capture lifetime regressions below.
    fixture_cpu=descriptors->GetCPUDescriptorHandleForHeapStart();fixture_cpu.ptr+=stride;
    srv.Format=DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS;dev->CreateShaderResourceView(snapshot.Get(),&srv,fixture_cpu);
    fixture_cpu.ptr+=stride;srv.Format=DXGI_FORMAT_R8G8B8A8_UNORM;dev->CreateShaderResourceView(color.Get(),&srv,fixture_cpu);

    std::cout<<"STAGE next-frame depth and stale rejection\n";
    // This time the outer proxy callback sees opaque list wrappers with a
    // distinct IUnknown. The native inner callback must still publish exactly
    // once, and the output must contain this frame's new depth pixels.
    proxy->forward_via_virtual=true;g_opaque_outer_queue=q.Get();
    // A later frame must carry new pixels, not a frozen successful snapshot.
    check(post_submit_allocator->Reset());check(cmd->Reset(post_submit_allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
    b=barrier(depth.Get(),read,D3D12_RESOURCE_STATE_COPY_DEST);cmd->ResourceBarrier(1,&b);
    upload(depth.Get(),[](UINT x,UINT){return x<16?.25f:.75f;});
    b=barrier(depth.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_DEPTH_WRITE);cmd->ResourceBarrier(1,&b);
    main_binding();b=barrier(depth.Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE,read);cmd->ResourceBarrier(1,&b);capture.on_post_resource_barriers(cmd.Get(),1,&b);
    check(cmd->Close());q->ExecuteCommandLists(1,lists);
    snapshot=capture.acquire();require(snapshot!=nullptr,"native inner queue callback was hidden by opaque outer wrappers");
    require(capture.summary().find(" submitted=2 ")!=std::string::npos,"nested callbacks published a capture twice");
    wait(q.Get());
    check(post_submit_allocator->Reset());check(cmd->Reset(post_submit_allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
    auto sd=snapshot->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT df{};UINT64 db{};dev->GetCopyableFootprints(&sd,0,1,0,&df,nullptr,nullptr,&db);
    auto depth_readback=make(dev.Get(),buf(db),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
    b=barrier(snapshot.Get(),read,D3D12_RESOURCE_STATE_COPY_SOURCE);cmd->ResourceBarrier(1,&b);
    from.pResource=snapshot.Get();to.pResource=depth_readback.Get();to.PlacedFootprint=df;cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    b=barrier(snapshot.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,read);cmd->ResourceBarrier(1,&b);
    check(cmd->Close());q->ExecuteCommandLists(1,lists);capture.finish_frame();wait(q.Get());
    check(depth_readback->Map(0,nullptr,&mapped));float value{};std::memcpy(&value,mapped,4);require(value==.25f,"depth froze at an earlier frame");depth_readback->Unmap(0,nullptr);
    require(!capture.acquire(),"updated depth reused after interval ended");

    // A reset/discard must never publish a recording that was not executed.
    check(post_submit_allocator->Reset());check(cmd->Reset(post_submit_allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
    b=barrier(depth.Get(),read,D3D12_RESOURCE_STATE_DEPTH_WRITE);cmd->ResourceBarrier(1,&b);
    main_binding();b=barrier(depth.Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE,read);cmd->ResourceBarrier(1,&b);capture.on_post_resource_barriers(cmd.Get(),1,&b);
    check(cmd->Close());check(post_submit_allocator->Reset());check(cmd->Reset(post_submit_allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());require(!capture.acquire(),"discarded list was published");check(cmd->Close());
    std::cout<<"STAGE wrong producer and late binding rejection\n";
    // A binding executed on another producer queue cannot validate a later
    // capture-only list on q. This deliberately constructs a matching shape
    // with incorrect queue provenance and must remain rejected.
    check(post_submit_allocator->Reset());check(cmd->Reset(post_submit_allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
    b=barrier(depth.Get(),read,D3D12_RESOURCE_STATE_DEPTH_WRITE);cmd->ResourceBarrier(1,&b);main_binding();
    b=barrier(depth.Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE,read);cmd->ResourceBarrier(1,&b);
    check(cmd->Close());other->ExecuteCommandLists(1,lists);wait(other.Get());
    check(post_submit_allocator->Reset());check(cmd->Reset(post_submit_allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
    b=barrier(depth.Get(),read,D3D12_RESOURCE_STATE_DEPTH_WRITE);cmd->ResourceBarrier(1,&b);
    b=barrier(depth.Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE,read);cmd->ResourceBarrier(1,&b);capture.on_post_resource_barriers(cmd.Get(),1,&b);
    check(cmd->Close());q->ExecuteCommandLists(1,lists);wait(q.Get());
    require(!capture.acquire(),"capture borrowed binding proof from a different producer queue");
    // Nor may a bind later in the very same recording validate an earlier
    // capture. The previously executed other-queue proof permits recording,
    // but neither that proof nor this late local bind may publish the slot.
    check(post_submit_allocator->Reset());check(cmd->Reset(post_submit_allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
    b=barrier(depth.Get(),read,D3D12_RESOURCE_STATE_DEPTH_WRITE);cmd->ResourceBarrier(1,&b);
    b=barrier(depth.Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE,read);cmd->ResourceBarrier(1,&b);capture.on_post_resource_barriers(cmd.Get(),1,&b);
    b=barrier(depth.Get(),read,D3D12_RESOURCE_STATE_DEPTH_WRITE);cmd->ResourceBarrier(1,&b);main_binding();
    b=barrier(depth.Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE,read);cmd->ResourceBarrier(1,&b);
    check(cmd->Close());q->ExecuteCommandLists(1,lists);wait(q.Get());
    require(!capture.acquire(),"late bind on same list validated an earlier capture");
    require(g_alias_callbacks>0,"COM command-list aliases were not tested");
    require(queue_submit_hook.size()>=2 && queue_submit_hook.size()<=3,"queue hook registry lost an installed queue");
    std::cout<<"STAGE actual depth-candidate selection, quota isolation and generation reset\n";
    stock_dibr::DepthCapture selection_capture;
    auto second_depth=make(dev.Get(),tex(32,32,DXGI_FORMAT_R32_TYPELESS,D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    auto selection_heap_desc=dsv_heap_desc;selection_heap_desc.NumDescriptors=2;
    ComPtr<ID3D12DescriptorHeap> selection_heap;check(dev->CreateDescriptorHeap(&selection_heap_desc,IID_PPV_ARGS(&selection_heap)));
    const auto selection_dsv_stride=dev->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_DSV);
    auto first_dsv=selection_heap->GetCPUDescriptorHandleForHeapStart();auto second_dsv=first_dsv;second_dsv.ptr+=selection_dsv_stride;
    auto second_desc=dsv_desc;second_desc.Format=DXGI_FORMAT_D32_FLOAT;
    dev->CreateDepthStencilView(depth.Get(),&dsv_desc,first_dsv);dev->CreateDepthStencilView(second_depth.Get(),&second_desc,second_dsv);
    auto configure_selection=[&]() {
        selection_capture.configure(dev.Get(),q.Get(),64,32,true);
        selection_capture.on_depth_stencil_view_created(depth.Get(),&dsv_desc,first_dsv);
        selection_capture.on_depth_stencil_view_created(second_depth.Get(),&second_desc,second_dsv);
        g_capture=&selection_capture;
    };
    configure_selection();
    auto begin_selection_frame=[&]() {
        check(post_submit_allocator->Reset());check(cmd->Reset(post_submit_allocator.Get(),nullptr));selection_capture.on_command_list_reset(cmd.Get());
    };
    auto selection_pass=[&](ID3D12Resource* resource,D3D12_CPU_DESCRIPTOR_HANDLE handle,float extent) {
        b=barrier(resource,read,D3D12_RESOURCE_STATE_DEPTH_WRITE);cmd->ResourceBarrier(1,&b);
        D3D12_VIEWPORT vp{0,0,extent,extent,0,1};cmd->RSSetViewports(1,&vp);selection_capture.on_viewports(cmd.Get(),1,&vp);
        cmd->OMSetRenderTargets(0,nullptr,FALSE,&handle);selection_capture.on_render_targets(cmd.Get(),0,handle);
        cmd->OMSetRenderTargets(0,nullptr,FALSE,nullptr);selection_capture.on_render_targets(cmd.Get(),0,{});
        b=barrier(resource,D3D12_RESOURCE_STATE_DEPTH_WRITE,read);cmd->ResourceBarrier(1,&b);selection_capture.on_post_resource_barriers(cmd.Get(),1,&b);
    };
    auto submit_selection_frame=[&]() {check(cmd->Close());q->ExecuteCommandLists(1,lists);wait(q.Get());};
    auto verify_selected_pixels=[&](ID3D12Resource* selected,float expected=.8f) {
        // A source-ID assertion alone could miss leasing the wrong slot.
        const auto desc=selected->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT64 size{};
        dev->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&size);
        auto result=make(dev.Get(),buf(size),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
        begin_selection_frame();b=barrier(selected,read,D3D12_RESOURCE_STATE_COPY_SOURCE);cmd->ResourceBarrier(1,&b);
        D3D12_TEXTURE_COPY_LOCATION src{},dst{};src.pResource=selected;src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.pResource=result.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=fp;cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
        b=barrier(selected,D3D12_RESOURCE_STATE_COPY_SOURCE,read);cmd->ResourceBarrier(1,&b);submit_selection_frame();
        void* data{};check(result->Map(0,nullptr,&data));float sample{};std::memcpy(&sample,data,4);result->Unmap(0,nullptr);
        require(std::abs(sample-expected)<.00001f,"candidate family leased pixels from the wrong physical source");
    };
    begin_selection_frame();upload(second_depth.Get(),[](UINT,UINT){return .8f;});
    b=barrier(second_depth.Get(),D3D12_RESOURCE_STATE_COPY_DEST,read);cmd->ResourceBarrier(1,&b);
    selection_pass(depth.Get(),first_dsv,16);selection_pass(second_depth.Get(),second_dsv,32);submit_selection_frame();
    const auto known_candidates=selection_capture.candidates();require(known_candidates.size()==2,"actual submitted producers did not register two candidate IDs");
    uint64_t first_id{},second_id{};
    for(const auto& candidate:known_candidates) {
        require(candidate.available,"submitted candidate was not marked available");
        if(candidate.width==48)first_id=candidate.id;
        if(candidate.width==32)second_id=candidate.id;
    }
    require(first_id && second_id && first_id!=second_id,"candidate IDs did not identify distinct producer allocations");
    selection_capture.finish_frame();wait(q.Get());
    require(selection_capture.select_candidate(second_id) && selection_capture.selected_candidate()==second_id,"known second candidate could not be selected");
    begin_selection_frame();
    // More nonselected read windows than the twelve capture slots must not
    // consume the selected source's record-time scheduling quota.
    for(UINT i=0;i<13;++i)selection_pass(depth.Get(),first_dsv,16);
    selection_pass(second_depth.Get(),second_dsv,32);submit_selection_frame();
    auto selected_snapshot=selection_capture.acquire();require(bool(selected_snapshot),"earlier nonselected windows starved a later manually selected producer");
    require(selection_capture.active_candidate_id()==second_id,"acquire did not report the actual manually selected source ID");
    verify_selected_pixels(selected_snapshot.Get());selection_capture.finish_frame();wait(q.Get());
    begin_selection_frame();selection_pass(depth.Get(),first_dsv,16);submit_selection_frame();
    require(!selection_capture.acquire() && selection_capture.active_candidate_id()==0,"missing selected producer fell back to another source or stale depth");
    require(selection_capture.selected_candidate()==second_id,"missing selected source silently rearmed automatic selection");
    selection_capture.finish_frame();wait(q.Get());
    selection_capture.reset();configure_selection();
    require(selection_capture.selected_candidate()==0 && selection_capture.active_candidate_id()==0 && selection_capture.candidates().empty(),"reset retained candidate selection or old generation metadata");
    require(!selection_capture.select_candidate(second_id),"old generation candidate ID remained selectable after reset");
    begin_selection_frame();selection_pass(second_depth.Get(),second_dsv,32);submit_selection_frame();
    selected_snapshot=selection_capture.acquire();require(bool(selected_snapshot),"reset did not rearm fresh automatic acquisition");
    require(selection_capture.active_candidate_id()!=0 && selection_capture.active_candidate_id()!=second_id,"reset reused an invalidated candidate ID");
    verify_selected_pixels(selected_snapshot.Get());selection_capture.finish_frame();wait(q.Get());

    std::cout<<"STAGE rotating producer family, stable equal-area choice and manual family pin\n";
    // Two physical resources alternate at the same executed producer route.
    // A second equal-sized pass at a distinct ordinal is a separate family.
    auto rotating_b=make(dev.Get(),tex(32,32,DXGI_FORMAT_R32_TYPELESS,D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    auto competing_depth=make(dev.Get(),tex(32,32,DXGI_FORMAT_R32_TYPELESS,D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    check(second_depth->SetName(L"R7_MainSceneDepth"));check(rotating_b->SetName(L"R7_MainSceneDepth"));
    check(competing_depth->SetName(L"R7_SecondaryDepth"));
    const auto main_name_hash=stock_dibr::producer_resource_name_hash(second_depth.Get());
    require(main_name_hash!=0 && main_name_hash==stock_dibr::producer_resource_name_hash(rotating_b.Get()),"actual D3D12 resource debug names did not corroborate the rotating family");
    require(main_name_hash!=stock_dibr::producer_resource_name_hash(competing_depth.Get()),"different named producer was conflated with the main family");
    D3D12_DESCRIPTOR_HEAP_DESC rotation_heap_desc{};rotation_heap_desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_DSV;rotation_heap_desc.NumDescriptors=3;
    ComPtr<ID3D12DescriptorHeap> rotation_heap;check(dev->CreateDescriptorHeap(&rotation_heap_desc,IID_PPV_ARGS(&rotation_heap)));
    auto rotation_a_dsv=rotation_heap->GetCPUDescriptorHandleForHeapStart();auto rotation_b_dsv=rotation_a_dsv;rotation_b_dsv.ptr+=selection_dsv_stride;
    auto competing_dsv=rotation_b_dsv;competing_dsv.ptr+=selection_dsv_stride;
    dev->CreateDepthStencilView(second_depth.Get(),&second_desc,rotation_a_dsv);
    dev->CreateDepthStencilView(rotating_b.Get(),&second_desc,rotation_b_dsv);
    dev->CreateDepthStencilView(competing_depth.Get(),&second_desc,competing_dsv);
    selection_capture.reset();selection_capture.configure(dev.Get(),q.Get(),64,32,true);g_capture=&selection_capture;
    selection_capture.on_depth_stencil_view_created(second_depth.Get(),&second_desc,rotation_a_dsv);
    selection_capture.on_depth_stencil_view_created(rotating_b.Get(),&second_desc,rotation_b_dsv);
    selection_capture.on_depth_stencil_view_created(competing_depth.Get(),&second_desc,competing_dsv);
    begin_selection_frame();upload(rotating_b.Get(),[](UINT,UINT){return .3f;});upload(competing_depth.Get(),[](UINT,UINT){return .6f;});
    b=barrier(rotating_b.Get(),D3D12_RESOURCE_STATE_COPY_DEST,read);cmd->ResourceBarrier(1,&b);
    b=barrier(competing_depth.Get(),D3D12_RESOURCE_STATE_COPY_DEST,read);cmd->ResourceBarrier(1,&b);
    selection_pass(competing_depth.Get(),competing_dsv,32);selection_pass(second_depth.Get(),rotation_a_dsv,32);submit_selection_frame();
    auto rotation_snapshot=selection_capture.acquire();require(bool(rotation_snapshot),"initial equal-area rotating producer could not be acquired");
    const auto family_id=selection_capture.active_candidate_id();require(family_id!=0,"rotating family has no stable ID");
    verify_selected_pixels(rotation_snapshot.Get(),.8f);selection_capture.finish_frame();wait(q.Get());
    uint64_t a_physical{},b_physical{};
    for(UINT frame=1;frame<=4;++frame) {
        if(frame==3)require(selection_capture.select_candidate(family_id),"stable producer family could not be manually pinned");
        begin_selection_frame();const bool use_b=(frame&1u)!=0;
        selection_pass(competing_depth.Get(),competing_dsv,32);
        selection_pass(use_b?rotating_b.Get():second_depth.Get(),use_b?rotation_b_dsv:rotation_a_dsv,32);
        // A later competing capture must not defeat a fresh established family.
        // The first two route ordinals remain stable across A/B rotation.
        selection_pass(competing_depth.Get(),competing_dsv,32);submit_selection_frame();
        rotation_snapshot=selection_capture.acquire();require(bool(rotation_snapshot),"rotating producer family became unavailable during normal A/B rotation");
        require(selection_capture.active_candidate_id()==family_id,"equal-area competitor caused automatic flip-flop or manual pin changed family");
        const auto metadata=selection_capture.candidates();require(metadata.size()==2,"rotating allocations created extra producer families");
        for(const auto& candidate:metadata)if(candidate.id==family_id) {
            require(candidate.members==2 && !candidate.ambiguous && candidate.route_confidence==2,"rotating producer did not report both name-corroborated physical members");
            if(use_b)b_physical=candidate.physical_id;else a_physical=candidate.physical_id;
        }
        verify_selected_pixels(rotation_snapshot.Get(),use_b?.3f:.8f);selection_capture.finish_frame();wait(q.Get());
    }
    require(a_physical && b_physical && a_physical!=b_physical,"rotating family obscured physical-member identity");
    require(selection_capture.select_candidate(0),"automatic selection could not be rearmed after family pin");
    // During the three-epoch logical-choice grace, a fresh alternate still
    // supplies this frame. No stale pixels or unnecessary synthesis stall.
    for(UINT absent=1;absent<=3;++absent) {
        begin_selection_frame();selection_pass(competing_depth.Get(),competing_dsv,32);submit_selection_frame();
        rotation_snapshot=selection_capture.acquire();
        require(bool(rotation_snapshot) && selection_capture.active_candidate_id()!=family_id,"missing automatic family failed to use a fresh current-frame alternate");
        uint64_t logical_choice{};for(const auto& candidate:selection_capture.candidates())if(candidate.selected_auto)logical_choice=candidate.id;
        if(absent<3)require(logical_choice==family_id,"logical automatic family switched before absence grace elapsed");
        else require(logical_choice==selection_capture.active_candidate_id(),"logical automatic family failed to switch after three absent epochs");
        verify_selected_pixels(rotation_snapshot.Get(),.6f);
        selection_capture.finish_frame();wait(q.Get());
    }
    g_capture=&capture;

    std::cout<<"STAGE failed depth fence signals retain submitted resources across list Reset\n";
    proxy->forward_via_virtual=false;g_opaque_outer_queue=nullptr;
    ComPtr<ID3D12CommandAllocator> failure_reset_allocator;
    check(dev->CreateCommandAllocator(qd.Type,IID_PPV_ARGS(&failure_reset_allocator)));
    auto record_failure_capture=[&](stock_dibr::DepthCapture& target) {
        target.configure(dev.Get(),q.Get(),64,32,true);
        target.on_depth_stencil_view_created(depth.Get(),&dsv_desc,dsv_handle);
        check(post_submit_allocator->Reset());check(cmd->Reset(post_submit_allocator.Get(),nullptr));
        target.on_command_list_reset(cmd.Get());
        b=barrier(depth.Get(),read,D3D12_RESOURCE_STATE_DEPTH_WRITE);cmd->ResourceBarrier(1,&b);
        D3D12_VIEWPORT vp{0,0,16,16,0,1};cmd->RSSetViewports(1,&vp);target.on_viewports(cmd.Get(),1,&vp);
        cmd->OMSetRenderTargets(0,nullptr,FALSE,&dsv_handle);target.on_render_targets(cmd.Get(),0,dsv_handle);
        cmd->OMSetRenderTargets(0,nullptr,FALSE,nullptr);target.on_render_targets(cmd.Get(),0,{});
        b=barrier(depth.Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE,read);cmd->ResourceBarrier(1,&b);
        target.on_post_resource_barriers(cmd.Get(),1,&b);check(cmd->Close());
        g_capture=&target;
    };
    auto reset_submitted_list=[&](stock_dibr::DepthCapture& target) {
        // The list may be reset using a different idle allocator while its
        // original allocator/work is still in flight. This is NOT retirement.
        check(failure_reset_allocator->Reset());check(cmd->Reset(failure_reset_allocator.Get(),nullptr));
        target.on_command_list_reset(cmd.Get());check(cmd->Close());
        require(target.has_pending_retirement(),"failed Signal resources were freed by recording-list Reset");
        target.reset();
        require(target.has_pending_retirement(),"failed Signal quarantine was lost on capture reset");
        wait(native_queue.Get());
    };
    stock_dibr::DepthCapture failed_producer;
    record_failure_capture(failed_producer);
    proxy->fail_signals=true;q->ExecuteCommandLists(1,lists);proxy->fail_signals=false;
    require(!failed_producer.acquire(),"failed producer fence published depth");
    reset_submitted_list(failed_producer);
    stock_dibr::DepthCapture failed_consumer;
    record_failure_capture(failed_consumer);q->ExecuteCommandLists(1,lists);
    require(bool(failed_consumer.acquire()),"consumer-failure setup did not publish depth");
    proxy->fail_signals=true;failed_consumer.finish_frame();proxy->fail_signals=false;
    reset_submitted_list(failed_consumer);
    g_capture=&capture;
    std::cout<<"STAGE teardown forwarding\n";
    const auto cached_detour=reinterpret_cast<stock_dibr::QueueSubmitHook::Callback>((*(void***)q.Get())[10]);
    const auto callbacks_before_clear=g_submit_callbacks;
    queue_submit_hook.clear();g_capture=nullptr;
    // A CPU thread can cache the target immediately before slot restoration.
    // Calling it after clear must still submit real work and skip the retired
    // observer. It must not dereference the destroyed hook instance.
    const auto original_calls_before_clear=g_proxy_execute_calls;
    cached_detour(q.Get(),1,probe_lists);wait(q.Get());
    require(g_proxy_execute_calls==original_calls_before_clear+1,"cached detour dropped real submission after clear");
    require(g_submit_callbacks==callbacks_before_clear,"retired hook still invoked its observer");
    ComPtr<ID3D12InfoQueue> info;if(SUCCEEDED(dev.As(&info)))for(UINT64 i=0;i<info->GetNumStoredMessages();++i){SIZE_T size{};info->GetMessage(i,nullptr,&size);std::vector<char> data(size);auto* message=reinterpret_cast<D3D12_MESSAGE*>(data.data());check(info->GetMessage(i,message,&size));if(message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)throw std::runtime_error(message->pDescription);}
    std::cout<<"PASS: actual queue-submit hook covers distinct dummy/proxy vtables and cached native dispatch, observer reentrancy guard, canonical command-list aliases, native inner callback under opaque outer wrappers, exactly-once publication, alternate direct-queue GPU wait, wrong-producer/late-bind rejection, teardown forwarding, automatic captured-list submission, immediate reset preservation, actual live capture header + production shader on WARP; actual multi-producer manual selection with quota isolation, missing-source fail-closed and reset-generation reacquisition; actual UE5 format19 D32+S8 depth plane, padded allocation with DLSS-sized viewport, distinct eyes, strength0-through2 monotonic known-plane displacement, opaque alpha, R6 padded-rect point/edge-aware filtering, calibrated depth conventions, raw/readable/edge/overlay/confidence binocular inspectors, exposure isolation, isolated-outlier repair with strand/silhouette protection, preserve2x legacy-control bypass; R7 production clear/scatter/resolve entrypoints, slanted character occlusion and projected target-Z/source-index analytic oracles, fractional plane subpixel reconstruction, normal/reversed far-plane sentinel coverage, verified background-only fill, binocular direct/filled/unresolved coverage inspector, invalid projection rejection, typed-null-UAV legacy fallback, named rotating A/B producer family fresh pixels and stable ties/manual pin/absence grace; fresh next-frame pixels, stale rejection, discarded-list reset, no D3D12 errors. "<<different<<" distinct pixel pairs.\n"<<capture.summary()<<"\n";
} catch(const std::exception& e) {std::cerr<<"FAIL: "<<e.what()<<"\n";return 1;}

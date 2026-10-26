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
    HRESULT STDMETHODCALLTYPE Signal(ID3D12Fence* f,UINT64 n) override {return inner->Signal(f,n);}
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
    ComPtr<ID3DBlob> bytecode,error;const auto compiled=D3DCompile(shader,std::strlen(shader),"production DIBR",nullptr,nullptr,"main","cs_5_0",D3DCOMPILE_ENABLE_STRICTNESS,0,&bytecode,&error);
    if(FAILED(compiled)){if(error)std::cerr<<static_cast<const char*>(error->GetBufferPointer());check(compiled);}
    D3D12_DESCRIPTOR_RANGE ranges[2]{};ranges[0]={D3D12_DESCRIPTOR_RANGE_TYPE_SRV,3,0,0,0};ranges[1]={D3D12_DESCRIPTOR_RANGE_TYPE_UAV,1,0,0,0};
    D3D12_ROOT_PARAMETER params[3]{};for(UINT i=0;i<2;++i){params[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;params[i].DescriptorTable={1,&ranges[i]};}
    params[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV;params[2].Descriptor.ShaderRegister=0;
    D3D12_STATIC_SAMPLER_DESC sampler{};sampler.Filter=D3D12_FILTER_MIN_MAG_MIP_LINEAR;sampler.AddressU=sampler.AddressV=sampler.AddressW=D3D12_TEXTURE_ADDRESS_MODE_CLAMP;sampler.MaxLOD=D3D12_FLOAT32_MAX;sampler.ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
    D3D12_ROOT_SIGNATURE_DESC rsd{3,params,1,&sampler,D3D12_ROOT_SIGNATURE_FLAG_NONE};ComPtr<ID3DBlob> rsblob;
    check(D3D12SerializeRootSignature(&rsd,D3D_ROOT_SIGNATURE_VERSION_1,&rsblob,&error));ComPtr<ID3D12RootSignature> rs;check(dev->CreateRootSignature(0,rsblob->GetBufferPointer(),rsblob->GetBufferSize(),IID_PPV_ARGS(&rs)));
    D3D12_COMPUTE_PIPELINE_STATE_DESC pd{};pd.pRootSignature=rs.Get();pd.CS={bytecode->GetBufferPointer(),bytecode->GetBufferSize()};ComPtr<ID3D12PipelineState> pso;check(dev->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pso)));
    D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hd.NumDescriptors=4;hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> descriptors;check(dev->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&descriptors)));const auto stride=dev->GetDescriptorHandleIncrementSize(hd.Type);auto cpu=descriptors->GetCPUDescriptorHandleForHeapStart();
    D3D12_SHADER_RESOURCE_VIEW_DESC srv{};srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;srv.Texture2D.MipLevels=1;srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    srv.Format=DXGI_FORMAT_R8G8B8A8_UNORM;dev->CreateShaderResourceView(color.Get(),&srv,cpu);cpu.ptr+=stride;
    srv.Format=DXGI_FORMAT_R32_FLOAT_X8X24_TYPELESS;dev->CreateShaderResourceView(snapshot.Get(),&srv,cpu);cpu.ptr+=stride;
    srv.Format=DXGI_FORMAT_R8G8B8A8_UNORM;dev->CreateShaderResourceView(color.Get(),&srv,cpu);cpu.ptr+=stride;
    D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;uav.Format=DXGI_FORMAT_R8G8B8A8_UNORM;dev->CreateUnorderedAccessView(output.Get(),nullptr,&uav,cpu);
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
    std::cout<<"PASS: actual queue-submit hook covers distinct dummy/proxy vtables and cached native dispatch, observer reentrancy guard, canonical command-list aliases, native inner callback under opaque outer wrappers, exactly-once publication, alternate direct-queue GPU wait, wrong-producer/late-bind rejection, teardown forwarding, automatic captured-list submission, immediate reset preservation, actual live capture header + production shader on WARP; actual UE5 format19 D32+S8 depth plane, padded allocation with DLSS-sized viewport, distinct eyes, strength0-through2 monotonic known-plane displacement, opaque alpha, fresh next-frame pixels, stale rejection, discarded-list reset, no D3D12 errors. "<<different<<" distinct pixel pairs.\n"<<capture.summary()<<"\n";
} catch(const std::exception& e) {std::cerr<<"FAIL: "<<e.what()<<"\n";return 1;}

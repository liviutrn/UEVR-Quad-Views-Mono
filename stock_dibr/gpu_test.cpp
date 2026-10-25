#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <d3dcompiler.h>
#include <wrl.h>
#include <mods/vr/d3d12/StockDibrDepth.hpp>
#include <array>
#include <vector>
#include <iostream>
#include <stdexcept>
#include <cstring>
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
int main() try {
    ComPtr<ID3D12Debug> debug; if(SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)))) debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIAdapter> adapter;check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
    ComPtr<ID3D12Device> dev;check(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&dev)));
    D3D12_COMMAND_QUEUE_DESC qd{};qd.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> q,other;check(dev->CreateCommandQueue(&qd,IID_PPV_ARGS(&q)));check(dev->CreateCommandQueue(&qd,IID_PPV_ARGS(&other)));
    ComPtr<ID3D12CommandAllocator> allocator;check(dev->CreateCommandAllocator(qd.Type,IID_PPV_ARGS(&allocator)));
    ComPtr<ID3D12GraphicsCommandList> cmd;check(dev->CreateCommandList(0,qd.Type,allocator.Get(),nullptr,IID_PPV_ARGS(&cmd)));
    ComPtr<ID3D12Fence> done;check(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&done)));UINT64 signal{};
    auto wait=[&](ID3D12CommandQueue* queue){check(queue->Signal(done.Get(),++signal));HANDLE e=CreateEventW(nullptr,FALSE,FALSE,nullptr);check(done->SetEventOnCompletion(signal,e));require(WaitForSingleObject(e,30000)==WAIT_OBJECT_0,"GPU timeout");CloseHandle(e);};
    constexpr auto read=D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    stock_dibr::DepthCapture capture;capture.configure(dev.Get(),q.Get(),64,32,true);
    static_assert(DXGI_FORMAT_R32G8X24_TYPELESS==19 && DXGI_FORMAT_R32_TYPELESS==39);
    auto depth=make(dev.Get(),tex(48,24,DXGI_FORMAT_R32G8X24_TYPELESS,D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_DESCRIPTOR_HEAP_DESC dsv_heap_desc{};dsv_heap_desc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_DSV;dsv_heap_desc.NumDescriptors=1;
    ComPtr<ID3D12DescriptorHeap> dsv_heap;check(dev->CreateDescriptorHeap(&dsv_heap_desc,IID_PPV_ARGS(&dsv_heap)));
    auto dsv_handle=dsv_heap->GetCPUDescriptorHandleForHeapStart();D3D12_DEPTH_STENCIL_VIEW_DESC dsv_desc{};dsv_desc.Format=DXGI_FORMAT_D32_FLOAT_S8X24_UINT;dsv_desc.ViewDimension=D3D12_DSV_DIMENSION_TEXTURE2D;
    dev->CreateDepthStencilView(depth.Get(),&dsv_desc,dsv_handle);capture.on_depth_stencil_view_created(depth.Get(),&dsv_desc,dsv_handle);
    auto main_binding=[&](){
        D3D12_VIEWPORT vp{0,0,16,16,0,1};cmd->RSSetViewports(1,&vp);capture.on_viewports(cmd.Get(),1,&vp);
        cmd->OMSetRenderTargets(0,nullptr,FALSE,&dsv_handle);capture.on_render_targets(cmd.Get(),0,dsv_handle);
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
    require(!capture.acquire(),"unsubmitted capture accepted");check(cmd->Close());ID3D12CommandList* lists[]{cmd.Get()};q->ExecuteCommandLists(1,lists);capture.on_command_lists_executed(q.Get(),1,lists);
    auto snapshot=capture.acquire();require(snapshot!=nullptr,"submitted live depth rejected");const auto depth_uv=capture.sample_uv();require(std::abs(depth_uv[0]-1.f/3.f)<.0001f && std::abs(depth_uv[1]-2.f/3.f)<.0001f,"padded allocation viewport mapping incorrect");wait(q.Get());check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());

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
    check(cmd->Close());q->ExecuteCommandLists(1,lists);capture.on_command_lists_executed(q.Get(),1,lists);capture.finish_frame();wait(q.Get());
    check(readback->Map(0,nullptr,&mapped));auto pixel=[&](UINT x,UINT y){return static_cast<uint8_t*>(mapped)+y*footprint.Footprint.RowPitch+x*4;};
    unsigned different{};for(UINT y=0;y<32;++y)for(UINT x=0;x<32;++x){require(pixel(x,y)[0]==x*8,"left eye color changed");require(pixel(x,y)[3]==255 && pixel(x+32,y)[3]==255,"scene alpha not opaque");different+=pixel(x,y)[0]!=pixel(x+32,y)[0];}
    require(different>512,"production shader did not create distinct L/R images");
    require(pixel(56,16)[0]>pixel(24,16)[0]+15,"packed left depth not used on right side of image");readback->Unmap(0,nullptr);
    require(!capture.acquire(),"stale depth reused in next interval");

    // A later frame must carry new pixels, not a frozen successful snapshot.
    check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
    b=barrier(depth.Get(),read,D3D12_RESOURCE_STATE_COPY_DEST);cmd->ResourceBarrier(1,&b);
    upload(depth.Get(),[](UINT x,UINT){return x<16?.25f:.75f;});
    b=barrier(depth.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_DEPTH_WRITE);cmd->ResourceBarrier(1,&b);
    main_binding();b=barrier(depth.Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE,read);cmd->ResourceBarrier(1,&b);capture.on_post_resource_barriers(cmd.Get(),1,&b);
    check(cmd->Close());q->ExecuteCommandLists(1,lists);capture.on_command_lists_executed(q.Get(),1,lists);
    snapshot=capture.acquire();require(snapshot!=nullptr,"next-frame live update missing");wait(q.Get());
    check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
    auto sd=snapshot->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT df{};UINT64 db{};dev->GetCopyableFootprints(&sd,0,1,0,&df,nullptr,nullptr,&db);
    auto depth_readback=make(dev.Get(),buf(db),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
    b=barrier(snapshot.Get(),read,D3D12_RESOURCE_STATE_COPY_SOURCE);cmd->ResourceBarrier(1,&b);
    from.pResource=snapshot.Get();to.pResource=depth_readback.Get();to.PlacedFootprint=df;cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    b=barrier(snapshot.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,read);cmd->ResourceBarrier(1,&b);
    check(cmd->Close());q->ExecuteCommandLists(1,lists);capture.on_command_lists_executed(q.Get(),1,lists);capture.finish_frame();wait(q.Get());
    check(depth_readback->Map(0,nullptr,&mapped));float value{};std::memcpy(&value,mapped,4);require(value==.25f,"depth froze at an earlier frame");depth_readback->Unmap(0,nullptr);
    require(!capture.acquire(),"updated depth reused after interval ended");

    // A reset/discard must never publish a recording that was not executed.
    check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());
    b=barrier(depth.Get(),read,D3D12_RESOURCE_STATE_DEPTH_WRITE);cmd->ResourceBarrier(1,&b);
    main_binding();b=barrier(depth.Get(),D3D12_RESOURCE_STATE_DEPTH_WRITE,read);cmd->ResourceBarrier(1,&b);capture.on_post_resource_barriers(cmd.Get(),1,&b);
    check(cmd->Close());check(cmd->Reset(allocator.Get(),nullptr));capture.on_command_list_reset(cmd.Get());require(!capture.acquire(),"discarded list was published");check(cmd->Close());
    ComPtr<ID3D12InfoQueue> info;if(SUCCEEDED(dev.As(&info)))for(UINT64 i=0;i<info->GetNumStoredMessages();++i){SIZE_T size{};info->GetMessage(i,nullptr,&size);std::vector<char> data(size);auto* message=reinterpret_cast<D3D12_MESSAGE*>(data.data());check(info->GetMessage(i,message,&size));if(message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)throw std::runtime_error(message->pDescription);}
    std::cout<<"PASS: actual live capture header + production shader on WARP; actual UE5 format19 D32+S8 depth plane, padded allocation with DLSS-sized viewport, submitted-list gate, distinct eyes, opaque alpha, fresh next-frame pixels, stale rejection, discarded-list reset, no D3D12 errors. "<<different<<" distinct pixel pairs.\n"<<capture.summary()<<"\n";
} catch(const std::exception& e) {std::cerr<<"FAIL: "<<e.what()<<"\n";return 1;}

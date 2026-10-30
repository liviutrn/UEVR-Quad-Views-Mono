#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <mods/vr/d3d12/StockDibrDepth.hpp>
#include <mods/vr/DuoViewD3D12.hpp>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <array>
#include <cstring>
#include <thread>
#include <chrono>
#include <fstream>
using Microsoft::WRL::ComPtr;
using stock_dibr::DepthCapture;
using namespace uevr::duoview;
thread_local bool g_inside_depth_stencil_observer=false;
void check(HRESULT h){if(FAILED(h))throw std::runtime_error("HRESULT="+std::to_string(uint32_t(h)));}
void need(bool b,const char* why){if(!b)throw std::runtime_error(why);}
D3D12_RESOURCE_DESC texture(UINT w,UINT h,DXGI_FORMAT f,D3D12_RESOURCE_FLAGS flags=D3D12_RESOURCE_FLAG_NONE){
 D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Width=w;d.Height=h;
 d.DepthOrArraySize=d.MipLevels=1;d.SampleDesc.Count=1;d.Format=f;d.Flags=flags;return d;
}
D3D12_RESOURCE_DESC buffer(UINT64 n){D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;d.Width=n;d.Height=d.DepthOrArraySize=d.MipLevels=1;d.SampleDesc.Count=1;d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;return d;}
ComPtr<ID3D12Resource> resource(ID3D12Device* dev,D3D12_RESOURCE_DESC d,D3D12_HEAP_TYPE type,D3D12_RESOURCE_STATES state){
 D3D12_HEAP_PROPERTIES hp{};hp.Type=type;ComPtr<ID3D12Resource> r;check(dev->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,state,nullptr,IID_PPV_ARGS(&r)));return r;
}
void barrier(ID3D12GraphicsCommandList* c,ID3D12Resource* r,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after){
 D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;b.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};c->ResourceBarrier(1,&b);
}
struct Context {
 ComPtr<ID3D12Device> device;ComPtr<ID3D12CommandQueue> queue;ComPtr<ID3D12CommandAllocator> allocator;ComPtr<ID3D12GraphicsCommandList> cmd;ComPtr<ID3D12Fence> fence;UINT64 serial{};
 Context(ID3D12Device* d,D3D12_COMMAND_LIST_TYPE type):device(d){
  D3D12_COMMAND_QUEUE_DESC q{};q.Type=type;check(d->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)));
  check(d->CreateCommandAllocator(type,IID_PPV_ARGS(&allocator)));check(d->CreateCommandList(0,type,allocator.Get(),nullptr,IID_PPV_ARGS(&cmd)));check(d->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));
 }
 void flush(DepthCapture* cap=nullptr){
  check(cmd->Close());ID3D12CommandList* lists[]{cmd.Get()};queue->ExecuteCommandLists(1,lists);
  if(cap)cap->on_command_lists_executed(queue.Get(),1,lists);
  check(queue->Signal(fence.Get(),++serial));HANDLE e=CreateEventW(nullptr,FALSE,FALSE,nullptr);need(e!=nullptr,"fence event");
  check(fence->SetEventOnCompletion(serial,e));const auto result=WaitForSingleObject(e,30000);CloseHandle(e);need(result==WAIT_OBJECT_0,"GPU timeout");
  if(cap)cap->on_command_list_reset(cmd.Get());check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
 }
};
ComPtr<ID3D12Resource> upload(Context& c,ID3D12Resource* target,const std::vector<uint8_t>& pixels,UINT bpp,D3D12_RESOURCE_STATES end){
 const auto d=target->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT foot{};UINT64 bytes{};
 c.device->GetCopyableFootprints(&d,0,1,0,&foot,nullptr,nullptr,&bytes);
 auto staging=resource(c.device.Get(),buffer(bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
 void* mapped{};D3D12_RANGE none{0,0};check(staging->Map(0,&none,&mapped));
 for(UINT y=0;y<d.Height;++y)std::memcpy(static_cast<uint8_t*>(mapped)+y*foot.Footprint.RowPitch,pixels.data()+size_t(y)*d.Width*bpp,size_t(d.Width)*bpp);
 staging->Unmap(0,nullptr);D3D12_TEXTURE_COPY_LOCATION from{},to{};from.pResource=staging.Get();from.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;from.PlacedFootprint=foot;
 to.pResource=target;to.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;c.cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);barrier(c.cmd.Get(),target,D3D12_RESOURCE_STATE_COPY_DEST,end);return staging;
}
std::vector<uint8_t> floats(UINT w,UINT h,float value){std::vector<uint8_t> p(size_t(w)*h*4);for(size_t i=0;i<size_t(w)*h;++i)std::memcpy(p.data()+i*4,&value,4);return p;}
std::vector<uint8_t> color(UINT w,UINT h,std::array<uint8_t,4> v){std::vector<uint8_t> p(size_t(w)*h*4);for(size_t i=0;i<size_t(w)*h;++i)std::memcpy(p.data()+i*4,v.data(),4);return p;}
struct Readback {ComPtr<ID3D12Resource> buffer;D3D12_PLACED_SUBRESOURCE_FOOTPRINT foot{};UINT64 bytes{};UINT w{},h{},bpp{};};
Readback readback(Context& c,ID3D12Resource* r,UINT bpp,D3D12_RESOURCE_STATES state){
 Readback v;const auto d=r->GetDesc();v.w=UINT(d.Width);v.h=d.Height;v.bpp=bpp;c.device->GetCopyableFootprints(&d,0,1,0,&v.foot,nullptr,nullptr,&v.bytes);
 v.buffer=resource(c.device.Get(),buffer(v.bytes),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
 barrier(c.cmd.Get(),r,state,D3D12_RESOURCE_STATE_COPY_SOURCE);D3D12_TEXTURE_COPY_LOCATION from{},to{};from.pResource=r;from.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;to.pResource=v.buffer.Get();to.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;to.PlacedFootprint=v.foot;
 c.cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);barrier(c.cmd.Get(),r,D3D12_RESOURCE_STATE_COPY_SOURCE,state);return v;
}
std::vector<uint8_t> packed(const Readback& v){void* data{};D3D12_RANGE range{0,SIZE_T(v.bytes)};check(v.buffer->Map(0,&range,&data));std::vector<uint8_t> out(size_t(v.w)*v.h*v.bpp);for(UINT y=0;y<v.h;++y)std::memcpy(out.data()+size_t(y)*v.w*v.bpp,static_cast<uint8_t*>(data)+size_t(y)*v.foot.Footprint.RowPitch,size_t(v.w)*v.bpp);D3D12_RANGE none{0,0};v.buffer->Unmap(0,&none);return out;}
ngx::Guide guide(unsigned role,uint64_t packet=42){ngx::Guide g;g.producer={packet,3,99,100,3,{16,12,8,6}};g.role=role;g.manual_source=true;g.feature=role;g.output=role;g.feature_generation=role;g.evaluation=role;
 g.input_width=role==1?8:4;g.input_height=role==1?6:3;g.output_width=role==1?16:8;g.output_height=role==1?12:6;g.flags=10;g.flags_known=true;g.motion_low_resolution=true;g.motion_extent_known=true;g.create_observed=true;g.feature_kind=1;return g;}
void capture_test(ID3D12Device* device,D3D12_COMMAND_LIST_TYPE producer_type,bool half){
 Context consumer(device,D3D12_COMMAND_LIST_TYPE_DIRECT),producer(device,producer_type);
 DepthCapture cap;cap.configure(device,consumer.queue.Get(),64,24,true);cap.configure_duoview_sources(16,12,8,6);cap.arm_diagnostic_capture();
 auto& registry=ngx::manual_registry();
 registry.observe({1,1,1,16,12,8,6,1,true,true});
 registry.observe({2,2,2,8,6,4,3,1,true,true});
 need(registry.pin(0,1,16,12),"manual LEFT pin required");
 need(registry.pin(1,2,8,6),"manual RIGHT pin required");
 std::vector<ComPtr<ID3D12Resource>> inputs,staging;
 for(unsigned role=1;role<=2;++role){
  auto g=guide(role);g.depth_x=g.color_x=g.motion_x=2;g.depth_y=g.color_y=g.motion_y=1;g.jitter_x=.25f;g.jitter_y=-.25f;
  const UINT w=g.input_width+4,h=g.input_height+3;
  auto depth=resource(device,texture(w,h,half?DXGI_FORMAT_R16_FLOAT:DXGI_FORMAT_R32_FLOAT),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
  auto rgb=resource(device,texture(w,h,DXGI_FORMAT_R8G8B8A8_UNORM),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
  auto mv=resource(device,texture(w,h,DXGI_FORMAT_R16G16_FLOAT),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
  std::vector<uint8_t> z;if(half){z.resize(size_t(w)*h*2);const uint16_t value=0x3400;for(size_t i=0;i<size_t(w)*h;++i)std::memcpy(z.data()+i*2,&value,2);}else z=floats(w,h,.25f);
  constexpr auto nps=D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
  staging.push_back(upload(producer,depth.Get(),z,half?2:4,nps));staging.push_back(upload(producer,rgb.Get(),color(w,h,{uint8_t(role*40),80,120,255}),4,nps));staging.push_back(upload(producer,mv.Get(),std::vector<uint8_t>(size_t(w)*h*4),4,nps));
  // Unknown late-create flags + padded MV must not disable authentic depth.
  if(role==2){g.flags_known=false;g.create_observed=false;g.motion_extent_known=false;}
  cap.capture_ngx_dlss(producer.cmd.Get(),depth.Get(),rgb.Get(),mv.Get(),g);inputs.push_back(depth);inputs.push_back(rgb);inputs.push_back(mv);
 }
 producer.flush(&cap);
 // CI70: a single manually pinned role must provide a diagnostic preview
 // independently from its missing counterpart; mode 3 is comparison-only.
 auto left_debug=cap.select_preview(0,0,16,12,8,6,false,42,3,1u);
 need(left_debug.left && !left_debug.right,"LEFT-only DLSS preview needs no RIGHT");
 auto right_debug=cap.select_preview(0,0,16,12,8,6,false,42,3,2u);
 need(right_debug.right && !right_debug.left,"RIGHT-only DLSS preview needs no LEFT");
 registry.clear(1);
 auto still_left=cap.select_preview(0,0,16,12,8,6,false,42,3,1u);
 need(still_left.left && !still_left.right,"LEFT preview must survive clearing RIGHT pin");
 auto no_right=cap.select_preview(0,0,16,12,8,6,false,42,3,2u);
 need(!no_right.right,"cleared RIGHT may not appear as stale depth");
 
 need(!cap.select_preview(0,0,16,12,8,6,false,43,3).left,"unassigned RIGHT must not form manual pair");
 need(registry.pin(1,2,8,6),"reassign manual RIGHT before pair test");
 auto pair=cap.select_preview(0,0,16,12,8,6,false,42,3);need(pair.left && pair.right,"NGX pair unavailable after real producer submission");
 need(pair.left->GetDesc().Format==(half?DXGI_FORMAT_R16_FLOAT:DXGI_FORMAT_R32_TYPELESS),"half depth reinterpreted as UNORM");
 auto candidates=cap.snapshot_candidates(pair.left_serial,pair.right_serial);need(candidates.size()>=2,"two NGX depth views missing from capture candidates");
 auto left=resource(device,texture(16,12,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
 auto right=resource(device,texture(8,6,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
 auto final=resource(device,texture(64,24,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
 diag::SelectionRecord selected;selected.color_packet=42;selected.layout_generation=3;selected.left_serial=pair.left_serial;selected.right_serial=pair.right_serial;selected.effective_mode=selected.requested_mode=5;
 for(size_t n=0;n<=candidates.size();++n){auto session=std::make_shared<diag::Session>(9000+n,"manual NGX gallery fixture","fixture");auto gallery_selection=selected;gallery_selection.effective_mode=gallery_selection.requested_mode=0;session->set_selection(gallery_selection);std::vector<diag::Candidate> subset(candidates.begin(),candidates.begin()+n);need(session->prepare(device,left.Get(),right.Get(),subset,true,false)==(n>=1),"manual gallery depth readback contract");}
 { auto single_depth=candidates.front();single_depth.ngx_guide.role=0;
   auto session=std::make_shared<diag::Session>(9100,"unassigned NGX gallery fixture","fixture");
   auto gallery_selection=selected;gallery_selection.effective_mode=gallery_selection.requested_mode=0;
   session->set_selection(gallery_selection);
   need(session->prepare(device,left.Get(),right.Get(),std::vector<diag::Candidate>{single_depth},true,false),"unassigned NGX depth should be exportable"); }
 auto rb=readback(consumer,pair.left.Get(),half?2:4,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
 auto session=std::make_shared<diag::Session>(9200+unsigned(producer_type)*10+unsigned(half),"WARP fixture; no NGX runtime/headset","fixture");session->set_selection(selected);
 need(session->prepare(device,left.Get(),right.Get(),candidates,true,false),"manual NGX session preparation");need(session->attach_headset_output(device,final.Get()),"final output attachment");need(session->record(consumer.cmd.Get()),"actual manual NGX GPU depth gallery recording");consumer.flush();
 const auto pixels=packed(rb);if(half){uint16_t value{};std::memcpy(&value,pixels.data(),2);need(value==0x3400,"half raw value changed");}else{float value{};std::memcpy(&value,pixels.data(),4);need(value==.25f,"float raw value changed");}
 cap.finish_frame();consumer.flush();
 std::cout<<"PASS manual NGX capture: producer="<<unsigned(producer_type)<<" half="<<half<<" real WARP GPU depth copy, unassigned gallery and pinned stereo\n";
}
void shader_test(ID3D12Device* device){
 Context c(device,D3D12_COMMAND_LIST_TYPE_DIRECT);
 auto layout=make_layout(32,24,.5f,.5f,.25f,1.f,.5f,.5f);need(bool(layout),"shader layout");
 ViewFrame f;f.config={{3,99},*layout,{.5f,.5f},{},1};f.config.settings.fovea_view=0;f.config.settings.sharpen_strength=0;f.split_eye=true;
 f.projection[0]=f.projection_right[0]=1.25f;f.projection[5]=f.projection_right[5]=1.5f;f.projection[11]=f.projection_right[11]=1;f.projection[14]=f.projection_right[14]=10;
 // Start with equal camera positions to isolate visibility from disparity.
 // Projection tests elsewhere cover the exact nonzero native camera baseline.
 std::array<ngx::Guide,2> guides{guide(1),guide(2)};guides[1].input_width=8;guides[1].input_height=6;
 guides[0].jitter_x=.25f;guides[0].jitter_y=-.25f;guides[1].jitter_x=-.25f;guides[1].jitter_y=.25f;
 dx12::Compositor compositor;need(compositor.prewarm(device,32,24,false),"compositor prewarm");
 for(unsigned scene=0;scene<3;++scene){
  std::vector<ComPtr<ID3D12Resource>> staging;
  auto left=resource(device,texture(16,12,DXGI_FORMAT_B8G8R8A8_TYPELESS,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
  auto right=resource(device,texture(8,6,DXGI_FORMAT_B8G8R8A8_TYPELESS,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
  auto ld=resource(device,texture(8,6,DXGI_FORMAT_R32_FLOAT),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
  auto rd=resource(device,texture(8,6,DXGI_FORMAT_R32_FLOAT),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
  auto out=resource(device,texture(64,24,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
  auto lz=floats(8,6,.1f),rz=floats(8,6,.1f);const float foreground=.5f;
  if(scene==1)std::memcpy(lz.data()+(3*8+4)*4,&foreground,4);
  if(scene==2)std::memcpy(rz.data()+(3*8+4)*4,&foreground,4);
  staging.push_back(upload(c,left.Get(),color(16,12,{0,0,255,255}),4,D3D12_RESOURCE_STATE_RENDER_TARGET));
  staging.push_back(upload(c,right.Get(),color(8,6,{255,0,0,255}),4,D3D12_RESOURCE_STATE_RENDER_TARGET));
  staging.push_back(upload(c,ld.Get(),lz,4,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE));
  staging.push_back(upload(c,rd.Get(),rz,4,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE));
  const std::array<float,4> quality{1.f,.015f,1.f,8.f}; // CI73 A/B comfort mode // CI72 research inverse target gather // CI71 full LEFT mesh at 2-texel stride
  need(compositor.record_native(device,c.cmd.Get(),left.Get(),right.Get(),out.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,f,{},0,ld.Get(),rd.Get(),0,5,1,{0,0,8,6,0,1},{0,0,8,6,0,1},guides,quality),compositor.error().c_str());
  need(compositor.last_true_stereo(),"requested production stereo not actually recorded");
  auto rb=readback(c,out.Get(),4,D3D12_RESOURCE_STATE_RENDER_TARGET);c.flush();const auto p=packed(rb);
  unsigned red=0,blue=0;
  for(UINT y=9;y<16;++y)for(UINT x=44;x<52;++x){const auto at=(size_t(y)*64+x)*4;red+=p[at+2]>220 && p[at]<30;blue+=p[at]>220 && p[at+2]<30;}
  if(scene==0)need(red>40 && blue==0,"matched dual-depth plane did not reuse LEFT foveal shading");
  else {
   const size_t center=(size_t(12)*64+48)*4;
   need(p[center]>220 && p[center+2]<30,"central one-texel source/target foreground leaked through depth validation");
  }
  if(scene==0) {
   for(unsigned debug_mode=1;debug_mode<=3;++debug_mode) {
    const bool l=debug_mode!=2,r=debug_mode!=1;
    std::array<ngx::Guide,2> pg{l?guides[0]:ngx::Guide{},r?guides[1]:ngx::Guide{}};
    const bool recorded=compositor.record_native(device,c.cmd.Get(),left.Get(),right.Get(),out.Get(),
         D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,f,{},0,
         l?ld.Get():nullptr,r?rd.Get():nullptr,debug_mode,0,1,
         l?DepthViewport{0,0,8,6,0,1}:DepthViewport{},
         r?DepthViewport{0,0,8,6,0,1}:DepthViewport{},pg,quality);
    need(recorded,compositor.error().c_str());
    need(!compositor.last_true_stereo(),"single depth debug cannot report stereo");
    auto depth_rb=readback(c,out.Get(),4,D3D12_RESOURCE_STATE_RENDER_TARGET);
    c.flush();
    const auto depth_pixels=packed(depth_rb);
    const auto middle=(size_t(12)*64+48)*4;
    need(depth_pixels[middle+1]>25,"depth diagnostic pixel shader did not execute");
    std::cout<<"PASS NGX independent depth preview="<<debug_mode<<" no paired stereo required\n";
   }
  }
  std::cout<<"PASS production dual-depth backward fovea scene="<<scene<<" red="<<red<<" right-fallback="<<blue<<"\n";
 }
}
int main()try {
 ComPtr<ID3D12Debug> debug;if(SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))))debug->EnableDebugLayer();
 ComPtr<IDXGIFactory4> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));ComPtr<IDXGIAdapter> adapter;check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));ComPtr<ID3D12Device> device;check(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)));
 capture_test(device.Get(),D3D12_COMMAND_LIST_TYPE_DIRECT,false);capture_test(device.Get(),D3D12_COMMAND_LIST_TYPE_COMPUTE,true);shader_test(device.Get());
 ComPtr<ID3D12InfoQueue> info;if(SUCCEEDED(device.As(&info))){for(UINT64 i=0;i<info->GetNumStoredMessages();++i){SIZE_T n{};info->GetMessage(i,nullptr,&n);std::vector<uint8_t> bytes(n);auto* m=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());check(info->GetMessage(i,m,&n));if(m->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)throw std::runtime_error(m->pDescription);}}
 std::cout<<"PASS: CI73 conservative NGX WARP capture, half depth, DIRECT+COMPUTE and stereo shader; no game/headset executed\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}

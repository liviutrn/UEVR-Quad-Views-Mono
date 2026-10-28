// Exercises the actual production Compositor/PSO. Expected plane colors are
// derived from independent double-precision 3D rays, not shader depth decoding.
#include "WarpTestSupport.hpp"
#include <algorithm>
#include <cmath>
using uevr::duoview::DepthViewport;
struct Scenario {
    // Unreal scene units are centimeters. Physical plane tests below use
    // 100/200/1000 units for 1/2/10 meters and a 6.4-unit physical baseline.
    float z=200.f, left_z=0.f, baseline=6.4f, left_near=10.f, right_near=10.f;
    bool padded=false, srgb=false, indirect=false, forward_z=false;
    uint32_t mode=1, preview=0, debug=0;
    float sign=1.f;
    int invalid=0;
    DepthViewport left{0,0,32,32,0,1}, right{0,0,16,16,0,1};
};
struct Readback { bool accepted=false, recorded=false, direct=false; std::string error; std::vector<uint8_t> pixels; };
class Fixture {
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> cmd;
    ComPtr<ID3D12Fence> fence;
    ComPtr<ID3D12InfoQueue> info;
    uint64_t serial=0;
public:
    Fixture() {
        ComPtr<ID3D12Debug> debug;
        if(SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))))debug->EnableDebugLayer();
        ComPtr<IDXGIFactory4> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
        ComPtr<IDXGIAdapter> adapter;check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
        check(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)));
        D3D12_COMMAND_QUEUE_DESC q{};q.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
        check(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)));
        check(device->CreateCommandAllocator(q.Type,IID_PPV_ARGS(&allocator)));
        check(device->CreateCommandList(0,q.Type,allocator.Get(),nullptr,IID_PPV_ARGS(&cmd)));
        check(cmd->Close());check(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));
        device.As(&info);
    }
    Readback render(Scenario s) {
        check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
        auto l=native_source(device.Get(),cmd.Get(),32,32,{0,0,0,255},true,0);
        auto r=native_source(device.Get(),cmd.Get(),16,16,{0,0,0,255},true,1);
        if(s.padded) {s.left.x=11;s.left.y=7;s.right.x=5;s.right.y=3;}
        const auto encoded=[&](float z,float near_plane,const DepthViewport& v) {
            const float d=s.forward_z ? (10000.f/(10000.f-near_plane)-10000.f*near_plane/((10000.f-near_plane)*z)) : near_plane/z;
            return v.min_depth+(v.max_depth-v.min_depth)*d;
        };
        auto ld=native_depth(device.Get(),cmd.Get(),s.padded?80:32,s.padded?64:32,
            encoded(s.left_z>0?s.left_z:s.z,s.left_near,s.left),s.left);
        auto rd=native_depth(device.Get(),cmd.Get(),s.padded?48:16,s.padded?40:16,
            encoded(s.z,s.right_near,s.right),s.right);
        auto output_desc=texture(128,64,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
        output_desc.Format=s.srgb && !s.indirect?DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:DXGI_FORMAT_B8G8R8A8_UNORM;
        auto output=resource(device.Get(),output_desc,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT foot{};UINT64 bytes{};
        device->GetCopyableFootprints(&output_desc,0,1,0,&foot,nullptr,nullptr,&bytes);
        auto readback=resource(device.Get(),buffer(bytes),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
        auto layout=uevr::duoview::make_layout(64,64,.5f,.5f,.25f,1.f,.5f,.5f);
        if(!layout)throw std::runtime_error("fixture layout invalid");
        uevr::duoview::ViewFrame frame{};
        frame.config={{1,1},*layout,{.5f,.5f},{},1};
        frame.config.settings.fovea_view=0;frame.config.settings.sharpen_strength=0;
        frame.config.settings.feather_fraction=.12f;frame.config.settings.diagnostic_view=s.debug;
        frame.split_eye=true;
        auto projection=[&](std::array<float,16>& p,float near_plane) {
            p={};p[0]=p[5]=p[11]=1.f;
            if(s.forward_z){p[10]=10000.f/(10000.f-near_plane);p[14]=-10000.f*near_plane/(10000.f-near_plane);}
            else p[14]=near_plane;
        };
        projection(frame.projection,s.left_near);projection(frame.projection_right,s.right_near);
        frame.eye_cameras[0].position={0.,0.,0.};frame.eye_cameras[1].position={s.baseline,0.,0.};
        ID3D12Resource* left=ld.texture.Get();ID3D12Resource* right=rd.texture.Get();
        ComPtr<ID3D12Resource> invalid_resource;
        if(s.invalid==1)s.left={};
        if(s.invalid==2)s.left.x=999;
        if(s.invalid==3)s.left.min_depth=s.left.max_depth=.5f;
        if(s.invalid==4)s.left.x=std::numeric_limits<float>::quiet_NaN();
        if(s.invalid==5)right=left;
        if(s.invalid==6)left=nullptr;
        if(s.invalid==7 || s.invalid==8) {
            auto d=texture(32,32,D3D12_RESOURCE_FLAG_NONE);d.Format=DXGI_FORMAT_R32_FLOAT;
            if(s.invalid==7)d.DepthOrArraySize=2;else d.MipLevels=2;
            invalid_resource=resource(device.Get(),d,D3D12_HEAP_TYPE_DEFAULT,
                D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE|D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            left=invalid_resource.Get();
        }
        if(s.invalid==9)frame.projection[5]=std::numeric_limits<float>::infinity();
        if(s.invalid==10)s.mode=99; // 3 is now the supported fovea-only mode
        if(s.invalid==11)s.right.max_depth=2;
        if(s.invalid==12)left=l.texture.Get();
        uevr::duoview::dx12::Compositor compositor;
        if(!compositor.prewarm(device.Get(),64,64,s.srgb))throw std::runtime_error(compositor.error());
        Readback result;
        result.accepted=compositor.record_native(device.Get(),cmd.Get(),l.texture.Get(),r.texture.Get(),output.Get(),
            D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,frame,
            std::make_shared<const int>(1),0,left,right,s.preview,s.mode,s.sign,s.left,s.right);
        result.recorded=compositor.recorded_commands();result.direct=compositor.last_native_direct_xr();result.error=compositor.error();
        if(result.accepted) {
            transition(cmd.Get(),output.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION from{output.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
            D3D12_TEXTURE_COPY_LOCATION to{readback.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};to.PlacedFootprint=foot;
            cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
        }
        check(cmd->Close());ID3D12CommandList* lists[]{cmd.Get()};queue->ExecuteCommandLists(1,lists);
        check(queue->Signal(fence.Get(),++serial));
        HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        if(!event)throw std::runtime_error("event allocation failed");
        check(fence->SetEventOnCompletion(serial,event));
        const auto waited=WaitForSingleObject(event,30000);CloseHandle(event);
        if(waited!=WAIT_OBJECT_0)throw std::runtime_error("WARP fence timeout");
        if(result.accepted) {
            void* data{};D3D12_RANGE range{0,static_cast<SIZE_T>(bytes)};check(readback->Map(0,&range,&data));
            result.pixels.resize(128*64*4);
            for(UINT y=0;y<64;++y)std::memcpy(result.pixels.data()+y*128*4,
                static_cast<uint8_t*>(data)+y*foot.Footprint.RowPitch,128*4);
            readback->Unmap(0,nullptr);
        }
        if(info) for(UINT64 i=0;i<info->GetNumStoredMessages();++i) {
            SIZE_T size{};check(info->GetMessage(i,nullptr,&size));std::vector<uint8_t> storage(size);
            auto* message=reinterpret_cast<D3D12_MESSAGE*>(storage.data());check(info->GetMessage(i,message,&size));
            if(message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)throw std::runtime_error(message->pDescription);
        }
        return result;
    }
};
static void require(bool condition,const std::string& message) {if(!condition)throw std::runtime_error(message);}
static const uint8_t* pixel(const Readback& r,int x,int y){return r.pixels.data()+(y*128+x)*4;}
static double pattern(int x,int y,int c,int offset) {
    if(c==0)return (x*17+offset*11)&255;
    if(c==1)return (y*23+offset*7)&255;
    return (x*3+y*5+offset*13)&255;
}
static double sample_pattern(double x,double y,int size,int c,int offset=0) {
    x=std::clamp(x,0.,double(size-1));y=std::clamp(y,0.,double(size-1));
    int a=int(std::floor(x)),b=int(std::floor(y));double fx=x-a,fy=y-b;
    return (1-fy)*((1-fx)*pattern(a,b,c,offset)+fx*pattern(std::min(a+1,size-1),b,c,offset))+
        fy*((1-fx)*pattern(a,std::min(b+1,size-1),c,offset)+fx*pattern(std::min(a+1,size-1),std::min(b+1,size-1),c,offset));
}
int main() try {
    Fixture gpu;int cases=0;
    auto render=[&](Scenario s){auto r=gpu.render(s);require(r.accepted,r.error);++cases;return r;};
    for(float z : {100.f,200.f,1000.f})for(float sign : {1.f,-1.f}) {
        Scenario s;s.z=z;s.sign=sign;const auto r=render(s);
        const double u=31.5/64.,v=31.5/64.;
        // Intersect the target camera's calibrated pinhole ray with a metric
        // plane. Translate into the source camera, then project and crop it.
        const double world_x=(2*u-1)*z+double(s.baseline)*sign;
        const double world_y=(1-2*v)*z;
        const double source_u=.5+.5*world_x/z,source_v=.5-.5*world_y/z;
        const double sx=(source_u-.25)/.5*32-.5,sy=(source_v-.25)/.5*32-.5;
        for(int c=0;c<3;++c)require(std::abs(pixel(r,95,31)[c]-sample_pattern(sx,sy,32,c))<=2.0,
            "metric plane disagrees with independent 3D oracle z="+std::to_string(z));
        for(int c=0;c<3;++c)require(std::abs(pixel(r,31,31)[c]-pattern(15,15,c,0))<=1.0,"native LEFT modified by warp");
        std::cout<<"PASS plane Z="<<z<<" baselineSign="<<sign<<" sourceTexelX="<<sx<<"\n";
    }
    Scenario plain;const auto baseline=render(plain);
    Scenario padded=plain;padded.padded=true;require(render(padded).pixels==baseline.pixels,"DSV padding/viewport changed output");
    Scenario asymmetric=plain;asymmetric.left_near=30.f;require(render(asymmetric).pixels==baseline.pixels,"LEFT decoded using RIGHT projection");
    Scenario ranged=plain;ranged.left.min_depth=.2f;ranged.left.max_depth=.8f;ranged.right.min_depth=.1f;ranged.right.max_depth=.9f;
    require(render(ranged).pixels==baseline.pixels,"viewport depth range ignored");
    Scenario reversed=plain;reversed.left.min_depth=1;reversed.left.max_depth=0;reversed.right.min_depth=1;reversed.right.max_depth=0;
    require(render(reversed).pixels==baseline.pixels,"inverted viewport depth range ignored");
    Scenario forward=plain;forward.forward_z=true;const auto forward_result=render(forward);
    for(size_t i=0;i<baseline.pixels.size();++i)require(std::abs(int(forward_result.pixels[i])-baseline.pixels[i])<=1,"forward/reversed Z plane differs");
    Scenario zero=plain;zero.baseline=0;render(zero);
    Scenario preview=plain;preview.preview=3;require(render(preview).pixels==baseline.pixels,"depth preview overrode stereo");
    Scenario tint=plain;tint.mode=2;const auto proof=render(tint);
    for(int y=0;y<64;++y)for(int x=0;x<64;++x)for(int c=0;c<3;++c) {
        require(pixel(proof,x,y)[c]==pixel(baseline,x,y)[c],"proof altered LEFT eye");
        const double target=c==0?.9*255:c==1?.2*255:0;
        const double expected=.76*pixel(baseline,x+64,y)[c]+.24*target;
        require(std::abs(pixel(proof,x+64,y)[c]-expected)<=2,"RIGHT whole-eye tint missed center/corner");
    }
    Scenario hidden=plain;hidden.left_z=100.f;const auto fallback=render(hidden);
    for(int c=0;c<3;++c)require(std::abs(pixel(fallback,95,31)[c]-sample_pattern(31.5/64*16-.5,31.5/64*16-.5,16,c,1))<=2,
        "occluded target did not use actual RIGHT color");
    Scenario direct=plain;direct.srgb=true;const auto direct_result=render(direct);
    direct.indirect=true;const auto indirect_result=render(direct);
    require(direct_result.direct&&!indirect_result.direct,"direct/indirect route not exercised");
    require(direct_result.pixels==indirect_result.pixels,"doublewide indirect output differs from direct output");
    Scenario mono=plain;mono.mode=0;const auto mono_result=render(mono);
    for(int y=0;y<64;++y)for(int x=0;x<64;++x)
        require(std::memcmp(pixel(mono_result,x,y),pixel(mono_result,x+64,y),4)==0,"mode0 eye halves differ");
    Scenario isolated=plain;isolated.mode=3;const auto isolated_result=render(isolated);
    for(int y : {0,1,62,63})for(int x=0;x<64;++x)
        require(std::memcmp(pixel(isolated_result,x,y),pixel(isolated_result,x+64,y),4)==0,
            "fovea-only mode warped one peripheral eye");
    Scenario debug=plain;debug.debug=2;const auto debug_result=render(debug);
    require(pixel(debug_result,0,0)[0]>=9&&pixel(debug_result,0,0)[0]<=11,"fovea-only diagnostic background missing");
    for(int invalid=1;invalid<=12;++invalid) {
        Scenario bad;bad.invalid=invalid;const auto r=gpu.render(bad);++cases;
        require(!r.accepted&&!r.recorded&&!r.error.empty(),"invalid depth/projection accepted or commands recorded, case="+std::to_string(invalid));
    }
    std::cout<<"PASS: "<<cases<<" production stereo WARP scenarios; analytic 3D, active rect/range, per-eye near_plane, tint, fallback, resource rejects\n";
    return 0;
} catch(const std::exception& e) {std::cerr<<"FAIL: "<<e.what()<<"\n";return 1;}

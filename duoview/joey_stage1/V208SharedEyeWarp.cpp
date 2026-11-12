// v208 pixel-level contract on WARP (D3D12 debug layer on) for the PATCHED
// production compositor:
//  - every XR command slot shares ONE Mono compose texture;
//  - "Same image for both eyes" writes the composed Mono image into the LEFT
//    half only (copy route, direct-raster route and gather route), leaving the
//    right half untouched, with left-half pixels identical to v207 output;
//  - OFF keeps v207 behavior: both halves identical.
#include <windows.h>
#include "DuoViewD3D12.hpp"
#include <dxgi1_6.h>
#include <d3d12sdklayers.h>
#include <array>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>
using Microsoft::WRL::ComPtr;

static void check(HRESULT h) { if (FAILED(h)) throw std::runtime_error("D3D12 failure " + std::to_string(static_cast<uint32_t>(h))); }
static D3D12_HEAP_PROPERTIES heap(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES h{}; h.Type=type; h.CreationNodeMask=h.VisibleNodeMask=1; return h;
}
static D3D12_RESOURCE_DESC texture(UINT w, UINT h, DXGI_FORMAT format, D3D12_RESOURCE_FLAGS flags) {
    D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width=w; d.Height=h; d.DepthOrArraySize=d.MipLevels=1; d.Format=format;
    d.SampleDesc.Count=1; d.Flags=flags; return d;
}
static D3D12_RESOURCE_DESC buffer(UINT64 size) {
    D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
    d.Width=size; d.Height=d.DepthOrArraySize=d.MipLevels=1;
    d.SampleDesc.Count=1; d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR; return d;
}
static ComPtr<ID3D12Resource> resource(ID3D12Device* device, D3D12_RESOURCE_DESC desc,
    D3D12_HEAP_TYPE type, D3D12_RESOURCE_STATES state) {
    auto hp=heap(type); ComPtr<ID3D12Resource> r;
    check(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&r))); return r;
}
static void transition(ID3D12GraphicsCommandList* cmd, ID3D12Resource* r, D3D12_RESOURCE_STATES a, D3D12_RESOURCE_STATES b) {
    D3D12_RESOURCE_BARRIER barrier{}; barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,a,b}; cmd->ResourceBarrier(1,&barrier);
}

struct Gpu {
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> cmd;
    ComPtr<ID3D12Fence> fence;
    UINT64 value{};
    void submit_and_wait() {
        check(cmd->Close());
        ID3D12CommandList* lists[]{cmd.Get()};
        queue->ExecuteCommandLists(1,lists);
        check(queue->Signal(fence.Get(),++value));
        auto event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        check(fence->SetEventOnCompletion(value,event));
        if (WaitForSingleObject(event,30000)!=WAIT_OBJECT_0) throw std::runtime_error("GPU timeout");
        CloseHandle(event);
        check(allocator->Reset()); check(cmd->Reset(allocator.Get(),nullptr));
    }
};

static ComPtr<ID3D12Resource> solid_source(Gpu& g, std::vector<ComPtr<ID3D12Resource>>& keep,
                                           UINT w, UINT h, std::array<uint8_t,4> bgra) {
    auto desc=texture(w,h,DXGI_FORMAT_B8G8R8A8_TYPELESS,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
    auto tex=resource(g.device.Get(),desc,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT foot{}; UINT64 bytes{};
    g.device->GetCopyableFootprints(&desc,0,1,0,&foot,nullptr,nullptr,&bytes);
    foot.Footprint.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
    auto upload=resource(g.device.Get(),buffer(bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    void* mapped{}; D3D12_RANGE zero{0,0}; check(upload->Map(0,&zero,&mapped));
    std::memset(mapped,0,static_cast<size_t>(bytes));
    for (UINT y=0;y<h;++y) for (UINT x=0;x<w;++x)
        std::memcpy(static_cast<uint8_t*>(mapped)+y*foot.Footprint.RowPitch+x*4,bgra.data(),4);
    upload->Unmap(0,nullptr);
    D3D12_TEXTURE_COPY_LOCATION from{upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT}; from.PlacedFootprint=foot;
    D3D12_TEXTURE_COPY_LOCATION to{tex.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
    g.cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    transition(g.cmd.Get(),tex.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
    keep.push_back(upload);
    return tex;
}

int main() try {
    ComPtr<ID3D12Debug> debug;
    if (SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)))) debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory; check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIAdapter> adapter; check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
    Gpu g;
    check(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&g.device)));
    D3D12_COMMAND_QUEUE_DESC q{}; q.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    check(g.device->CreateCommandQueue(&q,IID_PPV_ARGS(&g.queue)));
    check(g.device->CreateCommandAllocator(q.Type,IID_PPV_ARGS(&g.allocator)));
    check(g.device->CreateCommandList(0,q.Type,g.allocator.Get(),nullptr,IID_PPV_ARGS(&g.cmd)));
    check(g.device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&g.fence)));
    ComPtr<ID3D12InfoQueue> info; if (SUCCEEDED(g.device.As(&info))) info->ClearStoredMessages();

    std::vector<ComPtr<ID3D12Resource>> keep;
    auto primary=solid_source(g,keep,32,32,{0,0,255,255});    // fovea: red
    auto secondary=solid_source(g,keep,32,32,{255,0,0,255});  // periphery: blue
    auto stereo=resource(g.device.Get(),texture(64,32,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),
        D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
    const auto sdesc=stereo->GetDesc(); D3D12_PLACED_SUBRESOURCE_FOOTPRINT foot{}; UINT64 bytes{};
    g.device->GetCopyableFootprints(&sdesc,0,1,0,&foot,nullptr,nullptr,&bytes);
    auto readback=resource(g.device.Get(),buffer(bytes),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
    ComPtr<ID3D12DescriptorHeap> rtv_heap;
    D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.NumDescriptors=1; hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    check(g.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&rtv_heap)));
    const auto rtv=rtv_heap->GetCPUDescriptorHandleForHeapStart();
    g.device->CreateRenderTargetView(stereo.Get(),nullptr,rtv);
    g.submit_and_wait(); // upload sources

    auto layout=uevr::duoview::make_layout(32,32,.5f,.5f,.25f,1.f,.5f,.5f);
    if (!layout) throw std::runtime_error("Invalid test layout");
    uevr::duoview::ViewFrame frame{};
    frame.config={{1,80},*layout,{.5f,.5f},{},1};

    auto a=std::make_unique<uevr::duoview::dx12::Compositor>();
    auto b=std::make_unique<uevr::duoview::dx12::Compositor>();
    if (!a->prewarm(g.device.Get(),32,32,false,0) || !b->prewarm(g.device.Get(),32,32,false,0))
        throw std::runtime_error("Prewarm failed");
    if (!a->output_resource() || a->output_resource()!=b->output_resource())
        throw std::runtime_error("XR command slots do not share one compose texture");

    enum class Route { copy, direct, gather };
    std::vector<uint8_t> reference;
    auto run=[&](uevr::duoview::dx12::Compositor& c, bool shared, Route route, const char* name) {
        const float green[4]{0.f,1.f,0.f,1.f};
        g.cmd->ClearRenderTargetView(rtv,green,0,nullptr);
        frame.config.key.frame++;
        frame.config.settings.shared_eye_image=shared;
        frame.config.settings.direct_xr_output=route==Route::direct;
        const bool ok=route==Route::gather
            ? c.record_native_gather(g.device.Get(),g.cmd.Get(),primary.Get(),secondary.Get(),stereo.Get(),
                D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,frame,std::make_shared<const int>(1),0)
            : c.record_native(g.device.Get(),g.cmd.Get(),primary.Get(),secondary.Get(),stereo.Get(),
                D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,frame,std::make_shared<const int>(1),0);
        if (!ok) throw std::runtime_error(std::string(name)+": record failed: "+c.error());
        if (route!=Route::gather && c.last_native_direct_xr()!=(route==Route::direct))
            throw std::runtime_error(std::string(name)+": wrong XR output route");
        transition(g.cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION from{stereo.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
        D3D12_TEXTURE_COPY_LOCATION to{readback.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT}; to.PlacedFootprint=foot;
        g.cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
        transition(g.cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
        g.submit_and_wait();
        void* mapped{}; D3D12_RANGE read{0,static_cast<size_t>(bytes)}; check(readback->Map(0,&read,&mapped));
        auto px=[&](UINT x,UINT y){ return static_cast<const uint8_t*>(mapped)+y*foot.Footprint.RowPitch+x*4; };
        const uint8_t sentinel[4]{0,255,0,255};
        if (px(16,16)[2]<220 || px(1,1)[0]<220) throw std::runtime_error(std::string(name)+": composed left-eye pixels wrong");
        std::vector<uint8_t> left(32*32*4);
        for (UINT y=0;y<32;++y) for (UINT x=0;x<32;++x) {
            if (!std::memcmp(px(x,y),sentinel,4)) throw std::runtime_error(std::string(name)+": left half not composed");
            std::memcpy(left.data()+(y*32+x)*4,px(x,y),4);
            const bool right_untouched=!std::memcmp(px(x+32,y),sentinel,4);
            const bool right_copy=!std::memcmp(px(x+32,y),px(x,y),4);
            if (shared && !right_untouched) throw std::runtime_error(std::string(name)+": right half was written in shared mode");
            if (!shared && !right_copy) throw std::runtime_error(std::string(name)+": eyes differ with shared mode OFF");
        }
        readback->Unmap(0,nullptr);
        // Routes use different (proven) shaders; allow 2 levels of rounding.
        if (reference.empty()) reference=left;
        else for (size_t i=0;i<left.size();++i)
            if (std::abs(int(left[i])-int(reference[i]))>2)
                throw std::runtime_error(std::string(name)+": left-eye image differs from v207 route");
        std::cout << "PASS: " << name << "\n";
    };
    run(*a,false,Route::copy,"v207 copy route (both eyes identical)");
    run(*b,true,Route::copy,"v208 shared copy route (slot B, shared texture)");
    run(*a,true,Route::direct,"v208 shared direct raster route");
    run(*b,false,Route::direct,"v207 direct raster route");
    run(*a,true,Route::gather,"v208 shared gather fallback route");

    // A slot with another extent must get its own texture; the old slot keeps working.
    auto c=std::make_unique<uevr::duoview::dx12::Compositor>();
    if (!c->prewarm(g.device.Get(),40,32,false,0) || !c->output_resource() || c->output_resource()==a->output_resource())
        throw std::runtime_error("Different extent reused the wrong compose texture");
    run(*a,true,Route::copy,"old slot after extent change");
    a.reset(); b.reset(); c.reset();
    uevr::duoview::dx12::release_shared_output();
    auto d=std::make_unique<uevr::duoview::dx12::Compositor>();
    if (!d->prewarm(g.device.Get(),32,32,false,0) || !d->output_resource())
        throw std::runtime_error("Compose texture not recreated after release");
    run(*d,true,Route::copy,"recreated after release");

    if (info) {
        UINT64 errors=0;
        for (UINT64 i=0;i<info->GetNumStoredMessages();++i) {
            SIZE_T size=0; info->GetMessage(i,nullptr,&size);
            std::vector<uint8_t> storage(size); auto* m=reinterpret_cast<D3D12_MESSAGE*>(storage.data());
            if (SUCCEEDED(info->GetMessage(i,m,&size)) &&
                (m->Severity==D3D12_MESSAGE_SEVERITY_ERROR || m->Severity==D3D12_MESSAGE_SEVERITY_CORRUPTION)) {
                ++errors; std::cerr << "D3D12 debug: " << m->pDescription << "\n";
            }
        }
        if (errors) throw std::runtime_error("D3D12 debug layer reported errors");
    }
    std::cout << "PASS: v208 shared compose texture + same image for both eyes (WARP, debug layer)\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr << "FAIL: " << e.what() << "\n";
    return 1;
}

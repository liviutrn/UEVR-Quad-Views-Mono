// B30: isolated focus-brightness compensation through the production compositor.
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include "QuadViewD3D12.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
using namespace uevr::quadview;

static void require(HRESULT hr, const char* what) {
    if (FAILED(hr)) throw std::runtime_error(std::string(what) + ": " + std::to_string(hr));
}
static void check(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}
static D3D12_RESOURCE_DESC texture(uint32_t w, uint32_t h, D3D12_RESOURCE_FLAGS flags) {
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D; d.Width = w; d.Height = h;
    d.DepthOrArraySize = d.MipLevels = 1; d.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    d.SampleDesc.Count = 1; d.Flags = flags;
    return d;
}
static D3D12_RESOURCE_DESC buffer(uint64_t bytes) {
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; d.Width = bytes; d.Height = 1;
    d.DepthOrArraySize = d.MipLevels = 1; d.Format = DXGI_FORMAT_UNKNOWN;
    d.SampleDesc.Count = 1; d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    return d;
}
static ComPtr<ID3D12Resource> make_resource(ID3D12Device* device, const D3D12_RESOURCE_DESC& desc,
        D3D12_HEAP_TYPE type, D3D12_RESOURCE_STATES state) {
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = type; heap.CreationNodeMask = heap.VisibleNodeMask = 1;
    ComPtr<ID3D12Resource> out;
    require(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, state, nullptr,
        IID_PPV_ARGS(&out)), "CreateCommittedResource");
    return out;
}

struct Gpu {
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12Fence> fence;
    HANDLE event{};
    uint64_t fence_value{};
    ~Gpu() { if (event) CloseHandle(event); }
    void wait() {
        require(queue->Signal(fence.Get(), ++fence_value), "Signal fence");
        if (fence->GetCompletedValue() < fence_value) {
            require(fence->SetEventOnCompletion(fence_value, event), "SetEventOnCompletion");
            WaitForSingleObject(event, INFINITE);
        }
    }
};

struct SourceSet {
    std::array<ComPtr<ID3D12Resource>, 4> textures;
};

static SourceSet make_sources(Gpu& gpu, const Layout& layout, std::array<std::array<uint8_t, 4>, 4> colors,
                              bool focus_gradient = false) {
    const auto extents = source_extents(layout);
    SourceSet result;
    std::array<ComPtr<ID3D12Resource>, 4> uploads;
    for (unsigned i = 0; i != 4; ++i) {
        result.textures[i] = make_resource(gpu.device.Get(), texture(extents[i][0], extents[i][1], D3D12_RESOURCE_FLAG_NONE),
            D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
        const uint32_t row_pitch = (extents[i][0] * 4 + 255u) & ~255u;
        const uint64_t bytes = uint64_t(row_pitch) * extents[i][1];
        uploads[i] = make_resource(gpu.device.Get(), buffer(bytes), D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
        uint8_t* mapped{}; D3D12_RANGE no_read{0, 0};
        require(uploads[i]->Map(0, &no_read, reinterpret_cast<void**>(&mapped)), "Map source upload");
        for (uint32_t y = 0; y != extents[i][1]; ++y)
            for (uint32_t x = 0; x != extents[i][0]; ++x) {
                auto color = colors[i];
                if (focus_gradient && i >= 2) {
                    const auto& rect = layout.views[i];
                    const float u = (float(x) + .5f - float(rect.x)) / float(rect.width);
                    const auto value = uint8_t((std::clamp)(80.f + 40.f * u, 0.f, 255.f));
                    color = {value,value,value,255};
                }
                std::memcpy(mapped + size_t(y) * row_pitch + size_t(x) * 4, color.data(), 4);
            }
        D3D12_RANGE no_write{0, 0}; uploads[i]->Unmap(0, &no_write);
    }
    ComPtr<ID3D12CommandAllocator> allocator;
    require(gpu.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)), "Create upload allocator");
    ComPtr<ID3D12GraphicsCommandList> list;
    require(gpu.device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr, IID_PPV_ARGS(&list)), "Create upload list");
    for (unsigned i = 0; i != 4; ++i) {
        const uint32_t w = extents[i][0], h = extents[i][1];
        D3D12_TEXTURE_COPY_LOCATION from{}; from.pResource = uploads[i].Get(); from.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        from.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM, w, h, 1, (w * 4 + 255u) & ~255u};
        D3D12_TEXTURE_COPY_LOCATION to{}; to.pResource = result.textures[i].Get(); to.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        list->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
        D3D12_RESOURCE_BARRIER barrier{}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition = {result.textures[i].Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
            D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE};
        list->ResourceBarrier(1, &barrier);
    }
    require(list->Close(), "Close upload list");
    ID3D12CommandList* lists[]{list.Get()}; gpu.queue->ExecuteCommandLists(1, lists); gpu.wait();
    return result;
}

struct Pixels {
    ComPtr<ID3D12Resource> readback;
    uint32_t row_pitch{}, width{}, height{};
    std::vector<uint8_t> rgba;
    std::array<uint8_t, 4> at(uint32_t x, uint32_t y) const {
        const size_t p = (size_t(y) * width + x) * 4;
        return {rgba[p], rgba[p + 1], rgba[p + 2], rgba[p + 3]};
    }
};

static Pixels draw(Gpu& gpu, uevr::quadview::dx12::Compositor& compositor,
                   const SourceSet& sources, ID3D12Resource* output, const Layout& layout,
                   Settings settings) {
    ComPtr<ID3D12CommandAllocator> allocator;
    require(gpu.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)), "Create draw allocator");
    ComPtr<ID3D12GraphicsCommandList> list;
    require(gpu.device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr, IID_PPV_ARGS(&list)), "Create draw list");
    auto owner = std::make_shared<uint64_t>(gpu.fence_value + 1);
    const std::array<ID3D12Resource*, 4> raw{sources.textures[0].Get(), sources.textures[1].Get(),
        sources.textures[2].Get(), sources.textures[3].Get()};
    const bool recorded = compositor.record_sources(list.Get(), raw, output, layout, settings,
        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_SOURCE, owner);
    check(recorded, compositor.error());
    D3D12_RESOURCE_DESC output_desc = output->GetDesc();
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; UINT rows{}; UINT64 row_bytes{}, total{};
    gpu.device->GetCopyableFootprints(&output_desc, 0, 1, 0, &fp, &rows, &row_bytes, &total);
    auto readback = make_resource(gpu.device.Get(), buffer(total), D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_TEXTURE_COPY_LOCATION from{}; from.pResource = output; from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    D3D12_TEXTURE_COPY_LOCATION to{}; to.pResource = readback.Get(); to.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; to.PlacedFootprint = fp;
    list->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
    require(list->Close(), "Close draw list");
    ID3D12CommandList* lists[]{list.Get()}; gpu.queue->ExecuteCommandLists(1, lists); gpu.wait();
    compositor.on_slot_retired();
    Pixels result; result.readback = readback; result.width = uint32_t(output_desc.Width); result.height = output_desc.Height;
    result.row_pitch = fp.Footprint.RowPitch; result.rgba.resize(size_t(result.width) * result.height * 4);
    void* mapped_void{}; D3D12_RANGE read_range{0, SIZE_T(total)};
    require(readback->Map(0, &read_range, &mapped_void), "Map output readback");
    const auto* mapped = static_cast<const uint8_t*>(mapped_void);
    for (uint32_t y = 0; y != result.height; ++y)
        std::memcpy(result.rgba.data() + size_t(y) * result.width * 4, mapped + size_t(y) * fp.Footprint.RowPitch, size_t(result.width) * 4);
    D3D12_RANGE no_write{0, 0}; readback->Unmap(0, &no_write);
    return result;
}

int main() try {
    ComPtr<ID3D12Debug> debug;
    if (SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)))) debug->EnableDebugLayer();
    constexpr uint32_t eye_w=64,eye_h=64;
    const auto candidate=make_layout(eye_w,eye_h,.5f,.5f,.25f,1.f);
    check(candidate.has_value(),"Focus lift layout failed"); const auto layout=*candidate;
    ComPtr<IDXGIFactory4> factory;require(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"Create factory");
    ComPtr<IDXGIAdapter> adapter;require(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)),"WARP adapter");
    Gpu gpu;require(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&gpu.device)),"Device");
    ComPtr<ID3D12InfoQueue> info;gpu.device.As(&info);
    D3D12_COMMAND_QUEUE_DESC q{};q.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    require(gpu.device->CreateCommandQueue(&q,IID_PPV_ARGS(&gpu.queue)),"Queue");
    require(gpu.device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&gpu.fence)),"Fence");
    gpu.event=CreateEventW(nullptr,FALSE,FALSE,nullptr);check(gpu.event!=nullptr,"Event");
    auto output=make_resource(gpu.device.Get(),texture(eye_w*2,eye_h,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),
        D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_SOURCE);
    uevr::quadview::dx12::Compositor compositor;
    check(compositor.prewarm(gpu.device.Get(),DXGI_FORMAT_R8G8B8A8_UNORM,DXGI_FORMAT_R8G8B8A8_UNORM),compositor.error());
    const auto sources=make_sources(gpu,layout,{{{77,77,77,255},{77,77,77,255},{102,102,102,255},{102,102,102,255}}});
    Settings off{};off.context_scale=.25f;off.feather_fraction=0.f;off.sharpen_strength=0.f;
    off.focus_lift_enabled=false;
    const auto baseline=draw(gpu,compositor,sources,output.Get(),layout,off);
    Settings active=off;active.focus_lift_enabled=true;
    const auto lifted=draw(gpu,compositor,sources,output.Get(),layout,active);
    for(uint32_t eye=0;eye<2;++eye) for(uint32_t y=0;y<eye_h;++y) for(uint32_t x=0;x<eye_w;++x) {
        const float u=(x+.5f)/eye_w,v=(y+.5f)/eye_h;
        const auto actual=lifted.at(x+eye*eye_w,y);
        if(u<.25f||u>.75f||v<.25f||v>.75f) {
            check(actual==baseline.at(x+eye*eye_w,y),"Foveal correction changed the periphery");
        } else {
            const float fu=(u-.25f)/.5f,fv=(v-.25f)/.5f;
            const int expected=int(std::lround(102.f*focus_lift::gain(fu,fv)));
            check(std::abs(int(actual[0])-expected)<=1,"GPU correction differs from fitted CPU profile");
            check(actual[0]==actual[1]&&actual[1]==actual[2],"Brightness correction introduced a tint");
        }
    }
    check(lifted.at(32,32)==baseline.at(32,32),"Neutral center changed");
    check(lifted.at(17,17)[0]>lifted.at(32,32)[0],"Corners not lifted");
    Settings brighter=active;brighter.focus_brightness=1.05f;
    const auto bright=draw(gpu,compositor,sources,output.Get(),layout,brighter);
    check(bright.at(32,32)[0]>lifted.at(32,32)[0],"Overall brightness control failed");
    check(bright.at(4,32)==baseline.at(4,32),"Overall focus brightness changed periphery");
    brighter.focus_lift_enabled=false;
    check(draw(gpu,compositor,sources,output.Get(),layout,brighter).rgba==baseline.rgba,"Disabled correction did not restore exact baseline");
    Settings zero=active;zero.focus_lift_strength=0.f;
    check(draw(gpu,compositor,sources,output.Get(),layout,zero).rgba==baseline.rgba,"Zero anti-vignette strength changed image");
    if(info) for(UINT64 i=0,n=info->GetNumStoredMessages();i<n;++i) {
        SIZE_T size{};info->GetMessage(i,nullptr,&size);std::vector<uint8_t> memory(size);
        auto* message=reinterpret_cast<D3D12_MESSAGE*>(memory.data());
        require(info->GetMessage(i,message,&size),"Debug message");
        if(message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR) throw std::runtime_error(message->pDescription);
    }
    std::cout<<"Focus lift WARP: fitted profile, both eyes, neutral center, corner lift, manual brightness, exact periphery/off/zero identity passed\n";
    return 0;
} catch(const std::exception& e) {std::cerr<<"Focus lift WARP FAILED: "<<e.what()<<'\n';return 1;}

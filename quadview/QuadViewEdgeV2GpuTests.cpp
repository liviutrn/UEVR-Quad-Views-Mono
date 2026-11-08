// B35/B36: production compositor / shader coverage for Edge Match V2.
// Windows-only WARP executable; no shader/math substitute is used here.
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
                              int focus_gradient = 0) {
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
                if (focus_gradient > 0 && focus_gradient <= 2 && i >= 2) {
                    const auto& rect = layout.views[i];
                    const float u = (std::clamp)((float(x) + .5f - float(rect.x)) / float(rect.width), 0.f, 1.f);
                    const float v = (std::clamp)((float(y) + .5f - float(rect.y)) / float(rect.height), 0.f, 1.f);
                    // A colored border differs substantially from the interior,
                    // catching probes inset by a context texel rather than at
                    // the displayed border. Smooth tangential slopes exercise
                    // sampling without making one-pixel comparisons ambiguous.
                    const float rim = (u < .04f || u > .96f || v < .04f || v > .96f) ? 45.f : 0.f;
                    color = {uint8_t(55.f + 35.f*u + rim), uint8_t(45.f + 25.f*v + rim),
                             uint8_t(35.f + 20.f*u + 20.f*v + rim), 255};
                    if (focus_gradient==2)
                        color={uint8_t(40.f+180.f*u),uint8_t(30.f+180.f*v),
                               uint8_t(40.f+80.f*u+80.f*v),255};
                }
                // B36 fixtures use source-local integer pixels, including dark
                // allocation margins outside the logical native focus rectangle.
                if (focus_gradient >= 3 && i >= 2) {
                    const auto& r=layout.views[i];
                    const bool inside=x>=r.x && x<r.x+r.width && y>=r.y && y<r.y+r.height;
                    if (!inside) color={0,0,0,255};
                    else {
                        const uint32_t sx=x-r.x, sy=y-r.y;
                        const uint32_t rim=focus_gradient==4 ? (i==2 ? 8u : 5u) : (i==2 ? 5u : 8u);
                        if ((focus_gradient==3 || focus_gradient==4) && sx>=r.width-rim)
                            color={0,0,0,255};
                        if (focus_gradient==5) color={0,0,0,255};
                        if (focus_gradient==6 && sx>=r.width/3 && sx<2*r.width/3 &&
                            sy>=r.height/3 && sy<2*r.height/3) color={0,0,0,255};
                        // The rim is black only on separated horizontal bands;
                        // multiple detector probes see lit edge content.
                        if (focus_gradient==7 && sx>=r.width-rim && (sy/16u)%2u==0u)
                            color={0,0,0,255};
                        if (focus_gradient==8)
                            color=(sx/2u)%2u ? std::array<uint8_t,4>{210,55,170,255}
                                                       : std::array<uint8_t,4>{45,160,70,255};
                    }
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
                   Settings settings, const uevr::quadview::dx12::DepthInput* depth = nullptr,
                   uint64_t generation = 1, uint32_t time_ms = 1000) {
    ComPtr<ID3D12CommandAllocator> allocator;
    require(gpu.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)), "Create draw allocator");
    ComPtr<ID3D12GraphicsCommandList> list;
    require(gpu.device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr, IID_PPV_ARGS(&list)), "Create draw list");
    auto owner = std::make_shared<uint64_t>(gpu.fence_value + 1);
    const std::array<ID3D12Resource*, 4> raw{sources.textures[0].Get(), sources.textures[1].Get(),
        sources.textures[2].Get(), sources.textures[3].Get()};
    const bool recorded = compositor.record_sources(list.Get(), raw, output, layout, settings,
        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_SOURCE, owner, 0, depth, generation, time_ms);
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


using Compositor = uevr::quadview::dx12::Compositor;
using Color = std::array<uint8_t,4>;
static void close_rgb(Color actual, Color expected, int tolerance, const char* message) {
    for (unsigned c=0;c<3;++c) if (std::abs(int(actual[c])-int(expected[c]))>tolerance)
        throw std::runtime_error(std::string(message)+" channel="+std::to_string(c)+
            " actual="+std::to_string(actual[c])+" expected="+std::to_string(expected[c]));
    check(actual[3]==255,"Output alpha is not opaque");
}
// Compare the first context pixel outside the ACTUAL crop against the nearest
// displayed focus pixel. Include all sides and diagonal corners in both eyes.
// Smooth spatial decay at pixel centers permits a few quantization steps.
static void check_border(const Pixels& image, const Layout& layout, int tolerance=3) {
    for (uint32_t eye=0;eye<2;++eye) {
        const auto crop=layout.focus_crops[eye];
        const int loX=int(std::ceil(crop.u0*layout.eye_width-.5f));
        const int hiX=int(std::ceil(crop.u1*layout.eye_width-.5f))-1;
        const int loY=int(std::ceil(crop.v0*layout.eye_height-.5f));
        const int hiY=int(std::ceil(crop.v1*layout.eye_height-.5f))-1;
        const int mx=(loX+hiX)/2, my=(loY+hiY)/2;
        const std::array<std::array<int,4>,8> pairs{{
            {{mx,loY-1,mx,loY}},{{hiX+1,my,hiX,my}},
            {{mx,hiY+1,mx,hiY}},{{loX-1,my,loX,my}},
            {{loX-1,loY-1,loX,loY}},{{hiX+1,loY-1,hiX,loY}},
            {{hiX+1,hiY+1,hiX,hiY}},{{loX-1,hiY+1,loX,hiY}}}};
        for (const auto& p:pairs)
            close_rgb(image.at(eye*layout.eye_width+p[0],p[1]),
                      image.at(eye*layout.eye_width+p[2],p[3]),tolerance,"Visible border mismatch");
    }
}
static void focus_unchanged(const Pixels& actual, const Pixels& reference, const Layout& layout) {
    for (uint32_t eye=0;eye<2;++eye) {
        const auto c=layout.focus_crops[eye];
        for (uint32_t y=0;y<layout.eye_height;++y)
            for (uint32_t x=0;x<layout.eye_width;++x) {
                const float u=(x+.5f)/layout.eye_width,v=(y+.5f)/layout.eye_height;
                if (u>=c.u0 && u<=c.u1 && v>=c.v0 && v<=c.v1)
                    check(actual.at(eye*layout.eye_width+x,y)==reference.at(eye*layout.eye_width+x,y),
                          "Edge match altered an opaque focus pixel");
            }
    }
}
int main() try {
    ComPtr<ID3D12Debug> debug;
    if (SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)))) debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory; require(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"CreateDXGIFactory1");
    ComPtr<IDXGIAdapter> adapter; require(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)),"EnumWarpAdapter");
    Gpu gpu;
    require(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&gpu.device)),"D3D12CreateDevice");
    ComPtr<ID3D12InfoQueue> info; gpu.device.As(&info);
    D3D12_COMMAND_QUEUE_DESC qd{}; qd.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    require(gpu.device->CreateCommandQueue(&qd,IID_PPV_ARGS(&gpu.queue)),"CreateCommandQueue");
    require(gpu.device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&gpu.fence)),"CreateFence");
    gpu.event=CreateEventW(nullptr,FALSE,FALSE,nullptr); check(gpu.event!=nullptr,"CreateEventW");
    const auto maybe=make_layout(256,256,.5f,.5f,.25f,1.f);
    check(maybe.has_value(),"Create layout"); const Layout layout=*maybe;
    auto output=make_resource(gpu.device.Get(),texture(512,256,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),
        D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_SOURCE);
    auto prepare=[&](Compositor& c) {
        check(c.prewarm(gpu.device.Get(),DXGI_FORMAT_R8G8B8A8_UNORM,DXGI_FORMAT_R8G8B8A8_UNORM),c.error());
    };
    Settings off{}; off.crop_width=off.crop_height=.5f; off.context_scale=.25f;
    off.feather_fraction=0.f; off.sharpen_strength=0.f;
    Settings instant=off; instant.seam_mode=3; instant.seam_strength=1.f;
    instant.seam_transition_px=0.f; instant.edge_reach_px=64.f; instant.edge_fast_px=8.f;
    instant.edge_rate=.15f; instant.edge_hysteresis=.004f;
    Settings temporal=instant; temporal.seam_mode=4;
    Compositor immediate; prepare(immediate);
    uint32_t clock=1000;
    const auto render=[&](Compositor& c,const SourceSet& source,const Layout& l,Settings s,
                           uint64_t gen=1,const uevr::quadview::dx12::DepthInput* depth=nullptr) {
        clock+=16; return draw(gpu,c,source,output.Get(),l,s,depth,gen,clock);
    };
    // Ratios above 2x, black context, signed residuals, dissimilar RGB and
    // different eyes are valid additive cases, not low-confidence gain fits.
    const std::array<std::array<Color,4>,4> cases{{
        {{{20,20,20,255},{70,70,70,255},{190,190,190,255},{230,230,230,255}}},
        {{{0,1,2,255},{2,0,1,255},{12,28,48,255},{55,18,9,255}}},
        {{{210,180,240,255},{150,225,190,255},{22,70,40,255},{65,20,90,255}}},
        {{{15,120,40,255},{130,20,100,255},{200,35,180,255},{25,190,45,255}}}
    }};
    for (const auto& colors:cases) {
        const auto sources=make_sources(gpu,layout,colors);
        const auto reference=render(immediate,sources,layout,off);
        const auto image=render(immediate,sources,layout,instant);
        check_border(image,layout); focus_unchanged(image,reference,layout);
        Settings zero=instant; zero.seam_strength=0.f;
        check(render(immediate,sources,layout,zero).rgba==reference.rgba,"Zero edge strength changed output");
        auto history=uevr::quadview::dx12::EdgeHistoryState::create(gpu.device.Get(),gpu.queue.Get());
        check(bool(history),"Create temporal history"); Compositor t; prepare(t); t.set_edge_history(history);
        check(t.edge_submission_queue()==gpu.queue.Get(),"Temporal compositor lost its submission queue");
        const auto first=render(t,sources,layout,temporal);
        check(first.rgba==image.rgba,"First temporal frame differs from instant initialization");
    }
    // Noninteger/asymmetric crops ensure comparisons track the actual display
    // border. The nearest border is colored unlike the interior; sharpening
    // and calibrated anti-vignette remain enabled for the reference image.
    Layout asymmetric=layout;
    asymmetric.focus_crops[0]={.253f,.247f,.753f,.747f};
    asymmetric.focus_crops[1]={.237f,.261f,.737f,.761f};
    const auto textured=make_sources(gpu,asymmetric,cases[0],true);
    Settings appearance=instant; appearance.sharpen_strength=1.4f;
    appearance.focus_lift_enabled=true; appearance.focus_brightness=1.05f;
    Settings appearanceOff=appearance; appearanceOff.seam_mode=0;
    const auto display=render(immediate,textured,asymmetric,appearanceOff);
    const auto matched=render(immediate,textured,asymmetric,appearance);
    check_border(matched,asymmetric,3); focus_unchanged(matched,display,asymmetric);

    // Measure spatial attenuation using a uniform reference, then apply it
    // to the known nearest displayed border. This checks border projection
    // and perimeter wrap without copying EdgeFade or knot interpolation math.
    const std::array<Color,4> flatColors{{{20,20,20,255},{20,20,20,255},
                                         {120,120,120,255},{120,120,120,255}}};
    const auto flatSources=make_sources(gpu,layout,flatColors);
    const auto rampSources=make_sources(gpu,layout,flatColors,2);
    const auto flatField=render(immediate,flatSources,layout,instant);
    const auto rampDisplay=render(immediate,rampSources,layout,off);
    const auto rampField=render(immediate,rampSources,layout,instant);
    const std::array<std::array<uint32_t,4>,4> broadPairs{{
        {{96,16,96,64}},{{159,16,159,64}},
        {{32,48,64,64}},{{32,207,64,191}}}};
    for (uint32_t eye=0;eye<2;++eye) for (const auto& p:broadPairs) {
        const auto border=rampDisplay.at(eye*256+p[2],p[3]);
        const float attenuation=(float(flatField.at(eye*256+p[0],p[1])[0])-20.f)/100.f;
        auto expected=border;
        for (unsigned c=0;c<3;++c)
            expected[c]=uint8_t(std::lround(20.f+attenuation*(float(border[c])-20.f)));
        close_rgb(rampField.at(eye*256+p[0],p[1]),expected,3,
                  "Broad field followed wrong border or failed corner wrap");
    }

    const auto dark=make_sources(gpu,layout,{{{40,40,40,255},{40,40,40,255},{80,80,80,255},{80,80,80,255}}});
    const auto bright=make_sources(gpu,layout,{{{40,40,40,255},{40,40,40,255},{200,25,160,255},{20,190,100,255}}});
    // Two physical command slots share ONE queue history. Compare every frame
    // to a separate single-slot run with identical inputs/timestamps. A slot-
    // local history causes alternating phases after the color switch.
    auto shared=uevr::quadview::dx12::EdgeHistoryState::create(gpu.device.Get(),gpu.queue.Get());
    auto serial=uevr::quadview::dx12::EdgeHistoryState::create(gpu.device.Get(),gpu.queue.Get());
    check(bool(shared)&&bool(serial),"Create sequence histories");
    Compositor slots[2],single; prepare(slots[0]); prepare(slots[1]); prepare(single);
    slots[0].set_edge_history(shared); slots[1].set_edge_history(shared); single.set_edge_history(serial);
    Pixels previous;
    for (uint32_t frame=0;frame<14;++frame) {
        const auto& source=frame<3 ? dark : bright;
        const uint32_t time=4000+frame*32;
        const auto actual=draw(gpu,slots[frame%2],source,output.Get(),layout,temporal,nullptr,7,time);
        const auto expected=draw(gpu,single,source,output.Get(),layout,temporal,nullptr,7,time);
        check(actual.rgba==expected.rgba,"Shared temporal history depends on command-slot rotation");
        check_border(actual,layout,3);
        // x=32 is 31.5px outside the crop, beyond the 8px immediate band.
        if (frame>=3) for (uint32_t eye=0;eye<2;++eye) for (unsigned c=0;c<3;++c) {
            const int step=int(actual.at(eye*256+32,128)[c])-int(previous.at(eye*256+32,128)[c]);
            check(std::abs(step)<=2,"Broad temporal field exceeded RGB rate bound");
        }
        previous=actual;
    }
    const auto instantBright=render(immediate,bright,layout,instant);
    check(std::abs(int(previous.at(32,128)[0])-int(instantBright.at(32,128)[0]))>20,
          "Broad field jumped directly to the changed target");
    // Reset each category after creating a large lag. Compare to the actual
    // instant compositor rather than duplicating shader interpolation math.
    auto reset_case=[&](Settings changed,Layout changedLayout,uint64_t generation,const char* message) {
        auto h=uevr::quadview::dx12::EdgeHistoryState::create(gpu.device.Get(),gpu.queue.Get());
        check(bool(h),"Create reset history"); Compositor c; prepare(c); c.set_edge_history(h);
        draw(gpu,c,dark,output.Get(),layout,temporal,nullptr,7,6000);
        draw(gpu,c,bright,output.Get(),layout,temporal,nullptr,7,6016);
        const auto actual=draw(gpu,c,bright,output.Get(),changedLayout,changed,nullptr,generation,6032);
        changed.seam_mode=3;
        const auto expected=draw(gpu,immediate,bright,output.Get(),changedLayout,changed,nullptr,generation,6048);
        check(actual.rgba==expected.rgba,message);
    };
    reset_case(temporal,layout,8,"Scene generation failed to reset temporal history");
    Settings changedRate=temporal; changedRate.edge_rate=.2f;
    reset_case(changedRate,layout,7,"Rate setting failed to reset temporal history");
    Settings changedReach=temporal; changedReach.edge_reach_px=72.f;
    reset_case(changedReach,layout,7,"Reach setting failed to reset temporal history");
    Layout moved=layout; for (auto& crop:moved.focus_crops) { crop.u0+=.02f; crop.u1+=.02f; }
    reset_case(temporal,moved,7,"Crop relocation failed to reset temporal history");

    // Sub-threshold sensor noise must not move the broad field; a larger
    // persistent change must resume tracking within the configured rate.
    auto quietHistory=uevr::quadview::dx12::EdgeHistoryState::create(gpu.device.Get(),gpu.queue.Get());
    check(bool(quietHistory),"Create hysteresis history");
    Compositor quiet; prepare(quiet); quiet.set_edge_history(quietHistory);
    const auto quietStart=draw(gpu,quiet,dark,output.Get(),layout,temporal,nullptr,11,8000);
    const auto noise=make_sources(gpu,layout,{{{40,40,40,255},{40,40,40,255},
                                              {82,82,82,255},{82,82,82,255}}});
    for (uint32_t n=1;n<=8;++n) {
        const auto held=draw(gpu,quiet,noise,output.Get(),layout,temporal,nullptr,11,8000+n*50);
        for (uint32_t eye=0;eye<2;++eye)
            check(held.at(eye*256+32,128)==quietStart.at(eye*256+32,128),
                  "Hysteresis accumulated sub-threshold noise in broad field");
    }
    const auto stepSource=make_sources(gpu,layout,{{{40,40,40,255},{40,40,40,255},
                                                   {96,96,96,255},{96,96,96,255}}});
    const auto resumed=draw(gpu,quiet,stepSource,output.Get(),layout,temporal,nullptr,11,8500);
    for (uint32_t eye=0;eye<2;++eye) {
        const int step=int(resumed.at(eye*256+32,128)[0])-int(quietStart.at(eye*256+32,128)[0]);
        check(step>0 && step<=3,"Hysteresis failed to resume rate-limited tracking");
    }

    Layout sharedLayout=layout; sharedLayout.shared_context=true;
    auto invalidHistory=uevr::quadview::dx12::EdgeHistoryState::create(gpu.device.Get(),gpu.queue.Get());
    check(bool(invalidHistory),"Create invalid-depth history");
    Compositor invalid; prepare(invalid); invalid.set_edge_history(invalidHistory);
    draw(gpu,invalid,bright,output.Get(),sharedLayout,temporal,nullptr,9,7000);
    uevr::quadview::dx12::DepthInput missing{}; missing.reproject=true;
    const auto neutral=draw(gpu,invalid,dark,output.Get(),sharedLayout,temporal,&missing,9,7016);
    const auto plain=draw(gpu,immediate,dark,output.Get(),sharedLayout,off,nullptr,9,7032);
    check(neutral.rgba==plain.rgba,"Invalid depth retained stale edge correction");
    const auto recovered=draw(gpu,invalid,dark,output.Get(),sharedLayout,temporal,nullptr,9,7048);
    const auto fresh=draw(gpu,immediate,dark,output.Get(),sharedLayout,instant,nullptr,9,7064);
    check(recovered.rgba==fresh.rgba,"Invalid depth failed to invalidate temporal history");

    // B36: observed five-column rim and a wider eight-column variant in
    // both eyes. Compare repaired sampling with independently generated clean
    // sources; preserve all pixels safely inside the valid source rectangle.
    const std::array<Color,4> nrColors{{{65,80,105,255},{85,65,95,255},
                                      {145,105,165,255},{110,155,125,255}}};
    Layout compact=layout; check(apply_native_local(compact),"Create compact native layout");
    for (const Layout* testLayout:std::array<const Layout*,2>{&layout,&compact}) {
        const auto& l=*testLayout;
        const auto clean=make_sources(gpu,l,nrColors,9);
        Settings guarded=instant; guarded.edge_padding_guard=true; guarded.sharpen_strength=1.4f;
        Settings unguarded=guarded; unguarded.edge_padding_guard=false;
        const auto cleanImage=render(immediate,clean,l,guarded);
        for (int pattern:{3,4}) {
            const auto padded=make_sources(gpu,l,nrColors,pattern);
            const auto repaired=render(immediate,padded,l,guarded);
            const auto damaged=render(immediate,padded,l,unguarded);
            check_border(repaired,l,3);
            for (uint32_t eye=0;eye<2;++eye) {
                // The actual right crop boundary is x=192, independent of
                // source allocation size, rect offset, or guard width.
                const uint32_t base=eye*l.eye_width;
                for (uint32_t x:{190u,191u,192u,193u,200u})
                    close_rgb(repaired.at(base+x,128),cleanImage.at(base+x,128),2,
                              "Blank rim leaked into focus edge or outside context");
                check(int(repaired.at(base+191,128)[0])-int(damaged.at(base+191,128)[0])>40,
                      "Blank-rim fixture failed to exercise dark focus strip");
                check(int(repaired.at(base+193,128)[0])-int(damaged.at(base+193,128)[0])>20,
                      "Blank-rim fixture failed to exercise outside dark spill");
                for (uint32_t x=80;x<175;++x)
                    check(repaired.at(base+x,128)==damaged.at(base+x,128),
                          "Padding guard moved an interior focus sample");
            }
            // Guard sampling remains useful even with edge correction zero.
            Settings zero=guarded; zero.seam_strength=0.f;
            const auto zeroImage=render(immediate,padded,l,zero);
            for (uint32_t eye=0;eye<2;++eye)
                close_rgb(zeroImage.at(eye*256+191,128),nrColors[eye+2],2,
                          "Zero-strength draw skipped padding analysis");
        }
        for (int pattern:{5,6,7}) {
            const auto scene=make_sources(gpu,l,nrColors,pattern);
            const auto preserved=render(immediate,scene,l,guarded);
            check(preserved.rgba==render(immediate,scene,l,unguarded).rgba,
                  "Padding guard discarded black scene, interior object, or nonuniform edge");
            if (pattern==5 || pattern==6) for (uint32_t eye=0;eye<2;++eye)
                close_rgb(preserved.at(eye*256+128,128),{0,0,0,255},0,
                          "Padding guard erased an interior black sample");
        }
        // A wholly black scene must stay black with either control position.
        const auto black=make_sources(gpu,l,{{{0,0,0,255},{0,0,0,255},
                                            {0,0,0,255},{0,0,0,255}}},5);
        const auto blackImage=render(immediate,black,l,guarded);
        for (size_t p=0;p<blackImage.rgba.size();p+=4)
            check(blackImage.rgba[p]==0 && blackImage.rgba[p+1]==0 && blackImage.rgba[p+2]==0,
                  "Padding guard brightened a wholly black scene");
    }
    // Standard Context/focus feather must affect high-frequency edge blending
    // with V2's explicit transition set to zero, while the opaque center stays.
    const auto highFrequency=make_sources(gpu,compact,nrColors,8);
    Settings hard=instant; hard.sharpen_strength=1.4f; hard.edge_padding_guard=true;
    Settings feathered=hard; feathered.feather_fraction=.3f;
    const auto hardImage=render(immediate,highFrequency,compact,hard);
    const auto featherImage=render(immediate,highFrequency,compact,feathered);
    for (uint32_t eye=0;eye<2;++eye) {
        int changed=0;
        for (uint32_t x=66;x<95;++x) for (unsigned channel=0;channel<3;++channel)
            changed+=std::abs(int(hardImage.at(eye*256+x,128)[channel])-
                              int(featherImage.at(eye*256+x,128)[channel]));
        check(changed>100,"V2 bypassed standard context/focus feather");
        for (uint32_t x=112;x<144;++x)
            check(hardImage.at(eye*256+x,128)==featherImage.at(eye*256+x,128),
                  "Standard feather altered opaque focus center");
    }
    // A detected width change must discard stale broad temporal color, even
    // though layout, settings, and scene generation all remain identical.
    auto rimHistory=uevr::quadview::dx12::EdgeHistoryState::create(gpu.device.Get(),gpu.queue.Get());
    check(bool(rimHistory),"Create rim-width history"); Compositor rimTemporal;
    prepare(rimTemporal); rimTemporal.set_edge_history(rimHistory);
    const auto rimFive=make_sources(gpu,compact,nrColors,3);
    auto changedColors=nrColors; changedColors[2]={210,40,180,255}; changedColors[3]={35,195,95,255};
    const auto rimEight=make_sources(gpu,compact,changedColors,4);
    draw(gpu,rimTemporal,rimFive,output.Get(),compact,temporal,nullptr,21,10000);
    const auto widthChanged=draw(gpu,rimTemporal,rimEight,output.Get(),compact,temporal,nullptr,21,10016);
    const auto widthFresh=draw(gpu,immediate,rimEight,output.Get(),compact,instant,nullptr,21,10032);
    check(widthChanged.rgba==widthFresh.rgba,"Guard-width change failed to reset temporal history");

    if (info) for (UINT64 i=0,n=info->GetNumStoredMessages();i<n;++i) {
        SIZE_T size{}; info->GetMessage(i,nullptr,&size); std::vector<uint8_t> storage(size);
        auto* message=reinterpret_cast<D3D12_MESSAGE*>(storage.data());
        require(info->GetMessage(i,message,&size),"Read debug message");
        if (message->Severity<=D3D12_MESSAGE_SEVERITY_ERROR)
            throw std::runtime_error(std::string("D3D12 Edge V2 validation: ")+message->pDescription);
    }
    std::cout<<"Edge V2 WARP: signed RGB borders/corners, opaque focus, appearance, temporal slew, shared slots, resets, invalid depth, blank rims, compact margins and standard feather passed.\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr<<"Edge V2 WARP FAILED: "<<e.what()<<'\n'; return 1;
}

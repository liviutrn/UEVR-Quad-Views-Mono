// Tri-View: run the real compositor (precompiled shader + PSO) on the D3D12 WARP device and check pixels:
// own fovea in each eye centre, periphery (own texture, image at its origin) outside, black when view 2 is
// off, and nothing read from the main target's old right-half periphery spot. Then run the GPU capture.
#define NOMINMAX
#include <windows.h>
#include "TriViewD3D12.hpp"
#include <dxgi1_6.h>
#include <d3d12sdklayers.h>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>

using Microsoft::WRL::ComPtr;
static void check(HRESULT h, const char* what) {
    if (FAILED(h)) throw std::runtime_error(std::string(what) + " failed " + std::to_string(uint32_t(h)));
}
static ComPtr<ID3D12Resource> make(ID3D12Device* dev, D3D12_RESOURCE_DESC desc, D3D12_HEAP_TYPE type,
                                   D3D12_RESOURCE_STATES state) {
    D3D12_HEAP_PROPERTIES heap{}; heap.Type = type; heap.CreationNodeMask = heap.VisibleNodeMask = 1;
    ComPtr<ID3D12Resource> r;
    check(dev->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, state, nullptr, IID_PPV_ARGS(&r)), "resource");
    return r;
}
static D3D12_RESOURCE_DESC tex(UINT w, UINT h, DXGI_FORMAT f, D3D12_RESOURCE_FLAGS flags) {
    D3D12_RESOURCE_DESC d{}; d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D; d.Width = w; d.Height = h;
    d.DepthOrArraySize = d.MipLevels = 1; d.Format = f; d.SampleDesc.Count = 1; d.Flags = flags; return d;
}
static D3D12_RESOURCE_DESC buf(UINT64 size) {
    D3D12_RESOURCE_DESC d{}; d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; d.Width = size;
    d.Height = d.DepthOrArraySize = d.MipLevels = 1; d.SampleDesc.Count = 1; d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    return d;
}
static void barrier(ID3D12GraphicsCommandList* cmd, ID3D12Resource* r, D3D12_RESOURCE_STATES a, D3D12_RESOURCE_STATES b) {
    D3D12_RESOURCE_BARRIER x{}; x.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    x.Transition = {r, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, a, b}; cmd->ResourceBarrier(1, &x);
}

struct Gpu {
    ComPtr<ID3D12Device> device; ComPtr<ID3D12CommandQueue> queue; ComPtr<ID3D12CommandAllocator> alloc;
    ComPtr<ID3D12GraphicsCommandList> cmd; ComPtr<ID3D12Fence> fence; UINT64 value{};
    void run() {
        check(cmd->Close(), "Close");
        ID3D12CommandList* lists[]{cmd.Get()}; queue->ExecuteCommandLists(1, lists);
        check(queue->Signal(fence.Get(), ++value), "Signal");
        HANDLE e = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        check(fence->SetEventOnCompletion(value, e), "fence event");
        if (WaitForSingleObject(e, 30000) != WAIT_OBJECT_0) throw std::runtime_error("GPU timeout");
        CloseHandle(e);
        check(device->GetDeviceRemovedReason(), "device removed");
        check(alloc->Reset(), "alloc reset"); check(cmd->Reset(alloc.Get(), nullptr), "cmd reset");
    }
};

// Fill rectangles of a BGRA8 texture through an upload buffer; texture ends in RENDER_TARGET state.
static void fill(Gpu& g, ID3D12Resource* t, std::initializer_list<std::pair<RECT, std::array<uint8_t, 4>>> rects,
                 ComPtr<ID3D12Resource>& upload) {
    const auto desc = t->GetDesc(); D3D12_PLACED_SUBRESOURCE_FOOTPRINT f{}; UINT64 bytes{};
    g.device->GetCopyableFootprints(&desc, 0, 1, 0, &f, nullptr, nullptr, &bytes);
    f.Footprint.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    upload = make(g.device.Get(), buf(bytes), D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    uint8_t* p{}; D3D12_RANGE none{0, 0}; check(upload->Map(0, &none, reinterpret_cast<void**>(&p)), "map");
    std::memset(p, 0, size_t(bytes));
    for (const auto& [r, c] : rects)
        for (LONG y = r.top; y < r.bottom; ++y) for (LONG x = r.left; x < r.right; ++x)
            std::memcpy(p + y * f.Footprint.RowPitch + x * 4, c.data(), 4);
    upload->Unmap(0, nullptr);
    D3D12_TEXTURE_COPY_LOCATION from{upload.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT}; from.PlacedFootprint = f;
    D3D12_TEXTURE_COPY_LOCATION to{t, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; to.SubresourceIndex = 0;
    g.cmd->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
    barrier(g.cmd.Get(), t, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_RENDER_TARGET);
}

int main() try {
    namespace tv = uevr::triview;
    ComPtr<ID3D12Debug> debug;
    if (SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)))) debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory; check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)), "factory");
    ComPtr<IDXGIAdapter> adapter; check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)), "WARP");
    Gpu g;
    check(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&g.device)), "device");
    D3D12_COMMAND_QUEUE_DESC q{}; q.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    check(g.device->CreateCommandQueue(&q, IID_PPV_ARGS(&g.queue)), "queue");
    check(g.device->CreateCommandAllocator(q.Type, IID_PPV_ARGS(&g.alloc)), "allocator");
    check(g.device->CreateCommandList(0, q.Type, g.alloc.Get(), nullptr, IID_PPV_ARGS(&g.cmd)), "list");
    check(g.device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&g.fence)), "fence");

    constexpr UINT W = 64, H = 64; // make_layout needs >= 64 px per axis
    const auto layout = tv::make_layout(W, H, {-1.30f, 1.05f, 1.25f, -1.30f}, {-1.05f, 1.30f, 1.25f, -1.30f}, .5f);
    if (!layout) throw std::runtime_error("layout");
    const auto& l = *layout;
    const auto rt = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
    // Joey's main target (typeless like an engine RT), capture target and the double-wide XR image.
    auto main_rt = make(g.device.Get(), tex(2 * W, H, DXGI_FORMAT_B8G8R8A8_TYPELESS, rt), D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto capture = make(g.device.Get(), tex(W, H, DXGI_FORMAT_B8G8R8A8_TYPELESS, rt), D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto periphery = make(g.device.Get(), tex(W, H, DXGI_FORMAT_B8G8R8A8_TYPELESS, rt), D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto xr = make(g.device.Get(), tex(2 * W, H, DXGI_FORMAT_B8G8R8A8_UNORM, rt), D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_RENDER_TARGET);
    auto not_rt = make(g.device.Get(), tex(2 * W, H, DXGI_FORMAT_B8G8R8A8_UNORM, D3D12_RESOURCE_FLAG_NONE), D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COMMON);
    const std::array<uint8_t, 4> red{0, 0, 255, 255}, blue{255, 0, 0, 255}, green{0, 255, 0, 255},
        magenta{255, 0, 255, 255};
    ComPtr<ID3D12Resource> up1, up2, up3;
    // Main target: left fovea at (0,0); a decoy in the old right-half periphery spot that must never show.
    fill(g, main_rt.Get(), {{{0, 0, LONG(l.fovea_width), LONG(l.fovea_height)}, red},
                            {{LONG(W), 0, LONG(2 * W), LONG(H)}, magenta}}, up1);
    fill(g, capture.Get(), {{{0, 0, LONG(l.fovea_width), LONG(l.fovea_height)}, blue}}, up2);
    // Periphery target: image at its origin, the rest magenta (outside the rendered rect, never sampled).
    fill(g, periphery.Get(), {{{0, 0, LONG(W), LONG(H)}, magenta},
                              {{0, 0, LONG(l.periphery_width), LONG(l.periphery_height)}, green}}, up3);

    const auto xd = xr->GetDesc(); D3D12_PLACED_SUBRESOURCE_FOOTPRINT foot{}; UINT64 bytes{};
    g.device->GetCopyableFootprints(&xd, 0, 1, 0, &foot, nullptr, nullptr, &bytes);
    auto readback = make(g.device.Get(), buf(bytes), D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);

    tv::dx12::Compositor compositor;
    tv::PacketLayout frame{l, true, true};
    if (compositor.record(g.device.Get(), g.cmd.Get(), main_rt.Get(), capture.Get(), periphery.Get(), not_rt.Get(), frame, 0))
        throw std::runtime_error("non-render-target XR image accepted");
    for (const bool third : {true, false}) {
        frame.third = third;
        if (!compositor.record(g.device.Get(), g.cmd.Get(), main_rt.Get(), capture.Get(), periphery.Get(), xr.Get(), frame, 0))
            throw std::runtime_error("record rejected: " + compositor.error());
        barrier(g.cmd.Get(), xr.Get(), D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION from{xr.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX}; from.SubresourceIndex = 0;
        D3D12_TEXTURE_COPY_LOCATION to{readback.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT}; to.PlacedFootprint = foot;
        g.cmd->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
        barrier(g.cmd.Get(), xr.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
        g.run();
        uint8_t* p{}; D3D12_RANGE all{0, size_t(bytes)}; check(readback->Map(0, &all, reinterpret_cast<void**>(&p)), "map");
        const auto px = [&](UINT x, UINT y) { return p + y * foot.Footprint.RowPitch + x * 4; };
        const auto is = [&](UINT x, UINT y, std::array<uint8_t, 4> c) {
            const auto* v = px(x, y);
            return std::abs(v[0] - c[0]) < 8 && std::abs(v[1] - c[1]) < 8 && std::abs(v[2] - c[2]) < 8;
        };
        const std::array<uint8_t, 4> black{0, 0, 0, 255};
        const auto outside = third ? green : black;
        if (!is(W / 2, H / 2, red)) throw std::runtime_error("left eye centre is not the left fovea");
        if (!is(W + W / 2, H / 2, blue)) throw std::runtime_error("right eye centre is not the right fovea");
        for (const auto [x, y] : {std::pair<UINT, UINT>{1, 1}, {W - 2, H - 2}, {W + 1, H - 2}, {2 * W - 2, 1}})
            if (!is(x, y, outside)) throw std::runtime_error(third ? "eye corner is not periphery" : "third view OFF is not black");
        for (UINT y = 0; y < H; y += 3) for (UINT x = 0; x < 2 * W; x += 3)
            if (is(x, y, magenta)) throw std::runtime_error("a pixel came from outside a rendered image");
        readback->Unmap(0, nullptr);
    }

    // Automatic capture: copies four images after a composite, then writes the ZIP synchronously.
    frame.third = true;
    if (!compositor.record(g.device.Get(), g.cmd.Get(), main_rt.Get(), capture.Get(), periphery.Get(), xr.Get(), frame, 0))
        throw std::runtime_error("record rejected before capture: " + compositor.error());
    tv::dx12::GpuCapture grab;
    const auto zip = std::filesystem::temp_directory_path() / "TriView_Capture_test.zip";
    std::filesystem::remove(zip);
    const std::vector<tv::dx12::GpuCapture::Source> sources{
        {"main_left", main_rt.Get(), W, H, {{"fovea", 0, 0, l.fovea_width, l.fovea_height}}},
        {"capture", capture.Get(), W, H, {}},
        {"periphery", periphery.Get(), W, H, {{"image", 0, 0, l.periphery_width, l.periphery_height}}},
        {"xr", xr.Get(), 2 * W, H, {}}};
    if (!grab.record(g.device.Get(), g.cmd.Get(), sources, g.fence.Get(), g.value + 1, zip, "test report\n"))
        throw std::runtime_error("capture record failed");
    if (grab.poll(true)) throw std::runtime_error("capture finished before the GPU ran");
    g.run();
    if (!grab.poll(true) || grab.pending()) throw std::runtime_error("capture did not complete");
    std::ifstream in(zip, std::ios::binary);
    const std::string bytes((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    if (bytes.size() < 1000 || bytes.find("main_left_half.bmp") == std::string::npos ||
        bytes.find("main_left fovea [0,0)") == std::string::npos ||
        bytes.find("nonblack 100.0%") == std::string::npos)
        throw std::runtime_error("capture ZIP incomplete");
    std::puts("Tri-View compositor WARP pixel tests passed.");
    return 0;
} catch (const std::exception& e) {
    std::fprintf(stderr, "FAILED: %s\n", e.what());
    return 1;
}

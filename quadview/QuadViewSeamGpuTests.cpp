// B30: WARP coverage of seam matching through the production compositor.
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
                   Settings settings, const uevr::quadview::dx12::DepthInput* depth = nullptr) {
    ComPtr<ID3D12CommandAllocator> allocator;
    require(gpu.device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)), "Create draw allocator");
    ComPtr<ID3D12GraphicsCommandList> list;
    require(gpu.device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr, IID_PPV_ARGS(&list)), "Create draw list");
    auto owner = std::make_shared<uint64_t>(gpu.fence_value + 1);
    const std::array<ID3D12Resource*, 4> raw{sources.textures[0].Get(), sources.textures[1].Get(),
        sources.textures[2].Get(), sources.textures[3].Get()};
    const bool recorded = compositor.record_sources(list.Get(), raw, output, layout, settings,
        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_SOURCE, owner, 0, depth);
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
    constexpr uint32_t eye_w = 64, eye_h = 64;
    const auto maybe_layout = make_layout(eye_w, eye_h, .50f, .50f, .25f, 1.f);
    check(maybe_layout.has_value(), "Could not create seam test layout");
    const auto layout = *maybe_layout;
    ComPtr<IDXGIFactory4> factory; require(CreateDXGIFactory1(IID_PPV_ARGS(&factory)), "CreateDXGIFactory1");
    ComPtr<IDXGIAdapter> adapter; require(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)), "EnumWarpAdapter");
    Gpu gpu;
    require(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&gpu.device)), "D3D12CreateDevice");
    ComPtr<ID3D12InfoQueue> info;
    gpu.device.As(&info);
    D3D12_COMMAND_QUEUE_DESC qd{}; qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    require(gpu.device->CreateCommandQueue(&qd, IID_PPV_ARGS(&gpu.queue)), "CreateCommandQueue");
    require(gpu.device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&gpu.fence)), "CreateFence");
    gpu.event = CreateEventW(nullptr, FALSE, FALSE, nullptr); check(gpu.event != nullptr, "CreateEventW failed");

    auto output = make_resource(gpu.device.Get(), texture(eye_w * 2, eye_h, D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_SOURCE);
    uevr::quadview::dx12::Compositor compositor;
    const bool prepared = compositor.prewarm(gpu.device.Get(), DXGI_FORMAT_R8G8B8A8_UNORM, DXGI_FORMAT_R8G8B8A8_UNORM);
    check(prepared, compositor.error());

    Settings off{}; off.crop_width = off.crop_height = .50f; off.context_scale = .25f;
    off.feather_fraction = 0.f; off.sharpen_strength = 0.f;
    Settings manual = off; manual.seam_mode = 1; manual.seam_strength = 1.f;
    manual.seam_brightness_ev = .20f; manual.seam_color_strength = 0.f;
    const auto base = make_sources(gpu, layout, {{{77,77,77,255}, {77,77,77,255}, {102,102,102,255}, {102,102,102,255}}});
    const auto baseline = draw(gpu, compositor, base, output.Get(), layout, off);
    const auto corrected = draw(gpu, compositor, base, output.Get(), layout, manual);
    Settings local_disabled = manual; local_disabled.seam_local_strength = 0.f;
    const auto without_local = draw(gpu, compositor, base, output.Get(), layout, local_disabled);
    for (uint32_t eye = 0; eye != 2; ++eye) {
        const uint32_t x_context = eye * eye_w + 4, x_focus = eye * eye_w + eye_w / 2;
        check(baseline.at(x_context, eye_h / 2)[0] == 77, "Off mode changed the context identity baseline");
        check(corrected.at(x_context, eye_h / 2)[0] > baseline.at(x_context, eye_h / 2)[0], "Manual EV did not lift the context");
        check(std::abs(int(corrected.at(x_context, eye_h / 2)[0]) - int(without_local.at(x_context, eye_h / 2)[0])) <= 1,
            "Uniform seam acquired a local residual");
        check(corrected.at(x_focus, eye_h / 2)[0] == 102, "Seam correction changed opaque focus pixels");
    }

    // B34: automatic boundary RGB correction, no cross-frame state.
    Settings boundary=off; boundary.seam_mode=3; boundary.seam_strength=1.f;
    boundary.seam_max_gain=.5f; boundary.seam_color_strength=1.f;
    boundary.seam_local_strength=.9f; boundary.seam_radius_px=16.f;
    boundary.seam_transition_px=6.f;
    boundary.seam_noise_guard=.035f; boundary.seam_chroma_guard=.015f;
    const auto boundary_px=draw(gpu,compositor,base,output.Get(),layout,boundary);
    check(boundary_px.at(15,32)[0]>baseline.at(15,32)[0]+10,
          "B34 failed to brighten context close to the foveal boundary");
    check(boundary_px.at(0,32)==baseline.at(0,32),
          "B34 changed context outside correction band");
    check(boundary_px.at(32,32)==baseline.at(32,32),
          "B34 altered original opaque foveal pixels");
    check(draw(gpu,compositor,base,output.Get(),layout,boundary).rgba==boundary_px.rgba,
          "B34 output changed between identical input frames");
    Settings boundary_off=boundary; boundary_off.seam_strength=0.f;
    const auto boundary_neutral=draw(gpu,compositor,base,output.Get(),layout,boundary_off);
    check(boundary_neutral.at(4,32)==baseline.at(4,32),
          "B34 zero-strength periphery differs from B31 seam-off");
    const auto chromatic=make_sources(gpu, layout, {{{77,77,77,255},{77,77,77,255},
                                                     {104,92,83,255},{104,92,83,255}}});
    const auto chromatic_px=draw(gpu,compositor,chromatic,output.Get(),layout,boundary);
    check(chromatic_px.at(15,32)[0]>chromatic_px.at(15,32)[2],
          "B34 failed to correct warm-color mismatch");
    check(chromatic_px.at(32,32)[0]==104 && chromatic_px.at(32,32)[2]==83,
          "B34 color correction modified real stereo fovea core");

    // B34-R2: subthreshold RGB/luminance jitter must not change the periphery.
    const auto tiny_a=make_sources(gpu,layout,{{{77,77,77,255},{77,77,77,255},
                                               {78,78,78,255},{78,78,78,255}}});
    const auto tiny_b=make_sources(gpu,layout,{{{77,77,77,255},{77,77,77,255},
                                               {79,79,79,255},{79,79,79,255}}});
    const auto tiny_a_out=draw(gpu,compositor,tiny_a,output.Get(),layout,boundary);
    const auto tiny_b_out=draw(gpu,compositor,tiny_b,output.Get(),layout,boundary);
    check(tiny_a_out.at(15,32)==tiny_b_out.at(15,32),
          "B34-R2 brightness noise escaped the deadband");
    check(tiny_a_out.at(15,32)[0]==77,
          "B34-R2 neutral source acquired spurious brightness");
    const auto tiny_chroma_a=make_sources(gpu,layout,{{{77,77,77,255},{77,77,77,255},
                                               {77,78,77,255},{77,78,77,255}}});
    const auto tiny_chroma_b=make_sources(gpu,layout,{{{77,77,77,255},{77,77,77,255},
                                               {77,79,77,255},{77,79,77,255}}});
    const auto ca=draw(gpu,compositor,tiny_chroma_a,output.Get(),layout,boundary);
    const auto cb=draw(gpu,compositor,tiny_chroma_b,output.Get(),layout,boundary);
    check(ca.at(15,32)==cb.at(15,32),
          "B34-R2 chroma noise escaped the deadband");
    Settings wide=boundary; wide.seam_radius_px=32.f; wide.seam_transition_px=28.f;
    const auto wide_px=draw(gpu,compositor,base,output.Get(),layout,wide);
    check(wide_px.at(0,32)[0]>boundary_px.at(0,32)[0],
          "B34-R2 larger outward correction did not reach distant periphery");
    check(wide_px.at(32,32)==baseline.at(32,32),
          "B34-R2 wider feather changed sharp stereo fovea core");

    Settings lifted = off; lifted.focus_lift_enabled = true; lifted.focus_brightness = 1.05f;
    const auto lifted_off = draw(gpu, compositor, base, output.Get(), layout, lifted);
    Settings disabled_lift = lifted; disabled_lift.focus_lift_enabled = false;
    const auto disabled_lift_pixels = draw(gpu, compositor, base, output.Get(), layout, disabled_lift);
    check(lifted_off.at(32, 32)[0] > baseline.at(32, 32)[0], "Focus center lift did not increase the center");
    check(lifted_off.at(17, 17)[0] > lifted_off.at(32, 32)[0], "Focus edge lift did not exceed center lift");
    check(lifted_off.at(4, 32) == baseline.at(4, 32), "Focus lift changed peripheral pixels with seam Off");
    check(disabled_lift_pixels.at(32, 32) == baseline.at(32, 32) &&
          disabled_lift_pixels.at(17, 17) == baseline.at(17, 17) &&
          disabled_lift_pixels.at(4, 32) == baseline.at(4, 32),
        "Disabled focus lift used stored EV settings");

    Settings adaptive = off; adaptive.seam_mode = 2; adaptive.seam_strength = 1.f;
    adaptive.seam_max_gain = .50f; adaptive.seam_color_strength = 0.f;
    const auto independent = make_sources(gpu, layout, {{{77,77,77,255}, {77,77,77,255}, {102,102,102,255}, {153,153,153,255}}});
    const auto fit = draw(gpu, compositor, independent, output.Get(), layout, adaptive);
    const uint8_t left_fit = fit.at(4, eye_h / 2)[0], right_fit = fit.at(eye_w + 4, eye_h / 2)[0];
    check(left_fit > 77 && right_fit > left_fit, "Adaptive matching did not fit the two eyes independently");
    check(fit.at(eye_w / 2, eye_h / 2)[0] == 102 && fit.at(eye_w + eye_w / 2, eye_h / 2)[0] == 153,
        "Adaptive correction changed opaque focus pixels");
    Settings zero_strength = adaptive; zero_strength.seam_strength = 0.f;
    const auto zero_strength_pixels = draw(gpu, compositor, base, output.Get(), layout, zero_strength);
    check(zero_strength_pixels.rgba == baseline.rgba,
        "Zero-strength adaptive matching must not change any pixels");
    Settings adaptive_lift = adaptive; adaptive_lift.focus_lift_enabled = true; adaptive_lift.focus_brightness = 1.05f;
    const auto fit_lifted = draw(gpu, compositor, independent, output.Get(), layout, adaptive_lift);
    check(fit_lifted.at(4, eye_h / 2)[0] > fit.at(4, eye_h / 2)[0],
        "Adaptive seam match ignored the lifted focus reference");
    Settings global_only = adaptive; global_only.seam_local_strength = 0.f;
    const auto uniform_global = draw(gpu, compositor, base, output.Get(), layout, global_only);
    const auto uniform_local = draw(gpu, compositor, base, output.Get(), layout, adaptive);
    check(uniform_global.rgba == uniform_local.rgba, "Local fitting introduced a residual into a uniform pair");

    const auto varying = make_sources(gpu, layout, {{{77,77,77,255}, {77,77,77,255}, {100,100,100,255}, {100,100,100,255}}}, true);
    Settings local_fit = adaptive; local_fit.seam_local_strength = 1.f;
    const auto varied_global = draw(gpu, compositor, varying, output.Get(), layout, global_only);
    const auto varied_local = draw(gpu, compositor, varying, output.Get(), layout, local_fit);
    check(varied_local.at(14,32)[0] < varied_global.at(14,32)[0] &&
          varied_local.at(50,32)[0] > varied_global.at(50,32)[0], "Local fit did not follow opposite boundary brightness changes");
    check(varied_local.at(32,32) == varied_global.at(32,32), "Local residual altered the opaque fovea");
    // Exercise the production sharpening branch. Seam probes deliberately
    // compare unsharpened low-frequency patches; periphery is unchanged.
    Settings sharp_local = local_fit; sharp_local.sharpen_strength = 1.f;
    const auto sharpened_fit = draw(gpu, compositor, varying, output.Get(), layout, sharp_local);
    for (uint32_t eye = 0; eye < 2; ++eye)
        for (uint32_t x : {4u, 14u, 50u})
            check(sharpened_fit.at(eye * eye_w + x, 32)[0] == varied_local.at(eye * eye_w + x, 32)[0],
                "Fovea sharpening contaminated adaptive periphery statistics");

    Settings transitioned = manual; transitioned.seam_transition_px = 16.f;
    const auto edge_blend = draw(gpu, compositor, base, output.Get(), layout, transitioned);
    check(edge_blend.at(eye_w / 2, eye_h / 2)[0] == corrected.at(eye_w / 2, eye_h / 2)[0],
        "Transition reservation changed the fovea core");
    check(edge_blend.at(17, eye_h / 2)[0] < corrected.at(17, eye_h / 2)[0],
        "Transition reservation did not blend the crop boundary");

    const auto black = make_sources(gpu, layout, {{{0,0,0,255}, {0,0,0,255}, {0,0,0,255}, {0,0,0,255}}});
    const auto black_fit = draw(gpu, compositor, black, output.Get(), layout, adaptive);
    check(black_fit.at(4, eye_h / 2)[0] == 0, "Adaptive fit amplified an all-black patch");
    const auto clipped = make_sources(gpu, layout, {{{255,255,255,255}, {255,255,255,255}, {102,102,102,255}, {102,102,102,255}}});
    const auto clipped_fit = draw(gpu, compositor, clipped, output.Get(), layout, adaptive);
    check(clipped_fit.at(4, eye_h / 2)[0] == 255, "Adaptive fit modified a clipped context patch");
    const auto mismatch = make_sources(gpu, layout, {{{77,20,20,255}, {77,20,20,255}, {20,102,20,255}, {20,102,20,255}}});
    const auto mismatch_fit = draw(gpu, compositor, mismatch, output.Get(), layout, adaptive);
    check(mismatch_fit.at(4, eye_h / 2)[0] == 77 && mismatch_fit.at(4, eye_h / 2)[1] == 20,
        "Adaptive fit changed a mismatched-color patch");

    // Requested depth is unavailable after a prior valid adaptive fit. All
    // records must become neutral rather than leaking the prior-frame gains.
    auto shared_layout = layout;
    shared_layout.shared_context = true;
    // record_sources validates the full layout; its validator is private to Compositor.
    uevr::quadview::dx12::DepthInput missing_depth{};
    missing_depth.reproject = true;
    const auto shared_off = draw(gpu, compositor, base, output.Get(), shared_layout, off);
    const auto invalid_depth_fit = draw(gpu, compositor, base, output.Get(), shared_layout, adaptive, &missing_depth);
    check(invalid_depth_fit.rgba == shared_off.rgba,
        "Missing depth reused stale adaptive gains instead of neutral output");
    const auto recovered_fit = draw(gpu, compositor, base, output.Get(), shared_layout, adaptive);
    check(recovered_fit.at(4, 32)[0] > shared_off.at(4, 32)[0],
        "Adaptive statistics did not recover after missing-depth frame");

    if (info) for (UINT64 i=0,n=info->GetNumStoredMessages();i<n;++i) {
        SIZE_T size{}; info->GetMessage(i,nullptr,&size);
        std::vector<uint8_t> storage(size);
        auto* message=reinterpret_cast<D3D12_MESSAGE*>(storage.data());
        require(info->GetMessage(i,message,&size),"Read debug-layer message");
        if (message->Severity <= D3D12_MESSAGE_SEVERITY_ERROR)
            throw std::runtime_error(std::string("D3D12 seam validation: ")+message->pDescription);
    }

    std::cout << "QuadView seam WARP: off/manual/zero-strength identity, independent eyes, sharpened periphery, missing-depth neutral/recovery, edge blend and invalid-patch rejection passed.\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr << "QuadView seam WARP FAILED: " << e.what() << '\n';
    return 1;
}

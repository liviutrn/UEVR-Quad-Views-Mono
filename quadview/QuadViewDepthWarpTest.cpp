// Tri-view B14: the REAL compositor shader (QuadViewComposite.hlsl, compiled here
// with the production flags) on WARP, holding the B12/B13 24-step depth warp to
// exact ground-truth stereo pixels (DepthWarpScene.hpp): a card at 30 cm in front
// of a wall at 10 m, eyes 3.2 cm left/right of the periphery camera. Both eyes must
// sample the periphery point their own ray hits to within 1 texel. Two control
// passes (reprojection off, sign flipped) must FAIL the same verdict, proving the
// test can see a wrong warp.
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <d3dcompiler.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include "DepthWarpScene.hpp"
#include <climits>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>

using Microsoft::WRL::ComPtr;
using namespace uevr::quadview::depth_scene;

static void require(HRESULT result, const char* operation) {
    if (FAILED(result)) throw std::runtime_error(std::string(operation) + ": " + std::to_string(result));
}
static D3D12_RESOURCE_DESC texture(uint32_t w, uint32_t h, DXGI_FORMAT format, D3D12_RESOURCE_FLAGS flags) {
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D; d.Width = w; d.Height = h;
    d.DepthOrArraySize = d.MipLevels = 1; d.Format = format; d.SampleDesc.Count = 1; d.Flags = flags;
    return d;
}
static D3D12_RESOURCE_DESC buffer(uint64_t size) {
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; d.Width = size; d.Height = 1;
    d.DepthOrArraySize = d.MipLevels = 1; d.Format = DXGI_FORMAT_UNKNOWN; d.SampleDesc.Count = 1;
    d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    return d;
}
static ComPtr<ID3D12Resource> resource(ID3D12Device* device, const D3D12_RESOURCE_DESC& d, D3D12_HEAP_TYPE type,
                                      D3D12_RESOURCE_STATES state) {
    D3D12_HEAP_PROPERTIES p{}; p.Type = type; p.CreationNodeMask = p.VisibleNodeMask = 1;
    ComPtr<ID3D12Resource> r;
    require(device->CreateCommittedResource(&p, D3D12_HEAP_FLAG_NONE, &d, state, nullptr, IID_PPV_ARGS(&r)),
        "CreateCommittedResource");
    return r;
}
static void transition(ID3D12GraphicsCommandList* list, ID3D12Resource* r, D3D12_RESOURCE_STATES a, D3D12_RESOURCE_STATES b) {
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition = {r, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, a, b};
    list->ResourceBarrier(1, &barrier);
}

// Same layout as the shader's QuadViewConstants (and QuadViewShaderWarpTest.cpp).
struct alignas(16) Constants {
    uint32_t eye_and_atlas[4];
    uint32_t rectangles[4][4];
    float crops[2][4];
    float options[4];
    float sharpen[4];
    float sharpen_eye[4];
    float context_h[2][12]{{1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f},
                           {1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f}};
    uint32_t context_source[4]{0, 0, 0, 0};
    float depth_shift[4]{};
    uint32_t depth_rect[4]{};
    uint32_t depth_options[4]{};
    float depth_eye_origin[2][4]{};
    float depth_projection[4]{};
    float depth_coefficients[4]{};
    float depth_jitter[4]{};
    float seam[4]{};
    float seam_options[4]{};
    float seam_local[4]{};
    float focus_lift[4]{};
};
static_assert(sizeof(Constants) == 464);

int main(int argc, char** argv) try {
    if (argc != 2) throw std::runtime_error("Pass the QuadViewComposite.hlsl path");
    ComPtr<ID3D12Debug> debug_layer;
    const bool debug_enabled = SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug_layer)));
    if (debug_enabled) debug_layer->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory;
    require(CreateDXGIFactory1(IID_PPV_ARGS(&factory)), "CreateDXGIFactory1");
    ComPtr<IDXGIAdapter> adapter;
    require(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)), "EnumWarpAdapter");
    ComPtr<ID3D12Device> device;
    require(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)), "D3D12CreateDevice");
    ComPtr<ID3D12InfoQueue> info;
    if (debug_enabled) (void)device.As(&info);
    D3D12_COMMAND_QUEUE_DESC qd{}; qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;
    require(device->CreateCommandQueue(&qd, IID_PPV_ARGS(&queue)), "CreateCommandQueue");
    ComPtr<ID3D12CommandAllocator> allocator;
    require(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)), "CreateCommandAllocator");
    ComPtr<ID3D12GraphicsCommandList> list;
    require(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr, IID_PPV_ARGS(&list)),
        "CreateCommandList");
    ComPtr<ID3D12Fence> fence;
    require(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "CreateFence");
    uint64_t fence_value = 0;
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!event) throw std::runtime_error("CreateEventW");
    const auto submit_and_wait = [&]() {
        require(list->Close(), "Close");
        ID3D12CommandList* lists[]{list.Get()};
        queue->ExecuteCommandLists(1, lists);
        require(queue->Signal(fence.Get(), ++fence_value), "Signal");
        if (fence->GetCompletedValue() < fence_value) {
            require(fence->SetEventOnCompletion(fence_value, event), "SetEventOnCompletion");
            WaitForSingleObject(event, 30000);
        }
        if (fence->GetCompletedValue() < fence_value) throw std::runtime_error("GPU wait timed out");
    };

    // Inputs: periphery colour (texel-centre UV + object id) and its device depth.
    const auto color_format = DXGI_FORMAT_R16G16B16A16_UNORM;
    auto context = resource(device.Get(), texture(CW, CH, color_format, D3D12_RESOURCE_FLAG_NONE),
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto depth = resource(device.Get(), texture(CW, CH, DXGI_FORMAT_R32_FLOAT, D3D12_RESOURCE_FLAG_NONE),
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_RANGE no_read{0, 0};
    std::vector<ComPtr<ID3D12Resource>> uploads;
    const auto upload_texture = [&](ID3D12Resource* target, uint32_t bytes_per_texel,
                                    const std::function<void(uint32_t, uint32_t, uint8_t*)>& write) {
        const auto d = target->GetDesc();
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; uint64_t size{};
        device->GetCopyableFootprints(&d, 0, 1, 0, &fp, nullptr, nullptr, &size);
        auto up = resource(device.Get(), buffer(size), D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
        void* mapped{};
        require(up->Map(0, &no_read, &mapped), "Map upload");
        std::memset(mapped, 0, size_t(size));
        for (uint32_t y = 0; y < d.Height; ++y) for (uint32_t x = 0; x < uint32_t(d.Width); ++x)
            write(x, y, static_cast<uint8_t*>(mapped) + y * fp.Footprint.RowPitch + x * bytes_per_texel);
        up->Unmap(0, nullptr);
        D3D12_TEXTURE_COPY_LOCATION from{}, to{};
        from.pResource = up.Get(); from.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; from.PlacedFootprint = fp;
        to.pResource = target; to.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        list->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
        transition(list.Get(), target, D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        uploads.push_back(up);
    };
    upload_texture(context.Get(), 8, [](uint32_t x, uint32_t y, uint8_t* out) {
        const auto c = context_texel(x, y);
        uint16_t v[4];
        for (int i = 0; i < 4; ++i) v[i] = uint16_t(std::lround(std::clamp(c[i], 0.f, 1.f) * 65535.f));
        std::memcpy(out, v, sizeof(v));
    });
    upload_texture(depth.Get(), 4, [](uint32_t x, uint32_t y, uint8_t* out) {
        const float d = device_depth(x, y);
        std::memcpy(out, &d, sizeof(d));
    });

    constexpr uint32_t OW = 2 * EW;
    auto output = resource(device.Get(), texture(OW, EH, color_format, D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_RENDER_TARGET);
    const auto output_desc = output->GetDesc();
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT out_fp{}; uint64_t out_size{};
    device->GetCopyableFootprints(&output_desc, 0, 1, 0, &out_fp, nullptr, nullptr, &out_size);
    auto readback = resource(device.Get(), buffer(out_size), D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    auto constant_buffer = resource(device.Get(), buffer(512), D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);

    D3D12_DESCRIPTOR_HEAP_DESC hd{};
    hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.NumDescriptors = 6; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> srv_heap;
    require(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&srv_heap)), "SRV heap");
    D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
    srv.Format = color_format; srv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING; srv.Texture2D.MipLevels = 1;
    auto cpu = srv_heap->GetCPUDescriptorHandleForHeapStart();
    const auto stride = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    for (int i = 0; i != 4; ++i) { device->CreateShaderResourceView(context.Get(), &srv, cpu); cpu.ptr += stride; }
    srv.Format = DXGI_FORMAT_R32_FLOAT;
    device->CreateShaderResourceView(depth.Get(), &srv, cpu);
    cpu.ptr += stride;
    D3D12_SHADER_RESOURCE_VIEW_DESC seam_srv{};
    seam_srv.Format = DXGI_FORMAT_UNKNOWN; seam_srv.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
    seam_srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    seam_srv.Buffer.NumElements = 18; seam_srv.Buffer.StructureByteStride = 16;
    device->CreateShaderResourceView(nullptr, &seam_srv, cpu);
    hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV; hd.NumDescriptors = 1; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
    ComPtr<ID3D12DescriptorHeap> rtv_heap;
    require(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&rtv_heap)), "RTV heap");
    const auto rtv = rtv_heap->GetCPUDescriptorHandleForHeapStart();
    device->CreateRenderTargetView(output.Get(), nullptr, rtv);

    D3D12_DESCRIPTOR_RANGE range{}; range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV; range.NumDescriptors = 6;
    D3D12_ROOT_PARAMETER parameters[2]{};
    parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
    parameters[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    parameters[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    parameters[1].DescriptorTable.NumDescriptorRanges = 1; parameters[1].DescriptorTable.pDescriptorRanges = &range;
    parameters[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    D3D12_STATIC_SAMPLER_DESC sampler{};
    sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
    sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
    sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_ALWAYS; sampler.MaxAnisotropy = 1; sampler.MaxLOD = D3D12_FLOAT32_MAX;
    sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    D3D12_ROOT_SIGNATURE_DESC rd{};
    rd.NumParameters = 2; rd.pParameters = parameters; rd.NumStaticSamplers = 1; rd.pStaticSamplers = &sampler;
    rd.Flags = D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT;
    ComPtr<ID3DBlob> serialized, errors;
    require(D3D12SerializeRootSignature(&rd, D3D_ROOT_SIGNATURE_VERSION_1, &serialized, &errors), "Serialize root signature");
    ComPtr<ID3D12RootSignature> root;
    require(device->CreateRootSignature(0, serialized->GetBufferPointer(), serialized->GetBufferSize(), IID_PPV_ARGS(&root)),
        "CreateRootSignature");
    const auto shader_path = std::filesystem::path(argv[1]).wstring();
    const auto compile = [&](const char* entry, const char* profile) {
        ComPtr<ID3DBlob> result, diagnostics;
        const auto status = D3DCompileFromFile(shader_path.c_str(), nullptr, D3D_COMPILE_STANDARD_FILE_INCLUDE, entry, profile,
            D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_WARNINGS_ARE_ERRORS, 0, &result, &diagnostics);
        if (FAILED(status) && diagnostics)
            throw std::runtime_error(std::string(static_cast<const char*>(diagnostics->GetBufferPointer()), diagnostics->GetBufferSize()));
        require(status, "Compile compositor shader");
        return result;
    };
    const auto vs = compile("VSMain", "vs_5_0"), ps = compile("PSMain", "ps_5_0");
    D3D12_GRAPHICS_PIPELINE_STATE_DESC pd{};
    pd.pRootSignature = root.Get();
    pd.VS = {vs->GetBufferPointer(), vs->GetBufferSize()};
    pd.PS = {ps->GetBufferPointer(), ps->GetBufferSize()};
    auto& blend = pd.BlendState.RenderTarget[0];
    blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
    blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE; blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
    blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD; blend.LogicOp = D3D12_LOGIC_OP_NOOP;
    pd.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID; pd.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
    pd.RasterizerState.DepthClipEnable = TRUE;
    pd.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ZERO;
    pd.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
    pd.SampleMask = UINT_MAX; pd.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    pd.NumRenderTargets = 1; pd.RTVFormats[0] = color_format; pd.SampleDesc.Count = 1;
    ComPtr<ID3D12PipelineState> pipeline;
    require(device->CreateGraphicsPipelineState(&pd, IID_PPV_ARGS(&pipeline)), "CreateGraphicsPipelineState");
    submit_and_wait(); // uploads

    const auto render = [&](bool reproject, float strength) {
        Constants c{{EW, EH, CW, CH}, {}, {}, {0, 0, 0, 0}, {0, 0, 0, 0}, {0, 0, 0, 0}};
        for (auto& r : c.rectangles) { r[0] = 0; r[1] = 0; r[2] = CW; r[3] = CH; }
        for (auto& crop : c.crops) { crop[0] = 2.f; crop[1] = 2.f; crop[2] = 3.f; crop[3] = 3.f; } // no fovea anywhere
        const DepthConstants d{};
        c.depth_rect[2] = CW; c.depth_rect[3] = CH;
        c.depth_options[0] = reproject ? 1u : 0u; c.depth_options[2] = 1u;
        for (int eye = 0; eye != 2; ++eye) for (int i = 0; i != 4; ++i) c.depth_eye_origin[eye][i] = d.eye_origin[eye][i];
        for (int i = 0; i != 4; ++i) { c.depth_projection[i] = d.projection[i]; c.depth_coefficients[i] = d.coefficients[i]; }
        c.depth_coefficients[3] = strength;
        void* mapped{};
        require(constant_buffer->Map(0, &no_read, &mapped), "Map constants");
        std::memcpy(mapped, &c, sizeof(c));
        constant_buffer->Unmap(0, nullptr);
        require(allocator->Reset(), "Reset allocator");
        require(list->Reset(allocator.Get(), pipeline.Get()), "Reset list");
        list->SetGraphicsRootSignature(root.Get());
        ID3D12DescriptorHeap* heaps[]{srv_heap.Get()};
        list->SetDescriptorHeaps(1, heaps);
        list->SetGraphicsRootConstantBufferView(0, constant_buffer->GetGPUVirtualAddress());
        list->SetGraphicsRootDescriptorTable(1, srv_heap->GetGPUDescriptorHandleForHeapStart());
        const D3D12_VIEWPORT viewport{0, 0, float(OW), float(EH), 0, 1};
        const D3D12_RECT scissor{0, 0, LONG(OW), LONG(EH)};
        list->RSSetViewports(1, &viewport); list->RSSetScissorRects(1, &scissor);
        list->OMSetRenderTargets(1, &rtv, FALSE, nullptr);
        list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        list->DrawInstanced(3, 1, 0, 0);
        transition(list.Get(), output.Get(), D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION from{}, to{};
        from.pResource = output.Get(); from.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        to.pResource = readback.Get(); to.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; to.PlacedFootprint = out_fp;
        list->CopyTextureRegion(&to, 0, 0, 0, &from, nullptr);
        transition(list.Get(), output.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
        submit_and_wait();
        std::vector<uint8_t> pixels(static_cast<size_t>(out_size));
        D3D12_RANGE read{0, size_t(out_size)};
        require(readback->Map(0, &read, &mapped), "Map readback");
        std::memcpy(pixels.data(), mapped, pixels.size());
        readback->Unmap(0, &no_read);
        return judge([&](unsigned eye, uint32_t px, uint32_t py) {
            uint16_t v[4];
            std::memcpy(v, pixels.data() + py * out_fp.Footprint.RowPitch + (eye * EW + px) * 8, sizeof(v));
            return std::array<float, 3>{v[0] / 65535.f, v[1] / 65535.f, v[2] / 65535.f};
        });
    };
    const auto print = [](const char* name, const Verdict& v) {
        std::cout << name << ": card " << v.card[0] << "/" << v.card[1] << " wall " << v.wall[0] << "/" << v.wall[1]
                  << " max card err " << v.max_card_error_texels << " wall err " << v.max_wall_error_texels
                  << " v err " << v.max_v_error_texels << " wrong object " << v.wrong_object << (v.ok() ? " PASS\n" : " FAIL\n");
    };
    const auto good = render(true, 1.f), mono = render(false, 1.f), flipped = render(true, -1.f);
    print("WARP depth warp", good); print("WARP control: no reprojection", mono); print("WARP control: flipped sign", flipped);
    if (info) {
        uint64_t serious = 0;
        for (uint64_t i = 0, n = info->GetNumStoredMessages(); i < n; ++i) {
            SIZE_T length = 0;
            if (FAILED(info->GetMessage(i, nullptr, &length)) || !length) continue;
            std::vector<uint8_t> storage(length);
            auto* message = reinterpret_cast<D3D12_MESSAGE*>(storage.data());
            if (SUCCEEDED(info->GetMessage(i, message, &length)) &&
                (message->Severity == D3D12_MESSAGE_SEVERITY_ERROR || message->Severity == D3D12_MESSAGE_SEVERITY_CORRUPTION)) {
                ++serious;
                std::cerr << "D3D12 debug layer: " << message->pDescription << "\n";
            }
        }
        if (serious) throw std::runtime_error("D3D12 debug layer reported errors");
    }
    CloseHandle(event);
    if (!good.ok()) throw std::runtime_error("the depth warp does not match the ground-truth stereo pixels");
    if (mono.ok() || flipped.ok()) throw std::runtime_error("control passes did not fail: the test cannot see a wrong warp");
    std::cout << "QuadView depth warp ground truth: ok\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr << e.what() << "\n";
    return 1;
}

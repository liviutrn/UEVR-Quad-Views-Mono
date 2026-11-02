#pragma once
// Tri-View D3D12 compositor (rendering method ID 7): three source textures, each image at its origin.
// One instance per OpenXR command slot, like DuoView's compositor: its descriptors and the
// resource references it holds stay alive until that slot's fence has retired.
// Writes the double-wide XR image in one draw; the XR pose/submission stays Joey's Native Stereo.
#include <d3d12.h>
#include <wrl/client.h>
#include <atomic>
#include <climits>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <thread>
#include <vector>
#include "TriViewGeometry.hpp"
#include "TriViewShaderSource.hpp"
#include "TriViewCapture.hpp"

namespace uevr::triview::dx12 {
using Microsoft::WRL::ComPtr;

struct Constants {
    float eye_and_fovea[4];
    float fovea_window_left[4];
    float fovea_window_right[4];
    float map_left[4];
    float map_right[4];
    float periphery_rect[4];
    float source_sizes[4];
    float params[4];
};
static_assert(sizeof(Constants) == 128, "Must match TriViewConstants in TriViewComposite.hlsl");

class Compositor {
public:
    // main / capture: Joey's Native Fix targets in RENDER_TARGET state (as his copy expects).
    // periphery: Tri-View's own target (same kind as capture), RENDER_TARGET state; pass nullptr when
    // view 2 was not rendered for this packet (edges black).
    // destination: the double-wide XR image in RENDER_TARGET state. All are left in those states.
    bool record(ID3D12Device* device, ID3D12GraphicsCommandList* cmd, ID3D12Resource* main,
                ID3D12Resource* capture, ID3D12Resource* periphery, ID3D12Resource* destination,
                const PacketLayout& frame, unsigned debug_bits) {
        error_.clear();
        if (!frame.third) periphery = nullptr;
        if (!device || !cmd || !main || !capture || !destination || main == capture ||
            main == destination || capture == destination || periphery == main || periphery == capture ||
            periphery == destination || !frame.valid ||
            cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT) return reject("invalid inputs");
        const auto& l = frame.layout;
        const auto md = main->GetDesc(), cd = capture->GetDesc(), dd = destination->GetDesc();
        const auto pd = periphery ? periphery->GetDesc() : cd;
        const auto plain = [](const D3D12_RESOURCE_DESC& d) {
            return d.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && d.DepthOrArraySize == 1 &&
                d.MipLevels == 1 && d.SampleDesc.Count == 1 && d.Width <= 32768 && d.Height <= 32768;
        };
        if (!plain(md) || !plain(cd) || !plain(pd) || !plain(dd) || (dd.Width & 1) || dd.Width < 2 ||
            !(dd.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) ||
            (md.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            (cd.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            (pd.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE)) return reject("unsupported resource shape");
        if (!l.fovea_width || !l.fovea_height || !l.periphery_width || !l.periphery_height ||
            (periphery && (pd.Width < l.periphery_width || pd.Height < l.periphery_height)) ||
            md.Width < l.fovea_width || md.Height < l.fovea_height ||
            cd.Width < l.fovea_width || cd.Height < l.fovea_height) return reject("source smaller than layout");
        // Pixels must reach the XR image unchanged, like Joey's byte copy. Typeless images adopt the
        // other side's encoding (1 UNORM, 2 sRGB). A typed view cannot be recast, so if typed source
        // and XR encodings differ the shader undoes the conversion the hardware will apply.
        int source = 0;
        for (const auto f : {md.Format, cd.Format, pd.Format}) {
            const int e = encoding_of(f);
            if (e < 0) return reject("unsupported source colour format");
            if (e == 0) continue;
            if (source != 0 && source != e) return reject("source colour encodings differ");
            source = e;
        }
        int output = encoding_of(dd.Format);
        if (output < 0) return reject("unsupported XR colour format");
        if (source == 0) source = output != 0 ? output : 1;
        if (output == 0) output = source;
        const auto rtv = typed(dd.Format, output == 2), main_srv = typed(md.Format, source == 2),
            capture_srv = typed(cd.Format, source == 2), periphery_srv = typed(pd.Format, source == 2);
        const float convert = source == output ? 0.f : (output == 2 ? 1.f : 2.f); // 1 decode, 2 encode
        ComPtr<ID3D12Device> a, b, c, d, e;
        if (FAILED(main->GetDevice(IID_PPV_ARGS(&a))) || FAILED(capture->GetDevice(IID_PPV_ARGS(&b))) ||
            FAILED(destination->GetDevice(IID_PPV_ARGS(&c))) || FAILED(cmd->GetDevice(IID_PPV_ARGS(&d))) ||
            (periphery && FAILED(periphery->GetDevice(IID_PPV_ARGS(&e)))) ||
            a.Get() != device || b.Get() != device || c.Get() != device || d.Get() != device ||
            (periphery && e.Get() != device))
            return reject("device mismatch");
        if (!prepare(device, rtv)) return false;

        if (main_ref_.Get() != main || capture_ref_.Get() != capture || periphery_ref_.Get() != periphery ||
            main_srv_ != main_srv || capture_srv_ != capture_srv || periphery_srv_ != periphery_srv) {
            D3D12_SHADER_RESOURCE_VIEW_DESC view{};
            view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
            view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            view.Texture2D.MipLevels = 1;
            auto cpu = srv_->GetCPUDescriptorHandleForHeapStart();
            view.Format = main_srv;
            device->CreateShaderResourceView(main, &view, cpu);
            cpu.ptr += device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
            view.Format = capture_srv;
            device->CreateShaderResourceView(capture, &view, cpu);
            cpu.ptr += device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
            view.Format = periphery_srv;
            device->CreateShaderResourceView(periphery, &view, cpu); // null resource = null descriptor
            main_ref_ = main; capture_ref_ = capture; periphery_ref_ = periphery;
            main_srv_ = main_srv; capture_srv_ = capture_srv; periphery_srv_ = periphery_srv;
        }
        if (destination_ref_.Get() != destination || destination_rtv_ != rtv) {
            D3D12_RENDER_TARGET_VIEW_DESC view{};
            view.Format = rtv;
            view.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
            device->CreateRenderTargetView(destination, &view, rtv_->GetCPUDescriptorHandleForHeapStart());
            destination_ref_ = destination; destination_rtv_ = rtv;
        }

        const auto ml = periphery_map(l, 0), mr = periphery_map(l, 1);
        const Constants k{
            {float(dd.Width / 2), float(dd.Height), float(l.fovea_width), float(l.fovea_height)},
            {l.window[0].u0, l.window[0].v0, l.window[0].u1, l.window[0].v1},
            {l.window[1].u0, l.window[1].v0, l.window[1].u1, l.window[1].v1},
            {ml.ax, ml.bx, ml.ay, ml.by},
            {mr.ax, mr.bx, mr.ay, mr.by},
            {float(l.periphery_width), float(l.periphery_height), float(pd.Width), float(pd.Height)},
            {float(md.Width), float(md.Height), float(cd.Width), float(cd.Height)},
            {0.08f, periphery ? 1.f : 0.f, static_cast<float>(debug_bits & 1u), convert}};

        transition(cmd, main, D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        transition(cmd, capture, D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        if (periphery) transition(cmd, periphery, D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        ID3D12DescriptorHeap* heaps[]{srv_.Get()};
        cmd->SetDescriptorHeaps(1, heaps);
        cmd->SetGraphicsRootSignature(root_.Get());
        cmd->SetPipelineState(pipeline_.Get());
        cmd->SetGraphicsRootDescriptorTable(0, srv_->GetGPUDescriptorHandleForHeapStart());
        cmd->SetGraphicsRoot32BitConstants(1, sizeof(Constants) / 4, &k, 0);
        const D3D12_VIEWPORT viewport{0.f, 0.f, float(dd.Width), float(dd.Height), 0.f, 1.f};
        const D3D12_RECT scissor{0, 0, LONG(dd.Width), LONG(dd.Height)};
        cmd->RSSetViewports(1, &viewport);
        cmd->RSSetScissorRects(1, &scissor);
        const auto target = rtv_->GetCPUDescriptorHandleForHeapStart();
        cmd->OMSetRenderTargets(1, &target, FALSE, nullptr);
        cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        cmd->DrawInstanced(3, 1, 0, 0);
        transition(cmd, main, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
        transition(cmd, capture, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
        if (periphery) transition(cmd, periphery, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
        return true;
    }
    const std::string& error() const { return error_; }

private:
    bool reject(const char* why) { error_ = why; return false; }
    bool check(HRESULT hr, const char* what) {
        if (SUCCEEDED(hr)) return true;
        error_ = std::string(what) + " failed, HRESULT " + std::to_string(static_cast<uint32_t>(hr));
        return false;
    }
    static int encoding_of(DXGI_FORMAT f) {
        switch (f) {
        case DXGI_FORMAT_B8G8R8A8_TYPELESS: case DXGI_FORMAT_R8G8B8A8_TYPELESS: return 0;
        case DXGI_FORMAT_B8G8R8A8_UNORM: case DXGI_FORMAT_R8G8B8A8_UNORM: return 1;
        case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB: case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB: return 2;
        default: return -1;
        }
    }
    // The view format for an 8-bit BGRA/RGBA image (typeless or typed) in the chosen encoding.
    static DXGI_FORMAT typed(DXGI_FORMAT f, bool srgb) {
        const bool bgra = f == DXGI_FORMAT_B8G8R8A8_TYPELESS || f == DXGI_FORMAT_B8G8R8A8_UNORM ||
            f == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        if (bgra) return srgb ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        return srgb ? DXGI_FORMAT_R8G8B8A8_UNORM_SRGB : DXGI_FORMAT_R8G8B8A8_UNORM;
    }
    static void transition(ID3D12GraphicsCommandList* cmd, ID3D12Resource* r,
                           D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
        D3D12_RESOURCE_BARRIER b{};
        b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition = {r, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before, after};
        cmd->ResourceBarrier(1, &b);
    }
    // Root signature and heaps once per slot; the PSO again only if the XR format changes.
    bool prepare(ID3D12Device* device, DXGI_FORMAT rtv) {
        if (device_.Get() != device) {
            device_.Reset(); root_.Reset(); pipeline_.Reset(); srv_.Reset(); rtv_.Reset();
            main_ref_.Reset(); capture_ref_.Reset(); periphery_ref_.Reset(); destination_ref_.Reset();
            pipeline_rtv_ = destination_rtv_ = main_srv_ = capture_srv_ = periphery_srv_ = DXGI_FORMAT_UNKNOWN;
            D3D12_DESCRIPTOR_RANGE range{};
            range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
            range.NumDescriptors = 3;
            D3D12_ROOT_PARAMETER params[2]{};
            params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
            params[0].DescriptorTable = {1, &range};
            params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
            params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
            params[1].Constants = {0, 0, sizeof(Constants) / 4};
            params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
            D3D12_STATIC_SAMPLER_DESC sampler{};
            sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
            sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
            sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_ALWAYS;
            sampler.MaxAnisotropy = 1;
            sampler.MaxLOD = D3D12_FLOAT32_MAX;
            sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
            const D3D12_ROOT_SIGNATURE_DESC desc{2, params, 1, &sampler, D3D12_ROOT_SIGNATURE_FLAG_NONE};
            ComPtr<ID3DBlob> blob, errors;
            if (!check(D3D12SerializeRootSignature(&desc, D3D_ROOT_SIGNATURE_VERSION_1, &blob, &errors), "Root signature") ||
                !check(device->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(),
                    IID_PPV_ARGS(&root_)), "CreateRootSignature")) return false;
            D3D12_DESCRIPTOR_HEAP_DESC heap{};
            heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
            heap.NumDescriptors = 3;
            heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
            if (!check(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&srv_)), "SRV heap")) return false;
            heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
            heap.NumDescriptors = 1;
            heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
            if (!check(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&rtv_)), "RTV heap")) return false;
            device_ = device;
        }
        if (pipeline_ && pipeline_rtv_ == rtv) return true;
        pipeline_.Reset();
        D3D12_GRAPHICS_PIPELINE_STATE_DESC g{};
        g.pRootSignature = root_.Get();
        g.VS = {triview_vertex_shader_bytecode, sizeof(triview_vertex_shader_bytecode)};
        g.PS = {triview_pixel_shader_bytecode, sizeof(triview_pixel_shader_bytecode)};
        auto& blend = g.BlendState.RenderTarget[0];
        blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
        blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
        blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
        blend.LogicOp = D3D12_LOGIC_OP_NOOP;
        blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
        g.SampleMask = UINT_MAX;
        g.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
        g.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
        g.RasterizerState.DepthClipEnable = TRUE;
        g.DepthStencilState.DepthEnable = FALSE;
        g.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ZERO;
        g.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        g.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        g.NumRenderTargets = 1;
        g.RTVFormats[0] = rtv;
        g.SampleDesc.Count = 1;
        if (!check(device->CreateGraphicsPipelineState(&g, IID_PPV_ARGS(&pipeline_)), "Tri-View PSO")) return false;
        pipeline_rtv_ = rtv;
        return true;
    }

    ComPtr<ID3D12Device> device_;
    ComPtr<ID3D12RootSignature> root_;
    ComPtr<ID3D12PipelineState> pipeline_;
    ComPtr<ID3D12DescriptorHeap> srv_, rtv_;
    ComPtr<ID3D12Resource> main_ref_, capture_ref_, periphery_ref_, destination_ref_;
    DXGI_FORMAT pipeline_rtv_{DXGI_FORMAT_UNKNOWN}, destination_rtv_{DXGI_FORMAT_UNKNOWN};
    DXGI_FORMAT main_srv_{DXGI_FORMAT_UNKNOWN}, capture_srv_{DXGI_FORMAT_UNKNOWN}, periphery_srv_{DXGI_FORMAT_UNKNOWN};
    std::string error_;
};

// One-shot automatic GPU capture (no headset questions): copies each source image (a box at its texture
// origin) to a readback buffer in the same command list as the composite, then, once the command list's
// fence has passed, a worker thread maps the buffers and writes one ZIP: half-size BMPs + region statistics
// + the caller's report. Sources must be in RENDER_TARGET state and are left in it.
class GpuCapture {
public:
    struct Source {
        std::string name;
        ID3D12Resource* resource{};
        uint32_t width{}, height{};              // box from the texture origin
        std::vector<capture::Region> regions;    // statistics written to report.txt
    };

    bool record(ID3D12Device* device, ID3D12GraphicsCommandList* cmd, const std::vector<Source>& sources,
                ID3D12Fence* fence, UINT64 done_value, std::filesystem::path zip, std::string report) {
        if (!device || !cmd || !fence || job_) return false;
        auto job = std::make_shared<Job>();
        job->zip = std::move(zip);
        job->report = std::move(report);
        for (const auto& src : sources) {
            if (!src.resource || !src.width || !src.height) continue;
            const auto desc = src.resource->GetDesc();
            if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.Width < src.width || desc.Height < src.height) continue;
            const int bgra = is_bgra(desc.Format);
            if (bgra < 0) { job->report += "skipped " + src.name + ": format " + std::to_string(int(desc.Format)) + "\n"; continue; }
            D3D12_RESOURCE_DESC box = desc;
            box.Width = src.width; box.Height = src.height; box.MipLevels = 1; box.DepthOrArraySize = 1;
            box.Flags = D3D12_RESOURCE_FLAG_NONE;
            Item item{};
            UINT64 bytes{};
            device->GetCopyableFootprints(&box, 0, 1, 0, &item.footprint, nullptr, nullptr, &bytes);
            D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_READBACK;
            D3D12_RESOURCE_DESC buffer{}; buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; buffer.Width = bytes;
            buffer.Height = buffer.DepthOrArraySize = buffer.MipLevels = 1; buffer.SampleDesc.Count = 1;
            buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
            if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer,
                    D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&item.buffer)))) {
                job->report += "skipped " + src.name + ": readback buffer\n";
                continue;
            }
            barrier(cmd, src.resource, D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION from{src.resource, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
            from.SubresourceIndex = 0;
            D3D12_TEXTURE_COPY_LOCATION to{item.buffer.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
            to.PlacedFootprint = item.footprint;
            const D3D12_BOX region{0, 0, 0, src.width, src.height, 1};
            cmd->CopyTextureRegion(&to, 0, 0, 0, &from, &region);
            barrier(cmd, src.resource, D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
            item.name = src.name; item.width = src.width; item.height = src.height; item.bgra = bgra == 1;
            item.regions = src.regions;
            char line[200];
            std::snprintf(line, sizeof(line), "source %s: texture %llux%u format %d, captured box %ux%u at (0,0)\n",
                src.name.c_str(), static_cast<unsigned long long>(desc.Width), desc.Height, int(desc.Format), src.width, src.height);
            job->report += line;
            job->items.push_back(std::move(item));
        }
        if (job->items.empty()) return false;
        fence_ = fence; done_value_ = done_value; job_ = std::move(job); polls_ = 0;
        return true;
    }

    // Call once per frame. Returns true when a capture was handed to the writer thread (or dropped).
    // synchronous = write in the calling thread (tests).
    bool poll(bool synchronous = false) {
        if (!job_) return false;
        if (fence_->GetCompletedValue() < done_value_) {
            if (++polls_ > 2000) { job_.reset(); fence_.Reset(); return true; } // command list never ran
            return false;
        }
        auto job = std::move(job_);
        fence_.Reset();
        if (synchronous) { write(*job); return true; }
        try {
            std::thread([job]() { write(*job); }).detach();
        } catch (...) {}
        return true;
    }
    bool pending() const { return job_ != nullptr; }

private:
    struct Item {
        std::string name;
        ComPtr<ID3D12Resource> buffer;
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
        uint32_t width{}, height{};
        bool bgra{true};
        std::vector<capture::Region> regions;
    };
    struct Job {
        std::filesystem::path zip;
        std::string report;
        std::vector<Item> items;
    };
    static int is_bgra(DXGI_FORMAT f) {
        switch (f) {
        case DXGI_FORMAT_B8G8R8A8_TYPELESS: case DXGI_FORMAT_B8G8R8A8_UNORM: case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB: return 1;
        case DXGI_FORMAT_R8G8B8A8_TYPELESS: case DXGI_FORMAT_R8G8B8A8_UNORM: case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB: return 0;
        default: return -1;
        }
    }
    static void barrier(ID3D12GraphicsCommandList* cmd, ID3D12Resource* r, D3D12_RESOURCE_STATES a, D3D12_RESOURCE_STATES b) {
        D3D12_RESOURCE_BARRIER x{};
        x.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        x.Transition = {r, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, a, b};
        cmd->ResourceBarrier(1, &x);
    }
    // Worker thread: Map is free-threaded for readback buffers.
    static void write(Job& job) {
        capture::Zip zip;
        std::string stats;
        for (auto& item : job.items) {
            void* mapped{};
            const D3D12_RANGE all{0, size_t(item.footprint.Footprint.RowPitch) * item.height};
            if (FAILED(item.buffer->Map(0, &all, &mapped)) || mapped == nullptr) { stats += item.name + ": map failed\n"; continue; }
            const capture::View view{static_cast<const uint8_t*>(mapped) + item.footprint.Offset,
                item.footprint.Footprint.RowPitch, item.width, item.height, item.bgra};
            stats += capture::format_stats(item.name, {"whole", 0, 0, item.width, item.height},
                capture::region_stats(view, {"whole", 0, 0, item.width, item.height}));
            for (const auto& r : item.regions) stats += capture::format_stats(item.name, r, capture::region_stats(view, r));
            zip.add(item.name + "_half.bmp", capture::half_bmp(view));
            const D3D12_RANGE none{0, 0};
            item.buffer->Unmap(0, &none);
            item.buffer.Reset();
        }
        zip.add("report.txt", job.report + "\n--- pixel statistics (non-black = any channel > 10) ---\n" + stats);
        const auto bytes = zip.finish();
        try {
            std::filesystem::create_directories(job.zip.parent_path());
            std::ofstream out(job.zip, std::ios::binary | std::ios::trunc);
            out.write(reinterpret_cast<const char*>(bytes.data()), std::streamsize(bytes.size()));
        } catch (...) {}
    }

    std::shared_ptr<Job> job_;
    ComPtr<ID3D12Fence> fence_;
    UINT64 done_value_{};
    uint32_t polls_{};
};

} // namespace uevr::triview::dx12

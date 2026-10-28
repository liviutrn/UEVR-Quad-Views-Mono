#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <mods/vr/d3d12/StockDibrDepth.hpp>
#include <array>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <vector>

using Microsoft::WRL::ComPtr;
static void check(HRESULT hr) { if (FAILED(hr)) throw std::runtime_error("D3D12 HRESULT " + std::to_string(unsigned(hr))); }
static void require(bool ok, const char* why) { if (!ok) throw std::runtime_error(why); }

int main(int argc, char** argv) try {
    const bool expect_overwrite = argc == 2 && std::string_view(argv[1]) == "--expect-overwrite";
    ComPtr<ID3D12Debug> debug;
    if (SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)))) debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory; check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIAdapter> adapter; check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
    ComPtr<ID3D12Device> device; check(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)));
    ComPtr<ID3D12InfoQueue> info; device.As(&info);
    D3D12_COMMAND_QUEUE_DESC qd{}; qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue; check(device->CreateCommandQueue(&qd, IID_PPV_ARGS(&queue)));
    ComPtr<ID3D12CommandAllocator> allocator; check(device->CreateCommandAllocator(qd.Type, IID_PPV_ARGS(&allocator)));
    ComPtr<ID3D12GraphicsCommandList> cmd; check(device->CreateCommandList(0, qd.Type, allocator.Get(), nullptr, IID_PPV_ARGS(&cmd)));
    check(cmd->Close());
    ComPtr<ID3D12Fence> fence; check(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)));
    UINT64 tick = 0;
    auto wait = [&] {
        check(queue->Signal(fence.Get(), ++tick));
        HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr); require(event != nullptr, "event allocation");
        check(fence->SetEventOnCompletion(tick, event));
        const auto outcome = WaitForSingleObject(event, 30000); CloseHandle(event);
        require(outcome == WAIT_OBJECT_0, "GPU wait timeout");
    };
    D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_DSV; hd.NumDescriptors = 2;
    ComPtr<ID3D12DescriptorHeap> heap; check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&heap)));
    const auto stride = device->GetDescriptorHandleIncrementSize(hd.Type);
    constexpr auto read = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    for (bool snapshot : {false, true}) {
        stock_dibr::DepthCapture capture;
        capture.configure(device.Get(), queue.Get(), 512, 256, true);
        capture.configure_duoview_sources(128, 128, 64, 64);
        if (snapshot) capture.arm_diagnostic_capture();
        std::array<ComPtr<ID3D12Resource>, 2> depth;
        std::array<D3D12_CPU_DESCRIPTOR_HANDLE, 2> handles;
        for (UINT eye = 0; eye < 2; ++eye) {
            D3D12_RESOURCE_DESC desc{}; desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
            desc.Width = desc.Height = eye ? 32 : 64; desc.DepthOrArraySize = desc.MipLevels = 1;
            desc.SampleDesc.Count = 1; desc.Format = DXGI_FORMAT_R32_TYPELESS;
            desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL;
            D3D12_HEAP_PROPERTIES properties{}; properties.Type = D3D12_HEAP_TYPE_DEFAULT;
            check(device->CreateCommittedResource(&properties, D3D12_HEAP_FLAG_NONE, &desc,
                D3D12_RESOURCE_STATE_DEPTH_WRITE, nullptr, IID_PPV_ARGS(&depth[eye])));
            handles[eye] = heap->GetCPUDescriptorHandleForHeapStart(); handles[eye].ptr += eye * stride;
            D3D12_DEPTH_STENCIL_VIEW_DESC view{}; view.Format = DXGI_FORMAT_D32_FLOAT;
            view.ViewDimension = D3D12_DSV_DIMENSION_TEXTURE2D;
            device->CreateDepthStencilView(depth[eye].Get(), &view, handles[eye]);
            capture.on_depth_stencil_view_created(depth[eye].Get(), &view, handles[eye]);
        }
        for (UINT eye = 0; eye < 2; ++eye) {
            check(allocator->Reset()); check(cmd->Reset(allocator.Get(), nullptr));
            capture.on_command_list_reset(cmd.Get());
            const float size = eye ? 32.f : 64.f;
            const D3D12_VIEWPORT viewport{0, 0, size, size, 0, 1};
            cmd->RSSetViewports(1, &viewport); capture.on_viewports(cmd.Get(), 1, &viewport);
            cmd->OMSetRenderTargets(0, nullptr, FALSE, &handles[eye]); capture.on_render_targets(cmd.Get(), 0, handles[eye]);
            cmd->ClearDepthStencilView(handles[eye], D3D12_CLEAR_FLAG_DEPTH, eye ? .25f : .5f, 0, 0, nullptr);
            cmd->OMSetRenderTargets(0, nullptr, FALSE, nullptr); capture.on_render_targets(cmd.Get(), 0, {});
            D3D12_RESOURCE_BARRIER barrier{}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barrier.Transition = {depth[eye].Get(), D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, D3D12_RESOURCE_STATE_DEPTH_WRITE, read};
            cmd->ResourceBarrier(1, &barrier); capture.on_post_resource_barriers(cmd.Get(), 1, &barrier);
            check(cmd->Close()); ID3D12CommandList* lists[]{cmd.Get()};
            queue->ExecuteCommandLists(1, lists); capture.on_command_lists_executed(queue.Get(), 1, lists);
            // Critical schedule missing from the earlier fixtures: a producer
            // completes before the NEXT source pass, with NO finish_frame.
            wait();
        }
        const auto count = capture.preview_count();
        if (expect_overwrite) {
            require(count == 1, "old implementation did not reproduce expected same-interval overwrite");
            std::cout << "REPRODUCED old bug: completed foveal copy overwritten before Present (snapshot=" << snapshot << ")\n";
        } else {
            require(count == 2, "completed foveal producer was overwritten before its Present consumer");
            capture.arm_diagnostic_capture();
            auto copies = capture.snapshot_candidates();
            require(copies.size() == 2, "snapshot lost one retained write version");
            require(copies[0].source.Get() != copies[1].source.Get(), "retained copies alias");
            capture.finish_frame(); wait();
            require(capture.preview_count() == 0, "retired depth reused for a newer color interval");
            std::cout << "PASS retained fovea + periphery across separately completed submissions (snapshot=" << snapshot << ")\n";
        }
    }
    if (info) for (UINT64 i = 0; i < info->GetNumStoredMessages(); ++i) {
        SIZE_T bytes{}; check(info->GetMessage(i, nullptr, &bytes)); std::vector<unsigned char> buffer(bytes);
        auto* message = reinterpret_cast<D3D12_MESSAGE*>(buffer.data()); check(info->GetMessage(i, message, &bytes));
        if (message->Severity <= D3D12_MESSAGE_SEVERITY_ERROR) throw std::runtime_error(message->pDescription);
    }
    return 0;
} catch (const std::exception& error) { std::cerr << "FAIL: " << error.what() << '\n'; return 1; }

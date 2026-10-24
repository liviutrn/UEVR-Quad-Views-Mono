#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>

#include "ManualDibrCapture.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
using namespace uevr::duoview::dibr;
using namespace uevr::duoview::dibr::dx12;
using uevr::duoview::CaptureSourceStamp;
using uevr::duoview::CommandListEpoch;
using uevr::duoview::command_list_epochs;

namespace {
constexpr UINT kWidth = 64;
constexpr UINT kHeight = 32;
constexpr uint32_t kSourceSubresource = 1; // array slice 1, depth plane 0
constexpr uint64_t kGeneration = 17;

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

void check(HRESULT result, const char* operation) {
    if (FAILED(result)) throw std::runtime_error(std::string(operation) + " failed: " +
        std::to_string(static_cast<uint32_t>(result)));
}

D3D12_HEAP_PROPERTIES heap_properties(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES properties{};
    properties.Type = type;
    properties.CreationNodeMask = properties.VisibleNodeMask = 1;
    return properties;
}

D3D12_RESOURCE_DESC buffer_desc(UINT64 size) {
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = size;
    desc.Height = desc.DepthOrArraySize = desc.MipLevels = 1;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    return desc;
}

ComPtr<ID3D12Resource> create_resource(ID3D12Device* device, const D3D12_RESOURCE_DESC& desc,
    D3D12_HEAP_TYPE heap_type, D3D12_RESOURCE_STATES initial_state,
    const D3D12_CLEAR_VALUE* clear_value = nullptr) {
    ComPtr<ID3D12Resource> resource;
    const auto properties = heap_properties(heap_type);
    check(device->CreateCommittedResource(&properties, D3D12_HEAP_FLAG_NONE, &desc,
        initial_state, clear_value, IID_PPV_ARGS(&resource)), "CreateCommittedResource");
    return resource;
}

void transition(ID3D12GraphicsCommandList* command_list, ID3D12Resource* resource,
    UINT subresource, D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition = {resource, subresource, before, after};
    command_list->ResourceBarrier(1, &barrier);
}

void clear_depth_gradient(ID3D12GraphicsCommandList* command_list,
    D3D12_CPU_DESCRIPTOR_HANDLE dsv, float upper, float lower) {
    command_list->ClearDepthStencilView(dsv, D3D12_CLEAR_FLAG_DEPTH, upper, 0, 0, nullptr);
    const D3D12_RECT lower_half{0, static_cast<LONG>(kHeight / 2),
        static_cast<LONG>(kWidth), static_cast<LONG>(kHeight)};
    command_list->ClearDepthStencilView(dsv, D3D12_CLEAR_FLAG_DEPTH, lower, 0, 1, &lower_half);
}

void wait_for_fence(ID3D12Fence* fence, uint64_t value, HANDLE event, const char* operation) {
    if (fence->GetCompletedValue() >= value) return;
    check(fence->SetEventOnCompletion(value, event), "SetEventOnCompletion");
    if (WaitForSingleObject(event, 30000) != WAIT_OBJECT_0)
        throw std::runtime_error(std::string(operation) + " timed out");
}

void check_debug_errors(ID3D12InfoQueue* info_queue, const char* label) {
    if (!info_queue) return;
    const auto count = info_queue->GetNumStoredMessagesAllowedByRetrievalFilter();
    for (UINT64 index = 0; index < count; ++index) {
        SIZE_T length = 0;
        check(info_queue->GetMessage(index, nullptr, &length), "GetMessage(size)");
        std::vector<uint8_t> storage(length);
        auto* message = reinterpret_cast<D3D12_MESSAGE*>(storage.data());
        check(info_queue->GetMessage(index, message, &length), "GetMessage");
        if (message->Severity == D3D12_MESSAGE_SEVERITY_ERROR ||
            message->Severity == D3D12_MESSAGE_SEVERITY_CORRUPTION) {
            throw std::runtime_error(std::string(label) + ": " +
                (message->pDescription ? message->pDescription : "D3D12 error without description"));
        }
    }
}

struct Harness {
    ComPtr<ID3D12Device> device{};
    ComPtr<ID3D12CommandQueue> queue{};
    ComPtr<ID3D12CommandAllocator> allocator{};
    ComPtr<ID3D12GraphicsCommandList> command_list{};
    ComPtr<ID3D12Fence> test_fence{};
    ComPtr<ID3D12InfoQueue> info_queue{};
    HANDLE event{};
    ManualDibrCapture capture{};
    CommandListEpoch epoch{};
    uint64_t queue_order{};
    uint64_t test_fence_value{};

    uintptr_t command_key() const { return reinterpret_cast<uintptr_t>(command_list.Get()); }

    void open_list() {
        check(allocator->Reset(), "Reset command allocator");
        check(command_list->Reset(allocator.Get(), nullptr), "Reset graphics command list");
        epoch = command_list_epochs.reset(command_key());
        capture.on_command_list_reset(command_list.Get(), epoch.value);
        require(epoch.known && epoch.open && !epoch.closed, "Command-list epoch must open on Reset");
    }

    void close_list() {
        check(command_list->Close(), "Close graphics command list");
        command_list_epochs.close(command_key(), true);
        capture.on_command_list_close(command_list.Get(), true, epoch.value);
        const auto closed = command_list_epochs.current(command_key());
        require(closed.known && closed.closed && !closed.open,
            "Command-list epoch must close before ExecuteCommandLists");
    }

    void execute_and_wait() {
        ID3D12CommandList* lists[]{command_list.Get()};
        queue->ExecuteCommandLists(1, lists);
        ++queue_order;
        capture.on_queue_execute_command_lists(queue.Get(), 1, lists, queue_order);
        ++test_fence_value;
        check(queue->Signal(test_fence.Get(), test_fence_value), "Signal test completion fence");
        wait_for_fence(test_fence.Get(), test_fence_value, event, "WARP queue");
    }

    void execute_without_capture_observer() {
        ID3D12CommandList* lists[]{command_list.Get()};
        queue->ExecuteCommandLists(1, lists);
        ++queue_order;
        ++test_fence_value;
        check(queue->Signal(test_fence.Get(), test_fence_value), "Signal test completion fence");
        wait_for_fence(test_fence.Get(), test_fence_value, event, "WARP queue");
    }

    void record_live_depth_transition(ID3D12Resource* source, D3D12_RESOURCE_STATES before,
        uint64_t frame, float upper, float lower, D3D12_CPU_DESCRIPTOR_HANDLE dsv) {
        if (before == D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE)
            transition(command_list.Get(), source, kSourceSubresource,
                D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_DEPTH_WRITE);
        clear_depth_gradient(command_list.Get(), dsv, upper, lower);

        D3D12_RESOURCE_BARRIER observed{};
        observed.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        observed.Transition = {source, kSourceSubresource, D3D12_RESOURCE_STATE_DEPTH_WRITE,
            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE};
        const CaptureSourceStamp stamp{kGeneration, frame, frame + 500,
            uevr::duoview::capture_role_stereo_pair, true};
        capture.on_resource_barriers_scoped(command_list.Get(), 1, &observed, stamp, epoch);
        command_list->ResourceBarrier(1, &observed);
    }
};

std::vector<float> copy_owned_depth(Harness& harness, ID3D12Resource* texture) {
    const auto desc = texture->GetDesc();
    require(desc.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
        desc.Format == DXGI_FORMAT_R32_TYPELESS && desc.DepthOrArraySize == 1,
        "Owned snapshot must be an R32_TYPELESS single-slice texture");
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT rows = 0;
    UINT64 row_bytes = 0, total_bytes = 0;
    harness.device->GetCopyableFootprints(&desc, 0, 1, 0, &footprint, &rows, &row_bytes, &total_bytes);
    require(rows == kHeight && row_bytes == kWidth * sizeof(float) && total_bytes,
        "Owned R32 snapshot footprint must describe the full image");
    auto readback = create_resource(harness.device.Get(), buffer_desc(total_bytes),
        D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);

    harness.open_list();
    transition(harness.command_list.Get(), texture, 0,
        D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION source{};
    source.pResource = texture;
    source.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    source.SubresourceIndex = 0;
    D3D12_TEXTURE_COPY_LOCATION destination{};
    destination.pResource = readback.Get();
    destination.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    destination.PlacedFootprint = footprint;
    harness.command_list->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
    transition(harness.command_list.Get(), texture, 0,
        D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
    harness.close_list();
    harness.execute_and_wait();

    D3D12_RANGE read_range{0, static_cast<SIZE_T>(total_bytes)};
    void* mapped = nullptr;
    check(readback->Map(0, &read_range, &mapped), "Map owned depth readback");
    std::vector<float> pixels(static_cast<size_t>(kWidth) * kHeight);
    const auto* bytes = static_cast<const uint8_t*>(mapped);
    for (UINT y = 0; y < kHeight; ++y)
        for (UINT x = 0; x < kWidth; ++x)
            std::memcpy(&pixels[size_t{y} * kWidth + x], bytes + footprint.Offset +
                uint64_t{y} * footprint.Footprint.RowPitch + uint64_t{x} * sizeof(float), sizeof(float));
    const D3D12_RANGE written_range{0, 0};
    readback->Unmap(0, &written_range);
    return pixels;
}

void require_gradient(const std::vector<float>& pixels, float upper, float lower, const char* message) {
    require(pixels.size() == size_t{kWidth} * kHeight, message);
    const float got_upper = pixels[size_t{kHeight / 4} * kWidth + kWidth / 3];
    const float got_lower = pixels[size_t{3 * kHeight / 4} * kWidth + kWidth / 3];
    if (std::abs(got_upper - upper) > 0.0001f || std::abs(got_lower - lower) > 0.0001f)
        throw std::runtime_error(std::string(message) + " (measured " + std::to_string(got_upper) +
            ", " + std::to_string(got_lower) + ")");
}
}

int main() try {
    ComPtr<ID3D12Debug> debug;
    const bool debug_enabled = SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)));
    if (debug_enabled) debug->EnableDebugLayer();

    ComPtr<IDXGIFactory4> factory;
    check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)), "CreateDXGIFactory1");
    ComPtr<IDXGIAdapter> adapter;
    check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)), "EnumWarpAdapter");
    Harness harness{};
    check(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0,
        IID_PPV_ARGS(&harness.device)), "D3D12CreateDevice(WARP)");
    (void)harness.device.As(&harness.info_queue);

    D3D12_COMMAND_QUEUE_DESC queue_desc{};
    queue_desc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    check(harness.device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&harness.queue)),
        "Create direct command queue");
    check(harness.device->CreateCommandAllocator(queue_desc.Type, IID_PPV_ARGS(&harness.allocator)),
        "Create command allocator");
    check(harness.device->CreateCommandList(0, queue_desc.Type, harness.allocator.Get(), nullptr,
        IID_PPV_ARGS(&harness.command_list)), "Create graphics command list");
    check(harness.device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&harness.test_fence)),
        "Create test fence");
    harness.event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!harness.event) throw std::runtime_error("CreateEventW failed");

    D3D12_RESOURCE_DESC source_desc{};
    source_desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    source_desc.Width = kWidth;
    source_desc.Height = kHeight;
    source_desc.DepthOrArraySize = 2;
    source_desc.MipLevels = 1;
    source_desc.Format = DXGI_FORMAT_R32G8X24_TYPELESS;
    source_desc.SampleDesc.Count = 1;
    source_desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
    source_desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL;
    D3D12_CLEAR_VALUE clear_value{};
    clear_value.Format = DXGI_FORMAT_D32_FLOAT_S8X24_UINT;
    clear_value.DepthStencil.Depth = .9f;
    clear_value.DepthStencil.Stencil = 0;
    auto source = create_resource(harness.device.Get(), source_desc, D3D12_HEAP_TYPE_DEFAULT,
        D3D12_RESOURCE_STATE_DEPTH_WRITE, &clear_value);
    source->SetName(L"DuoView format-19 two-slice depth/stencil source");

    D3D12_PLACED_SUBRESOURCE_FOOTPRINT source_plane_footprint{};
    UINT source_plane_rows = 0;
    UINT64 source_plane_row_bytes = 0, source_plane_total_bytes = 0;
    harness.device->GetCopyableFootprints(&source_desc, kSourceSubresource, 1, 0,
        &source_plane_footprint, &source_plane_rows, &source_plane_row_bytes, &source_plane_total_bytes);
    require(source_plane_footprint.Footprint.Format == DXGI_FORMAT_R32_TYPELESS &&
        source_plane_rows == kHeight && source_plane_row_bytes == kWidth * sizeof(float) &&
        source_plane_total_bytes,
        "Format-19 array slice 1 plane 0 must expose an R32_TYPELESS staging footprint");

    D3D12_DESCRIPTOR_HEAP_DESC dsv_heap_desc{};
    dsv_heap_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_DSV;
    dsv_heap_desc.NumDescriptors = 2;
    dsv_heap_desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
    ComPtr<ID3D12DescriptorHeap> dsv_heap;
    check(harness.device->CreateDescriptorHeap(&dsv_heap_desc, IID_PPV_ARGS(&dsv_heap)),
        "Create DSV descriptor heap");
    const UINT dsv_increment = harness.device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_DSV);
    const auto dsv_start = dsv_heap->GetCPUDescriptorHandleForHeapStart();
    D3D12_DEPTH_STENCIL_VIEW_DESC dsv_desc{};
    dsv_desc.Format = DXGI_FORMAT_D32_FLOAT_S8X24_UINT;
    dsv_desc.ViewDimension = D3D12_DSV_DIMENSION_TEXTURE2DARRAY;
    dsv_desc.Texture2DArray.MipSlice = 0;
    dsv_desc.Texture2DArray.ArraySize = 1;
    dsv_desc.Texture2DArray.FirstArraySlice = 0;
    harness.device->CreateDepthStencilView(source.Get(), &dsv_desc, dsv_start);
    dsv_desc.Texture2DArray.FirstArraySlice = 1;
    const D3D12_CPU_DESCRIPTOR_HANDLE selected_dsv{dsv_start.ptr + dsv_increment};
    harness.device->CreateDepthStencilView(source.Get(), &dsv_desc, selected_dsv);

    // Initialize both slices through real DSV clears. Slice zero is a distinct
    // sentinel; the selected slice has a multi-row depth gradient.
    harness.command_list->ClearDepthStencilView(dsv_start, D3D12_CLEAR_FLAG_DEPTH, .9f, 0, 0, nullptr);
    clear_depth_gradient(harness.command_list.Get(), selected_dsv, .25f, .75f);
    check(harness.command_list->Close(), "Close depth initialization command list");
    harness.execute_without_capture_observer();

    harness.capture.set_requested(true, true);
    harness.capture.on_depth_stencil_view_created(source.Get(), &dsv_desc, selected_dsv);
    const auto observed = harness.capture.candidates();
    require(observed.size() == 1, "The real selected DSV must register one capture candidate");
    const auto original_key = observed.front().candidate.key;
    require(original_key.subresource == kSourceSubresource &&
        observed.front().candidate.format == static_cast<uint32_t>(DXGI_FORMAT_R32G8X24_TYPELESS) &&
        observed.front().candidate.capture_supported,
        "The format-19 DSV candidate must identify array-slice-1 depth plane 0");
    require(harness.capture.assign_periphery(original_key), "The valid depth candidate must be assignable");

    // Record a capture and deliberately discard its command list. Reset must
    // cancel the unsubmitted lease and roll back the staging state before the
    // exact same source transition is captured and submitted again.
    harness.open_list();
    harness.record_live_depth_transition(source.Get(), D3D12_RESOURCE_STATE_DEPTH_WRITE,
        101, .25f, .75f, selected_dsv);
    harness.close_list();

    if (harness.info_queue) harness.info_queue->ClearStoredMessages();
    harness.open_list();
    harness.record_live_depth_transition(source.Get(), D3D12_RESOURCE_STATE_DEPTH_WRITE,
        101, .25f, .75f, selected_dsv);
    harness.close_list();
    harness.execute_and_wait();
    check_debug_errors(harness.info_queue.Get(),
        "Discarded capture followed by recapture must have legal real resource states");

    const ProducerKey first_producer{kGeneration, 101};
    auto first_packet = harness.capture.selected_periphery(first_producer,
        harness.queue.Get(), harness.queue_order + 1);
    require(first_packet.has_value(), "Submitted format-19 copy must be selectable for its exact producer");
    require(first_packet->candidate.key == original_key && first_packet->sample.copy.origin_subresource == 1 &&
        first_packet->sample.copy.owned_subresource == 0 &&
        first_packet->sample.copy.capture_serial == first_packet->sample.capture_serial &&
        first_packet->owned_format == static_cast<uint32_t>(DXGI_FORMAT_R32_TYPELESS) &&
        first_packet->texture->GetDesc().Format == DXGI_FORMAT_R32_TYPELESS,
        "Copy receipt must preserve the nonzero source slice and owned zero-slice R32 texture");
    require_gradient(copy_owned_depth(harness, first_packet->texture.Get()), .25f, .75f,
        "The owned GPU texture must contain selected plane-0 gradient, not slice 0 or stencil");

    // Exercise the actual asynchronous preview readback path with a row
    // gradient. A multi-row assertion catches incorrect or missing footprints.
    harness.open_list();
    const auto preview_count = harness.capture.record_preview_readbacks(harness.device.Get(),
        harness.command_list.Get(), harness.queue.Get(), harness.epoch.value);
    require(preview_count == 1, "A live selected snapshot must record one fenced preview readback");
    harness.close_list();
    harness.execute_and_wait();
    harness.capture.poll_completed_previews();
    const auto after_preview = harness.capture.candidates();
    require(after_preview.size() == 1 && after_preview[0].preview &&
        valid_preview_payload(*after_preview[0].preview, original_key),
        "Preview must publish only after its private readback fence and queue proof complete");
    const auto& preview = *after_preview[0].preview;
    const auto preview_upper = preview.raw_depth[size_t{kPreviewHeight / 4} * kPreviewWidth + kPreviewWidth / 3];
    const auto preview_lower = preview.raw_depth[size_t{3 * kPreviewHeight / 4} * kPreviewWidth + kPreviewWidth / 3];
    require(std::abs(preview_upper - .25f) < .0001f && std::abs(preview_lower - .75f) < .0001f,
        "Preview readback footprint must preserve the real multi-row depth gradient");

    // Keep three packet leases alive while submitting new frames. The fixed
    // ring must allocate other slots and then refuse a fourth overwrite.
    auto capture_frame = [&](uint64_t frame, float upper, float lower) {
        harness.open_list();
        harness.record_live_depth_transition(source.Get(), D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,
            frame, upper, lower, selected_dsv);
        harness.close_list();
        harness.execute_and_wait();
    };
    capture_frame(102, .30f, .80f);
    auto second_packet = harness.capture.selected_periphery({kGeneration, 102},
        harness.queue.Get(), harness.queue_order + 1);
    require(second_packet && second_packet->texture.Get() != first_packet->texture.Get(),
        "A live packet lease must keep its ring slot unavailable to the next frame");
    require_gradient(copy_owned_depth(harness, second_packet->texture.Get()), .30f, .80f,
        "The second producer packet must be copied by a real same-queue consumer");
    capture_frame(103, .40f, .70f);
    auto third_packet = harness.capture.selected_periphery({kGeneration, 103},
        harness.queue.Get(), harness.queue_order + 1);
    require(third_packet && third_packet->texture.Get() != first_packet->texture.Get() &&
        third_packet->texture.Get() != second_packet->texture.Get(),
        "Three retained packet leases must occupy distinct immutable snapshot slots");
    require_gradient(copy_owned_depth(harness, third_packet->texture.Get()), .40f, .70f,
        "The third producer packet must be copied by a real same-queue consumer");

    capture_frame(104, .55f, .65f);
    require(!harness.capture.selected_periphery({kGeneration, 104},
        harness.queue.Get(), harness.queue_order + 1),
        "A full ring of GPU/CPU-held snapshots must refuse an overwrite");
    ID3D12Resource* reusable_texture = second_packet->texture.Get();
    second_packet.reset();
    capture_frame(104, .55f, .65f);
    auto fourth_packet = harness.capture.selected_periphery({kGeneration, 104},
        harness.queue.Get(), harness.queue_order + 1);
    require(fourth_packet && fourth_packet->texture.Get() == reusable_texture &&
        fourth_packet->sample.capture_serial != first_packet->sample.capture_serial,
        "A completed released slot may be reused under a new capture serial");
    require_gradient(copy_owned_depth(harness, fourth_packet->texture.Get()), .55f, .65f,
        "The reused slot must be read by a real same-queue consumer");
    require_gradient(copy_owned_depth(harness, first_packet->texture.Get()), .25f, .75f,
        "A retained old packet must remain immutable after later captures and slot reuse");
    require_gradient(copy_owned_depth(harness, third_packet->texture.Get()), .40f, .70f,
        "A retained third slot must remain immutable after ring reuse");
    require_gradient(copy_owned_depth(harness, fourth_packet->texture.Get()), .55f, .65f,
        "The reused snapshot slot must contain only the new producer frame");

    // Reset while consumers still hold packet leases. The candidate must stay
    // alive until an actual queue consumer finishes and every CPU hold drops.
    harness.capture.reset();
    require(harness.capture.candidates().size() == 1,
        "Reset must retain candidate resources while immutable packet leases are held");
    require(!harness.capture.selected_periphery({kGeneration, 104},
        harness.queue.Get(), harness.queue_order + 1),
        "Reset must immediately stop new packet selection");
    auto reset_consumer_copy = copy_owned_depth(harness, first_packet->texture.Get());
    require_gradient(reset_consumer_copy, .25f, .75f,
        "A consumer already holding the lease may finish its GPU copy after reset");
    first_packet.reset();
    third_packet.reset();
    fourth_packet.reset();
    harness.capture.poll_completed_previews();
    require(harness.capture.candidates().empty(),
        "Retired candidates must collect after producer/consumer fences and packet holds complete");

    // Re-registering the same COM resource after reset must use new IDs so an
    // old UI key can never select the new generation (ABA protection).
    harness.capture.resume();
    harness.capture.set_requested(true, true);
    harness.capture.on_depth_stencil_view_created(source.Get(), &dsv_desc, selected_dsv);
    const auto after_reset = harness.capture.candidates();
    require(after_reset.size() == 1 && after_reset[0].candidate.key.id > original_key.id &&
        after_reset[0].candidate.key.resource_generation > original_key.resource_generation &&
        after_reset[0].candidate.key != original_key,
        "Resource IDs and generations must not repeat after capture reset");

    check_debug_errors(harness.info_queue.Get(), "Format-19 capture lifecycle WARP validation");
    command_list_epochs.forget(harness.command_key());
    CloseHandle(harness.event);
    std::cout << "WARP production capture lifecycle: format-19 plane-0/slice-1 copy, discarded-list rollback, "
        << "row-gradient preview, fenced ring leases, safe reuse, reset retirement and no-ABA identity PASS";
    if (!debug_enabled) std::cout << " (D3D12 debug layer unavailable)";
    std::cout << '\n';
    return 0;
} catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
}

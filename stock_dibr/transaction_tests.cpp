#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

#include <mods/vr/d3d12/DIBRTransaction.hpp>

using Microsoft::WRL::ComPtr;
using d3d12::dibr_transaction::ExecuteResult;
using d3d12::dibr_transaction::OutputWriteState;

namespace {
void check(HRESULT result, const char* operation) {
    if (FAILED(result)) {
        throw std::runtime_error(std::string{operation} + " failed: 0x" +
            std::to_string(static_cast<uint32_t>(result)));
    }
}

void require(bool condition, const char* message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

D3D12_HEAP_PROPERTIES heap_properties(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES properties{};
    properties.Type = type;
    return properties;
}

D3D12_RESOURCE_DESC buffer_desc(UINT64 size) {
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = size;
    desc.Height = 1;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    return desc;
}

HRESULT create_buffer(
    ID3D12Device* device,
    UINT64 size,
    D3D12_HEAP_TYPE heap_type,
    D3D12_RESOURCE_STATES initial_state,
    ID3D12Resource** resource)
{
    const auto properties = heap_properties(heap_type);
    const auto desc = buffer_desc(size);
    return device->CreateCommittedResource(
        &properties,
        D3D12_HEAP_FLAG_NONE,
        &desc,
        initial_state,
        nullptr,
        IID_PPV_ARGS(resource));
}

struct RecordedCopy {
    ComPtr<ID3D12CommandAllocator> allocator{};
    ComPtr<ID3D12GraphicsCommandList> list{};
};

RecordedCopy record_copy(ID3D12Device* device, ID3D12Resource* source, ID3D12Resource* destination, UINT64 size) {
    RecordedCopy recording{};
    check(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&recording.allocator)),
        "CreateCommandAllocator");
    check(device->CreateCommandList(
        0,
        D3D12_COMMAND_LIST_TYPE_DIRECT,
        recording.allocator.Get(),
        nullptr,
        IID_PPV_ARGS(&recording.list)),
        "CreateCommandList");
    recording.list->CopyBufferRegion(destination, 0, source, 0, size);
    return recording;
}

ExecuteResult submit_with_fault(
    ID3D12CommandQueue* queue,
    ID3D12Fence* fence,
    HANDLE event_handle,
    RecordedCopy& recording,
    UINT64 fence_value,
    bool fail_close,
    bool fail_signal,
    bool fail_event,
    bool& did_submit)
{
    HRESULT close_result{E_FAIL};
    HRESULT signal_result{E_FAIL};
    HRESULT event_result{E_FAIL};
    ID3D12CommandList* const lists[] = {recording.list.Get()};
    return d3d12::dibr_transaction::submit_recorded_commands(
        [&] {
            close_result = fail_close ? E_FAIL : recording.list->Close();
            return close_result;
        },
        [&] {
            did_submit = true;
            queue->ExecuteCommandLists(1, lists);
        },
        [&] {
            signal_result = fail_signal ? E_FAIL : queue->Signal(fence, fence_value);
            return signal_result;
        },
        [&] {
            event_result = fail_event ? E_FAIL : fence->SetEventOnCompletion(fence_value, event_handle);
            return event_result;
        });
}

void wait_for_fence(ID3D12Fence* fence, UINT64 value) {
    if (fence->GetCompletedValue() >= value) {
        return;
    }
    HANDLE event_handle = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    require(event_handle != nullptr, "CreateEventW returned null");
    const auto set_result = fence->SetEventOnCompletion(value, event_handle);
    if (FAILED(set_result)) {
        CloseHandle(event_handle);
        check(set_result, "SetEventOnCompletion");
    }
    const auto wait_result = WaitForSingleObject(event_handle, INFINITE);
    CloseHandle(event_handle);
    require(wait_result == WAIT_OBJECT_0, "fence event did not complete");
}

std::array<uint8_t, 512> read_bytes(ID3D12Resource* resource) {
    D3D12_RANGE read_range{0, 512};
    void* mapped{};
    check(resource->Map(0, &read_range, &mapped), "Map readback buffer");
    std::array<uint8_t, 512> bytes{};
    std::memcpy(bytes.data(), mapped, bytes.size());
    const D3D12_RANGE no_writes{0, 0};
    resource->Unmap(0, &no_writes);
    return bytes;
}

void fill_upload(ID3D12Resource* resource, uint8_t value) {
    const D3D12_RANGE no_reads{0, 0};
    void* mapped{};
    check(resource->Map(0, &no_reads, &mapped), "Map upload buffer");
    std::memset(mapped, value, 512);
    const D3D12_RANGE written{0, 512};
    resource->Unmap(0, &written);
}

void verify_fill(ID3D12Resource* resource, uint8_t value, const char* message) {
    const auto bytes = read_bytes(resource);
    require(std::all_of(bytes.begin(), bytes.end(), [value](uint8_t byte) { return byte == value; }), message);
}

void test_alpha_consumer_selection() {
    using d3d12::dibr_transaction::needs_ui_alpha;
    require(!needs_ui_alpha(false, false, false), "inactive UI features requested alpha");
    require(needs_ui_alpha(true, false, false), "UI edge guard did not request alpha");
    require(needs_ui_alpha(false, true, false), "footprint reprojection did not request alpha");
    require(needs_ui_alpha(false, false, true), "footprint debug mask did not request alpha");
}

void test_discard_open_recording(ID3D12Device* device) {
    ComPtr<ID3D12CommandAllocator> allocator{};
    ComPtr<ID3D12GraphicsCommandList> list{};
    check(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)),
        "Create discard allocator");
    check(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr, IID_PPV_ARGS(&list)),
        "Create discard list");

    bool closed{};
    bool allocator_reset{};
    bool list_reset{};
    const auto discarded = d3d12::dibr_transaction::discard_open_recording(
        [&] {
            closed = true;
            return list->Close();
        },
        [&] {
            require(closed, "discard reset allocator before closing the command list");
            allocator_reset = true;
            return allocator->Reset();
        },
        [&] {
            require(allocator_reset, "discard reset list before resetting its allocator");
            list_reset = true;
            return list->Reset(allocator.Get(), nullptr);
        },
        [&] { return false; });
    require(discarded && list_reset, "open recording was not closed and reset");
    check(list->Close(), "Close list reopened by discard");

    // A failed Close cannot be followed by allocator reset. The production
    // helper must instead invoke the caller's safe idle-context recreation.
    check(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)),
        "Create fault discard allocator");
    check(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr, IID_PPV_ARGS(&list)),
        "Create fault discard list");
    bool reset_after_close_failure{};
    bool recreated{};
    const auto recovered = d3d12::dibr_transaction::discard_open_recording(
        [] { return E_FAIL; },
        [&] {
            reset_after_close_failure = true;
            return allocator->Reset();
        },
        [&] {
            reset_after_close_failure = true;
            return list->Reset(allocator.Get(), nullptr);
        },
        [&] {
            // This is the same safe operation as CommandContext::setup: drop
            // the never-submitted open list and create a fresh idle context.
            list.Reset();
            allocator.Reset();
            if (FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator))) ||
                FAILED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr, IID_PPV_ARGS(&list)))) {
                return false;
            }
            recreated = true;
            return true;
        });
    require(recovered && recreated && !reset_after_close_failure,
        "failed Close did not recreate the never-submitted context safely");
    check(list->Close(), "Close list created by discard recovery");
}

void test_warp_transactions() {
    ComPtr<IDXGIFactory6> factory{};
    check(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "CreateDXGIFactory2");
    ComPtr<IDXGIAdapter> warp_adapter{};
    check(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp_adapter)), "EnumWarpAdapter");

    ComPtr<ID3D12Device> device{};
    check(D3D12CreateDevice(warp_adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)), "D3D12CreateDevice");
    test_discard_open_recording(device.Get());

    D3D12_COMMAND_QUEUE_DESC queue_desc{};
    queue_desc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue{};
    check(device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue)), "CreateCommandQueue");

    ComPtr<ID3D12Fence> fence{};
    check(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "CreateFence");

    ComPtr<ID3D12Resource> upload{};
    ComPtr<ID3D12Resource> readback{};
    check(create_buffer(device.Get(), 512, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ, &upload),
        "Create upload buffer");
    check(create_buffer(device.Get(), 512, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST, &readback),
        "Create readback buffer");

    // Establish a known old frame so a failed Close can prove that no stale or
    // partially recorded copy reached the presentation-side readback buffer.
    fill_upload(upload.Get(), 0x11);
    auto baseline = record_copy(device.Get(), upload.Get(), readback.Get(), 512);
    HANDLE event_handle = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    require(event_handle != nullptr, "CreateEventW returned null");
    bool did_submit{};
    const auto baseline_result = submit_with_fault(
        queue.Get(), fence.Get(), event_handle, baseline, 1, false, false, false, did_submit);
    require(baseline_result == ExecuteResult::SubmittedTracked && did_submit, "baseline work was not tracked");
    wait_for_fence(fence.Get(), 1);
    verify_fill(readback.Get(), 0x11, "baseline copy did not reach readback");

    // A preparation failure must leave the transaction unopened. The next
    // frame resizes both owned targets, prepares them successfully, then uses
    // the same production state helper before recording WARP work.
    OutputWriteState resize_state{};
    resize_state.replace_output();
    ComPtr<ID3D12Resource> old_preview{};
    ComPtr<ID3D12Resource> old_present{};
    check(create_buffer(device.Get(), 256, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST, &old_preview),
        "Create old preview buffer");
    check(create_buffer(device.Get(), 256, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST, &old_present),
        "Create old present buffer");
    ComPtr<ID3D12Resource> failed_resize{};
    const auto failed_preview = create_buffer(device.Get(), 0, D3D12_HEAP_TYPE_DEFAULT,
        D3D12_RESOURCE_STATE_COPY_DEST, &failed_resize);
    require(FAILED(failed_preview), "zero-width preview allocation fault was not injected");
    require(!resize_state.begin_after_preparation(SUCCEEDED(failed_preview), true),
        "preview allocation failure began a DIBR recording transaction");

    ComPtr<ID3D12Resource> resized_preview{};
    check(create_buffer(device.Get(), 512, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST, &resized_preview),
        "Create resized preview buffer");
    ComPtr<ID3D12Resource> failed_present{};
    const auto failed_presentation = create_buffer(device.Get(), 0, D3D12_HEAP_TYPE_DEFAULT,
        D3D12_RESOURCE_STATE_COPY_DEST, &failed_present);
    require(FAILED(failed_presentation), "zero-width presentation allocation fault was not injected");
    require(!resize_state.begin_after_preparation(true, SUCCEEDED(failed_presentation)),
        "presentation preparation failure began a DIBR recording transaction");
    require(!resize_state.recording_pending() && !resize_state.output_written(),
        "failed allocation changed preview write state");

    ComPtr<ID3D12Resource> resized_present{};
    ComPtr<ID3D12Resource> resized_readback{};
    check(create_buffer(device.Get(), 512, D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST, &resized_present),
        "Create resized presentation buffer");
    check(create_buffer(device.Get(), 512, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST, &resized_readback),
        "Create resized readback buffer");
    fill_upload(upload.Get(), 0x22);
    require(resize_state.begin_after_preparation(true, true), "prepared resized frame did not begin");
    auto resized = record_copy(device.Get(), upload.Get(), resized_preview.Get(), 512);
    // The presentation resource is a distinct target just like the packed
    // BGRA target in production. Record both hops before the same checked
    // submission phase used by CommandContext.
    D3D12_RESOURCE_BARRIER preview_barrier{};
    preview_barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    preview_barrier.Transition.pResource = resized_preview.Get();
    preview_barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    preview_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    preview_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    resized.list->ResourceBarrier(1, &preview_barrier);
    resized.list->CopyBufferRegion(resized_present.Get(), 0, resized_preview.Get(), 0, 512);
    D3D12_RESOURCE_BARRIER present_barrier = preview_barrier;
    present_barrier.Transition.pResource = resized_present.Get();
    present_barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
    present_barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    resized.list->ResourceBarrier(1, &present_barrier);
    resized.list->CopyBufferRegion(resized_readback.Get(), 0, resized_present.Get(), 0, 512);
    did_submit = false;
    const auto resize_result = submit_with_fault(
        queue.Get(), fence.Get(), event_handle, resized, 2, false, false, false, did_submit);
    require(resize_result == ExecuteResult::SubmittedTracked && did_submit, "resized frame was not submitted");
    require(!resize_state.output_written(), "output was marked written before valid execution");
    wait_for_fence(fence.Get(), 2);
    resize_state.commit();
    verify_fill(resized_readback.Get(), 0x22, "resized presentation copy did not recover");
    require(resize_state.output_written(), "retired resized output was not committed");

    // Close failure means the queue never saw this recording. The prior
    // presentation contents remain intact and the pending write is aborted.
    OutputWriteState close_state{};
    require(close_state.begin_after_preparation(true), "close-fault state did not begin");
    fill_upload(upload.Get(), 0x33);
    auto close_fault = record_copy(device.Get(), upload.Get(), readback.Get(), 512);
    did_submit = false;
    const auto close_result = submit_with_fault(
        queue.Get(), fence.Get(), event_handle, close_fault, 3, true, false, false, did_submit);
    require(close_result == ExecuteResult::NotSubmitted && !did_submit, "Close failure was published as submitted");
    close_state.abort();
    require(!close_state.output_written() && !close_state.recording_pending(), "Close failure left preview state pending");
    verify_fill(readback.Get(), 0x11, "Close failure changed the previously presented image");

    // Execute succeeds but Signal fails: the result is explicitly untracked,
    // so output remains unpublished and all COM resources stay alive through
    // a later retirement signal on the same queue.
    OutputWriteState signal_state{};
    require(signal_state.begin_after_preparation(true), "signal-fault state did not begin");
    fill_upload(upload.Get(), 0x44);
    auto signal_fault = record_copy(device.Get(), upload.Get(), readback.Get(), 512);
    did_submit = false;
    const auto signal_result = submit_with_fault(
        queue.Get(), fence.Get(), event_handle, signal_fault, 3, false, true, false, did_submit);
    require(signal_result == ExecuteResult::SubmittedUntracked && did_submit, "Signal failure lost submitted status");
    require(!signal_state.output_written() && signal_state.recording_pending(), "untracked output was published early");
    check(queue->Signal(fence.Get(), 3), "Recovery Signal");
    wait_for_fence(fence.Get(), 3);
    signal_state.commit();
    verify_fill(readback.Get(), 0x44, "resources were not retained through recovered signal retirement");
    require(signal_state.output_written(), "recovered submission did not commit output state");

    // Event-arm failure still has a valid queue fence. Do not publish until a
    // polling query observes that fence retire, then release the frame refs.
    OutputWriteState event_state{};
    event_state.replace_output();
    require(event_state.begin_after_preparation(true), "event-fault state did not begin");
    fill_upload(upload.Get(), 0x55);
    auto event_fault = record_copy(device.Get(), upload.Get(), readback.Get(), 512);
    did_submit = false;
    const auto event_result = submit_with_fault(
        queue.Get(), fence.Get(), event_handle, event_fault, 4, false, false, true, did_submit);
    require(event_result == ExecuteResult::SubmittedTrackedNeedsPolling && did_submit,
        "event-arm failure was not classified as tracked work");
    require(!event_state.output_written() && event_state.recording_pending(), "event failure published output before retirement");
    while (fence->GetCompletedValue() < 4) {
        Sleep(1);
    }
    event_state.commit();
    verify_fill(readback.Get(), 0x55, "event-failed submission did not complete");
    require(event_state.output_written(), "polled event-failed output was not committed");

    CloseHandle(event_handle);
}
} // namespace

int main() {
    try {
        test_alpha_consumer_selection();
        test_warp_transactions();
        std::cout << "DIBR checked submission transaction WARP tests passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "DIBR checked submission transaction WARP tests failed: " << error.what() << '\n';
        return 1;
    }
}

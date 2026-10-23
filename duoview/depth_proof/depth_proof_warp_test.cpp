#define WIN32_LEAN_AND_MEAN
#define NOMINMAX

#include "DepthProofSession.hpp"

#include <windows.h>
#include <d3d12sdklayers.h>
#include <dxgi1_4.h>
#include <wrl/client.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

using Microsoft::WRL::ComPtr;
using uevr::depth_proof::Session;

constexpr UINT kWidth = 128;
constexpr UINT kHeight = 128;
constexpr float kLeftDepth = 0.25f;
constexpr float kRightDepth = 0.75f;
constexpr std::chrono::seconds kExportTimeout{5};

struct TestFailure final : std::runtime_error {
    using std::runtime_error::runtime_error;
};

void require(bool condition, const std::string& message) {
    if (!condition) {
        throw TestFailure(message);
    }
}

std::string hr_string(HRESULT hr) {
    std::ostringstream out;
    out << "0x" << std::hex << std::uppercase << static_cast<unsigned long>(hr);
    return out.str();
}

void require_hr(HRESULT hr, const char* operation) {
    if (FAILED(hr)) {
        throw TestFailure(std::string(operation) + " failed with HRESULT " + hr_string(hr));
    }
}

struct WinEvent {
    HANDLE value{CreateEventW(nullptr, FALSE, FALSE, nullptr)};
    WinEvent() {
        require(value != nullptr, "CreateEventW failed");
    }
    ~WinEvent() {
        if (value) {
            CloseHandle(value);
        }
    }
    WinEvent(const WinEvent&) = delete;
    WinEvent& operator=(const WinEvent&) = delete;
};

struct DeviceContext {
    ComPtr<IDXGIFactory4> factory;
    ComPtr<IDXGIAdapter> warp_adapter;
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12InfoQueue> info_queue;
    bool debug_layer_enabled{};
};

DeviceContext make_warp_device() {
    DeviceContext result{};
    ComPtr<ID3D12Debug> debug;
    result.debug_layer_enabled = SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)));
    if (result.debug_layer_enabled) {
        debug->EnableDebugLayer();
    }

    UINT factory_flags = result.debug_layer_enabled ? DXGI_CREATE_FACTORY_DEBUG : 0;
    HRESULT factory_hr = CreateDXGIFactory2(factory_flags, IID_PPV_ARGS(&result.factory));
    if (FAILED(factory_hr) && factory_flags != 0) {
        factory_hr = CreateDXGIFactory2(0, IID_PPV_ARGS(&result.factory));
    }
    require_hr(factory_hr, "CreateDXGIFactory2");
    require_hr(result.factory->EnumWarpAdapter(IID_PPV_ARGS(&result.warp_adapter)), "EnumWarpAdapter");
    require_hr(D3D12CreateDevice(result.warp_adapter.Get(), D3D_FEATURE_LEVEL_11_0,
        IID_PPV_ARGS(&result.device)), "D3D12CreateDevice(WARP)");

    if (result.debug_layer_enabled && SUCCEEDED(result.device.As(&result.info_queue))) {
        result.info_queue->ClearStoredMessages();
    }
    return result;
}

struct TargetSpec {
    const char* name{};
    DXGI_FORMAT resource_format{};
    DXGI_FORMAT dsv_format{};
    bool has_stencil{};
};

struct DepthTarget {
    TargetSpec spec{};
    ComPtr<ID3D12Resource> resource;
    ComPtr<ID3D12DescriptorHeap> dsv_heap;
    D3D12_CPU_DESCRIPTOR_HANDLE dsv{};
};

DepthTarget make_depth_target(ID3D12Device* device, TargetSpec spec) {
    DepthTarget result{};
    result.spec = spec;

    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    heap.CreationNodeMask = 1;
    heap.VisibleNodeMask = 1;

    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = kWidth;
    desc.Height = kHeight;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.Format = spec.resource_format;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
    desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL;

    D3D12_CLEAR_VALUE clear{};
    clear.Format = spec.dsv_format;
    clear.DepthStencil.Depth = 1.0f;
    clear.DepthStencil.Stencil = 0;
    require_hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
        D3D12_RESOURCE_STATE_DEPTH_WRITE, &clear, IID_PPV_ARGS(&result.resource)),
        "CreateCommittedResource(depth target)");

    D3D12_DESCRIPTOR_HEAP_DESC dsv_heap_desc{};
    dsv_heap_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_DSV;
    dsv_heap_desc.NumDescriptors = 1;
    require_hr(device->CreateDescriptorHeap(&dsv_heap_desc, IID_PPV_ARGS(&result.dsv_heap)),
        "CreateDescriptorHeap(DSV)");

    D3D12_DEPTH_STENCIL_VIEW_DESC dsv_desc{};
    dsv_desc.Format = spec.dsv_format;
    dsv_desc.ViewDimension = D3D12_DSV_DIMENSION_TEXTURE2D;
    result.dsv = result.dsv_heap->GetCPUDescriptorHandleForHeapStart();
    device->CreateDepthStencilView(result.resource.Get(), &dsv_desc, result.dsv);
    return result;
}

struct Recording {
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> command_list;
};

Recording make_recording(ID3D12Device* device) {
    Recording result{};
    require_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,
        IID_PPV_ARGS(&result.allocator)), "CreateCommandAllocator");
    require_hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT,
        result.allocator.Get(), nullptr, IID_PPV_ARGS(&result.command_list)), "CreateCommandList");
    return result;
}

void reset_recording(Recording& recording) {
    require_hr(recording.allocator->Reset(), "ID3D12CommandAllocator::Reset");
    require_hr(recording.command_list->Reset(recording.allocator.Get(), nullptr),
        "ID3D12GraphicsCommandList::Reset");
}

D3D12_RESOURCE_BARRIER transition(ID3D12Resource* resource, UINT subresource,
        D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after,
        D3D12_RESOURCE_BARRIER_FLAGS flags = D3D12_RESOURCE_BARRIER_FLAG_NONE) {
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Flags = flags;
    barrier.Transition.pResource = resource;
    barrier.Transition.Subresource = subresource;
    barrier.Transition.StateBefore = before;
    barrier.Transition.StateAfter = after;
    return barrier;
}

void observe_then_apply(Session& session, ID3D12GraphicsCommandList* command_list,
        const D3D12_RESOURCE_BARRIER& barrier) {
    session.barriers(command_list, 1, &barrier);
    command_list->ResourceBarrier(1, &barrier);
}

void clear_depth(ID3D12GraphicsCommandList* command_list, const DepthTarget& target, float value) {
    const D3D12_CLEAR_FLAGS flags = target.spec.has_stencil
        ? static_cast<D3D12_CLEAR_FLAGS>(D3D12_CLEAR_FLAG_DEPTH | D3D12_CLEAR_FLAG_STENCIL)
        : D3D12_CLEAR_FLAG_DEPTH;
    command_list->ClearDepthStencilView(target.dsv, flags, value, 0, 0, nullptr);
}

void clear_depth_pattern(ID3D12GraphicsCommandList* command_list, const DepthTarget& target) {
    clear_depth(command_list, target, kRightDepth);
    const D3D12_RECT left_half{0, 0, static_cast<LONG>(kWidth / 2), static_cast<LONG>(kHeight)};
    command_list->ClearDepthStencilView(target.dsv, D3D12_CLEAR_FLAG_DEPTH,
        kLeftDepth, 0, 1, &left_half);
}

void execute_and_notify(ID3D12CommandQueue* queue, Session& session,
        ID3D12GraphicsCommandList* command_list) {
    ID3D12CommandList* lists[] = {command_list};
    session.submitting(queue, 1, lists);
    queue->ExecuteCommandLists(1, lists);
    session.submitted(queue, 1, lists);
}

void signal_and_wait(ID3D12CommandQueue* queue, ID3D12Fence* external_fence,
        WinEvent& completion_event, UINT64& external_value) {
    ++external_value;
    require_hr(queue->Signal(external_fence, external_value), "ID3D12CommandQueue::Signal(test fence)");
    if (external_fence->GetCompletedValue() < external_value) {
        require_hr(external_fence->SetEventOnCompletion(external_value, completion_event.value),
            "ID3D12Fence::SetEventOnCompletion");
        const DWORD wait = WaitForSingleObject(completion_event.value, 5000);
        require(wait == WAIT_OBJECT_0, "Timed out waiting for WARP queue fence");
    }
}

void submit_and_wait(ID3D12CommandQueue* queue, Session& session,
        ID3D12GraphicsCommandList* command_list, ID3D12Fence* external_fence,
        WinEvent& completion_event, UINT64& external_value) {
    execute_and_notify(queue, session, command_list);
    signal_and_wait(queue, external_fence, completion_event, external_value);
}

std::filesystem::path make_output_root() {
    return std::filesystem::current_path() / "proof-output";
}

void wait_for_export(Session& session) {
    const auto deadline = std::chrono::steady_clock::now() + kExportTimeout;
    while (!session.export_finished() && std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    require(session.export_finished(), "Timed out waiting for depth proof export worker");
}

std::string read_text(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    require(input.good(), "Could not open " + path.string());
    std::ostringstream contents;
    contents << input.rdbuf();
    require(input.good() || input.eof(), "Could not read " + path.string());
    return contents.str();
}

std::uint64_t json_uint(const std::string& json, const std::string& key) {
    const std::string marker = "\"" + key + "\":";
    const auto start = json.find(marker);
    require(start != std::string::npos, "Manifest is missing numeric field " + key);
    const auto digits = start + marker.size();
    const auto end = json.find_first_not_of("0123456789", digits);
    require(end != digits, "Manifest field is not an unsigned integer: " + key);
    return std::stoull(json.substr(digits, end == std::string::npos ? end : end - digits));
}

void validate_pgm(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    require(input.good(), "Missing PGM preview " + path.string());
    std::string magic, dimensions, maximum;
    std::getline(input, magic);
    std::getline(input, dimensions);
    std::getline(input, maximum);
    require(magic == "P5", "PGM preview is not binary P5");
    require(dimensions == "128 128", "PGM preview has unexpected dimensions");
    require(maximum == "255", "PGM preview has unexpected maximum value");
    std::vector<unsigned char> pixels((std::istreambuf_iterator<char>(input)), {});
    require(pixels.size() == static_cast<size_t>(kWidth) * kHeight,
        "PGM pixel payload has the wrong size");
    require(pixels[0] != pixels[static_cast<size_t>(kWidth / 2)],
        "PGM preview does not preserve the left/right depth boundary");
}

void validate_bmp(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    require(input.good(), "Missing BMP gallery preview " + path.string());
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(input)), {});
    constexpr size_t pixel_offset = 54;
    constexpr size_t row_pitch = (kWidth * 3 + 3) & ~size_t(3);
    require(bytes.size() == pixel_offset + row_pitch * kHeight,
        "BMP preview has the wrong byte size");
    require(bytes[0] == 'B' && bytes[1] == 'M', "Gallery preview is not a BMP image");
    const size_t left_pixel = pixel_offset;
    const size_t right_pixel = pixel_offset + (kWidth / 2) * 3;
    require(bytes[left_pixel] != bytes[right_pixel],
        "BMP gallery preview does not preserve the left/right depth boundary");
}

void validate_capture(const std::filesystem::path& folder, DXGI_FORMAT source_format,
        std::uint64_t expected_fence_value) {
    const auto raw_path = folder / "candidate_0.f32";
    std::ifstream raw(raw_path, std::ios::binary);
    require(raw.good(), "Missing raw depth file " + raw_path.string());
    std::vector<float> samples(static_cast<size_t>(kWidth) * kHeight);
    raw.read(reinterpret_cast<char*>(samples.data()),
        static_cast<std::streamsize>(samples.size() * sizeof(float)));
    require(raw.gcount() == static_cast<std::streamsize>(samples.size() * sizeof(float)),
        "Raw depth file has the wrong byte length");
    char extra{};
    require(!raw.read(&extra, 1), "Raw depth file has trailing bytes");
    for (size_t i = 0; i < samples.size(); ++i) {
        const float expected = (i % kWidth) < (kWidth / 2) ? kLeftDepth : kRightDepth;
        if (!std::isfinite(samples[i]) || std::abs(samples[i] - expected) > 1.0e-6f) {
            throw TestFailure("Raw depth sample " + std::to_string(i) + " was " +
                std::to_string(samples[i]) + ", expected " + std::to_string(expected));
        }
    }

    validate_pgm(folder / "candidate_0.pgm");
    validate_bmp(folder / "candidate_0.bmp");
    const auto manifest = read_text(folder / "manifest.json");
    require(json_uint(manifest, "recorded") == 1, "Expected exactly one recorded depth copy");
    require(json_uint(manifest, "submitted") == 1, "Expected exactly one submitted depth copy");
    require(json_uint(manifest, "completed") == 1, "Expected exactly one completed depth copy");
    require(json_uint(manifest, "recording_sealed") == 1,
        "Capture recording was not sealed by successful Reset before export");
    require(json_uint(manifest, "fence_value") == expected_fence_value,
        "Manifest did not preserve the last same-queue replay fence value");
    require(manifest.find("\"format\":" + std::to_string(static_cast<unsigned>(source_format))) != std::string::npos,
        "Manifest does not identify the WARP source format");
    require(manifest.find("NOT verified scene depth") != std::string::npos,
        "Manifest must retain the anonymous/unverified role disclaimer");
}

void run_gpu_capture(ID3D12Device* device, ID3D12CommandQueue* queue,
        ID3D12Fence* external_fence, WinEvent& completion_event,
        UINT64& external_value, const TargetSpec& spec,
        const std::filesystem::path& output_root) {
    const auto folder = output_root / spec.name;
    auto target = make_depth_target(device, spec);
    auto recording = make_recording(device);
    Session session;
    require(session.start(device, folder), std::string("Session::start failed for ") + spec.name);
    session.reset(recording.command_list.Get());

    clear_depth(recording.command_list.Get(), target, kLeftDepth);
    if (spec.has_stencil) {
        // Plane 1 stays shader-readable while the observer later snapshots only depth plane 0.
        const auto stencil_to_read = transition(target.resource.Get(), 1,
            D3D12_RESOURCE_STATE_DEPTH_WRITE, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        observe_then_apply(session, recording.command_list.Get(), stencil_to_read);
    }
    const auto first_depth_to_read = transition(target.resource.Get(), 0,
        D3D12_RESOURCE_STATE_DEPTH_WRITE, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    observe_then_apply(session, recording.command_list.Get(), first_depth_to_read);
    require_hr(recording.command_list->Close(), "Close first WARP command list");
    submit_and_wait(queue, session, recording.command_list.Get(), external_fence,
        completion_event, external_value);

    // Session intentionally waits for a full second of resource observations before prewarming.
    std::this_thread::sleep_for(std::chrono::milliseconds(1100));
    session.service(1);
    reset_recording(recording);
    session.reset(recording.command_list.Get());

    if (spec.has_stencil) {
        const auto stencil_to_write = transition(target.resource.Get(), 1,
            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_DEPTH_WRITE);
        observe_then_apply(session, recording.command_list.Get(), stencil_to_write);
    }
    const auto depth_to_write = transition(target.resource.Get(), 0,
        D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_DEPTH_WRITE);
    observe_then_apply(session, recording.command_list.Get(), depth_to_write);
    clear_depth_pattern(recording.command_list.Get(), target);

    if (spec.has_stencil) {
        // This is a rejected plane-1 observation. Plane 1 remains NPSR while plane 0 is copied.
        const auto stencil_to_read = transition(target.resource.Get(), 1,
            D3D12_RESOURCE_STATE_DEPTH_WRITE, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        observe_then_apply(session, recording.command_list.Get(), stencil_to_read);
    }
    const auto capture_depth_to_read = transition(target.resource.Get(), 0,
        D3D12_RESOURCE_STATE_DEPTH_WRITE, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    observe_then_apply(session, recording.command_list.Get(), capture_depth_to_read);
    require_hr(recording.command_list->Close(), "Close capture WARP command list");
    const bool replay_capture_list = spec.has_stencil;
    if (replay_capture_list) {
        // Re-execution is legal before Reset. The observer must retarget its
        // fence to the second queue signal and wait until Reset seals this epoch.
        execute_and_notify(queue, session, recording.command_list.Get());
        execute_and_notify(queue, session, recording.command_list.Get());
        signal_and_wait(queue, external_fence, completion_event, external_value);

        reset_recording(recording); // Both submissions are complete before allocator reset.
        session.reset(recording.command_list.Get()); // Seal the old recording epoch.
        require_hr(recording.command_list->Close(), "Close reset capture command list");
    } else {
        // Interleave Reset between ExecuteCommandLists and the post-submit observer callback.
        ID3D12CommandList* lists[] = {recording.command_list.Get()};
        session.submitting(queue, 1, lists);
        queue->ExecuteCommandLists(1, lists);
        signal_and_wait(queue, external_fence, completion_event, external_value);

        reset_recording(recording); // External fence proves the GPU no longer uses the allocator.
        session.reset(recording.command_list.Get());
        session.submitted(queue, 1, lists); // Pair the callback with the sealed old epoch.
        signal_and_wait(queue, external_fence, completion_event, external_value);
        require_hr(recording.command_list->Close(), "Close reset capture command list");
    }

    // The test's external queue fence retires only after Session's per-candidate signal.
    session.service(2);
    session.finish_for_test();
    session.service(3);
    wait_for_export(session);
    validate_capture(folder, spec.resource_format, replay_capture_list ? 2 : 1);
    std::cout << "PASS WARP capture " << spec.name << ": candidate_0.f32 preserves the 0.25/0.75 boundary"
        << (replay_capture_list ? " after same-queue replay at fence value 2" : "") << "; output="
        << folder.string() << '\n';
}

Recording make_empty_command_list(ID3D12Device* device) {
    return make_recording(device);
}

std::string finish_rejection_session(Session& session, const std::filesystem::path& folder) {
    session.finish_for_test();
    session.service(10);
    wait_for_export(session);
    return read_text(folder / "manifest.json");
}

void run_simple_rejection(ID3D12Device* device, const std::filesystem::path& root, const std::string& name,
        const std::string& counter, std::uint64_t minimum,
        const std::function<void(Session&, ID3D12GraphicsCommandList*)>& exercise) {
    const auto folder = root / name;
    Session session;
    require(session.start(device, folder), "Session::start failed in rejection case " + name);
    auto recording = make_empty_command_list(device);
    exercise(session, recording.command_list.Get());
    require_hr(recording.command_list->Close(), "Close rejection-only command list");
    const auto manifest = finish_rejection_session(session, folder);
    require(json_uint(manifest, counter) >= minimum,
        "Rejection case " + name + " did not increment " + counter);
    std::cout << "PASS rejection " << name << '\n';
}

void run_rejection_tests(ID3D12Device* device, const TargetSpec& r32_spec,
        const TargetSpec& stencil_spec, const std::filesystem::path& output_root) {
    auto r32 = make_depth_target(device, r32_spec);
    auto stencil = make_depth_target(device, stencil_spec);

    run_simple_rejection(device, output_root, "reject_unknown_recording",
        "unknown_recording", 1,
        [resource = r32.resource.Get()](Session& session, ID3D12GraphicsCommandList* command_list) {
            const auto barrier = transition(resource, 0, D3D12_RESOURCE_STATE_DEPTH_WRITE,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            // Deliberately omit Session::reset for this list.
            session.barriers(command_list, 1, &barrier);
        });

    run_simple_rejection(device, output_root, "reject_inside_render_pass",
        "render_pass", 1,
        [resource = r32.resource.Get()](Session& session, ID3D12GraphicsCommandList* command_list) {
            session.reset(command_list);
            session.begin_pass(command_list, static_cast<D3D12_RENDER_PASS_FLAGS>(0));
            const auto barrier = transition(resource, 0, D3D12_RESOURCE_STATE_DEPTH_WRITE,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            session.barriers(command_list, 1, &barrier);
            session.end_pass(command_list);
        });

    run_simple_rejection(device, output_root, "reject_split_barrier",
        "split", 1,
        [resource = r32.resource.Get()](Session& session, ID3D12GraphicsCommandList* command_list) {
            session.reset(command_list);
            const auto barrier = transition(resource, 0, D3D12_RESOURCE_STATE_DEPTH_WRITE,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                D3D12_RESOURCE_BARRIER_FLAG_BEGIN_ONLY);
            session.barriers(command_list, 1, &barrier);
        });

    run_simple_rejection(device, output_root, "reject_stencil_plane",
        "non_depth_plane", 1,
        [resource = stencil.resource.Get()](Session& session, ID3D12GraphicsCommandList* command_list) {
            session.reset(command_list);
            const auto barrier = transition(resource, 1, D3D12_RESOURCE_STATE_DEPTH_WRITE,
                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            session.barriers(command_list, 1, &barrier);
        });

    run_simple_rejection(device, output_root, "reject_ambiguous_batch",
        "ambiguous_batch", 2,
        [resource = r32.resource.Get()](Session& session, ID3D12GraphicsCommandList* command_list) {
            session.reset(command_list);
            const std::array<D3D12_RESOURCE_BARRIER, 2> barriers{
                transition(resource, 0, D3D12_RESOURCE_STATE_DEPTH_WRITE,
                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),
                transition(resource, 0, D3D12_RESOURCE_STATE_DEPTH_WRITE,
                    D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE)};
            session.barriers(command_list, static_cast<UINT>(barriers.size()), barriers.data());
        });

    {
        const auto folder = output_root / "reject_unsubmitted_reset";
        auto target = make_depth_target(device, r32_spec);
        auto recording = make_recording(device);
        Session session;
        require(session.start(device, folder), "Session::start failed in unsubmitted-reset case");
        session.reset(recording.command_list.Get());
        const auto qualifying = transition(target.resource.Get(), 0,
            D3D12_RESOURCE_STATE_DEPTH_WRITE, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        session.barriers(recording.command_list.Get(), 1, &qualifying); // Discover, no readback yet.
        std::this_thread::sleep_for(std::chrono::milliseconds(1100));
        session.service(1); // Prewarm after the required observation window.
        session.barriers(recording.command_list.Get(), 1, &qualifying); // Record an unsubmitted copy.
        recording.command_list->ResourceBarrier(1, &qualifying);
        require_hr(recording.command_list->Close(), "Close command list before pre-submit reset");
        reset_recording(recording); // The GPU never receives the old list.
        session.reset(recording.command_list.Get()); // Must discard its recorded copy.
        require_hr(recording.command_list->Close(), "Close reset empty command list");
        const auto manifest = finish_rejection_session(session, folder);
        require(json_uint(manifest, "recorded") == 1, "Expected the discarded case to record one copy");
        require(json_uint(manifest, "submitted") == 0, "Unsubmitted reset must not mark work submitted");
        require(json_uint(manifest, "completed") == 0, "Unsubmitted reset must not mark work complete");
        require(json_uint(manifest, "discarded_recording") == 1,
            "Reset-before-submit did not report the discarded recording");
        require(!std::filesystem::exists(folder / "candidate_0.f32"),
            "Discarded unsubmitted work must not be exported as a depth image");
        std::cout << "PASS rejection unsubmitted list reset\n";
    }
}

void check_debug_messages(ID3D12InfoQueue* info_queue) {
    if (!info_queue) {
        std::cout << "INFO D3D12 debug layer unavailable; WARP functional checks still ran\n";
        return;
    }
    const UINT64 count = info_queue->GetNumStoredMessagesAllowedByRetrievalFilter();
    for (UINT64 i = 0; i < count; ++i) {
        SIZE_T size = 0;
        if (FAILED(info_queue->GetMessage(i, nullptr, &size)) || size == 0) {
            continue;
        }
        std::vector<unsigned char> storage(size);
        auto* message = reinterpret_cast<D3D12_MESSAGE*>(storage.data());
        if (FAILED(info_queue->GetMessage(i, message, &size)) || !message) {
            continue;
        }
        if (message->Severity == D3D12_MESSAGE_SEVERITY_ERROR ||
            message->Severity == D3D12_MESSAGE_SEVERITY_CORRUPTION) {
            throw TestFailure(std::string("D3D12 debug layer reported an error: ") +
                (message->pDescription ? message->pDescription : "<no description>"));
        }
    }
    std::cout << "PASS D3D12 debug queue: no corruption or error messages (" << count << " total)\n";
}

} // namespace

int main() {
    try {
        auto context = make_warp_device();
        D3D12_COMMAND_QUEUE_DESC queue_desc{};
        queue_desc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        ComPtr<ID3D12CommandQueue> queue;
        require_hr(context.device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue)),
            "CreateCommandQueue(DIRECT)");
        ComPtr<ID3D12Fence> external_fence;
        require_hr(context.device->CreateFence(0, D3D12_FENCE_FLAG_NONE,
            IID_PPV_ARGS(&external_fence)), "CreateFence(test queue completion)");
        WinEvent completion_event;
        UINT64 external_value = 0;

        const TargetSpec r32_spec{
            "r32_typeless_d32", DXGI_FORMAT_R32_TYPELESS, DXGI_FORMAT_D32_FLOAT, false};
        const TargetSpec stencil_spec{
            "r32g8x24_typeless_d32s8", DXGI_FORMAT_R32G8X24_TYPELESS,
            DXGI_FORMAT_D32_FLOAT_S8X24_UINT, true};
        const auto output_root = make_output_root();
        std::filesystem::remove_all(output_root);
        std::filesystem::create_directories(output_root);

        std::cout << "WARP device ready; D3D12 debug layer "
            << (context.debug_layer_enabled ? "enabled" : "unavailable") << '\n';
        run_gpu_capture(context.device.Get(), queue.Get(), external_fence.Get(),
            completion_event, external_value, r32_spec, output_root);
        run_gpu_capture(context.device.Get(), queue.Get(), external_fence.Get(),
            completion_event, external_value, stencil_spec, output_root);
        run_rejection_tests(context.device.Get(), r32_spec, stencil_spec, output_root);
        check_debug_messages(context.info_queue.Get());
        std::cout << "PASS all depth proof WARP tests; artifacts=" << output_root.string() << '\n';
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "FAIL depth proof WARP test: " << e.what() << '\n';
        return 1;
    }
}

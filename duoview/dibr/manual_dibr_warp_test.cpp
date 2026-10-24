#include <windows.h>
#include "DuoViewDibrD3D12.hpp"
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
using namespace uevr::duoview::dibr;
using namespace uevr::duoview::dibr::dx12;
using uevr::duoview::Rect;

static void check(HRESULT h) {
    if (FAILED(h)) throw std::runtime_error("D3D12 failure " + std::to_string(static_cast<uint32_t>(h)));
}
static D3D12_HEAP_PROPERTIES heap(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES h{}; h.Type = type; h.CreationNodeMask = h.VisibleNodeMask = 1; return h;
}
static D3D12_RESOURCE_DESC texture(UINT w, UINT h, DXGI_FORMAT format, D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE) {
    D3D12_RESOURCE_DESC d{}; d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width = w; d.Height = h; d.DepthOrArraySize = d.MipLevels = 1; d.Format = format;
    d.SampleDesc.Count = 1; d.Flags = flags; return d;
}
static D3D12_RESOURCE_DESC buffer(UINT64 size) {
    D3D12_RESOURCE_DESC d{}; d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    d.Width = size; d.Height = d.DepthOrArraySize = d.MipLevels = 1;
    d.SampleDesc.Count = 1; d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR; return d;
}
static ComPtr<ID3D12Resource> resource(ID3D12Device* device, D3D12_RESOURCE_DESC desc,
    D3D12_HEAP_TYPE type, D3D12_RESOURCE_STATES state) {
    auto hp = heap(type); ComPtr<ID3D12Resource> r;
    check(device->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &desc, state, nullptr, IID_PPV_ARGS(&r)));
    return r;
}
static std::array<float, 16> identity() {
    std::array<float, 16> m{}; m[0] = m[5] = m[10] = m[15] = 1.f; return m;
}
static std::array<float, 16> infinite_reverse_z_source_to_eye(
    double source_horizontal_fov, double target_horizontal_fov, double eye_x_meters,
    double principal_shift_ndc, double near_meters) {
    // Closed form of P_target * T_eye * inverse(P_source) for a left-handed,
    // infinite-far reverse-Z projection with equal source/target aspect ratios.
    // At raw depth 0 the source point is homogeneous w=0, so eye translation
    // drops out while each target frustum's FOV and optical center remain.
    const double source_fx = 1.0 / std::tan(source_horizontal_fov * .5);
    const double target_fx = 1.0 / std::tan(target_horizontal_fov * .5);
    const double scale = target_fx / source_fx;
    auto m = identity();
    m[0] = static_cast<float>(scale);
    m[2] = static_cast<float>(-target_fx * eye_x_meters / near_meters);
    m[3] = static_cast<float>(principal_shift_ndc);
    m[5] = static_cast<float>(scale);
    return m;
}
static void transition(ID3D12GraphicsCommandList* cmd, ID3D12Resource* resource,
    D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition = {resource, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before, after};
    cmd->ResourceBarrier(1, &barrier);
}
static double line_center(const uint8_t* data, UINT row_pitch, UINT eye, UINT width, UINT height) {
    double weighted = 0.0, total = 0.0;
    for (UINT y = 0; y < height; ++y) for (UINT x = 0; x < width; ++x) {
        const auto value = data[y * row_pitch + (eye * width + x) * 4 + 2];
        weighted += (static_cast<double>(x) + .5) * value;
        total += value;
    }
    if (!total) throw std::runtime_error("Synthetic plane disappeared from an eye surface");
    return weighted / total;
}
static double line_center_window(const uint8_t* data, UINT row_pitch, UINT eye, UINT width, UINT height,
    UINT x_begin, UINT x_end) {
    double weighted = 0.0, total = 0.0;
    for (UINT y = 0; y < height; ++y) for (UINT x = x_begin; x < x_end; ++x) {
        const auto value = data[y * row_pitch + (eye * width + x) * 4 + 2];
        weighted += (static_cast<double>(x) + .5) * value;
        total += value;
    }
    if (!total) throw std::runtime_error("Synthetic marker disappeared from its crop window");
    return weighted / total;
}
static void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
static double disparity(const std::vector<uint8_t>& image, UINT row_pitch, UINT width, UINT height) {
    return line_center(image.data(), row_pitch, 0, width, height) -
        line_center(image.data(), row_pitch, 1, width, height);
}
static double disparity_window(const std::vector<uint8_t>& image, UINT row_pitch, UINT width, UINT height,
    UINT x_begin, UINT x_end) {
    return line_center_window(image.data(), row_pitch, 0, width, height, x_begin, x_end) -
        line_center_window(image.data(), row_pitch, 1, width, height, x_begin, x_end);
}
static void require_identical_eyes(const std::vector<uint8_t>& image, UINT row_pitch,
    UINT width, UINT height, const char* message) {
    for (UINT y = 0; y < height; ++y) for (UINT x = 0; x < width; ++x)
        require(std::memcmp(image.data() + y * row_pitch + x * 4,
            image.data() + y * row_pitch + (x + width) * 4, 4) == 0, message);
}
static void require_pixel_near(const uint8_t* pixel, const std::array<uint8_t, 4>& expected,
    uint8_t tolerance, const char* message) {
    for (size_t channel = 0; channel < 4; ++channel) {
        const int difference = std::abs(static_cast<int>(pixel[channel]) - expected[channel]);
        require(difference <= tolerance, message);
    }
}

int main() try {
    constexpr UINT W = 64, H = 32;
    constexpr UINT DW = 40, DH = 24;
    constexpr UINT FW = 16, FH = 8;
    // Offset and size this rect so a full-texture UV lookup lands in the
    // padded region instead of accidentally sampling a valid texel.
    constexpr Rect DepthRect{4, 8, 12, 8};
    constexpr Rect FoveaDepthRect{2, 1, 12, 6};
    constexpr Rect ColorRect{4, 2, 56, 28};
    const CandidateKey selected_depth_key{77, 1, 1}; // original array slice 1
    const CandidateKey selected_fovea_key{88, 2, 0};
    ComPtr<ID3D12Debug> debug;
    const bool debug_enabled = SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)));
    if (debug_enabled) debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory; check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIAdapter> adapter; check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
    ComPtr<ID3D12Device> device; check(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)));
    ComPtr<ID3D12InfoQueue> info_queue; (void)device.As(&info_queue);
    D3D12_COMMAND_QUEUE_DESC queue_desc{}; queue_desc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue; check(device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue)));
    ComPtr<ID3D12CommandAllocator> allocator; check(device->CreateCommandAllocator(queue_desc.Type, IID_PPV_ARGS(&allocator)));
    ComPtr<ID3D12GraphicsCommandList> command_list;
    check(device->CreateCommandList(0, queue_desc.Type, allocator.Get(), nullptr, IID_PPV_ARGS(&command_list)));
    check(command_list->Close()); // allocator may now be reset by the first render.

    auto color = resource(device.Get(), texture(W, H, DXGI_FORMAT_B8G8R8A8_UNORM),
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto depth_resource = resource(device.Get(), texture(DW, DH, DXGI_FORMAT_R32_FLOAT),
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto depth_array_desc = texture(DW, DH, DXGI_FORMAT_R32_FLOAT);
    depth_array_desc.DepthOrArraySize = 2;
    auto depth_source_array = resource(device.Get(), depth_array_desc,
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto fovea_resource = resource(device.Get(), texture(FW, FH, DXGI_FORMAT_R32_FLOAT),
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto output = resource(device.Get(), texture(W * 2, H, DXGI_FORMAT_B8G8R8A8_UNORM,
        D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET), D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_SOURCE);

    D3D12_PLACED_SUBRESOURCE_FOOTPRINT color_foot{}, fovea_foot{}, output_foot{};
    std::array<D3D12_PLACED_SUBRESOURCE_FOOTPRINT, 2> depth_feet{};
    std::array<UINT, 2> depth_rows{};
    std::array<UINT64, 2> depth_row_sizes{};
    UINT64 color_bytes{}, depth_array_bytes{}, fovea_bytes{}, output_bytes{};
    const auto color_desc = color->GetDesc(), output_desc = output->GetDesc();
    const auto fovea_desc = fovea_resource->GetDesc();
    device->GetCopyableFootprints(&color_desc, 0, 1, 0, &color_foot, nullptr, nullptr, &color_bytes);
    device->GetCopyableFootprints(&depth_array_desc, 0, 2, 0, depth_feet.data(),
        depth_rows.data(), depth_row_sizes.data(), &depth_array_bytes);
    device->GetCopyableFootprints(&fovea_desc, 0, 1, 0, &fovea_foot, nullptr, nullptr, &fovea_bytes);
    device->GetCopyableFootprints(&output_desc, 0, 1, 0, &output_foot, nullptr, nullptr, &output_bytes);
    auto color_upload = resource(device.Get(), buffer(color_bytes), D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto depth_upload = resource(device.Get(), buffer(depth_array_bytes), D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto fovea_upload = resource(device.Get(), buffer(fovea_bytes), D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto readback = resource(device.Get(), buffer(output_bytes), D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);

    void* mapped{}; D3D12_RANGE no_read{0, 0};
    check(color_upload->Map(0, &no_read, &mapped));
    std::memset(mapped, 0, color_bytes);
    for (UINT y = 0; y < H; ++y) for (UINT x = 0; x < W; ++x) {
        auto* px = static_cast<uint8_t*>(mapped) + y * color_foot.Footprint.RowPitch + x * 4;
        if (x >= 30 && x <= 32) { px[0] = 64; px[1] = 96; px[2] = 128; }
        px[3] = 255;
    }
    color_upload->Unmap(0, nullptr);

    check(fovea_upload->Map(0, &no_read, &mapped));
    for (UINT y = 0; y < FH; ++y) for (UINT x = 0; x < FW; ++x) {
        const float value = x >= FoveaDepthRect.x && x < FoveaDepthRect.x + FoveaDepthRect.width &&
            y >= FoveaDepthRect.y && y < FoveaDepthRect.y + FoveaDepthRect.height ? .75f : .25f;
        std::memcpy(static_cast<uint8_t*>(mapped) + y * fovea_foot.Footprint.RowPitch +
            x * sizeof(float), &value, sizeof(float));
    }
    fovea_upload->Unmap(0, nullptr);

    D3D12_TEXTURE_COPY_LOCATION color_source{color_upload.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    color_source.PlacedFootprint = color_foot;
    std::array<D3D12_TEXTURE_COPY_LOCATION, 2> depth_upload_locations{};
    std::array<D3D12_TEXTURE_COPY_LOCATION, 2> depth_array_locations{};
    for (UINT slice = 0; slice < 2; ++slice) {
        depth_upload_locations[slice].pResource = depth_upload.Get();
        depth_upload_locations[slice].Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        depth_upload_locations[slice].PlacedFootprint = depth_feet[slice];
        depth_array_locations[slice].pResource = depth_source_array.Get();
        depth_array_locations[slice].Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        depth_array_locations[slice].SubresourceIndex = slice;
    }
    D3D12_TEXTURE_COPY_LOCATION fovea_upload_location{fovea_upload.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    fovea_upload_location.PlacedFootprint = fovea_foot;
    D3D12_TEXTURE_COPY_LOCATION fovea_target{fovea_resource.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    fovea_target.SubresourceIndex = 0;
    D3D12_TEXTURE_COPY_LOCATION color_target{color.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    D3D12_TEXTURE_COPY_LOCATION depth_target{depth_resource.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    depth_target.SubresourceIndex = 0;
    D3D12_TEXTURE_COPY_LOCATION output_source{output.Get(), D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    D3D12_TEXTURE_COPY_LOCATION output_readback{readback.Get(), D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    output_readback.PlacedFootprint = output_foot;

    OwnedDepthTexture depth{};
    depth.texture = depth_resource;
    depth.candidate = {selected_depth_key, DW, DH, DepthRect,
        static_cast<uint32_t>(DXGI_FORMAT_R32_FLOAT), CaptureStage::depth_write_to_shader_read,
        true, true, 0, 1};
    OwnedDepthTexture fovea{};
    fovea.texture = fovea_resource;
    fovea.candidate = {selected_fovea_key, FW, FH, FoveaDepthRect,
        static_cast<uint32_t>(DXGI_FORMAT_R32_FLOAT), CaptureStage::depth_write_to_shader_read,
        true, true, 0, 1};
    RoleAssignments roles{}; roles.assign_periphery(depth.candidate.key);
    ProjectionPair projections{};
    projections.color_rect = ColorRect;
    // Exercise the production raw-device-Z defaults: finite [0,1] is valid,
    // and only the exact known reversed-Z clear value is invalid.
    auto& left = projections.left; auto& right = projections.right;
    left = right = identity();
    left[2] = .4f; left[3] = -.2f;
    right[2] = -.4f; right[3] = .2f;
    const auto stereo_left = left;
    const auto stereo_right = right;

    uevr::duoview::dibr::dx12::Compositor compositor;
    require(compositor.prewarm(device.Get(), W, H, DXGI_FORMAT_B8G8R8A8_UNORM),
        "DIBR production PSO must prewarm before recording");
    ComPtr<ID3D12Fence> fence; check(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)));
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!event) throw std::runtime_error("Could not create WARP fence event");
    uint64_t signal = 0;
    auto render = [&](float raw_depth, uint64_t frame, const std::array<float,16>& l,
                      const std::array<float,16>& r, OwnedDepthTexture* fovea_sample = nullptr) {
        projections.left = l; projections.right = r;
        check(depth_upload->Map(0, &no_read, &mapped));
        for (UINT slice = 0; slice < 2; ++slice) {
            const auto& footprint = depth_feet[slice];
            for (UINT y = 0; y < DH; ++y) for (UINT x = 0; x < DW; ++x) {
                float value = .75f; // padded texels and the unselected source slice
                if (slice == 1 && x >= DepthRect.x && x < DepthRect.x + DepthRect.width &&
                    y >= DepthRect.y && y < DepthRect.y + DepthRect.height) {
                    value = raw_depth;
                }
                std::memcpy(static_cast<uint8_t*>(mapped) + footprint.Offset +
                    y * footprint.Footprint.RowPitch + x * sizeof(float), &value, sizeof(float));
            }
        }
        depth_upload->Unmap(0, nullptr);
        check(allocator->Reset()); check(command_list->Reset(allocator.Get(), nullptr));
        command_list->CopyTextureRegion(&color_target, 0, 0, 0, &color_source, nullptr);
        for (UINT slice = 0; slice < 2; ++slice)
            command_list->CopyTextureRegion(&depth_array_locations[slice], 0, 0, 0,
                &depth_upload_locations[slice], nullptr);
        transition(command_list.Get(), depth_source_array.Get(), D3D12_RESOURCE_STATE_COPY_DEST,
            D3D12_RESOURCE_STATE_COPY_SOURCE);
        // The selected original subresource is array slice 1. The compositor
        // sees only this independently owned, single-slice 2D snapshot.
        command_list->CopyTextureRegion(&depth_target, 0, 0, 0, &depth_array_locations[1], nullptr);
        transition(command_list.Get(), depth_source_array.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE,
            D3D12_RESOURCE_STATE_COPY_DEST);
        if (fovea_sample && fovea_sample != &depth) {
            command_list->CopyTextureRegion(&fovea_target, 0, 0, 0, &fovea_upload_location, nullptr);
            fovea_sample->candidate.update_serial = frame;
            fovea_sample->latest_update_serial = frame;
            fovea_sample->sample = {fovea_sample->candidate.key, {1, frame},
                CaptureStage::depth_write_to_shader_read, frame, frame,
                {fovea_sample->candidate.key, fovea_sample->candidate.key.subresource, 0, frame},
                FoveaDepthRect, true, true,
                {QueueRelation::same_queue, 9, 9, frame * 2, 0, 0, 0}};
        }
        depth.candidate.update_serial = frame;
        depth.latest_update_serial = frame;
        depth.sample = {selected_depth_key, {1, frame}, CaptureStage::depth_write_to_shader_read,
            frame, frame, {selected_depth_key, selected_depth_key.subresource, 0, frame},
            DepthRect, true, true,
            {QueueRelation::same_queue, 9, 9, frame * 2, 0, 0, 0}};
        const auto recorded = compositor.record(device.Get(), command_list.Get(), color.Get(),
            D3D12_RESOURCE_STATE_COPY_DEST, depth, D3D12_RESOURCE_STATE_COPY_DEST,
            fovea_sample, D3D12_RESOURCE_STATE_COPY_DEST, roles,
            {1, frame}, {9, frame * 2 + 1, 0}, output.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE,
            projections, {}, frame);
        if (!recorded) throw std::runtime_error("DIBR WARP production adapter rejected packet: " + compositor.error());
        command_list->CopyTextureRegion(&output_readback, 0, 0, 0, &output_source, nullptr);
        check(command_list->Close());
        ID3D12CommandList* lists[]{command_list.Get()}; queue->ExecuteCommandLists(1, lists);
        compositor.on_queue_execute_command_lists(queue.Get(), 1, lists, frame);
        check(queue->Signal(fence.Get(), ++signal));
        check(fence->SetEventOnCompletion(signal, event));
        if (WaitForSingleObject(event, 30000) != WAIT_OBJECT_0) throw std::runtime_error("DIBR WARP GPU timeout");
        compositor.retire_after_fence(fence.Get(), signal);
        D3D12_RANGE read{0, static_cast<size_t>(output_bytes)};
        check(readback->Map(0, &read, &mapped));
        std::vector<uint8_t> pixels(static_cast<size_t>(output_foot.Footprint.RowPitch) * H);
        std::memcpy(pixels.data(), mapped, pixels.size());
        readback->Unmap(0, nullptr);
        return pixels;
    };

    const auto same_geometry = identity();
    const auto zero_baseline = render(.75f, 1, same_geometry, same_geometry);
    require_identical_eyes(zero_baseline, output_foot.Footprint.RowPitch, W, H,
        "Zero camera baseline must produce identical eye surfaces");
    const std::array<uint8_t, 4> midtone_bgra{64, 96, 128, 255};
    require(std::memcmp(zero_baseline.data() + 16 * output_foot.Footprint.RowPitch + 31 * 4,
        midtone_bgra.data(), midtone_bgra.size()) == 0,
        "UNORM zero-baseline composition must preserve a known midtone color");

    const auto convergence = render(.5f, 2, stereo_left, stereo_right);
    require(std::memcmp(convergence.data() + 16 * output_foot.Footprint.RowPitch + 31 * 4,
        convergence.data() + 16 * output_foot.Footprint.RowPitch + (W + 31) * 4, 4) == 0,
        "Convergence-plane correspondence must remain centered");

    const auto near_image = render(.75f, 3, stereo_left, stereo_right);
    const double near_disparity = disparity(near_image, output_foot.Footprint.RowPitch, W, H);
    require(near_disparity > 4.5 && near_disparity < 8.5,
        "Near-plane eye disparity must have expected sign and bounded magnitude");

    const auto far_image = render(.25f, 4, stereo_left, stereo_right);
    const double far_disparity = disparity(far_image, output_foot.Footprint.RowPitch, W, H);
    require(far_disparity < -4.5 && far_disparity > -8.5,
        "Far-plane disparity must reverse sign around the convergence plane");

    projections.iterations = 1;
    const auto padded_rect_far = render(.25f, 5, stereo_left, stereo_right);
    const double padded_rect_disparity = disparity(padded_rect_far,
        output_foot.Footprint.RowPitch, W, H);
    std::cout << "Padded active-rect L-R=" << padded_rect_disparity << " px\n";
    require(padded_rect_disparity < -4.5 && padded_rect_disparity > -8.5,
        "Mixed-resolution depth must honor the offset active rect and selected source slice");
    projections.iterations = 3;

    const auto reversed_z_far = render(.00001f, 6, stereo_left, stereo_right);
    const double reversed_z_far_disparity = disparity(reversed_z_far,
        output_foot.Footprint.RowPitch, W, H);
    require(reversed_z_far_disparity < -10.0 && reversed_z_far_disparity > -15.0,
        "Finite reversed-Z depth near zero must remain valid, not be cut off as sky");

    const auto reversed_z_near = render(.99999f, 7, stereo_left, stereo_right);
    const double reversed_z_near_disparity = disparity(reversed_z_near,
        output_foot.Footprint.RowPitch, W, H);
    require(reversed_z_near_disparity > 10.0 && reversed_z_near_disparity < 15.0,
        "Finite reversed-Z depth near one must remain valid");

    const auto clear_same_domain = render(0.f, 8, same_geometry, same_geometry);
    require_identical_eyes(clear_same_domain, output_foot.Footprint.RowPitch, W, H,
        "Clear-depth sky in identical source/target domains must preserve both eyes");
    constexpr double pi = 3.14159265358979323846;
    const auto sky_left = infinite_reverse_z_source_to_eye(100.0 * pi / 180.0,
        95.0 * pi / 180.0, -.032, -.04, .1);
    const auto sky_right = infinite_reverse_z_source_to_eye(100.0 * pi / 180.0,
        105.0 * pi / 180.0, .032, .04, .1);
    const auto asymmetric_sky = render(0.f, 9, sky_left, sky_right);
    const double asymmetric_sky_disparity = disparity(asymmetric_sky,
        output_foot.Footprint.RowPitch, W, H);
    require(asymmetric_sky_disparity < -1.5 && asymmetric_sky_disparity > -4.0,
        "Clear reversed-Z sky must retain the source-to-eye FOV mapping at infinity");
    uint64_t invalid_frame = 10;
    for (const float invalid_depth : {-0.01f, 1.01f,
            std::numeric_limits<float>::quiet_NaN(), std::numeric_limits<float>::infinity()}) {
        const auto invalid_image = render(invalid_depth, invalid_frame++, stereo_left, stereo_right);
        require_identical_eyes(invalid_image, output_foot.Footprint.RowPitch, W, H,
            "Non-finite or out-of-range raw depth must fall back without parallax");
    }

    // Give the image one marker inside the crop and one on each side. Fovea
    // depth is near (.75) only in the center crop; periphery depth stays far
    // (.25) across the rest of the view.
    check(color_upload->Map(0, &no_read, &mapped));
    std::memset(mapped, 0, color_bytes);
    for (UINT y = 0; y < H; ++y) for (UINT x = 0; x < W; ++x) {
        auto* px = static_cast<uint8_t*>(mapped) + y * color_foot.Footprint.RowPitch + x * 4;
        if ((x >= 8 && x <= 10) || (x >= 53 && x <= 55)) {
            px[0] = 32; px[1] = 48; px[2] = 64;
        }
        if (x >= 30 && x <= 32 && y >= 10 && y <= 22) {
            px[0] = 64; px[1] = 96; px[2] = 128;
        }
        px[3] = 255;
    }
    color_upload->Unmap(0, nullptr);
    projections.use_fovea_depth = true;
    projections.fovea_uv_rect = {.25f, .25f, .75f, .75f};
    roles.assign_fovea(selected_fovea_key);
    const auto fused = render(.25f, invalid_frame, stereo_left, stereo_right, &fovea);
    const double fovea_disparity = disparity_window(fused, output_foot.Footprint.RowPitch,
        W, H, 20, 45);
    const double periphery_left_disparity = disparity_window(fused, output_foot.Footprint.RowPitch,
        W, H, 0, 20);
    const double periphery_right_disparity = disparity_window(fused, output_foot.Footprint.RowPitch,
        W, H, 45, W);
    std::cout << "Fovea/periphery L-R=" << fovea_disparity << "/"
        << periphery_left_disparity << "/" << periphery_right_disparity << " px\n";
    require(fovea_disparity > 4.5 && fovea_disparity < 8.5,
        "The selected fovea depth must control markers inside its full-view crop");
    require(periphery_left_disparity < -4.5 && periphery_left_disparity > -8.5 &&
        periphery_right_disparity < -4.5 && periphery_right_disparity > -8.5,
        "Markers outside the selected fovea crop must continue to use periphery depth");

    // A single CandidateKey may be assigned to both roles. Production safely
    // drops the optional fovea for this draw and uses the periphery snapshot,
    // which keeps state transitions unique for the aliased GPU resource.
    projections.use_fovea_depth = false;
    roles.clear_fovea();
    const auto alias_baseline = render(.5f, invalid_frame++, stereo_left, stereo_right);
    roles.assign_fovea(selected_depth_key);
    projections.use_fovea_depth = true;
    if (info_queue) info_queue->ClearStoredMessages();
    const auto alias_roles = render(.5f, invalid_frame++, stereo_left, stereo_right, &depth);
    require(alias_roles == alias_baseline,
        "Assigning one depth candidate to both roles must safely use periphery-only depth");
    require(compositor.fallback_reason().find("same depth resource") != std::string::npos,
        "Aliased-role fallback must report why optional fovea depth was bypassed");
    if (info_queue) {
        const auto message_count = info_queue->GetNumStoredMessagesAllowedByRetrievalFilter();
        for (UINT64 i = 0; i < message_count; ++i) {
            SIZE_T length = 0;
            check(info_queue->GetMessage(i, nullptr, &length));
            std::vector<uint8_t> storage(length);
            auto* message = reinterpret_cast<D3D12_MESSAGE*>(storage.data());
            check(info_queue->GetMessage(i, message, &length));
            require(message->Severity != D3D12_MESSAGE_SEVERITY_ERROR &&
                message->Severity != D3D12_MESSAGE_SEVERITY_CORRUPTION,
                "Aliased DIBR roles must not emit invalid duplicate state transitions");
        }
    }
    projections.use_fovea_depth = false;
    roles.clear_fovea();

    // Stable Mono writes its typeless center texture through an sRGB RTV when
    // the source/output path is sRGB. Sampling that texture as UNORM then
    // rendering to an sRGB target changes midtones (for example 128 -> 188).
    // Verify that explicit inherited sRGB metadata preserves encoded pixels.
    D3D12_RESOURCE_DESC srgb_color_desc = texture(W, H, DXGI_FORMAT_B8G8R8A8_TYPELESS,
        D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
    auto srgb_center = resource(device.Get(), srgb_color_desc,
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto srgb_output = resource(device.Get(), texture(W * 2, H, DXGI_FORMAT_B8G8R8A8_UNORM_SRGB,
        D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET), D3D12_HEAP_TYPE_DEFAULT,
        D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT srgb_color_foot{}, srgb_output_foot{};
    UINT64 srgb_color_bytes{}, srgb_output_bytes{};
    device->GetCopyableFootprints(&srgb_color_desc, 0, 1, 0, &srgb_color_foot,
        nullptr, nullptr, &srgb_color_bytes);
    const auto srgb_output_desc = srgb_output->GetDesc();
    device->GetCopyableFootprints(&srgb_output_desc, 0, 1, 0, &srgb_output_foot,
        nullptr, nullptr, &srgb_output_bytes);
    auto srgb_color_upload = resource(device.Get(), buffer(srgb_color_bytes),
        D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto srgb_readback = resource(device.Get(), buffer(srgb_output_bytes),
        D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    check(srgb_color_upload->Map(0, &no_read, &mapped));
    for (UINT y = 0; y < H; ++y) for (UINT x = 0; x < W; ++x) {
        auto* px = static_cast<uint8_t*>(mapped) + y * srgb_color_foot.Footprint.RowPitch + x * 4;
        px[0] = 64; px[1] = 96; px[2] = 128; px[3] = 255;
    }
    srgb_color_upload->Unmap(0, nullptr);
    D3D12_TEXTURE_COPY_LOCATION srgb_color_source{srgb_color_upload.Get(),
        D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    srgb_color_source.PlacedFootprint = srgb_color_foot;
    D3D12_TEXTURE_COPY_LOCATION srgb_color_target{srgb_center.Get(),
        D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    D3D12_TEXTURE_COPY_LOCATION srgb_output_source{srgb_output.Get(),
        D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    D3D12_TEXTURE_COPY_LOCATION srgb_output_readback{srgb_readback.Get(),
        D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    srgb_output_readback.PlacedFootprint = srgb_output_foot;
    uevr::duoview::dibr::dx12::Compositor srgb_compositor;
    require(srgb_compositor.prewarm(device.Get(), W, H, DXGI_FORMAT_B8G8R8A8_UNORM_SRGB),
        "DIBR sRGB output PSO must prewarm before recording");
    projections.center_color_srgb = true;
    projections.left = projections.right = same_geometry;
    check(allocator->Reset()); check(command_list->Reset(allocator.Get(), nullptr));
    command_list->CopyTextureRegion(&srgb_color_target, 0, 0, 0, &srgb_color_source, nullptr);
    depth.candidate.update_serial = invalid_frame;
    depth.latest_update_serial = invalid_frame;
    depth.sample = {depth.candidate.key, {1, invalid_frame}, CaptureStage::depth_write_to_shader_read,
        invalid_frame, invalid_frame,
        {depth.candidate.key, depth.candidate.key.subresource, 0, invalid_frame},
        DepthRect, true, true,
        {QueueRelation::same_queue, 9, 9, invalid_frame * 2, 0, 0, 0}};
    const auto srgb_recorded = srgb_compositor.record(device.Get(), command_list.Get(), srgb_center.Get(),
        D3D12_RESOURCE_STATE_COPY_DEST, depth, D3D12_RESOURCE_STATE_COPY_DEST,
        nullptr, D3D12_RESOURCE_STATE_COPY_DEST, roles, {1, invalid_frame}, {9, invalid_frame * 2 + 3, 0},
        srgb_output.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, projections, {}, invalid_frame);
    if (!srgb_recorded) throw std::runtime_error("DIBR sRGB roundtrip rejected packet: " + srgb_compositor.error());
    command_list->CopyTextureRegion(&srgb_output_readback, 0, 0, 0, &srgb_output_source, nullptr);
    check(command_list->Close());
    ID3D12CommandList* srgb_lists[]{command_list.Get()}; queue->ExecuteCommandLists(1, srgb_lists);
    srgb_compositor.on_queue_execute_command_lists(queue.Get(), 1, srgb_lists, invalid_frame);
    check(queue->Signal(fence.Get(), ++signal));
    check(fence->SetEventOnCompletion(signal, event));
    if (WaitForSingleObject(event, 30000) != WAIT_OBJECT_0)
        throw std::runtime_error("DIBR sRGB WARP GPU timeout");
    srgb_compositor.retire_after_fence(fence.Get(), signal);
    D3D12_RANGE srgb_read{0, static_cast<size_t>(srgb_output_bytes)};
    check(srgb_readback->Map(0, &srgb_read, &mapped));
    std::vector<uint8_t> srgb_pixels(static_cast<size_t>(srgb_output_foot.Footprint.RowPitch) * H);
    std::memcpy(srgb_pixels.data(), mapped, srgb_pixels.size());
    srgb_readback->Unmap(0, nullptr);
    require_identical_eyes(srgb_pixels, srgb_output_foot.Footprint.RowPitch, W, H,
        "sRGB zero-baseline output must preserve identical eyes");
    require_pixel_near(srgb_pixels.data() + 16 * srgb_output_foot.Footprint.RowPitch + 31 * 4,
        midtone_bgra, 1,
        "Typeless Mono center sampled as sRGB must preserve the known encoded midtone");
    projections.center_color_srgb = false;

    // Exercise the real stable Mono Native/Glamarye composition in UNORM
    // mode, where the shader performs explicit sRGB decode/encode. Its bytes
    // are copied into the typed-91 XR image, cropped back to a typeless
    // per-eye center image, then consumed by the production DIBR PSO and
    // rendered into the typed-91 target again.
    const auto baseline_layout = uevr::duoview::make_layout(W, H, .5f, .5f,
        .25f, 1.f, .5f, .5f);
    require(baseline_layout.has_value(), "The real Mono DIBR color-pipeline layout must be valid");
    const uint64_t baseline_frame = invalid_frame + 100;
    uevr::duoview::ViewFrame baseline_view{};
    baseline_view.config = {{1, baseline_frame}, *baseline_layout, {.5f, .5f}, {}, 1};
    baseline_view.config.settings.feather_fraction = .12f;
    baseline_view.config.settings.sharpen_strength = .4f;
    baseline_view.config.settings.direct_xr_output = true;

    const auto native_source_desc = texture(W, H, DXGI_FORMAT_B8G8R8A8_UNORM,
        D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
    auto native_fovea = resource(device.Get(), native_source_desc,
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto native_periphery = resource(device.Get(), native_source_desc,
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT native_source_upload_foot{};
    UINT64 native_source_upload_bytes{};
    device->GetCopyableFootprints(&native_source_desc, 0, 1, 0, &native_source_upload_foot,
        nullptr, nullptr, &native_source_upload_bytes);
    auto native_source_upload = resource(device.Get(), buffer(native_source_upload_bytes),
        D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    check(native_source_upload->Map(0, &no_read, &mapped));
    for (UINT y = 0; y < H; ++y) for (UINT x = 0; x < W; ++x) {
        auto* px = static_cast<uint8_t*>(mapped) + y * native_source_upload_foot.Footprint.RowPitch + x * 4;
        std::memcpy(px, midtone_bgra.data(), midtone_bgra.size());
    }
    native_source_upload->Unmap(0, nullptr);
    D3D12_TEXTURE_COPY_LOCATION native_fovea_upload{native_source_upload.Get(),
        D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    native_fovea_upload.PlacedFootprint = native_source_upload_foot;
    D3D12_TEXTURE_COPY_LOCATION native_fovea_target{native_fovea.Get(),
        D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    D3D12_TEXTURE_COPY_LOCATION native_periphery_target{native_periphery.Get(),
        D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};

    D3D12_RESOURCE_DESC center_from_native_desc = texture(W, H,
        DXGI_FORMAT_B8G8R8A8_TYPELESS);
    auto center_from_native = resource(device.Get(), center_from_native_desc,
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT center_from_native_foot{};
    UINT64 center_from_native_bytes{};
    device->GetCopyableFootprints(&center_from_native_desc, 0, 1, 0,
        &center_from_native_foot, nullptr, nullptr, &center_from_native_bytes);
    auto center_from_native_readback = resource(device.Get(), buffer(center_from_native_bytes),
        D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_TEXTURE_COPY_LOCATION center_from_native_target{center_from_native.Get(),
        D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    D3D12_TEXTURE_COPY_LOCATION center_from_native_source{srgb_output.Get(),
        D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    const D3D12_BOX left_eye_box{0, 0, 0, W, H, 1};
    D3D12_TEXTURE_COPY_LOCATION center_from_native_readback_target{center_from_native_readback.Get(),
        D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    center_from_native_readback_target.PlacedFootprint = center_from_native_foot;

    uevr::duoview::dx12::Compositor native_baseline_compositor;
    require(native_baseline_compositor.prewarm(device.Get(), W, H, false),
        "The real Native Mono baseline compositor must prewarm in UNORM mode");
    check(allocator->Reset()); check(command_list->Reset(allocator.Get(), nullptr));
    command_list->CopyTextureRegion(&native_fovea_target, 0, 0, 0, &native_fovea_upload, nullptr);
    command_list->CopyTextureRegion(&native_periphery_target, 0, 0, 0, &native_fovea_upload, nullptr);
    transition(command_list.Get(), srgb_output.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE,
        D3D12_RESOURCE_STATE_RENDER_TARGET);
    const auto native_baseline_recorded = native_baseline_compositor.record_native(device.Get(),
        command_list.Get(), native_fovea.Get(), native_periphery.Get(), srgb_output.Get(),
        D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COPY_DEST, baseline_view, {}, 0);
    if (!native_baseline_recorded)
        throw std::runtime_error("Real Native/Glamarye baseline rejected packet: " +
            native_baseline_compositor.error());
    require(!native_baseline_compositor.last_native_direct_xr(),
        "Glamarye must keep the baseline on the single center-image plus copy path");
    transition(command_list.Get(), srgb_output.Get(), D3D12_RESOURCE_STATE_RENDER_TARGET,
        D3D12_RESOURCE_STATE_COPY_SOURCE);
    command_list->CopyTextureRegion(&center_from_native_target, 0, 0, 0,
        &center_from_native_source, &left_eye_box);
    transition(command_list.Get(), center_from_native.Get(), D3D12_RESOURCE_STATE_COPY_DEST,
        D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION center_from_native_source_subresource{center_from_native.Get(),
        D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    command_list->CopyTextureRegion(&center_from_native_readback_target, 0, 0, 0,
        &center_from_native_source_subresource, nullptr);
    transition(command_list.Get(), center_from_native.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE,
        D3D12_RESOURCE_STATE_COPY_DEST);
    transition(command_list.Get(), srgb_output.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE,
        D3D12_RESOURCE_STATE_RENDER_TARGET);

    depth.candidate.update_serial = baseline_frame;
    depth.latest_update_serial = baseline_frame;
    depth.sample = {depth.candidate.key, {1, baseline_frame}, CaptureStage::depth_write_to_shader_read,
        baseline_frame, baseline_frame,
        {depth.candidate.key, depth.candidate.key.subresource, 0, baseline_frame},
        DepthRect, true, true,
        {QueueRelation::same_queue, 9, 9, signal, 0, 0, 0}};
    projections.color_rect = {0, 0, W, H};
    projections.left = projections.right = same_geometry;
    projections.use_fovea_depth = false;
    projections.center_color_srgb = true;
    const auto native_to_dibr_recorded = srgb_compositor.record(device.Get(), command_list.Get(),
        center_from_native.Get(), D3D12_RESOURCE_STATE_COPY_DEST, depth,
        D3D12_RESOURCE_STATE_COPY_DEST, nullptr, D3D12_RESOURCE_STATE_COPY_DEST, roles,
        {1, baseline_frame}, {9, signal + 1, 0}, srgb_output.Get(),
        D3D12_RESOURCE_STATE_RENDER_TARGET, projections, {}, baseline_frame);
    if (!native_to_dibr_recorded)
        throw std::runtime_error("Real Mono-to-DIBR typed-91 roundtrip rejected packet: " +
            srgb_compositor.error());
    transition(command_list.Get(), srgb_output.Get(), D3D12_RESOURCE_STATE_RENDER_TARGET,
        D3D12_RESOURCE_STATE_COPY_SOURCE);
    command_list->CopyTextureRegion(&srgb_output_readback, 0, 0, 0, &srgb_output_source, nullptr);
    check(command_list->Close());
    ID3D12CommandList* native_pipeline_lists[]{command_list.Get()};
    queue->ExecuteCommandLists(1, native_pipeline_lists);
    const auto native_pipeline_order = ++signal;
    srgb_compositor.on_queue_execute_command_lists(queue.Get(), 1,
        native_pipeline_lists, native_pipeline_order);
    require(srgb_compositor.last_record_submitted() &&
        srgb_compositor.last_record_submission_order() == native_pipeline_order,
        "The typed-91 DIBR draw must retain its resources through queue submission");
    check(queue->Signal(fence.Get(), signal));
    check(fence->SetEventOnCompletion(signal, event));
    if (WaitForSingleObject(event, 30000) != WAIT_OBJECT_0)
        throw std::runtime_error("Real Mono-to-DIBR sRGB WARP GPU timeout");
    srgb_compositor.retire_after_fence(fence.Get(), signal);
    D3D12_RANGE baseline_center_read{0, static_cast<SIZE_T>(center_from_native_bytes)};
    check(center_from_native_readback->Map(0, &baseline_center_read, &mapped));
    require_pixel_near(static_cast<const uint8_t*>(mapped) + center_from_native_foot.Offset,
        midtone_bgra, 1,
        "The UNORM Mono/Glamarye baseline must still store sRGB-encoded center bytes");
    const D3D12_RANGE no_write{0, 0};
    center_from_native_readback->Unmap(0, &no_write);
    check(srgb_readback->Map(0, &srgb_read, &mapped));
    std::vector<uint8_t> native_dibr_pixels(static_cast<size_t>(srgb_output_foot.Footprint.RowPitch) * H);
    std::memcpy(native_dibr_pixels.data(), mapped, native_dibr_pixels.size());
    srgb_readback->Unmap(0, &no_write);
    require_identical_eyes(native_dibr_pixels, srgb_output_foot.Footprint.RowPitch, W, H,
        "Native Mono encoded center bytes must survive DIBR composition into the typed-91 XR image");
    require_pixel_near(native_dibr_pixels.data() + 16 * srgb_output_foot.Footprint.RowPitch + 31 * 4,
        midtone_bgra, 1,
        "Native Mono sRGB bytes must roundtrip unchanged through typed-91 DIBR");
    if (info_queue) {
        const auto message_count = info_queue->GetNumStoredMessagesAllowedByRetrievalFilter();
        for (UINT64 i = 0; i < message_count; ++i) {
            SIZE_T length = 0;
            check(info_queue->GetMessage(i, nullptr, &length));
            std::vector<uint8_t> storage(length);
            auto* message = reinterpret_cast<D3D12_MESSAGE*>(storage.data());
            check(info_queue->GetMessage(i, message, &length));
            require(message->Severity != D3D12_MESSAGE_SEVERITY_ERROR &&
                message->Severity != D3D12_MESSAGE_SEVERITY_CORRUPTION,
                "Native Mono plus DIBR typed-91 path must pass D3D12 debug validation");
        }
    }
    projections.center_color_srgb = false;

    CloseHandle(event);
    std::cout << "Real Mono Native/Glamarye UNORM -> typed-91 DIBR encoded-byte roundtrip PASS\n";
    std::cout << "WARP production DIBR adapter: zero baseline, convergence, mixed-resolution padded rect, selected array slice, reversed-Z endpoints, sky projection, invalid-depth fallback, cropped fovea fusion and sRGB roundtrip PASS\n";
    std::cout << "Measured near L-R=" << near_disparity << " px; far L-R=" << far_disparity
        << " px; endpoint near/far=" << reversed_z_near_disparity << "/"
        << reversed_z_far_disparity << " px; sky=" << asymmetric_sky_disparity
        << " px; fovea/periphery=" << fovea_disparity << "/"
        << periphery_left_disparity << " px\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr << e.what() << '\n';
    return 1;
}

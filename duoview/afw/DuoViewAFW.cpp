// DuoView AFW Stage 1: PureDark's Alternate Frame Warping inside the DuoView v207 backend
// (Joey Hodge UEVR 5ac7edc + the DuoView v207 patch chain).
//
// CREDITS: Alternate Frame Warping, PDAFWPlugin.dll and its public API header PDAFWPlugin.h are by PureDark
// (https://github.com/PureDark/UEVR, branch "AFW"). Used non-commercially with his permission. The DLL is never
// modified or redistributed: users copy PDAFWPlugin.dll from PureDark's own release next to UEVRBackend.dll.
// PDAFWPlugin.h is downloaded at build time from PureDark's repository at commit
// fc8de1026622d42d0d1f76c3e9c8bb0d80b11035 and is not stored in the DuoView repository.
//
// This file ports PureDark's UEVR integration (src/mods/VR.cpp, src/mods/vr/D3D12Component.cpp and the NGX
// part of src/mods/vr/UpscaleHelper.hpp at fc8de10) into one module. Deliberate differences:
//  - the plugin is loaded (LoadLibrary/GetProcAddress) and hooked only when rendering method 7 is first selected
//    and PDAFWPlugin.dll is present, so modes 0-6 never run any AFW hook;
//  - hooks are installed disabled and enabled after they are stored (no half-installed hook can be entered),
//    and call the original without safetyhook's per-call mutex (they are never removed while running);
//  - OpenXR only (the reference also handles OpenVR); the UEVR ghosting fix (one view state per eye) is forced on
//    while ID 7 is selected, matching the reference default; "Ultra Responsive", the no-DLSS depth fallback,
//    FSR/XeSS inputs, RenderDoc and numpad debug keys are not ported (AFW needs DLSS/DLAA ON);
//  - captured engine textures are reference counted, cached plugin descriptors are refreshed when a resource
//    address is reused for a different texture, the warp waits until both eyes' depth was captured, and the
//    other eye is never submitted before AFW wrote it.

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <d3d11.h>
#include <d3d12.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <filesystem>
#include <map>
#include <mutex>
#include <set>
#include <shared_mutex>
#include <thread>

#include <imgui.h>
#include <safetyhook.hpp>
#include <spdlog/spdlog.h>

#include "Framework.hpp"
#include "../VR.hpp"
#include "DuoViewAFW.hpp"

// PureDark's public AFW API. Included last: it ends with `using namespace pd;`, which must not leak
// into any of Joey's translation units. Everything below still uses explicit pd:: names.
#include "../../../dependencies/pd-afwmod/include/PDAFWPlugin.h"

namespace {

// Minimal NVIDIA NGX SDK declarations, as in PureDark's UpscaleHelper.hpp. The virtual function order of
// Parameter must match NVSDK_NGX_Parameter exactly.
namespace ngx {
using Result = int;
constexpr int feature_super_sampling = 1;
constexpr int feature_ray_reconstruction = 13;
struct Handle { unsigned int id; };
struct Parameter {
    virtual void Set(const char* name, unsigned long long value) = 0;
    virtual void Set(const char* name, float value) = 0;
    virtual void Set(const char* name, double value) = 0;
    virtual void Set(const char* name, unsigned int value) = 0;
    virtual void Set(const char* name, int value) = 0;
    virtual void Set(const char* name, ID3D11Resource* value) = 0;
    virtual void Set(const char* name, ID3D12Resource* value) = 0;
    virtual void Set(const char* name, void* value) = 0;
    virtual Result Get(const char* name, unsigned long long* value) const = 0;
    virtual Result Get(const char* name, float* value) const = 0;
    virtual Result Get(const char* name, double* value) const = 0;
    virtual Result Get(const char* name, unsigned int* value) const = 0;
    virtual Result Get(const char* name, int* value) const = 0;
    virtual Result Get(const char* name, ID3D11Resource** value) const = 0;
    virtual Result Get(const char* name, ID3D12Resource** value) const = 0;
    virtual Result Get(const char* name, void** value) const = 0;
    virtual void Reset() = 0;
};
} // namespace ngx

constexpr auto shader_resource_state =
    D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE | D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;

struct AfwState {
    std::mutex init_mutex{};
    bool gave_up{false};
    std::atomic<const char*> status{"Not loaded"};

    decltype(&pd::InitDevice) init_device{};
    decltype(&pd::InitFrameWarp) init_frame_warp{};
    decltype(&pd::EvaluateFrameWarp) evaluate_frame_warp{};
    pd::D3D12RendererAPI* renderer{};

    std::mutex handle_mutex{};
    std::set<const ngx::Handle*> non_dlss_handles{};

    // Engine inputs captured from the DLSS evaluation (PureDark's VR members).
    std::mutex raw_mutex{};
    ID3D12Resource* raw_depth{};   // AddRef'd
    ID3D12Resource* raw_motion{};  // AddRef'd
    std::atomic<std::thread::id> rhi_thread{};
    UINT render_size[2]{0, 0};
    float mv_scale[2]{1.0f, 1.0f};
    float jitter[2]{1.0f, 1.0f};
    int last_dlss_frame{0};
    int dlss_continue{0};
    int paused_frame{0};

    pd::TextureDesc raw_mv_desc[2]{};
    pd::TextureDesc raw_velocity_desc[2]{};
    pd::TextureDesc depth_desc[2]{};
    pd::TextureDesc mv_desc[2]{};
    std::atomic<bool> captured[2]{false, false}; // this eye's depth/MV were copied at least once since creation
    pd::CameraData camera[2]{};
    pd::CameraDataMVCorrection camera_mv[2]{};
    int last_camera_update{0};

    // AFW eye frame buffers (owned by the plugin).
    pd::EyeFrameBuffers buffers{};
    uint32_t buffer_size[2]{0, 0};
    bool buffers_ready{false};
    bool written[2]{false, false};
    pd::TextureDesc scene_desc[8]{};
    D3D12_RESOURCE_DESC scene_resource_desc[8]{};
    pd::FrameBufferDesc current_frame_buffer{};
};

// A plugin descriptor for an engine texture, refreshed if the address is reused for a different texture.
struct CachedTexture {
    pd::TextureDesc desc{};
    D3D12_RESOURCE_DESC resource{};
};

bool same_texture(const D3D12_RESOURCE_DESC& a, const D3D12_RESOURCE_DESC& b) {
    return a.Width == b.Width && a.Height == b.Height && a.Format == b.Format &&
        a.DepthOrArraySize == b.DepthOrArraySize && a.MipLevels == b.MipLevels;
}

AfwState g_afw{};
SafetyHookInline g_create_hook{};
SafetyHookInline g_release_hook{};
SafetyHookInline g_evaluate_hook{};
SafetyHookInline g_barrier_hook{};

void set_status(const char* text) {
    if (g_afw.status.exchange(text) != text) {
        spdlog::info("[AFW] {}", text);
    }
}

pd::EyeIndex eye_for_frame(int frame) {
    return (frame % 2 == VR::get()->get_left_eye_interval()) ? pd::EyeLeft : pd::EyeRight;
}

pd::EyeIndex other_eye(pd::EyeIndex eye) {
    return eye == pd::EyeLeft ? pd::EyeRight : pd::EyeLeft;
}

pd::ShadingRate shading_rate_from_index(int index) {
    static constexpr std::array<pd::ShadingRate, 9> rates{
        pd::ShadingRate::ShadingRate_1X1, pd::ShadingRate::ShadingRate_1X2, pd::ShadingRate::ShadingRate_1X4,
        pd::ShadingRate::ShadingRate_2X1, pd::ShadingRate::ShadingRate_2X2, pd::ShadingRate::ShadingRate_2X4,
        pd::ShadingRate::ShadingRate_4X1, pd::ShadingRate::ShadingRate_4X2, pd::ShadingRate::ShadingRate_4X4,
    };
    return rates[static_cast<size_t>(std::clamp(index, 0, 8))];
}

void retain(ID3D12Resource*& slot, ID3D12Resource* value) {
    if (slot == value) {
        return;
    }
    if (value != nullptr) {
        value->AddRef();
    }
    if (slot != nullptr) {
        slot->Release();
    }
    slot = value;
}

glm::mat4 to_reverse_z(const glm::mat4& projection) {
    const glm::mat4 transform{
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, -1, 0,
        0, 0, 1, 1};
    return transform * projection;
}

std::filesystem::path backend_folder() {
    HMODULE self{};
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        (LPCWSTR)&backend_folder, &self);
    wchar_t buffer[4096]{};
    GetModuleFileNameW(self, buffer, static_cast<DWORD>(std::size(buffer)));
    return std::filesystem::path{buffer}.parent_path();
}

bool is_non_dlss(const ngx::Handle* handle) {
    std::scoped_lock lock{g_afw.handle_mutex};
    return g_afw.non_dlss_handles.contains(handle);
}

// PureDark: copy this eye's DLSS depth and (optionally corrected) motion vectors into AFW's per-eye inputs.
void capture_dlss_inputs(ID3D12GraphicsCommandList* cmd, ngx::Parameter* params) {
    auto& vr = VR::get();
    ID3D12Resource* depth{};
    ID3D12Resource* motion{};
    ID3D12Resource* output{};
    float mv_scale[2]{1.0f, 1.0f};
    params->Get("Depth", &depth);
    params->Get("MotionVectors", &motion);
    params->Get("Output", &output);
    params->Get("MV.Scale.X", &mv_scale[0]);
    params->Get("MV.Scale.Y", &mv_scale[1]);
    params->Get("Jitter.Offset.X", &g_afw.jitter[0]);
    params->Get("Jitter.Offset.Y", &g_afw.jitter[1]);

    {
        std::scoped_lock lock{g_afw.raw_mutex};
        retain(g_afw.raw_depth, depth);
        retain(g_afw.raw_motion, motion);
    }

    if (output != nullptr && motion != nullptr) {
        const auto mv_desc = motion->GetDesc();
        const auto output_desc = output->GetDesc();
        g_afw.mv_scale[0] = mv_scale[0] * (float)output_desc.Width / (float)mv_desc.Width;
        g_afw.mv_scale[1] = mv_scale[1] * (float)output_desc.Height / (float)mv_desc.Height;
    }

    if (depth != nullptr) {
        const auto depth_desc = depth->GetDesc();
        if (g_afw.render_size[0] != depth_desc.Width || g_afw.render_size[1] != depth_desc.Height) {
            g_afw.render_size[0] = static_cast<UINT>(depth_desc.Width);
            g_afw.render_size[1] = depth_desc.Height;
            vr->afw_resolution_change_skip_frames = 90;
        }
    }

    g_afw.rhi_thread = std::this_thread::get_id();
    const int frame = vr->get_render_frame_count();
    const auto eye = eye_for_frame(frame);
    const auto other = other_eye(eye);
    if (frame - g_afw.last_dlss_frame > 2) {
        g_afw.dlss_continue = 0;
    }
    g_afw.last_dlss_frame = frame;
    vr->afw_last_dlss_frame = frame;
    ++g_afw.dlss_continue;

    const bool buffers_valid = vr->is_hmd_active() && motion != nullptr && depth != nullptr &&
        g_afw.mv_desc[eye].pTexture != nullptr && g_afw.depth_desc[eye].pTexture != nullptr;
    if (!buffers_valid || g_afw.paused_frame > frame) {
        g_afw.paused_frame = frame;
    }
    if (!vr->is_using_afw() || vr->afw_resolution_change_skip_frames > 0 || frame - g_afw.paused_frame <= 30 || !buffers_valid) {
        return;
    }

    pd::TextureDesc source{};
    source.pTexture = depth;
    source.initialState = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
    g_afw.renderer->Copy(cmd, g_afw.depth_desc[eye], source);

    if (g_afw.raw_mv_desc[eye].pTexture != motion) {
        g_afw.raw_mv_desc[eye].pTexture = motion;
        g_afw.raw_mv_desc[eye].initialState = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        g_afw.renderer->SetupTextureDesc(g_afw.raw_mv_desc[eye]);
    }

    const auto settings = vr->get_afw_settings();
    bool motion_copied = false;
    if (vr->is_ghosting_fix_enabled() && settings.fix_object_motion &&
        g_afw.raw_velocity_desc[eye].pTexture != nullptr && g_afw.raw_velocity_desc[other].pTexture != nullptr) {
        if (g_afw.raw_mv_desc[eye].pTexture != nullptr && g_afw.mv_desc[eye].pTexture != nullptr) {
            vr->afw_update_camera_data(frame);
            pd::CorrectMotionVectorsParams correction{};
            correction.InMotionVectors = &g_afw.raw_velocity_desc[eye];
            correction.InDepth = &g_afw.depth_desc[eye];
            correction.CameraData = &g_afw.camera_mv[eye];
            correction.InMotionScale[0] = mv_scale[0];
            correction.InMotionScale[1] = mv_scale[1];
            correction.CorrectMVType = pd::FixUEObjectMotion;
            correction.ObjectMotionScale = 2.0f;
            correction.FixUEObjMotionRange = settings.fix_object_motion_range;
            correction.IgnoreMotionThreshold = settings.ignore_motion_threshold;
            correction.InUEVelocityPrev = &g_afw.raw_velocity_desc[other];
            correction.InDepthPrev = &g_afw.depth_desc[other];
            g_afw.renderer->CorrectMotionVectors(cmd, g_afw.raw_mv_desc[eye], correction);
            g_afw.renderer->Copy(cmd, g_afw.mv_desc[eye], g_afw.raw_mv_desc[eye]);
            motion_copied = true;
        }
    } else {
        source.pTexture = motion;
        source.initialState = D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        g_afw.renderer->Copy(cmd, g_afw.mv_desc[eye], source);
        motion_copied = true;
    }
    if (motion_copied) {
        g_afw.captured[eye] = true;
    }
}

ngx::Result hk_create_feature(ID3D12GraphicsCommandList* cmd, int feature, ngx::Parameter* params, ngx::Handle** out_handle) {
    const auto result = g_create_hook.unsafe_call<ngx::Result>(cmd, feature, params, out_handle);
    spdlog::info("[AFW] NGX CreateFeature id={} result=0x{:x}", feature, static_cast<uint32_t>(result));
    if (out_handle != nullptr && *out_handle != nullptr &&
        feature != ngx::feature_super_sampling && feature != ngx::feature_ray_reconstruction) {
        std::scoped_lock lock{g_afw.handle_mutex};
        g_afw.non_dlss_handles.insert(*out_handle);
    }
    return result;
}

ngx::Result hk_release_feature(ngx::Handle* handle) {
    const auto result = g_release_hook.unsafe_call<ngx::Result>(handle);
    std::scoped_lock lock{g_afw.handle_mutex};
    g_afw.non_dlss_handles.erase(handle);
    return result;
}

ngx::Result hk_evaluate_feature(ID3D12GraphicsCommandList* cmd, const ngx::Handle* handle, ngx::Parameter* params, void* callback) {
    if (cmd != nullptr && handle != nullptr && params != nullptr && g_afw.renderer != nullptr &&
        VR::get()->is_afw_selected() && !is_non_dlss(handle)) {
        capture_dlss_inputs(cmd, params);
    }
    return g_evaluate_hook.unsafe_call<ngx::Result>(cmd, handle, params, callback);
}

// PureDark: find UE's velocity buffer (needed by "Fix Object Motion Vector") from its barrier transitions.
void WINAPI hk_resource_barrier(ID3D12GraphicsCommandList* self, UINT count, const D3D12_RESOURCE_BARRIER* barriers) {
    g_barrier_hook.unsafe_call<void>(self, count, barriers);

    thread_local bool inside = false;
    if (inside || barriers == nullptr || g_afw.renderer == nullptr) {
        return;
    }
    auto& vr = VR::get();
    if (!vr->is_using_afw() || !vr->is_ghosting_fix_enabled() || !vr->get_afw_settings().fix_object_motion) {
        return;
    }

    const int frame = vr->get_render_frame_count();
    const auto eye = eye_for_frame(frame);
    ID3D12Resource* velocity{};
    for (UINT i = 0; i < count; ++i) {
        const auto& barrier = barriers[i];
        if (barrier.Type != D3D12_RESOURCE_BARRIER_TYPE_TRANSITION || barrier.Transition.pResource == nullptr ||
            barrier.Transition.pResource == g_afw.raw_velocity_desc[eye].pTexture ||
            barrier.Transition.pResource == g_afw.raw_mv_desc[eye].pTexture) {
            continue;
        }
        const auto desc = barrier.Transition.pResource->GetDesc();
        if (desc.Format != DXGI_FORMAT_R16G16B16A16_UNORM) {
            continue;
        }
        const bool to_shader = (barrier.Transition.StateAfter & D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE) ==
            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE;
        const bool from_target = barrier.Transition.StateBefore == D3D12_RESOURCE_STATE_RENDER_TARGET ||
            barrier.Transition.StateBefore == shader_resource_state;
        const bool render_sized = (desc.Width == g_afw.render_size[0] || g_afw.render_size[0] == 0) &&
            (desc.Height == g_afw.render_size[1] || g_afw.render_size[1] == 0);
        if (to_shader && from_target && render_sized) {
            velocity = barrier.Transition.pResource;
        }
    }
    if (velocity == nullptr) {
        return;
    }

    // Only trust the RHI submission thread, unless the game submits everything on the RHI thread.
    static std::atomic<int> last_rhi_found{0};
    static std::atomic<int> last_submission_found{0};
    const bool is_rhi_thread = g_afw.rhi_thread.load() == std::this_thread::get_id();
    if (is_rhi_thread) {
        last_rhi_found = frame;
    } else {
        last_submission_found = frame;
    }
    const bool submission_found_recently = frame - last_submission_found.load() <= 100;
    if (is_rhi_thread && submission_found_recently) {
        return;
    }
    if (frame - g_afw.last_dlss_frame > 1) {
        return;
    }

    const auto desc = velocity->GetDesc();
    if (g_afw.raw_velocity_desc[eye].pTexture == nullptr ||
        g_afw.raw_velocity_desc[eye].pTexture->GetDesc().Width != desc.Width ||
        g_afw.raw_velocity_desc[eye].pTexture->GetDesc().Height != desc.Height) {
        g_afw.renderer->CreateTexture(static_cast<int>(desc.Width), static_cast<int>(desc.Height), desc.Format,
            shader_resource_state, g_afw.raw_velocity_desc[eye], true);
    }

    static std::mutex sources_mutex{};
    static std::map<ID3D12Resource*, CachedTexture> sources{};
    pd::TextureDesc* source{};
    {
        std::scoped_lock lock{sources_mutex};
        auto& entry = sources[velocity];
        if (entry.desc.pTexture != velocity || !same_texture(entry.resource, desc)) {
            entry.desc.pTexture = velocity;
            entry.desc.initialState = D3D12_RESOURCE_STATE_RENDER_TARGET;
            entry.resource = desc;
            g_afw.renderer->SetupTextureDesc(entry.desc);
        }
        source = &entry.desc;
    }

    inside = true;
    g_afw.renderer->Copy(self, g_afw.raw_velocity_desc[eye], *source);
    inside = false;
}

// Store the hook first, enable it second: a detour can only run once its global hook object is complete.
bool install_hook(SafetyHookInline& hook, void* target, void* detour) {
    hook = safetyhook::create_inline(target, detour, SafetyHookInline::StartDisabled);
    return static_cast<bool>(hook) && hook.enable().has_value();
}

bool install_barrier_hook() {
    auto* cmd = g_afw.renderer->BeginCommandList(0);
    if (cmd == nullptr) {
        return false;
    }
    // ID3D12GraphicsCommandList vtable slot 26 = ResourceBarrier (same slot PureDark hooks).
    void* target = (*reinterpret_cast<void***>(cmd))[26];
    g_afw.renderer->EndCommandList(0);
    return install_hook(g_barrier_hook, target, reinterpret_cast<void*>(&hk_resource_barrier));
}

bool install_ngx_hooks() {
    HMODULE ngx_module = LoadLibraryA("_nvngx.dll");
    if (ngx_module == nullptr) {
        ngx_module = LoadLibraryA("nvngx.dll");
    }
    // OptiScaler installs itself as dxgi.dll or winmm.dll and exports the NGX entry points (PureDark's check).
    for (const char* proxy : {"dxgi.dll", "winmm.dll"}) {
        if (HMODULE candidate = LoadLibraryA(proxy); candidate != nullptr &&
            GetProcAddress(candidate, "NVSDK_NGX_D3D12_CreateFeature") != nullptr) {
            ngx_module = candidate;
            spdlog::info("[AFW] OptiScaler detected ({}), hooking it instead of nvngx.dll", proxy);
            break;
        }
    }
    if (ngx_module == nullptr) {
        spdlog::error("[AFW] nvngx.dll not loaded");
        return false;
    }

    const auto create = GetProcAddress(ngx_module, "NVSDK_NGX_D3D12_CreateFeature");
    const auto release = GetProcAddress(ngx_module, "NVSDK_NGX_D3D12_ReleaseFeature");
    const auto evaluate = GetProcAddress(ngx_module, "NVSDK_NGX_D3D12_EvaluateFeature");
    if (create == nullptr || release == nullptr || evaluate == nullptr) {
        spdlog::error("[AFW] NGX D3D12 entry points not found");
        return false;
    }
    return install_hook(g_create_hook, reinterpret_cast<void*>(create), reinterpret_cast<void*>(&hk_create_feature)) &&
        install_hook(g_release_hook, reinterpret_cast<void*>(release), reinterpret_cast<void*>(&hk_release_feature)) &&
        install_hook(g_evaluate_hook, reinterpret_cast<void*>(evaluate), reinterpret_cast<void*>(&hk_evaluate_feature));
}

} // namespace

namespace uevr::afw {

bool initialize() {
    std::scoped_lock lock{g_afw.init_mutex};
    auto& vr = VR::get();
    if (vr->afw_plugin_ready.load()) {
        return true;
    }
    if (g_afw.gave_up) {
        return false;
    }
    if (g_framework == nullptr || !g_framework->is_dx12()) {
        set_status("Unavailable: AFW needs a DX12 game");
        g_afw.gave_up = true;
        return false;
    }

    if (g_afw.init_device == nullptr) {
        HMODULE plugin = GetModuleHandleW(L"PDAFWPlugin.dll");
        if (plugin == nullptr) {
            const auto path = backend_folder() / L"PDAFWPlugin.dll";
            std::error_code error{};
            if (!std::filesystem::exists(path, error)) {
                set_status("PDAFWPlugin.dll not found next to UEVRBackend.dll: copy it from PureDark's AFW beta 6, then restart the game");
                g_afw.gave_up = true;
                return false;
            }
            plugin = LoadLibraryW(path.c_str());
            if (plugin == nullptr) {
                spdlog::error("[AFW] LoadLibrary failed for PDAFWPlugin.dll, error {}", GetLastError());
                set_status("PDAFWPlugin.dll found but could not be loaded");
                g_afw.gave_up = true;
                return false;
            }
        }
        g_afw.init_device = reinterpret_cast<decltype(&pd::InitDevice)>(GetProcAddress(plugin, "InitDevice"));
        g_afw.init_frame_warp = reinterpret_cast<decltype(&pd::InitFrameWarp)>(GetProcAddress(plugin, "InitFrameWarp"));
        g_afw.evaluate_frame_warp = reinterpret_cast<decltype(&pd::EvaluateFrameWarp)>(GetProcAddress(plugin, "EvaluateFrameWarp"));
        if (g_afw.init_device == nullptr || g_afw.init_frame_warp == nullptr || g_afw.evaluate_frame_warp == nullptr) {
            set_status("PDAFWPlugin.dll does not export InitDevice / InitFrameWarp / EvaluateFrameWarp");
            g_afw.init_device = nullptr;
            g_afw.gave_up = true;
            return false;
        }
    }

    auto& hook = g_framework->get_d3d12_hook();
    ID3D12Device* device = hook != nullptr ? hook->get_device() : nullptr;
    ID3D12CommandQueue* queue = hook != nullptr ? hook->get_command_queue() : nullptr;
    if (device == nullptr || queue == nullptr) {
        set_status("Waiting for the game's D3D12 device");
        return false; // retried from VR::on_present while AFW is selected
    }

    pd::DeviceParams params{};
    params.d3d12Device = device;
    params.d3d12Queue = queue;
    g_afw.renderer = g_afw.init_device(params);
    if (g_afw.renderer == nullptr) {
        set_status("PDAFWPlugin.dll InitDevice failed");
        g_afw.gave_up = true;
        return false;
    }
    if (!install_barrier_hook()) {
        set_status("Could not hook ID3D12GraphicsCommandList::ResourceBarrier");
        g_afw.gave_up = true;
        return false;
    }
    if (!install_ngx_hooks()) {
        set_status("Could not hook DLSS (NGX); AFW needs DLSS or DLAA ON");
        g_afw.gave_up = true;
        return false;
    }

    set_status("PDAFWPlugin.dll loaded");
    vr->afw_plugin_ready = true;
    return true;
}

const char* status() {
    return g_afw.status.load();
}

void prepare_inputs() {
    if (g_afw.renderer == nullptr) {
        return;
    }
    // Per-eye AFW inputs follow the size and format of the DLSS inputs (PureDark's on_frame). Prepared during the
    // warm-up too, so DLSS capture is already running when warping starts.
    std::scoped_lock lock{g_afw.raw_mutex};
    if (g_afw.raw_depth != nullptr) {
        const auto desc = g_afw.raw_depth->GetDesc();
        for (int i = 0; i < 2; ++i) {
            auto& target = g_afw.depth_desc[i];
            if (target.pTexture == nullptr || target.pTexture->GetDesc().Width != desc.Width ||
                target.pTexture->GetDesc().Height != desc.Height) {
                g_afw.captured[i] = false;
                g_afw.renderer->CreateTexture(static_cast<int>(desc.Width), static_cast<int>(desc.Height), desc.Format,
                    shader_resource_state, target, true);
            }
        }
    }
    if (g_afw.raw_motion != nullptr) {
        const auto desc = g_afw.raw_motion->GetDesc();
        for (int i = 0; i < 2; ++i) {
            auto& target = g_afw.mv_desc[i];
            if (target.pTexture == nullptr || target.pTexture->GetDesc().Width != desc.Width ||
                target.pTexture->GetDesc().Height != desc.Height) {
                g_afw.captured[i] = false;
                g_afw.renderer->CreateTexture(static_cast<int>(desc.Width), static_cast<int>(desc.Height),
                    DXGI_FORMAT_R16G16_FLOAT, shader_resource_state, target, true);
            }
        }
    }
}

std::optional<OtherEye> evaluate(ID3D12Resource* scene, D3D12_RESOURCE_STATES scene_state,
    uint32_t command_slot, int frame_count, const D3D12_BOX& eye_box)
{
    auto& vr = VR::get();
    if (g_afw.renderer == nullptr || scene == nullptr) {
        return std::nullopt;
    }

    const auto width = vr->get_hmd_width();
    const auto height = vr->get_hmd_height();
    if (!g_afw.buffers_ready || g_afw.buffer_size[0] != width || g_afw.buffer_size[1] != height) {
        // Same parameters as PureDark's D3D12Component::setup: HMD eye size, UEVR's B8G8R8A8 eye format.
        pd::FrameWarpInitParams init{static_cast<int>(width), static_cast<int>(height), DXGI_FORMAT_B8G8R8A8_UNORM};
        spdlog::info("[AFW] InitFrameWarp {}x{}", width, height);
        g_afw.buffers = g_afw.init_frame_warp(init);
        g_afw.buffer_size[0] = width;
        g_afw.buffer_size[1] = height;
        g_afw.written[0] = g_afw.written[1] = false;
        g_afw.buffers_ready = g_afw.buffers.eyeFrameBuffers[0].color.pTexture != nullptr &&
            g_afw.buffers.eyeFrameBuffers[1].color.pTexture != nullptr;
        if (!g_afw.buffers_ready) {
            set_status("InitFrameWarp returned no eye buffers");
            return std::nullopt;
        }
        set_status("Warping");
    }

    const auto eye = eye_for_frame(frame_count);
    const auto other = other_eye(eye);
    auto& current = g_afw.buffers.eyeFrameBuffers[eye];
    auto& warped = g_afw.buffers.eyeFrameBuffers[other];

    // Warp only once both eyes' DLSS depth and motion were captured into the current input textures.
    if (g_afw.captured[eye] && g_afw.captured[other]) {
        const auto slot = command_slot % std::size(g_afw.scene_desc);
        auto& scene_desc = g_afw.scene_desc[slot];
        const auto scene_resource = scene->GetDesc();
        if (scene_desc.pTexture != scene || !same_texture(g_afw.scene_resource_desc[slot], scene_resource)) {
            scene_desc.pTexture = scene;
            scene_desc.initialState = scene_state;
            g_afw.scene_resource_desc[slot] = scene_resource;
            g_afw.renderer->SetupTextureDesc(scene_desc);
        }
        scene_desc.initialState = scene_state;

        auto* cmd = g_afw.renderer->BeginCommandList(static_cast<int>(command_slot));
        if (cmd != nullptr) {
            const auto settings = vr->get_afw_settings();
            if (settings.sharpening && settings.sharpness > 0.0f) {
                g_afw.renderer->Crop(cmd, warped.color, scene_desc, eye_box);
                g_afw.renderer->Sharpen(cmd, current.color, warped.color, settings.sharpness);
            } else {
                g_afw.renderer->Crop(cmd, current.color, scene_desc, eye_box);
            }

            g_afw.current_frame_buffer.color = current.color;
            g_afw.current_frame_buffer.depth = g_afw.depth_desc[eye];
            g_afw.current_frame_buffer.motionVectors = g_afw.mv_desc[eye];

            pd::FrameWarpEvaluateParams params{};
            params.InCmdList = cmd;
            params.InEyeFrameBuffer = &g_afw.current_frame_buffer;
            params.InUIColorAlpha = nullptr;
            params.IsHudlessColor = true;
            params.MotionVectorsType = vr->is_ghosting_fix_enabled() ? pd::Normal : pd::FromOtherEye;
            params.InMotionScale[0] = g_afw.mv_scale[0];
            params.InMotionScale[1] = g_afw.mv_scale[1];
            params.Mode = static_cast<pd::FrameWarpMode>(std::clamp(settings.mode, 0, 3));
            params.EyeIndex = eye;
            params.ClearBeforeWarping = settings.clear_before_warping;
            params.CameraData = &g_afw.camera[eye];
            params.IgnoreMotionThreshold = settings.ignore_motion_threshold;
            params.Debug = settings.debug;
            if (vr->is_ghosting_fix_enabled() && settings.fix_object_motion && settings.fix_flicker) {
                params.InUEVelocityBuffer = &g_afw.raw_velocity_desc[eye];
            }
            params.UseUINT64 = false;
            params.ShadingRate = shading_rate_from_index(settings.shading_rate);
            g_afw.evaluate_frame_warp(params);
            g_afw.renderer->EndCommandList(static_cast<int>(command_slot));
            g_afw.written[eye] = true;
            g_afw.written[other] = true;
        }
    }

    if (!g_afw.written[other] || warped.color.pTexture == nullptr) {
        return std::nullopt;
    }
    const auto desc = warped.color.pTexture->GetDesc();
    OtherEye result{};
    result.color = warped.color.pTexture;
    result.depth = warped.depth.pTexture;
    result.box = D3D12_BOX{0, 0, 0, static_cast<UINT>(desc.Width), desc.Height, 1};
    result.destination_is_left = other == pd::EyeLeft;
    return result;
}

} // namespace uevr::afw

// PureDark's VR::update_camera_data: source (rendered) and destination (other) eye matrices for AFW.
void VR::afw_update_camera_data(int frame_count) {
    if (!(g_afw.last_camera_update < frame_count || g_afw.last_camera_update > frame_count + 100)) {
        return;
    }
    g_afw.last_camera_update = frame_count;

    std::shared_lock _{get_runtime()->eyes_mtx};

    const int eye = (m_render_frame_count % 2 == m_left_eye_interval) ? 0 : 1;
    const int other = 1 - eye;
    auto& camera = g_afw.camera;
    auto& camera_mv = g_afw.camera_mv;

    camera_mv[eye].srcWorldToViewMatrixPrev = camera[eye].srcWorldToViewMatrix;
    camera_mv[eye].srcViewToWorldMatrixPrev = camera[eye].srcViewToWorldMatrix;
    camera_mv[eye].srcViewToClipMatrixPrev = camera[eye].srcViewToClipMatrix;
    camera_mv[eye].srcClipToViewMatrixPrev = camera[eye].srcClipToViewMatrix;

    camera_mv[eye].destWorldToViewMatrix = camera[other].srcWorldToViewMatrix;
    camera_mv[eye].destViewToWorldMatrix = camera[other].srcViewToWorldMatrix;
    camera_mv[eye].destViewToClipMatrix = camera[other].srcViewToClipMatrix;
    camera_mv[eye].destClipToViewMatrix = camera[other].srcClipToViewMatrix;

    camera_mv[other].destWorldToViewMatrixPrev = camera[eye].srcWorldToViewMatrix;
    camera_mv[other].destViewToWorldMatrixPrev = camera[eye].srcViewToWorldMatrix;
    camera_mv[other].destViewToClipMatrixPrev = camera[eye].srcViewToClipMatrix;
    camera_mv[other].destClipToViewMatrixPrev = camera[eye].srcClipToViewMatrix;

    auto offset = last_update_matrix_frame_count[eye] - g_afw.last_camera_update;
    offset = std::clamp(offset, 0, 2) / 2;

    camera[eye].camWorldToViewMatrix = glm::mat4(1.0f); // not used (no AFW-rendered UI)
    camera[eye].camViewToWorldMatrix = glm::mat4(1.0f);
    camera[eye].camViewToClipMatrix = glm::mat4(1.0f);
    camera[eye].camClipToViewMatrix = glm::mat4(1.0f);
    camera[eye].destViewToWorldMatrix = render_view_inv_matrix[eye][offset].other;
    camera[eye].srcViewToWorldMatrix = render_view_inv_matrix[eye][offset].curr;
    camera[eye].destWorldToViewMatrix = glm::inverse(camera[eye].destViewToWorldMatrix);
    camera[eye].srcWorldToViewMatrix = glm::inverse(camera[eye].srcViewToWorldMatrix);
    camera[eye].destViewToClipMatrix = to_reverse_z(render_projection_matrix[eye].other);
    camera[eye].srcViewToClipMatrix = to_reverse_z(render_projection_matrix[eye].curr);
    camera[eye].destClipToViewMatrix = glm::inverse(camera[eye].destViewToClipMatrix);
    camera[eye].srcClipToViewMatrix = glm::inverse(camera[eye].srcViewToClipMatrix);

    camera_mv[eye].srcWorldToViewMatrix = camera[eye].srcWorldToViewMatrix;
    camera_mv[eye].srcViewToWorldMatrix = camera[eye].srcViewToWorldMatrix;
    camera_mv[eye].srcViewToClipMatrix = camera[eye].srcViewToClipMatrix;
    camera_mv[eye].srcClipToViewMatrix = camera[eye].srcClipToViewMatrix;
}

void VR::afw_draw_ui() {
    ImGui::SetNextItemOpen(true, ImGuiCond_Once);
    if (!ImGui::TreeNode("Alternate Frame Warping (PureDark AFW)")) {
        return;
    }
    ImGui::TextWrapped("AFW by PureDark: one real eye is rendered per frame and AFW warps it into the other eye. "
        "Used with permission, non-commercial. Needs PDAFWPlugin.dll next to UEVRBackend.dll and DLSS or DLAA ON in-game.");
    ImGui::TextWrapped("Plugin: %s", uevr::afw::status());
    if (is_using_afw()) {
        ImGui::TextWrapped("State: warping (stereo from AFW)");
    } else {
        ImGui::TextWrapped("State: not warping - rendering Synchronized Sequential (warm-up after selecting AFW or a resolution change, or the plugin is unavailable)");
    }
    if (m_render_frame_count - afw_last_dlss_frame.load() > 10) {
        ImGui::TextWrapped("No DLSS instance detected, are you sure you have turned on DLSS in-game?");
    }
    m_afw_mode->draw("Framewarp Mode");
    if (m_afw_mode->value() == 3) {
        m_afw_shading_rate->draw("Framewarp Shading Rate");
    }
    m_afw_clear_before->draw("Clear Before Framewarp");
    m_afw_debug->draw("Debug Framewarp");
    m_afw_sharpening->draw("Enable Sharpening");
    m_afw_sharpness->draw("Sharpness");
    m_afw_fix_object_mv->draw("Fix Object Motion Vector");
    m_afw_fix_object_mv_range->draw("Fix Object Motion Range");
    if (is_using_afw() && m_afw_fix_object_mv->value() && g_afw.raw_velocity_desc[0].pTexture == nullptr) {
        ImGui::TextWrapped("No UE velocity buffer found yet; the object motion fix is not active.");
    }
    m_afw_fix_flicker->draw("Fix Moving Object Brightness Flickering");
    m_afw_ignore_motion_threshold->draw("Ignore Motion Threshold");
    ImGui::TreePop();
}

// External PureDark PDAFWPlugin.dll export and layout preflight (no GPU warp).
// Inspired by tig3rmast3r/witcher3-vr's MIT independent binary-interface bridge.
// No PureDark code, header or DLL is copied. Never call unverified binary function pointers.
#include <windows.h>
#include <d3d11.h>
#include <d3d12.h>
#include <dxgi.h>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>
#include <type_traits>

namespace abi {
struct Matrix4x4 { float e[16]{}; };
struct DeviceParams {
    ID3D11Device* d3d11{};
    ID3D11DeviceContext* context{};
    ID3D12Device* d3d12{};
    ID3D12CommandQueue* queue{};
    IDXGIAdapter* adapter{};
};
struct FrameWarpInitParams {
    int width{}, height{};
    DXGI_FORMAT eye_format{DXGI_FORMAT_R8G8B8A8_UNORM};
    DXGI_FORMAT backbuffer_format{DXGI_FORMAT_R10G10B10A2_UNORM};
};
enum class FrameWarpMode : int { None, AlternateEye, PreviousFrame, Combined };
enum class EyeIndex : int { Left, Right };
enum class MotionVectorsType : int { Normal, FromOtherEye, ObjectOnly };
struct TextureDesc {
    int image_type{};
    ID3D12Resource* texture{};
    int srv_pos{-1}, uav_pos{-1};
    D3D12_GPU_DESCRIPTOR_HANDLE srv{};
    D3D12_GPU_DESCRIPTOR_HANDLE uav{};
    union { D3D12_CPU_DESCRIPTOR_HANDLE rtv{}; D3D12_CPU_DESCRIPTOR_HANDLE dsv; };
    D3D12_RESOURCE_STATES initial_state{D3D12_RESOURCE_STATE_COMMON};
};
struct FrameBufferDesc { TextureDesc color, depth, motion; };
struct EyeFrameBuffers { FrameBufferDesc eye[2]; };
struct CameraData { Matrix4x4 m[12]; };
struct FrameWarpEvaluateParams {
    void* cmd_list{};
    FrameBufferDesc* input{};
    FrameBufferDesc* output{};
    TextureDesc* ui{};
    float ui_scale[2]{1.0f, 1.0f};
    float ui_pos[3]{0.0f, 0.0f, -1.0f};
    float mv_scale[2]{};
    FrameWarpMode mode{};
    EyeIndex eye{};
    CameraData* camera{};
    bool clear{};
    float ignore_motion_threshold{2.5f};
    bool hudless{true};
    MotionVectorsType mv_type{MotionVectorsType::Normal};
    bool debug{}, is_foveated{};
    RECT foveated_area{};
    TextureDesc* ue_velocity{};
    bool use_uint64{};
    std::uint32_t shading_rate{9}; // Published 1x1 enum value in beta-6 header.
    float reserved[12]{};
};
static_assert(sizeof(DeviceParams) == 40);
static_assert(sizeof(FrameWarpInitParams) == 16);
static_assert(sizeof(TextureDesc) == 56);
static_assert(sizeof(FrameBufferDesc) == 168);
static_assert(sizeof(EyeFrameBuffers) == 336);
static_assert(sizeof(CameraData) == 768);
static_assert(sizeof(FrameWarpEvaluateParams) == 184);
static_assert(offsetof(FrameWarpEvaluateParams, camera) == 72);
static_assert(offsetof(FrameWarpEvaluateParams, foveated_area) == 100);
static_assert(offsetof(FrameWarpEvaluateParams, ue_velocity) == 120);
static_assert(offsetof(FrameWarpEvaluateParams, shading_rate) == 132);
static_assert(offsetof(FrameWarpEvaluateParams, reserved) == 136);
static_assert(std::is_trivially_copyable_v<FrameWarpEvaluateParams>);
}

int wmain(int argc, wchar_t** argv) {
    std::wcout << L"DuoView AFW interface preflight; NOT a stereo build.\n";
    std::wcout << L"x64 expected params size " << sizeof(abi::FrameWarpEvaluateParams)
               << L", shading rate offset " << offsetof(abi::FrameWarpEvaluateParams, shading_rate)
               << L", reserved offset " << offsetof(abi::FrameWarpEvaluateParams, reserved) << L"\n";
    if (argc == 2 && std::wstring(argv[1]) == L"--self-test") {
        std::wcout << L"PASS: compile-time x64 layout checks.\n";
        return 0;
    }
    if (argc != 2) {
        std::wcerr << L"Usage: AFWAbiProbe.exe C:\\full\\path\\PDAFWPlugin.dll\n";
        return 2;
    }
    const std::wstring path(argv[1]);
    if (path.empty() || GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES) {
        std::wcerr << L"ERROR: provide existing PDAFWPlugin.dll path.\n";
        return 3;
    }
    wchar_t full[MAX_PATH]{};
    const DWORD n = GetFullPathNameW(path.c_str(), MAX_PATH, full, nullptr);
    if (n == 0 || n >= MAX_PATH) {
        std::wcerr << L"ERROR: DLL path too long or invalid.\n";
        return 4;
    }
    const HMODULE dll = LoadLibraryExW(
        full, nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!dll) {
        std::wcerr << L"ERROR: DLL could not load, Windows error " << GetLastError() << L".\n";
        return 5;
    }
    bool all_present = true;
    for (const char* name : {"InitDevice", "InitFrameWarp", "EvaluateFrameWarp"}) {
        const bool found = GetProcAddress(dll, name) != nullptr;
        std::cout << name << ": " << (found ? "PRESENT" : "MISSING") << "\n";
        all_present &= found;
    }
    FreeLibrary(dll);
    if (!all_present) {
        std::wcerr << L"FAIL: one or more named exports missing.\n";
        return 6;
    }
    std::wcout << L"PASS: load and exports; NOT verified: binary ABI, vtable or actual warp.\n";
    return 0;
}

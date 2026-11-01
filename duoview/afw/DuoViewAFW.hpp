#pragma once
// DuoView AFW Stage 1: PureDark's Alternate Frame Warping inside the DuoView v207 backend.
// Interface only; the implementation (and the only include of PureDark's PDAFWPlugin.h) lives in
// DuoViewAFW.cpp so the plugin's `using namespace pd;` never reaches Joey's other translation units.
#include <cstdint>
#include <optional>

#include <d3d12.h>

namespace uevr::afw {

// The warped image of the eye that was NOT rendered this frame, owned by PDAFWPlugin.dll and left in
// PIXEL_SHADER_RESOURCE | NON_PIXEL_SHADER_RESOURCE state after EvaluateFrameWarp.
struct OtherEye {
    ID3D12Resource* color{};
    ID3D12Resource* depth{};
    D3D12_BOX box{};
    bool destination_is_left{};
};

// Loads PDAFWPlugin.dll from the UEVRBackend.dll folder if (and only if) the file is there, creates the
// plugin device and installs the DLSS (NGX) and ResourceBarrier hooks. Without the DLL nothing is hooked.
// Safe to call repeatedly; it retries only while the D3D12 device is not available yet.
bool initialize();

// Short plain-language status for the UEVR menu.
const char* status();

// Creates/resizes AFW's per-eye depth and motion-vector inputs to match the DLSS inputs. Called every frame while
// rendering method 7 is selected (including the warm-up), as PureDark does in D3D12Component::on_frame.
void prepare_inputs();

// Crops the eye rendered this frame from the scene texture, hands it with its DLSS depth and motion
// vectors to PureDark's EvaluateFrameWarp and returns the other eye. Returns nothing until AFW has
// written the other eye at least once, so an uninitialised image is never submitted.
std::optional<OtherEye> evaluate(ID3D12Resource* scene, D3D12_RESOURCE_STATES scene_state,
    uint32_t command_slot, int frame_count, const D3D12_BOX& eye_box);

} // namespace uevr::afw

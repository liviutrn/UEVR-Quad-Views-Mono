#!/usr/bin/env python3
"""v208: free video memory / GPU time for DuoView Mono (ID6). Applies AFTER v207.

1. "Same image for both eyes" (menu toggle, default OFF = exact v207 output):
   DuoView composes the Mono image into the LEFT half of the double-wide XR
   image only (the second copy / second raster half is skipped) and both
   OpenXR projection views reference the SAME swapchain, array slice and
   rectangle (the union of the two eye crops, with its exact FOV). The flag is
   frozen in the DuoView frame settings and travels with the composed frame to
   xrEndFrame, so composition and submission can never disagree. This is also
   the signal a mono-aware VectorXR uses to run frame generation once.
2. One Mono compose texture shared by all XR command slots instead of one per
   swapchain image (all slots record on the game's single direct queue, one
   ExecuteCommandLists each, and always return it to RENDER_TARGET).
3. Live video-memory readout (DXGI QueryVideoMemoryInfo via the game's own
   factory) in the DuoView menu and the log every 10 s while ID6 is selected.

NOT changed: Unreal rendering, Native Fix capture/targets, gaze, FOV fix,
shaders, swapchain size (still double-wide), Joey Mono ID5 and all other modes.
Edits only files already in verify_stage234.py's allowed sets.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_v208_shared_eye_vram.py <backend>")
root = Path(sys.argv[1])
files = {}


def load(rel):
    if rel not in files:
        files[rel] = (root / rel).read_text(encoding="utf-8-sig")
    return files[rel]


def replace(rel, old, new, count=1, label=""):
    text = load(rel)
    found = text.count(old)
    if found != count:
        raise SystemExit(f"v208 anchor mismatch in {rel} ({label or old[:60]!r}): found {found}, expected {count}")
    files[rel] = text.replace(old, new)


# ---------------------------------------------------------------- settings
CFG = "src/mods/vr/DuoViewConfig.hpp"
replace(CFG, "    bool sharp_periphery{true};\n};\n",
        "    bool sharp_periphery{true};\n"
        "    // v208: present the one Mono image to BOTH eyes from the same XR\n"
        "    // swapchain rectangle (left half); skips the right-half copy/raster.\n"
        "    // Default OFF keeps v207 output exactly.\n"
        "    bool shared_eye_image{false};\n};\n", label="Settings tail")
replace(CFG, "    out.sharp_periphery=requested.sharp_periphery;\n",
        "    out.sharp_periphery=requested.sharp_periphery;\n"
        "    out.shared_eye_image=requested.shared_eye_image;\n", label="reconcile")

# ------------------------------------------------- union crop (pure helper)
MONO = "src/mods/vr/MonoRenderingPolicy.hpp"
replace(MONO,
        "        (1.f - 2.f * top / height) * g.vertical, (1.f - 2.f * bottom / height) * g.vertical}};\n}\n",
        "        (1.f - 2.f * top / height) * g.vertical, (1.f - 2.f * bottom / height) * g.vertical}};\n}\n"
        r'''
// v208 "Same image for both eyes": one rectangle that covers both eye crops of
// the same Mono image. Crop tangents are linear in pixel position, so the FOV
// of the union rectangle is exactly the min/max of the two crop FOVs.
inline std::optional<ProjectionCrop> shared_projection_crop(const ProjectionCrop& a, const ProjectionCrop& b) {
    if (!a.width || !a.height || !b.width || !b.height) { return {}; }
    for (float v : a.fov) { if (!std::isfinite(v)) { return {}; } }
    for (float v : b.fov) { if (!std::isfinite(v)) { return {}; } }
    const uint64_t right = (std::max)(uint64_t(a.x) + a.width, uint64_t(b.x) + b.width);
    const uint64_t bottom = (std::max)(uint64_t(a.y) + a.height, uint64_t(b.y) + b.height);
    const uint32_t left = (std::min)(a.x, b.x), top = (std::min)(a.y, b.y);
    if (right > 32768 || bottom > 32768) { return {}; }
    ProjectionCrop out{left, top, static_cast<uint32_t>(right - left), static_cast<uint32_t>(bottom - top), {
        (std::min)(a.fov[0], b.fov[0]), (std::max)(a.fov[1], b.fov[1]),
        (std::max)(a.fov[2], b.fov[2]), (std::min)(a.fov[3], b.fov[3])}};
    if (!(out.fov[0] < out.fov[1] && out.fov[3] < out.fov[2])) { return {}; }
    return out;
}
''', label="projection_crop end")

# ------------------------------------------------ left-eye-only XR copy
COPY = "src/mods/vr/DuoViewMonoCopyD3D12.hpp"
replace(COPY, "                                    D3D12_RESOURCE_STATES destination_state) {\n",
        "                                    D3D12_RESOURCE_STATES destination_state,\n"
        "                                    bool left_eye_only = false) {\n", label="copy signature")
replace(COPY, "    cmd->CopyTextureRegion(&to,w,0,0,&from,&box);\n",
        "    // v208: with \"Same image for both eyes\" both views read the left half.\n"
        "    if(!left_eye_only) cmd->CopyTextureRegion(&to,w,0,0,&from,&box);\n", label="right copy")

# ------------------------------------------- compositor: shared output + flag
D = "src/mods/vr/DuoViewD3D12.hpp"
replace(D, "#include <memory>\n#include <string>\n", "#include <memory>\n#include <mutex>\n#include <string>\n")
replace(D, "using Microsoft::WRL::ComPtr;\n", r'''using Microsoft::WRL::ComPtr;
// v208: ONE Mono compose texture shared by every XR command slot (was one per
// swapchain image, W*H*4 bytes each). All slots record on the game's single
// direct queue with one ExecuteCommandLists each, so their GPU use never
// overlaps, and every slot leaves the texture in RENDER_TARGET state. Each
// Compositor keeps its own reference (GPU lifetime); this is only a cache.
struct SharedOutputCache { std::mutex mutex; ComPtr<ID3D12Resource> texture; };
inline SharedOutputCache& shared_output_cache() { static SharedOutputCache cache; return cache; }
// Call only after every Compositor was destroyed (their slots retired).
inline void release_shared_output() {
    auto& cache = shared_output_cache();
    std::scoped_lock lock{cache.mutex};
    cache.texture.Reset();
}
''', label="namespace head")
replace(D, "        const auto copied = copy_composite_to_stereo(cmd, device, output_.Get(), destination,\n"
           "            D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_RENDER_TARGET);\n",
        "        const auto copied = copy_composite_to_stereo(cmd, device, output_.Get(), destination,\n"
        "            D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_RENDER_TARGET,\n"
        "            frame.settings.shared_eye_image);\n", label="record copy")
replace(D, "            const D3D12_VIEWPORT viewport{\n"
           "                0,0,static_cast<float>(width_*2),static_cast<float>(height_),0,1};\n"
           "            const D3D12_RECT rect{\n"
           "                0,0,static_cast<LONG>(width_*2),static_cast<LONG>(height_)};\n",
        "            // v208: same image for both eyes => raster the left half only.\n"
        "            const UINT direct_width=frame.config.settings.shared_eye_image ? width_ : width_*2;\n"
        "            const D3D12_VIEWPORT viewport{\n"
        "                0,0,static_cast<float>(direct_width),static_cast<float>(height_),0,1};\n"
        "            const D3D12_RECT rect{\n"
        "                0,0,static_cast<LONG>(direct_width),static_cast<LONG>(height_)};\n", label="direct viewport")
replace(D, "            copy_composite_to_stereo(cmd,device,output_.Get(),destination,\n"
           "                D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET);\n",
        "            copy_composite_to_stereo(cmd,device,output_.Get(),destination,\n"
        "                D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,\n"
        "                frame.config.settings.shared_eye_image);\n", label="native copy")
replace(D, "    UINT64 timing_frequency() const { return frequency_; }\n",
        "    UINT64 timing_frequency() const { return frequency_; }\n"
        "    ID3D12Resource* output_resource() const { return output_.Get(); } // v208 diagnostics\n")
replace(D, "        if (!check(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &texture,\n"
           "            D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr, IID_PPV_ARGS(&output_)), \"Create output\")) return false;\n"
           "        output_->SetName(L\"DuoView::MonoComposite\");\n",
        r'''        {
            // v208: reuse the shared compose texture when it matches this slot.
            auto& cache=shared_output_cache();
            std::scoped_lock lock{cache.mutex};
            if (cache.texture) {
                const auto existing=cache.texture->GetDesc();
                ComPtr<ID3D12Device> owner;
                if (existing.Width==width && existing.Height==height &&
                    existing.Format==DXGI_FORMAT_B8G8R8A8_TYPELESS &&
                    existing.Flags==D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET &&
                    SUCCEEDED(cache.texture->GetDevice(IID_PPV_ARGS(&owner))) && owner.Get()==device)
                    output_=cache.texture;
            }
            if (!output_) {
                if (!check(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &texture,
                    D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr, IID_PPV_ARGS(&output_)), "Create output")) return false;
                output_->SetName(L"DuoView::MonoComposite (v208 shared)");
                cache.texture=output_;
            }
        }
''', label="output creation")

# ------------------------------------------------------- frame -> xrEndFrame
XRH = "src/mods/vr/runtimes/OpenXR.hpp"
replace(XRH, "        bool coherent_matches_render{};\n    };\n",
        "        bool coherent_matches_render{};\n"
        "        bool duoview_shared_image{}; // v208: composed into the left half only\n    };\n")

XR = "src/mods/vr/runtimes/OpenXR.cpp"
replace(XR, "    const auto debug_submit_empty = this->debug_submit_empty_frame->value();\n",
        r'''    // v208 "Same image for both eyes": the frame was composed into the left
    // half only. Both views then reference the same swapchain, slice and
    // rectangle (union of the two crops, exact FOV); pose stays the Mono pose.
    const auto shared_crop = (mono_projection && mono_crops[0] && mono_crops[1] &&
        submit_state.duoview_shared_image && vr->is_duoview_renderer_active())
        ? uevr::mono::shared_projection_crop(*mono_crops[0], *mono_crops[1])
        : std::optional<uevr::mono::ProjectionCrop>{};
    if (submit_state.duoview_shared_image && !shared_crop) {
        SPDLOG_WARNING_EVERY_N_SEC(5, "[DuoView][v208] Shared-eye frame without a valid union crop; not submitted");
    } else if (shared_crop) {
        SPDLOG_INFO_EVERY_N_SEC(10, "[DuoView][v208] Same image for both eyes: rect {}x{} at ({},{}) tan L{:.3f} R{:.3f} U{:.3f} D{:.3f}",
            shared_crop->width, shared_crop->height, shared_crop->x, shared_crop->y,
            shared_crop->fov[0], shared_crop->fov[1], shared_crop->fov[2], shared_crop->fov[3]);
    }
    const auto debug_submit_empty = this->debug_submit_empty_frame->value();
''', label="shared crop")
# A shared frame never falls back to separate halves: its right half is stale.
replace(XR, "        (!mono || (mono_projection && mono_crops[0] && mono_crops[1]))) {\n",
        "        (!mono || (mono_projection && mono_crops[0] && mono_crops[1])) &&\n"
        "        (!submit_state.duoview_shared_image || shared_crop)) {\n", label="submit gate")
replace(XR, "            if (mono_projection) {\n"
            "                const auto& crop = *mono_crops[i];\n"
            "                const int eye_width = swapchain->width / 2;\n"
            "                offset_x = static_cast<int>(crop.x) + static_cast<int>(i) * eye_width;\n",
        "            if (mono_projection) {\n"
        "                const auto& crop = shared_crop ? *shared_crop : *mono_crops[i];\n"
        "                const int eye_width = swapchain->width / 2;\n"
        "                offset_x = static_cast<int>(crop.x) + (shared_crop ? 0 : static_cast<int>(i) * eye_width);\n",
        label="per-view rect")
replace(XR, "                    const float shift = interp * (tr - tl);\n",
        "                    // v208: keep the v207 shift size: scale by this eye's own\n"
        "                    // crop width, not by the wider shared rectangle.\n"
        "                    const float span = shared_crop ? (mono_crops[i]->fov[1] - mono_crops[i]->fov[0]) : (tr - tl);\n"
        "                    const float shift = interp * span;\n", label="alignment span")
replace(XR, "            if (duoview_holding) ++duoview_hold_submits;\n"
            "            else ++duoview_copy_submits;\n",
        "            if (duoview_holding) ++duoview_hold_submits;\n"
        "            else ++duoview_copy_submits;\n"
        "            vr->note_duoview_shared_submit(shared_crop.has_value());\n", label="submit note")

# ------------------------------------------------------------------ D3D12
D12 = "src/mods/vr/D3D12Component.cpp"
replace(D12, "#include <d3dcompiler.h>\n", "#include <d3dcompiler.h>\n#include <dxgi1_4.h>\n")
replace(D12, "vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {\n", r'''// v208: live video-memory readout for DuoView, once per second. Uses the game
// swap chain's own DXGI factory (no new factory, no proxy-DLL interaction).
static void sample_duoview_vram(VR* vr) {
    static std::chrono::steady_clock::time_point next_sample{};
    static Microsoft::WRL::ComPtr<IDXGIAdapter3> adapter{};
    static LUID adapter_luid{};
    const auto now = std::chrono::steady_clock::now();
    if (vr == nullptr || now < next_sample) { return; }
    next_sample = now + std::chrono::seconds(1);
    auto& hook = g_framework->get_d3d12_hook();
    if (hook == nullptr) { return; }
    auto* device = hook->get_device();
    auto* swap_chain = hook->get_swap_chain();
    if (device == nullptr || swap_chain == nullptr) { return; }
    const auto luid = device->GetAdapterLuid();
    if (adapter == nullptr || luid.LowPart != adapter_luid.LowPart || luid.HighPart != adapter_luid.HighPart) {
        adapter.Reset();
        Microsoft::WRL::ComPtr<IDXGIFactory4> factory{};
        if (FAILED(swap_chain->GetParent(IID_PPV_ARGS(&factory))) || factory == nullptr ||
            FAILED(factory->EnumAdapterByLuid(luid, IID_PPV_ARGS(&adapter))) || adapter == nullptr) {
            adapter.Reset();
            SPDLOG_WARNING_EVERY_N_SEC(30, "[DuoView][VRAM] DXGI adapter query unavailable");
            return;
        }
        adapter_luid = luid;
    }
    DXGI_QUERY_VIDEO_MEMORY_INFO local{}, system{};
    if (FAILED(adapter->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_LOCAL, &local))) { return; }
    if (FAILED(adapter->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_NON_LOCAL, &system))) { system = {}; }
    vr->note_duoview_vram(local.CurrentUsage, local.Budget, system.CurrentUsage);
    if (vr->is_using_duoview_mono()) {
        SPDLOG_INFO_EVERY_N_SEC(10, "[DuoView][VRAM] game process: {} MB used / {} MB budget; in system memory {} MB",
            local.CurrentUsage >> 20, local.Budget >> 20, system.CurrentUsage >> 20);
    }
}

// v208: report how many XR command slots share how many compose textures.
static void log_duoview_compose_sharing(
    const std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>>& compositors) {
    std::unordered_set<ID3D12Resource*> textures{};
    size_t slots = 0;
    for (const auto& [commands, compositor] : compositors) {
        if (!compositor || compositor->output_resource() == nullptr) { continue; }
        ++slots;
        textures.insert(compositor->output_resource());
    }
    SPDLOG_INFO("[DuoView][v208] {} XR command slot(s) share {} Mono compose texture(s)", slots, textures.size());
}

vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {
''', label="on_frame")
replace(D12, "    m_last_on_frame = std::chrono::steady_clock::now();\n",
        "    m_last_on_frame = std::chrono::steady_clock::now();\n    sample_duoview_vram(vr);\n")
replace(D12, "                                pose.duoview_serial=packet->serial;\n",
        "                                pose.duoview_serial=packet->serial;\n"
        "                                pose.duoview_shared_image=packet_frame->config.settings.shared_eye_image;\n")
replace(D12, "            SPDLOG_INFO(\"[DuoView][Activation] Prepared {}/{} OpenXR command slots on ID6 entry\",\n"
             "                prepared, it->second.texture_contexts.size());\n",
        "            SPDLOG_INFO(\"[DuoView][Activation] Prepared {}/{} OpenXR command slots on ID6 entry\",\n"
        "                prepared, it->second.texture_contexts.size());\n"
        "            log_duoview_compose_sharing(m_openxr.duoview_compositors);\n", label="activation log")
replace(D12, "                if (!comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), duo_srgb, duo_frequency)) {\n"
             "                    SPDLOG_WARNING_EVERY_N_SEC(2,\n"
             "                        \"[DuoView] DX12 prewarm failed; guarded compositing/fallback remains available\");\n"
             "                }\n"
             "            }\n",
        "                if (!comp->prewarm(device, vr->get_hmd_width(), vr->get_hmd_height(), duo_srgb, duo_frequency)) {\n"
        "                    SPDLOG_WARNING_EVERY_N_SEC(2,\n"
        "                        \"[DuoView] DX12 prewarm failed; guarded compositing/fallback remains available\");\n"
        "                }\n"
        "            }\n"
        "            log_duoview_compose_sharing(this->duoview_compositors);\n", label="swapchain prewarm log")
replace(D12, "    this->duoview_compositors.clear();\n",
        "    this->duoview_compositors.clear();\n    uevr::duoview::dx12::release_shared_output();\n",
        count=2, label="release shared output")

# ------------------------------------------------------------------- VR
VRH = "src/mods/VR.hpp"
replace(VRH, "    const ModToggle::Ptr m_duo_sharp_periphery{ModToggle::create(generate_name(\"DuoViewSharpPeriphery\"), true)};\n",
        "    const ModToggle::Ptr m_duo_sharp_periphery{ModToggle::create(generate_name(\"DuoViewSharpPeriphery\"), true)};\n"
        "    const ModToggle::Ptr m_duo_shared_eye{ModToggle::create(generate_name(\"DuoViewSameImageBothEyes\"), false)};\n"
        "    std::atomic<uint64_t> m_duo_vram_used{}, m_duo_vram_budget{}, m_duo_vram_system{};\n"
        "    std::atomic<int32_t> m_duo_shared_submitted{-1};\n")
replace(VRH, "            *m_duo_sharp_periphery,\n", "            *m_duo_sharp_periphery,\n            *m_duo_shared_eye,\n")
replace(VRH, "    void note_duoview_source_extents(uint64_t packed) {\n"
             "        m_duoview_source_extents.store(packed,std::memory_order_relaxed);\n"
             "    }\n",
        "    void note_duoview_source_extents(uint64_t packed) {\n"
        "        m_duoview_source_extents.store(packed,std::memory_order_relaxed);\n"
        "    }\n"
        "    void note_duoview_vram(uint64_t used, uint64_t budget, uint64_t system) { // v208\n"
        "        m_duo_vram_used.store(used,std::memory_order_relaxed);\n"
        "        m_duo_vram_budget.store(budget,std::memory_order_relaxed);\n"
        "        m_duo_vram_system.store(system,std::memory_order_relaxed);\n"
        "    }\n"
        "    void note_duoview_shared_submit(bool shared) { // v208\n"
        "        m_duo_shared_submitted.store(shared ? 1 : 0,std::memory_order_relaxed);\n"
        "    }\n")

VRC = "src/mods/VR.cpp"
replace(VRC, "        .sharp_periphery=m_duo_sharp_periphery->value()};\n",
        "        .sharp_periphery=m_duo_sharp_periphery->value(),\n"
        "        .shared_eye_image=m_duo_shared_eye->value()};\n")
replace(VRC, "        current.sharp_periphery==candidate.sharp_periphery) return;\n",
        "        current.sharp_periphery==candidate.sharp_periphery &&\n"
        "        current.shared_eye_image==candidate.shared_eye_image) return;\n")
replace(VRC, "                ImGui::TextWrapped(\"OFF composes once and copies to both eyes. ON blends both eye halves directly when formats match. Compare GPU timing in the same scene; either route may be faster.\");\n",
        "                ImGui::TextWrapped(\"OFF composes once and copies to both eyes. ON blends both eye halves directly when formats match. Compare GPU timing in the same scene; either route may be faster.\");\n"
        r'''                m_duo_shared_eye->draw("Same image for both eyes (v208)");
                ImGui::TextWrapped("ON: both eyes are given the same rectangle of the XR image, so the second eye copy is skipped and a mono-aware VectorXR runs frame generation once. OFF: exact v207 output.");
                {
                    const auto shared_submitted=m_duo_shared_submitted.load(std::memory_order_relaxed);
                    if (shared_submitted >= 0)
                        ImGui::Text("Last XR submit: %s", shared_submitted ? "same image for both eyes" : "separate eye halves (v207)");
                    const auto vram_used=m_duo_vram_used.load(std::memory_order_relaxed);
                    const auto vram_budget=m_duo_vram_budget.load(std::memory_order_relaxed);
                    const auto vram_system=m_duo_vram_system.load(std::memory_order_relaxed);
                    if (vram_budget)
                        ImGui::Text("Video memory (whole game process): %.0f MB used / %.0f MB budget (%.0f%%); in system memory %.0f MB",
                            vram_used/1048576.0, vram_budget/1048576.0, 100.0*vram_used/vram_budget, vram_system/1048576.0);
                    else ImGui::TextUnformatted("Video memory: waiting for the first DXGI reading");
                }
''', label="menu")

for rel, text in files.items():
    (root / rel).write_text(text, encoding="utf-8", newline="")
print("v208 applied: same-image-both-eyes toggle (default OFF), shared compose texture, VRAM readout;"
      f" {len(files)} files edited")

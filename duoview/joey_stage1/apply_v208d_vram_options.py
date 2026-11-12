#!/usr/bin/env python3
"""v208d: optional VRAM saving + one diagnostic. Applies AFTER v208b.

1. Menu toggle "DuoViewSkipDepthSwapchain" (default OFF = byte-for-byte the old
   behaviour). When ON and DuoView ID6 is the active renderer, PassDepthToRuntime
   is OFF, and neither AFR nor the DIBR preview is active, the OpenXR DEPTH
   swapchain (2W x H, D32_FLOAT_S8X24, never written or submitted in DuoView) is
   not created. Read only inside create_swapchains(), so it applies after
   "Reinitialize Runtime" or a restart. If depth later becomes needed, the
   existing on-frame depth recreate path builds the chain (made_depth_with_null_defaults
   is set while it is skipped). All other consumers already use contains()/find()
   or the copy() existence check.
2. Diagnostic only: log + menu line when the Native gather atlas is allocated.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_v208d_vram_options.py <backend>")
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
        raise SystemExit(f"v208d anchor mismatch in {rel} ({label or old[:60]!r}): found {found}, expected {count}")
    files[rel] = text.replace(old, new)


VRH = "src/mods/VR.hpp"
replace(VRH, '    const ModToggle::Ptr m_duo_shared_eye{ModToggle::create(generate_name("DuoViewSameImageBothEyes"), false)};\n',
        '    const ModToggle::Ptr m_duo_shared_eye{ModToggle::create(generate_name("DuoViewSameImageBothEyes"), false)};\n'
        '    const ModToggle::Ptr m_duo_skip_depth{ModToggle::create(generate_name("DuoViewSkipDepthSwapchain"), false)};\n',
        label="declare toggle")
replace(VRH, "            *m_duo_shared_eye,\n",
        "            *m_duo_shared_eye,\n            *m_duo_skip_depth,\n", label="persisted list")
replace(VRH, "    bool is_depth_enabled() const {\n        return !is_using_mono() && m_enable_depth->value();\n    }\n",
        "    bool is_depth_enabled() const {\n        return !is_using_mono() && m_enable_depth->value();\n    }\n\n"
        "    // v208d: true only when the OpenXR depth swapchain is certainly unused\n"
        "    // (DuoView ID6 active, no depth pass-through, no AFR, no DIBR preview).\n"
        "    bool should_skip_unused_depth_swapchain() const {\n"
        "        return m_duo_skip_depth->value() && is_duoview_renderer_active() &&\n"
        "            !m_enable_depth->value() && !is_depth_enabled() &&\n"
        "            !is_using_afr() && !is_dibr_preview_active();\n"
        "    }\n", label="skip predicate")

VRC = "src/mods/VR.cpp"
replace(VRC, "m_duo_shared_eye->value()=false; // v208\n",
        "m_duo_shared_eye->value()=false; // v208\n                    m_duo_skip_depth->value()=false; // v208d\n",
        label="restore defaults")
replace(VRC, 'ImGui::TextWrapped("ON: both eyes are given the same rectangle of the XR image, so the second eye copy is skipped and a mono-aware VectorXR runs frame generation once. OFF: exact v207 output.");\n',
        'ImGui::TextWrapped("ON: both eyes are given the same rectangle of the XR image, so the second eye copy is skipped and a mono-aware VectorXR runs frame generation once. OFF: exact v207 output.");\n'
        '                m_duo_skip_depth->draw("Skip unused depth swapchain (saves VRAM; applies after Reinitialize Runtime / restart)");\n',
        label="draw toggle")
replace(VRC, '                    output_path ? "direct double-wide raster" : "composite and copy compatibility route");\n',
        '                    output_path ? "direct double-wide raster" : "composite and copy compatibility route");\n'
        '                ImGui::Text("Gather atlas allocated (since start): %s", uevr::duoview::dx12::gather_atlas_allocated_flag().load(std::memory_order_relaxed) ? "yes" : "no");\n',
        label="atlas menu line")

DVH = "src/mods/vr/DuoViewD3D12.hpp"
replace(DVH, "#include <memory>\n#include <mutex>\n#include <string>\n\nnamespace uevr::duoview::dx12 {\n",
        "#include <atomic>\n#include <cstdint>\n#include <memory>\n#include <mutex>\n#include <string>\n"
        "// v208d: the standalone DX12 warp tests include this header without spdlog on their include path.\n"
        "#if __has_include(<spdlog/spdlog.h>)\n#include <spdlog/spdlog.h>\n"
        '#define DUOVIEW_V208D_LOG_ATLAS(mib) spdlog::info("[DuoView][VRAM] Native gather atlas ALLOCATED ({} MiB)", (mib))\n'
        "#else\n#define DUOVIEW_V208D_LOG_ATLAS(mib) ((void)(mib))\n#endif\n\nnamespace uevr::duoview::dx12 {\n"
        "// v208d: diagnostic only. Function-local static avoids ODR/duplicate-definition issues.\n"
        "inline std::atomic<bool>& gather_atlas_allocated_flag() { static std::atomic<bool> flag{false}; return flag; }\n",
        label="atlas flag")
replace(DVH, '        atlas_->SetName(L"DuoView::NativeGatherAtlasFallback");\n        return true;\n',
        '        atlas_->SetName(L"DuoView::NativeGatherAtlasFallback");\n'
        '        gather_atlas_allocated_flag().store(true, std::memory_order_relaxed);\n'
        '        DUOVIEW_V208D_LOG_ATLAS((static_cast<uint64_t>(width_) * 2 * height_ * 4) / (1024ull * 1024ull));\n'
        '        return true;\n', label="atlas log")

D3D = "src/mods/vr/D3D12Component.cpp"
replace(D3D, "    // Depth textures\n    if (vr->get_openxr_runtime()->is_depth_allowed()) {\n",
        "    // v208d: optional (default OFF) - skip the depth swapchain when DuoView certainly never uses it.\n"
        "    const bool skip_unused_depth_swapchain =\n"
        "        vr->get_openxr_runtime()->is_depth_allowed() && vr->should_skip_unused_depth_swapchain();\n"
        "    if (skip_unused_depth_swapchain) {\n"
        "        // Lets the existing on-frame recreate path build the chain if depth is needed later.\n"
        "        this->made_depth_with_null_defaults = true;\n"
        '        spdlog::info("[DuoView][VRAM] depth swapchain skipped (toggle ON; saves roughly {} MiB per image)",\n'
        "            (static_cast<uint64_t>(vr->get_hmd_width()) * 2 * vr->get_hmd_height() * 8) / (1024ull * 1024ull));\n"
        "    }\n\n"
        "    // Depth textures\n    if (!skip_unused_depth_swapchain && vr->get_openxr_runtime()->is_depth_allowed()) {\n",
        label="skip depth")

for rel, text in files.items():
    (root / rel).write_text(text, encoding="utf-8", newline="")
print(f"v208d applied: optional depth-swapchain skip toggle + gather atlas diagnostic; {len(files)} files edited")

#!/usr/bin/env python3
"""Build 49: preserve Build48 Mono Eye Alignment across OpenXR Reset Runtime.

Root cause: VR::reinitialize_openxr() destroys m_openxr (including its
ModToggle and ModSlider). initialize_openxr() makes a fresh object, but the
reinitialization path does not perform on_config_load() again.

Fix: capture the two calibrated OpenXR option values immediately before
destroying the runtime, then restore them to the new instance before returning.
No Render/SteamVR/OpenXR projection code, UI/overlay, shader, or DLL ABI changes.
"""
import argparse
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument("backend",type=Path)
args=p.parse_args()
path=args.backend/"src/mods/VR.hpp"
s=path.read_text(encoding="utf-8-sig")
old="""    std::optional<std::string> reinitialize_openxr() {
        spdlog::info("Reinitializing OpenXR");
        std::scoped_lock _{m_openvr_mtx};

        if (m_is_d3d12) {
            m_d3d12.openxr().destroy_swapchains();
        } else {
            m_d3d11.openxr().destroy_swapchains();
        }

        m_openxr.reset();
        m_runtime.reset();
        m_runtime = std::make_shared<VRRuntime>();
        
        m_controllers.clear();
        m_controllers_set.clear();

        auto e = initialize_openxr();

        if (e) {
            spdlog::error("Failed to reinitialize OpenXR: {}", *e);
        }

        return e;
    }"""
new="""    std::optional<std::string> reinitialize_openxr() {
        spdlog::info("Reinitializing OpenXR");
        std::scoped_lock _{m_openvr_mtx};

        // Build 49: OpenXR Reset Runtime constructs a NEW OpenXR object.
        // Preserve the user's live binocular calibration across that
        // replacement. Loading config.txt does NOT run on this reset path.
        const bool saved_mono_eye_alignment_enabled =
            m_openxr != nullptr && m_openxr->mono_eye_alignment_enabled->value();
        const float saved_mono_eye_alignment_percent =
            m_openxr != nullptr ? m_openxr->mono_eye_alignment_percent->value() : 0.0f;

        if (m_is_d3d12) {
            m_d3d12.openxr().destroy_swapchains();
        } else {
            m_d3d11.openxr().destroy_swapchains();
        }

        m_openxr.reset();
        m_runtime.reset();
        m_runtime = std::make_shared<VRRuntime>();

        m_controllers.clear();
        m_controllers_set.clear();

        auto e = initialize_openxr();

        // Restore BOTH the value and toggle, including when switching modes
        // before the reset. Never alter a Mono projection or any GPU resource.
        // Validate range defensively: invalid values reset safely to zero.
        if (m_openxr != nullptr) {
            const bool valid_percent =
                std::isfinite(saved_mono_eye_alignment_percent) &&
                saved_mono_eye_alignment_percent >= -3.0f &&
                saved_mono_eye_alignment_percent <= 3.0f;
            m_openxr->mono_eye_alignment_percent->value() =
                valid_percent ? saved_mono_eye_alignment_percent : 0.0f;
            m_openxr->mono_eye_alignment_enabled->value() =
                valid_percent && saved_mono_eye_alignment_enabled;
            spdlog::info("[OpenXR] Restored Mono Eye Alignment after runtime reset: enabled={}, total_percent={:.4f}",
                m_openxr->mono_eye_alignment_enabled->value(),
                m_openxr->mono_eye_alignment_percent->value());
        }

        if (e) {
            spdlog::error("Failed to reinitialize OpenXR: {}", *e);
        }

        return e;
    }"""
if s.count(old)!=1:
    raise RuntimeError(f"OpenXR reset lifecycle anchor changed: {s.count(old)}")
if "saved_mono_eye_alignment_percent" in s:
    raise RuntimeError("Build 49 already applied")
s=s.replace(old,new,1)
path.write_text(s,encoding="utf-8",newline="")
print("Build49: restored Mono Eye Alignment toggle + percent after OpenXR reset; VR.hpp only.")

#!/usr/bin/env python3
"""Tri-view B12: do not allocate the OpenXR depth swapchain for TriView.

UEVR creates a double-wide D32S8 depth swapchain (3 images: 2W x H x 8 B each)
whenever the runtime allows depth, but ID7 never submits depth
(VR::is_depth_enabled() is false for ID7). 240 MiB at 2568x2040 per eye,
768 MiB at 4096x4096. Swapchains are created while the autostart warm-up still
runs Native Stereo, so the test also covers a requested/warming-up ID7.
A missing depth swapchain is already handled (OpenXR has_depth=false).
Run after apply_triview_autostart.py.
"""
from pathlib import Path
import sys


def once(text, old, new, what):
    if text.count(old) != 1:
        raise RuntimeError(f"vram anchor ({what}) count {text.count(old)}")
    return text.replace(old, new, 1)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_triview_vram.py <backend>")
    root = Path(sys.argv[1])
    hpp, cpp = root / "src/mods/VR.hpp", root / "src/mods/vr/D3D12Component.cpp"
    h = once(hpp.read_text(encoding="utf-8"),
        "    bool is_depth_enabled() const {\n",
        "    // Tri-view B12: TriView (active, requested or warming up) never submits XR depth.\n"
        "    bool triview_skips_xr_depth() const {\n"
        "        return is_quadview_mode_selected() || requested_rendering_method() == RenderingMethod::QUAD_VIEWS_STEREO ||\n"
        "            m_triview_autostart_stage == 1 || m_triview_autostart_stage == 2;\n"
        "    }\n\n"
        "    bool is_depth_enabled() const {\n", "VR depth helper")
    c = once(cpp.read_text(encoding="utf-8"),
        "    if (vr->get_openxr_runtime()->is_depth_allowed()) {\n"
        "        // Even when using AFR, the depth tex is always the size of a double wide.\n",
        "    if (vr->triview_skips_xr_depth() && vr->get_openxr_runtime()->is_depth_allowed()) {\n"
        "        spdlog::info(\"[TriView][VRAM] OpenXR depth swapchain not created (TriView never submits depth)\");\n"
        "    }\n"
        "    if (vr->get_openxr_runtime()->is_depth_allowed() && !vr->triview_skips_xr_depth()) {\n"
        "        // Even when using AFR, the depth tex is always the size of a double wide.\n", "depth swapchain")
    hpp.write_text(h, encoding="utf-8"); cpp.write_text(c, encoding="utf-8")
    print("Tri-view B12: OpenXR depth swapchain skipped in TriView")


if __name__ == "__main__":
    main()

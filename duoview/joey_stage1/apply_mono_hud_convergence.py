#!/usr/bin/env python3
"""Add an opt-in, single-quad Mono HUD convergence distance to Joey.

Based on stable v186.1 Glamayre + Build 45 Foreground MPC. Only the original
OpenXR *game HUD* QUAD gets a new effective physical depth/size when enabled:
- same one XR_EYE_VISIBILITY_BOTH layer, same UI swapchain,
- apparent angular size AND angular offsets remain unchanged,
- built-in controller ray hit test uses the *effective* geometry,
- disabled paths are byte-for-byte the original Joey overlay logic,
- stock stereo, AFR, other layer types, framework UI, SteamVR remain untouched.

The old dual-eye-layer convergence experiment is deliberately NOT used.
"""
from pathlib import Path
import argparse

HEADER_SETTINGS_OLD = '''    const ModSlider::Ptr m_slate_size{ ModSlider::create("UI_Size", 0.5f, 10.0f, 2.0f) };
'''
HEADER_SETTINGS_NEW = HEADER_SETTINGS_OLD + '''    // Build 45 HUD-only experiment: default OFF, Mono ID5 / DuoView ID6.
    const ModToggle::Ptr m_mono_hud_convergence{ ModToggle::create("UI_MonoHudConvergence", false) };
    const ModSlider::Ptr m_mono_hud_optical_distance{
        ModSlider::create("UI_MonoHudOpticalDistance", 2.0f, 200.0f, 100.0f) };
'''
HEADER_OPTIONS_OLD = '''            *m_ui_follows_view,
            *m_ui_invert_alpha,
'''
HEADER_OPTIONS_NEW = '''            *m_ui_follows_view,
            *m_mono_hud_convergence,
            *m_mono_hud_optical_distance,
            *m_ui_invert_alpha,
'''
MENU_OLD = '''        m_ui_follows_view->draw("UI Follows View");
        m_ui_invert_alpha->draw("UI Invert Alpha");
'''
MENU_NEW = '''        m_ui_follows_view->draw("UI Follows View");
        if (VR::get()->get_runtime()->is_openxr() && VR::get()->is_using_mono()) {
            m_mono_hud_convergence->draw("Mono HUD Optical Convergence (experimental)");
            if (m_mono_hud_convergence->value()) {
                m_mono_hud_optical_distance->draw("Mono HUD Optical Distance (m)");
                ImGui::TextWrapped("One shared OpenXR quad. Moves the HUD farther away while "
                    "preserving its apparent size and offset. 100 m nearly removes stereo depth. "
                    "Requires UI Follows View, Quad overlay, and runtime-layer UI composition.");
                if (!m_ui_follows_view->value() ||
                    (OverlayType)m_slate_overlay_type->value() != OverlayType::QUAD ||
                    (get_ui_composition_request() & 1) != 0) {
                    ImGui::TextWrapped("Convergence INACTIVE: enable UI Follows View, "
                        "select Quad overlay, and use Runtime layers for UI Composition.");
                }
            }
        }
        m_ui_invert_alpha->draw("UI Invert Alpha");
'''

QUAD_OLD = '''    const auto size_meters = m_parent->m_slate_size->value();
    const auto meters_w = (float)ui_swapchain.width / (float)ui_swapchain.height * size_meters;
    const auto meters_h = size_meters;
    layer.size = {meters_w, meters_h};

    glm_matrix[3] -= glm_matrix[2] * m_parent->m_slate_distance->value();
    glm_matrix[3] += m_parent->m_slate_x_offset->value() * glm_matrix[0];
    glm_matrix[3] += m_parent->m_slate_y_offset->value() * glm_matrix[1];
    glm_matrix[3].w = 1.0f;
'''
QUAD_NEW = '''    // Mono game HUD convergence: keep Joey's single BOTH-eye OpenXR quad.
    // A mono world has no scene parallax; a HUD at finite depth can split
    // into separate reticles when both eyes focus on the mono image.
    // Move the quad along the same view ray and enlarge it proportionally.
    // When disabled, all original geometry is mathematically identical.
    const float configured_distance = m_parent->m_slate_distance->value();
    const float requested_optical_distance = m_parent->m_mono_hud_optical_distance->value();
    const bool mono_hud_optical =
        eye == XR_EYE_VISIBILITY_BOTH &&
        swapchain == runtimes::OpenXR::SwapchainIndex::UI &&
        !force_stage_space && follows_view &&
        vr->is_using_mono() &&
        (m_parent->get_ui_composition_request() & 1) == 0 &&
        (OverlayComponent::OverlayType)m_parent->m_slate_overlay_type->value() == OverlayComponent::OverlayType::QUAD &&
        m_parent->m_mono_hud_convergence->value() &&
        std::isfinite(configured_distance) && configured_distance >= 0.5f &&
        std::isfinite(requested_optical_distance) &&
        requested_optical_distance >= 2.0f && requested_optical_distance <= 200.0f;

    const float optical_scale = mono_hud_optical
        ? requested_optical_distance / configured_distance : 1.0f;
    const float optical_distance = mono_hud_optical
        ? requested_optical_distance : configured_distance;

    const float size_meters = m_parent->m_slate_size->value() * optical_scale;
    const auto meters_w = (float)ui_swapchain.width / (float)ui_swapchain.height * size_meters;
    const auto meters_h = size_meters;
    layer.size = {meters_w, meters_h};

    glm_matrix[3] -= glm_matrix[2] * optical_distance;
    glm_matrix[3] += (m_parent->m_slate_x_offset->value() * optical_scale) * glm_matrix[0];
    glm_matrix[3] += (m_parent->m_slate_y_offset->value() * optical_scale) * glm_matrix[1];
    glm_matrix[3].w = 1.0f;
'''

def once(text: str, old: str, new: str, label: str):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected ONE unchanged Joey source anchor, got {count}")
    return text.replace(old, new, 1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", type=Path)
    args = parser.parse_args()
    root = args.backend / "src/mods/vr"
    header = root / "OverlayComponent.hpp"
    cpp = root / "OverlayComponent.cpp"
    h = header.read_text(encoding="utf-8-sig")
    c = cpp.read_text(encoding="utf-8-sig")
    if "UI_MonoHudConvergence" in h or "mono_hud_optical" in c:
        raise RuntimeError("Mono HUD optical convergence already patched")
    h = once(h, HEADER_SETTINGS_OLD, HEADER_SETTINGS_NEW, "settings")
    h = once(h, HEADER_OPTIONS_OLD, HEADER_OPTIONS_NEW, "option persistence")
    c = once(c, MENU_OLD, MENU_NEW, "on-screen Mono HUD controls")
    c = once(c, QUAD_OLD, QUAD_NEW, "single-quad OpenXR HUD geometry")
    # The only writes are the two original Joey overlay files.
    header.write_text(h, encoding="utf-8", newline="")
    cpp.write_text(c, encoding="utf-8", newline="")
    print("Mono HUD convergence: one BOTH-eye quad, proportional size/offset, default OFF.")

if __name__ == "__main__":
    main()

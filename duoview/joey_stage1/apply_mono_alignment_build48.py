#!/usr/bin/env python3
"""Build 48: repair opt-in HUD convergence in both mono modes; add zero-cost Mono presentation alignment.
Apply AFTER Build47 apply_mono_hud_convergence.py. Changes only OverlayComponent.cpp and OpenXR.cpp/.hpp.
No GPU copies, no scene, fovea, shaders, timing or compositor layer changes.
"""
import argparse
from pathlib import Path

def once(text, old, new, label):
    n=text.count(old)
    if n!=1: raise RuntimeError(f"{label}: expected ONE anchor, got {n}")
    return text.replace(old,new,1)

p=argparse.ArgumentParser()
p.add_argument("backend",type=Path)
a=p.parse_args()
base=a.backend/"src/mods/vr"
cpp=base/"OverlayComponent.cpp"
h=base/"runtimes/OpenXR.hpp"
xr=base/"runtimes/OpenXR.cpp"
s=cpp.read_text(encoding="utf-8")
s=once(s,
'''                    "Requires UI Follows View, Quad overlay, and runtime-layer UI composition.");''',
'''                    "Works with UI Follows View ON/OFF and Mono ID5/DuoView ID6. "
                    "Applies to the game OpenXR Quad or Cylinder layer (including per-eye composition).");''',
"HUD help")
s=once(s,
'''                if (!m_ui_follows_view->value() ||
                    (OverlayType)m_slate_overlay_type->value() != OverlayType::QUAD ||
                    (get_ui_composition_request() & 1) != 0) {
                    ImGui::TextWrapped("Convergence INACTIVE: enable UI Follows View, "
                        "select Quad overlay, and use Runtime layers for UI Composition.");
                }''',
'''                ImGui::TextWrapped("No follows-view or per-eye-composition restrictions. "
                    "If the reticle is in the scene texture instead of the game UI layer, "
                    "this HUD-only setting cannot move it.");''',
"HUD inactive gates")
s=once(s,
'''        eye == XR_EYE_VISIBILITY_BOTH &&
        swapchain == runtimes::OpenXR::SwapchainIndex::UI &&
        !force_stage_space && follows_view &&
        vr->is_using_mono() &&
        (m_parent->get_ui_composition_request() & 1) == 0 &&
        (OverlayComponent::OverlayType)m_parent->m_slate_overlay_type->value() == OverlayComponent::OverlayType::QUAD &&
        m_parent->m_mono_hud_convergence->value() &&''',
'''        (swapchain == runtimes::OpenXR::SwapchainIndex::UI ||
         swapchain == runtimes::OpenXR::SwapchainIndex::UI_RIGHT) &&
        !vr->is_using_2d_screen() &&
        vr->is_using_mono() &&
        m_parent->m_mono_hud_convergence->value() &&''',
"HUD all original OpenXR quad modes")
# A cylinder layer uses a different projection primitive, but identical optical distance/scale.
cylinder_old='''    const auto size_meters = m_parent->m_slate_size->value();
    const auto meters_w = (float)ui_swapchain.width / (float)ui_swapchain.height * size_meters;
    const auto meters_h = size_meters;

    // OpenXR Docs:
'''
cylinder_new='''    // Preserve apparent height, angular width and offsets while changing
    // the cylinder optical distance. Includes stage-space and per-eye UI.
    const float configured_distance = m_parent->m_slate_distance->value();
    const float optical_request = m_parent->m_mono_hud_optical_distance->value();
    const bool mono_hud_optical = vr->is_using_mono() && !vr->is_using_2d_screen() &&
        (swapchain == runtimes::OpenXR::SwapchainIndex::UI ||
         swapchain == runtimes::OpenXR::SwapchainIndex::UI_RIGHT) &&
        m_parent->m_mono_hud_convergence->value() &&
        std::isfinite(configured_distance) && configured_distance >= 0.5f &&
        std::isfinite(optical_request) && optical_request >= 2.0f &&
        optical_request <= 200.0f;
    const float optical_scale = mono_hud_optical ? optical_request / configured_distance : 1.0f;
    const float optical_distance = mono_hud_optical ? optical_request : configured_distance;
    const auto size_meters = m_parent->m_slate_size->value() * optical_scale;
    const auto meters_w = (float)ui_swapchain.width / (float)ui_swapchain.height * size_meters;
    const auto meters_h = size_meters;

    // OpenXR Docs:
'''
s=once(s,cylinder_old,cylinder_new,"cylinder geometry")
s=once(s,'''    glm_matrix[3] -= glm_matrix[2] * m_parent->m_slate_distance->value();
    glm_matrix[3] += glm_matrix[2] * layer.radius;
    glm_matrix[3] += m_parent->m_slate_x_offset->value() * glm_matrix[0];
    glm_matrix[3] += m_parent->m_slate_y_offset->value() * glm_matrix[1];
''',
'''    glm_matrix[3] -= glm_matrix[2] * optical_distance;
    glm_matrix[3] += glm_matrix[2] * layer.radius;
    glm_matrix[3] += (m_parent->m_slate_x_offset->value() * optical_scale) * glm_matrix[0];
    glm_matrix[3] += (m_parent->m_slate_y_offset->value() * optical_scale) * glm_matrix[1];
''',"cylinder position")
cpp.write_text(s,encoding="utf-8",newline="")

s=h.read_text(encoding="utf-8")
s=once(s,
'''    const ModToggle::Ptr ignore_vd_checks{ ModToggle::create("OpenXR_IgnoreVirtualDesktopChecks", false) };''',
'''    // Live Mono ID5 / DuoView ID6 presentation calibration; disabled = exact Build 47.
    // Value is TOTAL interocular image shift in per-eye full-resolution pixels.
    const ModToggle::Ptr mono_eye_alignment_enabled{
        ModToggle::create("OpenXR_MonoEyeAlignmentEnabled", false) };
    const ModSlider::Ptr mono_eye_alignment_pixels{
        ModSlider::create("OpenXR_MonoEyeAlignmentTotalPixels", -512.0f, 512.0f, 0.0f) };
    const ModToggle::Ptr ignore_vd_checks{ ModToggle::create("OpenXR_IgnoreVirtualDesktopChecks", false) };''',
"eye alignment persisted controls")
s=once(s,
'''        *resolution_scale,
        *ignore_vd_checks,''',
'''        *resolution_scale,
        *mono_eye_alignment_enabled,
        *mono_eye_alignment_pixels,
        *ignore_vd_checks,''',
"eye alignment persistence")
h.write_text(s,encoding="utf-8",newline="")

s=xr.read_text(encoding="utf-8")
s=once(s,
'''        ImGui::Checkbox("Virtual Desktop Fix", &this->push_dummy_projection);

        ImGui::SameLine();''',
'''        ImGui::Checkbox("Virtual Desktop Fix", &this->push_dummy_projection);
        if (VR::get()->is_using_mono()) {
            mono_eye_alignment_enabled->draw("Mono Eye Alignment (presentation only)");
            if (mono_eye_alignment_enabled->value()) {
                mono_eye_alignment_pixels->draw("Total Horizontal Eye Shift (source px)");
                ImGui::TextWrapped("Positive shifts left-eye image RIGHT and right-eye image LEFT; "
                    "negative reverses. Full-resolution source-pixel units; up to +/-512 total. "
                    "Live change, zero resets; does not touch scene textures, source crops, "
                    "eye-tracking, pose, shaders, or SteamVR settings. For stationary calibration only.");
                if (ImGui::Button("Reset Mono Eye Shift to Zero")) {
                    mono_eye_alignment_pixels->value() = 0.0f;
                }
            }
        }

        ImGui::SameLine();''',
"eye alignment live UI")
# After existing Mono crop and FOV have been computed, modify only submitted
# horizontal projection tangents so the sampling shift is consistent with XR metadata.
# This does NOT edit pixels or create a second GPU pass.
anchor='''                projection_layer_views[i].fov = {std::atan(crop.fov[0]), std::atan(crop.fov[1]),
                    std::atan(crop.fov[2]), std::atan(crop.fov[3])};
            }
            
            // SPDLOG_INFO("image calc for eye '''
repl='''                projection_layer_views[i].fov = {std::atan(crop.fov[0]), std::atan(crop.fov[1]),
                    std::atan(crop.fov[2]), std::atan(crop.fov[3])};
            }
            // Mono present-time eye alignment. Source is already fused/copied:
            // DuoView fovea/periphery, gaze, Unreal view and GPU scene are untouched.
            // Shift the left eye to the right and right eye to the left when positive.
            // Apply the equivalent shift in projection-tangent space so SteamVR
            // still receives valid FOV metadata, not an unreported bitmap shift.
            // No additional OpenXR layer, pose change, GPU copy or reprojection flag.
            if (mono_projection && mono_crops[i] && mono_eye_alignment_enabled->value()) {
                const float total_px = mono_eye_alignment_pixels->value();
                const auto& fov = projection_layer_views[i].fov;
                const int crop_width = projection_layer_views[i].subImage.imageRect.extent.width;
                // Rect is filled below, so use the already-validated crop extent.
                const float source_width = static_cast<float>(mono_crops[i]->width);
                if (std::isfinite(total_px) && std::abs(total_px) <= 512.0f &&
                    source_width > 0.0f && std::abs(total_px) > 0.0001f) {
                    const float tl = std::tan(fov.angleLeft);
                    const float tr = std::tan(fov.angleRight);
                    const float interp = (i == 0 ? 0.5f : -0.5f) * total_px / source_width;
                    const float shift = interp * (tr - tl);
                    if (std::isfinite(shift) && (tr - tl) > 0.0f) {
                        projection_layer_views[i].fov.angleLeft = std::atan(tl + shift);
                        projection_layer_views[i].fov.angleRight = std::atan(tr + shift);
                    }
                }
            }

            // SPDLOG_INFO("image calc for eye '''
# Removing unused local expected compiler warning, Werror possibly.
repl=repl.replace('                const int crop_width = projection_layer_views[i].subImage.imageRect.extent.width;\n','')
s=once(s,anchor,repl,"Mono submit FOV alignment")
xr.write_text(s,encoding="utf-8",newline="")
print("Build48 patched: Quad & cylinder HUD, all mono modes/compositions, native present-only eye alignment (OFF/0 default).")

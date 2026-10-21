#!/usr/bin/env python3
"""Experiment: DuoView-only stereo convergence on an otherwise unchanged UI texture.

All source edits are exact-anchor and restricted to the pinned Joey backend.
No UI compositor pass, texture allocation, VR pose changes, or Mono scene changes.
"""
def apply(changed, edit):
    header="src/mods/vr/OverlayComponent.hpp"
    cpp="src/mods/vr/OverlayComponent.cpp"
    dx="src/mods/vr/D3D12Component.cpp"
    vr_cpp="src/mods/VR.cpp"

    edit(header,
'''    const ModSlider::Ptr m_slate_size{ ModSlider::create("UI_Size", 0.5f, 10.0f, 2.0f) };''',
'''    const ModSlider::Ptr m_slate_size{ ModSlider::create("UI_Size", 0.5f, 10.0f, 2.0f) };
    // DuoView-only: geometry stays at UI Distance/Size; convergence is independent.
    const ModToggle::Ptr m_duoview_convergence{ ModToggle::create("UI_DuoView_Convergence", false) };
    const ModSlider::Ptr m_duoview_convergence_reference{ ModSlider::create("UI_DuoView_ConvergenceReference", 0.5f, 20.0f, 2.0f) };
    const ModSlider::Ptr m_duoview_convergence_manual{ ModSlider::create("UI_DuoView_ConvergenceManualMetersPerEye", -0.25f, 0.25f, 0.0f) };
    std::atomic<uint64_t> m_duoview_convergence_frames{0};''')
    edit(header,
'''    uint64_t get_ui_composition_request() const { return m_ui_composition_request.load(std::memory_order_relaxed); }''',
'''    void draw_duoview_convergence_controls() {
        ImGui::TextUnformatted("OpenXR UI convergence (game HUD / crosshair)");
        m_duoview_convergence->draw("Enable DuoView UI convergence");
        if (m_duoview_convergence->value()) {
            m_duoview_convergence_reference->draw("UI convergence reference distance (m)");
            m_duoview_convergence_manual->draw("Manual convergence offset per eye (meters)");
            ImGui::TextWrapped("Use UI Distance 10, Size 10, Overlay Quad. Reference 2 tries the previous 2/2 alignment. If there is no change, sweep manual offset from -0.05 to +0.05.");
            if (!duoview_convergence_supported())
                ImGui::TextWrapped("NOT ACTIVE: Set OpenXR UI Overlay Type to Quad.");
            ImGui::Text("Eye-specific OpenXR quad pairs submitted: %llu",
                (unsigned long long)m_duoview_convergence_frames.load(std::memory_order_relaxed));
        }
    }
    void note_duoview_convergence_submitted() {
        m_duoview_convergence_frames.fetch_add(1,std::memory_order_relaxed);
    }
    bool duoview_convergence_enabled() const { return m_duoview_convergence->value(); }
    float duoview_convergence_reference() const { return m_duoview_convergence_reference->value(); }
    float duoview_convergence_manual() const { return m_duoview_convergence_manual->value(); }
    bool duoview_convergence_supported() const {
        return m_slate_overlay_type->value() == static_cast<int32_t>(OverlayType::QUAD) &&
            (get_ui_composition_request() & 1) == 0;
    }
    uint64_t get_ui_composition_request() const { return m_ui_composition_request.load(std::memory_order_relaxed); }''')
    edit(header,
'''            *m_slate_size,
            *m_slate_cylinder_angle,''',
'''            *m_slate_size,
            *m_duoview_convergence,
            *m_duoview_convergence_reference,
            *m_duoview_convergence_manual,
            *m_slate_cylinder_angle,''')
    edit(cpp,
'''        m_slate_distance->draw("UI Distance");
        m_slate_size->draw("UI Size");
        m_ui_follows_view->draw("UI Follows View");''',
'''        m_slate_distance->draw("UI Distance");
        m_slate_size->draw("UI Size");
        m_ui_follows_view->draw("UI Follows View");
        if (VR::get()->is_duoview_renderer_active())
            draw_duoview_convergence_controls();''')
    edit(cpp,
'''    glm_matrix[3] -= glm_matrix[2] * m_parent->m_slate_distance->value();
    glm_matrix[3] += m_parent->m_slate_x_offset->value() * glm_matrix[0];
    glm_matrix[3] += m_parent->m_slate_y_offset->value() * glm_matrix[1];
    glm_matrix[3].w = 1.0f;

    layer.pose.orientation = runtimes::OpenXR::to_openxr(glm::quat_cast(glm_matrix));''',
'''    glm_matrix[3] -= glm_matrix[2] * m_parent->m_slate_distance->value();
    glm_matrix[3] += m_parent->m_slate_x_offset->value() * glm_matrix[0];
    glm_matrix[3] += m_parent->m_slate_y_offset->value() * glm_matrix[1];
    glm_matrix[3].w = 1.0f;

    // Monoscopic scene uses a centered optical origin; a normal OpenXR UI quad
    // instead converges according to its physical distance. Only when BOTH
    // halves are submitted do we shift their poses symmetrically, in view-space.
    // Standard OpenXR view coordinates: left eye is -X, right is +X.
    // At D=10m, reference=2m, eye shift = +/- 2*half-IPD.
    if (vr->is_duoview_renderer_active() &&
        m_parent->duoview_convergence_enabled() && m_parent->duoview_convergence_supported() &&
        (eye == XR_EYE_VISIBILITY_LEFT || eye == XR_EYE_VISIBILITY_RIGHT)) {
        const float distance = m_parent->m_slate_distance->value();
        const float reference = m_parent->duoview_convergence_reference();
        const auto submit = vr->m_openxr->get_submit_state();
        float half_shift = 0.0f;
        if (std::isfinite(distance) && distance > 0.0f &&
            std::isfinite(reference) && reference >= 0.5f && reference <= 20.0f &&
            submit.stage_views.size() == 2) {
            const auto& l = submit.stage_views[0].pose.position;
            const auto& r = submit.stage_views[1].pose.position;
            const float dx = r.x-l.x, dy=r.y-l.y, dz=r.z-l.z;
            const float ipd = std::sqrt(dx*dx+dy*dy+dz*dz);
            if (std::isfinite(ipd) && ipd >= 0.045f && ipd <= 0.085f)
                half_shift = std::clamp(0.5f*ipd*(distance/reference-1.0f), -0.5f, 0.5f);
        }
        // Manual override always works, including when the Mono pipeline does
        // not supply independently tracked stage_views. Do not silently no-op.
        const float manual = m_parent->duoview_convergence_manual();
        if (std::isfinite(manual) && manual >= -0.25f && manual <= 0.25f)
            half_shift = std::clamp(half_shift + manual,-0.5f,0.5f);
        glm_matrix[3] += (eye==XR_EYE_VISIBILITY_LEFT ? half_shift : -half_shift) * glm_matrix[0];
    }

    layer.pose.orientation = runtimes::OpenXR::to_openxr(glm::quat_cast(glm_matrix));''')
    edit(dx,
'''            } else if (!suppress_ui_copy && m_openxr.ever_acquired((uint32_t)runtimes::OpenXR::SwapchainIndex::UI)) {
                const auto slate_layer = openxr_overlay.generate_slate_layer(runtimes::OpenXR::SwapchainIndex::UI, XrEyeVisibility::XR_EYE_VISIBILITY_BOTH, ui_pose_basis_ptr);''',
'''            } else if (!suppress_ui_copy && m_openxr.ever_acquired((uint32_t)runtimes::OpenXR::SwapchainIndex::UI)) {
                // Same acquired UI image, two separate eye-visible quads. The original
                // single BOTH-eye quad is retained for all unsupported combinations.
                const bool duo_converge=vr->is_duoview_renderer_active() &&
                    vr->get_overlay_component().duoview_convergence_enabled() &&
                    vr->get_overlay_component().duoview_convergence_supported();
                bool duo_converged=false;
                if (duo_converge) {
                    auto left=openxr_overlay.generate_slate_layer(
                        runtimes::OpenXR::SwapchainIndex::UI,XR_EYE_VISIBILITY_LEFT,ui_pose_basis_ptr);
                    auto right=openxr_overlay.generate_slate_layer(
                        runtimes::OpenXR::SwapchainIndex::UI,XR_EYE_VISIBILITY_RIGHT,ui_pose_basis_ptr);
                    if (left && right) {
                        quad_layers.push_back(&left->get());
                        quad_layers.push_back(&right->get());
                        duo_converged=true;
                        vr->get_overlay_component().note_duoview_convergence_submitted();
                    }
                }
                if (!duo_converged) {
                const auto slate_layer = openxr_overlay.generate_slate_layer(runtimes::OpenXR::SwapchainIndex::UI, XrEyeVisibility::XR_EYE_VISIBILITY_BOTH, ui_pose_basis_ptr);''')
    edit(dx,
'''                    quad_layers.push_back(&slate_layer->get());
                }   
            }
            
            if (is_ue58_runtime_cached()) {''',
'''                    quad_layers.push_back(&slate_layer->get());
                }
                }
            }
            
            if (is_ue58_runtime_cached()) {''')

    # The setting is also accessible directly in the DuoView ID6 panel,
    # eliminating the hidden Overlay Options control from the prior build.
    edit(vr_cpp,
'''                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");''',
'''                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");
                get_overlay_component().draw_duoview_convergence_controls();''')

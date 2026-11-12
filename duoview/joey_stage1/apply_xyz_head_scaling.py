#!/usr/bin/env python3
"""Opt-in XYZ HMD translation scaling; applies after pinned v186.1 Build49 patches."""
import sys
from pathlib import Path
if len(sys.argv)!=2: raise SystemExit("Usage: apply_xyz_head_scaling.py <backend>")
b=Path(sys.argv[1])
h=b/"src/mods/VR.hpp"; c=b/"src/mods/VR.cpp"; f=b/"src/mods/vr/FFakeStereoRenderingHook.cpp"

def edit(p, old, new):
 s=p.read_text(encoding="utf-8-sig")
 if s.count(old)!=1: raise RuntimeError(f"Expected exactly one anchor in {p}, found {s.count(old)}: {old[:120]}")
 p.write_text(s.replace(old,new,1),encoding="utf-8",newline="")

edit(h,
'    const ModSlider::Ptr m_world_scale{ ModSlider::create(generate_name("WorldScale"), 0.01f, 10.0f, 1.0f) };',
'''    const ModSlider::Ptr m_world_scale{ ModSlider::create(generate_name("WorldScale"), 0.01f, 10.0f, 1.0f) };
    // Opt-in XYZ translation scaling; never affects the stock World Scale or IPD.
    const ModToggle::Ptr m_xyz_headscale_enabled{ ModToggle::create(generate_name("XYZHeadScalingEnabled"), false) };
    const ModSlider::Ptr m_xyz_headscale_x{ ModSlider::create(generate_name("XYZHeadScaleX"), 0.05f, 5.0f, 1.0f) };
    const ModSlider::Ptr m_xyz_headscale_y{ ModSlider::create(generate_name("XYZHeadScaleY"), 0.05f, 5.0f, 1.0f) };
    const ModSlider::Ptr m_xyz_headscale_z{ ModSlider::create(generate_name("XYZHeadScaleZ"), 0.05f, 5.0f, 1.0f) };
    const ModKey::Ptr m_xyz_headscale_toggle_key{ ModKey::create(generate_name("XYZHeadScaleToggleKey")) };
    const ModKey::Ptr m_xyz_headscale_hold_bypass_key{ ModKey::create(generate_name("XYZHeadScaleHoldBypassKey")) };
    std::atomic<bool> m_xyz_headscale_hold_bypass{ false };''')

edit(h,
'''    auto get_world_scale() const {
        return m_world_scale->value();
    }''',
'''    auto get_world_scale() const {
        return m_world_scale->value();
    }

    // Tracking-space movement only; no origin/reference resets or eye changes.
    glm::vec3 get_xyz_head_movement_gains() const {
        if (!m_xyz_headscale_enabled->value() ||
            m_xyz_headscale_hold_bypass.load(std::memory_order_relaxed)) {
            return {1.0f, 1.0f, 1.0f};
        }
        const auto valid_gain = [](float v) {
            return std::isfinite(v) && v >= 0.05f && v <= 5.0f ? v : 1.0f;
        };
        return {valid_gain(m_xyz_headscale_x->value()),
                valid_gain(m_xyz_headscale_y->value()),
                valid_gain(m_xyz_headscale_z->value())};
    }''')

edit(h,'            *m_world_scale,\n            *m_depth_scale,',
'''            *m_world_scale,
            *m_xyz_headscale_enabled,
            *m_xyz_headscale_x, *m_xyz_headscale_y, *m_xyz_headscale_z,
            *m_xyz_headscale_toggle_key, *m_xyz_headscale_hold_bypass_key,
            *m_depth_scale,''')

edit(c,'''void VR::handle_keybinds() {
    ZoneScopedN(__FUNCTION__);''',
'''void VR::handle_keybinds() {
    ZoneScopedN(__FUNCTION__);
    // Sample keys on the game thread once per frame, not per render view.
    if (m_xyz_headscale_toggle_key->is_key_down_once()) {
        m_xyz_headscale_enabled->toggle();
    }
    m_xyz_headscale_hold_bypass.store(
        m_xyz_headscale_hold_bypass_key->is_key_down(), std::memory_order_relaxed);''')

edit(c,'''        m_world_scale->draw("World Scale");
        m_depth_scale->draw("Depth Scale");''',
'''        m_world_scale->draw("World Scale");
        ImGui::Separator();
        ImGui::TextUnformatted("Head Movement XYZ Scaling (independent of World Scale)");
        m_xyz_headscale_enabled->draw("Enable Head XYZ Scaling");
        m_xyz_headscale_x->draw("Head X - Left/Right");
        m_xyz_headscale_y->draw("Head Y - Up/Down");
        m_xyz_headscale_z->draw("Head Z - Forward/Back");
        ImGui::TextWrapped("Scales only HMD translation relative to the existing standing origin. Rotation, eye separation, controller poses and World Scale are unchanged. Set toggle and hold-bypass keys in Keybinds.");
        m_depth_scale->draw("Depth Scale");''')

edit(c,'''        if (ImGui::TreeNode("Overlay/Runtime Keys")) {
            m_keybind_toggle_2d_screen->draw("Toggle 2D Screen Mode Key");''',
'''        if (ImGui::TreeNode("Head Movement XYZ Keys")) {
            m_xyz_headscale_toggle_key->draw("Toggle XYZ Head Scaling");
            m_xyz_headscale_hold_bypass_key->draw("Hold to Disable XYZ Scaling");
            ImGui::TextWrapped("Hold bypass temporarily restores normal 1x head translation; it never changes the saved enabled setting. Both bindings default to Unbound.");
            ImGui::TreePop();
        }

        if (ImGui::TreeNode("Overlay/Runtime Keys")) {
            m_keybind_toggle_2d_screen->draw("Toggle 2D Screen Mode Key");''')

# Preserve roomscale pawn movement and IPD: modify *only* HMD head offset.
edit(f,'const auto pos = glm::vec3{rotation_offset * standing_delta};',
'''const auto xyz_gains = vr->get_xyz_head_movement_gains();
        const glm::vec3 scaled_standing_delta{
            standing_delta.x * xyz_gains.x,
            standing_delta.y * xyz_gains.y,
            standing_delta.z * xyz_gains.z
        };
        const auto pos = glm::vec3{rotation_offset * scaled_standing_delta};''')
print("XYZ Head Scaling patch applied. No changes to DuoView shading, gaze, GPU, SDK, World Scale or IPD.")

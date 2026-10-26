#!/usr/bin/env python3
"""Build 166: minimal, opt-in DuoView OpenXR menu-cursor alignment patch.

Builds ON TOP OF Build165's exact pinned backend and XYZ patch. Uses existing
FrameworkConfig Always Show Cursor setting; no input hooks, new threads,
shader edits, texture allocations, UEVR render producer/eye index edits,
OpenXR swapchain changes, or modified runtime/driver behavior.

Design from independent examination of the game-UI plane matching approach:
source: Remleo/UEVR (see docs). Code below is an independent implementation.
"""
from pathlib import Path
import argparse
p=argparse.ArgumentParser()
p.add_argument("backend",type=Path)
a=p.parse_args()
root=a.backend/"src/mods/vr"
hdr=root/"OverlayComponent.hpp"
cpp=root/"OverlayComponent.cpp"

def replace_one(s,old,new,label):
    n=s.count(old)
    if n!=1: raise RuntimeError(f"Build166 {label}: expected one original anchor, got {n}")
    if new in s: raise RuntimeError(f"Build166 already applied: {label}")
    return s.replace(old,new,1)

h=hdr.read_text(encoding="utf-8-sig")
h=replace_one(h,
'''        XrCompositionLayerQuad m_framework_ui_layer{};
        OverlayComponent* m_parent{ nullptr };''',
'''        XrCompositionLayerQuad m_framework_ui_layer{};
        // The game UI quad belongs to the current submitted frame, never a
        // previous frame or a rebuilt OpenXR swapchain. Does not own resources.
        uint32_t m_duoview_cursor_game_frame{};
        bool m_duoview_cursor_game_valid{false};
        OverlayComponent* m_parent{ nullptr };''',
"UI presentation frame stamp")
hdr.write_text(h,encoding="utf-8",newline="")

s=cpp.read_text(encoding="utf-8-sig")
s=replace_one(s,
'''#include "Framework.hpp"
#include "../VR.hpp"''',
'''#include "Framework.hpp"
#include "../FrameworkConfig.hpp"
#include "../VR.hpp"''',
"existing cursor option include")

# Mark a cursor-alignable presented GAME quad, not a per-eye slate layer,
# a cylinder, a Framework UI quad or another swapchain.
start=s.index("std::optional<std::reference_wrapper<XrCompositionLayerQuad>> OverlayComponent::OpenXR::generate_slate_quad(")
end=s.index("std::optional<std::reference_wrapper<XrCompositionLayerCylinderKHR>> OverlayComponent::OpenXR::generate_slate_cylinder(",start)
section=s[start:end]
section=replace_one(section,
'''    layer.pose.orientation = runtimes::OpenXR::to_openxr(glm::quat_cast(glm_matrix));
    layer.pose.position = runtimes::OpenXR::to_openxr(glm_matrix[3]);

    vr->record_ui_layer_pose_sample(''',
'''    layer.pose.orientation = runtimes::OpenXR::to_openxr(glm::quat_cast(glm_matrix));
    layer.pose.position = runtimes::OpenXR::to_openxr(glm_matrix[3]);

    // Record the *final submitted* game UI quad after HUD optical/convergence
    // adjustments. The cursor later uses THIS same quad rather than rebuilding
    // a second headset/pitch/standing-origin transform.
    if (vr->is_duoview_renderer_active() &&
        swapchain == runtimes::OpenXR::SwapchainIndex::UI &&
        eye == XR_EYE_VISIBILITY_BOTH) {
        m_duoview_cursor_game_frame = vr->get_frame_count();
        m_duoview_cursor_game_valid = true;
    }

    vr->record_ui_layer_pose_sample(''',
"final game UI quad frame stamp")
s=s[:start]+section+s[end:]

start=s.index("std::optional<std::reference_wrapper<XrCompositionLayerQuad>> OverlayComponent::OpenXR::generate_framework_ui_quad()")
section=s[start:]
section=replace_one(section,
'''    layer.layerFlags = XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT;
    layer.eyeVisibility = XrEyeVisibility::XR_EYE_VISIBILITY_BOTH;

    auto glm_matrix = glm::identity<glm::mat4>();''',
'''    layer.layerFlags = XR_COMPOSITION_LAYER_BLEND_TEXTURE_SOURCE_ALPHA_BIT;
    layer.eyeVisibility = XrEyeVisibility::XR_EYE_VISIBILITY_BOTH;

    // Opt-in via Main -> Always Show Cursor, gated to Mono DuoView OpenXR.
    // Existing ImGui already draws the pointer; match its layer to the GAME
    // UI's exact submitted pose/size, including saved optical convergence.
    // Do not touch stereo passes, projected views, game HUD, or user input.
    if (!g_framework->is_drawing_ui() &&
        FrameworkConfig::get()->is_always_show_cursor() &&
        vr->is_duoview_renderer_active() &&
        m_duoview_cursor_game_valid &&
        m_duoview_cursor_game_frame == vr->get_frame_count() &&
        m_slate_layer.type == XR_TYPE_COMPOSITION_LAYER_QUAD &&
        m_slate_layer.eyeVisibility == XR_EYE_VISIBILITY_BOTH &&
        m_slate_layer.subImage.swapchain ==
            vr->m_openxr->swapchains[(uint32_t)runtimes::OpenXR::SwapchainIndex::UI].handle &&
        m_slate_layer.space != XR_NULL_HANDLE &&
        std::isfinite(m_slate_layer.size.width) &&
        std::isfinite(m_slate_layer.size.height) &&
        m_slate_layer.size.width > 0.0f &&
        m_slate_layer.size.height > 0.0f) {
        layer.space = m_slate_layer.space;
        layer.pose = m_slate_layer.pose;
        layer.size = m_slate_layer.size;
        // Offset 1 cm towards the viewer along the game quad's local +Z.
        // A tiny separation keeps the cursor readable without changing UI
        // hit-testing, geometry, or eye-to-eye convergence.
        const auto& q = layer.pose.orientation;
        const glm::quat rotation{q.w, q.x, q.y, q.z};
        const glm::vec3 forward = rotation * glm::vec3{0.0f, 0.0f, 0.01f};
        layer.pose.position.x += forward.x;
        layer.pose.position.y += forward.y;
        layer.pose.position.z += forward.z;
        m_parent->m_framework_intersect_state.intersecting = false;
        return layer;
    }

    // All other modes/settings follow ORIGINAL JOEY framework UI path.
    auto glm_matrix = glm::identity<glm::mat4>();''',
"cursor overlay matches final game quad")
s=s[:start]+section

s=replace_one(s,
'''void OverlayComponent::OpenXR::reset_daysgone_ahud_pose() {
    m_daysgone_ahud_pose_basis = {};
}''',
'''void OverlayComponent::OpenXR::reset_daysgone_ahud_pose() {
    m_daysgone_ahud_pose_basis = {};
    m_duoview_cursor_game_valid = false;
}''',
"invalidate cursor quad on device/reset")
cpp.write_text(s,encoding="utf-8",newline="")
print("Build166 cursor: only OverlayComponent.hpp/.cpp edited; live current-frame quad matching; optional on existing Always Show Cursor toggle.")

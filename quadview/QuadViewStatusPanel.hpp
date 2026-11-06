#pragma once
#include "imgui.h"
#include "QuadViewStatus.hpp"
namespace uevr::quadview {
// Production and headless tests use the same container. All variable-height
// diagnostics belong inside it; following controls have a fixed cursor origin.
template <typename Details>
inline void draw_status_panel(DisplayState state, bool triview, Details&& details) {
    ImGui::Text("%s status: %s", triview ? "TriView" : "QuadView", display_state_text(state));
    const bool visible = ImGui::BeginChild("##QuadViewStatusDetails",
        ImVec2(0.f, ImGui::GetTextLineHeightWithSpacing() * 7.f), true,
        ImGuiWindowFlags_NoScrollWithMouse); // Mouse wheel belongs to the existing parent menu.
    if (visible) details();
    ImGui::EndChild();
}
}

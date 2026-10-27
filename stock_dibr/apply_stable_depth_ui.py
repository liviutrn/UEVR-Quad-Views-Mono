"""R7 stable choices, 1x preference and visibility controls; apply last."""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve();changes={}
def edit(path,old,new):
    s=changes.get(path,(root/path).read_text(encoding='utf-8'))
    if s.count(old)!=1: raise RuntimeError(f'{path}: R7 UI anchor count {s.count(old)}: {old[:100]}')
    changes[path]=s.replace(old,new)
h='src/mods/VR.hpp';c='src/mods/VR.cpp';dh='src/mods/vr/D3D12Component.hpp'
edit(h,'    int get_dibr_inspector_view() const { return std::clamp(m_dibr_inspector_view->value(), 0, 5); }','''    int get_dibr_reconstruction_mode() const { return std::clamp(m_dibr_reconstruction_mode->value(), 0, 1); }
    uint32_t get_dibr_visibility_fill_radius() const { return static_cast<uint32_t>(std::clamp(m_dibr_visibility_fill_radius->value(), 0.0f, 64.0f)); }
    float get_dibr_visibility_depth_tolerance() const { return std::clamp(m_dibr_visibility_depth_tolerance->value(), .001f, .25f); }
    int get_dibr_inspector_view() const { return std::clamp(m_dibr_inspector_view->value(), 0, 6); }''')
edit(h,'"Depth over color", "Reprojection confidence"}, 0)', '"Depth over color", "Reprojection confidence", "Visibility / holes (R7)"}, 0)')
edit(h,'    const ModCombo::Ptr m_dibr_inspector_view{','''    const ModCombo::Ptr m_dibr_reconstruction_mode{ ModCombo::create(generate_name("DIBRReconstructionMode"), {"R6 inverse (comparison)", "Visibility aware (R7)"}, 1) };
    const ModSlider::Ptr m_dibr_visibility_fill_radius{ ModSlider::create(generate_name("DIBRVisibilityFillRadius"), 0.0f, 64.0f, 32.0f) };
    const ModSlider::Ptr m_dibr_visibility_depth_tolerance{ ModSlider::create(generate_name("DIBRVisibilityDepthTolerance"), .001f, .25f, .03f) };
    const ModCombo::Ptr m_dibr_inspector_view{''')
edit(h,'            *m_dibr_inspector_view,','''            *m_dibr_reconstruction_mode,
            *m_dibr_visibility_fill_radius,
            *m_dibr_visibility_depth_tolerance,
            *m_dibr_inspector_view,''')
edit(dh, '    std::string get_dibr_preview_failure_reason() const { return m_dibr_slots[0].preview.failure_reason(); }', '''    std::string get_dibr_preview_failure_reason() const { return m_dibr_slots[0].preview.failure_reason(); }
    std::string get_dibr_visibility_failure_reason() const {
        for (const auto& slot : m_dibr_slots) {
            auto reason=slot.preview.visibility_failure_reason();
            if (!reason.empty()) return reason;
        }
        return {};
    }''')
edit(c,'''                    if (ImGui::Button("Max stereo strength (2.0)")) m_dibr_reprojection_strength->value() = 2.0f;
                    ImGui::TextWrapped("1.0 uses physical runtime geometry; 2.0 exaggerates binocular disparity. Switching comparison modes keeps this value.");''','''                    if (ImGui::Button("Physical stereo strength (1.0)")) m_dibr_reprojection_strength->value() = 1.0f;
                    ImGui::TextWrapped("1.0 is the preferred baseline. Increasing strength exaggerates disparity and changes perceived world scale; it is not a quality setting. Comparison modes retain this value.");
                    m_dibr_reconstruction_mode->draw("Stereo Reconstruction");
                    if (get_dibr_reconstruction_mode() != 0) {
                        m_dibr_visibility_fill_radius->draw("Bounded Background Fill Radius (pixels; 0 disables)");
                        if (const auto reason=m_d3d12.get_dibr_visibility_failure_reason(); !reason.empty())
                            ImGui::TextWrapped("R7 unavailable; using R6: %s",reason.c_str());
                        ImGui::TextWrapped("R7 forward-projects visible surfaces and resolves foreground occlusion. Only bounded holes with both depth boundaries and a stable farther background run are filled. It cannot reveal hidden background. Visibility inspector: green = covered, cyan = bounded fill, red = unresolved geometric fallback; purple = visibility unavailable. R6 inverse remains available for comparison.");
                        ImGui::TextWrapped("Visibility mode uses point depth at hard boundaries; the R5 linear sampling option applies to the R6 path. Optional isolated-spike repair only treats depth noise, not disocclusion.");
                    }''')
edit(c,'ImGui::BeginDisabled(stock_dibr_inspector_scope && is_dibr_preserve_stereo_strength());',
    'ImGui::BeginDisabled(stock_dibr_inspector_scope && (is_dibr_preserve_stereo_strength() || get_dibr_reconstruction_mode() != 0));')
edit(c,'''"Depth candidate selected: %llu; last used: %llu"''','''"Depth stream selected: %llu; last stream used: %llu"''')
edit(c,'''                            char label[192]{};
                            std::snprintf(label, sizeof(label), "ID %llu: %llu x %u, format %u, epoch %llu%s%s",
                                static_cast<unsigned long long>(candidate.id), static_cast<unsigned long long>(candidate.width),
                                static_cast<unsigned>(candidate.height), static_cast<unsigned>(candidate.format),
                                static_cast<unsigned long long>(candidate.last_seen_epoch),
                                candidate.available ? "" : " [no fresh slot]", candidate.id == active_id ? " [last used]" : "");
                            if (ImGui::Selectable(label, selected_id == candidate.id)) m_d3d12.select_dibr_depth_candidate(candidate.id);''','''                            char label[256]{};
                            std::snprintf(label, sizeof(label), "Stream %llu: %llu x %u, format %u, members %u, physical %llu, marker %u%s%s%s",
                                static_cast<unsigned long long>(candidate.id), static_cast<unsigned long long>(candidate.width),
                                static_cast<unsigned>(candidate.height), static_cast<unsigned>(candidate.format),
                                static_cast<unsigned>(candidate.members), static_cast<unsigned long long>(candidate.physical_id), static_cast<unsigned>(candidate.route_confidence),
                                candidate.ambiguous ? " [ambiguous]" : (candidate.available ? "" : " [no fresh slot]"),
                                candidate.id == active_id ? " [last used]" : "", candidate.selected_auto ? " [Auto lock]" : "");
                            ImGui::BeginDisabled(candidate.ambiguous);
                            if (ImGui::Selectable(label, selected_id == candidate.id)) m_d3d12.select_dibr_depth_candidate(candidate.id);
                            ImGui::EndDisabled();''')
edit(c,'ImGui::TextWrapped("IDs identify observed resources in this capture session. Fresh-slot status is instantaneous; last used can remain listed after a frame retires. Any observed ID can be selected, but capture waits for a fresh verified match. Auto resumes normal selection. The bounded list evicts old unselected resources; IDs are never reused.");',
    'ImGui::TextWrapped("Pattern IDs keep a resource-pool choice while textures rotate. Grouping uses executed view/queue metadata plus matching descriptors or exact names. This is a heuristic: unrelated passes can share names or recycle descriptors. Inspect the map before pinning. Ambiguous patterns cannot be pinned. No fresh member means unavailable, never stale depth. Auto keeps its current choice while fresh; a larger resource alone cannot evict it. Reset invalidates IDs and returns to Auto.");')
for path,s in changes.items(): (root/path).write_text(s,encoding='utf-8')
print('Applied R7 stable depth choice and visibility controls with preferred 1.0 stereo')

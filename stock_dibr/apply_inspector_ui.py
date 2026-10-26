"""Guarded R6 UI overlay; apply after all R5 stages and the R6 shader stage.

Only metadata crosses the depth-capture/UI boundary. Rendering-method buttons
request a normal lifecycle transition and never assign an effective mode.
"""
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()
changes = {}
def edit(path, old, new):
    source = changes.get(path)
    if source is None:
        source = (root / path).read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one R6 UI anchor, found {count}: {old[:100]}")
    changes[path] = source.replace(old, new)

vh = "src/mods/VR.hpp"
vc = "src/mods/VR.cpp"
dh = "src/mods/vr/D3D12Component.hpp"
edit(vh, "    int32_t requested_rendering_method() const { return m_rendering_method->requested_value(); }", """    int32_t requested_rendering_method() const { return m_rendering_method->requested_value(); }
    // Use the existing requested/effective rendering-method lifecycle.
    void request_rendering_method(int32_t method) { m_rendering_method->request(method); }""")
edit(vh, "    float get_dibr_disparity_pixels() const {", """    int get_dibr_inspector_view() const { return std::clamp(m_dibr_inspector_view->value(), 0, 5); }
    int get_dibr_depth_sampling_mode() const { return std::clamp(m_dibr_depth_sampling_mode->value(), 0, 2); }
    int get_dibr_depth_repair_mode() const { return std::clamp(m_dibr_depth_repair_mode->value(), 0, 1); }
    float get_dibr_depth_scale() const { return std::clamp(m_dibr_depth_scale->value(), 0.25f, 4.0f); }
    float get_dibr_depth_display_gain() const { return std::clamp(m_dibr_depth_display_gain->value(), -8.0f, 24.0f); }
    float get_dibr_depth_repair_threshold() const { return std::clamp(m_dibr_depth_repair_threshold->value(), 0.0001f, 0.1f); }
    bool is_dibr_preserve_stereo_strength() const { return m_dibr_preserve_stereo_strength->value(); }

    float get_dibr_disparity_pixels() const {""")
edit(vh, '    const ModSlider::Ptr m_dibr_disparity_pixels{', '''    const ModCombo::Ptr m_dibr_inspector_view{ ModCombo::create(generate_name("DIBRInspectorView"), {"Normal stereo", "Raw depth", "Readable depth", "Depth edges", "Depth over color", "Reprojection confidence"}, 0) };
    const ModCombo::Ptr m_dibr_depth_sampling_mode{ ModCombo::create(generate_name("DIBRDepthSamplingMode"), {"R5 linear", "Point", "Edge-aware"}, 0) };
    const ModCombo::Ptr m_dibr_depth_repair_mode{ ModCombo::create(generate_name("DIBRDepthRepairMode"), {"Off", "Isolated spike median"}, 0) };
    const ModSlider::Ptr m_dibr_depth_scale{ ModSlider::create(generate_name("DIBRDepthScale"), 0.25f, 4.0f, 1.0f) };
    const ModSlider::Ptr m_dibr_depth_display_gain{ ModSlider::create(generate_name("DIBRDepthDisplayGain"), -8.0f, 24.0f, 10.0f) };
    const ModSlider::Ptr m_dibr_depth_repair_threshold{ ModSlider::create(generate_name("DIBRDepthRepairThreshold"), 0.0001f, 0.1f, 0.005f) };
    const ModToggle::Ptr m_dibr_preserve_stereo_strength{ ModToggle::create(generate_name("DIBRPreserveStereoStrength"), true) };
    const ModSlider::Ptr m_dibr_disparity_pixels{''')
edit(vh, "            *m_dibr_disparity_pixels,", """            *m_dibr_inspector_view,
            *m_dibr_depth_sampling_mode,
            *m_dibr_depth_repair_mode,
            *m_dibr_depth_scale,
            *m_dibr_depth_display_gain,
            *m_dibr_depth_repair_threshold,
            *m_dibr_preserve_stereo_strength,
            *m_dibr_disparity_pixels,""")
edit(dh, "    void invalidate_dibr_single_view_readiness() {", """    std::vector<stock_dibr::CandidateInfo> get_dibr_depth_candidates() const {
        return m_stock_dibr_depth ? m_stock_dibr_depth->candidates() : std::vector<stock_dibr::CandidateInfo>{};
    }
    bool select_dibr_depth_candidate(uint64_t id) {
        return m_stock_dibr_depth && m_stock_dibr_depth->select_candidate(id);
    }
    uint64_t get_dibr_selected_depth_candidate() const {
        return m_stock_dibr_depth ? m_stock_dibr_depth->selected_candidate() : 0;
    }
    uint64_t get_dibr_active_depth_candidate() const {
        return m_stock_dibr_depth ? m_stock_dibr_depth->active_candidate_id() : 0;
    }

    void invalidate_dibr_single_view_readiness() {""")
# This panel deliberately lives outside is_dibr_rendering_method_selected(), so
# returning from native/sequential remains possible without finding another menu.
edit(vc, "        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {", """        const bool stock_dibr_inspector_scope = is_stalker2_executable_cached() && m_is_d3d12 &&
            get_runtime() != nullptr && get_runtime()->is_openxr();
        if (stock_dibr_inspector_scope && ImGui::TreeNode("DIBR comparison (S.T.A.L.K.E.R. 2)")) {
            ImGui::TextWrapped("Explicit full rendering-mode changes: allow warmup after each switch. This is not an instant or same-frame A/B comparison. DIBR calibration, strength, Native Stereo Fix and convergence settings are retained.");
            ImGui::Text("Requested method: %d; active method: %d", requested_rendering_method(), m_rendering_method->value());
            if (ImGui::Button("Compare Native Stereo")) {
                request_rendering_method(RenderingMethod::NATIVE_STEREO);
                rendering_method_changed = true;
            }
            ImGui::SameLine();
            if (ImGui::Button("Compare Sequential (Alternating)")) {
                request_rendering_method(RenderingMethod::ALTERNATING);
                rendering_method_changed = true;
            }
            ImGui::BeginDisabled(m_native_stereo_fix->value());
            if (ImGui::Button("Return to DIBR Single View")) {
                request_rendering_method(RenderingMethod::SYNTHETIC_DIBR_SINGLE_VIEW);
                rendering_method_changed = true;
            }
            ImGui::EndDisabled();
            if (m_native_stereo_fix->value())
                ImGui::TextWrapped("Return to DIBR is blocked while Native Stereo Fix is enabled. Disable it explicitly; comparison never changes it for you.");
            ImGui::TreePop();
        }
        if (rendering_method_changed && !is_mono_transition_pending() && get_runtime() != nullptr) {""")
edit(vc, '''                    "Requirement: disable Native Stereo Fix and Same Stereo Pass before using DIBR. "
                    "DIBR is intentionally isolated and never combines with Native Stereo Fix."''', '''                    "Requirement: Native Stereo Fix must be disabled for DIBR. "
                    "The saved Same Stereo Pass preference remains unchanged and is inactive with Native Stereo Fix off."''')
edit(vc, '''                m_dibr_disparity_pixels->draw("Disparity (Pixels)");
                m_dibr_reprojection_strength->draw("True Reprojection Strength");
                m_dibr_reversed_depth->draw("Use Reversed-Z Depth");''', '''                m_dibr_reprojection_strength->draw("True Reprojection Strength");
                if (stock_dibr_inspector_scope) {
                    ImGui::SameLine();
                    if (ImGui::Button("Max stereo strength (2.0)")) m_dibr_reprojection_strength->value() = 2.0f;
                    ImGui::TextWrapped("1.0 uses physical runtime geometry; 2.0 exaggerates binocular disparity. Switching comparison modes keeps this value.");
                    m_dibr_preserve_stereo_strength->draw("Preserve Stereo Strength");
                    ImGui::TextWrapped("When enabled, legacy edge stabilization, scene UI edge/footprint blends and legacy color-fill repair are bypassed so they cannot flatten local stereo. Separate UI submission stays unchanged.");
                    if (ImGui::TreeNode("Depth inspector and calibration")) {
                        m_dibr_inspector_view->draw("Inspector View");
                        ImGui::TextWrapped("Raw and readable depth show the same image in both eyes for comfortable inspection. Display exposure changes visualization only.");
                        m_dibr_depth_display_gain->draw("Depth display exposure (stops, visualization only)");
                        m_dibr_depth_sampling_mode->draw("Depth Sampling");
                        m_dibr_depth_scale->draw("Device-depth calibration (1 = unchanged)");
                        m_dibr_reversed_depth->draw("Reversed-Z convention (display/calibration/legacy repair)");
                        ImGui::TextWrapped("1.0 keeps captured depth unchanged. Scales near-oriented device-Z using the selected depth convention. This is not a metric distance or universal stereo-strength multiplier. Keep 1.0 unless calibrating a verified map.");
                        m_dibr_depth_repair_mode->draw("Depth Repair (no temporal history)");
                        if (get_dibr_depth_repair_mode() != 0)
                            m_dibr_depth_repair_threshold->draw("Isolated Spike Threshold (raw device-Z, not metres)");
                        ImGui::TextWrapped("Isolated-spike repair requires coherent surrounding depths; it avoids averaging across silhouettes. It can remove genuine one-pixel geometry; leave it off unless inspection proves useful.");
                        if (ImGui::Button("Reset depth calibration")) {
                            m_dibr_depth_scale->value() = 1.0f;
                            m_dibr_depth_sampling_mode->value() = 0;
                            m_dibr_depth_repair_mode->value() = 0;
                            m_dibr_depth_repair_threshold->value() = 0.005f;
                            m_dibr_depth_display_gain->value() = 10.0f;
                            m_dibr_inspector_view->value() = 0;
                        }
                        ImGui::TextWrapped("Reset keeps true reprojection strength, selected depth candidate and comparison mode.");
                        const auto selected_id = m_d3d12.get_dibr_selected_depth_candidate();
                        const auto active_id = m_d3d12.get_dibr_active_depth_candidate();
                        ImGui::Text("Depth candidate selected: %llu; last used: %llu", static_cast<unsigned long long>(selected_id), static_cast<unsigned long long>(active_id));
                        if (ImGui::Button("Auto-select depth candidate")) m_d3d12.select_dibr_depth_candidate(0);
                        const auto candidates = m_d3d12.get_dibr_depth_candidates();
                        if (candidates.empty()) ImGui::TextWrapped("No depth candidates observed yet. Enable depth capture and allow warmup.");
                        for (const auto& candidate : candidates) {
                            ImGui::PushID(static_cast<int>(candidate.id & 0x7fffffff));
                            char label[192]{};
                            std::snprintf(label, sizeof(label), "ID %llu: %llu x %u, format %u, epoch %llu%s%s",
                                static_cast<unsigned long long>(candidate.id), static_cast<unsigned long long>(candidate.width),
                                static_cast<unsigned>(candidate.height), static_cast<unsigned>(candidate.format),
                                static_cast<unsigned long long>(candidate.last_seen_epoch),
                                candidate.available ? "" : " [no fresh slot]", candidate.id == active_id ? " [last used]" : "");
                            if (ImGui::Selectable(label, selected_id == candidate.id)) m_d3d12.select_dibr_depth_candidate(candidate.id);
                            ImGui::PopID();
                        }
                        ImGui::TextWrapped("IDs identify observed resources in this capture session. Fresh-slot status is instantaneous; last used can remain listed after a frame retires. Any observed ID can be selected, but capture waits for a fresh verified match. Auto resumes normal selection. The bounded list evicts old unselected resources; IDs are never reused.");
                        ImGui::TreePop();
                    }
                }''')
# The legacy parallax-reduction controls remain saved, visibly disabled while
# stereo preservation bypasses them in the shader.
edit(vc, '''                    m_dibr_depth_edge_stabilization->draw("Enable Depth-Edge Stabilization");''', '''                    ImGui::BeginDisabled(stock_dibr_inspector_scope && is_dibr_preserve_stereo_strength());
                    m_dibr_depth_edge_stabilization->draw("Enable Depth-Edge Stabilization");''')
edit(vc, '''                    if (ImGui::TreeNode("Legacy fallback tuning")) {
                        m_dibr_legacy_depth_curve->draw("Legacy Depth Response Curve");''', '''                    ImGui::EndDisabled();
                    if (ImGui::TreeNode("Legacy fallback tuning")) {
                        m_dibr_disparity_pixels->draw("Disparity (Pixels, legacy only)");
                        ImGui::TextWrapped("Disparity changes only the legacy fallback. The geometric path uses captured device-Z unchanged at calibration 1.0. Reversed-Z selects the display, calibration and legacy repair convention.");
                        m_dibr_legacy_depth_curve->draw("Legacy Depth Response Curve");''')
# snprintf has an explicit include even on branches whose transitive includes
# happened to supply it. Keep this anchor independent of the shader changes.
edit(vc, '#include "VR.hpp"', '#include "VR.hpp"\n#include <cstdio>')
# Validate every anchor before any target is changed.
for path, source in changes.items():
    (root / path).write_text(source, encoding="utf-8")
print("R6 inspector UI overlay applied:", ", ".join(changes))

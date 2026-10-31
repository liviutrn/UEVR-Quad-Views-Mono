#!/usr/bin/env python3
"""E1 experiment: both eyes in ONE render, right eye built as an independent PRIMARY view.

Applies AFTER apply_v207_auto_fov_after_load.py. Edits src/mods/VR.hpp, src/mods/VR.cpp
and src/mods/vr/FFakeStereoRenderingHook.cpp only.

Question it answers: Native Stereo Fix (STALKER 2) does two things - it relabels the right
eye SECONDARY -> PRIMARY in the FSceneView constructor, and it splits the eyes into two
separate renders (~7 ms GPU each at any resolution). E1 keeps the relabel and drops the
split. If the shading matches Native Fix at near stock Native Stereo cost, tri-view can
put both foveas in one render.

UI: Native Stereo Fix section, combo "E1 test". Off = Native Fix exactly as configured.
E1-A = relabel only (view list visible, so UE sees the right eye as view 1).
E1-B = relabel + hide the view list during construction, exactly like Native Fix does.
While E1 is selected (Native Stereo method, not DuoView/AFR), Native Fix reports off, so
the stock one-render Native Stereo path and its normal submission are used.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_e1_shared_render.py <backend>")
backend = Path(sys.argv[1])


def edit(rel, old, new):
    path = backend / rel
    text = path.read_text(encoding="utf-8-sig")
    if text.count(old) != 1:
        raise SystemExit(f"E1 anchor matched {text.count(old)} times in {rel}: {old[:80]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


VR_HPP = "src/mods/VR.hpp"
VR_CPP = "src/mods/VR.cpp"
HOOK = "src/mods/vr/FFakeStereoRenderingHook.cpp"

# 1. Setting (persisted), names, counter.
edit(VR_HPP,
'''    const ModToggle::Ptr m_native_stereo_fix_preserve_secondary_pass{ ModToggle::create(generate_name("NativeStereoFixPreserveSecondaryPass"), true) };
''',
'''    const ModToggle::Ptr m_native_stereo_fix_preserve_secondary_pass{ ModToggle::create(generate_name("NativeStereoFixPreserveSecondaryPass"), true) };
    static const inline std::vector<std::string> s_e1_shared_render_names {
        "Off (Native Stereo Fix as configured)",
        "E1-A: one render, independent eyes",
        "E1-B: one render, independent eyes (hidden view list)",
    };
    const ModCombo::Ptr m_e1_shared_render{ ModCombo::create(generate_name("E1SharedRenderIndependentEyes"), s_e1_shared_render_names, 0) };
    std::atomic<uint64_t> m_e1_relabels{0};
''')
edit(VR_HPP,
'''            *m_native_stereo_fix_preserve_secondary_pass,
            *m_native_stereo_fix_texture_array_submit,
''',
'''            *m_native_stereo_fix_preserve_secondary_pass,
            *m_e1_shared_render,
            *m_native_stereo_fix_texture_array_submit,
''')

# 2. E1 overrides Native Fix (DuoView keeps priority: it forces Native Fix on).
edit(VR_HPP,
'''        if (is_duoview_renderer_active()) { return true; }

        return m_native_stereo_fix->value() &&''',
'''        if (is_duoview_renderer_active()) { return true; }
        if (is_e1_shared_render_active()) { return false; }

        return m_native_stereo_fix->value() &&''')
edit(VR_HPP,
'''    bool is_native_stereo_fix_same_pass_enabled() const {
''',
'''    // E1: 0 off, 1 relabel only, 2 relabel + hidden view list. Native Stereo method only.
    int32_t e1_shared_render_mode() const {
        if (is_mono_transition_quiescing() || is_duoview_renderer_active() || is_using_afr() ||
            m_rendering_method->value() != RenderingMethod::NATIVE_STEREO) { return 0; }
        return m_e1_shared_render->value();
    }
    bool is_e1_shared_render_active() const { return e1_shared_render_mode() != 0; }
    void note_e1_relabel() { m_e1_relabels.fetch_add(1, std::memory_order_relaxed); }
    uint64_t e1_relabels() const { return m_e1_relabels.load(std::memory_order_relaxed); }

    bool is_native_stereo_fix_same_pass_enabled() const {
''')

# 3. UI right under the Native Stereo Fix checkbox.
edit(VR_CPP,
'''            m_native_stereo_fix->draw("Enabled");
''',
'''            m_native_stereo_fix->draw("Enabled");
            m_e1_shared_render->draw("E1 test");
            if (is_e1_shared_render_active()) {
                ImGui::Text("E1 active: right eye built as PRIMARY %llu times (should keep rising)",
                    static_cast<unsigned long long>(e1_relabels()));
            } else if (m_e1_shared_render->value() != 0) {
                ImGui::TextWrapped("E1 selected but inactive: needs the Native Stereo rendering method (not DuoView/AFR).");
            }
            ImGui::TextWrapped("E1 keeps both eyes in ONE render but builds the right eye as its own view, "
                "like Native Fix, without Native Fix's second render. Off = Native Fix as configured.");
''')

# 4. Constructor relabel. Same mechanism as Native Fix's same-pass path (set_effective_stereo_pass
#    + restore after the constructor), applied only to the main viewport's right eye.
edit(HOOK,
'''    if (vr->is_native_stereo_fix_enabled() &&
        (is_ue_4_25_runtime() || is_ue_4_26_runtime()) &&
        init_options_original_stereo_pass == EStereoscopicPass::eSSP_SECONDARY)''',
'''    if (const auto e1_mode = vr->e1_shared_render_mode();
        e1_mode != 0 && is_ue5 && g_hook->is_in_viewport_client_draw() &&
        init_options_stereo_pass == EStereoscopicPass::eSSP_SECONDARY)
    {
        auto view_family = init_options->get_view_family();
        const auto rtm = g_hook->get_render_target_manager();
        const auto family_rt = view_family != nullptr ? view_family->get_render_target() : nullptr;
        const bool e1_main_family = rtm != nullptr && family_rt != nullptr &&
            (family_rt == rtm->get_view_family_render_target() ||
             family_rt == reinterpret_cast<sdk::FRenderTarget*>(rtm->get_viewport()));
        if (!e1_main_family) {
            SPDLOG_INFO_ONCE("[E1] Skipping a SECONDARY view outside the main viewport family");
        } else {
            set_effective_stereo_pass(EStereoscopicPass::eSSP_PRIMARY);
            restore_init_options_after_constructor = true;
            auto views = view_family->get_views();
            if (e1_mode == 2 && views != nullptr && !views_original_count.has_value()) {
                views_original_count = views->count;
                views->count = 0;
            }
            vr->note_e1_relabel();
            SPDLOG_INFO_ONCE("[E1] Right eye constructed as PRIMARY inside the shared two-view family (mode {})", e1_mode);
        }
    }

    if (vr->is_native_stereo_fix_enabled() &&
        (is_ue_4_25_runtime() || is_ue_4_26_runtime()) &&
        init_options_original_stereo_pass == EStereoscopicPass::eSSP_SECONDARY)''')

print("E1 shared-render experiment applied")

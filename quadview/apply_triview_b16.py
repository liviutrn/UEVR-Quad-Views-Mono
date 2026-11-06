#!/usr/bin/env python3
"""B16: TriView controls usability, settled config saves, and retirement-aware resize.

B15 remains the parent. This intentionally does NOT impose a crop-size cap and
does NOT claim to fix the GPU-driver BSOD: it prevents new source allocations
while previous native targets are still awaiting GPU-fenced retirement.
Run after apply_triview_b15.py.
"""
from pathlib import Path
import sys

def once(text, old, new, label):
    if text.count(old) != 1:
        raise RuntimeError(f"B16 {label}: expected 1 anchor, got {text.count(old)}")
    return text.replace(old, new, 1)

def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_triview_b16.py <backend>")
    path=Path(sys.argv[1]) / "src/mods/VR.cpp"
    s=path.read_text(encoding="utf-8")

    # Do not initiate successive resize generations before the native owners
    # from the previous generation have passed their GPU retirement fence.
    old="""                    if (decision.request) {
                        m_triview_pending_extents=decision.request_extents;
                        m_triview_pending_extents_valid=true;
                    }
"""
    new="""                    // B16: wait for GPU-fenced retirement of OLD source targets
                    // before another new generation is allocated. Keep the user's
                    // desired crop/scale unchanged; ResizeGate retries in 2 s.
                    bool safe_request=decision.request;
                    if (safe_request && live_rtm) {
                        const auto retired=live_rtm->get_quadview_native_retirement_diagnostics();
                        if (retired.observed && (retired.busy || retired.pending || retired.staged ||
                                                 retired.in_flight || retired.ready)) {
                            safe_request=false;
                            SPDLOG_INFO_EVERY_N_SEC(2,"[TriView][Resize] deferring new generation until GPU-fenced retirement finishes");
                        }
                    }
                    if (safe_request) {
                        m_triview_pending_extents=decision.request_extents;
                        m_triview_pending_extents_valid=true;
                    }
"""
    s=once(s,old,new,"retirement-aware resize")
    s=once(s,'decision.request ? "one build requested" : "waiting until the sizes stop changing"',
             'safe_request ? "one build requested" : "waiting for settle or target retirement"',
             "accurate resize status")

    anchor='''            if (ImGui::TreeNode(status_triview ? "TriView Stereo — focus controls and diagnostics###QuadViewControls" :
                "QuadView Stereo — focus controls and diagnostics###QuadViewControls")) {'''
    pre=r'''            // B16: option pointers were already registered in m_options by B5/B8.
            // Their values enter VR::on_config_save(), but ordinary edits are not
            // necessarily written before a crash / restart. Coalesce changes, not
            // one write per slider tick or render frame.
            auto tri_controls=std::make_tuple(
                m_quadview_crop_width->value(),m_quadview_crop_height->value(),
                m_quadview_context_scale->value(),m_quadview_foveal_density->value(),
                m_quadview_feather->value(),m_quadview_tri_view->value(),
                m_quadview_sharpen->value(),m_quadview_sharpen_max->value(),
                m_quadview_sharpen_link->value(),m_quadview_sharpen_right->value(),
                m_quadview_sharpen_right_max->value(),m_quadview_eye_tracking->value(),
                m_quadview_stabilize_crop->value(),m_quadview_guard->value(),
                m_quadview_gaze_quant->value(),m_quadview_gaze_hold->value(),
                m_quadview_gaze_reacquire->value(),m_quadview_gaze_offset_u->value(),
                m_quadview_gaze_offset_v->value(),m_quadview_gaze_micro_gain->value(),
                m_quadview_gaze_breakout->value(),m_quadview_gaze_still->value(),
                m_quadview_gaze_relock->value(),m_quadview_compact_targets->value(),
                m_quadview_depth_reproject->value(),m_quadview_depth_strength->value());
            static std::optional<decltype(tri_controls)> tri_last_controls{};
            static bool tri_save_pending=false;
            static uint64_t tri_change_tick=0;
            const auto tri_now=GetTickCount64();
            if (!tri_last_controls) tri_last_controls=tri_controls;
            else if (*tri_last_controls!=tri_controls) {
                tri_last_controls=tri_controls;
                tri_change_tick=tri_now;
                tri_save_pending=true;
            }
            if (tri_save_pending && tri_now-tri_change_tick>=750) {
                if (g_framework) g_framework->deferred_save_config();
                tri_save_pending=false;
            }
            ImGui::TextUnformatted("TriView values auto-save after a change settles.");
            if (ImGui::SmallButton("Save TriView settings now###TriViewSaveNow")) {
                if (g_framework) g_framework->deferred_save_config();
                tri_save_pending=false;
            }
'''
    s=once(s, anchor, pre+anchor, "autosave")

    beginning='''                "QuadView Stereo — focus controls and diagnostics###QuadViewControls")) {
'''
    beginning_new=beginning+'''                // Independent, bounded scrolling: does not depend on the parent
                // menu mouse wheel. Buttons work with mouse and VR pointer input.
                const bool tri_scroll_up=ImGui::SmallButton("Scroll up###TriViewUp");
                ImGui::SameLine();
                const bool tri_scroll_down=ImGui::SmallButton("Scroll down###TriViewDown");
                ImGui::BeginChild("TriViewScrollBody",ImVec2(0.f,400.f),true,
                    ImGuiWindowFlags_AlwaysVerticalScrollbar);
                if (tri_scroll_up) ImGui::SetScrollY(std::max(0.f,ImGui::GetScrollY()-240.f));
                if (tri_scroll_down) ImGui::SetScrollY(std::min(ImGui::GetScrollMaxY(),ImGui::GetScrollY()+240.f));
'''
    s=once(s,beginning,beginning_new,"scroll child start")
    start=s.index('ImGui::BeginChild("TriViewScrollBody"')
    end=s.find('                ImGui::TreePop();\n            }\n',start)
    if end<0 or "m_quadview_dimension_fallback" not in s[start:end]:
        raise RuntimeError("B16 scroll child end anchor not uniquely after TriView diagnostics")
    s=s[:end]+'                ImGui::EndChild();\n'+s[end:]
    path.write_text(s,encoding="utf-8",newline="\n")
    print("B16: UI scroll controls; settled auto-save; serialize resize against native retirement")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""B9: typed submission status and a fixed-height diagnostics container.
Run after apply_triview_eye_sharpen.py and before shader embedding.
"""
from pathlib import Path
import shutil
import sys
if len(sys.argv) != 3:
    raise SystemExit('Usage: apply_triview_stability.py <backend> <quadview-dir>')
root, overlay = map(Path, sys.argv[1:])
for name in ('QuadViewStatus.hpp', 'QuadViewStatusPanel.hpp'):
    shutil.copy2(overlay / name, root / 'src/mods/vr' / name)
def edit(rel, old, new):
    p = root / rel
    text = p.read_text(encoding='utf-8')
    if text.count(old) != 1:
        raise SystemExit(f'{rel}: expected one stability anchor, got {text.count(old)}: {old[:90]}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8', newline='\n')
edit('src/mods/VR.hpp', '#pragma once\n', '#pragma once\n#include "vr/QuadViewStatus.hpp"\n')
edit('src/mods/VR.hpp', '    const char* quadview_status() const { return m_quadview_status.load(std::memory_order_acquire); }', '''    const char* quadview_status() const { return m_quadview_status.load(std::memory_order_acquire); }
    void note_quadview_xr_submit(uint64_t generation, uint64_t serial, uint64_t tick) {
        if (generation == mono_generation()) m_quadview_display_status.submitted(generation, serial, tick);
    }
    uevr::quadview::StatusTracker m_quadview_display_status;''')
edit('src/mods/VR.cpp', '#include "VR.hpp"\n', '#include "VR.hpp"\n#include "vr/QuadViewStatusPanel.hpp"\n')
edit('src/mods/VR.cpp', '''            ImGui::TextWrapped("Quad Views Stereo (Experimental): four engine views use independent per-eye gaze crops while OpenXR receives two real stereo eyes.");
            if (const auto reason = quadview_unavailable_reason()) ImGui::TextWrapped("Unavailable: %s", reason);
            ImGui::TextWrapped("Quad Views status: %s", quadview_status());
            {''', '''            const auto status_key=quadview_producer_key();
            const auto status_source=quadview_producer().snapshot(status_key);
            const bool status_triview=status_source ? status_source->layout.shared_context : m_quadview_tri_view->value();
            const auto status_reason=quadview_unavailable_reason();
            const auto primary=m_quadview_display_status.state({mono_generation(),GetTickCount64(),
                is_mono_transition_pending(),status_reason!=nullptr,quadview_native_target_set(status_key)!=nullptr});
            uevr::quadview::draw_status_panel(primary,status_triview,[&] {
                ImGui::TextWrapped(status_triview
                    ? "TriView Stereo: one shared context and two real stereo focus views."
                    : "QuadView Stereo: four engine views with independent per-eye gaze crops.");
                if (status_reason) ImGui::TextWrapped("Unavailable: %s",status_reason);
                ImGui::TextWrapped("Latest pipeline detail: %s",quadview_status());''')
edit('src/mods/VR.cpp', '''                } else ImGui::TextUnformatted("Source textures: not published yet");
            }
            if (ImGui::TreeNode("Quad Views Stereo — focus controls and diagnostics")) {''', '''                } else ImGui::TextUnformatted("Source textures: not published yet");
            });
            if (ImGui::TreeNode(status_triview ? "TriView Stereo — focus controls and diagnostics###QuadViewControls" :
                "QuadView Stereo — focus controls and diagnostics###QuadViewControls")) {''')
# This anchor is inside the XR_SUCCESS branch, and the fresh-only conditional
# prevents a continuity-held image from keeping the primary indicator Active.
edit('src/mods/vr/runtimes/OpenXR.cpp', '''            vr->set_quadview_status(quadview_holding ? "Holding the last stereo QuadView image briefly" :
                "Four engine histories: stereo QuadView image submitted");''', '''            if (!quadview_holding) vr->note_quadview_xr_submit(quadview_pose_generation,
                submit_state.quadview_serial,GetTickCount64());
            vr->set_quadview_status(quadview_holding ? "Holding the last stereo QuadView image briefly" :
                "Four engine histories: stereo QuadView image submitted");''')
print('TriView B9 typed fresh-submit status and fixed diagnostics panel applied.')

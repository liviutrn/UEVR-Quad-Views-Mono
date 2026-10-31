#!/usr/bin/env python3
"""Tri-view build 1: three renders instead of four (apply LAST, after target_lifetime).

View 0 becomes ONE centre context shared by both eyes: camera at the eye midpoint
(left-eye orientation, like DuoView Mono) with the union FOV of both eye frusta.
View 1 is still constructed (so every four-view GT contract keeps its proofs) but
is never rendered: the dispatcher skips it and native delivery requires roles
0,2,3 only (0x0d). The compositor samples view 0 for both eyes through a per-eye
affine uv transform (exact at infinity). Focus views keep their true per-eye
cameras: view 2 still copies the frozen LEFT-eye pose, captured before the centre
shift. Toggle "Tri-view" (default ON) in the Quad Views UI; OFF = Build 51 quad.
"""
from pathlib import Path
import sys


def edit(root, rel, old, new, count=1):
    path = root / rel
    text = path.read_text(encoding="utf-8")
    if text.count(old) != count:
        raise SystemExit(f"Tri-view anchor matched {text.count(old)} times in {rel}: {old[:90]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def main():
    root = Path(sys.argv[1])
    hook = "src/mods/vr/FFakeStereoRenderingHook.cpp"

    # 1. Setting + UI + layout freeze.
    edit(root, "src/mods/VR.hpp",
        '    const ModSlider::Ptr m_quadview_context_scale{ModSlider::create(generate_name("QuadViewContextScale"), .05f, .50f, .20f)};\n',
        '    const ModSlider::Ptr m_quadview_context_scale{ModSlider::create(generate_name("QuadViewContextScale"), .05f, .50f, .20f)};\n'
        '    const ModToggle::Ptr m_quadview_tri_view{ModToggle::create(generate_name("QuadViewTriView"), true)};\n')
    edit(root, "src/mods/VR.cpp",
        '                m_quadview_context_scale->draw("Context resolution scale");\n',
        '                m_quadview_context_scale->draw("Context resolution scale");\n'
        '                m_quadview_tri_view->draw("Tri-view: one shared centre periphery (3 renders; OFF = 4)");\n')
    edit(root, "src/mods/VR.cpp",
        '            layout=m_quadview_layout_latch.freeze(key.generation,key.draw_serial,*candidate);\n',
        '            if (m_quadview_tri_view->value() && !is_stereo_emulation_enabled() &&\n'
        '                !(draw_config.base_projection_valid &&\n'
        '                  uevr::quadview::apply_shared_context(*candidate,draw_config.projections[0],draw_config.projections[1])))\n'
        '                set_quadview_status("Tri-view could not derive the shared context frustum; using four views");\n'
        '            layout=m_quadview_layout_latch.freeze(key.generation,key.draw_serial,*candidate);\n')

    # 2. Centre camera for view 0. The LEFT pose is frozen first (focus view 2 copies it),
    #    then the constructed context view is moved by half the eye separation.
    edit(root, hook,
        '    const auto view_d = (Vector3d*)view_location;\n',
        '    const auto view_d = (Vector3d*)view_location;\n'
        '    const bool qv_center_context = view_index == 0 && g_hook->m_has_double_precision &&\n'
        '        vr->is_quadview_renderer_active() && [&]() {\n'
        '            const auto snapshot = vr->quadview_producer().snapshot(vr->quadview_producer_key());\n'
        '            return snapshot && snapshot->layout.shared_context;\n'
        '        }();\n'
        '    glm::vec3 qv_center_shift{};\n')
    edit(root, hook,
        '        const auto eye_separation = quat_converter * (eye_translation_rotation * (eye_offset * world_scale));\n',
        '        const auto eye_separation = quat_converter * (eye_translation_rotation * (eye_offset * world_scale));\n'
        '        if (qv_center_context) {\n'
        '            const auto center_offset = (glm::vec3{vr->get_eye_offset(VRRuntime::Eye::LEFT)} +\n'
        '                glm::vec3{vr->get_eye_offset(VRRuntime::Eye::RIGHT)}) * 0.5f;\n'
        '            const auto center_separation = quat_converter * (eye_translation_rotation * (center_offset * world_scale));\n'
        '            qv_center_shift = glm::vec3{eye_separation - center_separation};\n'
        '        }\n')
    edit(root, hook,
        '                vr->set_quadview_status("Waiting for both context offsets to capture one exact OpenXR pose frame");\n'
        '        }\n',
        '                vr->set_quadview_status("Waiting for both context offsets to capture one exact OpenXR pose frame");\n'
        '        }\n'
        '        if (qv_center_context) {\n'
        '            view_d->x += qv_center_shift.x; view_d->y += qv_center_shift.y; view_d->z += qv_center_shift.z;\n'
        '        }\n')

    # 3. Union projection for view 0.
    edit(root, hook,
        '            } else vr->set_quadview_status("Using the native context projection because its frozen OpenXR matrix was unavailable");\n',
        '            } else vr->set_quadview_status("Using the native context projection because its frozen OpenXR matrix was unavailable");\n'
        '            if (view_index == 0 && layout->shared_context) {\n'
        '                matrix[0][0]=layout->context_projection[0]; matrix[2][0]=layout->context_projection[1];\n'
        '                matrix[1][1]=layout->context_projection[2]; matrix[2][1]=layout->context_projection[3];\n'
        '            }\n')

    # 4. Skip rendering view 1; require roles 0,2,3 for this draw's quartet.
    edit(root, hook,
        '            });\n        if (!qv_dispatch_result) {',
        '            },qv_snapshot && qv_snapshot->layout.shared_context ? uint8_t(0x02) : uint8_t(0));\n'
        '        if (!qv_dispatch_result) {')
    edit(root, hook,
        'native_context.target_set_generation,native_targets,true);',
        'native_context.target_set_generation,native_targets,true,\n'
        '                qv_snapshot && qv_snapshot->layout.shared_context ? uint8_t(0x0d) : uint8_t(0x0f));',
        count=2)
    print("Applied tri-view: shared centre context, three renders")


if __name__ == "__main__":
    main()

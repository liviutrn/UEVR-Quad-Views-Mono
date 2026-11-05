#!/usr/bin/env python3
"""B8: two independently tunable foveas, legacy settings linked by default.
Run after apply_triview_depth.py, before embed_shader.py.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_triview_eye_sharpen.py <backend>")
root = Path(sys.argv[1])

def edit(rel, pairs):
    file = root / rel
    source = file.read_text(encoding="utf-8")
    for before, after in pairs:
        count = source.count(before)
        if count != 1:
            raise SystemExit(f"{rel}: B8 anchor expected once, got {count}: {before[:100]!r}")
        source = source.replace(before, after, 1)
    file.write_text(source, encoding="utf-8", newline="\n")

edit("src/mods/VR.hpp", [
    ('ModSlider::create(generate_name("QuadViewSharpen"), 0.f, 5.f, 1.f)',
     'ModSlider::create(generate_name("QuadViewSharpen"), 0.f, 10.f, 1.f)'),
    ('    const ModSlider::Ptr m_quadview_sharpen_max{ModSlider::create(generate_name("QuadViewSharpenMaxChange"), 0.05f, 0.30f, 0.10f)};\n',
     '    const ModSlider::Ptr m_quadview_sharpen_max{ModSlider::create(generate_name("QuadViewSharpenMaxChange"), 0.05f, 0.30f, 0.10f)};\n'
     '    const ModToggle::Ptr m_quadview_sharpen_link{ModToggle::create(generate_name("QuadViewSharpenLinkEyes"), true)};\n'
     '    const ModSlider::Ptr m_quadview_sharpen_right{ModSlider::create(generate_name("QuadViewSharpenRight"), 0.f, 10.f, 1.f)};\n'
     '    const ModSlider::Ptr m_quadview_sharpen_right_max{ModSlider::create(generate_name("QuadViewSharpenRightMaxChange"), 0.05f, 0.30f, 0.10f)};\n'),
    ('            *m_quadview_sharpen, *m_quadview_sharpen_max, *m_quadview_eye_tracking,\n',
     '            *m_quadview_sharpen, *m_quadview_sharpen_max, *m_quadview_sharpen_link,\n'
     '            *m_quadview_sharpen_right, *m_quadview_sharpen_right_max, *m_quadview_eye_tracking,\n')
])

edit("src/mods/VR.cpp", [
    ('                m_quadview_sharpen->draw("Fused focus sharpening strength (0-5, default 1)");\n'
     '                m_quadview_sharpen_max->draw("Sharpening max change per pixel (default 0.10; higher = stronger on hard edges, more halo risk)");\n',
     '                m_quadview_sharpen->draw("Left fovea sharpening strength (0-10)");\n'
     '                m_quadview_sharpen_max->draw("Left fovea max change per pixel (0.05-0.30; more halo risk at high values)");\n'
     '                m_quadview_sharpen_link->draw("Link right fovea sharpening to left (default ON)");\n'
     '                if (!m_quadview_sharpen_link->value()) {\n'
     '                    m_quadview_sharpen_right->draw("Right fovea sharpening strength (0-10)");\n'
     '                    m_quadview_sharpen_right_max->draw("Right fovea max change per pixel (0.05-0.30)");\n'
     '                }\n'),
    ('            requested.sharpen_max_change=m_quadview_sharpen_max->value();\n',
     '            requested.sharpen_max_change=m_quadview_sharpen_max->value();\n'
     '            requested.sharpen_link_right=m_quadview_sharpen_link->value();\n'
     '            requested.sharpen_right_strength=m_quadview_sharpen_right->value();\n'
     '            requested.sharpen_right_max_change=m_quadview_sharpen_right_max->value();\n'),
    ('                    if (rejected&uevr::quadview::reject_sharpen_max) ImGui::TextUnformatted("Sharpen max change rejected");\n',
     '                    if (rejected&uevr::quadview::reject_sharpen_max) ImGui::TextUnformatted("Left sharpen max change rejected");\n'
     '                    if (rejected&uevr::quadview::reject_sharpen_right) ImGui::TextUnformatted("Right sharpen strength rejected");\n'
     '                    if (rejected&uevr::quadview::reject_sharpen_right_max) ImGui::TextUnformatted("Right sharpen max change rejected");\n')
])

edit("src/mods/vr/QuadViewSettings.hpp", [
    ('    float sharpen_max_change{.10f}; // Tri-view B5; .10 = previous fixed shader value\n',
     '    float sharpen_max_change{.10f}; // B5 legacy key retained for left eye\n'
     '    bool sharpen_link_right{true}; // legacy config: left settings on both eyes\n'
     '    float sharpen_right_strength{1.f};\n'
     '    float sharpen_right_max_change{.10f};\n'),
    ('reject_sharpen_max=1u<<17\n',
     'reject_sharpen_max=1u<<17, reject_sharpen_right=1u<<18, reject_sharpen_right_max=1u<<19\n'),
    ('    out.debug_border=requested.debug_border;\n',
     '    out.sharpen_link_right=requested.sharpen_link_right;\n'
     '    out.debug_border=requested.debug_border;\n'),
    ('scalar(requested.sharpen_strength,0.f,5.f,reject_sharpen,&Settings::sharpen_strength);',
     'scalar(requested.sharpen_strength,0.f,10.f,reject_sharpen,&Settings::sharpen_strength);\n'
     '    scalar(requested.sharpen_right_strength,0.f,10.f,reject_sharpen_right,&Settings::sharpen_right_strength);'),
    ('    scalar(requested.sharpen_max_change,.05f,.30f,reject_sharpen_max,&Settings::sharpen_max_change);\n',
     '    scalar(requested.sharpen_max_change,.05f,.30f,reject_sharpen_max,&Settings::sharpen_max_change);\n'
     '    scalar(requested.sharpen_right_max_change,.05f,.30f,reject_sharpen_right_max,&Settings::sharpen_right_max_change);\n'),
    ('a.sharpen_strength==b.sharpen_strength && a.sharpen_max_change==b.sharpen_max_change &&',
     'a.sharpen_strength==b.sharpen_strength && a.sharpen_max_change==b.sharpen_max_change &&\n'
     '        a.sharpen_link_right==b.sharpen_link_right &&\n'
     '        a.sharpen_right_strength==b.sharpen_right_strength &&\n'
     '        a.sharpen_right_max_change==b.sharpen_right_max_change &&')
])

edit("src/mods/vr/QuadViewD3D12.hpp", [
    ('        constants.sharpen_eye[0] = settings.sharpen_strength;\n'
     '        constants.sharpen_eye[1] = settings.sharpen_strength;\n'
     '        constants.sharpen_eye[2] = .10f;\n'
     '        constants.sharpen_eye[3] = .10f;\n',
     '        constants.sharpen_eye[0] = settings.sharpen_strength;\n'
     '        constants.sharpen_eye[1] = settings.sharpen_link_right ? settings.sharpen_strength : settings.sharpen_right_strength;\n'
     '        constants.sharpen_eye[2] = settings.sharpen_max_change;\n'
     '        constants.sharpen_eye[3] = settings.sharpen_link_right ? settings.sharpen_max_change : settings.sharpen_right_max_change;\n')
])
print("B8 per-eye sharpen overlay applied: 0-10 strength, 0.05-0.30 max change, linked by default.")

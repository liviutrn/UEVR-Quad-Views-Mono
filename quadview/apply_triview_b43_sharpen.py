#!/usr/bin/env python3
"""B43 over B42.5: stronger per-eye fovea sharpening, shorter startup holds.
- Strength range 0-10 -> 0-20 and max change 0.40 -> 0.80 (both eyes).
- New per-eye toggle "Extra-wide sharpen": adds a second sharpening ring at
  twice the radius (shader: GlamSharpenFocus, Sharpen.y bits 8/16).
The shader change lives directly in QuadViewComposite.hlsl. This script edits
only generated backend sources. Run after test_triview_b42.py, before
apply_liviu_defaults.py.
"""
from pathlib import Path
import sys


def once(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f"B43 anchor '{label}' found {n} times: {old[:100]!r}")
    return s.replace(old, new, 1)


def patch(path, edits):
    s = path.read_text(encoding='utf-8')
    for old, new, label in edits:
        s = once(s, old, new, label)
    path.write_text(s, encoding='utf-8', newline='\n')


def main():
    mods = Path(sys.argv[1]) / 'src/mods'

    patch(mods / 'VR.hpp', [
        ('ModSlider::create(generate_name("QuadViewSharpen"), 0.f, 10.f, 1.f)',
         'ModSlider::create(generate_name("QuadViewSharpen"), 0.f, 20.f, 1.f)', 'left strength range'),
        ('ModSlider::create(generate_name("QuadViewSharpenMaxChange"), 0.05f, 0.40f, 0.10f)',
         'ModSlider::create(generate_name("QuadViewSharpenMaxChange"), 0.05f, 0.80f, 0.10f)', 'left change range'),
        ('ModSlider::create(generate_name("QuadViewSharpenRight"), 0.f, 10.f, 1.f)',
         'ModSlider::create(generate_name("QuadViewSharpenRight"), 0.f, 20.f, 1.f)', 'right strength range'),
        ('    const ModSlider::Ptr m_quadview_sharpen_right_max{ModSlider::create(generate_name("QuadViewSharpenRightMaxChange"), 0.05f, 0.40f, 0.10f)};\n',
         '    const ModSlider::Ptr m_quadview_sharpen_right_max{ModSlider::create(generate_name("QuadViewSharpenRightMaxChange"), 0.05f, 0.80f, 0.10f)};\n'
         '    const ModToggle::Ptr m_quadview_sharpen_wide_left{ModToggle::create(generate_name("QuadViewSharpenWideLeft"), false)};\n'
         '    const ModToggle::Ptr m_quadview_sharpen_wide_right{ModToggle::create(generate_name("QuadViewSharpenWideRight"), false)};\n',
         'right change range + wide toggles'),
        ('            *m_quadview_sharpen_right, *m_quadview_sharpen_right_max, *m_quadview_eye_tracking,\n',
         '            *m_quadview_sharpen_right, *m_quadview_sharpen_right_max,\n'
         '            *m_quadview_sharpen_wide_left, *m_quadview_sharpen_wide_right, *m_quadview_eye_tracking,\n',
         'saved options'),
    ])

    patch(mods / 'VR.cpp', [
        ('                m_quadview_sharpen->draw("Left fovea sharpening strength (0-10)");\n'
         '                m_quadview_sharpen_max->draw("Left fovea max change per pixel (0.05-0.40; more halo risk at high values)");\n',
         '                m_quadview_sharpen->draw("Left fovea sharpening strength (0-20)");\n'
         '                m_quadview_sharpen_max->draw("Left fovea max change per pixel (0.05-0.80; more halo risk at high values)");\n'
         '                m_quadview_sharpen_wide_left->draw("Left fovea extra-wide sharpen (adds a 2x-radius ring, stronger)");\n',
         'left UI'),
        ('                    m_quadview_sharpen_right->draw("Right fovea sharpening strength (0-10)");\n'
         '                    m_quadview_sharpen_right_max->draw("Right fovea max change per pixel (0.05-0.40)");\n',
         '                    m_quadview_sharpen_right->draw("Right fovea sharpening strength (0-20)");\n'
         '                    m_quadview_sharpen_right_max->draw("Right fovea max change per pixel (0.05-0.80)");\n'
         '                    m_quadview_sharpen_wide_right->draw("Right fovea extra-wide sharpen (adds a 2x-radius ring, stronger)");\n',
         'right UI'),
        ('            requested.sharpen_right_max_change=m_quadview_sharpen_right_max->value();\n',
         '            requested.sharpen_right_max_change=m_quadview_sharpen_right_max->value();\n'
         '            requested.sharpen_wide_left=m_quadview_sharpen_wide_left->value();\n'
         '            requested.sharpen_wide_right=m_quadview_sharpen_wide_right->value();\n',
         'requested settings'),
    ])

    patch(mods / 'vr/QuadViewSettings.hpp', [
        ('    float sharpen_right_max_change{.10f};\n',
         '    float sharpen_right_max_change{.10f};\n'
         '    bool sharpen_wide_left{false};  // B43 extra-wide ring\n'
         '    bool sharpen_wide_right{false};\n', 'fields'),
        ('    out.sharpen_link_right=requested.sharpen_link_right;\n',
         '    out.sharpen_link_right=requested.sharpen_link_right;\n'
         '    out.sharpen_wide_left=requested.sharpen_wide_left;\n'
         '    out.sharpen_wide_right=requested.sharpen_wide_right;\n', 'copy toggles'),
        ('scalar(requested.sharpen_strength,0.f,10.f,reject_sharpen,&Settings::sharpen_strength);',
         'scalar(requested.sharpen_strength,0.f,20.f,reject_sharpen,&Settings::sharpen_strength);', 'left strength limit'),
        ('scalar(requested.sharpen_right_strength,0.f,10.f,reject_sharpen_right,&Settings::sharpen_right_strength);',
         'scalar(requested.sharpen_right_strength,0.f,20.f,reject_sharpen_right,&Settings::sharpen_right_strength);', 'right strength limit'),
        ('scalar(requested.sharpen_max_change,.05f,.40f,reject_sharpen_max,&Settings::sharpen_max_change);',
         'scalar(requested.sharpen_max_change,.05f,.80f,reject_sharpen_max,&Settings::sharpen_max_change);', 'left change limit'),
        ('scalar(requested.sharpen_right_max_change,.05f,.40f,reject_sharpen_right_max,&Settings::sharpen_right_max_change);',
         'scalar(requested.sharpen_right_max_change,.05f,.80f,reject_sharpen_right_max,&Settings::sharpen_right_max_change);', 'right change limit'),
        ('        a.sharpen_link_right==b.sharpen_link_right &&\n',
         '        a.sharpen_link_right==b.sharpen_link_right &&\n'
         '        a.sharpen_wide_left==b.sharpen_wide_left && a.sharpen_wide_right==b.sharpen_wide_right &&\n',
         'equality'),
    ])

    patch(mods / 'vr/QuadViewD3D12.hpp', [
        ('        constants.sharpen[1] = 1.f + 2.f + (encoded_unorm ? 4.f : 0.f);\n',
         '        constants.sharpen[1] = 1.f + 2.f + (encoded_unorm ? 4.f : 0.f)\n'
         '            + (settings.sharpen_wide_left ? 8.f : 0.f) // B43 extra-wide ring, left fovea\n'
         '            + ((settings.sharpen_link_right ? settings.sharpen_wide_left : settings.sharpen_wide_right) ? 16.f : 0.f);\n',
         'shader flags'),
        ('        for (float v : constants.sharpen_eye) hash_float(v);\n',
         '        for (float v : constants.sharpen_eye) hash_float(v);\n'
         '        hash_float(constants.sharpen[1]); // B43: wide-ring flags change the analysed fovea\n',
         'edge epoch hash'),
    ])
    # Startup: shorter fixed waits (log 12 Nov: 2 s warm-up hold + 3 s low-start hold).
    patch(mods / 'VR.cpp', [
        ('const bool warm = fix_active && now - m_triview_autostart_active_since > std::chrono::seconds(2);',
         'const bool warm = fix_active && now - m_triview_autostart_active_since > std::chrono::milliseconds(1000); // B43: was 2 s',
         'warm-up hold'),
        ('warm ? "Native Fix pair ready for 2 s" : "25 s timeout"',
         'warm ? "Native Fix pair ready for 1 s" : "25 s timeout"', 'warm-up log'),
        ('"[TriView][Build] B42.5 (B42.4 + all source views at origin 0: no black bar at the crop edge)"',
         '"[TriView][Build] B43 (B42.5 + per-eye extra-wide sharpen, sharpen 0-20 / 0.80, faster startup holds)"',
         'build identity'),
        ('    if (now - set_since < std::chrono::seconds(3)) return;\n    namespace vram = uevr::quadview::vram;',
         '    if (now - set_since < std::chrono::milliseconds(2000)) return; // B43: was 3 s; >=2 s so the 1 s VRAM sample is newer than the set\n    namespace vram = uevr::quadview::vram;',
         'low-start hold'),
    ])
    print('B43 startup: warm-up hold 2 s -> 1 s, low-start hold 3 s -> 2 s.')
    print('B43 sharpen: 0-20 strength, 0.05-0.80 max change, per-eye extra-wide ring toggle.')


if __name__ == '__main__':
    main()

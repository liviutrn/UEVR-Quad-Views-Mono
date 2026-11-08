#!/usr/bin/env python3
"""B39: add independent ambient spatial/temporal edge mode after B35+B38 UI overlays."""
from pathlib import Path
import sys

def once(s,a,b):
    n=s.count(a)
    if n!=1: raise RuntimeError(f'B39 UI anchor count {n}: {a[:95]!r}')
    return s.replace(a,b,1)

def main():
    root=Path(sys.argv[1])/'src/mods'
    p=root/'VR.hpp';s=p.read_text(encoding='utf-8')
    s=once(s,
        's_quadview_edge_mode_names{ "B31", "Edge V2 Instant", "Edge V2 Temporal" };',
        's_quadview_edge_mode_names{ "B31", "Edge V2 Instant", "Edge V2 Temporal", "Edge V3 Ambient Temporal" };')
    s=once(s,'s_quadview_edge_mode_names, 2)};',
             's_quadview_edge_mode_names, 3)};')
    anchor='    const ModSlider::Ptr m_quadview_legacy_anchor{ModSlider::create(generate_name("QuadViewLegacyInwardAnchorPx"), 2.f, 64.f, 12.f)};'
    s=once(s,anchor,anchor+'''
    const ModSlider::Ptr m_quadview_ambient_radius{ModSlider::create(generate_name("QuadViewAmbientRadiusPx"), 8.f, 128.f, 48.f)};
    const ModSlider::Ptr m_quadview_ambient_inside{ModSlider::create(generate_name("QuadViewAmbientInsidePx"), 8.f, 96.f, 32.f)};
    const ModSlider::Ptr m_quadview_ambient_time{ModSlider::create(generate_name("QuadViewAmbientTimeMs"), 50.f, 1500.f, 350.f)};''')
    s=once(s,'            *m_quadview_legacy_inward, *m_quadview_legacy_anchor,',
             '''            *m_quadview_legacy_inward, *m_quadview_legacy_anchor,
            *m_quadview_ambient_radius, *m_quadview_ambient_inside, *m_quadview_ambient_time,''')
    p.write_text(s,encoding='utf-8',newline='\n')

    p=root/'VR.cpp';s=p.read_text(encoding='utf-8')
    s=once(s,'                        m_quadview_edge_fast->draw("Immediate edge reach (output pixels)");',
'''                        if (m_quadview_edge_mode->value()!=3)
                            m_quadview_edge_fast->draw("Immediate edge reach (output pixels)");
                        if (m_quadview_edge_mode->value()==3) {
                            ImGui::TextWrapped("Ambient V3: average fifteen samples from groups of fovea pixels at three inward depths, then average the RGB correction across time. No live per-pixel mirroring at the exterior edge.");
                            m_quadview_ambient_radius->draw("Ambient width along edge (pixels)");
                            m_quadview_ambient_inside->draw("Ambient sampling inward (pixels)");
                            m_quadview_ambient_time->draw("Ambient temporal average (ms)");
                        }''')
    s=once(s,'                        if (m_quadview_edge_mode->value()==2) {',
             '                        if (m_quadview_edge_mode->value()>=2) {')
    s=once(s,'            requested.legacy_inward_anchor_px=m_quadview_legacy_anchor->value();',
'''            requested.legacy_inward_anchor_px=m_quadview_legacy_anchor->value();
            requested.ambient_radius_px=m_quadview_ambient_radius->value();
            requested.ambient_inside_px=m_quadview_ambient_inside->value();
            requested.ambient_time_ms=static_cast<uint32_t>(m_quadview_ambient_time->value());''')
    p.write_text(s,encoding='utf-8',newline='\n')
    print('B39 Ambient V3 mode, spatial/temporal controls and persisted settings installed')

if __name__=='__main__': main()

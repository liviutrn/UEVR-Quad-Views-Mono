#!/usr/bin/env python3
"""B40: simple motion-continuous ambient UI over B39, without legacy regressions."""
from pathlib import Path
import sys

def once(s, old, new):
    n=s.count(old)
    if n != 1:
        raise RuntimeError(f"B40 UI anchor count {n}: {old[:100]!r}")
    return s.replace(old,new,1)

def main():
    root=Path(sys.argv[1])/'src/mods'
    p=root/'VR.hpp'
    s=p.read_text(encoding='utf-8')
    s=once(s,
        '"Edge V3 Ambient Temporal" };',
        '"Edge V3 Ambient Temporal", "B40 Continuous Ambient" };')
    s=once(s,'s_quadview_edge_mode_names, 3)};',
             's_quadview_edge_mode_names, 4)};')
    s=once(s,'    const ModSlider::Ptr m_quadview_ambient_time{',
        '''    static const inline std::vector<std::string> s_quadview_b40_presets{ "Fast (75 ms)", "Balanced (200 ms)", "High (350 ms)", "Maximum (600 ms)" };
    const ModCombo::Ptr m_quadview_b40_stability{ModCombo::create(generate_name("QuadViewB40Stability"), s_quadview_b40_presets, 2)};
    const ModSlider::Ptr m_quadview_ambient_time{''')
    s=once(s,'            *m_quadview_ambient_radius, *m_quadview_ambient_inside, *m_quadview_ambient_time,',
        '''            *m_quadview_ambient_radius, *m_quadview_ambient_inside, *m_quadview_ambient_time,
            *m_quadview_b40_stability,''')
    p.write_text(s,encoding='utf-8',newline='\n')
    p=root/'VR.cpp'
    s=p.read_text(encoding='utf-8')
    s=once(s,'                    m_quadview_edge_mode->draw("Edge matcher");',
        '''                    m_quadview_edge_mode->draw("Edge matcher");
                    if (m_quadview_edge_mode->value()==4) {
                        m_quadview_edge_strength->draw("Correction strength");
                        m_quadview_b40_stability->draw("Temporal stability");
                        m_quadview_legacy_inward->draw("Original inward fovea feather (B27)");
                        ImGui::TextWrapped("Motion-continuous ambient correction: 128 pooled points, 32 robust groups per eye. History holds through gaze/head motion and unusable samples. Longer presets intentionally allow trailing colors.");
                    }''')
    s=once(s,'                    if (m_quadview_edge_mode->value()!=0) {',
        '                    if (m_quadview_edge_mode->value()!=0 && m_quadview_edge_mode->value()!=4) {')
    s=once(s,'                    m_quadview_seam_mode->draw("B31 mode (used when Edge matcher = B31)");',
        '''                    if (m_quadview_edge_mode->value()!=4) {
                    m_quadview_seam_mode->draw("B31 mode (used when Edge matcher = B31)");''')
    # Close only the legacy B31 settings branch before this same Seam Matching tree closes.
    anchor='                    ImGui::TreePop();\n                }'
    pos=s.index('m_quadview_seam_mode->draw("B31 mode (used when Edge matcher = B31)");')
    end=s.find(anchor,pos)
    if end<0: raise RuntimeError('B40 could not close legacy B31 UI branch')
    s=s[:end]+'                    } // legacy B31 settings hidden in B40\n'+s[end:]
    s=once(s,
        '            requested.ambient_time_ms=static_cast<uint32_t>(m_quadview_ambient_time->value());',
        '''            requested.ambient_time_ms=m_quadview_edge_mode->value()==4
                ? (m_quadview_b40_stability->value()==0 ? 75u :
                   m_quadview_b40_stability->value()==1 ? 200u :
                   m_quadview_b40_stability->value()==2 ? 350u : 600u)
                : static_cast<uint32_t>(m_quadview_ambient_time->value());''')
    p.write_text(s,encoding='utf-8',newline='\n')
    print('B40 continuous mode + simplified presets/UI installed')

if __name__=='__main__': main()

#!/usr/bin/env python3
"""B38: only UI controls, applied after reviewed B35 overlay."""
from pathlib import Path
import sys

def once(s,a,b):
    n=s.count(a)
    if n!=1: raise RuntimeError(f"B38 UI anchor count {n}: {a[:80]!r}")
    return s.replace(a,b,1)

def main():
    r=Path(sys.argv[1])/'src/mods'
    p=r/'VR.hpp'
    s=p.read_text()
    s=once(s,'    const ModSlider::Ptr m_quadview_edge_noise{ModSlider::create(generate_name("QuadViewEdgeV2Noise"), 0.f, .05f, .004f)};',
'''    const ModSlider::Ptr m_quadview_edge_noise{ModSlider::create(generate_name("QuadViewEdgeV2Noise"), 0.f, .05f, .004f)};
    const ModToggle::Ptr m_quadview_legacy_inward{ModToggle::create(generate_name("QuadViewLegacyInwardFeather"), true)};
    const ModSlider::Ptr m_quadview_legacy_anchor{ModSlider::create(generate_name("QuadViewLegacyInwardAnchorPx"), 2.f, 64.f, 12.f)};''')
    s=once(s,'            *m_quadview_edge_fast, *m_quadview_edge_rate, *m_quadview_edge_noise,',
'''            *m_quadview_edge_fast, *m_quadview_edge_rate, *m_quadview_edge_noise,
            *m_quadview_legacy_inward, *m_quadview_legacy_anchor,''')
    p.write_text(s)
    p=r/'VR.cpp'
    s=p.read_text()
    s=once(s,'                        m_quadview_edge_fast->draw("Immediate edge reach (output pixels)");',
'''                        m_quadview_edge_fast->draw("Immediate edge reach (output pixels)");
                        m_quadview_legacy_inward->draw("Original inward fovea feather (B27)");
                        if (m_quadview_legacy_inward->value()) {
                            m_quadview_legacy_anchor->draw("Inside seam continuity strip (pixels)");
                            ImGui::TextWrapped("Original B27 soft periphery/focus crossfade inside the fovea; B37 corrected periphery outside. The short strip joins the colors at the crop edge. Disable for unchanged B37.");
                        }''')
    s=once(s,'            requested.edge_hysteresis=m_quadview_edge_noise->value();',
'''            requested.edge_hysteresis=m_quadview_edge_noise->value();
            requested.legacy_inward_feather=m_quadview_legacy_inward->value();
            requested.legacy_inward_anchor_px=m_quadview_legacy_anchor->value();''')
    p.write_text(s)
    print('B38 isolated old inward feather toggle and boundary controls installed')

if __name__=='__main__':
    main()

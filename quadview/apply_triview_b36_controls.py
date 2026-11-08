#!/usr/bin/env python3
"""B36 controls; after B35 overlays. B31 controls and saved names are retained."""
from pathlib import Path
import sys

def once(s,a,b):
    if s.count(a)!=1: raise RuntimeError(f'B36 controls anchor count {s.count(a)}: {a[:100]!r}')
    return s.replace(a,b,1)

def main():
    r=Path(sys.argv[1])/'src/mods'
    p=r/'VR.hpp';s=p.read_text();a='    const ModCombo::Ptr m_quadview_edge_mode'
    s=once(s,a,'    const ModToggle::Ptr m_quadview_edge_padding{ModToggle::create(generate_name("QuadViewEdgeBlankPaddingGuard"), true)};\n'+a)
    a='            *m_quadview_edge_mode,';s=once(s,a,'            *m_quadview_edge_padding,\n'+a);p.write_text(s)
    p=r/'VR.cpp';s=p.read_text();a='                        m_quadview_edge_feather->draw("Inward feather (output pixels)");'
    s=once(s,a,a+'\n                        m_quadview_edge_padding->draw("Repair uniform black source padding");\n                        ImGui::TextWrapped("Context/focus blend feather remains active with Edge V2. Padding repair clamps only a detected uniformly zero rim; it does not move or stretch the crop.");')
    a='            requested.edge_reach_px=m_quadview_edge_reach->value();';s=once(s,a,'            requested.edge_padding_guard=m_quadview_edge_padding->value();\n'+a);p.write_text(s)
    print('B36: original feather + optional automatic source padding guard controls')
if __name__=='__main__':main()

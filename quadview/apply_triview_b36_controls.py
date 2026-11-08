#!/usr/bin/env python3
"""B36 explains restored standard blend, without a source-padding workaround."""
from pathlib import Path
import sys
p=Path(sys.argv[1])/'src/mods/VR.cpp'
s=p.read_text()
a='                        m_quadview_edge_feather->draw("Inward feather (output pixels)");'
assert s.count(a)==1,'B36 blend UI anchor mismatch'
s=s.replace(a,a+'\n                        ImGui::TextWrapped("Context/focus blend feather is active with Edge V2. The wider of the fractional blend and inward-pixel feather applies.");')
p.write_text(s)

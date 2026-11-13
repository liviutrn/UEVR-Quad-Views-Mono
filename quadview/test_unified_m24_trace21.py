#!/usr/bin/env python3
"""Static post-generation integration check: M2.4 and trace #21 must coexist."""
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
vr = (root / 'src/mods/VR.cpp').read_text(encoding='utf-8')
ox = (root / 'src/mods/vr/runtimes/OpenXR.cpp').read_text(encoding='utf-8')
d3d = (root / 'src/mods/vr/D3D12Component.cpp').read_text(encoding='utf-8')
hdr = (root / 'src/mods/vr/ResearchTrace21.hpp').read_text(encoding='utf-8')
checks = {
    'M2.4 scene depth packet Present epoch': 'm24_current_epoch()' in vr,
    'M2.4 vertical taper controls': 'm_duo_m24_vertical->draw(' in vr,
    'M2.4 distance fade controls': 'm_duo_m24_distance->draw(' in vr,
    'M2.4 epoch producer boundary': 'm24_note_present()' in d3d,
    'M2.4 fine depth ramp': 'm24_fine_weight()' in d3d,
    'Trace game tick': 'research_trace21::kGameTick' in vr,
    'Trace render': 'research_trace21::kRender' in ox,
    'Trace pose': 'research_trace21::kPose' in ox,
    'Trace submit': 'research_trace21::kSubmit' in ox,
    'Trace after session destroy': 'research_trace21::Sink().FlushNow();' in ox,
    'Trace off by default': 'enabled_=Key(flag)=="1";' in hdr,
    'Trace CSV schema': 'kind,frame,secondary,tick,qpc_ns,display_xr,pose_xr,aux,extra' in hdr,
    'Trace only on opt-in': 'if (research_trace21::Sink().Enabled())' in vr,
}
for name,ok in checks.items():
    print(('PASS' if ok else 'FAIL') + ': ' + name)
if not all(checks.values()):
    sys.exit(1)
print('PASS Unified M2.4 + World Trace #21 post-generation static contract')

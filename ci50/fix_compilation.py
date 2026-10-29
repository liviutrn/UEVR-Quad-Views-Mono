#!/usr/bin/env python3
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
def replace(rel,before,after):
    p=root/rel;s=p.read_text(encoding="utf-8-sig")
    if s.count(before)!=1:
        raise RuntimeError("%s: expected 1 exact anchor, found %d: %r"%(rel,s.count(before),before))
    p.write_text(s.replace(before,after,1),encoding="utf-8",newline="")
replace("src/mods/vr/d3d12/StockDibrDepth.hpp",
    "std::vector<uevr::duoview::diag::Candidate> snapshot_candidates() {",
    "std::vector<uevr::duoview::diag::Candidate> snapshot_candidates(uint64_t selected_left_serial=0,uint64_t selected_right_serial=0) {")
replace("src/mods/vr/D3D12Component.cpp",
    "auto candidates=m_stock_dibr_depth->snapshot_candidates();",
    "auto candidates=m_stock_dibr_depth->snapshot_candidates(depths.left_serial,depths.right_serial);")
print("CI50: selected fovea/periphery capture serials are bound through the producer and exporter")

# R32G32_FLOAT carries exactly two components, not three. Avoid reading a
# non-existent blue channel when constructing RGB diagnostic previews.
replace("src/mods/vr/d3d12/DuoViewDiagnosticDump.hpp",
    "q[0]=encode(im.bytes_per_pixel>=8 ? component(p,im.format,2) : x);",
    "q[0]=encode((im.format==DXGI_FORMAT_R16G16B16A16_FLOAT || im.format==DXGI_FORMAT_R32G32B32A32_FLOAT) ? component(p,im.format,2) : x);")
print("CI50: corrected two-channel float preview bounds")

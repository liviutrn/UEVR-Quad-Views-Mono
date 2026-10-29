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

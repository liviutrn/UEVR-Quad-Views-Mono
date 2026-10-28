#!/usr/bin/env python3
"""CI31 integration smoke: verifies patched backend has observation counters.
Windows WARP tests additionally execute real command-submitted depth frames.
"""
from pathlib import Path
import sys
if len(sys.argv)!=2:raise SystemExit("usage: test_provenance_audit.py <patched backend>")
s=(Path(sys.argv[1])/"src/mods/vr/d3d12/StockDibrDepth.hpp").read_text(encoding="utf-8-sig")
checks={
  "diagnostic normal-only gating": "if(duoview_source_sizes[0] && !snapshot_armed)" in s,
  "real shape policy function": "ci31_shape_matches[k]=duoview_depth_shape(" in s,
  "tracks missing shapes": "ci31_viewport_shape_neither" in s,
  "tracks ambiguous matches": "ci31_viewport_shape_ambiguous" in s,
  "counts accepted copy after capture": s.index("++recorded_this_interval; ++captured;")<s.index("++ci31_viewport_shape_copied[k];"),
  "counts rejects": "++ci31_viewport_shape_budget_skipped[k]" in s,
  "no false eye proof": 'matchedEyes=UNVERIFIED' in s,
  "all normal metrics visible": "CI31normalViewportMatches=" in s and "CI31normalCopies=" in s and "CI31budgetSkipped=" in s,
  "keeps CI30 probation": "if(auto_candidate_streak<3)" in s,
}
for label,ok in checks.items():print(("PASS" if ok else "FAIL"),label)
if not all(checks.values()):raise SystemExit(1)

#!/usr/bin/env python3
"""CI30 static integration/intent tests; not a substitute for headset testing."""
from pathlib import Path
import sys
if len(sys.argv)!=2:raise SystemExit("Usage: test_gameplay_guards.py <patched backend>")
root=Path(sys.argv[1])
d=(root/"src/mods/vr/d3d12/StockDibrDepth.hpp").read_text(encoding="utf-8-sig")
s=(root/"src/mods/vr/DuoViewStereoCompositeRaster.hlsl").read_text(encoding="utf-8-sig")
checks={
"two viewport-size capture buckets":'std::array<NormalSizeBucket,2> normal_size_buckets{};' in d,
"no false semantic eye claim":'viewport-SIZE bucketing' in d,
"bounded bucket capacity":'normal_size_buckets[normal_bucket].captured>=NormalCapacity/2' in d,
"copy accounting only post-copy":'++normal_size_buckets[normal_bucket].captured;' in d and d.index('++recorded_this_interval; ++captured;')<d.index('++normal_size_buckets[normal_bucket].captured;'),
"snapshot mode not budgeted":'if (duoview_source_sizes[0] && !snapshot_armed)' in d,
"stable source/write-version rank pin":'const auto guarded=choose_duoview_depth_pair(' in d and 'stage_key' in d,
"auto probation only":'if(left_selector==0 && right_selector==0)' in d,
"fresh epoch eligibility before auto":'const auto ids=preview_indices();' in d and d.index('const auto ids=preview_indices();')<d.index('if(auto_candidate_streak<3)'),
"missing pair resets probation":'if(ids.size()<2) {' in d and 'auto_candidate_streak=0;' in d,
"screen/eye source proof not asserted":'matchedEyes=UNVERIFIED' in d,
"original experimental stereo remains":'float4 PSNativeStereo(VertexOut i)' in s,
"R5 queue retirement still on":'snapshot_leases[i]=true;' in d and 'finish_frame(bool keep_snapshot_armed=false)' in d,
"debug telemetry":'autoPairChanges=' in d and 'extraShapes=' in d,
}
for k,v in checks.items():print(("PASS " if v else "FAIL ")+k)
if not all(checks.values()):raise SystemExit(1)

#!/usr/bin/env python3
"""CI31 viewport-shape telemetry ONLY. Applied after CI30 gameplay guards.
A shape match does not prove eye role, view frame, render stage or matrix.
No changes to the V3 rendering path, capacity, eligibility or pairing policy.
"""
from pathlib import Path
import sys
if len(sys.argv)!=2:raise SystemExit("usage: apply_provenance_audit.py <patched backend>")
root=Path(sys.argv[1]).resolve()
depth=root/"src/mods/vr/d3d12/StockDibrDepth.hpp"
s=depth.read_text(encoding="utf-8-sig")
def edit(old,new,label):
    global s
    n=s.count(old)
    if n!=1:raise RuntimeError(f"CI31 {label}: expected one anchor, got {n}")
    s=s.replace(old,new,1)
edit("    uint64_t normal_extra_shape_skips{};",
"""    uint64_t normal_extra_shape_skips{};
    // Shape observations are NOT certified left/right producer identity.
    uint64_t ci31_viewport_shape_matches[2]{};
    uint64_t ci31_viewport_shape_copied[2]{};
    uint64_t ci31_viewport_shape_budget_skipped[2]{};
    uint64_t ci31_viewport_shape_ambiguous{};
    uint64_t ci31_viewport_shape_neither{};""","counters")
edit("""            if (kind == Layout::Invalid) { ++rejected; ++reject_reasons[3]; continue; }
            size_t normal_bucket = 2;""",
"""            if (kind == Layout::Invalid) { ++rejected; ++reject_reasons[3]; continue; }
            std::array<bool,2> ci31_shape_matches{};
            if(duoview_source_sizes[0] && !snapshot_armed) {
                for(size_t k=0;k<2;++k) {
                    ci31_shape_matches[k]=duoview_depth_shape(
                        source_viewport.Width,source_viewport.Height,
                        duoview_source_sizes[2*k],duoview_source_sizes[2*k+1]);
                    if(ci31_shape_matches[k])++ci31_viewport_shape_matches[k];
                }
                if(ci31_shape_matches[0] && ci31_shape_matches[1])
                    ++ci31_viewport_shape_ambiguous;
                if(!ci31_shape_matches[0] && !ci31_shape_matches[1])
                    ++ci31_viewport_shape_neither;
            }
            size_t normal_bucket = 2;""","normal-only viewport shape observations")
edit("""                if(normal_bucket==2){++normal_extra_shape_skips;continue;}
                if(normal_size_buckets[normal_bucket].captured>=NormalCapacity/2) {
                    ++normal_bucket_skips[normal_bucket];continue;
                }""",
"""                if(normal_bucket==2) {
                    ++normal_extra_shape_skips;
                    for(size_t k=0;k<2;++k)if(ci31_shape_matches[k])
                        ++ci31_viewport_shape_budget_skipped[k];
                    continue;
                }
                if(normal_size_buckets[normal_bucket].captured>=NormalCapacity/2) {
                    ++normal_bucket_skips[normal_bucket];
                    for(size_t k=0;k<2;++k)if(ci31_shape_matches[k])
                        ++ci31_viewport_shape_budget_skipped[k];
                    continue;
                }""","budget rejects with shape labels")
edit("""            if(normal_bucket<2){
                ++normal_size_buckets[normal_bucket].captured;
                ++normal_bucket_captures[normal_bucket];
            }""",
"""            if(normal_bucket<2){
                ++normal_size_buckets[normal_bucket].captured;
                ++normal_bucket_captures[normal_bucket];
                for(size_t k=0;k<2;++k)if(ci31_shape_matches[k])
                    ++ci31_viewport_shape_copied[k];
            }""","post-record copy accounting")
edit('            " autoDeferred=" + std::to_string(auto_candidate_deferred);',
"""            " autoDeferred=" + std::to_string(auto_candidate_deferred) +
            " CI31normalViewportMatches=" + std::to_string(ci31_viewport_shape_matches[0]) + "," + std::to_string(ci31_viewport_shape_matches[1]) +
            " CI31normalCopies=" + std::to_string(ci31_viewport_shape_copied[0]) + "," + std::to_string(ci31_viewport_shape_copied[1]) +
            " CI31budgetSkipped=" + std::to_string(ci31_viewport_shape_budget_skipped[0]) + "," + std::to_string(ci31_viewport_shape_budget_skipped[1]) +
            " CI31ambiguousShapes=" + std::to_string(ci31_viewport_shape_ambiguous) +
            " CI31neitherShape=" + std::to_string(ci31_viewport_shape_neither) +
            " matchedEyes=UNVERIFIED";""","status summary")
depth.write_text(s,encoding="utf-8",newline="")
print("CI31: normal producer viewport/recorded/budget shape statistics (unverified role).")

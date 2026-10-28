#!/usr/bin/env python3
"""CI30 conservative gameplay guard: split capture by actual viewport SIZE CLASS,
and require repeated Auto candidate identity before using stereo. This does not
prove scene-eye/frame/stage provenance, and must remain experimental.
Applied after enable_true_stereo_xr.py, never to a validated V3 baseline.
"""
from pathlib import Path
import sys
if len(sys.argv)!=2:
    raise SystemExit("Usage: apply_gameplay_guards.py <patched backend>")
root=Path(sys.argv[1]).resolve()
def edit(path,old,new,what):
    p=root/path
    s=p.read_text(encoding="utf-8-sig")
    count=s.count(old)
    if count!=1:
        raise RuntimeError(f"CI30 {what}: expected exactly one anchor, got {count}")
    p.write_text(s.replace(old,new,1),encoding="utf-8",newline="")
depth="src/mods/vr/d3d12/StockDibrDepth.hpp"
edit(depth,'    bool snapshot_armed{};',
'''    bool snapshot_armed{};
    // This is viewport-SIZE bucketing, deliberately NOT a camera/eye claim.
    // Two distinct scale classes get six producer slots each; previously
    // twelve early, repeated low-resolution passes could exhaust all slots.
    struct NormalSizeBucket { double w{},h{};uint32_t captured{}; };
    std::array<NormalSizeBucket,2> normal_size_buckets{};
    uint64_t normal_bucket_captures[2]{};
    uint64_t normal_bucket_skips[2]{};
    uint64_t normal_extra_shape_skips{};
    std::array<std::uintptr_t,2> auto_candidate_identity{};
    uint64_t auto_last_evaluated_epoch{};
    uint32_t auto_candidate_streak{};
    uint64_t auto_candidate_changes{}, auto_candidate_deferred{};
''',"bounded capture and candidate state")
edit(depth,'''            if (kind == Layout::Invalid) { ++rejected; ++reject_reasons[3]; continue; }''',
'''            if (kind == Layout::Invalid) { ++rejected; ++reject_reasons[3]; continue; }
            size_t normal_bucket = 2;
            if (duoview_source_sizes[0] && !snapshot_armed) {
                // Dimensions of a SINGLE candidate cannot prove L versus R:
                // at different DLSS scales both can match either source.
                // Reserve capacity for two distinct viewport size classes.
                for(size_t k=0;k<normal_size_buckets.size();++k) {
                    const auto& c=normal_size_buckets[k];
                    if(c.w>0 && std::abs(c.w-source_viewport.Width)/c.w<0.25 &&
                                  std::abs(c.h-source_viewport.Height)/c.h<0.25) {
                        normal_bucket=k;break;
                    }
                }
                if(normal_bucket==2) {
                    for(size_t k=0;k<normal_size_buckets.size();++k) {
                        if(normal_size_buckets[k].w==0) {
                            normal_bucket=k;
                            normal_size_buckets[k].w=source_viewport.Width;
                            normal_size_buckets[k].h=source_viewport.Height;
                            break;
                        }
                    }
                }
                if(normal_bucket==2){++normal_extra_shape_skips;continue;}
                if(normal_size_buckets[normal_bucket].captured>=NormalCapacity/2) {
                    ++normal_bucket_skips[normal_bucket];continue;
                }
            }''',"two-stratum normal capture budget")
edit(depth,'            ++recorded_this_interval; ++captured;',
'''            ++recorded_this_interval; ++captured;
            if(normal_bucket<2){
                ++normal_size_buckets[normal_bucket].captured;
                ++normal_bucket_captures[normal_bucket];
            }''',"account only successfully submitted copy commands")
edit(depth,'''        snapshot_armed=keep_snapshot_armed;
        ++epoch; recorded_this_interval = 0;
        executed_proofs.clear();''',
'''        snapshot_armed=keep_snapshot_armed;
        ++epoch; recorded_this_interval = 0;
        normal_size_buckets={};
        executed_proofs.clear();''',"reset size classes at frame boundary")
edit(depth,'            " proofHistory=[" + proofs + "]";',
'''            " proofHistory=[" + proofs + "]" +
            " CI30sizeClassesCaptured=" + std::to_string(normal_bucket_captures[0]) + "," + std::to_string(normal_bucket_captures[1]) +
            " classBudgetSkips=" + std::to_string(normal_bucket_skips[0]) + "," + std::to_string(normal_bucket_skips[1]) +
            " extraShapes=" + std::to_string(normal_extra_shape_skips) +
            " autoPairChanges=" + std::to_string(auto_candidate_changes) +
            " autoDeferred=" + std::to_string(auto_candidate_deferred);''',"telemetry in existing R5 status")
edit(depth,'        if(ids.size()<2)return r;',
'''        if(ids.size()<2) {
            auto_candidate_streak=0;
            auto_candidate_identity={};
            return r;
        }''',"reset probation on missing captured pair")
edit(depth,'        if(!chosen.valid)return r;',
'''        if(!chosen.valid) {
            auto_candidate_streak=0;
            auto_candidate_identity={};
            return r;
        }''',"reset probation on geometry mismatch")
edit(depth,'        const size_t a=ids[chosen.left],b=ids[chosen.right];',
'''        const size_t a=ids[chosen.left],b=ids[chosen.right];
        if(left_selector==0 && right_selector==0) {
            const std::array<std::uintptr_t,2> current{
                reinterpret_cast<std::uintptr_t>(slots[a].source.Get()),
                reinterpret_cast<std::uintptr_t>(slots[b].source.Get())
            };
            // No reuse of stale *textures*: this key ONLY gates fresh epoch
            // candidates, which still must have passed the geometry test.
            // It is a flicker safety gate, NOT source eye/stage verification.
            if(auto_last_evaluated_epoch!=epoch) {
                const bool consecutive=auto_last_evaluated_epoch &&
                    epoch==auto_last_evaluated_epoch+1;
                if(!consecutive || current!=auto_candidate_identity) {
                    if(auto_last_evaluated_epoch &&
                       current!=auto_candidate_identity)++auto_candidate_changes;
                    auto_candidate_identity=current;
                    auto_candidate_streak=1;
                } else if(auto_candidate_streak<1000000u) {
                    ++auto_candidate_streak;
                }
                auto_last_evaluated_epoch=epoch;
            }
            if(auto_candidate_streak<3) {
                ++auto_candidate_deferred;
                last="CI30: Auto candidate identity unsteady; waiting in V3 mono";
                return r;
            }
        }''',"3 consecutive GPU-eligible candidate evaluations before Auto stereo")
print("CI30 gameplay guards applied (experimental; camera/frame stage not proven)")

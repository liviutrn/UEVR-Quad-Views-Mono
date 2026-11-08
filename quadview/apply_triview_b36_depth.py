#!/usr/bin/env python3
"""B36: preserve the newest still-selectable periphery depth during recapture."""
from pathlib import Path
import sys


def once(src: str, before: str, after: str, label: str) -> str:
    count = src.count(before)
    if count != 1:
        raise RuntimeError(f"B36 {label}: expected one anchor, found {count}")
    return src.replace(before, after, 1)


def main() -> None:
    backend = Path(sys.argv[1])
    header = backend / "src/mods/vr/QuadViewNgxDepth.hpp"
    policy = Path(__file__).with_name("QuadViewDepthContinuity.hpp")
    (header.parent / policy.name).write_text(policy.read_text())
    src = header.read_text()
    src = once(src, "#include <vector>\n", '#include <vector>\n#include "QuadViewDepthContinuity.hpp"\n', "policy include")
    before = """        std::shared_ptr<DepthSnapshot> slot;
        for (auto& candidate : pool_) {
            const uint64_t completed = candidate->producer_fence ? candidate->producer_fence->GetCompletedValue() : 0;
"""
    after = """        // Preserve the newest depth that latest_recent_submitted() could still
        // return until a newer valid copy is submitted. Otherwise a singleton
        // pool is made unavailable between Record and Submit at ordinary cadence.
        DepthSnapshot* protected_slot=nullptr;
        uint64_t protected_sequence=0;
        for (const auto& candidate : pool_) {
            const uint64_t completed = candidate->producer_fence ? candidate->producer_fence->GetCompletedValue() : 0;
            const auto age = candidate->submitted && now >= candidate->submitted_at
                ? std::chrono::duration_cast<std::chrono::milliseconds>(now - candidate->submitted_at).count() : 250;
            const continuity::Candidate policy_candidate{candidate->sequence,candidate->out_w,candidate->out_h,
                age < 0 ? 0u : age >= 250 ? 250u : static_cast<uint32_t>(age),
                candidate->submitted,candidate->valid_evaluation,
                candidate->texture.Get()!=nullptr,candidate->foreign_queue,
                depth_copy_complete(completed,candidate->producer_fence_value)};
            if (continuity::protectable(policy_candidate,want_w,want_h) &&
                (!protected_slot || candidate->sequence>protected_sequence)) {
                protected_slot=candidate.get();
                protected_sequence=candidate->sequence;
            }
        }
        std::shared_ptr<DepthSnapshot> slot;
        for (auto& candidate : pool_) {
            if (candidate.get()==protected_slot) continue;
            const uint64_t completed = candidate->producer_fence ? candidate->producer_fence->GetCompletedValue() : 0;
"""
    src = once(src, before, after, "reuse scan")
    header.write_text(src)


if __name__ == "__main__":
    main()

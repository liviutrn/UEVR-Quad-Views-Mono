#!/usr/bin/env python3
"""Independent B25 review: capture why GT native owners fail live checks.

No bypass of vtable, world, device, or UObject checks. No new allocations,
fences or extra lifetime inspections in the success path.
"""
from pathlib import Path
import sys

OLD = '''        if (!owner || owner->resource_allocation_generation!=snapshot->resource_allocation_generation ||
            !current_device || owner->render_target!=targets.render_targets[i] || !owner->live()) {
            SPDLOG_ERROR_EVERY_N_SEC(1,"[QuadViews][TargetLifetime] stale source role={} target={:x}; refusing virtual dispatch",
                i,reinterpret_cast<uintptr_t>(targets.render_targets[i]));
            return false;
        }'''

NEW = '''        // A single rejected native target must never be dispatched. Distinguish
        // benign world reallocation from same-world resource identity changes.
        const bool generation_matches=owner &&
            owner->resource_allocation_generation==snapshot->resource_allocation_generation;
        const bool render_target_matches=owner && owner->render_target==targets.render_targets[i];
        const bool owner_live=generation_matches && current_device &&
            render_target_matches && owner->live();
        if (!owner_live) {
            const char* reason=!owner ? "missing-owner" :
                !generation_matches ? "allocation-generation-mismatch" :
                !current_device ? "D3D12-device-mismatch" :
                !render_target_matches ? "render-target-identity-mismatch" :
                "Unreal-owner-property-resource-or-hook-mismatch";
            SPDLOG_ERROR_EVERY_N_SEC(1,"[TriView][TargetLifetime] rejected source role={} allocation={} publication={} reason={} target={:x}",
                i, snapshot->resource_allocation_generation, targets.generation,
                reason, reinterpret_cast<uintptr_t>(targets.render_targets[i]));
            return false;
        }'''


def main():
    path=Path(sys.argv[1])/"src/mods/vr/FFakeStereoRenderingHook.cpp"
    s=path.read_text(encoding="utf-8")
    if s.count(OLD)!=1:
        raise RuntimeError(f"B25 final owner health-check block count={s.count(OLD)}; generated source changed")
    s=s.replace(OLD,NEW,1)
    path.write_text(s,encoding="utf-8",newline="\n")
    print("B25: stale owner failure reason and allocation/publication identity, unchanged safety admission")


if __name__=="__main__":
    main()

#!/usr/bin/env python3
"""Check B18 resource invariants in the actual fully generated backend."""
from pathlib import Path
import sys


def main():
    base=Path(sys.argv[1])/'src/mods/vr'
    c=(base/'FFakeStereoRenderingHook.cpp').read_text()
    h=(base/'FFakeStereoRenderingHook.hpp').read_text()
    assert 'valid_resource_publication(generation,owner->generation,' in h
    assert 'owner->resource_allocation_generation!=snapshot->resource_allocation_generation' in c
    assert 'owner_device.Get()==hook->get_device()' in c
    assert 'engine->get_world())!=targets.world_identity' in c
    assert 'if (build->reused[i]) continue; // Keep the exact existing owner and gamma table.' in c
    assert 'republish_resource_snapshot(reused,build->generation)' in c
    assert 'snapshot->resource_allocation_generation=owner.resource_allocation_generation' in c
    assert 'build->reused[0] || sdk::UTexture::commit_validated_render_resource_offsets_texture2d(' in c
    # Only newly allocated owners may have their hook installed or rolled back.
    build=c[c.index('struct VRRenderTargetManager_Base::QuadViewNativeTargetBuild {'):c.index('bool VRRenderTargetManager_Base::create_ue58_ui_texture()')]
    assert 'std::array<std::shared_ptr<QuadViewNativeTargetOwner>,4> owners{}; // New allocations only.' in build
    assert 'for (auto& prior:build->owners) if (prior && prior->gamma_hooked)' in build
    assert 'for (auto& owner:build->owners)' in build
    assert 'for (auto& owner:build->reused)' not in build
    assert 'No world; native publication invalidated, leased owners retained' in build
    # Retain the failure-closed fence and vtable gates after all overlays.
    assert 'completed!=UINT64_MAX && completed>=owner->retire_fence_value' in c
    assert 'live_vtable==reinterpret_cast<uintptr_t>(owner->hooked_vtable.data())' in c
    assert 'is_writable_process_range(address,sizeof(uintptr_t))' in c
    assert (base/'QuadViewResourceReuse.hpp').read_bytes()==(Path(__file__).parent/'QuadViewResourceReuse.hpp').read_bytes()
    print('B18 resource contracts passed: three roles, allocation/publication identity, reused hook ownership, world/device gates, conservative retirement')

if __name__=='__main__': main()

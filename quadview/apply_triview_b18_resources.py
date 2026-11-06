#!/usr/bin/env python3
"""B18: same-world per-role source reuse; publication and allocation identities stay distinct."""
from pathlib import Path
import sys


def one(s, old, new):
    if s.count(old)!=1:
        raise RuntimeError(f'B18 resource anchor count {s.count(old)}: {old[:100]!r}')
    return s.replace(old,new,1)


def transform_header(s):
    s='#include "QuadViewResourceReuse.hpp"\n'+s
    s=one(s,'        std::shared_ptr<const void> owner_lifetime{};',
          '        std::shared_ptr<const void> owner_lifetime{};\n'
          '        uint64_t resource_allocation_generation{}; // Native targets: immutable physical owner identity.\n')
    s=one(s,'                if (!owner || !native || !render_targets[i]) return false;',
          '                if (!owner || !native || !render_targets[i] || !owner->owner_lifetime ||\n'
          '                    !uevr::quadview::valid_resource_publication(generation,owner->generation,\n'
          '                        owner->resource_allocation_generation)) return false;')
    return s


def transform_cpp(s):
    s=one(s,'    uintptr_t texture_resource_identity{};\n    uintptr_t rhi_texture_identity{};',
          '    uintptr_t texture_resource_identity{};\n    uintptr_t rhi_texture_identity{};\n'
          '    uint64_t resource_allocation_generation{}; // Set once before any engine allocation/publication.\n')
    start=s.index('struct VRRenderTargetManager_Base::QuadViewNativeTargetBuild {')
    end=s.index('\nbool VRRenderTargetManager_Base::create_ue58_ui_texture()',start)
    b=s[start:end]
    b=one(b,'    std::array<std::shared_ptr<QuadViewNativeTargetOwner>,4> owners{};',
          '    std::array<std::shared_ptr<QuadViewNativeTargetOwner>,4> owners{}; // New allocations only.\n'
          '    std::array<std::shared_ptr<const SceneCaptureTargetSnapshot>,4> reused{};\n'
          '    uevr::quadview::NativeResourceReusePlan reuse_plan{};')
    b=one(b,'    if (!GameThreadWorker::get().is_same_thread() || !targets.generation || !targets.world_identity) return false;',
          '    if (!GameThreadWorker::get().is_same_thread() || !targets.generation || !targets.world_identity) return false;\n'
          '    auto* engine=sdk::UGameEngine::get();\n'
          '    if (!engine || reinterpret_cast<uintptr_t>(engine->get_world())!=targets.world_identity) return false;')
    b=one(b,'        if (!owner || owner->render_target!=targets.render_targets[i] || !owner->live()) {',
          '        Microsoft::WRL::ComPtr<ID3D12Device> owner_device{};\n'
          '        const auto* hook=g_framework ? g_framework->get_d3d12_hook().get() : nullptr;\n'
          '        const bool current_device=owner && owner->native_resource && hook &&\n'
          '            SUCCEEDED(owner->native_resource->GetDevice(IID_PPV_ARGS(&owner_device))) &&\n'
          '            owner_device.Get()==hook->get_device();\n'
          '        if (!owner || owner->resource_allocation_generation!=snapshot->resource_allocation_generation ||\n'
          '            !current_device || owner->render_target!=targets.render_targets[i] || !owner->live()) {')
    b=one(b,'    if (!world || !kismet) {',
          '    if (!world) {\n'
          '        // GT observation invalidates publication/build admission; existing packet leases still retire normally.\n'
          '        retire_quadview_native_target_set();\n'
          '        SPDLOG_INFO_EVERY_N_SEC(2,"[TriView][Resources] No world; native publication invalidated, leased owners retained");\n'
          '        return false;\n'
          '    }\n'
          '    if (!kismet) {')
    b=one(b,'    std::shared_ptr<QuadViewNativeTargetBuild> build{};',
          '    const auto reuse_source=quadview_native_target_set_snapshot.load(std::memory_order_acquire);\n'
          '    const bool reuse_live=reuse_source && reuse_source->world_identity==world_identity &&\n'
          '        reuse_source->complete() && quadview_native_targets_live(*reuse_source);\n'
          '    const auto reuse_plan=uevr::quadview::plan_native_resource_reuse(\n'
          '        reuse_live,reuse_live,reuse_source ? reuse_source->extents : decltype(extents){},extents);\n'
          '    std::shared_ptr<QuadViewNativeTargetBuild> build{};')
    # decltype(extents) is reference; use concrete alias for empty extent set.
    b=b.replace('decltype(extents){}','uevr::quadview::NativeResourceExtents{}')
    b=one(b,'        build->extents=extents;',
          '        build->extents=extents; build->reuse_plan=reuse_plan;\n'
          '        for (size_t i=0;i!=4;++i) if (reuse_plan.reuses(i)) build->reused[i]=reuse_source->target_owners[i];')
    b=one(b,'    // Use the same world actor -> component TextureTarget property chain as',
          '    SPDLOG_INFO("[TriView][Resources] build={} reuse_mask={} new_color_mib={:.1f} (payload estimate)",\n'
          '        build->generation,unsigned(build->reuse_plan.reuse_mask),double(build->reuse_plan.new_color_bytes)/(1024.0*1024.0));\n\n'
          '    // Use the same world actor -> component TextureTarget property chain as')
    b=one(b,'            if (i==1) continue; // Do not spawn a holder or allocate a texture.',
          '            if (i==1) continue; // Do not spawn a holder or allocate a texture.\n'
          '            if (build->reused[i]) continue; // Keep the exact existing owner and gamma table.')
    b=one(b,'            build->owners[i]=owner;',
          '            build->owners[i]=owner;\n'
          '            owner->resource_allocation_generation=build->generation;')
    b=one(b,'            const auto& owner=build->owners[i];\n            if (!owner || !owner->texture.valid()) return false;',
          '            if (const auto& reused=build->reused[i]; reused) {\n'
          '                const auto owner=std::static_pointer_cast<const QuadViewNativeTargetOwner>(reused->owner_lifetime);\n'
          '                if (!owner || owner->resource_allocation_generation!=reused->resource_allocation_generation ||\n'
          '                    !owner->live() || !owner->native_resource) return false;\n'
          '                Microsoft::WRL::ComPtr<ID3D12Device> owner_device{};\n'
          '                const auto* hook=g_framework ? g_framework->get_d3d12_hook().get() : nullptr;\n'
          '                if (!hook || FAILED(owner->native_resource->GetDevice(IID_PPV_ARGS(&owner_device))) ||\n'
          '                    owner_device.Get()!=hook->get_device()) return false;\n'
          '                // The installed gamma vtable is ours, not module-owned: preserve its original validation/owner.\n'
          '                chains[i]={reinterpret_cast<sdk::FTextureRenderTargetResource*>(owner->texture_resource_identity),\n'
          '                    owner->render_target,reused->rhi_texture,owner->native_resource};\n'
          '                continue;\n'
          '            }\n'
          '            const auto& owner=build->owners[i];\n            if (!owner || !owner->texture.valid()) return false;')
    b=one(b,'            build->owners[0]->texture.get(),STALKER2_UE55_UTEXTURE_PRIVATE_RESOURCE_OFFSET,',
          '            build->reused[0] ? reinterpret_cast<sdk::UTexture*>(build->reused[0]->owner_texture) : build->owners[0]->texture.get(),\n'
          '            STALKER2_UE55_UTEXTURE_PRIVATE_RESOURCE_OFFSET,')
    b=one(b,'        const bool texture_offsets=sdk::UTexture::commit_validated_render_resource_offsets_texture2d(',
          '        const bool texture_offsets=build->reused[0] || sdk::UTexture::commit_validated_render_resource_offsets_texture2d(')
    b=one(b,'        const bool render_target_offset=sdk::FTextureRenderTargetResource::commit_validated_render_target_vtable_offset(',
          '        const bool render_target_offset=build->reused[0] || sdk::FTextureRenderTargetResource::commit_validated_render_target_vtable_offset(')
    b=one(b,'        sdk::FRenderTarget::update_offsets(chains[0].render_target);',
          '        if (!build->reused[0]) sdk::FRenderTarget::update_offsets(chains[0].render_target);')
    b=one(b,'        if (!gamma_index || *gamma_index>=build->owners[0]->hooked_vtable.size()) {',
          '        if (!gamma_index || *gamma_index>=std::tuple_size<decltype(QuadViewNativeTargetOwner::hooked_vtable)>::value) {')
    # Do not roll back or reinstall reused owners. Their old packets may still execute.
    b=one(b,'            auto& owner=*build->owners[i]; auto* frt=chains[i].render_target;',
          '            if (const auto& reused=build->reused[i]; reused) {\n'
          '                auto snapshot=uevr::quadview::republish_resource_snapshot(reused,build->generation);\n'
          '                if (!snapshot) return false; // Fail closed without mutating a live owner.\n'
          '                target_set->target_owners[i]=std::move(snapshot);\n'
          '                target_set->render_targets[i]=chains[i].render_target;\n'
          '                target_set->native_sources[i]=chains[i].native_resource;\n'
          '                continue;\n'
          '            }\n'
          '            auto& owner=*build->owners[i]; auto* frt=chains[i].render_target;')
    b=one(b,'            snapshot->generation=build->generation; snapshot->width=build->extents[i][0]; snapshot->height=build->extents[i][1];',
          '            snapshot->generation=build->generation; snapshot->resource_allocation_generation=owner.resource_allocation_generation;\n'
          '            snapshot->width=build->extents[i][0]; snapshot->height=build->extents[i][1];')
    # Make repeated unknown-vtable retention observable, preserving all safety checks.
    s=s[:start]+b+s[end:]
    s=one(s,'                        // Do not free our hook table if another owner changed this vtable.\n                        safe_to_delete=false;',
          '                        // Do not free our hook table if another owner changed this vtable.\n'
          '                        SPDLOG_WARNING_EVERY_N_SEC(10,"[TriView][Resources] Retaining fenced native owner: FRenderTarget vtable changed; engine destruction proof unavailable");\n'
          '                        safe_to_delete=false;')
    return s


def main():
    base=Path(sys.argv[1])/'src/mods/vr'
    operations={base/'FFakeStereoRenderingHook.hpp':transform_header,base/'FFakeStereoRenderingHook.cpp':transform_cpp}
    results={p:fn(p.read_text(encoding='utf-8')) for p,fn in operations.items()}
    for p,value in results.items(): p.write_text(value,encoding='utf-8',newline='\n')
    (base/'QuadViewResourceReuse.hpp').write_text((Path(__file__).parent/'QuadViewResourceReuse.hpp').read_text(),encoding='utf-8',newline='\n')
    print('B18 resources: immutable allocation leases reused per role; publication generations remain independent')

if __name__=='__main__': main()

#!/usr/bin/env python3
"""Give every QV source the working Native Fix actor/component texture owner."""
from pathlib import Path
import sys


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Build51 lifetime anchor count {text.count(old)}: {old[:120]!r}')
    return text.replace(old, new, 1)


def main():
    base = Path(sys.argv[1]) / 'src/mods/vr'
    cp, hp = base / 'FFakeStereoRenderingHook.cpp', base / 'FFakeStereoRenderingHook.hpp'
    c, h = cp.read_text(), hp.read_text()
    c = '#include <stdexcept>\n' + c
    owner = c.index('struct VRRenderTargetManager_Base::QuadViewNativeTargetOwner {')
    end = c.index('struct VRRenderTargetManager_Base::QuadViewNativeTargetBuild {', owner)
    block = c[owner:end]
    block = once(block, '    sdk::UObjectReference<sdk::UTexture> texture{nullptr};', '''    // UPROPERTY ownership is essential: a weak UObjectReference and a retained
    // ID3D12Resource do not own the engine's FTextureRenderTargetResource.
    sdk::UObjectReference<sdk::AActor> holder_actor{nullptr};
    sdk::UObjectReference<sdk::USceneCaptureComponent2D> holder_component{nullptr};
    sdk::UObjectReference<sdk::UTexture> texture{nullptr};
    uintptr_t texture_resource_identity{};
    uintptr_t rhi_texture_identity{};

    bool live() const {
        if (!holder_actor.valid() || !holder_component.valid() || !texture.valid()) return false;
        constexpr uint32_t destroyed_flags=0x00008000u | 0x00010000u;
        if ((texture->get_object_flags() & destroyed_flags) != 0 ||
            (holder_actor->get_object_flags() & destroyed_flags) != 0 ||
            (holder_component->get_object_flags() & destroyed_flags) != 0) return false;
        auto** texture_slot=holder_component->get_texture_target();
        if (!texture_slot || *texture_slot!=texture.get()) return false;
        uintptr_t resource{},rhi{},vtable{};
        return texture_resource_identity && rhi_texture_identity && render_target && gamma_hooked &&
            safe_read_value(reinterpret_cast<uintptr_t>(texture.get())+STALKER2_UE55_UTEXTURE_PRIVATE_RESOURCE_OFFSET,resource) &&
            resource==texture_resource_identity &&
            safe_read_value(resource+STALKER2_UE55_FTEXTURE_RHI_OFFSET,rhi) && rhi==rhi_texture_identity &&
            safe_read_value(reinterpret_cast<uintptr_t>(render_target),vtable) &&
            vtable==reinterpret_cast<uintptr_t>(hooked_vtable.data());
    }''')
    block = once(block, '    static void drain_retired() {', '''    static void drain_retired() {
        if (!GameThreadWorker::get().is_same_thread()) {
            try { GameThreadWorker::get().enqueue([] { QuadViewNativeTargetOwner::drain_retired(); }); }
            catch (...) { /* Retain the actor/property owners until GT can drain. */ }
            return;
        }''')
    block = block.replace('The object and its UTexture remain rooted if retirement bookkeeping fails.',
        'The actor/component property chain remains retained if retirement bookkeeping fails.')
    block = once(block, '''            if (safe_to_delete) {
                owner->native_resource.Reset();''', '''            if (safe_to_delete) {
                // This runs on GT only, after CPU leases and the existing GPU
                // fence have retired. Keep the engine's property chain until then.
                constexpr uint32_t destroyed_flags=0x00008000u | 0x00010000u;
                if (owner->holder_component.valid() &&
                    (owner->holder_component->get_object_flags() & destroyed_flags)==0)
                    owner->holder_component->set_texture_target(nullptr);
                if (owner->holder_actor.valid() &&
                    (owner->holder_actor->get_object_flags() & destroyed_flags)==0)
                    owner->holder_actor->destroy_actor();
                owner->holder_component=nullptr;owner->holder_actor=nullptr;
                owner->native_resource.Reset();''')
    c = c[:owner] + block + c[end:]
    h = once(h, '    bool ensure_quadview_native_target_set(uint32_t width,uint32_t height);',
        '    bool ensure_quadview_native_target_set(uint32_t width,uint32_t height);\n'
        '    bool quadview_native_targets_live(const QuadViewNativeTargetSetSnapshot& targets) const;')
    c = once(c, '''bool VRRenderTargetManager_Base::ensure_quadview_native_target_set(uint32_t width,uint32_t height) {''', '''bool VRRenderTargetManager_Base::quadview_native_targets_live(const QuadViewNativeTargetSetSnapshot& targets) const {
    if (!GameThreadWorker::get().is_same_thread() || !targets.generation || !targets.world_identity) return false;
    for (size_t i=0;i!=4;++i) {
        const auto& snapshot=targets.target_owners[i];
        if (!snapshot || !snapshot->owner_lifetime) return false;
        const auto owner=std::static_pointer_cast<const QuadViewNativeTargetOwner>(snapshot->owner_lifetime);
        if (!owner || owner->render_target!=targets.render_targets[i] || !owner->live()) {
            SPDLOG_ERROR_EVERY_N_SEC(1,"[QuadViews][TargetLifetime] stale source role={} target={:x}; refusing virtual dispatch",
                i,reinterpret_cast<uintptr_t>(targets.render_targets[i]));
            return false;
        }
    }
    return true;
}

bool VRRenderTargetManager_Base::ensure_quadview_native_target_set(uint32_t width,uint32_t height) {''')
    c = once(c, '''        current && current->world_identity==world_identity && current->width==width &&
        current->height==height && current->complete()) return true;''', '''        current && current->world_identity==world_identity && current->width==width &&
        current->height==height && current->complete()) {
        if (quadview_native_targets_live(*current)) return true;
        retire_quadview_native_target_set();
        return false;
    }''')
    c = once(c, '''    // Kismet may flush rendering; the manager mutex is deliberately not held here.
    const float clear_color[4]{0.0f,0.0f,0.0f,1.0f};''', '''    // Use the same world actor -> component TextureTarget property chain as
    // working DuoView Native Fix. Configure before registration so these
    // holders never schedule independent scene-capture rendering.
    auto* gameplay=sdk::UGameplayStatics::get();
    auto* actor_class=sdk::AActor::static_class();
    auto* capture_class=sdk::USceneCaptureComponent2D::static_class();
    auto* capture_every=capture_class ? capture_class->find_property(L"bCaptureEveryFrame") : nullptr;
    auto* capture_movement=capture_class ? capture_class->find_property(L"bCaptureOnMovement") : nullptr;
    if (!gameplay || !actor_class || !capture_class || !capture_every || !capture_movement) {
        std::scoped_lock lock{quadview_native_target_mutex};
        if (quadview_native_target_build==build) quadview_native_target_build.reset();
        return false;
    }
    // Kismet may flush rendering; the manager mutex is deliberately not held here.
    const float clear_color[4]{0.0f,0.0f,0.0f,1.0f};''')
    c = once(c, '''            auto owner=std::shared_ptr<QuadViewNativeTargetOwner>{new QuadViewNativeTargetOwner{},&QuadViewNativeTargetOwner::retire};
            auto* texture=kismet->create_render_target_2d(world,width,height,2,clear_color,false);''', '''            auto owner=std::shared_ptr<QuadViewNativeTargetOwner>{new QuadViewNativeTargetOwner{},&QuadViewNativeTargetOwner::retire};
            // Store immediately: partial creation follows the same GT cleanup.
            build->owners[i]=owner;
            owner->holder_actor=gameplay->spawn_actor(world,actor_class,glm::vec3{0,0,0});
            if (!owner->holder_actor.valid()) throw std::runtime_error("QuadView holder actor creation failed");
            owner->holder_component=static_cast<sdk::USceneCaptureComponent2D*>(
                owner->holder_actor->add_component_by_class(capture_class,true));
            if (!owner->holder_component.valid()) throw std::runtime_error("QuadView holder component creation failed");
            *capture_every->get_data<bool>(owner->holder_component.get())=false;
            *capture_movement->get_data<bool>(owner->holder_component.get())=false;
            owner->holder_component->set_visibility(false);
            auto* texture=kismet->create_render_target_2d(world,width,height,2,clear_color,false);''')
    c = once(c, '''            root_dedicated_ui_texture(texture); owner->rooted=true; owner->texture=texture; build->owners[i]=std::move(owner);''', '''            owner->texture=texture;
            if (!owner->texture.valid()) throw std::runtime_error("QuadView texture identity invalid");
            owner->holder_component->set_texture_target(texture);
            auto** texture_slot=owner->holder_component->get_texture_target();
            if (!texture_slot || *texture_slot!=texture)
                throw std::runtime_error("QuadView TextureTarget property did not retain the source");
            owner->holder_actor->finish_add_component(owner->holder_component.get());
            SPDLOG_INFO("[QuadViews][TargetLifetime] role={} actor={:x} component={:x} texture={:x} property_owned=true capture_every=false capture_movement=false",
                i,reinterpret_cast<uintptr_t>(owner->holder_actor.get()),
                reinterpret_cast<uintptr_t>(owner->holder_component.get()),reinterpret_cast<uintptr_t>(texture));''')
    c = once(c, '''            owner.render_target=frt;
            *reinterpret_cast<uintptr_t*>(frt)=reinterpret_cast<uintptr_t>(owner.hooked_vtable.data());''', '''            owner.render_target=frt;
            owner.texture_resource_identity=reinterpret_cast<uintptr_t>(chains[i].texture_resource);
            owner.rhi_texture_identity=reinterpret_cast<uintptr_t>(chains[i].rhi_texture);
            *reinterpret_cast<uintptr_t*>(frt)=reinterpret_cast<uintptr_t>(owner.hooked_vtable.data());''')
    c = once(c, '''        const bool qv_family_valid=qv_target_set && qv_target_set->complete() && qv_snapshot && qv_snapshot->construction_complete() &&''', '''        const bool qv_family_valid=qv_target_set && qv_target_set->complete() &&
            qv_rtm && qv_rtm->quadview_native_targets_live(*qv_target_set) && qv_snapshot && qv_snapshot->construction_complete() &&''')
    c = once(c, '''            [&](size_t slot) {
                if (slot!=0) reinterpret_cast<sdk::FScene*>(qv_scene)->decrement_frame_count();''', '''            [&](size_t slot) {
                if (!qv_rtm->quadview_native_targets_live(*qv_target_set)) {
                    vr->set_quadview_status("Native source ownership changed; dispatch stopped before virtual call");
                    return false;
                }
                if (slot!=0) reinterpret_cast<sdk::FScene*>(qv_scene)->decrement_frame_count();''')
    cp.write_text(c)
    hp.write_text(h)
    print('Applied Build51 engine-owned four-target lifetime and per-dispatch liveness proof.')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Experimental UE5.5 first-person FOV calibration per DuoView source.

The game may also implement foreground geometry using independent material WPO.
This guarded path changes only a uniquely discovered native UE5.5
FFirstPersonParameters.FOVCorrectionFactor, never world FOV or arbitrary SDK
offsets. It is OFF by default. Runtime evidence determines whether it applies.
"""
def apply(changed, edit):
    header="src/mods/VR.hpp"
    cpp="src/mods/VR.cpp"
    hook="src/mods/vr/FFakeStereoRenderingHook.cpp"
    edit(header,
'''    const ModSlider::Ptr m_duo_sharpen{ModSlider::create(generate_name("DuoViewGlamaryeFoveaStrength"), 0.f, 2.f, 1.f)};''',
'''    const ModSlider::Ptr m_duo_sharpen{ModSlider::create(generate_name("DuoViewGlamaryeFoveaStrength"), 0.f, 2.f, 1.f)};
    const ModToggle::Ptr m_duo_foreground_fix{ModToggle::create(generate_name("DuoViewStalker2ForegroundMPC"),true)};
    std::atomic<uint64_t> m_duo_foreground_applied{0}, m_duo_foreground_not_found{0};
    const ModToggle::Ptr m_duo_fg_fovea_on{ModToggle::create(generate_name("DuoViewFirstPersonFoveaEnabled"),false)};
    const ModSlider::Ptr m_duo_fg_fovea_factor{ModSlider::create(generate_name("DuoViewFirstPersonFoveaFactor"),.33f,3.f,1.f)};
    const ModToggle::Ptr m_duo_fg_periphery_on{ModToggle::create(generate_name("DuoViewFirstPersonPeripheryEnabled"),false)};
    const ModSlider::Ptr m_duo_fg_periphery_factor{ModSlider::create(generate_name("DuoViewFirstPersonPeripheryFactor"),.33f,3.f,1.f)};
    std::atomic<uint64_t> m_duo_fg_fovea_applied{0}, m_duo_fg_fovea_unavailable{0};
    std::atomic<uint64_t> m_duo_fg_periphery_applied{0}, m_duo_fg_periphery_unavailable{0};''')
    edit(header,
'''            *m_duo_feather, *m_duo_sharpen, *m_duo_gaze,''',
'''             *m_duo_feather, *m_duo_sharpen, *m_duo_fg_fovea_on, *m_duo_fg_fovea_factor,
             *m_duo_fg_periphery_on, *m_duo_fg_periphery_factor, *m_duo_foreground_fix, *m_duo_gaze,''')
    edit(header,
'''    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }''',
'''    void note_duoview_foreground(bool is_fovea, bool applied) {
        (is_fovea ? (applied ? m_duo_fg_fovea_applied : m_duo_fg_fovea_unavailable)
                  : (applied ? m_duo_fg_periphery_applied : m_duo_fg_periphery_unavailable))
            .fetch_add(1,std::memory_order_relaxed);
    }
    void update_duoview_game_foreground(sdk::UGameEngine* engine);
    void note_duoview_game_foreground(bool applied) {
        (applied ? m_duo_foreground_applied : m_duo_foreground_not_found)
            .fetch_add(1,std::memory_order_relaxed);
    }
    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }''')
    edit(cpp,
'''                    m_duo_feather->value()=.08f; m_duo_sharpen->value()=1.f; m_duo_gaze->value()=true;''',
'''                    m_duo_feather->value()=.08f; m_duo_sharpen->value()=1.f; m_duo_gaze->value()=true;
                    m_duo_fg_fovea_on->value()=false; m_duo_fg_fovea_factor->value()=1.f;
                    m_duo_fg_periphery_on->value()=false; m_duo_fg_periphery_factor->value()=1.f;
                    m_duo_foreground_fix->value()=true;''')
    edit(cpp,
'''                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");''',
'''                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");
                m_duo_foreground_fix->draw("STALKER 2: normalize weapon/hand foreground FOV (EXPERIMENTAL)");
                if (m_duo_foreground_fix->value()) {
                    ImGui::TextWrapped("Applies a game-wide MPC_FOV override to both DuoView sources at the game-thread boundary. No UE view-memory scanning. The original MPC parameters are restored on mode exit when the same world is still live.");
                    ImGui::Text("MPC updates applied: %llu; missing or invalid: %llu",
                       (unsigned long long)m_duo_foreground_applied.load(),
                       (unsigned long long)m_duo_foreground_not_found.load());
                }''')
    edit(cpp,
'''                        {uevr::duoview::reject_sharpen,"Glamarye strength"},''',
'''                        {uevr::duoview::reject_sharpen,"Glamarye strength"},
                        {uevr::duoview::reject_foreground_fovea,"First-person fovea factor"},
                        {uevr::duoview::reject_foreground_periphery,"First-person periphery factor"},''')
    edit(cpp,
'''        .feather_fraction=m_duo_feather->value(), .sharpen_strength=m_duo_sharpen->value(), .debug_border=m_duo_border->value(),''',
'''        .feather_fraction=m_duo_feather->value(), .sharpen_strength=m_duo_sharpen->value(),
        .foreground_fovea_enabled=m_duo_fg_fovea_on->value(),
        .foreground_fovea_factor=m_duo_fg_fovea_factor->value(),
        .foreground_periphery_enabled=m_duo_fg_periphery_on->value(),
        .foreground_periphery_factor=m_duo_fg_periphery_factor->value(),
        .debug_border=m_duo_border->value(),''')
    edit(cpp,
'''        current.feather_fraction==candidate.feather_fraction && current.sharpen_strength==candidate.sharpen_strength &&
        current.debug_border==candidate.debug_border &&''',
'''        current.feather_fraction==candidate.feather_fraction && current.sharpen_strength==candidate.sharpen_strength &&
        current.foreground_fovea_enabled==candidate.foreground_fovea_enabled &&
        current.foreground_fovea_factor==candidate.foreground_fovea_factor &&
        current.foreground_periphery_enabled==candidate.foreground_periphery_enabled &&
        current.foreground_periphery_factor==candidate.foreground_periphery_factor &&
        current.debug_border==candidate.debug_border &&''')
    # Apply game-owned foreground material collection parameters once per
    # game tick, after the game's own update. Both DuoView render sources see
    # the SAME geometry and WPO; never scan arbitrary FSceneView memory.
    edit(cpp,
'''void VR::on_post_engine_tick(sdk::UGameEngine* engine, float delta) {''',
r'''void VR::update_duoview_game_foreground(sdk::UGameEngine* engine) {
    // All operations on the Unreal game thread. No shader, projection, D3D12
    // or compositor work. UObject pointers are rediscovered on every tick:
    // STALKER 2 destroys and recreates MPC assets across level reloads.
    struct Baseline {
        uintptr_t world_id{};
        uintptr_t collection_id{};
        float is_fov_enabled{};
        float depth_scale{};
        bool active{};
    };
    static Baseline baseline{};
    const bool requested = is_duoview_renderer_active() && m_duo_foreground_fix->value();
    if (!requested && !baseline.active) return;

    auto* world = engine != nullptr ? engine->get_world() : nullptr;
    if (!world) { baseline = {}; return; }

    const auto world_id = reinterpret_cast<uintptr_t>(world);
    if (baseline.world_id != 0 && baseline.world_id != world_id) baseline = {};

    try {
        sdk::UObject* collection{};
        // Distinguish the game's specific collection by exact asset name;
        // avoid a hardcoded cooked package path or stale UObject cache.
        for (auto* object : get_live_objects_by_class_name(
                 L"Class /Script/Engine.MaterialParameterCollection")) {
            if (object && object->get_full_name().ends_with(L".MPC_FOV")) {
                if (collection != nullptr) {
                    note_duoview_game_foreground(false); // ambiguous asset
                    return;
                }
                collection = object;
            }
        }
        // An asset may be reloaded within the same world; never restore a
        // previous collection's baseline into a replacement object.
        if (baseline.active && baseline.collection_id != reinterpret_cast<uintptr_t>(collection))
            baseline = {};
        const auto klass = sdk::find_uobject<sdk::UClass>(
            L"Class /Script/Engine.KismetMaterialLibrary");
        auto* library = klass != nullptr ? klass->get_class_default_object() : nullptr;
        auto* getter = klass != nullptr ? klass->find_function(L"GetScalarParameterValue") : nullptr;
        auto* setter = klass != nullptr ? klass->find_function(L"SetScalarParameterValue") : nullptr;
        if (!collection || !library || !getter || !setter) {
            if (requested) note_duoview_game_foreground(false);
            return;
        }
        auto read_value = [&](std::wstring_view name, float& value) -> bool {
            sdk::ReflectedNameCall call{getter};
            if (!call.write(L"WorldContextObject", (sdk::UObject*)world) ||
                !call.write(L"Collection", collection) ||
                !call.write_name(L"ParameterName", sdk::OwnedFName{name}) ||
                !call.field(L"ReturnValue", sizeof(float)) ||
                !call.invoke(library)) return false;
            value = call.read<float>(L"ReturnValue");
            return std::isfinite(value);
        };
        auto write_value = [&](std::wstring_view name, float value) -> bool {
            sdk::ReflectedNameCall call{setter};
            return call.write(L"WorldContextObject", (sdk::UObject*)world) &&
                call.write(L"Collection", collection) &&
                call.write_name(L"ParameterName", sdk::OwnedFName{name}) &&
                call.write(L"ParameterValue", value) && call.invoke(library);
        };

        if (!requested) {
            if (baseline.active && baseline.world_id == world_id) {
                // Never restore parameters into a different game world.
                const bool restored =
                    write_value(L"IsFOVEnabled", baseline.is_fov_enabled) &&
                    write_value(L"DepthScale", baseline.depth_scale);
                if (!restored)
                    SPDLOG_WARNING_EVERY_N_SEC(5,
                        "[DuoView][Foreground] original MPC_FOV values could not be restored");
            }
            baseline = {};
            return;
        }
        if (!baseline.active) {
            float fov{}, depth{};
            if (!read_value(L"IsFOVEnabled", fov) ||
                !read_value(L"DepthScale", depth)) {
                note_duoview_game_foreground(false);
                SPDLOG_WARNING_EVERY_N_SEC(5,
                    "[DuoView][Foreground] MPC_FOV parameters unavailable: no changes made");
                return;
            }
            baseline = {world_id, reinterpret_cast<uintptr_t>(collection), fov, depth, true};
        }

        // GSC's MF_ForegroundWithShadowSwitch uses both parameters for its
        // World Position Offset. Neutralize the separate first-person FOV and
        // depth squash for BOTH source views, preserving all meshes and shadows.
        // The game can rewrite these per tick; reapply after its update.
        const bool ok = write_value(L"IsFOVEnabled", 0.0f) &&
                        write_value(L"DepthScale", 1.0f);
        note_duoview_game_foreground(ok);
        if (!ok)
            SPDLOG_WARNING_EVERY_N_SEC(5,
                "[DuoView][Foreground] STALKER 2 material override failed; do not infer parity");
    } catch (...) {
        if (requested) note_duoview_game_foreground(false);
        SPDLOG_WARNING_EVERY_N_SEC(5,
            "[DuoView][Foreground] reflected MPC access refused safely");
    }
}

void VR::on_post_engine_tick(sdk::UGameEngine* engine, float delta) {''')
    edit(cpp,
'''    // Some Supermassive camera paths rewrite crop/aspect state during engine''',
'''    // Use the active game material pipeline for both sources, not an
    // unverified FSceneViewInitOptions memory pattern in the foveal view.
    update_duoview_game_foreground(engine);

    // Some Supermassive camera paths rewrite crop/aspect state during engine''')

    # The now-unreferenced DuoViewFirstPerson.hpp stays in the test tree as a
    # historical proof-of-concept but is deliberately never hooked at runtime.

#!/usr/bin/env python3
"""Disable STALKER 2 artificial first-person FOV in BOTH DuoView sources.

No per-source TanFOV mutation. The single world-global IsFOVEnabled=0 write
happens on Unreal's game-thread pre-engine tick, prior to the two producer
draws. Keep the validated compositor, gaze, render packet and XR path intact.
Experimental, OFF by default; switch OFF/mode exit restores the captured
pre-override parameter (when the game hasn't already changed ownership).
"""
def apply(changed, edit):
    header="src/mods/VR.hpp"
    cpp="src/mods/VR.cpp"
    edit(header,
'''    const ModSlider::Ptr m_duo_sharpen{ModSlider::create(generate_name("DuoViewGlamayreFoveaStrength"), 0.f, 2.f, 1.f)};''',
'''    const ModSlider::Ptr m_duo_sharpen{ModSlider::create(generate_name("DuoViewGlamayreFoveaStrength"), 0.f, 2.f, 1.f)};
    const ModToggle::Ptr m_duo_disable_firstperson_fov{ModToggle::create(generate_name("DuoViewDisableFirstPersonFOV"),false)};
    std::atomic<uint64_t> m_duo_fov_verified{0},m_duo_fov_failed{0};
    std::atomic<int> m_duo_fov_status{0};
    std::atomic<float> m_duo_fov_original{0.f},m_duo_fov_last{0.f};''')
    edit(header,
'''            *m_duo_feather, *m_duo_sharpen, *m_duo_gaze,''',
'''            *m_duo_feather, *m_duo_sharpen, *m_duo_disable_firstperson_fov, *m_duo_gaze,''')
    edit(header,
'''    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }''',
'''    void note_duoview_global_fov(bool verified,int status,float original,float last) {
        (verified ? m_duo_fov_verified : m_duo_fov_failed)
            .fetch_add(1,std::memory_order_relaxed);
        m_duo_fov_status.store(status,std::memory_order_relaxed);
        m_duo_fov_original.store(original,std::memory_order_relaxed);
        m_duo_fov_last.store(last,std::memory_order_relaxed);
    }
    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }''')
    edit(cpp,
'''#include "VR.hpp"''',
'''#include "VR.hpp"
#include "vr/DuoViewMPCFov.hpp"''')
    edit(cpp,
'''                    m_duo_feather->value()=.08f; m_duo_sharpen->value()=1.f; m_duo_gaze->value()=true;''',
'''                    m_duo_feather->value()=.08f; m_duo_sharpen->value()=1.f; m_duo_gaze->value()=true;
                    m_duo_disable_firstperson_fov->value()=false;''')
    edit(cpp,
'''                m_duo_sharpen->draw("Glamayre fovea strength (default 1.0; 0 = off)");''',
'''                m_duo_sharpen->draw("Glamayre fovea strength (default 1.0; 0 = off)");
                ImGui::Separator();
                m_duo_disable_firstperson_fov->draw("Disable STALKER 2 First-Person FOV (both sources)");
                ImGui::TextWrapped("Experimental: sets the shared game MPC_FOV.IsFOVEnabled=0 BEFORE both UE source passes; restores the original value when disabled or leaving DuoView. Does not change crop, projection or HUD.");
                ImGui::Text("First-person FOV write/readback: verified %llu / failed %llu",
                    (unsigned long long)m_duo_fov_verified.load(),
                    (unsigned long long)m_duo_fov_failed.load());
                ImGui::Text("MPC status %d (6=confirmed); original %.3f; last %.3f",
                    m_duo_fov_status.load(),m_duo_fov_original.load(),m_duo_fov_last.load());
''')
    edit(cpp,
'''        .feather_fraction=m_duo_feather->value(), .sharpen_strength=m_duo_sharpen->value(), .debug_border=m_duo_border->value(),''',
'''        .feather_fraction=m_duo_feather->value(), .sharpen_strength=m_duo_sharpen->value(),
        .disable_firstperson_fov=m_duo_disable_firstperson_fov->value(),
        .debug_border=m_duo_border->value(),''')
    edit(cpp,
'''        current.feather_fraction==candidate.feather_fraction && current.sharpen_strength==candidate.sharpen_strength &&
        current.debug_border==candidate.debug_border &&''',
'''        current.feather_fraction==candidate.feather_fraction && current.sharpen_strength==candidate.sharpen_strength &&
        current.disable_firstperson_fov==candidate.disable_firstperson_fov &&
        current.debug_border==candidate.debug_border &&''')
    edit(cpp,
'''    m_cvar_manager->on_pre_engine_tick(engine, delta);''',
'''    m_cvar_manager->on_pre_engine_tick(engine, delta);
    // STALKER 2 viewmodel FOV is a single game WORLD material collection.
    // Do not change it while preparing each UE source: both must sample the
    // same value. This callback is the UE game thread before viewport drawing.
    // When ID6/option turns OFF, restore here even when producer hooks stop.
    {
        auto& bridge=uevr::duoview::mpc::active();
        const bool disable=is_duoview_renderer_active() &&
            m_duoview.settings().disable_firstperson_fov;
        if (disable || bridge.override_active()) {
            const bool ok=bridge.apply(disable);
            note_duoview_global_fov(ok,static_cast<int>(bridge.status()),
                bridge.baseline(),bridge.last_value());
            if (!ok)
                SPDLOG_WARNING_EVERY_N_SEC(5,
                    "[DuoView][FirstPersonFOV] {} write/readback failed; status {}",
                    disable ? "disable" : "restore",
                    static_cast<int>(bridge.status()));
            else
                SPDLOG_INFO_EVERY_N_SEC(5,
                    "[DuoView][FirstPersonFOV] {} IsFOVEnabled last {:.3f}, original {:.3f}",
                    disable ? "disabled for BOTH views" : "restored",
                    bridge.last_value(),bridge.baseline());
        }
    }''')

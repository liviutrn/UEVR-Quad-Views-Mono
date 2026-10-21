#!/usr/bin/env python3
"""STALKER 2 material MPC_FOV.TanFOV experiment; removes the ineffective
FFirstPersonParameters heuristic from Build 195 completely.

Uses SDK-reflected KismetMaterialLibrary Get/SetScalarParameterValue and
immediate readback. Both DuoView source controls are independently OFF by
default. Source-specific visual ownership is NOT assumed: UE material
parameter collections are world-scoped, so per-pass timing needs a headset
test even when readback succeeds.
"""
def apply(changed, edit):
    header="src/mods/VR.hpp"
    cpp="src/mods/VR.cpp"
    hook="src/mods/vr/FFakeStereoRenderingHook.cpp"
    edit(header,
'''    const ModSlider::Ptr m_duo_sharpen{ModSlider::create(generate_name("DuoViewGlamaryeFoveaStrength"), 0.f, 2.f, 1.f)};''',
'''    const ModSlider::Ptr m_duo_sharpen{ModSlider::create(generate_name("DuoViewGlamaryeFoveaStrength"), 0.f, 2.f, 1.f)};
    const ModToggle::Ptr m_duo_mpc_fovea_on{ModToggle::create(generate_name("DuoViewMPCTanFOVFoveaEnabled"),false)};
    const ModSlider::Ptr m_duo_mpc_fovea_factor{ModSlider::create(generate_name("DuoViewMPCTanFOVFoveaFactor"),.33f,3.f,1.f)};
    const ModToggle::Ptr m_duo_mpc_periphery_on{ModToggle::create(generate_name("DuoViewMPCTanFOVPeripheryEnabled"),false)};
    const ModSlider::Ptr m_duo_mpc_periphery_factor{ModSlider::create(generate_name("DuoViewMPCTanFOVPeripheryFactor"),.33f,3.f,1.f)};
    std::atomic<uint64_t> m_duo_mpc_fovea_confirmed{0}, m_duo_mpc_fovea_failed{0};
    std::atomic<uint64_t> m_duo_mpc_periphery_confirmed{0}, m_duo_mpc_periphery_failed{0};
    std::atomic<float> m_duo_mpc_baseline{0.f},m_duo_mpc_last_write{0.f};
    std::atomic<int> m_duo_mpc_last_status{0};''')
    edit(header,
'''            *m_duo_feather, *m_duo_sharpen, *m_duo_gaze,''',
'''            *m_duo_feather, *m_duo_sharpen, *m_duo_mpc_fovea_on, *m_duo_mpc_fovea_factor,
            *m_duo_mpc_periphery_on, *m_duo_mpc_periphery_factor, *m_duo_gaze,''')
    edit(header,
'''    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }''',
'''    void note_duoview_mpc(bool fovea, bool verified, int status, float baseline, float last) {
        (fovea ? (verified ? m_duo_mpc_fovea_confirmed : m_duo_mpc_fovea_failed)
               : (verified ? m_duo_mpc_periphery_confirmed : m_duo_mpc_periphery_failed))
            .fetch_add(1,std::memory_order_relaxed);
        m_duo_mpc_last_status.store(status,std::memory_order_relaxed);
        m_duo_mpc_baseline.store(baseline,std::memory_order_relaxed);
        m_duo_mpc_last_write.store(last,std::memory_order_relaxed);
    }
    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }''')
    edit(cpp,
'''                    m_duo_feather->value()=.08f; m_duo_sharpen->value()=1.f; m_duo_gaze->value()=true;''',
'''                    m_duo_feather->value()=.08f; m_duo_sharpen->value()=1.f; m_duo_gaze->value()=true;
                    m_duo_mpc_fovea_on->value()=false; m_duo_mpc_fovea_factor->value()=1.f;
                    m_duo_mpc_periphery_on->value()=false; m_duo_mpc_periphery_factor->value()=1.f;''')
    edit(cpp,
'''                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");''',
'''                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");
                ImGui::Separator();
                ImGui::TextUnformatted("STALKER 2 weapon materials: MPC_FOV.TanFOV (experimental)");
                m_duo_mpc_fovea_on->draw("Fovea MPC TanFOV correction");
                if (m_duo_mpc_fovea_on->value()) {
                    m_duo_mpc_fovea_factor->draw("Fovea MPC TanFOV factor (0.33 - 3.0)");
                    ImGui::Text("Fovea MPC verified %llu / failed %llu",
                        (unsigned long long)m_duo_mpc_fovea_confirmed.load(),
                        (unsigned long long)m_duo_mpc_fovea_failed.load());
                }
                m_duo_mpc_periphery_on->draw("Periphery MPC TanFOV correction");
                if (m_duo_mpc_periphery_on->value()) {
                    m_duo_mpc_periphery_factor->draw("Periphery MPC TanFOV factor (0.33 - 3.0)");
                    ImGui::Text("Periphery MPC verified %llu / failed %llu",
                        (unsigned long long)m_duo_mpc_periphery_confirmed.load(),
                        (unsigned long long)m_duo_mpc_periphery_failed.load());
                }
                ImGui::Text("MPC TanFOV status %d, base %.4f, last %.4f",
                    m_duo_mpc_last_status.load(),m_duo_mpc_baseline.load(),
                    m_duo_mpc_last_write.load());
                ImGui::TextWrapped("Status 6 = Kismet Get/Set readback confirmed. This adjusts the REAL game MPC_FOV.TanFOV material parameter, not UE's native first-person primitive FOV. Warning: MPC is world-shared. Readback does NOT prove the two GPU passes sampled independent values; test visually and check logs.");
''')
    edit(cpp,
'''                        {uevr::duoview::reject_sharpen,"Glamarye strength"},''',
'''                        {uevr::duoview::reject_sharpen,"Glamarye strength"},
                        {uevr::duoview::reject_mpc_fovea,"MPC TanFOV fovea factor"},
                        {uevr::duoview::reject_mpc_periphery,"MPC TanFOV periphery factor"},''')
    edit(cpp,
'''        .feather_fraction=m_duo_feather->value(), .sharpen_strength=m_duo_sharpen->value(), .debug_border=m_duo_border->value(),''',
'''        .feather_fraction=m_duo_feather->value(), .sharpen_strength=m_duo_sharpen->value(),
        .mpc_fovea_enabled=m_duo_mpc_fovea_on->value(),
        .mpc_fovea_factor=m_duo_mpc_fovea_factor->value(),
        .mpc_periphery_enabled=m_duo_mpc_periphery_on->value(),
        .mpc_periphery_factor=m_duo_mpc_periphery_factor->value(),
        .debug_border=m_duo_border->value(),''')
    edit(cpp,
'''        current.feather_fraction==candidate.feather_fraction && current.sharpen_strength==candidate.sharpen_strength &&
        current.debug_border==candidate.debug_border &&''',
'''        current.feather_fraction==candidate.feather_fraction && current.sharpen_strength==candidate.sharpen_strength &&
        current.mpc_fovea_enabled==candidate.mpc_fovea_enabled &&
        current.mpc_fovea_factor==candidate.mpc_fovea_factor &&
        current.mpc_periphery_enabled==candidate.mpc_periphery_enabled &&
        current.mpc_periphery_factor==candidate.mpc_periphery_factor &&
        current.debug_border==candidate.debug_border &&''')
    edit(hook,
'''#include "DuoViewGeometry.hpp"''',
'''#include "DuoViewGeometry.hpp"
#include "DuoViewMPCFov.hpp"''')
    edit(hook,
'''            vr->duoview_state().scene(key,index,state,applied);''',
'''            // Verified STALKER 2 game material mechanism (WorldPositionOffset):
            // MPC_FOV.TanFOV, called through UKismetMaterialLibrary.
            // This is a world-shared MPC: separate producer passes are attempted
            // in sequence, but GPU visual independence requires headset testing.
            if (const auto frozen=vr->duoview_state().snapshot(key); frozen) {
                const auto& quality=frozen->config.settings;
                const bool fovea=index==quality.fovea_view;
                const bool enabled=fovea ? quality.mpc_fovea_enabled
                                         : quality.mpc_periphery_enabled;
                const float factor=fovea ? quality.mpc_fovea_factor
                                         : quality.mpc_periphery_factor;
                auto& bridge=uevr::duoview::mpc::active();
                if (enabled || bridge.attempts()!=0) {
                    const bool verified=bridge.set_factor(factor,enabled);
                    if (enabled) vr->note_duoview_mpc(fovea,verified,
                        static_cast<int>(bridge.status()),bridge.baseline(),bridge.last_value());
                    if (enabled && !verified)
                        SPDLOG_WARNING_EVERY_N_SEC(5,
                            "[DuoView][MPC_FOV] {} UE{} TanFOV write/readback failed; status {}",
                            fovea ? "fovea" : "periphery",index,
                            static_cast<int>(bridge.status()));
                    if (enabled && verified)
                        SPDLOG_INFO_EVERY_N_SEC(5,
                            "[DuoView][MPC_FOV] {} UE{} TanFOV factor {:.3f}, base {:.3f}, last {:.3f} readback confirmed (per-pass sampling unverified)",
                            fovea ? "fovea" : "periphery",index,factor,bridge.baseline(),bridge.last_value());
                }
            }
            vr->duoview_state().scene(key,index,state,applied);''')

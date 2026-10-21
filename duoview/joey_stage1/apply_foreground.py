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
    const ModToggle::Ptr m_duo_fg_fovea_on{ModToggle::create(generate_name("DuoViewFirstPersonFoveaEnabled"),false)};
    const ModSlider::Ptr m_duo_fg_fovea_factor{ModSlider::create(generate_name("DuoViewFirstPersonFoveaFactor"),.33f,3.f,1.f)};
    const ModToggle::Ptr m_duo_fg_periphery_on{ModToggle::create(generate_name("DuoViewFirstPersonPeripheryEnabled"),false)};
    const ModSlider::Ptr m_duo_fg_periphery_factor{ModSlider::create(generate_name("DuoViewFirstPersonPeripheryFactor"),.33f,3.f,1.f)};
    std::atomic<uint64_t> m_duo_fg_fovea_applied{0}, m_duo_fg_fovea_unavailable{0};
    std::atomic<uint64_t> m_duo_fg_periphery_applied{0}, m_duo_fg_periphery_unavailable{0};''')
    edit(header,
'''            *m_duo_feather, *m_duo_sharpen, *m_duo_gaze,''',
'''             *m_duo_feather, *m_duo_sharpen, *m_duo_fg_fovea_on, *m_duo_fg_fovea_factor,
             *m_duo_fg_periphery_on, *m_duo_fg_periphery_factor, *m_duo_gaze,''')
    edit(header,
'''    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }''',
'''    void note_duoview_foreground(bool is_fovea, bool applied) {
        (is_fovea ? (applied ? m_duo_fg_fovea_applied : m_duo_fg_fovea_unavailable)
                  : (applied ? m_duo_fg_periphery_applied : m_duo_fg_periphery_unavailable))
            .fetch_add(1,std::memory_order_relaxed);
    }
    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }''')
    edit(cpp,
'''                    m_duo_feather->value()=.08f; m_duo_sharpen->value()=1.f; m_duo_gaze->value()=true;''',
'''                    m_duo_feather->value()=.08f; m_duo_sharpen->value()=1.f; m_duo_gaze->value()=true;
                    m_duo_fg_fovea_on->value()=false; m_duo_fg_fovea_factor->value()=1.f;
                    m_duo_fg_periphery_on->value()=false; m_duo_fg_periphery_factor->value()=1.f;''')
    edit(cpp,
'''                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");''',
'''                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");
                ImGui::Separator(); ImGui::TextUnformatted("First-person mesh FOV calibration (experimental)");
                m_duo_fg_fovea_on->draw("Fovea: first-person FOV correction");
                if (m_duo_fg_fovea_on->value()) {
                    m_duo_fg_fovea_factor->draw("Fovea first-person scale factor (0.33 - 3.0)");
                    ImGui::Text("Fovea: adjusted %llu / unavailable %llu",
                        (unsigned long long)m_duo_fg_fovea_applied.load(),
                        (unsigned long long)m_duo_fg_fovea_unavailable.load());
                }
                m_duo_fg_periphery_on->draw("Periphery: first-person FOV correction");
                if (m_duo_fg_periphery_on->value()) {
                    m_duo_fg_periphery_factor->draw("Periphery first-person scale factor (0.33 - 3.0)");
                    ImGui::Text("Periphery: adjusted %llu / unavailable %llu",
                        (unsigned long long)m_duo_fg_periphery_applied.load(),
                        (unsigned long long)m_duo_fg_periphery_unavailable.load());
                }
                ImGui::TextWrapped("Both controls are independent. OFF = original. Factor 1.0 = unchanged, below 1 = smaller, above 1 = larger. Only UE5.5 tagged native first-person geometry is targeted. Material WPO-based STALKER 2 weapons may not respond.");''')
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
    edit(hook,
'''#include "DuoViewGeometry.hpp"''',
'''#include "DuoViewGeometry.hpp"
#include "DuoViewFirstPerson.hpp"''')
    edit(hook,
'''            vr->duoview_state().scene(key,index,state,applied);''',
'''            // Evaluate exactly one frozen DuoView source at a time.
            // No global weapon FOV changes: the selected Unreal view alone
            // receives the native UE5.5 tagged first-person FOV adjustment.
            if (const auto frozen=vr->duoview_state().snapshot(key); frozen) {
                const auto& quality=frozen->config.settings;
                const bool fovea=index==quality.fovea_view;
                const bool enabled=fovea ? quality.foreground_fovea_enabled
                                         : quality.foreground_periphery_enabled;
                const float factor=fovea ? quality.foreground_fovea_factor
                                         : quality.foreground_periphery_factor;
                if (enabled) {
                    bool adjusted=false;
                    // A non-square fovea cannot be matched using one uniform
                    // first-person FOV scale; periphery has no crop restriction.
                    if ((!fovea || std::fabs(quality.crop_width-quality.crop_height)<.015f) &&
                        init_options_ue5!=nullptr) {
                        auto* begin=reinterpret_cast<std::byte*>(&init_options_ue5->stereo_pass);
                        constexpr size_t inspect_size=0x240;
                        if (is_readable_process_range(reinterpret_cast<uintptr_t>(begin),inspect_size)) {
                            auto bytes=std::span<std::byte>{begin,inspect_size};
                            if (const auto slot=uevr::duoview::foreground::find_slot(bytes)) {
                                adjusted=uevr::duoview::foreground::correct(bytes,*slot,factor);
                                if (adjusted)
                                    SPDLOG_INFO_EVERY_N_SEC(5,
                                        "[DuoView][Foreground] {} UE{} first-person factor {:.3f} (native FOV {:.1f}/{:.1f}, base {:.3f})",
                                        fovea ? "fovea" : "periphery",index,factor,
                                        slot->fields.scene_fov,slot->fields.desired_fov,
                                        slot->fields.correction);
                            }
                        }
                    }
                    vr->note_duoview_foreground(fovea,adjusted);
                    if (!adjusted)
                        SPDLOG_WARNING_EVERY_N_SEC(5,
                            "[DuoView][Foreground] {} UE{} requested but tagged UE5.5 parameter unavailable, ambiguous, or incompatible; no memory write",
                            fovea ? "fovea" : "periphery",index);
                }
            }
            vr->duoview_state().scene(key,index,state,applied);''')

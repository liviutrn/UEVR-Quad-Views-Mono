#!/usr/bin/env python3
"""Experimental UE5.5 first-person FOV parity on DuoView's cropped source only.

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
    const ModToggle::Ptr m_duo_foreground_fix{ModToggle::create(generate_name("DuoViewFirstPersonFovCorrection"),false)};
    const ModSlider::Ptr m_duo_foreground_factor{ModSlider::create(generate_name("DuoViewFirstPersonFoveaFactor"),.2f,2.f,.5f)};
    std::atomic<uint64_t> m_duo_foreground_applied{0};
    std::atomic<uint64_t> m_duo_foreground_not_found{0};''')
    edit(header,
'''             *m_duo_feather, *m_duo_sharpen, *m_duo_gaze,''',
'''             *m_duo_feather, *m_duo_sharpen, *m_duo_foreground_fix, *m_duo_foreground_factor, *m_duo_gaze,''')
    edit(header,
'''    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }''',
'''    void note_duoview_foreground(bool applied) {
        (applied ? m_duo_foreground_applied : m_duo_foreground_not_found).fetch_add(1,std::memory_order_relaxed);
    }
    void note_duoview_gpu_ms(float ms) { m_duo_gpu_ms.store(ms, std::memory_order_relaxed); }''')
    edit(cpp,
'''                    m_duo_feather->value()=.08f; m_duo_sharpen->value()=1.f; m_duo_gaze->value()=true;''',
'''                    m_duo_feather->value()=.08f; m_duo_sharpen->value()=1.f; m_duo_gaze->value()=true;
                    m_duo_foreground_fix->value()=false; m_duo_foreground_factor->value()=.5f;''')
    edit(cpp,
'''                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");''',
'''                m_duo_sharpen->draw("Glamarye fovea strength (default 1.0; 0 = off)");
                m_duo_foreground_fix->draw("Match first-person geometry FOV in fovea (EXPERIMENTAL)");
                if (m_duo_foreground_fix->value()) {
                    m_duo_foreground_factor->draw("First-person fovea factor (0.5 for 50% crop)");
                    ImGui::TextWrapped("Only tagged UE5.5 native first-person mesh geometry is adjusted. If STALKER 2 uses independent material-WPO foreground, the option may have no effect; see counters and log. Keep crop W and H equal when testing.");
                    ImGui::Text("First-person native parameter changed: %llu; unavailable or unsafe: %llu",
                       (unsigned long long)m_duo_foreground_applied.load(),
                       (unsigned long long)m_duo_foreground_not_found.load());
                }''')
    edit(cpp,
'''                        {uevr::duoview::reject_sharpen,"Glamarye strength"},''',
'''                        {uevr::duoview::reject_sharpen,"Glamarye strength"},
                        {uevr::duoview::reject_foreground_factor,"First-person fovea factor"},''')
    edit(cpp,
'''        .feather_fraction=m_duo_feather->value(), .sharpen_strength=m_duo_sharpen->value(), .debug_border=m_duo_border->value(),''',
'''        .feather_fraction=m_duo_feather->value(), .sharpen_strength=m_duo_sharpen->value(),
        .foreground_crop_correction=m_duo_foreground_fix->value(),
        .foreground_fovea_factor=m_duo_foreground_factor->value(), .debug_border=m_duo_border->value(),''')
    edit(cpp,
'''        current.feather_fraction==candidate.feather_fraction && current.sharpen_strength==candidate.sharpen_strength &&
        current.debug_border==candidate.debug_border &&''',
'''        current.feather_fraction==candidate.feather_fraction && current.sharpen_strength==candidate.sharpen_strength &&
        current.foreground_crop_correction==candidate.foreground_crop_correction &&
        current.foreground_fovea_factor==candidate.foreground_fovea_factor &&
        current.debug_border==candidate.debug_border &&''')
    edit(hook,
'''#include "DuoViewGeometry.hpp"''',
'''#include "DuoViewGeometry.hpp"
#include "DuoViewFirstPerson.hpp"''')
    edit(hook,
'''            vr->duoview_state().scene(key,index,state,applied);''',
'''            // UE5.5 first-person meshes have a distinct morphing FOV from
            // ordinary world geometry. The fovea changes projection/viewport;
            // only tune the morph on that source, and only with an exact
            // uniquely validated native parameter signature. Never touch the
            // game camera, global MPC material state or the peripheral view.
            if (const auto frozen=vr->duoview_state().snapshot(key);
                frozen && frozen->config.settings.foreground_crop_correction &&
                index==frozen->config.settings.fovea_view) {
                bool adjusted=false;
                const auto& quality=frozen->config.settings;
                if (std::fabs(quality.crop_width-quality.crop_height)<.015f &&
                    init_options_ue5!=nullptr) {
                    auto* begin=reinterpret_cast<std::byte*>(&init_options_ue5->stereo_pass);
                    constexpr size_t inspect_size=0x240;
                    if (is_readable_process_range(reinterpret_cast<uintptr_t>(begin),inspect_size)) {
                        auto bytes=std::span<std::byte>{begin,inspect_size};
                        if (const auto slot=uevr::duoview::foreground::find_slot(bytes)) {
                            adjusted=uevr::duoview::foreground::correct(
                                bytes,*slot,quality.foreground_fovea_factor);
                            if (adjusted)
                                SPDLOG_INFO_EVERY_N_SEC(5,
                                    "[DuoView][Foreground] first-person fovea factor {:.3f} on UE{} (native FOV {:.1f}/{:.1f}, base {:.3f}); periphery and world remain untouched",
                                    quality.foreground_fovea_factor,index,
                                    slot->fields.scene_fov,slot->fields.desired_fov,
                                    slot->fields.correction);
                        }
                    }
                }
                vr->note_duoview_foreground(adjusted);
                if (!adjusted)
                    SPDLOG_WARNING_EVERY_N_SEC(5,
                        "[DuoView][Foreground] tagged UE5.5 first-person factor unavailable, ambiguous or asymmetrical crop; no unsafe memory write");
            }
            vr->duoview_state().scene(key,index,state,applied);''')

#!/usr/bin/env python3
"""B41 over B40: black-flash hold window, rejection diagnostics, queue pin for
modes 4-6, B40 blend distance slider, build identity log.

Shader-side B41 changes (parallel B40 sampling, neutral fallback, blend shape)
live directly in QuadViewComposite.hlsl; settings in QuadViewSettings.hpp and
QuadViewD3D12.hpp. This script edits only generated backend sources.
"""
from pathlib import Path
import shutil
import sys


def once(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f"B41 anchor '{label}' found {n} times: {old[:100]!r}")
    return s.replace(old, new, 1)


def main():
    backend = Path(sys.argv[1])
    here = Path(__file__).resolve().parent
    mods = backend / 'src/mods'
    shutil.copyfile(here / 'TriViewHold.hpp', mods / 'vr/TriViewHold.hpp')

    # 1. Hold window: TriView uses its own continuity class (DuoView untouched).
    p = mods / 'vr/runtimes/OpenXR.hpp'
    s = p.read_text(encoding='utf-8')
    s = once(s, '    uevr::duoview::SubmitContinuity quadview_continuity;',
             '    uevr::quadview::TriViewHold quadview_continuity; // B41: configurable hold window\n'
             '    uint64_t triview_blank_frames{}; // B41: frames sent without a scene image',
             'continuity member')
    s = once(s, '#include "../DuoViewFrame.hpp"', '#include "../DuoViewFrame.hpp"\n#include "../TriViewHold.hpp"',
             'OpenXR include')
    p.write_text(s, encoding='utf-8', newline='\n')

    p = mods / 'vr/runtimes/OpenXR.cpp'
    s = p.read_text(encoding='utf-8')
    s = once(s, '''            } else if (quadview_submitted_pose &&
                quadview_continuity.can_hold(vr->mono_generation(),handle,GetTickCount64())) {
                selected=*quadview_submitted_pose; quadview_holding=true;
            }''', '''            } else if (quadview_submitted_pose &&
                quadview_continuity.can_hold(vr->mono_generation(),handle,GetTickCount64())) {
                selected=*quadview_submitted_pose; quadview_holding=true;
            } else if (quadview_continuity.ready()) {
                // B41: nothing new and the hold window ran out: this frame goes to
                // the headset without a scene image (black / SteamVR void).
                ++triview_blank_frames;
                SPDLOG_WARNING_EVERY_N_SEC(1,"[TriView][BlankFrame] no scene image sent: last real submit {} ms ago, hold window {} ms, blank frames so far {}",
                    quadview_continuity.age_ms(GetTickCount64()),uevr::quadview::TriViewHold::window_ms(),triview_blank_frames);
            }''', 'hold selection')
    p.write_text(s, encoding='utf-8', newline='\n')

    # 2. Queue pin for every mode that writes the shared history (4, 5, 6).
    p = mods / 'vr/D3D12Component.cpp'
    s = p.read_text(encoding='utf-8')
    s = once(s, 'const auto seam_queue=frozen->settings.seam_mode==4 ? comp.edge_submission_queue() : nullptr;',
             'const auto seam_queue=(frozen->settings.seam_mode>=4 && frozen->settings.seam_mode<=6) ? comp.edge_submission_queue() : nullptr;',
             'seam queue pin')
    p.write_text(s, encoding='utf-8', newline='\n')

    # 3. Split the combined "D3D12-device-mismatch" reason. Failure path only.
    p = mods / 'vr/FFakeStereoRenderingHook.cpp'
    s = p.read_text(encoding='utf-8')
    s = once(s, '''            SPDLOG_ERROR_EVERY_N_SEC(1,"[TriView][TargetLifetime] rejected source role={} allocation={} publication={} reason={} target={:x}",
                i, snapshot->resource_allocation_generation, targets.generation,
                reason, reinterpret_cast<uintptr_t>(targets.render_targets[i]));
            return false;''', '''            static std::atomic<uint64_t> b41_rejections{0};
            const auto rejection_count=b41_rejections.fetch_add(1,std::memory_order_relaxed)+1;
            // B41: which part of the device check failed (no extra work on success).
            const bool has_native=owner && owner->native_resource;
            const auto* hook_device=hook ? hook->get_device() : nullptr;
            Microsoft::WRL::ComPtr<ID3D12Device> probe_device{};
            const HRESULT device_hr=has_native ? owner->native_resource->GetDevice(IID_PPV_ARGS(&probe_device)) : E_POINTER;
            SPDLOG_ERROR_EVERY_N_SEC(1,"[TriView][TargetLifetime] rejected source role={} allocation={} publication={} reason={} target={:x} "
                "native_resource={} hook={} hook_device={:x} get_device_hr={:#x} resource_device={:x} live={} rejections_total={}",
                i, snapshot->resource_allocation_generation, targets.generation,
                reason, reinterpret_cast<uintptr_t>(targets.render_targets[i]),
                has_native, hook!=nullptr, reinterpret_cast<uintptr_t>(hook_device), static_cast<uint32_t>(device_hr),
                reinterpret_cast<uintptr_t>(probe_device.Get()), owner && owner->live(), rejection_count);
            return false;''', 'lifetime log')
    p.write_text(s, encoding='utf-8', newline='\n')

    # 4. Menu: hold window, blend distance multiplier, blend shape.
    p = mods / 'VR.hpp'
    s = p.read_text(encoding='utf-8')
    s = once(s, '    const ModCombo::Ptr m_quadview_b40_stability{',
             '    const ModSlider::Ptr m_quadview_b41_hold_ms{ModSlider::create(generate_name("QuadViewB41HoldMs"), 100.f, 1000.f, 250.f)};\n'
             '    const ModSlider::Ptr m_quadview_b41_reach_scale{ModSlider::create(generate_name("QuadViewB41BlendDistance"), 1.f, 3.f, 1.f)};\n'
             '    const ModCombo::Ptr m_quadview_b40_stability{', 'slider members')
    s = once(s, '            *m_quadview_b40_stability,',
             '            *m_quadview_b40_stability, *m_quadview_b41_hold_ms, *m_quadview_b41_reach_scale,',
             'saved options')
    p.write_text(s, encoding='utf-8', newline='\n')

    p = mods / 'VR.cpp'
    s = p.read_text(encoding='utf-8')
    s = once(s, '                m_quadview_context_scale->draw("Context resolution scale");\n',
             '                m_quadview_context_scale->draw("Context resolution scale");\n'
             '                m_quadview_b41_hold_ms->draw("Hold last image on a missed frame (ms)");\n'
             '                ImGui::TextWrapped("If a frame is missing, keep showing the last image (it still follows your head) for up to this long instead of black. 250 = B41 default, 100 = B40.");\n',
             'hold slider UI')
    s = once(s, '                        m_quadview_b40_stability->draw("Temporal stability");\n',
             '                        m_quadview_b40_stability->draw("Temporal stability");\n'
             '                        m_quadview_b41_reach_scale->draw("Colour blend distance (x B40)");\n'
             '                        ImGui::TextWrapped("How far into the periphery the colour/light match reaches (1 = B40, 3 = three times farther).");\n',
             'blend slider UI')
    s = once(s, '            if (m_quadview_edge_mode->value()!=0) {\n                requested.seam_mode=static_cast<uint32_t>(m_quadview_edge_mode->value()+2);',
             '''            uevr::quadview::TriViewHold::set_window_ms(static_cast<uint32_t>(m_quadview_b41_hold_ms->value()));
            if (m_quadview_edge_mode->value()==4) {
                // B41: B40 blend distance multiplier (x1..x3).
                requested.edge_reach_px=std::min(m_quadview_edge_reach->value()*m_quadview_b41_reach_scale->value(),1024.f);
            }
            {
                static std::once_flag b41_build_logged;
                std::call_once(b41_build_logged,[]{ spdlog::info("[TriView][Build] B41.1 (B40 + device-race fix + hold window, rejection diagnostics, queue pin 4-6, blend distance)"); });
            }
            if (m_quadview_edge_mode->value()!=0) {
                requested.seam_mode=static_cast<uint32_t>(m_quadview_edge_mode->value()+2);''', 'per-draw settings')
    s = once(s, '#include "vr/Stalker2NativePolicy.hpp"\n',
             '#include "vr/Stalker2NativePolicy.hpp"\n#include "vr/TriViewHold.hpp"\n', 'VR include')
    p.write_text(s, encoding='utf-8', newline='\n')
    # 5. B41.1: UEVR's Present hook refreshed m_device with GetDevice(&m_device)
    # every frame. COM clears the out pointer before filling it, so other
    # threads could read nullptr for a moment: TriView's target lifetime check
    # then saw "device changed" (log: hook_device=0, resource_device valid),
    # rejected the frame and rebuilt all source targets (~0.67 s, black after
    # the hold window). Fetch into a local and publish only a non-null device.
    p = backend / 'src/hooks/D3D12Hook.cpp'
    s = p.read_text(encoding='utf-8')
    s = once(s, '    swap_chain->GetDevice(IID_PPV_ARGS(&d3d12->m_device));\n',
             '    {\n'
             '        // B41.1: never let other threads observe a transient nullptr device.\n'
             '        ID3D12Device4* present_device{nullptr};\n'
             '        swap_chain->GetDevice(IID_PPV_ARGS(&present_device));\n'
             '        if (present_device != nullptr) d3d12->m_device = present_device;\n'
             '    }\n', 'present device refresh')
    p.write_text(s, encoding='utf-8', newline='\n')
    print('Applied B41.1: device-race fix, hold window, rejection diagnostics, queue pin 4-6, blend distance UI, build log')


if __name__ == '__main__':
    main()

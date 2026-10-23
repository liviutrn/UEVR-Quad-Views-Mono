#!/usr/bin/env python3
"""Build52: consistent source pass classification before view construction.

The previous constructor-only PRIMARY substitution left GetViewPassForIndex
returning SECONDARY for right-eye indices outside that constructor. The new
path is limited to a live native four-source draw and can be toggled off.
Exposure/history memory and shading quality CVars are not modified.
"""
from pathlib import Path
import sys


def once(text, old, new):
    if text.count(old)!=1: raise RuntimeError(f"Shading overlay expected one anchor: {old[:100]!r}")
    return text.replace(old,new,1)


def main():
    root=Path(sys.argv[1]); source=Path(__file__).parent
    cpp=root/'src/mods/vr/FFakeStereoRenderingHook.cpp'
    hp=root/'src/mods/VR.hpp'; vp=root/'src/mods/VR.cpp'
    c=cpp.read_text(encoding='utf-8-sig'); h=hp.read_text(encoding='utf-8-sig'); v=vp.read_text(encoding='utf-8-sig')
    if 'is_quadview_primary_pass_enabled' in h: raise RuntimeError('Shading overlay already applied')
    start=c.index('EStereoscopicPass FFakeStereoRenderingHook::get_view_pass_for_index_hook(')
    end=c.index('\nIStereoRenderTargetManager* FFakeStereoRenderingHook::get_render_target_manager_hook(',start)
    function=c[start:end]
    anchor='    return view_index % 2 == 0 ? EStereoscopicPass::eSSP_PRIMARY : EStereoscopicPass::eSSP_SECONDARY;'
    function=once(function,anchor,(source/'primary_pass_runtime.inc').read_text()+'\n'+anchor)
    c=c[:start]+function+c[end:]
    h=once(h,'    bool is_quadview_supported_title() const;',
        '    bool is_quadview_supported_title() const;\n'
        '    bool is_quadview_primary_pass_enabled() const { return m_quadview_primary_pass->value(); }')
    h=once(h,'    const ModToggle::Ptr m_quadview_foreground_mpc{',
        '    const ModToggle::Ptr m_quadview_primary_pass{ModToggle::create(generate_name("QuadViewPrimaryPass"), true)};\n'
        '    const ModToggle::Ptr m_quadview_foreground_mpc{')
    h=once(h,'            *m_quadview_foreground_mpc,','            *m_quadview_primary_pass,\n            *m_quadview_foreground_mpc,')
    anchor='                m_quadview_foreground_mpc->draw("First-person FOV parity (STALKER 2 MPC)");\n'
    v=once(v,anchor,anchor+'                m_quadview_primary_pass->draw("Consistent source shading pass (STALKER 2)");\n')

    # Opt-in dispatch CPU measurement uses the existing timing control. The
    # GPU number still measures only the raster compositor, never total GPU time.
    anchor='        FFakeStereoRenderingHook::QuadViewNativeBuildContext previous_context=std::move(native_context);'
    c=once(c,anchor,'''        const bool qv_cpu_timing=qv_snapshot->settings.gpu_timing;
        const auto qv_cpu_started=qv_cpu_timing?std::chrono::steady_clock::now():std::chrono::steady_clock::time_point{};
        uint8_t qv_cpu_completed{};
        utility::ScopeGuard qv_cpu_scope{[&]() {
            if (!qv_cpu_timing || qv_cpu_completed!=4) return;
            const auto now=std::chrono::steady_clock::now();
            const double ms=std::chrono::duration<double,std::milli>(now-qv_cpu_started).count();
            static std::mutex timing_mutex;
            std::lock_guard timing_lock{timing_mutex};
            static uint64_t count{}; static double sum{},peak{};
            static auto last=now;
            ++count;sum+=ms;peak=(std::max)(peak,ms);
            if (now-last>=std::chrono::seconds(2)) {
                SPDLOG_INFO("[QuadViews][CPU] native_dispatch samples={} avg_ms={:.3f} max_ms={:.3f} includes_four_renderer_calls=true excludes_gpu=true excludes_rest_of_game=true",
                    count,sum/double(count),peak);
                count=0;sum=peak=0;last=now;
            }
        }};
'''+anchor)
    c=once(c,'        if (!qv_dispatch_result) {',
        '        qv_cpu_completed=qv_dispatch_result.completed;\n        if (!qv_dispatch_result) {')
    anchor='        auto* options = reinterpret_cast<sdk::FSceneViewInitOptionsUE5*>(init_options);'
    c=once(c,anchor,"""        if (qv_native_constructor && qv_original_view_count<4) {
            uevr::quadview::HookTraceRecord r{};r.event="SHADING_SOURCE";r.reason="constructor_input_pass";
            r.generation=qv_draw_key.generation;r.serial=qv_draw_key.draw_serial;r.role=unsigned(qv_original_view_count);r.mode=7;
            r.family=reinterpret_cast<uintptr_t>(family);r.target=reinterpret_cast<uintptr_t>(target);
            r.root=reinterpret_cast<uintptr_t>(state);r.index=static_cast<int>(qv_original_pass);
            r.expected_index=static_cast<int>(EStereoscopicPass::eSSP_PRIMARY);
            r.result=static_cast<int>(init_options->get_stereo_pass());
            uevr::quadview::emit_hook_trace(40+size_t(qv_original_view_count),r);
        }
"""+anchor)
    cpp.write_text(c,encoding='utf-8',newline='');hp.write_text(h,encoding='utf-8',newline='');vp.write_text(v,encoding='utf-8',newline='')
    print('Applied ID7 initial-pass shading parity candidate and opt-in dispatch CPU measurement.')


if __name__=='__main__': main()

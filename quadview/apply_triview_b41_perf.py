#!/usr/bin/env python3
"""B41 optional performance panel on top of B40; exact anchors, fail closed."""
from pathlib import Path
import sys

def once(text, old, new, path):
    count=text.count(old)
    if count != 1:
        raise RuntimeError(f"B41 {path}: wanted 1 exact anchor, found {count}: {old[:110]!r}")
    return text.replace(old, new, 1)

def main():
    if len(sys.argv)!=3:
        raise SystemExit("usage: apply_triview_b41_perf.py backend quadview")
    root=Path(sys.argv[1])/"src/mods"
    source=Path(sys.argv[2])/"QuadViewPerfDiagnostics.hpp"
    dest=root/"vr/QuadViewPerfDiagnostics.hpp"
    data=source.read_bytes()
    if dest.exists() and dest.read_bytes()!=data:
        raise RuntimeError("B41 refuses to overwrite another profiler header")
    dest.write_bytes(data)

    p=root/"vr/FFakeStereoRenderingHook.cpp"
    s=p.read_text(encoding="utf-8")
    s=once(s,"            [&]() { call_original(); },\n",
        """            [&]() {
                const auto b41_begin=uevr::quadview::perf::begin();
                call_original(); // preserve original UE ordering
                uevr::quadview::perf::end_role(native_context.current_slot,b41_begin);
            },
""",p)
    p.write_text('#include "QuadViewPerfDiagnostics.hpp"\n'+s,encoding="utf-8",newline="\n")

    p=root/"vr/D3D12Component.cpp"
    s=p.read_text(encoding="utf-8")
    s=once(s,'                                    VR::get()->note_quadview_gpu_ms(comp.gpu_milliseconds());',
        '''                                    VR::get()->note_quadview_gpu_ms(comp.gpu_milliseconds());
                                    // Fence-retired compositor GPU timestamps; never mislabeled as scene GPU.
                                    uevr::quadview::perf::retired_gpu(comp.gpu_milliseconds(),comp.seam_gpu_milliseconds());''',p)
    s=once(s,
        '                                    recorded=comp.record_sources(commands.cmd_list.Get(),native_sources,destination,',
        '''                                    const auto b41_record_start=uevr::quadview::perf::begin();
                                    recorded=comp.record_sources(commands.cmd_list.Get(),native_sources,destination,''',p)
    s=once(s,'                                    if (comp.commands_recorded()) commands.has_commands=true;',
        '''                                    uevr::quadview::perf::end_record(b41_record_start);
                                    if (comp.commands_recorded()) commands.has_commands=true;''',p)
    s=once(s,'                            const bool accepted=m_openxr.copy(',
        '''                            const auto b41_copy_start=uevr::quadview::perf::begin();
                            const bool accepted=m_openxr.copy(''',p)
    s=once(s,'                            if (accepted && recorded && output &&',
        '''                            uevr::quadview::perf::end_copy(b41_copy_start);
                            if (accepted && recorded && output &&''',p)
    s=once(s,'                                // Shared mode-transition readiness also gates post-present GPU memory retirement.',
        '''                                uevr::quadview::perf::output_accepted();
                                // Shared mode-transition readiness also gates post-present GPU memory retirement.''',p)
    s=once(s,'                                vr->set_quadview_status("Waiting for a reusable QuadView output slot");',
        '''                                uevr::quadview::perf::output_failed();
                                vr->set_quadview_status("Waiting for a reusable QuadView output slot");''',p)
    s=once(s,'                            vr->set_quadview_status("Waiting for four distinct main-family views and executed source");',
        '''                            uevr::quadview::perf::source_missing();
                            vr->set_quadview_status("Waiting for four distinct main-family views and executed source");''',p)
    p.write_text('#include "QuadViewPerfDiagnostics.hpp"\n'+s,encoding="utf-8",newline="\n")

    p=root/"VR.cpp"
    s=p.read_text(encoding="utf-8")
    ui=r'''                if (ImGui::TreeNode("B41 Performance Diagnostics")) {
                    bool b41_on=uevr::quadview::perf::enabled.load(std::memory_order_acquire);
                    if (ImGui::Checkbox("Enable TriView profiler (default off)", &b41_on)) {
                        uevr::quadview::perf::set_enabled(b41_on);
                        if (b41_on) m_quadview_gpu_timing->value()=true;
                    }
                    ImGui::TextWrapped("CPU view callback is not GPU scene time. GPU compositor timestamps are fence-retired and exclude UE scene, DLSS/NR, SteamVR and driver. Output cadence counts composed images, not headset display frames.");
                    const auto b41_iv=uevr::quadview::perf::output_interval.snapshot();
                    const double b41_fps=b41_iv.average_ms>0.001?1000.0/b41_iv.average_ms:0.0;
                    ImGui::Text("Composed: %.1f FPS (interval mean %.2f ms; max %.2f; n=%llu)",
                        b41_fps,b41_iv.average_ms,b41_iv.maximum_ms,(unsigned long long)b41_iv.count);
                    const auto b41_ok=uevr::quadview::perf::composed.load(std::memory_order_relaxed);
                    const auto b41_failed=uevr::quadview::perf::copy_failed.load(std::memory_order_relaxed);
                    const auto b41_missing=uevr::quadview::perf::missing_source.load(std::memory_order_relaxed);
                    ImGui::Text("Composed %llu; rejected copy %llu; missing source %llu",
                        (unsigned long long)b41_ok,(unsigned long long)b41_failed,(unsigned long long)b41_missing);
                    const auto b41_context=uevr::quadview::perf::source_context_cpu.snapshot();
                    const auto b41_left=uevr::quadview::perf::source_left_cpu.snapshot();
                    const auto b41_right=uevr::quadview::perf::source_right_cpu.snapshot();
                    ImGui::Text("UE context CPU callback: avg %.3f / max %.3f ms (n=%llu)",
                        b41_context.average_ms,b41_context.maximum_ms,(unsigned long long)b41_context.count);
                    ImGui::Text("UE left CPU callback:    avg %.3f / max %.3f ms (n=%llu)",
                        b41_left.average_ms,b41_left.maximum_ms,(unsigned long long)b41_left.count);
                    ImGui::Text("UE right CPU callback:   avg %.3f / max %.3f ms (n=%llu)",
                        b41_right.average_ms,b41_right.maximum_ms,(unsigned long long)b41_right.count);
                    const auto b41_record=uevr::quadview::perf::composite_record_cpu.snapshot();
                    const auto b41_copy=uevr::quadview::perf::copy_call_cpu.snapshot();
                    ImGui::Text("CPU compositor record: avg %.3f / max %.3f ms",b41_record.average_ms,b41_record.maximum_ms);
                    ImGui::Text("CPU OpenXR copy call (includes record): avg %.3f / max %.3f ms",b41_copy.average_ms,b41_copy.maximum_ms);
                    const auto b41_gpu=uevr::quadview::perf::composite_gpu.snapshot();
                    const auto b41_seam=uevr::quadview::perf::seam_analysis_gpu.snapshot();
                    if (b41_gpu.count) {
                        ImGui::Text("GPU compositor: avg %.3f / max %.3f ms (n=%llu)",
                            b41_gpu.average_ms,b41_gpu.maximum_ms,(unsigned long long)b41_gpu.count);
                        ImGui::Text("GPU seam analysis: avg %.3f / max %.3f ms",b41_seam.average_ms,b41_seam.maximum_ms);
                    } else ImGui::TextUnformatted("GPU compositor: waiting for retired timestamp samples");
                    ImGui::TextWrapped("Per-view UE scene GPU, DLSS/NR GPU and total GPU frame time require an external GPU capture; they cannot be derived by subtracting these values.");
                    if (ImGui::Button("Reset TriView profiling samples")) uevr::quadview::perf::reset();
                    if (ImGui::Button("Export TriView profiling summary to UEVR log")) {
                        SPDLOG_INFO("[TriViewPerfB41] composed={} output_rejected={} source_missing={} cadence_fps={:.2f} interval_avg_ms={:.3f} interval_max_ms={:.3f} cpu_context_avg_ms={:.3f} cpu_left_avg_ms={:.3f} cpu_right_avg_ms={:.3f} cpu_record_avg_ms={:.3f} cpu_copy_avg_ms={:.3f} gpu_comp_avg_ms={:.3f} gpu_comp_max_ms={:.3f} gpu_seam_avg_ms={:.3f} gpu_samples={}",
                            b41_ok,b41_failed,b41_missing,b41_fps,b41_iv.average_ms,b41_iv.maximum_ms,
                            b41_context.average_ms,b41_left.average_ms,b41_right.average_ms,
                            b41_record.average_ms,b41_copy.average_ms,b41_gpu.average_ms,b41_gpu.maximum_ms,b41_seam.average_ms,b41_gpu.count);
                    }
                    ImGui::TreePop();
                }
'''
    s=once(s,'                const auto diagnostic_key=quadview_key();',
        ui+'                const auto diagnostic_key=quadview_key();',p)
    p.write_text('#include "vr/QuadViewPerfDiagnostics.hpp"\n'+s,encoding="utf-8",newline="\n")
    print("B41 profiler installed: CPU callback/copy/record, fence-retired compositor GPU, cadence, UI/log")

if __name__=="__main__":
    main()

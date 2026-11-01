#!/usr/bin/env python3
"""Build52 guarded diagnostic overlay; apply AFTER Build51's full overlay chain."""
from pathlib import Path
import shutil
import sys

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Build52 exact source anchor count {text.count(old)} (wanted 1): {old[:110]!r}")
    return text.replace(old, new, 1)

def patch_header(text):
    text = once(text, '#include "QuadViewShaderBytecode.hpp"',
                '#include "QuadViewShaderBytecode.hpp"\n#include "QuadViewAutoCapture.hpp"')
    text = once(text, '        read_timing();\n        owner_.reset();',
                '        read_timing();\n        build52_capture_.finish();\n        owner_.reset();')
    checkpoint = '''        if (timed) {
            commands->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
            commands->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timestamps_.Get(),0);
            timing_pending_=true;
        }
        for (size_t i = 0; i != 4; ++i) {'''
    text = once(text, checkpoint, checkpoint.replace(
        '        for (size_t i = 0; i != 4; ++i) {',
        '        // Build52: read-only GPU copy AFTER composition, BEFORE sources leave shader state.\n'
        '        // Readback is consumed only when the existing per-slot fence retires.\n'
        '        build52_capture_.queue(commands,device_.Get(),sources,layout,\n'
        '                               source_generation,source_serial,source_engine_frame);\n'
        '        for (size_t i = 0; i != 4; ++i) {'))
    text = once(text, '                std::shared_ptr<const void> owner, UINT64 timestamp_frequency = 0) {\n        recorded_ = false;', 
                '                std::shared_ptr<const void> owner, UINT64 timestamp_frequency = 0,\n'
                '                uint64_t source_generation = 0,uint64_t source_serial = 0,\n'
                '                uint32_t source_engine_frame = 0) {\n        recorded_ = false;')
    text = once(text, '    ComPtr<ID3D12Device> device_;',
                '    uevr::quadview::diagnostics::AutoCapture build52_capture_{};\n'
                '    ComPtr<ID3D12Device> device_;')
    return text

def patch_consumer(text):
    # The GPU callback has an explicit capture list. Capture only stable scalars,
    # not the optional source owner; the compiler rejects uncaptured 'source'.
    outer='''                            const bool accepted=m_openxr.copy(
                                (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE,nullptr,'''
    replacement='''                            const auto capture_generation=source->generation;
                            const auto capture_serial=source->serial;
                            const auto capture_engine_frame=source->engine_frame;
                            const bool accepted=m_openxr.copy(
                                (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE,nullptr,'''
    text=once(text,outer,replacement)
    capture='''[this,packet,frozen,native_sources,timestamp_frequency,&recorded,&output,&command_list]'''
    text=once(text,capture,
        '''[this,packet,frozen,native_sources,timestamp_frequency,
                                 capture_generation,capture_serial,capture_engine_frame,
                                 &recorded,&output,&command_list]''')
    anchor='''                                        frozen->settings.gpu_timing ? timestamp_frequency : 0);'''
    return once(text,anchor,
        '''                                        frozen->settings.gpu_timing ? timestamp_frequency : 0,
                                        capture_generation,capture_serial,capture_engine_frame);''')

def patch_hook_trace(text):
    anchor='namespace uevr::quadview {\nint hook_trace_mode() {'
    text=once(text,anchor,'#include "QuadViewAutoTrace.hpp"\n'+anchor)
    text=once(text,'    if(!decision.emit) return;\n    SPDLOG_INFO(',
        '    if(!decision.emit) return;\n'
        '    diagnostics::persist_hook_event(site,r,decision.count);\n    SPDLOG_INFO(')
    demand='''    if (vr->is_quadview_mode_selected()) {
        const auto demanded=vr->quadview_desired_view_count();'''
    text=once(text,demand,'''    if (vr->is_quadview_mode_selected()) {
        // Build52: this fires even if a four-view family is never accepted.
        {
            uevr::quadview::HookTraceRecord r{};
            r.event="VIEW_DEMAND";r.reason="quadview_selected";
            r.mode=7;r.generation=vr->mono_generation();
            r.result=vr->is_quadview_renderer_active()?1:0;
            r.pending=vr->quadview_desired_view_count();
            uevr::quadview::emit_hook_trace(142,r);
        }
        const auto demanded=vr->quadview_desired_view_count();''')
    return text

def main():
    if len(sys.argv)!=2:
        raise SystemExit("Usage: apply_auto_capture.py BACKEND_DIRECTORY")
    source=Path(__file__).resolve().parent
    target=Path(sys.argv[1]) / "src/mods/vr"
    file=target / "QuadViewD3D12.hpp"
    consumer=target / "D3D12Component.cpp"
    hook=target / "FFakeStereoRenderingHook.cpp"
    # Validate all three generated sources before writing any modified files.
    patched=patch_header(file.read_text(encoding="utf-8"))
    patched_consumer=patch_consumer(consumer.read_text(encoding="utf-8"))
    patched_hook=patch_hook_trace(hook.read_text(encoding="utf-8"))
    capture=source / "QuadViewAutoCapture.hpp"
    trace=source / "QuadViewAutoTrace.hpp"
    if not capture.is_file() or not trace.is_file():
        raise RuntimeError("Missing Build52 capture/trace headers")
    shutil.copyfile(capture,target / "QuadViewAutoCapture.hpp")
    shutil.copyfile(trace,target / "QuadViewAutoTrace.hpp")
    file.write_text(patched,encoding="utf-8")
    consumer.write_text(patched_consumer,encoding="utf-8")
    hook.write_text(patched_hook,encoding="utf-8")
    print("Build52: persistent pre-compositor trace + frame-stamped GPU capture applied.")

if __name__=="__main__":
    main()

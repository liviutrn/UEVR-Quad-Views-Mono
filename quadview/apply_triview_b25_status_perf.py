#!/usr/bin/env python3
"""B25: after all overlays, suppress routine status chatter and dormant RHI tracing."""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply_triview_b25_status_perf.py BACKEND")
root = Path(sys.argv[1])

def patch(rel, edits):
    p = root / rel
    data = p.read_text(encoding="utf-8")
    for label, old, new in edits:
        count = data.count(old)
        if count != 1:
            raise RuntimeError(f"{rel}: {label}: expected exactly one anchor, got {count}")
        data = data.replace(old, new, 1)
    p.write_text(data, encoding="utf-8", newline="\n")

patch("src/mods/VR.cpp", [
    ("healthy GT admission",
     'set_quadview_status("Waiting for four engine view histories and main-family raster");',
     '// B25: healthy GT admission is not a stall; fresh XR submit owns the status.'),
])

patch("src/mods/vr/FFakeStereoRenderingHook.cpp", [
    ("healthy native completion",
     'vr->set_quadview_status("Four isolated native source renders completed; waiting for exact quartet RHI tails");',
     '// B25: healthy source completion is not a stall.'),
    ("healthy producer registration",
     'vr->set_quadview_status("Four-view source registered before the renderer copies this family");',
     '// B25: source registration is a routine success.'),
    ("transient first eye pose",
     'if (!vr->quadview_note_eye_pose(static_cast<uint32_t>(view_index)))\n'
     '                vr->set_quadview_status("Waiting for both context offsets to capture one exact OpenXR pose frame");',
     '(void)vr->quadview_note_eye_pose(static_cast<uint32_t>(view_index));'
     ' // B25: first eye pending the other eye is expected.'),
    ("avoid heavy hook trace preparation",
     'auto qv_trace=[&](size_t site,const char* event,const char* reason,const char* detail="none",int result=-1) {\n'
     '            uevr::quadview::HookTraceRecord r{};',
     'auto qv_trace=[&](size_t site,const char* event,const char* reason,const char* detail="none",int result=-1) {\n'
     '            if (!uevr::quadview::hook_trace_enabled()) return;\n'
     '            uevr::quadview::HookTraceRecord r{};'),
    ("prelock record creation",
     '        uevr::quadview::HookTraceRecord qv_pre{};',
     '        const bool qv_trace_verbose=uevr::quadview::hook_trace_enabled();\n'
     '        if (qv_trace_verbose) {\n'
     '        uevr::quadview::HookTraceRecord qv_pre{};'),
    ("prelock record close and conditional clock",
     '        uevr::quadview::emit_hook_trace(7,qv_pre);\n'
     '        const auto qv_lock_start=std::chrono::steady_clock::now();',
     '        uevr::quadview::emit_hook_trace(7,qv_pre);\n'
     '        }\n'
     '        const auto qv_lock_start=qv_trace_verbose ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};'),
    ("conditional postlock clock",
     '        const auto qv_lock_acquired=std::chrono::steady_clock::now();',
     '        const auto qv_lock_acquired=qv_trace_verbose ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};'),
    ("RHI observation payload only when verbose",
     '        uevr::quadview::HookTraceRecord qv_rhi{};\n'
     '        const auto* qv_native_owner=',
     '        uevr::quadview::HookTraceRecord qv_rhi{};\n'
     '        if (qv_trace_verbose) {\n'
     '        const auto* qv_native_owner='),
    ("RHI observation block close",
     '        qv_rhi.original_vtable=reinterpret_cast<uintptr_t>(original_vtable);\n'
     '        auto qv_emit_rhi=[qv_rhi](size_t site,const char* event,const char* reason,uint64_t us=0,int result=-1) {\n'
     '            auto r=qv_rhi;',
     '        qv_rhi.original_vtable=reinterpret_cast<uintptr_t>(original_vtable);\n'
     '        }\n'
     '        auto qv_emit_rhi=[qv_rhi,qv_trace_verbose](size_t site,const char* event,const char* reason,uint64_t us=0,int result=-1) {\n'
     '            if (!qv_trace_verbose) return;\n'
     '            auto r=qv_rhi;'),
    ("sync diagnostic timer conditional",
     '            const auto started=std::chrono::steady_clock::now();\n'
     '            const auto result=runtime->synchronize_frame(frame,callsite);',
     '            const auto started=qv_trace_verbose ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};\n'
     '            const auto result=runtime->synchronize_frame(frame,callsite);'),
    ("sync diagnostic elapsed conditional",
     '            qv_emit_rhi(11,"XR_SYNC_RETURN","synchronize_frame",static_cast<uint64_t>(',
     '            if (qv_trace_verbose) qv_emit_rhi(11,"XR_SYNC_RETURN","synchronize_frame",static_cast<uint64_t>('),
    ("original callback diagnostic timer conditional",
     '            const auto qv_original_started=std::chrono::steady_clock::now();',
     '            const auto qv_original_started=qv_trace_verbose ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};'),
    ("original callback diagnostic elapsed conditional",
     '            qv_emit_rhi(13,"ORIGINAL_RETURN","engine_callback",static_cast<uint64_t>(',
     '            if (qv_trace_verbose) qv_emit_rhi(13,"ORIGINAL_RETURN","engine_callback",static_cast<uint64_t>('),
    ("final RHI diagnostic timer conditional",
     '            qv_emit_rhi(15,"RHI_COMPLETE",N==correct_execute_index?"correct_index":"other_index",',
     '            if (qv_trace_verbose) qv_emit_rhi(15,"RHI_COMPLETE",N==correct_execute_index?"correct_index":"other_index",'),
    ("RT routing trace preparation conditional",
     'auto qv_route_trace=[=](size_t site,const char* event,const char* reason,uintptr_t list) {\n'
     '        uevr::quadview::HookTraceRecord r{};',
     'auto qv_route_trace=[=](size_t site,const char* event,const char* reason,uintptr_t list) {\n'
     '        if (!uevr::quadview::hook_trace_enabled()) return;\n'
     '        uevr::quadview::HookTraceRecord r{};'),
    ("skip optional diagnostic render snapshot",
     'reinterpret_cast<uintptr_t>(view_family.get_scene_interface()),&native_trace);',
     'reinterpret_cast<uintptr_t>(view_family.get_scene_interface()),'
     'uevr::quadview::hook_trace_enabled()?&native_trace:nullptr);'),
])
print("B25 applied: routine status chatter removed; verbose trace collection skipped by default.")

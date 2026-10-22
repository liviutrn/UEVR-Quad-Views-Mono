#!/usr/bin/env python3
"""Build50: trace source selection, queued composite copy, and XR end-frame result."""

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    root = Path(sys.argv[1])
    d3d_path = root / "src/mods/vr/D3D12Component.cpp"
    openxr_path = root / "src/mods/vr/runtimes/OpenXR.cpp"
    d3d = d3d_path.read_text()
    openxr = openxr_path.read_text()

    markers = ('trace.event="SOURCE_SELECT"', 'trace.event="COPY_ENQUEUED"')
    applied = [marker in d3d for marker in markers]
    if any(applied):
        if all(applied) and '? "XR_SUBMIT" : "XR_END_RETURN"' in openxr:
            print("Build50 output trace is already applied.")
            return
        raise RuntimeError("Output trace looks partially applied; inspect files before retrying")
    if '? "XR_SUBMIT" : "XR_END_RETURN"' in openxr:
        raise RuntimeError("XR_SUBMIT trace exists without matching D3D12 output traces")

    selection = '''                        const auto source=stereo && vr->is_quadview_renderer_active()
                            ? stereo->quadview_delivery.select(vr->mono_generation(),GetCurrentThreadId())
                            : std::optional<FFakeStereoRenderingHook::QuadViewDelivery::Source>{};'''
    d3d = replace_once(d3d, selection, selection + '''
                        {
                            uevr::quadview::HookTraceRecord trace{};
                            trace.event="SOURCE_SELECT";
                            trace.reason=source ? "selected" : "no_executed_source";
                            trace.generation=source ? source->generation : vr->mono_generation();
                            trace.serial=source ? source->serial : 0;
                            trace.owner_generation=source ? source->generation : 0;
                            trace.owner_serial=trace.serial;
                            trace.frame=frame_count;
                            trace.canonical_frame=source ? source->engine_frame : 0;
                            trace.mode=7;
                            trace.source=static_cast<bool>(source);
                            trace.result=source ? 1 : 0;
                            if (source) { trace.target=source->target; trace.scene=source->scene; }
                            uevr::quadview::emit_hook_trace(25,trace);
                        }''', "SOURCE_SELECT")

    copy_gate = '''                            if (accepted && recorded && output &&
                                stereo->quadview_delivery.submitted(*source,reinterpret_cast<uintptr_t>(output))) {'''
    d3d = replace_once(d3d, copy_gate, copy_gate + '''
                                {
                                    uevr::quadview::HookTraceRecord trace{};
                                    trace.event="COPY_ENQUEUED";
                                    trace.reason="composite_recorded_and_swapchain_released";
                                    trace.generation=source->generation;
                                    trace.serial=source->serial;
                                    trace.owner_generation=source->generation;
                                    trace.owner_serial=source->serial;
                                    trace.frame=frame_count;
                                    trace.canonical_frame=source->engine_frame;
                                    trace.mode=7;
                                    trace.source=true;
                                    trace.result=1;
                                    trace.target=reinterpret_cast<uintptr_t>(output);
                                    trace.list=command_list;
                                    uevr::quadview::emit_hook_trace(26,trace);
                                }''', "COPY_ENQUEUED")

    end_frame = '    auto result = xrEndFrame(this->session, &frame_end_info);'
    openxr = replace_once(openxr, end_frame, end_frame + '''
    if (vr->is_quadview_mode_selected()) {
        uevr::quadview::HookTraceRecord trace{};
        trace.event=vr->is_quadview_renderer_active() && result==XR_SUCCESS && !projection_layer_views.empty()
            ? "XR_SUBMIT" : "XR_END_RETURN";
        trace.reason=projection_layer_views.empty() ? "no_projection_views" : "projection_views";
        trace.generation=vr->mono_generation();
        trace.serial=submit_state.quadview_serial;
        trace.owner_generation=trace.serial ? trace.generation : 0;
        trace.owner_serial=trace.serial;
        trace.frame=submit_state.frame_count;
        trace.canonical_frame=submit_state.frame_count;
        trace.mode=7;
        trace.source=trace.serial != 0;
        trace.result=static_cast<int>(result);
        trace.pending=projection_layer_views.size();
        uevr::quadview::emit_hook_trace(27,trace);
    }''', "XR_SUBMIT")

    d3d_path.write_text(d3d)
    openxr_path.write_text(openxr)
    print("Applied Build50 output trace observations.")


if __name__ == "__main__":
    main()

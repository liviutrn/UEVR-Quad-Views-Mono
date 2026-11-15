#!/usr/bin/env python3
"""VectorXR stereo investigation: async route telemetry and JIT pair-release safety.

Apply AFTER the pinned 0.20.1 -> mono -> DynamicSmooth -> #21 -> #22 -> #22b
chain. Every anchor must match once; write nothing until all edits validate.
No optical-flow algorithm, image size, pose, or synthesis quality is changed.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
G = root / "layer/include/depthxr/framegen_gpu.h"
D = root / "layer/src/framegen/framegen_d3d12.cpp"
H = root / "layer/include/depthxr/framegen_presenter.h"
P = root / "layer/src/framegen/framegen_presenter.cpp"
sources = {p: p.read_text(encoding="utf-8") for p in (G, D, H, P)}

def edit(path, old, new, label):
    count = sources[path].count(old)
    if count != 1:
        raise SystemExit(f"stereo route/release patch: {label}: expected 1 anchor, found {count}; nothing written")
    sources[path] = sources[path].replace(old, new, 1)

edit(G,
    "    double hardware_call_ms{0.0}; // CPU time the optical flow hardware's execute calls took\n",
    """    double hardware_call_ms{0.0}; // CPU time the optical flow hardware's execute calls took
    // Metadata sampled with already asynchronous GPU timestamps; never wait
    // on a fence to fill these. 0=shader/no hardware, 1=atlas, 2=per-eye.
    std::uint32_t route_kind{0};
    std::uint32_t route_views{0};
    std::uint32_t route_input_width{0}, route_input_height{0};
    std::uint32_t route_atlas_width{0}, route_atlas_height{0};
""", "analysis timing metadata")

edit(D,
    "    bool analysis_pending{false}; // an analysis whose timing TakeTimings has not returned\n",
    """    bool analysis_pending{false}; // an analysis whose timing TakeTimings has not returned
    std::uint32_t route_kind{0}, route_views{0};
    std::uint32_t route_input_width{0}, route_input_height{0};
    std::uint32_t route_atlas_width{0}, route_atlas_height{0};
""", "frame slot route metadata")

edit(D,
    """        if (ok && hardware) {
            ok = RunHardwareFlow(recordings, slot, slot_index, error);""",
    """        // The route is selected after all view plans are recorded; a view
        // not waiting for hardware must not be misreported as atlas work.
        slot.route_kind = hardware ? (atlas_in_use_ ? 1u : 2u) : 0u;
        slot.route_views = static_cast<std::uint32_t>(views.size());
        const auto input_extent = views.empty() ? FrameGenExtent{}
            : FrameGenPyramid(views.front().request.extent)[1];
        slot.route_input_width = input_extent.width;
        slot.route_input_height = input_extent.height;
        slot.route_atlas_width = slot.route_atlas_height = 0;
#ifdef DEPTHXR_NVOF
        if (hardware && atlas_in_use_ && atlas_.newest.resource) {
            const auto atlas_extent = atlas_.newest.resource->GetDesc();
            slot.route_atlas_width = static_cast<std::uint32_t>(atlas_extent.Width);
            slot.route_atlas_height = atlas_extent.Height;
        }
#endif
        if (ok && hardware) {
            ok = RunHardwareFlow(recordings, slot, slot_index, error);""",
    "actual per-frame atlas or per-view route")

edit(D,
    "        timing.hardware_call_ms = slot.hardware_call_ms;\n",
    "        timing.hardware_call_ms = slot.hardware_call_ms;\n",
    "hardware-call anchor")
# Move outside the hardware-only branch so shader analyses are reported too.
edit(D,
    """        timing.end = clock(stamps[kTimingStamps - 1]);
        constexpr std::size_t kKeptTimings = 16;""",
    """        timing.end = clock(stamps[kTimingStamps - 1]);
        timing.route_kind = slot.hardware_timed ? slot.route_kind : 0u;
        timing.route_views = slot.route_views;
        timing.route_input_width = slot.route_input_width;
        timing.route_input_height = slot.route_input_height;
        timing.route_atlas_width = slot.route_atlas_width;
        timing.route_atlas_height = slot.route_atlas_height;
        constexpr std::size_t kKeptTimings = 16;""",
    "copy route at fence-retirement")

edit(H,
    "        bool timed_out{false};  // ...an output image the runtime did not hand back in time\n",
    """        bool timed_out{false};  // ...an output image the runtime did not hand back in time
        bool release_failed{false}; // a generated eye output was not accepted by OpenXR
""", "explicit output release failure")

edit(H,
    "    std::vector<double> synth_lock_ms_;\n",
    """    std::vector<double> synth_lock_ms_;
    std::uint64_t route_trace_samples_{0}; // diagnostic only, under mutex_
""", "sample-throttled route log counter")

edit(P,
    """        if (timing.start != Clock::time_point{} && timing.end != Clock::time_point{}) {
            AddSample(analysis_ms_, Milliseconds(timing.end - timing.start));
        }""",
    """        if (timing.start != Clock::time_point{} && timing.end != Clock::time_point{}) {
            AddSample(analysis_ms_, Milliseconds(timing.end - timing.start));
            // A GPU fence has already retired this sample; no profiler waits.
            // The bracket includes the queued hardware dependency, NOT only
            // time the OFA unit itself was executing.
            if (logger_ && timing.route_views && (++route_trace_samples_ % 120 == 1)) {
                const bool bracket = timing.hardware_end > timing.hardware_start &&
                                     timing.hardware_start >= timing.start &&
                                     timing.end >= timing.hardware_end;
                const auto before = bracket ? Milliseconds(timing.hardware_start - timing.start) : -1.0;
                const auto between = bracket ? Milliseconds(timing.hardware_end - timing.hardware_start) : -1.0;
                const auto after = bracket ? Milliseconds(timing.end - timing.hardware_end) : -1.0;
                const char* route = timing.route_kind == 1 ? "atlas" :
                                    timing.route_kind == 2 ? "per-eye" : "shader/no-hardware";
                logger_->Info(std::string("FrameGen stereo route: views=") +
                    std::to_string(timing.route_views) + " route=" + route +
                    " flowInput=" + std::to_string(timing.route_input_width) + "x" +
                    std::to_string(timing.route_input_height) +
                    " atlas=" + std::to_string(timing.route_atlas_width) + "x" +
                    std::to_string(timing.route_atlas_height) +
                    " gpuTotalMs=" + Number(Milliseconds(timing.end - timing.start), 2) +
                    " preBracketMs=" + Number(before, 2) +
                    " flowFenceBracketMs=" + Number(between, 2) +
                    " postBracketMs=" + Number(after, 2) +
                    " nvOfExecuteCpuMs=" + Number(timing.hardware_call_ms, 2));
            }
        }""",
    "retired GPU timeline / atlas route logging")

edit(P,
    """    for (Output& output : output_sets_.front()) {
        XrSwapchainImageReleaseInfo release{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
        {
            std::scoped_lock submit(submit_mutex_);
            const PresenterCall call(*this, "xrReleaseSwapchainImage");
            xr_.release(output.swapchain, &release);
        }
        output.acquired = false;
        output.waited = false;
    }
    // The real frame's views, showing the images just written""",
    """    // Release the RIGHT eye first. More importantly, check every result:
    // ignoring a failed right-eye release falsely marks that image ready,
    // then submits an updated left eye against an older right eye.
    // A failed release is never described as a successful generated pair.
    for (std::size_t n = output_sets_.front().size(); n > 0; --n) {
        Output& output = output_sets_.front()[n - 1];
        XrSwapchainImageReleaseInfo release{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
        XrResult released = XR_ERROR_RUNTIME_FAILURE;
        {
            std::scoped_lock submit(submit_mutex_);
            const PresenterCall call(*this, "xrReleaseSwapchainImage");
            released = xr_.release(output.swapchain, &release);
        }
        if (XR_FAILED(released)) {
            // It is still acquired/waited if the runtime rejected release.
            // Do not publish an allegedly coherent pair this refresh. A
            // future successful pair may recover; never call Release twice
            // on an image already successfully released.
            std::scoped_lock lock(mutex_);
            ++totals_.unwritten_failed;
            ++repeated_;
            write.failed = write.release_failed = true;
            write.error = "eye " + std::to_string(n - 1) +
                          " output image release failed (" + std::to_string(released) + ")";
            if (logger_) logger_->Error("Frame Generation: " + write.error +
                "; holding previous complete stereo frame.");
            return false;
        }
        output.acquired = false;
        output.waited = false;
    }
    // The real frame's views, showing the images just written""",
    "release both eyes with checked results")

edit(P,
    """            DropStaleDepthLocked(content);
            const bool usable = content.valid""",
    """            if (write.release_failed) {
                // A partial swapchain release may have happened. Do not
                // xrEndFrame any pair until a complete successful write.
                submit = false;
                ++totals_.stale_skipped;
            }
            DropStaleDepthLocked(content);
            const bool usable = content.valid""",
    "hold last good stereo pair after release error")

for path, value in sources.items():
    path.write_text(value, encoding="utf-8")
print("PASS VectorXR stereo route telemetry and paired release checks (4 files)")

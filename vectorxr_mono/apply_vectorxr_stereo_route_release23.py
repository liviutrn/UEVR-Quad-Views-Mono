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
T = root / "layer/tests/framegen_presenter_tests.cpp"
sources = {p: p.read_text(encoding="utf-8") for p in (G, D, H, P, T)}

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


# A fake-runtime fault in the RIGHT eye's release (after the GPU wrote both
# images), which must never reach xrEndFrame as a half-updated pair.
edit(T,
    "std::map<XrSwapchain, int> g_releases; // images released per swapchain",
    """std::map<XrSwapchain, int> g_releases; // images released per swapchain
std::vector<XrSwapchain> g_created_outputs23;
std::atomic<std::uintptr_t> g_fault_right23{0};
std::atomic<int> g_fault_count23{0};
std::atomic<int> g_fault_seen23{0};""",
    "fake runtime right eye fault globals")
edit(T,
    """    ++g_creates;
    g_create_sizes.push_back({info->width, info->height});""",
    """    ++g_creates;
    g_created_outputs23.push_back(*swapchain);
    g_create_sizes.push_back({info->width, info->height});""",
    "remember output handles")
edit(T,
    """XrResult XRAPI_PTR Release(XrSwapchain swapchain, const XrSwapchainImageReleaseInfo*) {
    std::scoped_lock lock(g_xr_mutex);
    auto& images = g_images[swapchain];""",
    """XrResult XRAPI_PTR Release(XrSwapchain swapchain, const XrSwapchainImageReleaseInfo*) {
    std::scoped_lock lock(g_xr_mutex);
    if (g_fault_count23.load() != 0 &&
        reinterpret_cast<std::uintptr_t>(swapchain) == g_fault_right23.load()) {
        g_fault_count23.store(0);
        ++g_fault_seen23;
        return XR_ERROR_RUNTIME_FAILURE;
    }
    auto& images = g_images[swapchain];""",
    "inject one right output release failure")
edit(T,
    "void TestJitWaitsForNoGameFrame() {",
    """void TestJitRightEyeReleaseFailure23() {
    FrameGenPresenter presenter;
    GpuLog gpu;
    Runtime runtime;
    runtime.paced = true;
    std::unique_ptr<App> owned;
    App* app = nullptr;
    std::size_t created_before = 0;
    {
        std::scoped_lock lock(g_xr_mutex);
        created_before = g_created_outputs23.size();
    }
    StartJit(presenter, gpu, FrameGenSynthesisMode::kInterpolate,
             FrameGenMultiplier::kDynamic, app, runtime, owned);
    for (int i = 0; i < 15; ++i) app->Frame();
    XrSwapchain left = XR_NULL_HANDLE, right = XR_NULL_HANDLE;
    {
        std::scoped_lock lock(g_xr_mutex);
        if (g_created_outputs23.size() >= created_before + 2) {
            right = g_created_outputs23.back();
            left = g_created_outputs23[g_created_outputs23.size() - 2];
        }
    }
    Check(left != XR_NULL_HANDLE && right != XR_NULL_HANDLE,
          "right eye fault: two output swapchains initialized");
    g_fault_seen23.store(0);
    g_fault_right23.store(reinterpret_cast<std::uintptr_t>(right));
    g_fault_count23.store(1);
    const auto submits_before = runtime.Submissions();
    for (int i = 0; i < 30; ++i) app->Frame();
    const int faults = g_fault_seen23.load();
    g_fault_count23.store(0);
    g_fault_right23.store(0);
    const auto submits_after = runtime.Submissions();
    presenter.Stop();
    const auto submitted = runtime.Snapshot();
    std::size_t checked_pairs = 0;
    for (const auto& frame : submitted) {
        if (frame.swapchains.size() != 2 || frame.releases.size() != 2 ||
            frame.swapchains[0] != left || frame.swapchains[1] != right) continue;
        ++checked_pairs;
        Check(frame.releases[0] == frame.releases[1],
              "right eye fault: never submitted an unequal left/right output release generation");
    }
    Check(checked_pairs > 0, "right eye fault: saw generated stereo submissions");
    Check(faults == 1, "right eye fault: exactly one injected failed release reached presenter");
    Check(submits_after > submits_before,
          "right eye fault: compositor recovered and submitted following frames");
    Check(!runtime.ordering_violation && !g_release_violation,
          "right eye fault: runtime and swapchain call ordering retained");
}

void TestJitWaitsForNoGameFrame() {""",
    "right eye fault recovery regression")
edit(T,
    "    RUN(TestJitWaitsForNoGameFrame);",
    """    RUN(TestJitWaitsForNoGameFrame);
    RUN(TestJitRightEyeReleaseFailure23);""",
    "right eye regression test registered")

for path, value in sources.items():
    path.write_text(value, encoding="utf-8")
print("PASS VectorXR stereo route telemetry and paired release checks and fake-runtime test (5 files)")

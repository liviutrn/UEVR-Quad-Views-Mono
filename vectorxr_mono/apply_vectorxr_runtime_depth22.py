#!/usr/bin/env python3
"""VectorXR #22: runtime-depth A/B, kind-7 trace corrections and #18 details.

Applied LAST after the pinned upstream v0.20.1 and #21 patch chain.
Every source anchor is exact and fail-closed; no files are written on mismatch.
VECTORXR_FRAMEGEN_RUNTIME_DEPTH defaults to 1 (unchanged #36 behaviour).
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
H = root / "layer/include/depthxr/framegen_presenter.h"
P = root / "layer/src/framegen/framegen_presenter.cpp"
T = root / "layer/tests/framegen_presenter_tests.cpp"
files = {p: p.read_text(encoding="utf-8") for p in (H, P, T)}

def change(path, old, new, label):
    current = files[path]
    count = current.count(old)
    if count != 1:
        raise SystemExit(f"VectorXR #22 anchor {label}: {count}, expected 1; NOTHING written")
    files[path] = current.replace(old, new)

# Session-scoped switch. ReadResearchSwitch searches the research file and
# environment in the same way as the #21 switches. No global or live
# reconfiguration and no change to the depth input the backend consumes.
change(H,
       "    std::uint32_t research_cadence_lock_{0};",
       """    std::uint32_t research_cadence_lock_{0};
    bool runtime_depth_{true}; // #22: only outbound OpenXR depth, NEVER the FG input""",
       "depth setting")
change(P,
       '    const auto lock21 = ReadResearchSwitch("VECTORXR_CADENCE_LOCK21");',
       '''    runtime_depth_ = ReadResearchSwitch("VECTORXR_FRAMEGEN_RUNTIME_DEPTH") != "0";
    const auto lock21 = ReadResearchSwitch("VECTORXR_CADENCE_LOCK21");''',
       "depth setting read")
change(P,
       '                      ", gpuProbe=" + (research21_ ? "on" : "off") + ".");',
       '''                      ", gpuProbe=" + (research21_ ? "on" : "off") +
                      ", runtimeDepth=" + (runtime_depth_ ? "1" : "0") + ".");''',
       "startup log")

# BuildFrame was a static helper in #36. Runtime depth is session-scoped
# instance state, so make this helper an instance method. Both existing call
# sites are in the member CompositorLoop; there are no static callers.
# This corrects CI #41 MSVC C2597/C3867/C2568 without changing the policy.
change(H,
       "    static XrFrameEndInfo BuildFrame(",
       "    XrFrameEndInfo BuildFrame(",
       "BuildFrame session state access")

# The original FrameCopy, with captured per-eye depth, is still stored and
# consumed by optical flow/FG. BuildFrame operates on an ephemeral *copy* of
# that stored data. Clearing has_depth here covers exact copies, JIT as-is
# fallback, and non-primary projection layers without touching GPU depth.
change(P,
       """    pointers.clear();
    for (std::size_t i = 0; i < copy.layers.size(); ++i) {""",
       """    generated_depth = generated_depth && runtime_depth_; // #22: output only
    pointers.clear();
    for (std::size_t i = 0; i < copy.layers.size(); ++i) {""",
       "generated depth disabled")
change(P,
       """            for (std::size_t view = 0; view < layer.views.size(); ++view) {
                layer.views[view].next = layer.has_depth[view] ? &layer.depth[view] : nullptr;""",
       """            // Runtime depth OFF is applied only to this output copy,
            // never to the original depth input kept by Frame Generation.
            if (!runtime_depth_) {
                std::fill(layer.has_depth.begin(), layer.has_depth.end(), std::uint8_t{0});
            }
            for (std::size_t view = 0; view < layer.views.size(); ++view) {
                layer.views[view].next = layer.has_depth[view] ? &layer.depth[view] : nullptr;""",
       "all projection views")
change(P,
       "BuildFrame(content, use_generated ? &views : nullptr, space, flags, views_exact, pointers);",
       "BuildFrame(content, use_generated ? &views : nullptr, space, flags, views_exact && runtime_depth_, pointers);",
       "legacy exact copy")

# A final output-only guard also covers inline, priming, standby and fallback
# xrEndFrame paths, which bypass BuildFrame and would otherwise leak app depth.
# Unknown non-depth chains remain untouched unless a depth node appears later
# in a chain; in that exceptional opt-in case, omit the rest of the view chain
# rather than submit a dangling depth pointer. The source frame stays intact.
change(P,
       """    XrResult result = XR_SUCCESS;
    if (trace_.Enabled() && info) {
        // What the runtime is given: its first projection layer's views.""",
       """    XrResult result = XR_SUCCESS;
    // #22: only sanitize the runtime-facing submission. NEVER mutate app
    // projection views or their source depth chain used by the FG backend.
    XrFrameEndInfo depthless_end22{};
    std::vector<const XrCompositionLayerBaseHeader*> depthless_headers22;
    std::deque<XrCompositionLayerProjection> depthless_projections22;
    std::deque<std::vector<XrCompositionLayerProjectionView>> depthless_views22;
    if (!runtime_depth_ && info && info->layers && info->layerCount) {
        depthless_end22 = *info;
        depthless_headers22.assign(info->layers, info->layers + info->layerCount);
        for (std::uint32_t i = 0; i < info->layerCount; ++i) {
            const auto* header = info->layers[i];
            if (!header || header->type != XR_TYPE_COMPOSITION_LAYER_PROJECTION) continue;
            const auto* projection = reinterpret_cast<const XrCompositionLayerProjection*>(header);
            if (!projection->views || !projection->viewCount) continue;
            depthless_projections22.push_back(*projection);
            depthless_views22.emplace_back(projection->views, projection->views + projection->viewCount);
            for (auto& view : depthless_views22.back()) {
                const auto* first = static_cast<const XrBaseInStructure*>(view.next);
                const auto* after = first;
                while (after && after->type == XR_TYPE_COMPOSITION_LAYER_DEPTH_INFO_KHR)
                    after = after->next;
                bool depth_later = false;
                for (auto* node = after; node; node = node->next) {
                    if (node->type == XR_TYPE_COMPOSITION_LAYER_DEPTH_INFO_KHR) {
                        depth_later = true;
                        break;
                    }
                }
                if (depth_later) view.next = nullptr; // cannot clone opaque chain links
                else if (after != first) view.next = after;
            }
            depthless_projections22.back().views = depthless_views22.back().data();
            depthless_headers22[i] = reinterpret_cast<const XrCompositionLayerBaseHeader*>(
                &depthless_projections22.back());
        }
        depthless_end22.layers = depthless_headers22.data();
        info = &depthless_end22;
    }
    if (trace_.Enabled() && info) {
        // What the runtime is given: its first projection layer's views.""",
       "final submission guard")

# Trace kind 7: paths 6/8 carry the fraction of the *previously shown* frame.
# They are still marked fraction-invalid by aux bit 13: do not reclassify as
# a new synthesis. An exact extrapolation is fraction 0, not one million.
change(P,
       """                const std::int64_t fraction_ppm = synthesized_now
                    ? static_cast<std::int64_t>(std::llround(
                        static_cast<double>(write.exact ? 1.0f : choice.fraction) * 1000000.0))
                    : -1; // Not a new GPU synthesis: no valid fraction.""",
       """                const std::int64_t fraction_ppm = synthesized_now
                    ? static_cast<std::int64_t>(std::llround(
                        static_cast<double>(write.exact
                            ? (choice.mode == FrameGenSynthesisMode::kExtrapolate ? 0.0f : 1.0f)
                            : choice.fraction) * 1000000.0))
                    : ((path == 6 || path == 8) && jit_shown_
                        ? static_cast<std::int64_t>(std::llround(
                            static_cast<double>(std::get<2>(*jit_shown_)) * 1000000.0))
                        : -1); // 6/8 carry prior shown fraction, not a new synthesis.""",
       "kind7 fractions")

# #18 diagnostic only: augment EVERY existing off-timeline record with
# classification derived from the submitted swapchain and session-state
# snapshots. The status/capture fields are end-of-window snapshots, not
# per-refresh measurements. No policy, threshold or pacing changes.
change(T,
       "    const std::vector<XrTime>& game_times, bool detailed) {",
       """    const std::vector<XrTime>& game_times, bool detailed,
    const FrameGenStatus* warmup_status = nullptr,
    const GpuLog* warmup_gpu = nullptr, int warmup_cap = 0) {""",
       "diagnosis signature")
change(T,
       "    struct Point { std::size_t index; XrTime time; double residual; };",
       "    struct Point { std::size_t index; XrTime time; double residual; bool app_copy; };",
       "diagnosis point path")
change(T,
       "            points.push_back({i, t, residual});",
       "            points.push_back({i, t, residual, IsAppImage(runtime.submitted_swapchains[i])});",
       "diagnosis path observation")
change(T,
       r'                  << " nearestRealPhasePeriods=" << phase << "\n";',
       r'''                  << " nearestRealPhasePeriods=" << phase;
        if (warmup_status && warmup_gpu) {
            std::cerr << " path=" << (point.app_copy ? "real-copy" : "generated-or-fallback")
                      << " leadSnapshot=" << warmup_status->lead_slots
                      << " cap=" << warmup_cap
                      << " ringCeilingSnapshot=" << warmup_status->lead_ceiling
                      << " ringCeilingOn=" << (warmup_status->lead_ceiling_on ? 1 : 0)
                      << " captureSnapshot=" << warmup_gpu->depth_captures.load()
                      << " analyzedSnapshot=" << warmup_gpu->analyzes.load();
        }
        std::cerr << "\n";''',
       "per-miss warmup diagnostics")
change(T,
       """        const auto diag = DiagnoseSlowTimeline(runtime, first, 8,
                                               app->eye_speed, real_times, true);
        const auto st = presenter.Status();""",
       """        const auto st = presenter.Status();
        const auto diag = DiagnoseSlowTimeline(runtime, first, 8,
                                               app->eye_speed, real_times, true,
                                               &st, &gpu, six ? 6 : 4);""",
       "warmup snapshot")

# The fake runtime checks *all* projection layers / views, not just view 0.
# Observe at submission before the caller can release its stack-backed chains.
change(T,
       "    std::vector<bool> submitted_depth;",
       """    std::vector<bool> submitted_depth;
    std::vector<bool> submitted_any_view_depth22; // all projection layers""",
       "fake runtime depth recorder")
change(T,
       "            submitted_depth.push_back(depth);",
       """            submitted_depth.push_back(depth);
            bool any_depth22 = false;
            for (std::uint32_t l = 0; l < info->layerCount; ++l) {
                if (!info->layers[l] || info->layers[l]->type != XR_TYPE_COMPOSITION_LAYER_PROJECTION)
                    continue;
                const auto* projection =
                    reinterpret_cast<const XrCompositionLayerProjection*>(info->layers[l]);
                for (std::uint32_t v = 0; v < projection->viewCount; ++v) {
                    for (auto* node = static_cast<const XrBaseInStructure*>(projection->views[v].next);
                         node; node = node->next)
                        if (node->type == XR_TYPE_COMPOSITION_LAYER_DEPTH_INFO_KHR) any_depth22 = true;
                }
            }
            submitted_any_view_depth22.push_back(any_depth22);""",
       "all-view observer")

# Both compositors are exercised with actual fake input depth; prove the FG
# backend still captures that depth while the runtime gets none.
change(T,
       "void TestJitBuild18WarmupFixture() {",
       """void TestRuntimeDepth22Off() {
    for (const bool jit : {false, true}) {
        g_jit = jit;
        _putenv_s("VECTORXR_FRAMEGEN_RUNTIME_DEPTH", "0");
        FrameGenPresenter presenter;
        GpuLog gpu;
        gpu.depth = true;
        Runtime runtime;
        runtime.paced = jit;
        std::unique_ptr<App> owned;
        App* app = nullptr;
        if (jit) {
            StartJit(presenter, gpu, FrameGenSynthesisMode::kInterpolate,
                     FrameGenMultiplier::k2, app, runtime, owned, nullptr);
        } else {
            StartPresenter(presenter, gpu, FrameGenSynthesisMode::kInterpolate);
            presenter.TrackSwapchain(kDepthChain, 20, 1,
                XR_SWAPCHAIN_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | XR_SWAPCHAIN_USAGE_SAMPLED_BIT);
            owned = std::make_unique<App>(presenter, runtime);
            owned->depth.subImage.swapchain = kDepthChain;
            owned->depth.subImage.imageRect = {{0, 0}, {1600, 1600}};
            owned->depth.nearZ = 0.1f;
            owned->depth.farZ = 1000.0f;
            app = owned.get();
        }
        _putenv_s("VECTORXR_FRAMEGEN_RUNTIME_DEPTH", "");
        if (jit) RunPipelined(*app, 1400ms, 18ms, 61ms);
        else for (int i = 0; i < 18; ++i) app->Frame();
        presenter.Stop();
        Check(gpu.depth_captures.load() > 0,
              "runtimeDepth=0: FG depth capture remains enabled");
        Check(gpu.executes.load() > 0,
              "runtimeDepth=0: FG still executes");
        std::scoped_lock lock(g_xr_mutex);
        bool copied = false, generated = false, any_runtime_depth = false;
        for (std::size_t i = 0; i < runtime.submitted_any_view_depth22.size(); ++i) {
            if (runtime.submitted_swapchains[i].empty()) continue;
            copied |= IsAppImage(runtime.submitted_swapchains[i]);
            generated |= !IsAppImage(runtime.submitted_swapchains[i]);
            any_runtime_depth |= runtime.submitted_any_view_depth22[i];
        }
        Check(copied && generated,
              "runtimeDepth=0: inspected both real copies and generated frames");
        Check(!any_runtime_depth,
              "runtimeDepth=0: no submitted projection view has runtime depth");
        Check(!runtime.ordering_violation && !g_release_violation,
              "runtimeDepth=0: valid runtime/GPU call order");
    }
    g_jit = false;
}

void TestJitBuild18WarmupFixture() {""",
       "new runtime depth regression")
change(T,
       "    RUN(TestJitBuild18WarmupFixture);",
       """    RUN(TestJitBuild18WarmupFixture);
    RUN(TestRuntimeDepth22Off);""",
       "register runtime depth regression")

for path, value in files.items():
    path.write_text(value, encoding="utf-8", newline="")
print("VectorXR #22: runtime depth output switch, kind7 fixes, #18 per-miss context, fake-runtime regression")

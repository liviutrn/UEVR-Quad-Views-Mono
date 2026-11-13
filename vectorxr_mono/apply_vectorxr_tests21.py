#!/usr/bin/env python3
"""#21 fake world-time test and exact #18 warmup fixture; no production changes."""
from pathlib import Path
import sys
p=Path(sys.argv[1]).resolve()/"layer/tests/framegen_presenter_tests.cpp"
s=p.read_text(encoding="utf-8")
def change(old,new,label):
    global s
    if s.count(old)!=1:
        raise SystemExit(f"#21 tests anchor {label}: {s.count(old)} != 1; file untouched")
    s=s.replace(old,new)
change("""    double eye_speed{0.0};
    std::mutex periods_mutex;""",
"""    double eye_speed{0.0};
    // #21: fake scene state advances on a wall-clock game-thread tick,
    // independent of the OpenXR display timestamp returned to the app.
    bool use_world_tick{false};
    std::mutex world_tick_mutex;
    std::map<XrTime, XrTime> tick_time_for_predicted;
    std::mutex periods_mutex;""","fake world clock fields")
change("""        for (auto& view : views) {
            view.pose.position.x = static_cast<float>(eye_speed * static_cast<double>(display_time - 1'000'000'000) * 1e-9);
        }""",
"""        XrTime scene_time = display_time;
        if (use_world_tick) {
            std::scoped_lock tick_lock(world_tick_mutex);
            if (const auto it = tick_time_for_predicted.find(display_time);
                it != tick_time_for_predicted.end()) scene_time = it->second;
        }
        for (auto& view : views) {
            view.pose.position.x = static_cast<float>(
                eye_speed * static_cast<double>(scene_time - 1'000'000'000) * 1e-9);
        }""","fake use tick")
change("""            const XrFrameState state = app.Wait();
            SleepPrecise(std::chrono::steady_clock::now() + simulate);""",
"""            const XrFrameState state = app.Wait();
            if (app.use_world_tick) {
                const auto tick = std::chrono::steady_clock::now();
                const auto elapsed_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
                    tick - app.runtime.epoch).count();
                std::scoped_lock tick_lock(app.world_tick_mutex);
                app.tick_time_for_predicted[state.predictedDisplayTime] =
                    app.runtime.display_base + elapsed_ns;
                if (app.tick_time_for_predicted.size() > 256)
                    app.tick_time_for_predicted.erase(app.tick_time_for_predicted.begin());
            }
            SleepPrecise(std::chrono::steady_clock::now() + simulate);""","capture fake tick at game thread")
anchor="    RUN(TestJitDynamicSlackReserve);"
change(anchor,anchor+"""
    RUN(TestJitWorldTickIndependentOfDisplayTime);
    RUN(TestJitBuild18WarmupFixture);""","register research tests")
marker="// Repeats the one-interval clamp of extrapolation predicts between real frames shown at " + chr(96) + "times" + chr(96) + ":"
insert="""// #21: compare the old display-clock-driven fake app with a UE-style
// game-thread world tick. Production pose/timestamp paths stay stock unless
// a separate optional research switch is explicitly enabled.
void TestJitWorldTickIndependentOfDisplayTime() {
    for (const bool content_clock : {false, true}) {
        _putenv_s("VECTORXR_CONTENT_CLOCK21", content_clock ? "1" : "");
        FrameGenPresenter presenter;
        GpuLog gpu;
        Runtime runtime;
        runtime.paced = true;
        std::unique_ptr<App> owned;
        App* app = nullptr;
        StartJit(presenter, gpu, FrameGenSynthesisMode::kInterpolate,
                 FrameGenMultiplier::kDynamic, app, runtime, owned);
        _putenv_s("VECTORXR_CONTENT_CLOCK21", "");
        app->eye_speed = 0.5;
        app->use_world_tick = true;
        app->end_offset_periods = 1;
        RunPipelined(*app, 2500ms, 18ms, 61ms);
        const auto first = runtime.Submissions();
        const auto began = std::chrono::steady_clock::now();
        RunPipelined(*app, 1600ms, 18ms, 61ms);
        const auto log = runtime.Snapshot();
        const double rate = static_cast<double>(log.size() - first) /
            std::max(Seconds(std::chrono::steady_clock::now() - began), 0.001);
        const double timeline = TimelineShare(runtime, first, 8, app->eye_speed);
        std::cerr << "  UE-world-tick fake content_clock=" << content_clock
                  << ", output=" << rate << ", time share=" << timeline
                  << " (diagnostic; no world-clock improvement assertion)" << std::endl;
        Check(rate > 65.0 && log.size() > first + 40,
              "world tick fake: presenter still submits at display rate");
        CheckOrderedTimes(log, "world tick fake");
        presenter.Stop();
        Check(!runtime.ordering_violation && !g_release_violation,
              "world tick fake: runtime/swapchain ordering");
    }
}

// #18 historical fixture, identical warmup (1,000ms) and measurement
// (1,600ms, 18ms simulate/61ms render, 90Hz fake runtime) to #18.
// No invented pass threshold: record and print off-timeline samples, lead,
// cap-ratio context, and failures for adversarial review.
void TestJitBuild18WarmupFixture() {
    for (const bool six : {false, true}) {
        _putenv_s("VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX", six ? "6" : "");
        FrameGenPresenter presenter;
        GpuLog gpu;
        Runtime runtime;
        runtime.paced = true;
        std::unique_ptr<App> owned;
        App* app = nullptr;
        StartJit(presenter, gpu, FrameGenSynthesisMode::kInterpolate,
                 FrameGenMultiplier::kDynamic, app, runtime, owned);
        _putenv_s("VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX", "");
        app->eye_speed = 0.5;
        app->end_offset_periods = 1;
        RunPipelined(*app, 1000ms, 18ms, 61ms);
        const auto first = runtime.Submissions();
        const std::uint32_t lead_start = presenter.Status().lead_slots;
        const auto started = std::chrono::steady_clock::now();
        std::vector<XrTime> real_times;
        const int frames = RunPipelined(*app, 1600ms, 18ms, 61ms,
            [&](int, const XrFrameState& state) {
                real_times.push_back(state.predictedDisplayTime);
            });
        std::sort(real_times.begin(), real_times.end());
        const double elapsed = std::max(Seconds(std::chrono::steady_clock::now() - started), 0.001);
        const auto log = runtime.Snapshot();
        const double timeline = TimelineShare(runtime, first, 8, app->eye_speed);
        const auto diag = DiagnoseSlowTimeline(runtime, first, 8,
                                               app->eye_speed, real_times, true);
        const auto st = presenter.Status();
        std::cerr << "  #18-exact-warmup max" << (six ? 6 : 4)
                  << ": app=" << frames / elapsed
                  << " output=" << static_cast<double>(log.size() - first) / elapsed
                  << " timeline=" << timeline << " off=" << diag.bad << "/" << diag.total
                  << " lead=" << lead_start << "->" << st.lead_slots << std::endl;
        Check(std::abs(diag.share - timeline) < .001, "#18 warmup diagnostic matches");
        CheckOrderedTimes(log, "#18 warmup");
        presenter.Stop();
        Check(!runtime.ordering_violation && !g_release_violation,
              "#18 warmup: ordered");
    }
}
"""
change(marker,insert+"\n"+marker,"fixture insertion")
p.write_text(s,encoding="utf-8",newline="")
print("Applied #21 world-clock fake test and exact #18 1-second warmup fixture")

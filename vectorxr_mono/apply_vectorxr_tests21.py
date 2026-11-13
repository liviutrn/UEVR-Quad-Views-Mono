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
    RUN(TestJitBuild18WarmupFixture);
    RUN(TestResearch21WorldClockSyntheticResidual);""","register research tests")
marker="// Repeats the one-interval clamp of extrapolation predicts between real frames shown at " + chr(96) + "times" + chr(96) + ":"
insert="""
// A reproducible scene-motion model, with variable release phases and exact
// real frames. Tests content-time interpolation directly; NEVER equates
// pose-based TimelineShare with actual synthesized world motion.
void TestResearch21WorldClockSyntheticResidual() {
    constexpr double period=8.333333; // 120 Hz milliseconds
    constexpr double phases[]={0.7,7.2,1.3,6.7,2.8,5.9,3.3,4.6};
    double stock=0.0, corrected=0.0;
    int samples=0;
    double mean_phase=phases[0];
    for (int n=1;n<80;++n) {
        const double prev=(n-1)*5.0*period;
        const double next=n*5.0*period;
        const double p0=phases[(n-1)%8], p1=phases[n%8];
        mean_phase += (p1-mean_phase)/30.0;
        const double w0=prev+p0, w1=next+p1;
        for (int interior=1;interior<5;++interior) {
            const double target=prev+interior*period;
            const double grid_fraction=(target-prev)/(next-prev);
            const double b_fraction=(target+mean_phase-w0)/(w1-w0);
            const double sceneA=w0+grid_fraction*(w1-w0);
            const double sceneB=w0+b_fraction*(w1-w0);
            stock+=std::abs(sceneA-(target+mean_phase));
            corrected+=std::abs(sceneB-(target+mean_phase));
            ++samples;
        }
    }
    std::cerr<<"  world-clock synthetic motion residual stock="<<stock/samples
             <<" ms, B-mean="<<corrected/samples<<" ms"<<std::endl;
    Check(corrected < stock*0.1,"B phase-mean removes synthetic content-clock bias");
}

// #21: compare the old display-clock-driven fake app with a UE-style
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

    // This is the actual fake-GPU synthesis fraction, not the view-pose
    // TimelineShare proxy (which is intentionally unchanged in B).
    std::size_t moving=0;
    double sum_fraction=0.0;
    {
        std::scoped_lock lock(gpu.syntheses_mutex);
        for (const auto& output : gpu.syntheses) {
            if (output.mode == FrameGenSynthesisMode::kInterpolate &&
                output.fraction > 0.001f && output.fraction < 0.999f) {
                ++moving;
                sum_fraction += output.fraction;
            }
        }
    }
    std::cerr << "  GPU fractional synthesis samples: " << moving
              << ", avg=" << (moving ? sum_fraction / moving : 0.0) << std::endl;
    Check(moving > 8, "world-tick fake: genuine synthesized fractions observed");

        std::cerr << "  UE-world-tick fake content_clock=" << content_clock
                  << ", output=" << rate << ", view-pose timeline share=" << timeline
                  << " (pose-only; GPU fractions tested separately)" << std::endl;
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

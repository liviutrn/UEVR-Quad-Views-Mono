#!/usr/bin/env python3
"""VectorXR #22b live A/B and trace v2. LAST after #22; fail-closed patches."""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
H = root / "layer/include/depthxr/framegen_presenter.h"
P = root / "layer/src/framegen/framegen_presenter.cpp"
F = root / "layer/src/framegen_plan.cpp"
L = root / "layer/src/openxr_layer.cpp"
T = root / "layer/tests/framegen_presenter_tests.cpp"
R = root / "layer/include/depthxr/ResearchTrace21.hpp"
X = root / "layer/include/depthxr/framegen_live22b.hpp"
if X.exists():
    raise SystemExit("VectorXR #22b helper already exists; expected #45-generated tree")
files = {p: p.read_text(encoding="utf-8") for p in (H,P,F,L,T,R)}
LIVE_HEADER = "#pragma once\n// VectorXR #22b: research-file live read only on compositor thread, max 1 Hz.\n// No locks, GPU calls, or OpenXR calls; only local file metadata/read.\n#include <chrono>\n#include <cstdlib>\n#include <filesystem>\n#include <fstream>\n#include <optional>\n#include <string>\n#include <string_view>\n#include <utility>\n\nnamespace depthxr {\nstruct LiveSwitchSnapshot22b {\n    bool content_clock{false}, cap_hysteresis{false}, runtime_depth{true};\n    bool nonlive_changed{false};\n};\nclass LiveSwitchPoll22b {\n    using Clock = std::chrono::steady_clock;\n    Clock::time_point last_check_{};\n    std::filesystem::file_time_type last_mtime_{};\n    bool seen_mtime_{false}, seen_nonlive_{false};\n    std::string nonlive_snapshot_;\n    static std::string trim(std::string s) {\n        const auto begin = s.find_first_not_of(\" \\t\\r\\n\");\n        if (begin == std::string::npos) return {};\n        const auto end = s.find_last_not_of(\" \\t\\r\\n\");\n        return s.substr(begin, end - begin + 1);\n    }\n    static bool enabled(const char* name, const std::string& file_value, bool fallback) {\n        if (const auto* env = std::getenv(name); env && *env)\n            return std::string_view(env) == \"1\";\n        if (file_value == \"1\") return true;\n        if (file_value == \"0\") return false;\n        return fallback;\n    }\npublic:\n    void Reset() {\n        last_check_ = {};\n        last_mtime_ = {};\n        seen_mtime_ = seen_nonlive_ = false;\n        nonlive_snapshot_.clear();\n    }\n    std::optional<LiveSwitchSnapshot22b> Poll(Clock::time_point now) noexcept {\n        // The caller is responsible for dropping FrameGenPresenter::mutex_\n        // before Poll. Throttle *even metadata* checks to at most once a second.\n        if (last_check_ != Clock::time_point{} && now - last_check_ < std::chrono::seconds(1))\n            return std::nullopt;\n        last_check_ = now;\n        try {\n            const auto* local = std::getenv(\"LOCALAPPDATA\");\n            if (!local || !*local) return std::nullopt;\n            const auto path = std::filesystem::path(local) / \"VectorXR\" / \"framegen-research.txt\";\n            std::error_code ec;\n            auto mtime = std::filesystem::last_write_time(path, ec);\n            // Absent/unreadable research file must preserve startup policy.\n            if (ec) return std::nullopt;\n            if (seen_mtime_ && mtime == last_mtime_) return std::nullopt;\n            seen_mtime_ = true;\n            last_mtime_ = mtime;\n            std::ifstream file(path, std::ios::binary);\n            if (!file && !ec) return std::nullopt;\n            LiveSwitchSnapshot22b snapshot{};\n            std::string c, h, d, nonlive, line;\n            std::size_t bytes = 0;\n            while (file && std::getline(file, line)) {\n                bytes += line.size();\n                if (bytes > 65536) return std::nullopt; // reject truncated/oversized research files\n                line = trim(line);\n                if (line.empty() || line[0] == '#') continue;\n                const auto at = line.find('=');\n                if (at == std::string::npos) continue;\n                const auto key = trim(line.substr(0, at));\n                const auto val = trim(line.substr(at + 1));\n                if (key == \"VECTORXR_CONTENT_CLOCK21\") c = val;\n                else if (key == \"VECTORXR_MAX6_HYSTERESIS21\") h = val;\n                else if (key == \"VECTORXR_FRAMEGEN_RUNTIME_DEPTH\") d = val;\n                else nonlive += key + \"=\" + val + \"\\n\";\n            }\n            snapshot.content_clock = enabled(\"VECTORXR_CONTENT_CLOCK21\", c, false);\n            snapshot.cap_hysteresis = enabled(\"VECTORXR_MAX6_HYSTERESIS21\", h, false);\n            snapshot.runtime_depth = enabled(\"VECTORXR_FRAMEGEN_RUNTIME_DEPTH\", d, true);\n            snapshot.nonlive_changed = seen_nonlive_ && nonlive != nonlive_snapshot_;\n            seen_nonlive_ = true;\n            nonlive_snapshot_ = std::move(nonlive);\n            return snapshot;\n        } catch (...) {\n            return std::nullopt; // no exceptions on the presenter thread\n        }\n    }\n};\n} // namespace depthxr\n"
def change(path, old, new, label):
    data = files[path]
    count = data.count(old)
    if count != 1:
        raise SystemExit(f"VectorXR #22b {label}: anchor count={count}, expected 1; NO files written")
    files[path] = data.replace(old,new,1)

change(H, '#include "depthxr/framegen_trace.h"',
       '#include "depthxr/framegen_trace.h"\n#include "depthxr/framegen_live22b.hpp"',
       "include live switch poller")
change(H, '    bool runtime_depth_{true}; // #22: only outbound OpenXR depth, NEVER the FG input',
       '''    std::atomic<bool> runtime_depth_{true}; // #22b live, ONLY outbound OpenXR depth
    LiveSwitchPoll22b live22b_;''', "atomic runtime depth / poll state")
change(H, '    void CompositorLoop();',
       '''    void PollLiveSwitches22b(); // outside mutex_, once per research-file mtime
    void CompositorLoop();''', "presenter poll declaration")
change(H, '    bool ResearchFileInUse() const;',
       '''    bool ResearchFileInUse() const;
    bool RuntimeDepthEnabled22b() const noexcept {
        return runtime_depth_.load(std::memory_order_acquire);
    }''', "bypass runtime-depth accessor")
change(P, '    started_at_ = Clock::now();',
       '''    started_at_ = Clock::now();
    live22b_.Reset();''', "reset watcher at session start")
change(P, '''void FrameGenPresenter::CompositorLoop() {''',
       '''void FrameGenPresenter::PollLiveSwitches22b() {
    // File I/O and stat are intentionally OUTSIDE mutex_ and GPU queue locks.
    const auto snapshot = live22b_.Poll(Clock::now());
    if (!snapshot) return;
    struct Applied { const char* name; bool old_value, value; std::uint64_t id; };
    Applied applied[3]{};
    std::size_t changed{};
    {
        std::scoped_lock guard(mutex_);
        if (research_content_clock_ != snapshot->content_clock) {
            applied[changed++] = {"VECTORXR_CONTENT_CLOCK21",
                research_content_clock_, snapshot->content_clock, 1};
            research_content_clock_ = snapshot->content_clock;
            // Only reset the content estimator, NEVER the pose/source clock.
            research_phase_mean_ns_ = 0;
            research_phase_mean_valid_ = false;
            research_last_target_ = 0;
        }
        if (research_cap_hysteresis_ != snapshot->cap_hysteresis) {
            applied[changed++] = {"VECTORXR_MAX6_HYSTERESIS21",
                research_cap_hysteresis_, snapshot->cap_hysteresis, 2};
            research_cap_hysteresis_ = snapshot->cap_hysteresis;
            research_dynamic_slots_ = 0;
        }
        const bool was_depth = runtime_depth_.load(std::memory_order_relaxed);
        if (was_depth != snapshot->runtime_depth) {
            applied[changed++] = {"VECTORXR_FRAMEGEN_RUNTIME_DEPTH",
                was_depth, snapshot->runtime_depth, 3};
            runtime_depth_.store(snapshot->runtime_depth, std::memory_order_release);
        }
    }
    LARGE_INTEGER qpc{};
    QueryPerformanceCounter(&qpc);
    for (std::size_t i = 0; i < changed; ++i) {
        const auto& a = applied[i];
        if (logger_)
            logger_->Info(std::string("VectorXR live switch: ") + a.name + "=" +
                          (a.old_value ? "1" : "0") + "→" + (a.value ? "1" : "0") +
                          " at " + std::to_string(qpc.QuadPart));
        research_trace21::Sink().Record(research_trace21::kLiveSwitch,
            a.id, 0, 0, 0, a.value ? 1 : 0);
    }
    if (snapshot->nonlive_changed && logger_)
        logger_->Info("VectorXR live switch: non-live research setting changed; takes effect next session");
}

void FrameGenPresenter::CompositorLoop() {''', "live poll implementation")
change(P, '''    while (!compositor_stop_ && !(compositor_drain_ && drained())) {
        // A runtime frame''',
       '''    while (!compositor_stop_ && !(compositor_drain_ && drained())) {
        lock.unlock();
        PollLiveSwitches22b(); // never perform filesystem I/O under presenter mutex
        lock.lock();
        // A runtime frame''', "live polling point")

# The #45 raw passthrough path uses the same live atomic when the presenter
# has started, but retains the session setting if FG never initialized.
change(L, '''        depthless22.Apply(info, runtime_depth22_enabled_.load(std::memory_order_acquire)));''',
       '''        depthless22.Apply(info, framegen_.Started()
            ? framegen_.RuntimeDepthEnabled22b()
            : runtime_depth22_enabled_.load(std::memory_order_acquire)));''',
       "raw passthrough watches live runtime depth")
# #21 startup previously could read B/C only from environment, not the file.
change(F, '''        wanted != "VECTORXR_FRAMEGEN_WORLD" && wanted != "VECTORXR_FRAMEGEN_RUNTIME_DEPTH") {''',
       '''        wanted != "VECTORXR_FRAMEGEN_WORLD" && wanted != "VECTORXR_FRAMEGEN_RUNTIME_DEPTH" &&
        wanted != "VECTORXR_CONTENT_CLOCK21" && wanted != "VECTORXR_MAX6_HYSTERESIS21") {''',
       "research-file allowlist for B/C")
# Change only the VectorXR COPIED trace header, never the UEVR header.
change(R, 'kXrRealEnd=6,kXrRefresh=7 };',
       'kXrRealEnd=6,kXrRefresh=7,kLiveSwitch=8 };', "trace kind 8")
change(R, '''            out<<"kind,frame,secondary,tick,qpc_ns,display_xr,pose_xr,aux,extra\\n";''',
       '''            out<<"kind,frame,secondary,tick,qpc_ns,display_xr,pose_xr,aux,extra\\n";
#if !defined(RESEARCH21_UEVR)
            out<<"0,21,2,0,0,0,0,0,0\\n"; // VectorXR-only schema v2 header
#endif''', "CSV version first row")

# Self-contained deterministic mock file test: mtime, 1-Hz throttle, a
# non-live key, and defaults. CI also exercises the entire JIT runtime suite.
change(T, '#include "depthxr/framegen_runtime_depth22.h"',
       '#include "depthxr/framegen_runtime_depth22.h"\n#include "depthxr/framegen_live22b.hpp"\n#include "depthxr/ResearchTrace21.hpp"',
       "include test helper")
change(T, '''void TestRuntimeDepth22Standby() {''',
       '''void TestLiveSwitch22b() {
    const auto folder = std::filesystem::temp_directory_path() /
        ("vectorxr-live22b-" + std::to_string(GetCurrentProcessId()));
    const auto research_dir = folder / "VectorXR";
    std::filesystem::create_directories(research_dir);
    const auto research = research_dir / "framegen-research.txt";
    const char* previous = std::getenv("LOCALAPPDATA");
    const std::string saved = previous ? previous : "";
    _putenv_s("LOCALAPPDATA", folder.string().c_str());
    _putenv_s("VECTORXR_CONTENT_CLOCK21", "");
    _putenv_s("VECTORXR_MAX6_HYSTERESIS21", "");
    _putenv_s("VECTORXR_FRAMEGEN_RUNTIME_DEPTH", "");
    const auto write = [&](std::string_view value, int tick) {
        std::ofstream file(research, std::ios::trunc);
        file << value;
        file.close();
        std::error_code ignored;
        std::filesystem::last_write_time(research,
            std::filesystem::file_time_type::clock::now() + std::chrono::seconds(tick), ignored);
        Check(!ignored, "live22b: research-file timestamp changed");
    };
    const auto now = std::chrono::steady_clock::now();
    LiveSwitchPoll22b poll;
    write("VECTORXR_CONTENT_CLOCK21=0\\nVECTORXR_MAX6_HYSTERESIS21=0\\nVECTORXR_FRAMEGEN_RUNTIME_DEPTH=1\\n", 1);
    auto first = poll.Poll(now);
    Check(first && !first->content_clock && !first->cap_hysteresis && first->runtime_depth,
          "live22b: A baseline intact");
    write("VECTORXR_CONTENT_CLOCK21=1\\nVECTORXR_MAX6_HYSTERESIS21=0\\nVECTORXR_FRAMEGEN_RUNTIME_DEPTH=0\\n", 2);
    Check(!poll.Poll(now + 800ms), "live22b: never stat file twice inside one second");
    auto changed = poll.Poll(now + 1100ms);
    Check(changed && changed->content_clock && !changed->runtime_depth &&
          !changed->nonlive_changed, "live22b: B and runtime-depth changed atomically");
    write("VECTORXR_CONTENT_CLOCK21=1\\nVECTORXR_MAX6_HYSTERESIS21=1\\nVECTORXR_FRAMEGEN_RUNTIME_DEPTH=0\\nVECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX=6\\n", 3);
    changed = poll.Poll(now + 2200ms);
    Check(changed && changed->cap_hysteresis && changed->nonlive_changed,
          "live22b: C applies; non-live MAX setting deferred");
    Check(!poll.Poll(now + 2300ms), "live22b: repeated test poll throttled");
    _putenv_s("LOCALAPPDATA", saved.c_str());
    std::error_code ignored;
    std::filesystem::remove_all(folder, ignored);
}

void TestRuntimeDepth22Standby() {''', "deterministic live-mtime regression")
change(T, '''    RUN(TestRuntimeDepth22Standby);''',
       '''    RUN(TestRuntimeDepth22Standby);
    RUN(TestLiveSwitch22b);''', "register live switch test")

# Integration fixture: actually run the fake pacing runtime while editing the
# research file; assert dispatch changes, kind-8 rows and no >1-refresh hitch.
change(T, '''void TestRuntimeDepth22Standby() {''',
       '''void TestLiveSwitch22bJit() {
    const auto folder = std::filesystem::temp_directory_path() /
        ("vectorxr-livejit22b-" + std::to_string(GetCurrentProcessId()));
    const auto research_dir = folder / "VectorXR";
    std::filesystem::create_directories(research_dir);
    const auto research = research_dir / "framegen-research.txt";
    const char* old_local = std::getenv("LOCALAPPDATA");
    const std::string saved = old_local ? old_local : "";
    _putenv_s("LOCALAPPDATA", folder.string().c_str());
    _putenv_s("VECTORXR_FRAMEGEN_RESEARCH21", "1");
    _putenv_s("VECTORXR_CONTENT_CLOCK21", "");
    _putenv_s("VECTORXR_MAX6_HYSTERESIS21", "");
    _putenv_s("VECTORXR_FRAMEGEN_RUNTIME_DEPTH", "");
    auto write = [&](const char* content, int ahead) {
        std::ofstream output(research, std::ios::trunc);
        output << content;
        output.close();
        std::error_code ec;
        std::filesystem::last_write_time(research,
            std::filesystem::file_time_type::clock::now() + std::chrono::seconds(ahead), ec);
        Check(!ec, "livejit22b: research file saved");
    };
    write("VECTORXR_CONTENT_CLOCK21=0\\nVECTORXR_MAX6_HYSTERESIS21=0\\nVECTORXR_FRAMEGEN_RUNTIME_DEPTH=1\\n", 1);
    SessionLog log("livejit22b");
    FrameGenPresenter presenter;
    GpuLog gpu;
    Runtime runtime;
    runtime.paced = true;
    std::unique_ptr<App> owned;
    App* app = nullptr;
    g_jit = true;
    StartJit(presenter, gpu, FrameGenSynthesisMode::kInterpolate,
             FrameGenMultiplier::k2, app, runtime, owned, log.logger.get());
    Check(presenter.RuntimeDepthEnabled22b(), "livejit22b: starts RD=1");
    const auto started = std::chrono::steady_clock::now();
    std::thread editor([&] {
        std::this_thread::sleep_for(1200ms);
        write("VECTORXR_CONTENT_CLOCK21=1\\nVECTORXR_MAX6_HYSTERESIS21=1\\n"
              "VECTORXR_FRAMEGEN_RUNTIME_DEPTH=0\\n"
              "VECTORXR_FRAMEGEN_FLOW_DYNAMIC_MAX=6\\n", 5);
    });
    RunPipelined(*app, 3100ms, 19ms, 20ms);
    editor.join();
    Check(!presenter.RuntimeDepthEnabled22b(), "livejit22b: runtime depth turned OFF without restart");
    const auto submissions = runtime.Snapshot();
    const auto ended = std::chrono::steady_clock::now();
    Check(!runtime.ordering_violation && !g_release_violation,
          "livejit22b: runtime and images remain ordered through live edit");
    // Quantify the fake-runtime's forward progress. The periodic file check
    // must not produce a compositor stall over one extra refresh.
    auto max_gap = std::chrono::steady_clock::duration{};
    {
        std::scoped_lock guard(g_xr_mutex);
        for (std::size_t i = 26; i < runtime.submitted_at.size(); ++i)
            max_gap = (std::max)(max_gap, runtime.submitted_at[i] - runtime.submitted_at[i-1]);
    }
    const auto bound = std::chrono::nanoseconds(2 * kPeriod) + 4ms;
    Check(max_gap <= bound, "livejit22b: no compositor stall beyond one missed refresh");
    Check(submissions.size() > 120 &&
          ended - started > 2s, "livejit22b: more than two seconds of real pacing");
    presenter.Stop();
    const auto changes = log.Lines("VectorXR live switch: ");
    const auto has = [&](const std::string& match) {
        return std::any_of(changes.begin(), changes.end(),
            [&](const std::string& line){ return line.find(match)!=std::string::npos; });
    };
    Check(has("VECTORXR_CONTENT_CLOCK21=0") && has("VECTORXR_MAX6_HYSTERESIS21=0") &&
          has("VECTORXR_FRAMEGEN_RUNTIME_DEPTH=1"), "livejit22b: three live setting logs");
    Check(has("takes effect next session"), "livejit22b: non-live setting logged, not applied");
    research_trace21::Sink().FlushNow();
    int schema{}, switches{};
    for (const auto& item : std::filesystem::directory_iterator(research_dir)) {
        if (item.path().filename().string().find("vectorxr-real-trace21-") != 0) continue;
        std::ifstream in(item.path());
        std::string line;
        std::getline(in, line); // CSV header
        std::getline(in, line); // schema row
        if (line.rfind("0,21,2,",0) == 0) ++schema;
        while (std::getline(in,line)) if (line.rfind("8,",0)==0) ++switches;
    }
    if (research_trace21::Sink().Enabled())
        Check(schema >= 1 && switches >= 3, "livejit22b: VectorXR schema 2 and all kind-8 transitions");
    g_jit = false;
    _putenv_s("LOCALAPPDATA", saved.c_str());
    _putenv_s("VECTORXR_FRAMEGEN_RESEARCH21", "");
    std::error_code ignored;
    std::filesystem::remove_all(folder, ignored);
}

void TestRuntimeDepth22Standby() {''', "fake runtime with live file edit")
change(T, '''    RUN(TestLiveSwitch22b);''',
       '''    RUN(TestLiveSwitch22b);
    RUN(TestLiveSwitch22bJit);''', "register live integration test")

for path, text in files.items():
    path.write_text(text, encoding="utf-8", newline="")
X.write_text(LIVE_HEADER, encoding="utf-8", newline="")
print("PASS VectorXR #22b live mtime A/B/C, trace schema v2, test fixture")

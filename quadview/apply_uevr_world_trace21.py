#!/usr/bin/env python3
"""UEVR research #21 optional bounded world/pose/submit trace.

Applied last, after M2.3. Never changes projection, poses, render control,
mode settings, frame ordering, or game logic. Fails closed on upstream anchors.
Environment UEVR_WORLD_TRACE21=1 or same in %LOCALAPPDATA%/VectorXR/framegen-research.txt.
"""
import shutil
from pathlib import Path
import sys

backend = Path(sys.argv[1]).resolve()
here = Path(__file__).resolve().parent
V=backend/"src/mods/VR.cpp"
X=backend/"src/mods/vr/runtimes/OpenXR.cpp"
D=backend/"src/mods/vr/ResearchTrace21.hpp"
sources={V: V.read_text(encoding="utf-8"), X: X.read_text(encoding="utf-8")}
def replace(path,needle,replacement,label):
    s=sources[path]
    n=s.count(needle)
    if n!=1:
        raise SystemExit(f"UEVR #21 anchor {label}: {n}, expected 1; no files written")
    sources[path]=s.replace(needle,replacement)

replace(V,
'#include "vr/StockFrameBindingMigration.hpp"',
'#include "vr/StockFrameBindingMigration.hpp"\n#include "vr/ResearchTrace21.hpp"',
"include UEVR trace")
replace(V,
"""VR::~VR() {
    stop_native_openxr_async_wait_worker();""",
"""VR::~VR() {
    // Flush bounded research CSV before unloading UEVR code.
    research_trace21::Sink().Stop();
    stop_native_openxr_async_wait_worker();""",
"stop trace on VR teardown")
replace(V,
"""    const auto now = std::chrono::steady_clock::now();
    const auto previous_engine_tick = m_last_engine_tick.load(std::memory_order_relaxed);
    const bool hitch_diagnostics_enabled = m_enable_hitch_diagnostics->value();""",
"""    const auto now = std::chrono::steady_clock::now();
    if (research_trace21::Sink().Enabled()) {
        auto& trace = research_trace21::Sink();
        trace.Tick();
        trace.Record(research_trace21::kGameTick,
                     static_cast<std::uint64_t>(m_frame_count), 0, 0, 0,
                     static_cast<std::int64_t>(delta * 1000000000.0));
    }
    const auto previous_engine_tick = m_last_engine_tick.load(std::memory_order_relaxed);
    const bool hitch_diagnostics_enabled = m_enable_hitch_diagnostics->value();""",
"game tick")
replace(X,
'#include "../SteamFrameBindings.hpp"',
'#include "../SteamFrameBindings.hpp"\n#include "../ResearchTrace21.hpp"',
"include OpenXR trace")
replace(X,
"""void OpenXR::on_pre_render_game_thread(uint32_t frame_count) {
    if (VR::get()->mono_frame_gate_required()) {""",
"""void OpenXR::on_pre_render_game_thread(uint32_t frame_count) {
    research_trace21::Sink().Record(research_trace21::kRender, frame_count,
                                     this->internal_render_frame_count, 0);
    if (VR::get()->mono_frame_gate_required()) {""",
"render frame")
replace(X,
"""    const auto display_time = pipeline_state.frame_state.predictedDisplayTime + (XrDuration)(pipeline_state.frame_state.predictedDisplayPeriod * this->prediction_scale);

    XrViewLocateInfo view_locate_info""",
"""    const auto display_time = pipeline_state.frame_state.predictedDisplayTime + (XrDuration)(pipeline_state.frame_state.predictedDisplayPeriod * this->prediction_scale);
    research_trace21::Sink().Record(research_trace21::kPose, frame_count,
                                    this->internal_render_frame_count,
                                    pipeline_state.frame_state.predictedDisplayTime,
                                    display_time,
                                    static_cast<std::int64_t>(pipeline_state.frame_state.predictedDisplayPeriod));

    XrViewLocateInfo view_locate_info""",
"actual LocateViews pose time")
replace(X,
"""    //spdlog::info("[VR] display time diff: {}", pipelined_frame_state.predictedDisplayTime - this->frame_state.predictedDisplayTime);""",
"""    research_trace21::Sink().Record(research_trace21::kSubmit,
                                    submit_state.frame_count,
                                    this->internal_render_frame_count,
                                    frame_end_info.displayTime,
                                    pipelined_frame_state.predictedDisplayTime,
                                    static_cast<std::int64_t>(frame_end_info.layerCount));
    //spdlog::info("[VR] display time diff: {}", pipelined_frame_state.predictedDisplayTime - this->frame_state.predictedDisplayTime);""",
"actual XR submit frame")
for path,s in sources.items():
    path.write_text(s,encoding="utf-8",newline="")
D.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(here/"ResearchTrace21.hpp",D)
print("UEVR #21 research: bounded game-tick / render-frame / pose / XR-submit CSV; default OFF")

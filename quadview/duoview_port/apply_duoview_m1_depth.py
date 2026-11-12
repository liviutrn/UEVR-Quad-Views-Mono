#!/usr/bin/env python3
"""Enable the existing fenced NGX periphery depth capture for DuoView M1."""
from pathlib import Path
import sys


def patch(path, edits):
    source = path.read_text(encoding="utf-8")
    for label, old, new in edits:
        count = source.count(old)
        if count != 1:
            raise RuntimeError(f"M1 depth {label}: expected one anchor, found {count} in {path}")
        source = source.replace(old, new, 1)
    path.write_text(source, encoding="utf-8", newline="\n")


def apply_depth_pool(path):
    patch(path, [
        ("request and capture mode", "struct DepthSnapshot {",
         """// Immutable request ties a snapshot to one mode-6 generation and extent.
struct DuoViewDepthRequest {
    uint64_t generation;
    uint32_t width, height, fovea_width, fovea_height;
    friend bool operator==(const DuoViewDepthRequest&, const DuoViewDepthRequest&) = default;
};

enum class DepthCaptureMode { Off, TriView, DuoView };

struct DepthSnapshot {"""),
        ("snapshot capture identity", "    bool foreign_queue{}; // submitted on a queue other than the compositor's: wait for its fence",
         """    bool foreign_queue{}; // submitted on a queue other than the compositor's: wait for its fence
    std::shared_ptr<const DuoViewDepthRequest> duoview_request;
    ComPtr<ID3D12CommandQueue> duoview_producer_queue;"""),
        ("publish frozen mode-6 extents",
         "    // Rare runtime restart only. Tracked foreign-queue copies must actually",
         """    void set_duoview_expected(uint64_t generation, uint32_t width, uint32_t height,
                               uint32_t fovea_width, uint32_t fovea_height) {
        if (!generation || !width || !height ||
            matches_periphery(fovea_width, fovea_height, width, height)) {
            duoview_expected_.store({}, std::memory_order_release);
            return;
        }
        const DuoViewDepthRequest requested{generation, width, height, fovea_width, fovea_height};
        const auto current = duoview_expected_.load(std::memory_order_acquire);
        if (!current || *current != requested)
            duoview_expected_.store(std::make_shared<const DuoViewDepthRequest>(requested),
                                    std::memory_order_release);
    }
    // Rare runtime restart only. Tracked foreign-queue copies must actually"""),
        ("one mode tag for enable and pool ownership",
         """    void set_enabled(bool on) {
        enabled_.store(on && capture_supported(), std::memory_order_release);""",
         """    void set_enabled(bool on, bool duoview = false) {
        const auto mode = !on || !capture_supported() ? DepthCaptureMode::Off :
            duoview ? DepthCaptureMode::DuoView : DepthCaptureMode::TriView;
        const auto previous = capture_mode_.exchange(mode, std::memory_order_acq_rel);
        if (previous == DepthCaptureMode::DuoView && mode != previous)
            duoview_expected_.store({}, std::memory_order_release);"""),
        ("quiescent restart disabled check",
         """    bool restart_quiescent() const {
        if (enabled_.load(std::memory_order_acquire)) return false;""",
         """    bool restart_quiescent() const {
        if (capture_enabled()) return false;"""),
        ("discard only after disabled",
         """    bool discard_completed_for_new_xr_session() {
        if (enabled_.load(std::memory_order_acquire)) return false;""",
         """    bool discard_completed_for_new_xr_session() {
        if (capture_enabled()) return false;"""),
        ("clear mode-6 request on session reset",
         "        pool_.clear();\n        want_w_.store(0,std::memory_order_release);",
         "        pool_.clear();\n        duoview_expected_.store({}, std::memory_order_release);\n"
         "        want_w_.store(0,std::memory_order_release);"),
        ("install only when capture enabled",
         "        if (!enabled_.load(std::memory_order_acquire) || !queue) return;",
         "        if (!capture_enabled() || !queue) return;"),
        ("legacy selection stays isolated and expose frozen mode-6 lookup",
         """        if (!enabled_.load(std::memory_order_acquire) || !w || !h) { ++missed_; return {}; }
        const auto now = std::chrono::steady_clock::now();""",
         """        if (capture_mode_.load(std::memory_order_acquire) != DepthCaptureMode::TriView ||
            !w || !h) { ++missed_; return {}; }
        return select_recent(w, h, {}, nullptr);
    }

    // Match the immutable mode-6 request and the frozen colour packet's extent.
    // This is an approximate temporal match, just as in TriView.
    std::shared_ptr<const DepthSnapshot> latest_duoview_submitted(
            uint64_t generation, uint32_t width, uint32_t height, ID3D12CommandQueue* consumer_queue) {
        const auto request = duoview_expected_.load(std::memory_order_acquire);
        if (capture_mode_.load(std::memory_order_acquire) != DepthCaptureMode::DuoView ||
            !request || request->generation != generation || request->width != width ||
            request->height != height || !consumer_queue) { ++missed_; return {}; }
        return select_recent(width, height, request, consumer_queue);
    }

private:
    std::shared_ptr<const DepthSnapshot> select_recent(
            uint32_t w, uint32_t h, const std::shared_ptr<const DuoViewDepthRequest>& request,
            ID3D12CommandQueue* consumer_queue) {
        const auto now = std::chrono::steady_clock::now();"""),
        ("reject incompatible pool entries and account for the consumer queue",
         """            if (slot->submitted && slot->valid_evaluation && slot->texture && matches_periphery(slot->out_w, slot->out_h, w, h) &&
                (!slot->foreign_queue || depth_copy_complete(completed, slot->producer_fence_value)) &&""",
         """            if (slot->duoview_request != request) continue;
            const bool ordered = request
                ? completed != UINT64_MAX && slot->producer_fence_value &&
                    (slot->duoview_producer_queue.Get() == consumer_queue ||
                     depth_copy_complete(completed, slot->producer_fence_value))
                : !slot->foreign_queue || depth_copy_complete(completed, slot->producer_fence_value);
            if (slot->submitted && slot->valid_evaluation && slot->texture &&
                matches_periphery(slot->out_w, slot->out_h, w, h) && ordered &&"""),
        ("preserve existing diagnostics API",
         "    // Why the last DLSS evaluation was not captured (shown in the menu and log).",
         "public:\n    // Why the last DLSS evaluation was not captured (shown in the menu and log)."),
        ("display the active mode's extents",
         """        return {evaluations_.load(), matches_.load(), captures_.load(), submits_.load(), used_.load(), missed_.load(), skips_.load(),
                last_out_w_.load(), last_out_h_.load(), last_in_w_.load(), last_in_h_.load(), last_format_.load(), hooks, queue_hook,
                want_w_.load(), want_h_.load(), other_w_.load(), other_h_.load(), last_reason_.load(), last_used_age_us_.load(), slots,""",
         """        const bool duo = capture_mode_.load(std::memory_order_acquire) == DepthCaptureMode::DuoView;
        const auto request = duo ? duoview_expected_.load(std::memory_order_acquire) : nullptr;
        const auto want_w = duo ? (request ? request->width : 0u) : want_w_.load();
        const auto want_h = duo ? (request ? request->height : 0u) : want_h_.load();
        return {evaluations_.load(), matches_.load(), captures_.load(), submits_.load(), used_.load(), missed_.load(), skips_.load(),
                last_out_w_.load(), last_out_h_.load(), last_in_w_.load(), last_in_h_.load(), last_format_.load(), hooks, queue_hook,
                want_w, want_h, other_w_.load(), other_h_.load(), last_reason_.load(), last_used_age_us_.load(), slots,"""),
        ("store a single mode and request identity",
         "    std::atomic<bool> enabled_{false};",
         """    std::atomic<DepthCaptureMode> capture_mode_{DepthCaptureMode::Off};
    std::atomic<std::shared_ptr<const DuoViewDepthRequest>> duoview_expected_{};
    bool capture_enabled() const noexcept {
        return capture_mode_.load(std::memory_order_acquire) != DepthCaptureMode::Off;
    }"""),
        ("freeze the request before evaluating the NGX candidate",
         """        if (!enabled_.load(std::memory_order_acquire) || !cmd || !feature || !p ||
            cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT) return {};
        ++evaluations_;
        const auto want_w = want_w_.load(std::memory_order_relaxed), want_h = want_h_.load(std::memory_order_relaxed);""",
         """        const auto mode = capture_mode_.load(std::memory_order_acquire);
        if (mode == DepthCaptureMode::Off || !cmd || !feature || !p ||
            cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT) return {};
        ++evaluations_;
        const bool duo = mode == DepthCaptureMode::DuoView;
        const auto request = duo ? duoview_expected_.load(std::memory_order_acquire) : nullptr;
        const auto want_w = duo ? (request ? request->width : 0u) : want_w_.load(std::memory_order_relaxed);
        const auto want_h = duo ? (request ? request->height : 0u) : want_h_.load(std::memory_order_relaxed);"""),
        ("exclude ambiguous overlap with the fovea",
         "        if (!matches_periphery(out_w, out_h, want_w, want_h)) {",
         """        if (!matches_periphery(out_w, out_h, want_w, want_h) ||
            (request && matches_periphery(out_w, out_h, request->fovea_width, request->fovea_height))) {"""),
        ("reject a request superseded while inspecting the evaluation",
         "        if (!device_ || dev.Get() != device_.Get()) { reject(OtherDevice); return {}; }",
         """        if (!device_ || dev.Get() != device_.Get()) { reject(OtherDevice); return {}; }
        if (mode != capture_mode_.load(std::memory_order_acquire) ||
            (duo && request != duoview_expected_.load(std::memory_order_acquire))) return {};"""),
        ("scope B36 protected slot to the active capture request",
         "        for (const auto& candidate : pool_) {\n            const uint64_t completed",
         "        for (const auto& candidate : pool_) {\n"
         "            if (candidate->duoview_request != request) continue;\n"
         "            const uint64_t completed"),
        ("bind the recording request to the depth snapshot",
         "        slot->source_reference = depth;",
         """        slot->source_reference = depth;
        slot->duoview_request = request;
        slot->duoview_producer_queue.Reset();"""),
        ("lease the actual submitting queue for mode-6 consumers",
         "            slot->submitted_at = now;slot->pending_list_lease.Reset(); ++submits_;",
         """            if (slot->duoview_request) slot->duoview_producer_queue = queue;
            slot->submitted_at = now;slot->pending_list_lease.Reset(); ++submits_;"""),
    ])


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_duoview_m1_depth.py <backend>")
    mods = Path(sys.argv[1]) / "src/mods"
    apply_depth_pool(mods / "vr/QuadViewNgxDepth.hpp")
    patch(mods / "VR.cpp", [
        ("publish the actual frozen Mono periphery and fovea dimensions",
         "        }, GetTickCount64(), source_frame);\n    if (frame) m_duoview_candidate_key.store(",
         """        }, GetTickCount64(), source_frame);
    if (frame && frame->config.settings.synthetic_stereo) {
        const auto& layout = frame->config.layout;
        uevr::quadview::ngx::PeripheryDepth::self().set_duoview_expected(
            frame->config.key.generation, layout.periphery.width, layout.periphery.height,
            layout.fovea.width, layout.fovea.height);
    } else {
        uevr::quadview::ngx::PeripheryDepth::self().set_duoview_expected(0, 0, 0, 0, 0);
    }
    if (frame) m_duoview_candidate_key.store("""),
    ])
    patch(mods / "vr/D3D12Component.cpp", [
        ("depth hooks while either periphery consumer needs them",
         """    {   // Tri-view B7: periphery depth capture only while ID7 + depth (reproject or show) is on.
        auto& depth=uevr::quadview::ngx::PeripheryDepth::self();
        const bool want=vr->is_quadview_mode_selected() && (vr->quadview_depth_reproject() || vr->quadview_depth_show());
        depth.set_enabled(want);""",
         """    {   // Enable the shared producer for the active periphery-depth consumer.
        auto& depth=uevr::quadview::ngx::PeripheryDepth::self();
        const bool duo_depth = vr->is_duoview_renderer_active() &&
            vr->duoview_state().settings().synthetic_stereo;
        const bool want = duo_depth ||
            (vr->is_quadview_mode_selected() && (vr->quadview_depth_reproject() || vr->quadview_depth_show()));
        depth.set_enabled(want, duo_depth);"""),
        ("depth diagnostics identify the active renderer",
         '            spdlog::info("[TriView][Depth] hooks={}/6',
         '            spdlog::info("[{}][Depth] hooks={}/6'),
        ("depth diagnostic renderer name",
         "                s.hooks, s.queue_hook, s.evaluations, s.matches,",
         '                duo_depth ? "DuoView" : "TriView", s.hooks, s.queue_hook, s.evaluations, s.matches,'),
    ])
    print("DuoView M1: isolated periphery-depth request and fenced producer routing applied")


if __name__ == "__main__":
    main()

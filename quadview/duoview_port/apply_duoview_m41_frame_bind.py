#!/usr/bin/env python3
"""Join M4 depth to the existing DuoView source transaction at the Slate tail.

A deferred tail with both colour roles marks the end of their RHI commands.
Between consecutive such tails on one thread, accept exactly one NGX capture
of each role. An incomplete, split, or ambiguous interval cannot supply fine
depth. Present still validates the original colour packet and the producer
queue/fence before consuming any depth.
"""
import sys
from pathlib import Path

from apply_duoview_b40_pipeline import patch


CAPTURE_INTERVAL = r'''
    // Called on the authenticated source marker before its original command.
    // Earlier RHI commands have recorded their copies, which may still be
    // pending here. The selector independently checks submission and fences.
    void m41_close_capture_interval(uint64_t generation, uint64_t serial, uint32_t thread) {
        std::scoped_lock lock(mutex_);
        const bool consecutive = serial && m41_marker_serial_ && serial == m41_marker_serial_ + 1 &&
            generation == m41_marker_generation_ && thread == m41_marker_thread_;
        m41_marker_generation_ = generation;
        m41_marker_serial_ = serial;
        m41_marker_thread_ = thread;

        const auto coarse = std::exchange(m41_candidates_[0], {});
        const auto fine = std::exchange(m41_candidates_[1], {});
        if (!serial) return;
        if (!consecutive || coarse.count != 1 || fine.count != 1 ||
            coarse.thread != thread || fine.thread != thread) {
            ++m41_interval_rejected_;
            return;
        }

        DepthSnapshot* coarse_slot{};
        DepthSnapshot* fine_slot{};
        for (const auto& slot : pool_) {
            if (slot->sequence == coarse.sequence && slot->m25_pool_role == 1) coarse_slot = slot.get();
            if (slot->sequence == fine.sequence && slot->m25_pool_role == 2) fine_slot = slot.get();
        }
        const auto request = duoview_expected_.load(std::memory_order_acquire);
        if (!request || request->generation != generation || !coarse_slot || !fine_slot ||
            coarse_slot->duoview_request != request || fine_slot->duoview_request != request ||
            !coarse_slot->valid_evaluation || !fine_slot->valid_evaluation) {
            ++m41_interval_rejected_;
            return;
        }
        coarse_slot->m41_packet_serial = serial;
        fine_slot->m41_packet_serial = serial;
        ++m41_interval_bound_;
    }

    std::pair<std::shared_ptr<const DepthSnapshot>, std::shared_ptr<const DepthSnapshot>>
    m41_pair_for_packet(uint64_t generation, uint64_t serial, uint32_t coarse_w, uint32_t coarse_h,
            uint32_t fine_w, uint32_t fine_h, ID3D12CommandQueue* consumer_queue) {
        std::scoped_lock lock(mutex_);
        const auto request = duoview_expected_.load(std::memory_order_acquire);
        std::shared_ptr<const DepthSnapshot> coarse, fine;
        if (serial && consumer_queue && request && request->generation == generation &&
            request->width == coarse_w && request->height == coarse_h &&
            request->fovea_width == fine_w && request->fovea_height == fine_h &&
            capture_mode_.load(std::memory_order_acquire) == DepthCaptureMode::DuoView) {
            const auto now = std::chrono::steady_clock::now();
            for (const auto& slot : pool_) {
                if (slot->m41_packet_serial != serial || slot->duoview_request != request ||
                    !slot->submitted || !slot->valid_evaluation || !slot->texture ||
                    !slot->producer_fence || !slot->producer_fence_value ||
                    now < slot->submitted_at || now - slot->submitted_at >= std::chrono::milliseconds(250)) continue;
                const auto complete = slot->producer_fence->GetCompletedValue();
                if (complete == UINT64_MAX || (slot->duoview_producer_queue.Get() != consumer_queue &&
                    !depth_copy_complete(complete, slot->producer_fence_value))) continue;
                if (slot->m25_pool_role == 1) coarse = slot;
                if (slot->m25_pool_role == 2 && slot->jitter_valid) fine = slot;
            }
        }
        if (coarse && fine) {
            ++m41_exact_;
            return {coarse, fine};
        }
        ++m41_coarse_only_;
        return {coarse, {}};
    }

    struct M41Window { uint64_t bound, rejected, exact, coarse_only; };
    M41Window m41_take_window() {
        return {m41_interval_bound_.exchange(0), m41_interval_rejected_.exchange(0),
            m41_exact_.exchange(0), m41_coarse_only_.exchange(0)};
    }
'''


def backend(mods):
    vr = mods / "vr"
    patch(vr / "DuoViewDelivery.hpp", [
        ("track deferred role attachments",
         """        Source original{};
        Source owner() const { return original; }
        Attachment attach(const Source& source) {""",
         """        Source original{};
        uint8_t deferred_roles{};
        Source owner() const { return original; }
        Attachment attach(const Source& source, bool deferred = false) {"""),
        ("record only the original attachment's route",
         """            slot=source;
            if (!original) original=source;""",
         """            slot=source;
            if (deferred) deferred_roles |= uint8_t(1u << static_cast<unsigned>(source.role));
            if (!original) original=source;"""),
    ])
    patch(vr / "FFakeStereoRenderingHook.cpp", [
        ("depth producer include",
         '#include "DuoViewGeometry.hpp"',
         '''#include "DuoViewGeometry.hpp"
#include "QuadViewNgxDepth.hpp"'''),
        ("identify deferred marker route",
         """const FFakeStereoRenderingHook::QuadViewNativeDelivery::Command& quad_native = {}) {
        std::scoped_lock __{vtable_mutex};""",
         """const FFakeStereoRenderingHook::QuadViewNativeDelivery::Command& quad_native = {},
        bool duo_deferred = false) {
        std::scoped_lock __{vtable_mutex};"""),
        ("deferred Slate route",
         """reinterpret_cast<sdk::FRHICommandBase_New*>(*root), frame_count + compensation, duo_source, quad_source, quad_engine, quad_native);""",
         """reinterpret_cast<sdk::FRHICommandBase_New*>(*root), frame_count + compensation, duo_source, quad_source, quad_engine, quad_native, true);"""),
        ("deferred Slate UE5.8 route",
         "SceneViewExtensionAnalyzer::hook_new_rhi_command(root, frame_count + compensation, duo_source, quad_source, quad_engine, quad_native);",
         "SceneViewExtensionAnalyzer::hook_new_rhi_command(root, frame_count + compensation, duo_source, quad_source, quad_engine, quad_native, true);"),
        ("deferred Slate legacy discovery route",
         "SceneViewExtensionAnalyzer::hook_new_rhi_command((sdk::FRHICommandBase_New*)l->root, frame_count + compensation, duo_source, quad_source, quad_engine, quad_native);",
         "SceneViewExtensionAnalyzer::hook_new_rhi_command((sdk::FRHICommandBase_New*)l->root, frame_count + compensation, duo_source, quad_source, quad_engine, quad_native, true);"),
        ("preserve route for both source roles",
         "? owner->second.attach(duo_source) : Attachment::conflict;",
         "? owner->second.attach(duo_source, duo_deferred) : Attachment::conflict;"),
        ("preserve first source route",
         """            command.attach(duo_source);
            duo_command_sources.emplace""",
         """            command.attach(duo_source, duo_deferred);
            duo_command_sources.emplace"""),
        ("close capture interval before the Slate tail",
         """            qv_emit_rhi(12,"ORIGINAL_ENTER","engine_callback");""",
         """            if (N == correct_execute_index && duo_source) {
                const auto& owner = duo_source.packet;
                const bool owns_both = duo_command.deferred_roles == 3u && owner &&
                    owner->duoview_frame && owner->duoview_frame->config.settings.m4_fovea_grid &&
                    vr->is_duoview_renderer_active() && duo_source.generation == vr->mono_generation();
                uevr::quadview::ngx::PeripheryDepth::self().m41_close_capture_interval(
                    duo_source.generation, owns_both ? owner->serial : 0, GetCurrentThreadId());
            }
            qv_emit_rhi(12,"ORIGINAL_ENTER","engine_callback");"""),
    ])

    patch(vr / "QuadViewNgxDepth.hpp", [
        ("depth snapshot transaction",
         """    uint64_t m24_present_epoch{};
    bool duoview_fovea{};""",
         """    uint64_t m24_present_epoch{};
    uint64_t m41_packet_serial{};
    bool duoview_fovea{};"""),
        ("observe submitted or pending captures in the marker interval",
         "        slot->sequence = ++next_sequence_;",
         """        slot->sequence = ++next_sequence_;
        slot->m41_packet_serial = 0;
        if (duo && m41_marker_serial_) {
            auto& capture = m41_candidates_[m25_role - 1];
            capture.count = (std::min)(2u, capture.count + 1);
            capture.sequence = slot->sequence;
            capture.thread = GetCurrentThreadId();
        }"""),
        ("packet selection",
         """        ++m25_cpu_pairs_;
        return latest;
    }
""",
         """        ++m25_cpu_pairs_;
        return latest;
    }
""" + CAPTURE_INTERVAL),
        ("transaction state",
         "    std::atomic<uint64_t> m24_present_epoch_{1};",
         """    std::atomic<uint64_t> m24_present_epoch_{1};
    struct M41Candidate { uint64_t sequence{}; uint32_t thread{}, count{}; };
    std::array<M41Candidate, 2> m41_candidates_{};
    uint64_t m41_marker_generation_{}, m41_marker_serial_{};
    uint32_t m41_marker_thread_{};
    std::atomic<uint64_t> m41_interval_bound_{}, m41_interval_rejected_{}, m41_exact_{}, m41_coarse_only_{};"""),
    ])

    patch(vr / "D3D12Component.cpp", [
        ("select depth from colour transaction",
         "                                            const auto snapshot=(config.settings.m25_fine_mode==0u && pair.first) ?",
         """                                            const auto m41_pair = config.settings.m4_fovea_grid ?
                                                depths.m41_pair_for_packet(config.key.generation, packet->serial,
                                                    periphery.width, periphery.height, fovea.width, fovea.height, current_queue) :
                                                std::pair<std::shared_ptr<const uevr::quadview::ngx::DepthSnapshot>,
                                                    std::shared_ptr<const uevr::quadview::ngx::DepthSnapshot>>{};
                                            const auto snapshot=m41_pair.first ? m41_pair.first :
                                                (config.settings.m25_fine_mode==0u && pair.first) ?"""),
        ("coarse only on missing fine owner",
         "                                            const auto m25_fine=(config.settings.m2_fovea_depth &&",
         """                                            const auto m25_fine=config.settings.m4_fovea_grid ? m41_pair.second :
                                                (config.settings.m2_fovea_depth &&"""),
        ("log accepted and missing pairs",
         '                                                SPDLOG_INFO("[DuoView][M4] fovea_grid={} frames={} grid={}x{} fine_in={}x{}",',
         """                                                if (config.settings.m4_fovea_grid) {
                                                    const auto m41 = depths.m41_take_window();
                                                    SPDLOG_INFO("[DuoView][M4.1] bound={} rejected={} exact={} coarse_only={}",
                                                        m41.bound, m41.rejected, m41.exact, m41.coarse_only);
                                                }
                                                SPDLOG_INFO("[DuoView][M4] fovea_grid={} frames={} grid={}x{} fine_in={}x{}","""),
    ])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_duoview_m41_frame_bind.py <backend>")
    backend(Path(sys.argv[1]) / "src/mods")
    print("M4.1: DuoView depth paired with the colour transaction at the deferred RHI tail")

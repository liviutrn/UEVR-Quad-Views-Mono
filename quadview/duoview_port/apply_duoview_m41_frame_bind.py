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
    // Retain both recordings even if the producer has yet to submit them.
    // The selector only consumes copies after the producer's Signal is queued.
    void m41_close_capture_interval(uint64_t generation, uint64_t serial, uint32_t thread) {
        std::scoped_lock lock(mutex_);
        const bool consecutive = serial && m41_marker_serial_ && serial == m41_marker_serial_ + 1 &&
            generation == m41_marker_generation_ && thread == m41_marker_thread_;
        m41_marker_generation_ = generation;
        m41_marker_serial_ = serial;
        m41_marker_thread_ = thread;

        const auto coarse = std::exchange(m41_candidates_[0], {});
        const auto fine = std::exchange(m41_candidates_[1], {});
        if (!serial) { m41_packets_ = {}; return; }
        if (!consecutive) m41_packets_ = {};
        if (!consecutive || coarse.count != 1 || fine.count != 1 ||
            coarse.thread != thread || fine.thread != thread) {
            return;
        }

        const auto request = duoview_expected_.load(std::memory_order_acquire);
        if (!request || request->generation != generation || !coarse.depth || !fine.depth ||
            coarse.depth->duoview_request != request || fine.depth->duoview_request != request ||
            !coarse.depth->valid_evaluation || !fine.depth->valid_evaluation) {
            return;
        }
        m41_packets_[serial % m41_packets_.size()] = {serial, coarse.depth, fine.depth};
    }

    struct M41DepthPair {
        uint64_t serial{};
        std::shared_ptr<const DepthSnapshot> coarse, fine;
    };

    M41DepthPair m41_pair_for_packet(uint64_t generation, uint64_t serial,
            uint32_t coarse_w, uint32_t coarse_h, uint32_t fine_w, uint32_t fine_h,
            ID3D12CommandQueue* consumer_queue) {
        std::scoped_lock lock(mutex_);
        const auto request = duoview_expected_.load(std::memory_order_acquire);
        const auto& pair = m41_packets_[serial % m41_packets_.size()];
        if (!serial || pair.serial != serial || !consumer_queue || !request ||
            request->generation != generation || request->width != coarse_w || request->height != coarse_h ||
            request->fovea_width != fine_w || request->fovea_height != fine_h ||
            capture_mode_.load(std::memory_order_acquire) != DepthCaptureMode::DuoView) return {};
        const auto ready = [&request](const auto& slot) {
            return slot && slot->duoview_request == request && slot->submitted &&
                slot->valid_evaluation && slot->texture.Get() && slot->duoview_producer_queue.Get() &&
                slot->producer_fence.Get() && slot->producer_fence_value &&
                slot->producer_fence->GetCompletedValue() != UINT64_MAX;
        };
        if (!ready(pair.coarse) || !ready(pair.fine) || !pair.fine->jitter_valid) return {};
        return pair;
    }

    // A foreign-queue producer has already enqueued this fence Signal.
    // Keep the CPU moving and put the dependency on the consuming GPU queue.
    static bool m41_order_for_composition(const M41DepthPair& pair, ID3D12CommandQueue* queue) {
        for (const auto* slot : {pair.coarse.get(), pair.fine.get()}) {
            const auto completed = slot->producer_fence->GetCompletedValue();
            if (completed == UINT64_MAX) return false;
            if (slot->duoview_producer_queue.Get() != queue &&
                !depth_copy_complete(completed, slot->producer_fence_value) &&
                FAILED(queue->Wait(slot->producer_fence.Get(), slot->producer_fence_value))) return false;
        }
        return true;
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
                    owner->duoview_frame->config.settings.synthetic_stereo &&
                    vr->is_duoview_renderer_active() && duo_source.generation == vr->mono_generation();
                uevr::quadview::ngx::PeripheryDepth::self().m41_close_capture_interval(
                    duo_source.generation, owns_both ? owner->serial : 0, GetCurrentThreadId());
            }
            qv_emit_rhi(12,"ORIGINAL_ENTER","engine_callback");"""),
    ])

    patch(vr / "QuadViewNgxDepth.hpp", [
        ("observe submitted or pending captures in the marker interval",
         "        slot->sequence = ++next_sequence_;",
         """        slot->sequence = ++next_sequence_;
        if (duo && m41_marker_serial_) {
            auto& capture = m41_candidates_[m25_role - 1];
            if (capture.count == 0) {
                capture = {slot, GetCurrentThreadId(), 1};
            } else {
                capture = {nullptr, 0, 2};
            }
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
        ("release the depth leases when leaving DuoView",
         """        if (previous == DepthCaptureMode::DuoView && mode != previous)
            duoview_expected_.store({}, std::memory_order_release);""",
         """        if (previous == DepthCaptureMode::DuoView && mode != previous) {
            std::scoped_lock lock(mutex_);
            duoview_expected_.store({}, std::memory_order_release);
            m41_candidates_ = {};
            m41_packets_ = {};
            m41_marker_serial_ = 0;
        }"""),
        ("transaction state",
         "    std::atomic<uint64_t> m24_present_epoch_{1};",
         """    std::atomic<uint64_t> m24_present_epoch_{1};
    struct M41Candidate { std::shared_ptr<const DepthSnapshot> depth; uint32_t thread{}, count{}; };
    std::array<M41Candidate, 2> m41_candidates_{};
    std::array<M41DepthPair, 2> m41_packets_{};
    uint64_t m41_marker_generation_{}, m41_marker_serial_{};
    uint32_t m41_marker_thread_{};
"""),
    ])

    patch(vr / "D3D12Component.cpp", [
        ("select the required pair before acquiring an XR image",
         """                        if (!packet_pair_valid) {
                            SPDLOG_WARNING_EVERY_N_SEC(2,
                                "[DuoView][Pair] Waiting""",
         """                        auto& depths = uevr::quadview::ngx::PeripheryDepth::self();
                        const bool require_fine = packet_frame && packet_frame->config.settings.synthetic_stereo &&
                            packet_frame->config.settings.m4_fovea_grid;
                        const auto queue = g_framework->get_d3d12_hook()->get_command_queue();
                        const auto fine_pair = packet_pair_valid && require_fine
                            ? depths.m41_pair_for_packet(packet_frame->config.key.generation, packet->serial,
                                packet_frame->config.layout.periphery.width, packet_frame->config.layout.periphery.height,
                                packet_frame->config.layout.fovea.width, packet_frame->config.layout.fovea.height, queue)
                            : uevr::quadview::ngx::PeripheryDepth::M41DepthPair{};
                        if (!packet_pair_valid) {
                            SPDLOG_WARNING_EVERY_N_SEC(2,
                                "[DuoView][Pair] Waiting"""),
        ("skip XR image acquisition on missing depth",
         """                            vr->set_mono_status("Waiting for a complete Native Stereo Fix DuoView source pair");
                        } else {""",
         """                            vr->set_mono_status("Waiting for a complete Native Stereo Fix DuoView source pair");
                        } else if (require_fine && !fine_pair.fine) {
                            SPDLOG_WARNING_EVERY_N_SEC(2,
                                "[DuoView][M4] Waiting for matched full-resolution depth, packet={}", packet->serial);
                            vr->set_mono_status("Waiting for matching full-resolution fovea depth");
                        } else {"""),
        ("pass retained pair and its consuming queue",
         """                                [this, packet, packet_frame, source=m_game_tex.texture,""",
         """                                [this, packet, packet_frame, require_fine, fine_pair, queue, source=m_game_tex.texture,"""),
        ("use the exact pair in M4",
         """                                            const auto snapshot=(config.settings.m25_fine_mode==0u && pair.first) ?""",
         """                                            const auto snapshot=require_fine ? fine_pair.coarse :
                                                (config.settings.m25_fine_mode==0u && pair.first) ?"""),
        ("use the exact fine image",
         """                                            const auto m25_fine=(config.settings.m2_fovea_depth &&""",
         """                                            const auto m25_fine=require_fine ? fine_pair.fine :
                                                (config.settings.m2_fovea_depth &&"""),
        ("order all depth reads behind their GPU copies",
         """                                    recorded = compositor.record_native(device, commands.cmd_list.Get(),""",
         """                                    if (require_fine) {
                                        if (!stereo_geometry || !stereo_depth || !fine_depth ||
                                            g_framework->get_d3d12_hook()->get_command_queue() != queue ||
                                            !uevr::quadview::ngx::PeripheryDepth::m41_order_for_composition(fine_pair, queue)) return;
                                        commands.seam_submission_queue = queue;
                                    }
                                    recorded = compositor.record_native(device, commands.cmd_list.Get(),"""),
        ("keep previous full-resolution projection eligible, not a previous coarse projection",
         """                                pose.duoview_stereo_output=stereo_output;""",
         """                                pose.duoview_stereo_output=stereo_output;
                                pose.duoview_full_resolution_depth=require_fine;"""),
        ("keep strict mode armed on generation or pose mismatch",
         """                                        !uevr::duoview::native_frame_binding(*packet_frame)) {
                                        compositor_fault = true;""",
         """                                        !uevr::duoview::native_frame_binding(*packet_frame)) {
                                        compositor_fault = !require_fine;"""),
        ("keep strict mode armed when the compositor is not ready",
         """                                            "[DuoView][Activation] Missing prewarmed compositor for XR command slot");
                                        compositor_fault = true;""",
         """                                            "[DuoView][Activation] Missing prewarmed compositor for XR command slot");
                                        compositor_fault = !require_fine;"""),
        ("keep mode armed on strict compositor rejection",
         """                                        compositor_fault = true;
                                    }
                                }, std::nullopt, D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr,""",
         """                                        compositor_fault = !require_fine;
                                    }
                                }, std::nullopt, D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr,"""),
    ])

    patch(vr / "DuoViewD3D12.hpp", [
        ("require the actual fine grid before any GPU draw",
         "        const bool direct_xr=m1_active ||",
         """        const bool require_fine=settings.synthetic_stereo && settings.m4_fovea_grid;
        if (require_fine && (!m1_active || !m1_.m4_active))
            return reject("Full-resolution fovea depth is required for M4 stereo");
        const bool direct_xr=m1_active ||"""),
        ("block the mono gather fallback on strict M4",
         "            return record_native_gather(device,cmd,primary,secondary,destination,",
         """            if (require_fine) return reject("M4 stereo requires shader-readable source textures");
            return record_native_gather(device,cmd,primary,secondary,destination,"""),
        ("also enforce the requirement through the gather entry point",
         """        const auto reject = [this](const char* reason) { error_ = reason; return false; };
        if (!device || !cmd || !primary || !secondary || !destination || primary == secondary ||""",
         """        const auto reject = [this](const char* reason) { error_ = reason; return false; };
        if (frame.config.settings.synthetic_stereo && frame.config.settings.m4_fovea_grid)
            return reject("Gather cannot record M4 full-resolution stereo");
        if (!device || !cmd || !primary || !secondary || !destination || primary == secondary ||"""),
    ])
    patch(vr / "DuoViewM1D3D12.hpp", [
        ("same-transaction M4 uses full fine weight without the old content veto",
         "        m25_content_active=fine_ok && fine_mode==1u;",
         "        m25_content_active=fine_ok && fine_mode==1u && !m4_fovea_grid;"),
    ])
    patch(vr / "runtimes/OpenXR.hpp", [
        ("track which projection was made with fine depth",
         "        bool duoview_stereo_output{};",
         "        bool duoview_stereo_output{};\n        bool duoview_full_resolution_depth{};"),
    ])
    patch(vr / "runtimes/OpenXR.cpp", [
        ("do not hold a pre-M4 frame when fine depth is required",
         """        duoview_holding=false;
        if (duoview_pending_pose) {""",
         """        const auto settings=vr->duoview_state().settings();
        const bool require_fine=settings.synthetic_stereo && settings.m4_fovea_grid;
        duoview_holding=false;
        if (require_fine && duoview_pending_pose && !duoview_pending_pose->duoview_full_resolution_depth)
            duoview_pending_pose.reset();
        if (duoview_pending_pose) {"""),
        ("accept only a complete previous fine projection during a short interruption",
         """        } else if (duoview_submitted_pose &&
            duoview_continuity.can_hold""",
         """        } else if (duoview_submitted_pose &&
            (!require_fine || duoview_submitted_pose->duoview_full_resolution_depth) &&
            duoview_continuity.can_hold"""),
    ])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_duoview_m41_frame_bind.py <backend>")
    backend(Path(sys.argv[1]) / "src/mods")
    print("M4.1: matched fine depth required for every M4 stereo submission")

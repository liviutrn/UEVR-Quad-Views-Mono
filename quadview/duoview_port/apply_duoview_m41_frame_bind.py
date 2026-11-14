#!/usr/bin/env python3
"""DuoView M4.1 (Claude, 14 Nov 2026): bind fovea/periphery depth to the colour
packet's own OpenXR frame, the same rule DuoView uses for colour (v22
"projection coherence": a packet carries its frozen projection/crop and its
mono_source_frame; the compositor never mixes in a live or newer one).

Problem (Liviu, #262): with eye tracking, fine fovea depth slid with the eyes
and settled late. Depth images were picked as "newest available": the fine one
was the next frame's about half the time (seq +1, log 12:14-12:20), and could
come from another gaze crop than the colour packet being composited.

Fix: every DuoView NGX depth capture is stamped with the OpenXR render-frame
number that UEVR publishes when that frame's RHI work executes
(internal_render_frame_count, the counterpart of the colour packet's
mono_source_frame). With M4 ON the compositor uses only the coarse+fine pair of
the packet's own frame; if that exact pair is missing it uses coarse only for
that frame (no fine from a different frame/crop). M4 OFF: selection unchanged.
Log: [DuoView][M4] exact/miss and where the newest images sat relative to the
packet frame (-3..+3 histogram).

Run after apply_duoview_m4_fovea.py. Every edit is exact-once.
"""
import sys
from pathlib import Path
from apply_duoview_b40_pipeline import patch

PAIR_FN = r'''
    // M4.1: coarse + fine depth from the colour packet's own OpenXR frame only.
    std::pair<std::shared_ptr<const DepthSnapshot>,std::shared_ptr<const DepthSnapshot>>
    m41_pair_for_frame(uint64_t generation,uint32_t coarse_w,uint32_t coarse_h,
            uint32_t fine_w,uint32_t fine_h,ID3D12CommandQueue* consumer_queue,uint32_t frame) {
        const auto request=duoview_expected_.load(std::memory_order_acquire);
        if(!frame || !consumer_queue ||
           capture_mode_.load(std::memory_order_acquire)!=DepthCaptureMode::DuoView ||
           !request || request->generation!=generation ||
           request->width!=coarse_w || request->height!=coarse_h ||
           request->fovea_width!=fine_w || request->fovea_height!=fine_h) {++m41_miss_;return {};}
        std::scoped_lock lock(mutex_);
        std::shared_ptr<DepthSnapshot> coarse,fine,newest_coarse,newest_fine;
        uint64_t unstamped=0;
        for(const auto& s:pool_) {
            if(!s || s->duoview_request!=request || !s->submitted || !s->valid_evaluation ||
               !s->texture || !s->producer_fence_value) continue;
            const uint64_t completed=s->producer_fence ? s->producer_fence->GetCompletedValue() : 0;
            if(completed==UINT64_MAX || !(s->duoview_producer_queue.Get()==consumer_queue ||
               depth_copy_complete(completed,s->producer_fence_value))) continue;
            const bool is_fine=s->duoview_fovea;
            if(!matches_periphery(s->out_w,s->out_h,is_fine ? fine_w : coarse_w,is_fine ? fine_h : coarse_h)) continue;
            if(is_fine && !s->jitter_valid) continue;
            if(!s->m41_frame_valid) {++unstamped;continue;}
            auto& newest=is_fine ? newest_fine : newest_coarse;
            if(!newest || s->sequence>newest->sequence) newest=s;
            if(s->m41_frame!=frame) continue;
            auto& exact=is_fine ? fine : coarse;
            if(!exact || s->sequence>exact->sequence) exact=s;
        }
        const auto bucket=[&](const std::shared_ptr<DepthSnapshot>& s)->size_t {
            const int32_t d=int32_t(s->m41_frame-frame);
            return size_t((std::clamp)(d,-3,3)+3);
        };
        if(newest_coarse) ++m41_coarse_hist_[bucket(newest_coarse)];
        if(newest_fine) ++m41_fine_hist_[bucket(newest_fine)];
        m41_unstamped_+=unstamped;
        if(coarse && fine) {++m41_exact_;return {coarse,fine};}
        ++m41_miss_;
        return {};
    }
    struct M41Window { uint64_t exact,miss,unstamped; std::array<uint64_t,7> coarse{},fine{}; };
    M41Window m41_take_window() {
        M41Window w{m41_exact_.exchange(0),m41_miss_.exchange(0),m41_unstamped_.exchange(0)};
        for(size_t i=0;i<7;++i) { w.coarse[i]=m41_coarse_hist_[i].exchange(0); w.fine[i]=m41_fine_hist_[i].exchange(0); }
        return w;
    }
    // The OpenXR render-frame number of the RHI work being recorded right now.
    void m41_set_frame_provider(bool(*provider)(uint32_t&)) noexcept {
        m41_frame_provider_.store(provider,std::memory_order_release);
    }
'''


def backend(mods):
    vr = mods/"vr"
    patch(vr/"QuadViewNgxDepth.hpp", [
        ("M4.1 snapshot frame stamp",
         "    uint64_t m24_present_epoch{};\n    bool duoview_fovea{};",
         "    uint64_t m24_present_epoch{};\n"
         "    uint32_t m41_frame{}; // OpenXR render frame of the RHI work that evaluated it\n"
         "    bool m41_frame_valid{};\n"
         "    bool duoview_fovea{};"),
        ("M4.1 stamp at capture",
         "        slot->m24_present_epoch=duo ?\n            m24_present_epoch_.load(std::memory_order_acquire) : 0u;\n",
         "        slot->m24_present_epoch=duo ?\n            m24_present_epoch_.load(std::memory_order_acquire) : 0u;\n"
         "        slot->m41_frame=0; slot->m41_frame_valid=false;\n"
         "        if(duo) {\n"
         "            if(const auto provider=m41_frame_provider_.load(std::memory_order_acquire)) {\n"
         "                uint32_t frame{};\n"
         "                if(provider(frame) && frame) { slot->m41_frame=frame; slot->m41_frame_valid=true; }\n"
         "            }\n"
         "        }\n"),
        ("M4.1 exact-frame selection",
         "        ++m25_cpu_pairs_;\n        return latest;\n    }\n",
         "        ++m25_cpu_pairs_;\n        return latest;\n    }\n" + PAIR_FN),
        ("M4.1 state",
         "    std::atomic<uint64_t> m24_present_epoch_{1};\n",
         "    std::atomic<uint64_t> m24_present_epoch_{1};\n"
         "    std::atomic<bool(*)(uint32_t&)> m41_frame_provider_{nullptr};\n"
         "    std::atomic<uint64_t> m41_exact_{},m41_miss_{},m41_unstamped_{};\n"
         "    std::array<std::atomic<uint64_t>,7> m41_coarse_hist_{},m41_fine_hist_{};\n"),
    ])

    patch(vr/"D3D12Component.cpp", [
        ("M4.1 render-frame provider",
         "vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {\n",
         "// M4.1: frame number of the RHI work being executed (published by UEVR's\n"
         "// render-pose handoff), i.e. the counterpart of a packet's mono_source_frame.\n"
         "static bool m41_render_frame(uint32_t& out) {\n"
         "    const auto vr=VR::get();\n"
         "    const auto xr=vr ? vr->get_openxr_runtime() : nullptr;\n"
         "    if(!xr) return false;\n"
         "    // Lock-free read (called inside NGX evaluation): never block the RHI thread\n"
         "    // on the XR pose mutex. Both fields are naturally aligned scalars.\n"
         "    if(!std::atomic_ref<bool>(xr->has_render_frame_count).load(std::memory_order_acquire)) return false;\n"
         "    out=std::atomic_ref<uint32_t>(xr->internal_render_frame_count).load(std::memory_order_acquire);\n"
         "    return true;\n"
         "}\n\n"
         "vr::EVRCompositorError D3D12Component::on_frame(VR* vr) {\n"),
        ("M4.1 register provider",
         "        depth.m24_note_present();\n",
         "        depth.m24_note_present();\n"
         "        depth.m41_set_frame_provider(&m41_render_frame);\n"),
        ("M4.1 coarse from the packet frame",
         "                                            const auto snapshot=(config.settings.m25_fine_mode==0u && pair.first) ?\n",
         "                                            const auto m41_pair=config.settings.m4_fovea_grid ?\n"
         "                                                depths.m41_pair_for_frame(config.key.generation,\n"
         "                                                    periphery.width,periphery.height,fovea.width,fovea.height,\n"
         "                                                    current_queue,packet_frame->mono_source_frame.value_or(0u)) :\n"
         "                                                std::pair<std::shared_ptr<const uevr::quadview::ngx::DepthSnapshot>,\n"
         "                                                    std::shared_ptr<const uevr::quadview::ngx::DepthSnapshot>>{};\n"
         "                                            const auto snapshot=m41_pair.first ? m41_pair.first :\n"
         "                                                (config.settings.m25_fine_mode==0u && pair.first) ?\n"),
        ("M4.1 fine only from the packet frame",
         "                                            const auto m25_fine=(config.settings.m2_fovea_depth &&\n",
         "                                            const auto m25_fine=m41_pair.second ? m41_pair.second :\n"
         "                                                config.settings.m4_fovea_grid ?\n"
         "                                                std::shared_ptr<const uevr::quadview::ngx::DepthSnapshot>{} :\n"
         "                                                (config.settings.m2_fovea_depth &&\n"),
        ("M4.1 log",
         "                                                SPDLOG_INFO(\"[DuoView][M4] fovea_grid={} frames={} grid={}x{} fine_in={}x{}\",\n",
         "                                                const auto m41=depths.m41_take_window();\n"
         "                                                SPDLOG_INFO(\"[DuoView][M4.1] exact={} miss={} unstamped={} newest_coarse_vs_packet=-3:{},-2:{},-1:{},0:{},1:{},2:{},3:{} newest_fine_vs_packet=-3:{},-2:{},-1:{},0:{},1:{},2:{},3:{}\",\n"
         "                                                    m41.exact,m41.miss,m41.unstamped,\n"
         "                                                    m41.coarse[0],m41.coarse[1],m41.coarse[2],m41.coarse[3],m41.coarse[4],m41.coarse[5],m41.coarse[6],\n"
         "                                                    m41.fine[0],m41.fine[1],m41.fine[2],m41.fine[3],m41.fine[4],m41.fine[5],m41.fine[6]);\n"
         "                                                SPDLOG_INFO(\"[DuoView][M4] fovea_grid={} frames={} grid={}x{} fine_in={}x{}\",\n"),
    ])


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_duoview_m41_frame_bind.py <backend>")
    backend(Path(sys.argv[1])/"src/mods")
    print("M4.1: depth bound to the colour packet's OpenXR frame (M4 ON only)")


if __name__ == "__main__":
    main()

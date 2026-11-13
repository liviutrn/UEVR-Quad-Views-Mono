#!/usr/bin/env python3
"""M2.4 additive Present-epoch provenance and fail-safe fine ramp.

M2.3 adjacent+25ms+same-queue/fence selection remains mandatory. Present-epoch
equality is a further rejection gate, never an excuse to accept older depth.
Caveat: the epoch's actual relationship to the UE colour frame is empirical.
"""
import sys
from pathlib import Path
from apply_duoview_b40_pipeline import patch


def main():
    if len(sys.argv)!=2:
        raise SystemExit("Usage: apply_duoview_m24_epoch.py <backend>")
    mods=Path(sys.argv[1])/"src/mods"
    patch(mods/"vr/DuoViewState.hpp",[
        ("M24 freeze epoch field",
         '    std::optional<uint32_t> mono_source_frame{};',
         '    std::optional<uint32_t> mono_source_frame{};\n    uint64_t present_epoch{}; // Present counter sampled at colour-packet freeze'),
        ("M24 frozen epoch argument",
         'uint64_t now_ms=0, std::optional<uint32_t> mono_source_frame={}) {',
         'uint64_t now_ms=0, std::optional<uint32_t> mono_source_frame={},uint64_t present_epoch=0) {'),
        ("M24 save frozen epoch",
         '        slot->mono_source_frame = mono_source_frame;',
         '        slot->mono_source_frame = mono_source_frame;\n        slot->present_epoch=present_epoch;'),
    ])
    patch(mods/"VR.cpp",[
        ("M24 use producer epoch at packet freeze",
         '}, GetTickCount64(), source_frame);',
         '''}, GetTickCount64(), source_frame,
        uevr::quadview::ngx::PeripheryDepth::self().m24_current_epoch());'''),
    ])
    patch(mods/"vr/QuadViewNgxDepth.hpp",[
        ("M24 capture epoch field",
         '    std::shared_ptr<const DuoViewDepthRequest> duoview_request;',
         '    std::shared_ptr<const DuoViewDepthRequest> duoview_request;\n    uint64_t m24_present_epoch{};'),
        ("M24 producer epoch and safety counters",
         '    std::atomic<bool> m21_allow_fine_capture_{false};',
         '''    std::atomic<bool> m21_allow_fine_capture_{false};
    std::atomic<uint64_t> m24_present_epoch_{1};
    std::atomic<uint64_t> m24_epoch_reject_{0},m24_epoch_equal_{0};
    std::atomic<uint32_t> m24_good_streak_{0};
    std::atomic<float> m24_fine_weight_{0.f};
    std::atomic<int64_t> m24_fade_start_ms_{0};'''),
        ("M24 frame epoch API",
         '''    void set_duoview_fine_capture_enabled(bool on) noexcept {
        m21_allow_fine_capture_.store(on,std::memory_order_release);
    }''',
         '''    // One increment per game's D3D12 Present processing, NOT xrEndFrame.
    // This must be empirically compared to the colour packet's source frame.
    uint64_t m24_current_epoch() const noexcept {
        return m24_present_epoch_.load(std::memory_order_acquire);
    }
    void m24_note_present() noexcept {
        m24_present_epoch_.fetch_add(1,std::memory_order_acq_rel);
    }
    uint64_t m24_epoch_rejects() const noexcept {return m24_epoch_reject_.load();}
    uint64_t m24_epoch_equals() const noexcept {return m24_epoch_equal_.load();}
    float m24_fine_weight() const noexcept {return m24_fine_weight_.load();}
    void set_duoview_fine_capture_enabled(bool on) noexcept {
        m21_allow_fine_capture_.store(on,std::memory_order_release);
        if(!on) {m24_good_streak_.store(0);m24_fine_weight_.store(0.f);}
    }'''),
        ("M24 capture epoch at actual NGX record",
         '        slot->recorded = now;',
         '''        slot->recorded = now;
        slot->m24_present_epoch=duo ?
            m24_present_epoch_.load(std::memory_order_acquire) : 0u;'''),
        ("M24 packet epoch strict argument",
         '''latest_duoview_pair_submitted(uint64_t generation,
            uint32_t coarse_w,uint32_t coarse_h,uint32_t fine_w,uint32_t fine_h,
            ID3D12CommandQueue* consumer_queue) {
        const auto request=duoview_expected_.load(std::memory_order_acquire);''',
         '''latest_duoview_pair_submitted(uint64_t generation,
            uint32_t coarse_w,uint32_t coarse_h,uint32_t fine_w,uint32_t fine_h,
            ID3D12CommandQueue* consumer_queue,uint64_t packet_epoch) {
        const auto request=duoview_expected_.load(std::memory_order_acquire);'''),
        ("M24 epoch fail closed for missing colour stamp",
         '            !consumer_queue) { m21_pair_reason_.store(1); ++m21_pair_misses_; return {}; }',
         '''            !consumer_queue || !packet_epoch) {
            m21_pair_reason_.store(1); ++m21_pair_misses_;
            m24_good_streak_.store(0);m24_fine_weight_.store(0.f);return {}; }'''),
        ("M24 epoch EXTRA gate after all original pair checks",
         '''                if (!best_c || (std::max)(coarse->sequence,fine->sequence)>''',
         '''                // An ADDITIONAL gate: never drop M2.3 adjacency/time/queue/fence.
                // Equal Present epochs are necessary, not proven sufficient.
                if(coarse->m24_present_epoch!=fine->m24_present_epoch ||
                   coarse->m24_present_epoch!=packet_epoch) {
                    reason=6; ++m24_epoch_reject_; continue;
                }
                ++m24_epoch_equal_;
                if (!best_c || (std::max)(coarse->sequence,fine->sequence)>'''),
        ("M24 fail-safe reset on pair miss",
         '        if (!best_c) {\n            m21_pair_reason_.store(reason);',
         '''        if (!best_c) {
            m24_good_streak_.store(0);m24_fine_weight_.store(0.f);
            m21_pair_reason_.store(reason);'''),
        ("M24 early cooldown fail-safe",
         '''            m21_pair_reason_.store(5); m21_pair_gap_us_.store(0); return {};''',
         '''            m24_good_streak_.store(0);m24_fine_weight_.store(0.f);
            m21_pair_reason_.store(5); m21_pair_gap_us_.store(0); return {};'''),
        ("M24 ramp only after five consecutive valid pairs",
         '''        m21_pair_reason_.store(0); ++m21_pairs_; ++used_;''',
         '''        const uint32_t streak=m24_good_streak_.fetch_add(1)+1;
        if(streak<5u) {
            m24_fine_weight_.store(0.f);
            m21_pair_reason_.store(7);return {};
        }
        if(streak==5u) m24_fade_start_ms_.store(now_ms,std::memory_order_relaxed);
        const int64_t start=m24_fade_start_ms_.load(std::memory_order_relaxed);
        const float ramp=float((std::max)(int64_t(0),now_ms-start))/200.f;
        m24_fine_weight_.store((std::clamp)(ramp,0.f,1.f));
        m21_pair_reason_.store(0); ++m21_pairs_; ++used_;'''),
    ])
    patch(mods/"vr/D3D12Component.cpp",[
        ("M24 present boundary on same D3D12 path as NGX",
         '''        auto& depth=uevr::quadview::ngx::PeripheryDepth::self();
        const bool duo_depth''',
         '''        auto& depth=uevr::quadview::ngx::PeripheryDepth::self();
        // Records the boundary at the UEVR D3D12 Present callback.
        depth.m24_note_present();
        const bool duo_depth'''),
        ("M24 include frozen packet epoch in pair selection",
         '''fovea.width,fovea.height,current_queue)''',
         '''fovea.width,fovea.height,current_queue,packet_frame->present_epoch)'''),
        ("M24 pair decision log and epoch histogram",
         '''                                            if (snapshot && pair.first==snapshot && pair.second) {''',
         '''                                            SPDLOG_INFO_EVERY_N_SEC(2,
                                                "[DuoView][M2.4] epoch packet={} coarse={} fine={} packet_frame={} source_frame={} epoch_equal={} epoch_reject={} fine_weight={:.2f}",
                                                packet_frame->present_epoch,
                                                snapshot?snapshot->m24_present_epoch:0u,
                                                pair.second?pair.second->m24_present_epoch:0u,
                                                config.key.frame,
                                                packet_frame->mono_source_frame.value_or(0),
                                                depths.m24_epoch_equals(),depths.m24_epoch_rejects(),
                                                depths.m24_fine_weight());
                                            if (snapshot && pair.first==snapshot && pair.second) {'''),
        ("M24 pass fine ramp within fenced capture lease",
         'focus->jitter_uv,focus};',
         'focus->jitter_uv,focus,depths.m24_fine_weight()};'),
        ("M24 scale diagnostics for cross-eye sanity",
         '''                                        if (stereo_geometry) {
                                            const auto& config=packet_frame->config;''',
         '''                                        if (stereo_geometry) {
                                            const float dx=eyes[1].position[0]-eyes[0].position[0];
                                            const float dy=eyes[1].position[1]-eyes[0].position[1];
                                            const float dz=eyes[1].position[2]-eyes[0].position[2];
                                            const float sep=std::sqrt(dx*dx+dy*dy+dz*dz);
                                            const float wtm=stereo_geometry->world_to_meters;
                                            const float pixPerInvM=float(vr->get_hmd_width())/(std::max)(wtm,1.e-6f);
                                            SPDLOG_INFO_EVERY_N_SEC(2,
                                                "[DuoView][M2.4] scale eye_sep_m={:.5f} wtm={:.3f} strength={:.3f} k_l={:.7f} k_r={:.7f} disp_1m_px={:.2f} disp_04m_px={:.2f}",
                                                sep,wtm,packet_frame->config.settings.stereo_strength,
                                                stereo_geometry->k[0],stereo_geometry->k[1],
                                                2.f*std::abs(stereo_geometry->k[1])*pixPerInvM,
                                                5.f*std::abs(stereo_geometry->k[1])*pixPerInvM);
                                            const auto& config=packet_frame->config;'''),
    ])
    print("M2.4: Present-epoch stamp/reject extra gate, 5-good-pair 200ms ramp-in, immediate unsafe drop, scale audit")
if __name__=="__main__":
    main()

#!/usr/bin/env python3
"""Builder A M2.5a: role-safe snapshots and opt-in content-checked CPU candidates.

Run after M2.4 and Trace21, before embedding FXC. Every source edit is
exactly-once. TriView/mono paths and strict M2.4 mode remain untouched.
"""
from pathlib import Path
import sys
from apply_duoview_b40_pipeline import patch

def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: apply_duoview_m25a_cpu.py <backend> <shaders>")
    mods=Path(sys.argv[1])/"src/mods"

    patch(mods/"vr/DuoViewConfig.hpp",[
        ("M25 mode state",
         "    bool m2_fovea_depth{false};",
         "    bool m2_fovea_depth{false};\n    uint32_t m25_fine_mode{0}; // 0=M2.4 strict, 1=GPU content gate"),
        ("M25 mode validate",
         "    out.m2_fovea_depth=requested.m2_fovea_depth;",
         "    out.m2_fovea_depth=requested.m2_fovea_depth;\n    out.m25_fine_mode=(std::min)(requested.m25_fine_mode,1u);"),
        ("M25 debug becomes four-way",
         "    bool m21_depth_debug{false};",
         "    uint32_t m21_depth_debug{0};"),
    ])
    patch(mods/"VR.hpp",[
        ("M25 mode persistent",
         '    const ModToggle::Ptr m_duo_m2_fovea_depth{',
         '    const ModSlider::Ptr m_duo_m25_fine_mode{ModSlider::create(generate_name("DuoM25FineMode"),0.f,1.f,0.f)};\n    const ModToggle::Ptr m_duo_m2_fovea_depth{'),
        ("M25 debug slider",
         'const ModToggle::Ptr m_duo_m21_depth_debug{ModToggle::create(generate_name("DuoM21DepthDebug"),false)};',
         'const ModSlider::Ptr m_duo_m21_depth_debug{ModSlider::create(generate_name("DuoM21DepthDebug"),0.f,3.f,0.f)};'),
        ("M25 persist",
         '            *m_duo_m2_fovea_depth, *m_duo_m21_depth_debug,',
         '            *m_duo_m25_fine_mode, *m_duo_m2_fovea_depth, *m_duo_m21_depth_debug,'),
    ])
    patch(mods/"VR.cpp",[
        ("M25 default",
         'm_duo_m2_fovea_depth->value()=false;',
         'm_duo_m2_fovea_depth->value()=false;\n                    m_duo_m25_fine_mode->value()=0.f;'),
        ("M25 menu",
         'm_duo_m2_fovea_depth->draw("M2 fine fovea depth (experimental: off by default)");',
         'm_duo_m2_fovea_depth->draw("M2 fine fovea depth (experimental: off by default)");\n                    if (m_duo_m2_fovea_depth->value()) m_duo_m25_fine_mode->draw("Fine depth check (0=M2.4 strict, 1=content-checked)");'),
        ("M25 debug label",
         'm_duo_m21_depth_debug->draw("M2.1 depth edge overlay (unwarped image)");',
         'm_duo_m21_depth_debug->draw("Depth debug (0=off, 1=conditioned, 2=fine weight, 3=disagreement)");'),
        ("M25 config freeze",
         '.m2_fovea_depth=m_duo_m2_fovea_depth->value(),',
         '.m2_fovea_depth=m_duo_m2_fovea_depth->value(),\n        .m25_fine_mode=uint32_t(m_duo_m25_fine_mode->value()>=.5f),'),
        ("M25 debug freeze",
         '.m21_depth_debug=m_duo_m21_depth_debug->value(),',
         '.m21_depth_debug=uint32_t((std::clamp)(m_duo_m21_depth_debug->value(),0.f,3.f)+.5f),'),
        ("M25 mode equality",
         'current.m2_fovea_depth==candidate.m2_fovea_depth &&',
         'current.m2_fovea_depth==candidate.m2_fovea_depth &&\n        current.m25_fine_mode==candidate.m25_fine_mode &&'),
    ])

    patch(mods/"vr/QuadViewNgxDepth.hpp",[
        ("M25 persistent role ownership",
         "    bool duoview_fovea{};",
         "    bool duoview_fovea{};\n    uint8_t m25_pool_role{}; // 0=legacy, 1=Duo coarse, 2=Duo fine"),
        ("M25 role of capture",
         "        const bool coarse_output=matches_periphery(out_w,out_h,want_w,want_h);",
         "        const bool coarse_output=matches_periphery(out_w,out_h,want_w,want_h);\n        const uint8_t m25_role=duo ? (fine_output ? 2u : 1u) : 0u;"),
        ("M25 selection role isolation",
         '''        for (auto& candidate : pool_) {
            if (candidate->duoview_request != request) continue;
            const uint64_t completed''',
         '''        uint32_t m25_owned=0;
        if (duo) for(const auto& s:pool_) if(s->m25_pool_role==m25_role) ++m25_owned;
        for (auto& candidate : pool_) {
            if (candidate->duoview_request != request) continue;
            if(duo && candidate->m25_pool_role!=m25_role &&
                !(candidate->m25_pool_role==0u && m25_owned<6u)) continue;
            const uint64_t completed'''),
        ("M25 per-role cap and busy accounting",
         'if (pool_.size() >= MaxSlots) { if (duo) ++m21_full_; reject(PoolFull); return {}; }',
         '''if ((duo && m25_owned>=6u) || pool_.size()>=MaxSlots) {
                if(duo) {++m21_full_;++m25_alloc_busy_;}
                reject(PoolFull);return {};
            }'''),
        ("M25 immutable role on capture",
         "        slot->duoview_fovea = fine_output;",
         '''        slot->duoview_fovea = fine_output;
        // Only a retired slot can be selected above. The role never changes
        // between DuoView coarse and fine, even during Cheeky resize pressure.
        slot->m25_pool_role=m25_role;'''),
        ("M25 split allocation reason telemetry",
         '''            if (duo) { ++m21_alloc_; if (slot->texture) ++m21_realloc_; }
            slot->texture.Reset();''',
         '''            if (duo) {
                ++m21_alloc_;
                if(m25_role==1u) ++m25_alloc_coarse_;
                else if(m25_role==2u) ++m25_alloc_fine_;
                if(slot->texture) {
                    ++m21_realloc_;
                    if(have.Width!=w || have.Height!=h) ++m25_resize_;
                    else if(have.Format!=copy_format) ++m25_reformat_;
                }
            }
            slot->texture.Reset();'''),
        ("M25 counters",
         "    std::atomic<uint64_t> m21_alloc_{},m21_realloc_{},m21_full_{},m21_pairs_{},m21_pair_misses_{};",
         '''    std::atomic<uint64_t> m21_alloc_{},m21_realloc_{},m21_full_{},m21_pairs_{},m21_pair_misses_{};
    std::atomic<uint64_t> m25_alloc_coarse_{},m25_alloc_fine_{},m25_resize_{},m25_reformat_{},m25_alloc_busy_{};
    std::atomic<uint64_t> m25_cpu_pairs_{},m25_cpu_none_{};
    std::array<std::atomic<uint64_t>,5> m25_delta_hist_{};
    std::array<std::atomic<uint64_t>,8> m25_reject_hist_{};'''),
        ("M25 content candidate API",
         '    struct M21Stats {\n',
         '''    // The coarse snapshot is already chosen by the original fence-safe
    // latest_duoview_submitted(). Only seek a fine sibling for that snapshot.
    // No CPU timeline "same frame" assertion; GPU proves local agreement.
    std::shared_ptr<const DepthSnapshot> latest_duoview_content_fine_submitted(
            uint64_t generation,uint32_t fine_w,uint32_t fine_h,
            ID3D12CommandQueue* consumer_queue,
            const std::shared_ptr<const DepthSnapshot>& coarse) {
        const auto request=duoview_expected_.load(std::memory_order_acquire);
        if(!coarse || !consumer_queue ||
           capture_mode_.load(std::memory_order_acquire)!=DepthCaptureMode::DuoView ||
           !request || request->generation!=generation ||
           request->fovea_width!=fine_w || request->fovea_height!=fine_h ||
           coarse->duoview_request!=request || coarse->duoview_fovea) {
            ++m25_cpu_none_;++m25_reject_hist_[1];return {};
        }
        std::scoped_lock lock(mutex_);
        std::shared_ptr<DepthSnapshot> latest;
        for(const auto& fine:pool_) {
            if(!fine || fine->duoview_request!=request || !fine->duoview_fovea ||
                !fine->submitted || !fine->valid_evaluation || !fine->texture ||
                !fine->jitter_valid || !fine->producer_fence_value ||
                !matches_periphery(fine->out_w,fine->out_h,fine_w,fine_h)) continue;
            const uint64_t completed=fine->producer_fence ?
                fine->producer_fence->GetCompletedValue() : 0;
            if(completed==UINT64_MAX ||
               !(fine->duoview_producer_queue.Get()==consumer_queue ||
                 depth_copy_complete(completed,fine->producer_fence_value))) continue;
            const uint64_t gap=fine->sequence>coarse->sequence ?
                fine->sequence-coarse->sequence : coarse->sequence-fine->sequence;
            if(gap>2u) continue;
            if(!latest || fine->sequence>latest->sequence) latest=fine;
        }
        if(!latest) {++m25_cpu_none_;++m25_reject_hist_[2];return {};}
        const int delta=int(latest->sequence)-int(coarse->sequence);
        ++m25_delta_hist_[(std::clamp)(delta,-2,2)+2];
        ++m25_cpu_pairs_;
        return latest;
    }
    struct M25Stats {
        uint64_t alloc_coarse,alloc_fine,resize,reformat,busy,cpu_pairs,cpu_none;
        std::array<uint64_t,5> delta;
        std::array<uint64_t,8> reject;
    };
    M25Stats m25_stats() const {
        M25Stats s{m25_alloc_coarse_.load(),m25_alloc_fine_.load(),
            m25_resize_.load(),m25_reformat_.load(),m25_alloc_busy_.load(),
            m25_cpu_pairs_.load(),m25_cpu_none_.load()};
        for(size_t i=0;i<5;++i) s.delta[i]=m25_delta_hist_[i].load();
        for(size_t i=0;i<8;++i) s.reject[i]=m25_reject_hist_[i].load();
        return s;
    }

    struct M21Stats {
'''),
    ])

    patch(mods/"vr/D3D12Component.cpp",[
        ("M25 strict remains default",
         'const auto pair=config.settings.m2_fovea_depth\n                                                ? depths.latest_duoview_pair_submitted',
         'const auto pair=(config.settings.m2_fovea_depth && config.settings.m25_fine_mode==0u)\n                                                ? depths.latest_duoview_pair_submitted'),
        ("M25 coarse strictly newest in relaxed mode",
         '''const auto snapshot=pair.first ? pair.first :
                                                depths.latest_duoview_submitted(config.key.generation,
                                                    periphery.width,periphery.height,current_queue);''',
         '''const auto snapshot=(config.settings.m25_fine_mode==0u && pair.first) ?
                                                pair.first : depths.latest_duoview_submitted(
                                                    config.key.generation,periphery.width,periphery.height,current_queue);
                                            const auto m25_fine=(config.settings.m2_fovea_depth &&
                                                config.settings.m25_fine_mode==1u) ?
                                                depths.latest_duoview_content_fine_submitted(
                                                    config.key.generation,fovea.width,fovea.height,
                                                    current_queue,snapshot) : pair.second;'''),
        ("M25 use optional selected fine",
         'if (snapshot && pair.first==snapshot && pair.second) {\n                                                const auto& focus=pair.second;',
         'if (snapshot && m25_fine && (config.settings.m25_fine_mode==1u || pair.first==snapshot)) {\n                                                const auto& focus=m25_fine;'),
        ("M25 weight content gate selected",
         'focus->jitter_uv,focus,depths.m24_fine_weight()};',
         'focus->jitter_uv,focus,config.settings.m25_fine_mode==1u ? 1.f : depths.m24_fine_weight()};'),
    ])
    print("M2.5a CPU: opt-in relaxed fenced selection, role-isolated 6+6 slots, histogram counters")

if __name__=="__main__":
    main()

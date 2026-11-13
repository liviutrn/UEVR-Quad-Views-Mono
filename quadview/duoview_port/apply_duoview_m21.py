#!/usr/bin/env python3
"""M2.1 on M2: global depth conditioning, paired captures, pool reuse, debug.

Exact-anchor generated-source overlay, only after M2 in Windows CI.
Mode 7 remains the original TriView producer and renderer.
"""
from pathlib import Path
import sys
from apply_duoview_b40_pipeline import patch


def controls(mods):
    patch(mods/"vr/DuoViewConfig.hpp",[
        ("M21 fine default safe","    bool m2_fovea_depth{true};","    bool m2_fovea_depth{false};"),
        ("M21 debug config","    bool m2_unlinked_sharpen{false};",
         "    bool m21_depth_debug{false};\n    bool m2_unlinked_sharpen{false};"),
        ("M21 debug reconcile","    out.m2_unlinked_sharpen=requested.m2_unlinked_sharpen;",
         "    out.m2_unlinked_sharpen=requested.m2_unlinked_sharpen;\n    out.m21_depth_debug=requested.m21_depth_debug;"),
        ("M21 per-eye 20 range","(std::clamp)(requested.m2_left_sharpen,0.f,5.f)",
         "(std::clamp)(requested.m2_left_sharpen,0.f,20.f)"),
        ("M21 right 20 range","(std::clamp)(requested.m2_right_sharpen,0.f,5.f)",
         "(std::clamp)(requested.m2_right_sharpen,0.f,20.f)"),
    ])
    patch(mods/"VR.hpp",[
        ("M21 fine toggle default",'ModToggle::create(generate_name("DuoM2FoveaDepth"),true)',
         'ModToggle::create(generate_name("DuoM21FoveaDepth"),false)'),
        ("M21 debug toggle",'    const ModToggle::Ptr m_duo_m2_unlinked{',
         '    const ModToggle::Ptr m_duo_m21_depth_debug{ModToggle::create(generate_name("DuoM21DepthDebug"),false)};\n'
         '    const ModToggle::Ptr m_duo_m2_unlinked{'),
        ("M21 left slider",'ModSlider::create(generate_name("DuoM2LeftSharpen"),0.f,5.f,1.f)',
         'ModSlider::create(generate_name("DuoM2LeftSharpen"),0.f,20.f,1.f)'),
        ("M21 right slider",'ModSlider::create(generate_name("DuoM2RightSharpen"),0.f,5.f,1.f)',
         'ModSlider::create(generate_name("DuoM2RightSharpen"),0.f,20.f,1.f)'),
        ("M21 persist debug",'            *m_duo_m2_fovea_depth, *m_duo_m2_unlinked,',
         '            *m_duo_m2_fovea_depth, *m_duo_m21_depth_debug, *m_duo_m2_unlinked,'),
    ])
    patch(mods/"VR.cpp",[
        ("M21 reset fine",'m_duo_m2_fovea_depth->value()=true;',
         'm_duo_m2_fovea_depth->value()=false;\n                    m_duo_m21_depth_debug->value()=false;'),
        ("M21 edge sharpness name",'m_duo_stereo_softness->draw("Depth edge softness");',
         'm_duo_stereo_softness->draw("Depth edge sharpness (higher = harder edge)");'),
        ("M21 depth display menu",'m_duo_m2_fovea_depth->draw("M2 fine fovea depth (if matched)");',
         'm_duo_m2_fovea_depth->draw("M2 fine fovea depth (experimental: off by default)");\n'
         '                    m_duo_m21_depth_debug->draw("M2.1 depth edge overlay (unwarped image)");'),
        ("M21 frozen debug",'.m2_fovea_depth=m_duo_m2_fovea_depth->value(),',
         '.m2_fovea_depth=m_duo_m2_fovea_depth->value(),\n'
         '        .m21_depth_debug=m_duo_m21_depth_debug->value(),'),
        ("M21 debug equality",'current.m2_fovea_depth==candidate.m2_fovea_depth &&',
         'current.m2_fovea_depth==candidate.m2_fovea_depth &&\n'
         '        current.m21_depth_debug==candidate.m21_depth_debug &&'),
    ])


def captured_pair(mods):
    path=mods/"vr/QuadViewNgxDepth.hpp"
    # Keep original 12-slot safety and TriView selection. For DuoView, prefer
    # reusing an idle texture with matching dimensions/format before resizing.
    patch(path,[
        ("M21 public producer toggle",
         '    void set_duoview_expected(uint64_t generation, uint32_t width, uint32_t height,',
         '''    void set_duoview_fine_capture_enabled(bool on) noexcept {
        m21_allow_fine_capture_.store(on,std::memory_order_release);
    }
    void set_duoview_expected(uint64_t generation, uint32_t width, uint32_t height,'''),
        ("M21 producer defaults to coarse-only",
         '    std::atomic<DepthCaptureMode> capture_mode_{DepthCaptureMode::Off};',
         '''    std::atomic<DepthCaptureMode> capture_mode_{DepthCaptureMode::Off};
    std::atomic<bool> m21_allow_fine_capture_{false};'''),
        ("M21 suppress unused fine NGX copies",
         '''        const bool fine_output=duo && request &&
            matches_periphery(out_w,out_h,request->fovea_width,request->fovea_height);''',
         '''        const bool fine_output=duo && request &&
            m21_allow_fine_capture_.load(std::memory_order_acquire) &&
            matches_periphery(out_w,out_h,request->fovea_width,request->fovea_height);'''),
        ("M21 prioritize matching texture",
         '            if (!slot || candidate->sequence<slot->sequence) slot=candidate;',
         '''            const auto cd=candidate->texture ? candidate->texture->GetDesc() : D3D12_RESOURCE_DESC{};
            const bool fits=candidate->texture && cd.Width==w && cd.Height==h && cd.Format==copy_format;
            const auto sd=slot && slot->texture ? slot->texture->GetDesc() : D3D12_RESOURCE_DESC{};
            const bool best_fits=slot && slot->texture && sd.Width==w && sd.Height==h && sd.Format==copy_format;
            if (!slot || (fits && !best_fits) ||
                (fits==best_fits && candidate->sequence<slot->sequence)) slot=candidate;'''),
        ("M21 count pool full",
         'if (pool_.size() >= MaxSlots) { reject(PoolFull); return {}; }',
         'if (pool_.size() >= MaxSlots) { if (duo) ++m21_full_; reject(PoolFull); return {}; }'),
        ("M21 allocation counters",
         '''            slot->texture.Reset();
            D3D12_RESOURCE_DESC td{};''',
         '''            if (duo) { ++m21_alloc_; if (slot->texture) ++m21_realloc_; }
            slot->texture.Reset();
            D3D12_RESOURCE_DESC td{};'''),
        ("M21 pair statistics state",
         '    uint64_t next_sequence_{};',
         '''    uint64_t next_sequence_{};
    std::atomic<uint64_t> m21_alloc_{},m21_realloc_{},m21_full_{},m21_pairs_{},m21_pair_misses_{};
    std::atomic<uint32_t> m21_pair_reason_{},m21_pair_gap_us_{};
    std::atomic<int64_t> m21_fine_cooldown_until_ms_{};'''),
        ("M21 exact-list pair selection",
         '        return select_recent(width,height,request,consumer_queue,true);\n    }\n\nprivate:',
         '''        return select_recent(width,height,request,consumer_queue,true);
    }

    // Fine depth is used only for two adjacent NGX evaluations from one
    // command-list recording epoch, not a 25 ms coincidence across frames.
    // No proof of equality to the colour packet exists yet; experimental OFF.
    std::pair<std::shared_ptr<const DepthSnapshot>,std::shared_ptr<const DepthSnapshot>>
    latest_duoview_pair_submitted(uint64_t generation,
            uint32_t coarse_w,uint32_t coarse_h,uint32_t fine_w,uint32_t fine_h,
            ID3D12CommandQueue* consumer_queue) {
        const auto request=duoview_expected_.load(std::memory_order_acquire);
        if (capture_mode_.load(std::memory_order_acquire)!=DepthCaptureMode::DuoView ||
            !request || request->generation!=generation ||
            request->width!=coarse_w || request->height!=coarse_h ||
            request->fovea_width!=fine_w || request->fovea_height!=fine_h ||
            !consumer_queue) { m21_pair_reason_.store(1); ++m21_pair_misses_; return {}; }
        const auto now=std::chrono::steady_clock::now();
        const auto not_before=now-std::chrono::milliseconds(250);
        const int64_t now_ms=std::chrono::duration_cast<std::chrono::milliseconds>(
                now.time_since_epoch()).count();
        std::scoped_lock lock(mutex_);
        const auto valid=[&](const std::shared_ptr<DepthSnapshot>& s,bool fine)->bool {
            if (!s || s->duoview_request!=request || s->duoview_fovea!=fine ||
                !s->submitted || !s->valid_evaluation || !s->texture ||
                !s->jitter_valid || !s->producer_fence_value ||
                !depth_capture_in_window(s->recorded,not_before,now)) return false;
            if (!matches_periphery(s->out_w,s->out_h,
                    fine ? fine_w : coarse_w,fine ? fine_h : coarse_h)) return false;
            const uint64_t done=s->producer_fence ?
                s->producer_fence->GetCompletedValue() : 0;
            const bool ordered=done!=UINT64_MAX &&
                (s->duoview_producer_queue.Get()==consumer_queue ||
                 depth_copy_complete(done,s->producer_fence_value));
            return ordered;
        };
        std::shared_ptr<DepthSnapshot> best_c,best_f;
        uint32_t reason=2;
        for (const auto& coarse:pool_) if (valid(coarse,false)) {
            for (const auto& fine:pool_) if (valid(fine,true)) {
                if (coarse->sequence!=fine->sequence+1 &&
                    fine->sequence!=coarse->sequence+1) { reason=3; continue; }
                if (coarse->producer_list!=fine->producer_list ||
                    coarse->list_epoch!=fine->list_epoch) { reason=4; continue; }
                if (!best_c || (std::max)(coarse->sequence,fine->sequence)>
                               (std::max)(best_c->sequence,best_f->sequence)) {
                    best_c=coarse;best_f=fine;
                }
            }
        }
        if (!best_c) {
            m21_pair_reason_.store(reason); m21_pair_gap_us_.store(0); ++m21_pair_misses_;
            m21_fine_cooldown_until_ms_.store(now_ms+500,std::memory_order_relaxed);
            return {};
        }
        // Hold coarse-only after any missing fine pair: avoids rapid toggles.
        if (now_ms<m21_fine_cooldown_until_ms_.load(std::memory_order_relaxed)) {
            m21_pair_reason_.store(5); m21_pair_gap_us_.store(0); return {};
        }
        m21_pair_reason_.store(0); ++m21_pairs_; ++used_;
        last_used_age_us_.store(uint32_t(std::chrono::duration_cast<std::chrono::microseconds>(
            now-best_c->recorded).count()),std::memory_order_relaxed);
        const auto gap=best_f->recorded>=best_c->recorded ?
            best_f->recorded-best_c->recorded : best_c->recorded-best_f->recorded;
        m21_pair_gap_us_.store(uint32_t(std::chrono::duration_cast<std::chrono::microseconds>(
            gap).count()),std::memory_order_relaxed);
        return {best_c,best_f};
    }

    struct M21Stats {
        uint64_t allocations,reallocations,pool_full,pairs,pair_misses,pool_bytes;
        uint32_t pair_reason,pair_gap_us;
    };
    M21Stats m21_stats() const {
        M21Stats s{m21_alloc_.load(),m21_realloc_.load(),
            m21_full_.load(),m21_pairs_.load(),m21_pair_misses_.load(),0,
            m21_pair_reason_.load(),m21_pair_gap_us_.load()};
        std::scoped_lock lock(mutex_);
        for (const auto& slot:pool_) if (slot->texture && slot->duoview_request) {
            const auto d=slot->texture->GetDesc();
            s.pool_bytes+=uint64_t(d.Width)*d.Height*
                (d.Format==DXGI_FORMAT_R32G8X24_TYPELESS ? 8u : 4u);
        }
        return s;
    }

private:''' ),
    ])
    # Producer has the same frozen Mode-6 source-frame setting as the compositor.
    # Fine OFF must not make an unnecessary depth copy every NGX fovea Evaluate.
    patch(mods/"VR.cpp",[
        ("M21 enable fine producer from the frozen packet",
         '''            layout.fovea.width, layout.fovea.height);
    } else {
        uevr::quadview::ngx::PeripheryDepth::self().set_duoview_expected(0, 0, 0, 0, 0);
    }''',
         '''            layout.fovea.width, layout.fovea.height);
        uevr::quadview::ngx::PeripheryDepth::self().set_duoview_fine_capture_enabled(
            frame->config.settings.m2_fovea_depth);
    } else {
        uevr::quadview::ngx::PeripheryDepth::self().set_duoview_expected(0, 0, 0, 0, 0);
        uevr::quadview::ngx::PeripheryDepth::self().set_duoview_fine_capture_enabled(false);
    }'''),
    ])


def deliver(mods):
    patch(mods/"vr/DuoViewD3D12.hpp",[
        ("M21 debug to shader constants",
         '''settings.m2_unlinked_sharpen ? settings.m2_right_sharpen : settings.sharpen_strength,
                settings.stereo_near_m,settings.stereo_softness,m1_raw_srv_,m2_fovea_srv_);''',
         '''settings.m2_unlinked_sharpen ? settings.m2_right_sharpen : settings.sharpen_strength,
                settings.m21_depth_debug,settings.stereo_near_m,settings.stereo_softness,
                m1_raw_srv_,m2_fovea_srv_);'''),
    ])
    patch(mods/"vr/D3D12Component.cpp",[
        ("M21 paired-first lookup",
         '''                                            const auto snapshot=uevr::quadview::ngx::PeripheryDepth::self().latest_duoview_submitted(
                                                config.key.generation,periphery.width,periphery.height,current_queue);''',
         '''                                            const auto& fovea=config.layout.fovea;
                                            auto& depths=uevr::quadview::ngx::PeripheryDepth::self();
                                            const auto pair=config.settings.m2_fovea_depth
                                                ? depths.latest_duoview_pair_submitted(config.key.generation,
                                                    periphery.width,periphery.height,
                                                    fovea.width,fovea.height,current_queue)
                                                : std::pair<std::shared_ptr<const uevr::quadview::ngx::DepthSnapshot>,
                                                    std::shared_ptr<const uevr::quadview::ngx::DepthSnapshot>>{};
                                            const auto snapshot=pair.first ? pair.first :
                                                depths.latest_duoview_submitted(config.key.generation,
                                                    periphery.width,periphery.height,current_queue);'''),
        ("M21 remove timing-only pairing",
         '''                                            if (snapshot && config.settings.m2_fovea_depth) {
                                                const auto& fovea=config.layout.fovea;
                                                const auto focus=uevr::quadview::ngx::PeripheryDepth::self()
                                                    .latest_duoview_fovea_submitted(config.key.generation,
                                                        fovea.width,fovea.height,current_queue);
                                                // A cross-frame depth pair is worse than coarse-only
                                                // stereo. No guessed provenance, no stale mixed views.
                                                if (focus && focus->jitter_valid &&
                                                    focus->recorded <= std::chrono::steady_clock::now() &&
                                                    (focus->recorded > snapshot->recorded
                                                        ? focus->recorded-snapshot->recorded
                                                        : snapshot->recorded-focus->recorded) <=
                                                        std::chrono::milliseconds(25)) {
                                                    fine_depth=uevr::duoview::dx12::M1DepthInput{
                                                        focus->texture.Get(),focus->srv_format,
                                                        {focus->rect[0],focus->rect[1],focus->rect[2],focus->rect[3]},
                                                        focus->jitter_uv,focus};
                                                }
                                            }''',
         '''                                            if (snapshot && pair.first==snapshot && pair.second) {
                                                const auto& focus=pair.second;
                                                fine_depth=uevr::duoview::dx12::M1DepthInput{
                                                    focus->texture.Get(),focus->srv_format,
                                                    {focus->rect[0],focus->rect[1],focus->rect[2],focus->rect[3]},
                                                    focus->jitter_uv,focus};
                                            }'''),
        ("M21 diagnostics",
         '''SPDLOG_INFO_EVERY_N_SEC(2,"[DuoView][M2] stereo={} coarse_depth={} fovea_depth={} strength={:.2f}",
                                                stereo_output,compositor.last_stereo_depth(),
                                                compositor.last_stereo_fovea_depth(),packet_frame->config.settings.stereo_strength);''',
         '''const auto m21=uevr::quadview::ngx::PeripheryDepth::self().m21_stats();
                                            const auto depth_age=uevr::quadview::ngx::PeripheryDepth::self().stats().used_age_us;
                                            SPDLOG_INFO_EVERY_N_SEC(2,"[DuoView][M2.1] stereo={} coarse={} fine={} strength={:.2f} age_us={} pair={}/{} reject={} gap_us={} alloc={} realloc={} full={} poolMiB={:.1f}",
                                                stereo_output,compositor.last_stereo_depth(),
                                                compositor.last_stereo_fovea_depth(),packet_frame->config.settings.stereo_strength,
                                                depth_age,m21.pairs,m21.pair_misses,m21.pair_reason,m21.pair_gap_us,
                                                m21.allocations,m21.reallocations,m21.pool_full,
                                                double(m21.pool_bytes)/1048576.0);'''),
    ])


def shaders(src):
    # Keep native/legacy linked effects exactly as they were before M2.1.
    patch(src/"DuoViewGlamaryeFovea.hlsl",[
        ("M21 wide-strength overload",
         'float3 GlamExtraWideChange(float2 uv, float3 original) {',
         'float3 GlamExtraWideChange(float2 uv, float3 original, float strength) {'),
        ("M21 wide-strength denominator",
         '1.0/max(SharpenStrength,.00001)+abs(detail)/possible',
         '1.0/max(strength,.00001)+abs(detail)/possible'),
        ("M21 legacy wide wrapper",
         '    return change*(1.0-guard);\n}',
         '''    return change*(1.0-guard);
}
float3 GlamExtraWideChange(float2 uv,float3 original) {
    return GlamExtraWideChange(uv,original,SharpenStrength);
}'''),
    ])
    patch(src/"DuoViewNativeCompositeRaster.hlsl",[
        ("M21 disable stereo warp for unwarped depth overlay",
         'const float2 fullUv = M1PullUv(outputUv, i.pos.x >= OutputSize.x ? 1u : 0u);',
         'const float2 fullUv = M2Sharpen.z > .5 ? outputUv : M1PullUv(outputUv, i.pos.x >= OutputSize.x ? 1u : 0u);'),
        ("M21 true independent extra wide",
         'GlamExtraWideChange(fullUv, beforeSharpen)));',
         '''#ifdef DUOVIEW_M1_RASTER
                                            GlamExtraWideChange(fullUv, beforeSharpen, fineSharpen)));
#else
                                            GlamExtraWideChange(fullUv, beforeSharpen)));
#endif'''),
        ("M21 depth edge visual diagnostic",
         '''    if (DebugBorder && weight > 0.01 && weight < 0.1)
        result.rgb = float3(1.0,0.3,0.0);
    return result;''',
         '''    if (DebugBorder && weight > 0.01 && weight < 0.1)
        result.rgb = float3(1.0,0.3,0.0);
#ifdef DUOVIEW_M1_RASTER
    if (M2Sharpen.z>.5 && M1Grid.x>0) {
        const float2 delta=1.0/float2(OutputSize);
        const float2 pos=outputUv;
        const float mid=M1ReadConditioned(pos);
        const float left=M1ReadConditioned(pos-float2(delta.x,0));
        const float right=M1ReadConditioned(pos+float2(delta.x,0));
        const float up=M1ReadConditioned(pos-float2(0,delta.y));
        const float down=M1ReadConditioned(pos+float2(0,delta.y));
        const float edge=max(max(abs(mid-left),abs(mid-right)),
                             max(abs(mid-up),abs(mid-down)));
        const float emphasis=saturate(8.0*edge/max(mid,0.05));
        result.rgb=lerp(result.rgb,float3(1.0,0.03,0.05),emphasis*.85);
    }
#endif
    return result;'''),
    ])


def main():
    if len(sys.argv)!=3:
        raise SystemExit("Usage: apply_duoview_m21.py <backend> <duoview-shaders>")
    mods=Path(sys.argv[1])/"src/mods"
    src=Path(sys.argv[2])
    controls(mods)
    captured_pair(mods)
    deliver(mods)
    shaders(src)
    print("M2.1: globally conditioned fine depth, adjacent same-epoch pairing, WARP debug and separate sharpening")


if __name__=="__main__":
    main()

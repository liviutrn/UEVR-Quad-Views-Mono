#!/usr/bin/env python3
"""WARP A/B for M3b P5: legacy gate and tuned gate at stock defaults."""
from pathlib import Path
import argparse

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--source",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    v=a.parse_args()
    s=v.source.read_text(encoding="utf-8")
    marker="    // Restore every touched field; the final legacy comparison is intended"
    assert s.count(marker)==1, "M3b WARP insertion anchor drifted"
    block=r'''    // M3b P5: defaults must equal M2.5a before any user's tuning.
    {
        const auto m3b_saved_k=m1_geometry.k;
        const auto m3b_saved_depth=m1_depth;
        const auto m3b_saved_fine=m21_fine_depth;
        const auto m3b_saved_mode=frame.config.settings.m25_fine_mode;
        const auto m3b_saved_depth_switch=frame.config.settings.m2_fovea_depth;
        const auto m3b_saved_edges=frame.config.settings.m3_edges;
        const auto m3b_saved_tuning=frame.config.settings.m3b_gate_tuning;
        const auto m3b_saved_tolerance=frame.config.settings.m3b_agree_tolerance;
        const auto m3b_saved_low=frame.config.settings.m3b_ratio_low;
        const auto m3b_saved_high=frame.config.settings.m3b_ratio_high;
        const auto m3b_saved_contrast=frame.config.settings.m3b_contrast;
        m1_geometry.k={.25f,-.25f};
        m1_depth={coarse_step.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
        m21_fine_depth={fine_same.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
        frame.config.settings.m3_edges=false;
        frame.config.settings.m2_fovea_depth=true;
        frame.config.settings.m25_fine_mode=1u;
        frame.config.settings.m3b_gate_tuning=false;
        frame.config.settings.m3b_agree_tolerance=.03f;
        frame.config.settings.m3b_ratio_low=.60f;
        frame.config.settings.m3b_ratio_high=.85f;
        frame.config.settings.m3b_contrast=.10f;
        (void)take();
        run(*a,false,Route::direct,"M3b P5 OFF: M2.5a gate reference");
        const auto m3b_off_hash=m21_image_hash;
        (void)take();
        frame.config.settings.m3b_gate_tuning=true;
        run(*a,false,Route::direct,"M3b P5 ON: same default gate thresholds");
        if(m21_image_hash!=m3b_off_hash)
            throw std::runtime_error("M3b P5 changed image at unchanged M2.5a thresholds");
        frame.config.settings.m3b_gate_tuning=m3b_saved_tuning;
        frame.config.settings.m3b_agree_tolerance=m3b_saved_tolerance;
        frame.config.settings.m3b_ratio_low=m3b_saved_low;
        frame.config.settings.m3b_ratio_high=m3b_saved_high;
        frame.config.settings.m3b_contrast=m3b_saved_contrast;
        frame.config.settings.m25_fine_mode=m3b_saved_mode;
        frame.config.settings.m2_fovea_depth=m3b_saved_depth_switch;
        frame.config.settings.m3_edges=m3b_saved_edges;
        m21_fine_depth=m3b_saved_fine;
        m1_depth=m3b_saved_depth;
        m1_geometry.k=m3b_saved_k;
        std::cout<<"PASS: WARP M3b P5 OFF and default-tuned gate hashes match\n";
    }
'''
    block+=r'''    // M3b OFF hashing across independent P1-P4 toggles, current-frame WARP source.
    {
        const auto savedK=m1_geometry.k;
        const auto savedDepth=m1_depth;
        const auto savedFine=m21_fine_depth;
        const auto savedMode=frame.config.settings.m3_jitter_mode;
        const auto savedEdges=frame.config.settings.m3_edges;
        const auto savedFill=frame.config.settings.m3_fill;
        const auto savedFineEnabled=frame.config.settings.m2_fovea_depth;
        const auto savedGateMode=frame.config.settings.m25_fine_mode;
        const auto savedTemporal=frame.config.settings.m3b_temporal;
        const auto savedTemporalStrength=frame.config.settings.m3b_temporal_strength;
        const auto savedRepair=frame.config.settings.m3b_edge_repair;
        const auto savedRepairMask=frame.config.settings.m3b_edge_mask;
        const auto savedColor=frame.config.settings.m3b_color_edges;
        m1_geometry.k={.25f,-.25f};
        m1_depth={coarse_step.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
        m21_fine_depth={};
        frame.config.settings.m3_edges=false;frame.config.settings.m3_fill=true;
        frame.config.settings.m2_fovea_depth=false;frame.config.settings.m25_fine_mode=0u;
        frame.config.settings.m3_jitter_mode=0u;
        frame.config.settings.m3b_temporal=false;frame.config.settings.m3b_temporal_strength=.6f;
        frame.config.settings.m3b_edge_repair=false;frame.config.settings.m3b_edge_mask=false;
        frame.config.settings.m3b_color_edges=false;
        (void)take();
        run(*a,false,Route::direct,"M3b all OFF reference");
        const auto m3b_base=m21_image_hash;
        frame.config.settings.m3b_edge_repair=true;
        run(*a,false,Route::direct,"M3b repair ON (source-depth path)");
        frame.config.settings.m3b_edge_repair=false;
        run(*a,false,Route::direct,"M3b repair restored OFF");
        if(m21_image_hash!=m3b_base)throw std::runtime_error("M3b P3 OFF hash changed");
        frame.config.settings.m3b_edge_mask=true;
        run(*a,false,Route::direct,"M3b repair mask inert without repair");
        if(m21_image_hash!=m3b_base)throw std::runtime_error("M3b P3 mask OFF-path hash changed");
        frame.config.settings.m3b_edge_mask=false;
        frame.config.settings.m3b_color_edges=true;
        run(*a,false,Route::direct,"M3b colour guided ON");
        frame.config.settings.m3b_color_edges=false;
        run(*a,false,Route::direct,"M3b colour guided OFF restored");
        if(m21_image_hash!=m3b_base)throw std::runtime_error("M3b P4 OFF hash changed");
        frame.config.settings.m3b_temporal=true;
        for(int m3b_i=0;m3b_i<3;++m3b_i)
            run(*a,false,Route::direct,"M3b temporal ON");
        frame.config.settings.m3b_temporal=false;
        run(*a,false,Route::direct,"M3b temporal OFF restored");
        if(m21_image_hash!=m3b_base)throw std::runtime_error("M3b P2 OFF hash changed");
        (void)take();
        frame.config.settings.m3_jitter_mode=3u;
        run(*a,false,Route::direct,"M3b Auto jitter with zero jitter");
        frame.config.settings.m3_jitter_mode=0u;
        run(*a,false,Route::direct,"M3b jitter OFF restored");
        if(m21_image_hash!=m3b_base)throw std::runtime_error("M3b P1 OFF hash changed");
        (void)take();
        frame.config.settings.m3_jitter_mode=savedMode;
        frame.config.settings.m3_edges=savedEdges;frame.config.settings.m3_fill=savedFill;
        frame.config.settings.m2_fovea_depth=savedFineEnabled;
        frame.config.settings.m25_fine_mode=savedGateMode;
        frame.config.settings.m3b_temporal=savedTemporal;
        frame.config.settings.m3b_temporal_strength=savedTemporalStrength;
        frame.config.settings.m3b_edge_repair=savedRepair;
        frame.config.settings.m3b_edge_mask=savedRepairMask;
        frame.config.settings.m3b_color_edges=savedColor;
        m1_depth=savedDepth;m21_fine_depth=savedFine;m1_geometry.k=savedK;
        std::cout<<"PASS: M3b independent switches OFF reproduce M3a image hash\\n";
    }
'''
    block+=r'''    // M3b P1: force a foveal colour edge and jittered coarse-depth edge in WARP.
    {
        auto source_descriptor=texture(32,32,DXGI_FORMAT_B8G8R8A8_TYPELESS,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
        auto source=resource(g.device.Get(),source_descriptor,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT64 bytes{};
        g.device->GetCopyableFootprints(&source_descriptor,0,1,0,&fp,nullptr,nullptr,&bytes);
        fp.Footprint.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
        auto up=resource(g.device.Get(),buffer(bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
        void* mapped{};check(up->Map(0,&no_reads,&mapped));
        for(UINT y=0;y<32;++y) for(UINT x=0;x<32;++x) {
            uint8_t* pixel=static_cast<uint8_t*>(mapped)+y*fp.Footprint.RowPitch+4*x;
            const uint8_t v=x>=frame.config.layout.fovea.width/2u ? 240u : 20u;
            pixel[0]=v;pixel[1]=v;pixel[2]=v;pixel[3]=255u;
        }
        up->Unmap(0,nullptr);
        D3D12_TEXTURE_COPY_LOCATION from{up.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};from.PlacedFootprint=fp;
        D3D12_TEXTURE_COPY_LOCATION to{source.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
        g.cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
        transition(g.cmd.Get(),source.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
        g.submit_and_wait();keep.push_back(up);keep.push_back(source);
        const auto savedPrimary=primary;
        const auto savedDepth=m1_depth;
        const auto savedJitterMode=frame.config.settings.m3_jitter_mode;
        const auto savedFineEnabled=frame.config.settings.m2_fovea_depth;
        const auto savedM25Mode=frame.config.settings.m25_fine_mode;
        const auto savedStereo=frame.config.settings.synthetic_stereo;
        const auto savedGeometry=m1_geometry.k;
        const auto savedFine=m21_fine_depth;
        using Vote=uevr::duoview::dx12::M1Resources::M3bAutoJitter;
        Vote::test_window_length.store(4u);
        primary=source;
        m1_geometry.k={.25f,-.25f};
        m21_fine_depth={};
        frame.config.settings.synthetic_stereo=true;
        frame.config.settings.m2_fovea_depth=false;
        frame.config.settings.m25_fine_mode=0u;
        const int centre=static_cast<int>((cu0+cu1)*16.f);
        for(const int expected_sign : {1,-1}) {
            const int step=centre+expected_sign;
            auto depth=upload_depth([&](UINT x){return int(x)>=step ? .45f : .15f;});
            m1_depth={depth.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{1.f/32.f,0.f},lease};
            frame.config.settings.m3_jitter_mode=0u;
            run(*a,false,Route::direct,"M3b jitter test: flush previous slot");
            (void)take();
            {
                std::scoped_lock lock(Vote::mutex);
                Vote::sign.store(1);
                Vote::frames=Vote::streak=0u;Vote::last_vote=99;
                Vote::scores[0]=Vote::scores[1]=Vote::scores[2]=0u;
                Vote::pixel_sum=0.0;
            }
            frame.config.settings.m3_jitter_mode=3u;
            for(int i=0;i<12;++i) run(*a,false,Route::direct,"M3b jitter test: measured Auto window");
            const int sign=Vote::sign.load();
            frame.config.settings.m3_jitter_mode=0u;
            run(*a,false,Route::direct,"M3b jitter test: retired readback");
            const auto scores=take();
            const uint64_t selected=expected_sign>0 ? scores[11] : scores[9];
            const uint64_t opposite=expected_sign>0 ? scores[9] : scores[11];
            if(sign!=expected_sign || selected<=scores[10] || selected<=opposite)
                throw std::runtime_error("M3b Auto jitter did not select the source-depth aligned sign on WARP");
        }
        Vote::test_window_length.store(120u);
        {
            std::scoped_lock lock(Vote::mutex);
            Vote::sign.store(1);Vote::frames=Vote::streak=0u;Vote::last_vote=99;
            Vote::scores[0]=Vote::scores[1]=Vote::scores[2]=0u;Vote::pixel_sum=0.0;
        }
        primary=savedPrimary;m1_depth=savedDepth;m21_fine_depth=savedFine;
        m1_geometry.k=savedGeometry;
        frame.config.settings.m3_jitter_mode=savedJitterMode;
        frame.config.settings.m2_fovea_depth=savedFineEnabled;
        frame.config.settings.m25_fine_mode=savedM25Mode;
        frame.config.settings.synthetic_stereo=savedStereo;
        std::cout<<"PASS: WARP M3b jitter Auto votes for both calibrated signs\n";
    }
'''
    s=s.replace(marker,block+marker)
    v.output.write_text(s,encoding="utf-8",newline="\n")
    print("Generated M3b P5 gate A/B WARP fixture")

if __name__=="__main__": main()

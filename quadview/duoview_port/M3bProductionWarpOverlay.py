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
    s=s.replace(marker,block+marker)
    v.output.write_text(s,encoding="utf-8",newline="\n")
    print("Generated M3b P5 gate A/B WARP fixture")

if __name__=="__main__": main()

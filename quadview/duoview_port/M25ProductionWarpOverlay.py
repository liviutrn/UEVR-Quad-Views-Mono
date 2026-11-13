#!/usr/bin/env python3
"""Extend the production D3D12 WARP M21 fixture with actual M2.5a GPU paths."""
from pathlib import Path
import argparse

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--source",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    args=a.parse_args()
    s=args.source.read_text(encoding="utf-8")
    marker="""    // Restore every touched field; the final legacy comparison is intended"""
    assert s.count(marker)==1, "M25 WARP insertion drifted"
    # The B40 contract checks red fovea + blue periphery. M2.5a debug modes
    # 2 and 3 intentionally replace those colors with a heatmap. Preserve
    # the legacy assertion for all other modes, including fine-OFF parity.
    # The remaining image hash, eye-coverage and D3D12 assertions stay active.
    legacy_color_check='if (px(16,16)[2]<220 || px(1,1)[0]<220)'
    if s.count(legacy_color_check)!=1:
        raise SystemExit("M25 legacy WARP color-check anchor drifted")
    s=s.replace(legacy_color_check,
                'if (frame.config.settings.m21_depth_debug < 2u && '
                '(px(16,16)[2]<220 || px(1,1)[0]<220))',1)
    block=r'''    // Real FXC + D3D12 WARP M2.5a smoke: with fine depth disabled, the
    // content-mode switch is NOT allowed to alter a single output pixel.
    primary=saved_primary;
    frame.config.settings.sharpen_wide=false;
    frame.config.settings.m2_unlinked_sharpen=false;
    frame.config.settings.m21_depth_debug=0u;
    frame.config.settings.m2_fovea_depth=false;
    frame.config.settings.m25_fine_mode=0u;
    m21_fine_depth={};
    run(*a,false,Route::direct,"M2.5a coarse-only strict source reference");
    const auto m25_coarse_hash=m21_image_hash;
    frame.config.settings.m25_fine_mode=1u;
    run(*a,false,Route::direct,"M2.5a mode=1 with fine OFF must match mode=0 bit exact");
    if(m25_coarse_hash!=m21_image_hash)
        throw std::runtime_error("M2.5a coarse-only shader output changed when fine mode=1");
    // Exercise tile analysis, full-frame veto and debug raster in the real
    // production pipeline. This fixture does NOT claim the synthetic images
    // are a physically valid pair: it proves the GPU gate actually runs.
    frame.config.settings.m2_fovea_depth=true;
    frame.config.settings.m21_depth_debug=2u;
    m21_fine_depth={fine_tex.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},
                    {},std::make_shared<const int>(1)};
    run(*a,false,Route::direct,"M2.5a tile agreement debug via WARP");
    if(!a->last_stereo_fovea_depth())
        throw std::runtime_error("M2.5a debug path did not bind fine depth");
    const auto m25_tile_hash=m21_image_hash;
    m21_fine_depth={};
    run(*a,false,Route::direct,"M2.5a fine absent: grey tile diagnostic");
    if(m25_tile_hash==m21_image_hash)
        throw std::runtime_error("M2.5a fine-weight GPU debug unchanged with valid fine input");
    std::cout<<"PASS: WARP M2.5a content GPU branch, debug weights and exact fine-off parity\n";
    frame.config.settings.m25_fine_mode=0u;
'''
    s=s.replace(marker,block+marker)
    args.output.write_text(s,encoding="utf-8",newline="\n")
    print("Generated production M2.5a D3D12 WARP fixture (real shader/root bindings)")

if __name__=="__main__":
    main()

#!/usr/bin/env python3
"""Extend the production D3D12 WARP fixture with M4 (full-resolution fovea depth).

Checks on the real compositor: M4 without fine depth changes nothing; with a thin
fine-only near bar the depth picture (debug 4) changes; M4 dispatches cleanly in
the normal image and together with M3a per-eye edges."""
from pathlib import Path
import argparse


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--source", type=Path, required=True)
    a.add_argument("--output", type=Path, required=True)
    args = a.parse_args()
    s = args.source.read_text(encoding="utf-8")
    marker = "    // Restore every touched field; the final legacy comparison is intended"
    assert s.count(marker) == 1, "M4 WARP insertion drifted"
    assert s.count("auto upload_depth=[&](auto value_at)") == 1, "M4 WARP needs the M3 depth uploader"
    block = r'''    // ---- M4 full-resolution fovea depth (lead build) ----
    {
        m1_geometry.k={.25f,-.25f};
        const auto saved_m4_depth=m1_depth;
        auto m4_flat=upload_depth([](UINT){ return .15f; });
        // Fine-only detail: a 3-texel near bar the shared grid pools away.
        auto m4_bar=upload_depth([](UINT x){ return (x>=14u && x<17u) ? .45f : .15f; });
        frame.config.settings.synthetic_stereo=true;
        frame.config.settings.m2_fovea_depth=true;
        frame.config.settings.m25_fine_mode=1u;
        frame.config.settings.m3_edges=false;
        frame.config.settings.m3_jitter_mode=0u;
        frame.config.settings.m21_depth_debug=4u;
        m1_depth={m4_flat.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
        m21_fine_depth={};
        frame.config.settings.m4_fovea_grid=false;
        run(*a,false,Route::direct,"M4 OFF, fine absent, depth picture");
        const auto m4_off_absent=m21_image_hash;
        frame.config.settings.m4_fovea_grid=true;
        run(*a,false,Route::direct,"M4 ON, fine absent, depth picture");
        if (m21_image_hash!=m4_off_absent) throw std::runtime_error("M4 changed the image without fine depth");
        m21_fine_depth={m4_bar.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
        frame.config.settings.m4_fovea_grid=false;
        run(*a,false,Route::direct,"M4 OFF, fine bar, depth picture");
        const auto m4_off_bar=m21_image_hash;
        frame.config.settings.m4_fovea_grid=true;
        run(*a,false,Route::direct,"M4 ON, fine bar, depth picture");
        if (!a->last_stereo_fovea_depth()) throw std::runtime_error("M4 fine depth not bound");
        if (m21_image_hash==m4_off_bar) throw std::runtime_error("M4 fovea field did not reach the depth picture");
        if (m21_image_hash==m4_off_absent) throw std::runtime_error("M4 depth picture ignores fine depth");
        frame.config.settings.m21_depth_debug=0u;
        run(*a,false,Route::direct,"M4 ON, fine bar, normal image");
        frame.config.settings.m3_edges=true;
        frame.config.settings.m3_fill=true;
        run(*a,false,Route::direct,"M4 ON + M3a per-eye edges");
        frame.config.settings.m3_edges=false;
        frame.config.settings.m4_fovea_grid=false;
        frame.config.settings.m2_fovea_depth=false;
        frame.config.settings.m25_fine_mode=0u;
        m21_fine_depth={};
        m1_depth=saved_m4_depth;
        std::cout<<"PASS: WARP M4 fovea-native depth field (OFF parity, fine detail reaches the field, ON dispatch)\n";
    }
'''
    s = s.replace(marker, block + marker)
    args.output.write_text(s, encoding="utf-8", newline="\n")
    print("Generated M4 WARP fixture")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Extend the production D3D12 WARP fixture with M4 (full-resolution fovea depth).

Checks on the real compositor: M4 without fine depth cannot record a frame; with a thin
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
        if (a->record_native(g.device.Get(),g.cmd.Get(),primary.Get(),secondary.Get(),stereo.Get(),
                D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,frame,lease,0,
                &m1_geometry,&m1_depth,nullptr) || a->recorded_commands())
            throw std::runtime_error("M4 recorded a scene without fine depth");
        if (a->record_native_gather(g.device.Get(),g.cmd.Get(),primary.Get(),secondary.Get(),stereo.Get(),
                D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,frame,lease,0) ||
                a->recorded_commands())
            throw std::runtime_error("M4 gather recorded a scene without fine depth");
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
        // Publish only the previous accepted WARP frame, then change both the
        // gaze crop and the head position before binding it on another slot.
        auto history=uevr::duoview::dx12::B40MonoHistory::create(g.device.Get(),g.queue.Get());
        if (!history) throw std::runtime_error("Fine depth history setup failed");
        a->set_b40_history(history);
        b->set_b40_history(history);
        m1_geometry.fine_depth_camera={{1.5f,.1f,1.2f,-.15f},{0,0,0,1},{0,0,0},1};
        run(*a,false,Route::direct,"Fine depth history starts with current fine depth");
        if (a->last_fine_depth_history_used()) throw std::runtime_error("First frame used unproven history");
        a->note_fine_depth_enqueued();
        const auto original_layout=frame.config.layout;
        frame.config.layout.u0+=.04f; frame.config.layout.u1+=.04f;
        m1_geometry.fine_depth_camera.position[0]=.02f;
        run(*b,false,Route::direct,"Fine depth history across slots, crop shift and head translation");
        if (!b->last_fine_depth_history_used()) throw std::runtime_error("Fine depth history was not bound");
        b->note_fine_depth_enqueued();
        frame.config.key.generation++;
        run(*a,false,Route::direct,"Fine depth history rejects previous generation");
        if (a->last_fine_depth_history_used()) throw std::runtime_error("Old generation leaked into fine depth");
        frame.config.key.generation--;
        frame.config.layout=original_layout;
        a->set_b40_history({});
        b->set_b40_history({});
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

#!/usr/bin/env python3
"""Goal D switch 1 WARP activation check (criterion C2) on the real production compositor.

Fine NGX depth 3200x40 with 1-texel near bars every 64 texels. The baseline 1024 field fits
3200 -> 1024 (stride 3.125, 2x2 near-max footprint), so it can miss thin bars; predicted
32/50 kept [sampling simulation, 2026-11-18]. The 4096 field is 1:1 and must keep 50/50, at
the exact fine positions, with finite non-negative values; the depth picture must differ.
Writes goald_grid_result.txt (CI copies it to evidence). Skipped in replay/capture runs."""
from pathlib import Path
import argparse


BLOCK = r'''    // ---- Goal D switch 1: fovea depth grid 1024 / 4096 (WARP activation, C2) ----
    // Runs only in the plain fixture run, never inside replay/capture processes
    // (their Off captures are compared byte-for-byte with the baseline).
    const bool gd_capture_run=[]{
        for (const char* v:{"DUOVIEW_RECON_REPLAY","DUOVIEW_RECON_LARGE","DUOVIEW_RECON_V3",
                            "DUOVIEW_RECON_QUALITY","DUOVIEW_EDGE_PROBE","DUOVIEW_EDGE_PROFILE"})
            if (const char* e=std::getenv(v); e && *e) return true;
        return false;
    }();
    if (!gd_capture_run) {
        const auto gd_saved_depth=m1_depth;
        const auto gd_saved_fine=m21_fine_depth;
        const auto gd_saved_settings=frame.config.settings;
        const auto gd_saved_k=m1_geometry.k;
        m1_geometry.k={.25f,-.25f};
        constexpr UINT GW=3200u, GH=40u, BAR_PERIOD=64u, BAR_FIRST=31u;
        auto gd_upload=[&](UINT w,UINT h,auto value_at) {
            const auto d=texture(w,h,DXGI_FORMAT_R32_TYPELESS,D3D12_RESOURCE_FLAG_NONE);
            auto tex=resource(g.device.Get(),d,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; UINT64 nb{};
            g.device->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&nb);
            fp.Footprint.Format=DXGI_FORMAT_R32_FLOAT;
            auto up=resource(g.device.Get(),buffer(nb),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
            void* m{}; check(up->Map(0,&no_reads,&m));
            for (UINT y=0;y<h;++y) {
                auto* r=reinterpret_cast<float*>(static_cast<uint8_t*>(m)+y*fp.Footprint.RowPitch);
                for (UINT x=0;x<w;++x) r[x]=value_at(x,y);
            }
            up->Unmap(0,nullptr);
            D3D12_TEXTURE_COPY_LOCATION from{up.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT}; from.PlacedFootprint=fp;
            D3D12_TEXTURE_COPY_LOCATION to{tex.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
            g.cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
            transition(g.cmd.Get(),tex.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE);
            g.submit_and_wait();
            keep.push_back(up); keep.push_back(tex);
            return tex;
        };
        // Row `row` of slice 0 of the M4 field the compositor used last frame.
        auto gd_field_row=[&](UINT row,UINT width) {
            ID3D12Resource* field=a->goald_m4_field();
            if (!field) throw std::runtime_error("GoalD: no M4 field");
            const auto fd=field->GetDesc();
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT ffp{}; UINT64 fbytes{};
            g.device->GetCopyableFootprints(&fd,0,1,0,&ffp,nullptr,nullptr,&fbytes);
            auto rb=resource(g.device.Get(),buffer(fbytes),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
            transition(g.cmd.Get(),field,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION src{field,D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
            D3D12_TEXTURE_COPY_LOCATION dst{rb.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT}; dst.PlacedFootprint=ffp;
            g.cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
            transition(g.cmd.Get(),field,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
            g.submit_and_wait();
            keep.push_back(rb);
            std::vector<float> out(width);
            void* fm{}; const D3D12_RANGE all{0,SIZE_T(fbytes)};
            check(rb->Map(0,&all,&fm));
            const auto* r=reinterpret_cast<const float*>(static_cast<const uint8_t*>(fm)+ffp.Offset+UINT64(row)*ffp.Footprint.RowPitch);
            for (UINT x=0;x<width;++x) out[x]=r[x];
            const D3D12_RANGE none{0,0}; rb->Unmap(0,&none);
            return out;
        };
        frame.config.settings.synthetic_stereo=true;
        frame.config.settings.m2_fovea_depth=true;
        frame.config.settings.m25_fine_mode=1u;
        frame.config.settings.m3_edges=false;
        frame.config.settings.m3_jitter_mode=0u;
        frame.config.settings.m4_fovea_grid=true;
        frame.config.settings.m8_distance=true;
        frame.config.settings.m8_edge_near=.5f;
        frame.config.settings.m8_edge_far=.5f;
        frame.config.settings.m8_fill_near=0.f;
        frame.config.settings.m8_fill_far=0.f;
        frame.config.settings.edge_reach_px=20.f; // Stereo V2 depth policy
        frame.config.settings.m21_depth_debug=4u;
        auto gd_flat=upload_depth([](UINT){ return .15f; });
        auto gd_bars=gd_upload(GW,GH,[](UINT x,UINT){ return (x%64u)==31u ? .45f : .15f; }); // BAR_PERIOD, BAR_FIRST
        m1_depth={gd_flat.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
        m21_fine_depth={gd_bars.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,GW,GH},{},lease};

        frame.config.settings.goald_depth_grid=1024u;
        run(*a,false,Route::direct,"GoalD grid 1024 (baseline), 3200-wide fine bars, depth picture");
        const auto gd_off_hash=m21_image_hash;
        if (a->goald_m4_hi_active() || a->goald_m4_columns()!=1024u)
            throw std::runtime_error("GoalD: 1024 setting did not keep the baseline 1024 M4 field");
        const UINT off_rows=a->goald_m4_rows();
        const auto off_row=gd_field_row(off_rows/2u,1024u);

        const uint64_t hi_before=uevr::duoview::dx12::M1Resources::goald_hi_frames.load();
        frame.config.settings.goald_depth_grid=4096u;
        run(*a,false,Route::direct,"GoalD grid 4096, 3200-wide fine bars, depth picture");
        const auto gd_on_hash=m21_image_hash;
        const uint32_t gd_status=uevr::duoview::duo_goald_status().load();
        if (!a->goald_m4_hi_active()) {
            std::cout<<"GoalD 4096 NOT ACTIVE reason="<<((gd_status>>2)&15u)<<"\n";
            throw std::runtime_error("GoalD: 4096 field not active");
        }
        if (a->goald_m4_columns()!=GW || a->goald_m4_rows()!=GH)
            throw std::runtime_error("GoalD: 4096 field is not 1:1 with the fine depth");
        const uint64_t hi_frames=uevr::duoview::dx12::M1Resources::goald_hi_frames.load()-hi_before;
        if (!hi_frames) throw std::runtime_error("GoalD: activation counter did not move");
        const auto fd=a->goald_m4_field()->GetDesc();
        if (fd.Width<GW || fd.Height<GH || fd.DepthOrArraySize!=1)
            throw std::runtime_error("GoalD: unexpected 4096 field allocation");
        const auto on_row=gd_field_row(GH/2u,GW);

        float lo=1.e9f, hi=-1.e9f;
        for (const float v:on_row) {
            if (!std::isfinite(v) || v<0.f) throw std::runtime_error("GoalD: 4096 field has NaN or negative depth");
            lo=(std::min)(lo,v); hi=(std::max)(hi,v);
        }
        for (const float v:off_row) if (!std::isfinite(v) || v<0.f) throw std::runtime_error("GoalD: 1024 field has NaN or negative depth");
        if (!(hi>lo)) throw std::runtime_error("GoalD: 4096 field row is flat");
        const float tol=1.e-5f*(std::max)(1.f,hi);
        UINT bars=0, kept_on=0, kept_off=0, exact_on=0;
        for (UINT b=BAR_FIRST;b<GW;b+=BAR_PERIOD) {
            ++bars;
            // 4096: 1:1, the 2x2 near-max seeds fine texel b at field texels b-1 and b.
            if ((std::max)(on_row[b-1u],on_row[b])>=hi-tol) ++kept_on;
            if (on_row[b]>=hi-tol && on_row[b+BAR_PERIOD/2u]<hi-tol) ++exact_on;
            // 1024: field texel of fine b is ~(b+.5)/3.125-.5; search +-2.
            const float f=(float(b)+.5f)*1024.f/float(GW)-.5f;
            const int c=int(std::lround(f));
            float peak=0.f;
            for (int x=(std::max)(0,c-2);x<=(std::min)(1023,c+2);++x) peak=(std::max)(peak,off_row[UINT(x)]);
            if (peak>=hi-tol) ++kept_off;
        }
        const bool image_differs=gd_on_hash!=gd_off_hash;
        std::ofstream("goald_grid_result.txt")
            <<"GOALD_GRID_RESULT,bars="<<bars<<",kept_1024="<<kept_off<<",kept_4096="<<kept_on
            <<",exact_4096="<<exact_on<<",field="<<fd.Width<<"x"<<fd.Height<<",active="<<GW<<"x"<<GH
            <<",hi_frames="<<hi_frames<<",depth_picture_differs="<<(image_differs?1:0)<<"\n";
        std::cout<<"GOALD_GRID_RESULT bars="<<bars<<" kept_1024="<<kept_off<<" kept_4096="<<kept_on
                 <<" exact_4096="<<exact_on<<" depth_picture_differs="<<(image_differs?1:0)<<"\n";
        if (kept_on!=bars || exact_on!=bars)
            throw std::runtime_error("GoalD: 4096 field lost or displaced a thin bar");
        if (kept_off>=bars)
            throw std::runtime_error("GoalD: fixture not sensitive (1024 field kept every bar)");
        if (!image_differs)
            throw std::runtime_error("GoalD: 4096 did not change the depth picture");

        frame.config.settings=gd_saved_settings;
        m1_depth=gd_saved_depth;
        m21_fine_depth=gd_saved_fine;
        m1_geometry.k=gd_saved_k;
        std::cout<<"PASS: WARP goal D fovea depth grid 4096 (activation, thin bars kept, Off field unchanged)\n";
    }
'''


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--source", type=Path, required=True)
    a.add_argument("--output", type=Path, required=True)
    args = a.parse_args()
    s = args.source.read_text(encoding="utf-8")
    marker = "    // Restore every touched field; the final legacy comparison is intended"
    assert s.count(marker) == 1, "goal D WARP insertion drifted"
    assert s.count("auto upload_depth=[&](auto value_at)") == 1, "goal D WARP needs the M3 depth uploader"
    assert s.count("PASS: WARP M4 fovea-native depth field") == 1, "goal D WARP must follow the M4 block"
    s = s.replace(marker, BLOCK + marker)
    if "#include <fstream>" not in s:
        s = "#include <fstream>\n#include <cmath>\n#include <vector>\n" + s
    args.output.write_text(s, encoding="utf-8", newline="\n")
    print("Generated goal D WARP fixture")


if __name__ == "__main__":
    main()

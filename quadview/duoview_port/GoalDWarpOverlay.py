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
        if (fd.Width<GW || fd.Height<GH || fd.DepthOrArraySize!=3)
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


JITTER_BLOCK = r'''    // ---- Goal D switch 2 groundwork: fine-depth jitter sign (WARP, 55_ F5) ----
    // Synthetic jittered fine depth, render convention R=+1 (fine texel k holds the scene at
    // k+.5+jitter). Field 1:1 (4096 setting). Mode 1 = shader offset +jitter (mode 0, the
    // production default, must equal it), mode 2 = -jitter. Under R=+1 mode 2 is aligned, so
    // its near mask must flicker less over 8 phases. Pre-registered CPU prediction
    // (workspace research/edge-fix/56_jitter/predict_fixture.py): x flicker mode1=952, mode2=430.
    // The y axis repeats the scene transposed. Proves what each mode does in the real
    // compositor; which R the game's NGX jitter uses is measured separately on real frames.
    if (!gd_capture_run) {
        const auto gj_saved_depth=m1_depth;
        const auto gj_saved_fine=m21_fine_depth;
        const auto gj_saved_settings=frame.config.settings;
        const auto gj_saved_k=m1_geometry.k;
        m1_geometry.k={.25f,-.25f};
        // Same Stereo V2 depth policy as the grid block (it restored the settings on exit).
        frame.config.settings.synthetic_stereo=true;
        frame.config.settings.m2_fovea_depth=true;
        frame.config.settings.m25_fine_mode=1u;
        frame.config.settings.m3_edges=false;
        frame.config.settings.m4_fovea_grid=true;
        frame.config.settings.m8_distance=true;
        frame.config.settings.m8_edge_near=.5f;
        frame.config.settings.m8_edge_far=.5f;
        frame.config.settings.m8_fill_near=0.f;
        frame.config.settings.m8_fill_far=0.f;
        frame.config.settings.edge_reach_px=20.f;
        frame.config.settings.m21_depth_debug=4u;
        constexpr UINT JL=1600u, JT=40u, JN=50u, JP=8u;
        float bar_x[JN], bar_w[JN];
        for (UINT i=0;i<JN;++i) {
            double ip=0.; const double fr=std::modf(double(i)*0.618034,&ip);
            bar_x[i]=float(20.0+31.0*double(i)+fr);
            bar_w[i]=(i%8u)==7u ? 12.f : .25f+.25f*float(i%6u);
        }
        float phase[JP];
        for (UINT i=0;i<JP;++i) { UINT n=i+1u; float f=1.f, r=0.f; while (n) { f*=.5f; r+=f*float(n%2u); n/=2u; } phase[i]=r-.5f; }
        auto gj_near=[&](float pos) { for (UINT i=0;i<JN;++i) if (pos>=bar_x[i] && pos<bar_x[i]+bar_w[i]) return true; return false; };
        auto gj_upload=[&](UINT w,UINT h,auto value_at) {
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
        // Whole slice 0 of the M4 field, row-major, cols x rows active texels.
        auto gj_field=[&](UINT cols,UINT rows) {
            ID3D12Resource* field=a->goald_m4_field();
            if (!field) throw std::runtime_error("GoalD jitter: no M4 field");
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
            std::vector<float> out(size_t(cols)*rows);
            void* fm{}; const D3D12_RANGE all{0,SIZE_T(fbytes)};
            check(rb->Map(0,&all,&fm));
            for (UINT y=0;y<rows;++y) {
                const auto* r=reinterpret_cast<const float*>(static_cast<const uint8_t*>(fm)+ffp.Offset+UINT64(y)*ffp.Footprint.RowPitch);
                for (UINT x=0;x<cols;++x) out[size_t(y)*cols+x]=r[x];
            }
            const D3D12_RANGE none{0,0}; rb->Unmap(0,&none);
            return out;
        };
        frame.config.settings.goald_depth_grid=4096u;
        auto gj_flat=upload_depth([](UINT){ return .15f; });
        m1_depth={gj_flat.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
        // Near mask along the test axis (middle line) for one phase.
        auto gj_frame=[&](bool vertical,UINT mode,float jp) {
            const UINT W=vertical ? JT : JL, H=vertical ? JL : JT;
            auto tex=gj_upload(W,H,[&](UINT x,UINT y){ return gj_near(float(vertical ? y : x)+.5f+jp) ? .45f : .15f; });
            const std::array<float,2> jit{vertical ? 0.f : jp/float(JL), vertical ? jp/float(JL) : 0.f};
            m21_fine_depth={tex.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,W,H},jit,lease};
            frame.config.settings.m3_jitter_mode=mode;
            run(*a,false,Route::direct,vertical ? "GoalD jitter sign, y axis" : "GoalD jitter sign, x axis");
            if (!a->goald_m4_hi_active() || a->goald_m4_columns()!=W || a->goald_m4_rows()!=H)
                throw std::runtime_error("GoalD jitter: field not 1:1 with the fine depth");
            const auto f=gj_field(W,H);
            float hi=-1.e9f;
            for (const float v:f) {
                if (!std::isfinite(v) || v<0.f) throw std::runtime_error("GoalD jitter: NaN or negative depth");
                hi=(std::max)(hi,v);
            }
            const float tol=1.e-5f*(std::max)(1.f,hi);
            std::vector<uint8_t> mask(JL);
            for (UINT t=0;t<JL;++t) mask[t]=(vertical ? f[size_t(t)*W+W/2u] : f[size_t(H/2u)*W+t])>=hi-tol;
            return mask;
        };
        // CPU model of the seed: 2x2 near-max at floor(c+.5+s*jp-.5), clamped.
        auto gj_cpu=[&](int s,float jp) {
            std::vector<uint8_t> fine(JL), mask(JL);
            for (UINT k=0;k<JL;++k) fine[k]=gj_near(float(k)+.5f+jp);
            for (UINT c=0;c<JL;++c) {
                const int i0=(std::min)((std::max)(int(std::floor(float(c)+float(s)*jp)),0),int(JL)-2);
                mask[c]=fine[size_t(i0)]|fine[size_t(i0)+1u];
            }
            return mask;
        };
        UINT flick[2][3]{}, cpu_match[2][3]{}, mode0_diff=0u, mode12_diff=0u;
        for (UINT axis=0;axis<2u;++axis) {
            for (UINT mode=0;mode<3u;++mode) {
                if (axis==1u && mode==0u) continue;
                std::vector<std::vector<uint8_t>> m;
                for (UINT p=0;p<JP;++p) m.push_back(gj_frame(axis==1u,mode,phase[p]));
                for (UINT p=0;p<JP;++p) {
                    const auto ref=gj_cpu(mode==2u ? -1 : 1,phase[p]);
                    for (UINT t=0;t<JL;++t) {
                        flick[axis][mode]+=m[p][t]!=m[(p+1u)%JP][t] ? 1u : 0u;
                        cpu_match[axis][mode]+=m[p][t]==ref[t] ? 1u : 0u;
                    }
                }
            }
        }
        UINT neg_vs_m1=0u, neg_vs_m2=0u;
        {   // Same phase: production default (mode 0) vs mode 1, and mode 1 vs mode 2.
            const auto m0=gj_frame(false,0u,phase[1]), m1=gj_frame(false,1u,phase[1]), m2=gj_frame(false,2u,phase[1]);
            for (UINT t=0;t<JL;++t) { mode0_diff+=m0[t]!=m1[t] ? 1u : 0u; mode12_diff+=m1[t]!=m2[t] ? 1u : 0u; }
            // The NEW menu switch (goald_jitter_negative) itself: mode 1 + flipped must equal mode 2.
            frame.config.settings.goald_jitter_negative=1u;
            const auto mn=gj_frame(false,1u,phase[1]);
            frame.config.settings.goald_jitter_negative=0u;
            for (UINT t=0;t<JL;++t) { neg_vs_m1+=mn[t]!=m1[t] ? 1u : 0u; neg_vs_m2+=mn[t]!=m2[t] ? 1u : 0u; }
        }
        const UINT total=JL*JP;
        std::ofstream("goald_jitter_result.txt")
            <<"GOALD_JITTER_RESULT,R=+1,flicker_x_mode0="<<flick[0][0]<<",flicker_x_mode1="<<flick[0][1]
            <<",flicker_x_mode2="<<flick[0][2]<<",flicker_y_mode1="<<flick[1][1]<<",flicker_y_mode2="<<flick[1][2]
            <<",cpu_match_x="<<cpu_match[0][1]<<"/"<<cpu_match[0][2]<<",cpu_match_y="<<cpu_match[1][1]<<"/"<<cpu_match[1][2]
            <<",of="<<total<<",mode0_vs_mode1_diff="<<mode0_diff<<",mode1_vs_mode2_diff="<<mode12_diff
            <<",predicted_x=952/430,switch_neg_vs_mode1="<<neg_vs_m1<<",switch_neg_vs_mode2="<<neg_vs_m2<<"\n";
        std::cout<<"GOALD_JITTER_RESULT x: mode0="<<flick[0][0]<<" mode1="<<flick[0][1]<<" mode2="<<flick[0][2]
                 <<" y: mode1="<<flick[1][1]<<" mode2="<<flick[1][2]<<" cpu_match_x="<<cpu_match[0][1]<<"/"<<cpu_match[0][2]
                 <<" of "<<total<<" mode0_vs_mode1_diff="<<mode0_diff<<" mode1_vs_mode2_diff="<<mode12_diff<<"\n";
        if (!mode12_diff) throw std::runtime_error("GoalD jitter: sign does not reach the fovea depth field");
        if (mode0_diff) throw std::runtime_error("GoalD jitter: production default differs from the + offset");
        if (!neg_vs_m1 || neg_vs_m2) throw std::runtime_error("GoalD jitter: the jitter direction menu switch does not flip the sign");
        if (!(flick[0][2]*3u<flick[0][1]*2u) || !(flick[1][2]*3u<flick[1][1]*2u))
            throw std::runtime_error("GoalD jitter: aligned mode not clearly more stable (fixture insensitive)");
        // ---- Goal D switch 2: fovea depth history, static camera, production jitter mode 0.
        // 3 rounds x 8 phases (round 0 = warm-up). ON must activate (valid frames, counters)
        // and keep thin bars (< 1.5 texel) in more frames than OFF.
        {
            const auto gh_saved_cam=m1_geometry.fine_depth_camera;
            m1_geometry.fine_depth_camera={{1.f,0.f,1.f,0.f},{0.f,0.f,0.f,1.f},{0.f,0.f,0.f},1.f};
            UINT thin=0u;
            for (UINT i=0;i<JN;++i) thin+=bar_w[i]<1.5f ? 1u : 0u;
            auto gh_kept=[&](UINT mode) { // 0 off, 1 all fovea depth, 2 thin objects only
                frame.config.settings.goald_history=mode;
                UINT present=0u;
                for (UINT round=0;round<3u;++round) for (UINT p=0;p<JP;++p) {
                    const auto m=gj_frame(false,0u,phase[p]);
                    if (round==0u) continue;
                    for (UINT i=0;i<JN;++i) {
                        if (!(bar_w[i]<1.5f)) continue;
                        const int c0=int(std::floor(bar_x[i]));
                        bool any=false;
                        for (int c=c0-1;c<=c0+2;++c) if (c>=0 && c<int(JL) && m[size_t(c)]) any=true;
                        present+=any ? 1u : 0u;
                    }
                }
                return present;
            };
            const uint64_t gh_valid0=uevr::duoview::dx12::M1Resources::goald_hist_valid_frames.load();
            const UINT gh_off=gh_kept(0u);
            const UINT gh_on=gh_kept(1u);
            const uint64_t gh_valid=uevr::duoview::dx12::M1Resources::goald_hist_valid_frames.load()-gh_valid0;
            const uint32_t gh_status=uevr::duoview::duo_goald_history().load();
            const UINT gh_total=thin*2u*JP;
            std::ofstream("goald_history_result.txt")
                <<"GOALD_HISTORY_RESULT,thin_bar_frames="<<gh_total<<",kept_off="<<gh_off<<",kept_on="<<gh_on
                <<",valid_frames="<<gh_valid<<",status=0x"<<std::hex<<gh_status<<std::dec
                <<",from_history_permille="<<((gh_status>>8)&1023u)<<"\n";
            std::cout<<"GOALD_HISTORY_RESULT thin bar-frames="<<gh_total<<" kept off="<<gh_off<<" on="<<gh_on
                     <<" valid_frames="<<gh_valid<<" reason="<<((gh_status>>2)&15u)<<"\n";
            // Moving WIDE object, static camera (review #368: trails). A 24-texel slab
            // moves 4 texels per frame; ON must not keep it where it was (near texels
            // on the middle row must equal OFF after 6 frames).
            auto gm_near=[&](UINT mode) {
                frame.config.settings.goald_history=mode;
                frame.config.settings.m3_jitter_mode=0u;
                UINT count=0u;
                for (UINT f=0;f<6u;++f) {
                    const float x0=400.f+4.f*float(f);
                    auto tex=gj_upload(JL,JT,[&](UINT x,UINT){ const float p=float(x)+.5f; return (p>=x0 && p<x0+24.f) ? .45f : .15f; });
                    m21_fine_depth={tex.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,JL,JT},{0.f,0.f},lease};
                    run(*a,false,Route::direct,"GoalD history, moving wide object");
                    const auto fv=gj_field(JL,JT);
                    float hi=-1.e9f;
                    for (const float v:fv) hi=(std::max)(hi,v);
                    const float tol=1.e-5f*(std::max)(1.f,hi);
                    count=0u;
                    for (UINT t=0;t<JL;++t) count+=fv[size_t(JT/2u)*JL+t]>=hi-tol ? 1u : 0u;
                }
                return count;
            };
            const UINT gh_thin=gh_kept(2u);
            const UINT gm_off=gm_near(0u), gm_on=gm_near(1u), gm_thin=gm_near(2u);
            std::ofstream("goald_history_result.txt",std::ios::app)
                <<"GOALD_HISTORY_THIN_ONLY,kept_thin="<<gh_thin<<"\n"
                <<"GOALD_HISTORY_MOVING,near_texels_off="<<gm_off<<",near_texels_all="<<gm_on<<",near_texels_thin="<<gm_thin<<"\n";
            std::cout<<"GOALD_HISTORY_MOVING near texels off="<<gm_off<<" all="<<gm_on<<" thin="<<gm_thin
                     <<" kept_thin="<<gh_thin<<"\n";
            frame.config.settings.goald_history=0u;
            m1_geometry.fine_depth_camera=gh_saved_cam;
            if (!(gh_status&2u) || !gh_valid) throw std::runtime_error("GoalD history: not active / never valid");
            if (!(gh_on>gh_off)) throw std::runtime_error("GoalD history (all): does not keep more thin bars than OFF");
            if (!(gh_thin>gh_off)) throw std::runtime_error("GoalD history (thin only): does not keep more thin bars than OFF");
            // All-depth trail is expected by design (recorded only); thin-only must leave none.
            if (gm_thin>gm_off) throw std::runtime_error("GoalD history (thin only): moving wide object leaves a trail");
            std::cout<<"PASS: WARP goal D fovea depth history keeps thin bars, no trail behind a moving object\n";
        }
        frame.config.settings=gj_saved_settings;
        m1_depth=gj_saved_depth;
        m21_fine_depth=gj_saved_fine;
        m1_geometry.k=gj_saved_k;
        std::cout<<"PASS: WARP goal D jitter sign (mode 2 aligned under R=+1; default = mode 1)\n";
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
    s = s.replace(marker, BLOCK + JITTER_BLOCK + marker)
    if "#include <fstream>" not in s:
        s = "#include <fstream>\n#include <cmath>\n#include <vector>\n" + s
    args.output.write_text(s, encoding="utf-8", newline="\n")
    print("Generated goal D WARP fixture")


if __name__ == "__main__":
    main()

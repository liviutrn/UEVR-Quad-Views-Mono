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
        // 62_: synthetic DLSS motion vectors (R32G32_FLOAT, previous = current + mv).
        ID3D12Resource* gj_mv=nullptr; // attached to every goal D fine depth while set
        auto gj_upload_mv=[&](UINT w,UINT h,auto mv_at) {
            const auto d=texture(w,h,DXGI_FORMAT_R32G32_FLOAT,D3D12_RESOURCE_FLAG_NONE);
            auto tex=resource(g.device.Get(),d,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; UINT64 nb{};
            g.device->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&nb);
            auto up=resource(g.device.Get(),buffer(nb),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
            void* m{}; check(up->Map(0,&no_reads,&m));
            for (UINT y=0;y<h;++y) {
                auto* r=reinterpret_cast<float*>(static_cast<uint8_t*>(m)+y*fp.Footprint.RowPitch);
                for (UINT x=0;x<w;++x) { const std::array<float,2> v=mv_at(x,y); r[2*x]=v[0]; r[2*x+1]=v[1]; }
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
        auto gj_attach_mv=[&]{ m21_fine_depth.mv=gj_mv; m21_fine_depth.mv_format=DXGI_FORMAT_R32G32_FLOAT; m21_fine_depth.mv_scale={1.f,1.f}; };
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
            gj_attach_mv();
            frame.config.settings.m3_jitter_mode=mode;
            run(*a,false,Route::direct,vertical ? "GoalD jitter sign, y axis" : "GoalD jitter sign, x axis");
            // The XR caller reports a submitted list; goal D history commits only there (review #372 R1).
            if (frame.config.settings.goald_history) a->note_fine_depth_enqueued();
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
            frame.config.settings.goald_motion_source=0u; // head-pose mode first (pre-#376 results unchanged)
            UINT thin=0u;
            for (UINT i=0;i<JN;++i) thin+=bar_w[i]<1.5f ? 1u : 0u;
            auto gh_kept=[&](UINT mode) { // 0 off, 1 on (all fovea depth; Thin removed after #373)
                frame.config.settings.goald_history=mode;
                frame.config.settings.goald_confirm_texels=0u; // confirm gate measured separately below
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
            auto gm_near=[&](UINT mode,UINT confirm) {
                frame.config.settings.goald_history=mode;
                frame.config.settings.goald_confirm_texels=confirm;
                frame.config.settings.m3_jitter_mode=0u;
                UINT count=0u;
                for (UINT f=0;f<6u;++f) {
                    const float x0=400.f+4.f*float(f);
                    auto tex=gj_upload(JL,JT,[&](UINT x,UINT){ const float p=float(x)+.5f; return (p>=x0 && p<x0+24.f) ? .45f : .15f; });
                    m21_fine_depth={tex.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,JL,JT},{0.f,0.f},lease};
                    if (frame.config.settings.goald_motion_source) { // 62_: the slab's own motion
                        gj_mv=gj_upload_mv(JL,JT,[&](UINT x,UINT){ const float p=float(x)+.5f;
                            return (p>=x0 && p<x0+24.f) ? std::array<float,2>{-4.f,0.f} : std::array<float,2>{0.f,0.f}; }).Get();
                        gj_attach_mv();
                    }
                    run(*a,false,Route::direct,"GoalD history, moving wide object");
                    if (mode) a->note_fine_depth_enqueued(); // submitted (history commit, R1)
                    const auto fv=gj_field(JL,JT);
                    float hi=-1.e9f;
                    for (const float v:fv) hi=(std::max)(hi,v);
                    const float tol=1.e-5f*(std::max)(1.f,hi);
                    count=0u;
                    for (UINT t=0;t<JL;++t) count+=fv[size_t(JT/2u)*JL+t]>=hi-tol ? 1u : 0u;
                }
                return count;
            };
            const UINT gm_off=gm_near(0u,0u), gm_on=gm_near(1u,0u), gm_c2=gm_near(1u,2u);
            std::ofstream("goald_history_result.txt",std::ios::app)
                <<"GOALD_HISTORY_MOVING,near_texels_off="<<gm_off<<",near_texels_all="<<gm_on<<",near_texels_confirm2="<<gm_c2<<"\n";
            std::cout<<"GOALD_HISTORY_MOVING near texels off="<<gm_off<<" all="<<gm_on<<" confirm2="<<gm_c2<<"\n";
            // Confirm gate (#373 trails behind hands / moving objects): at most ~2 texels of trail.
            if (gm_c2>gm_off+3u) throw std::runtime_error("GoalD history confirm gate: moving object still leaves a trail");
            frame.config.settings.goald_confirm_texels=2u; // production default for the gate/F1/F2 checks
            // ---- #373 head-still gate + review #373 F1/F2. Observable: valid history frames
            // (committed frames that USED history). Static bars, production jitter mode 0.
            frame.config.settings.goald_history=1u;
            frame.config.settings.m3_jitter_mode=0u;
            auto gs_frame=[&](uevr::duoview::dx12::Compositor& c,float yaw,bool submit,const char* name) {
                auto tex=gj_upload(JL,JT,[&](UINT x,UINT){ return gj_near(float(x)+.5f) ? .45f : .15f; });
                m21_fine_depth={tex.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,JL,JT},{0.f,0.f},lease};
                m1_geometry.fine_depth_camera.orientation={0.f,std::sin(.5f*yaw),0.f,std::cos(.5f*yaw)};
                run(c,false,Route::direct,name);
                if (submit) c.note_fine_depth_enqueued();
            };
            auto gs_valid=[]{ return uevr::duoview::dx12::M1Resources::goald_hist_valid_frames.load(); };
            auto gs_moving=[]{ return uevr::duoview::dx12::M1Resources::goald_hist_moving_frames.load(); };
            gs_frame(*a,0.f,true,"GoalD gate warm-up 1");
            gs_frame(*a,0.f,true,"GoalD gate warm-up 2");
            uint64_t v=gs_valid(), mv=gs_moving();
            gs_frame(*a,1.e-5f,true,"GoalD gate: head still (tiny yaw)");
            const uint64_t still_valid=gs_valid()-v;
            v=gs_valid(); mv=gs_moving();
            gs_frame(*a,.05f,true,"GoalD gate: head turning (yaw .05 rad in one frame)");
            const uint64_t turn_valid=gs_valid()-v, turn_moving=gs_moving()-mv;
            v=gs_valid();
            gs_frame(*a,.05f,true,"GoalD gate: still again");
            const uint64_t again_valid=gs_valid()-v;
            // F2 (M1 side): a recorded list that was never submitted must not leave reusable history.
            gs_frame(*a,.05f,false,"GoalD F2: recorded, not submitted");
            v=gs_valid();
            gs_frame(*a,.05f,true,"GoalD F2: next frame");
            const uint64_t f2_valid=gs_valid()-v;
            gs_frame(*a,.05f,true,"GoalD F2: recovered");
            // F1: slot A records, slot B records, B submitted, then the OLDER A submitted -> drop.
            gs_frame(*a,.05f,false,"GoalD F1: record slot A");
            gs_frame(*b,.05f,false,"GoalD F1: record slot B");
            b->note_fine_depth_enqueued();
            a->note_fine_depth_enqueued();
            v=gs_valid();
            gs_frame(*a,.05f,true,"GoalD F1: next frame");
            const uint64_t f1_valid=gs_valid()-v;
            v=gs_valid();
            gs_frame(*a,.05f,true,"GoalD F1: recovered");
            const uint64_t f1_recovered=gs_valid()-v;
            std::ofstream("goald_history_result.txt",std::ios::app)
                <<"GOALD_HISTORY_GATE,still_valid="<<still_valid<<",turn_valid="<<turn_valid<<",turn_moving="<<turn_moving
                <<",again_valid="<<again_valid<<",f2_valid="<<f2_valid<<",f1_valid="<<f1_valid<<",f1_recovered="<<f1_recovered
                <<",expected=1/0/1/1/0/0/1\n";
            std::cout<<"GOALD_HISTORY_GATE still="<<still_valid<<" turn="<<turn_valid<<"/moving "<<turn_moving
                     <<" again="<<again_valid<<" f2="<<f2_valid<<" f1="<<f1_valid<<" f1_recovered="<<f1_recovered<<"\n";
            m1_geometry.fine_depth_camera.orientation={0.f,0.f,0.f,1.f};
            // ---- 62_ motion-vector history (pre-registered in research/edge-fix/62_).
            // (a) thin bars, static scene, zero MVs: kept_mv > kept_off.
            frame.config.settings.goald_motion_source=1u;
            gj_mv=gj_upload_mv(JL,JT,[](UINT,UINT){ return std::array<float,2>{0.f,0.f}; }).Get();
            const uint64_t mvf0=uevr::duoview::dx12::M1Resources::goald_mv_frames.load();
            const UINT mv_kept=gh_kept(1u);
            const uint64_t mv_frames=uevr::duoview::dx12::M1Resources::goald_mv_frames.load()-mvf0;
            const uint32_t mv_status=uevr::duoview::duo_goald_motion().load();
            // (b) moving slab with its own MVs, confirm gate Off: no trail (within 1 texel of Off).
            const UINT mv_slab=gm_near(1u,0u);
            // (c) panning scene (camera-yaw-like): every bar moves 3.37 texels/frame, uniform MVs,
            // no head-still gate in MV mode. Thin bars kept in more frames than Off.
            auto pan_kept=[&](UINT mode) {
                frame.config.settings.goald_history=mode;
                frame.config.settings.goald_confirm_texels=0u;
                frame.config.settings.m3_jitter_mode=0u;
                gj_mv=gj_upload_mv(JL,JT,[](UINT,UINT){ return std::array<float,2>{-3.37f,0.f}; }).Get();
                UINT present=0u;
                for (UINT f=0;f<24u;++f) {
                    const float shift=3.37f*float(f);
                    auto tex=gj_upload(JL,JT,[&](UINT x,UINT){ return gj_near(float(x)+.5f-shift) ? .45f : .15f; });
                    m21_fine_depth={tex.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,JL,JT},{0.f,0.f},lease};
                    gj_attach_mv();
                    run(*a,false,Route::direct,"GoalD MV history, panning scene");
                    if (mode) a->note_fine_depth_enqueued();
                    if (f<8u) continue; // warm-up
                    const auto fv=gj_field(JL,JT);
                    float hi=-1.e9f;
                    for (const float v:fv) hi=(std::max)(hi,v);
                    const float tol=1.e-5f*(std::max)(1.f,hi);
                    for (UINT i=0;i<JN;++i) {
                        if (!(bar_w[i]<1.5f)) continue;
                        const int c0=int(std::floor(bar_x[i]+shift));
                        if (c0<1 || c0+2>=int(JL)) continue;
                        bool any=false;
                        for (int c=c0-1;c<=c0+2;++c) if (fv[size_t(JT/2u)*JL+size_t(c)]>=hi-tol) any=true;
                        present+=any ? 1u : 0u;
                    }
                }
                return present;
            };
            const UINT pan_off=pan_kept(0u), pan_mv=pan_kept(1u);
            // (d) MV requested but the fine depth has none: head-pose fallback, counted.
            gj_mv=nullptr;
            const uint64_t fb0=uevr::duoview::dx12::M1Resources::goald_mv_fallback_frames.load();
            gs_frame(*a,0.f,true,"GoalD MV fallback: no motion vectors");
            const uint64_t mv_fallback=uevr::duoview::dx12::M1Resources::goald_mv_fallback_frames.load()-fb0;
            const bool fallback_pose=!(uevr::duoview::duo_goald_motion().load()&1u);
            frame.config.settings.goald_motion_source=0u;
            std::ofstream("goald_history_result.txt",std::ios::app)
                <<"GOALD_HISTORY_MV,kept_off="<<gh_off<<",kept_mv="<<mv_kept<<",mv_frames="<<mv_frames
                <<",near_texels_off="<<gm_off<<",near_texels_mv="<<mv_slab
                <<",pan_kept_off="<<pan_off<<",pan_kept_mv="<<pan_mv
                <<",fallback_frames="<<mv_fallback<<",fallback_pose="<<(fallback_pose?1:0)<<"\n";
            std::cout<<"GOALD_HISTORY_MV kept off="<<gh_off<<" mv="<<mv_kept<<" frames="<<mv_frames
                     <<" slab off="<<gm_off<<" mv="<<mv_slab<<" pan off="<<pan_off<<" mv="<<pan_mv
                     <<" fallback="<<mv_fallback<<"/"<<fallback_pose<<"\n";
            if (!mv_frames || !(mv_status&1u)) throw std::runtime_error("GoalD MV history: motion vectors never active");
            if (!(mv_kept>gh_off)) throw std::runtime_error("GoalD MV history: does not keep more thin bars than OFF");
            if (mv_slab>gm_off+1u) throw std::runtime_error("GoalD MV history: moving object leaves a trail");
            if (!(pan_mv>pan_off)) throw std::runtime_error("GoalD MV history: no gain on a panning scene");
            if (mv_fallback!=1u || !fallback_pose) throw std::runtime_error("GoalD MV history: missing MVs did not fall back to head pose");
            frame.config.settings.goald_history=0u;
            m1_geometry.fine_depth_camera=gh_saved_cam;
            if (!(gh_status&2u) || !gh_valid) throw std::runtime_error("GoalD history: not active / never valid");
            if (!(gh_on>gh_off)) throw std::runtime_error("GoalD history (all): does not keep more thin bars than OFF");
            // All-depth trail behind an object moving on its own is expected by design (recorded only).
            if (still_valid!=1u || again_valid!=1u || f1_recovered!=1u)
                throw std::runtime_error("GoalD history: not used while the head is still");
            if (turn_valid!=0u || turn_moving!=1u)
                throw std::runtime_error("GoalD history: used while the head turns (#373 lag)");
            if (f2_valid!=0u) throw std::runtime_error("GoalD history: unsubmitted frame reused (review #373 F2)");
            if (f1_valid!=0u) throw std::runtime_error("GoalD history: older slot submitted last was committed (review #373 F1)");
            std::cout<<"PASS: WARP goal D fovea depth history keeps thin bars, head-still gate, F1/F2 drops, MV mode (62_)\n";
        }
        frame.config.settings=gj_saved_settings;
        m1_depth=gj_saved_depth;
        m21_fine_depth=gj_saved_fine;
        m1_geometry.k=gj_saved_k;
        std::cout<<"PASS: WARP goal D jitter sign (mode 2 aligned under R=+1; default = mode 1)\n";
    }
'''

HYBRID_BLOCK = r'''    // ---- Goal D Fill=4 (Study 93 #6 Tight B+C2+3): WARP activation & push-pull check ----
    if (!gd_capture_run) {
        const auto ghb_saved_depth=m1_depth;
        const auto ghb_saved_fine=m21_fine_depth;
        const auto ghb_saved_settings=frame.config.settings;
        const auto ghb_saved_k=m1_geometry.k;
        m1_geometry.k={.06f,-.06f};
        constexpr UINT HW=256u, HH=144u;
        auto ghb_upload=[&](auto value_at) {
            const auto d=texture(HW,HH,DXGI_FORMAT_R32_TYPELESS,D3D12_RESOURCE_FLAG_NONE);
            auto tex=resource(g.device.Get(),d,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; UINT64 nb{};
            g.device->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&nb);
            fp.Footprint.Format=DXGI_FORMAT_R32_FLOAT;
            auto up=resource(g.device.Get(),buffer(nb),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
            void* m{}; check(up->Map(0,&no_reads,&m));
            for (UINT y=0;y<HH;++y) {
                auto* r=reinterpret_cast<float*>(static_cast<uint8_t*>(m)+y*fp.Footprint.RowPitch);
                for (UINT x=0;x<HW;++x) r[x]=value_at(x,y);
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
        // Slanted 3D-like near foreground (0.35 m -> d=2.85, tapering to 0.70 m -> d=1.43) over 6 m wall (d=0.167).
        auto ghb_near=ghb_upload([](UINT x,UINT y){
            const UINT edge=110u+y/3u;
            if (x>=edge && x<edge+48u && y>=24u && y<HH-20u)
                return 1.43f+1.42f*(float(y)/float(HH));
            return 1.f/6.f;
        });
        auto ghb_far=ghb_upload([](UINT,UINT){ return 1.f/12.f; });
        frame.config.settings.synthetic_stereo=true;
        frame.config.settings.m2_fovea_depth=true;
        frame.config.settings.m25_fine_mode=1u;
        frame.config.settings.m3_edges=false;
        frame.config.settings.m3_jitter_mode=0u;
        frame.config.settings.m4_fovea_grid=true;
        frame.config.settings.m8_distance=true;
        frame.config.settings.m8_edge_near=0.f;
        frame.config.settings.m8_edge_far=.5f;
        frame.config.settings.m8_fill_near=0.f;
        frame.config.settings.m8_fill_far=0.f;
        frame.config.settings.edge_reach_px=20.f;
        frame.config.settings.stereo_near_m=.512f; // #379 near knee -> CAP=3.91 so 0.35..0.70 m weapon isn't clipped
        frame.config.settings.m21_depth_debug=0u; // real stereo colour output!
        frame.config.settings.goald_history=0u;
        frame.config.settings.goald_depth_grid=4096u;
        frame.config.settings.goald_halo_near_m=4.f;
        frame.config.settings.goald_halo_fade_m=8.f;
        frame.config.settings.goald_hybrid_detail=.70f;
        frame.config.settings.goald_hybrid_gate=.11f;
        frame.config.settings.goald_hybrid_outline=.50f;
        frame.config.settings.goald_hybrid_shift=1.f;

        m1_depth={ghb_near.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,HW,HH},{},lease};
        m21_fine_depth={ghb_near.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,HW,HH},{},lease};
        frame.config.settings.goald_fill=0u;
        run(*a,false,Route::direct,"GoalD Fill=4 WARP: Off baseline colour");
        const auto ghb_off_hash=m21_image_hash;

        frame.config.settings.goald_fill=4u;
        frame.config.settings.goald_hybrid_tap_mode=0u; // #6 Best-Match Hybrid
        run(*a,false,Route::direct,"GoalD Fill=4 WARP: #6 Tight B+C2+3 hybrid");
        const bool hyb_on=a->goald_hybrid_active();
        const uint32_t pp_w=a->goald_pp_w(), pp_mips=a->goald_pp_mips();
        const auto ghb_m0_hash=m21_image_hash;

        frame.config.settings.goald_hybrid_tap_mode=1u; // #5 Vertical-First
        run(*a,false,Route::direct,"GoalD Fill=4 WARP: #5 Vertical-First");
        const auto ghb_m1_hash=m21_image_hash;

        frame.config.settings.goald_hybrid_tap_mode=2u; // #4 Horizontal-Only
        run(*a,false,Route::direct,"GoalD Fill=4 WARP: #4 Horizontal-Only");
        const auto ghb_m2_hash=m21_image_hash;

        frame.config.settings.goald_hybrid_tap_mode=3u; // Smooth Blur Only (Cand C)
        run(*a,false,Route::direct,"GoalD Fill=4 WARP: Cand C Smooth Blur");
        const auto ghb_m3_hash=m21_image_hash;

        // Distant >OFF_M (12 m > 8 m) flat scene must match Off bit-for-bit.
        m1_depth={ghb_far.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,HW,HH},{},lease};
        m21_fine_depth={ghb_far.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,HW,HH},{},lease};
        frame.config.settings.goald_fill=0u;
        run(*a,false,Route::direct,"GoalD Fill=4 WARP: distant >8m Off");
        const auto ghb_far_off=m21_image_hash;
        frame.config.settings.goald_fill=4u;
        frame.config.settings.goald_hybrid_tap_mode=0u;
        run(*a,false,Route::direct,"GoalD Fill=4 WARP: distant >8m Fill=4");
        const auto ghb_far_hyb=m21_image_hash;

        std::ofstream("goald_hybrid_result.txt")
            <<"GOALD_HYBRID,active="<<(hyb_on?1:0)<<",pp_w="<<pp_w<<",pp_mips="<<pp_mips
            <<",off_hash="<<ghb_off_hash<<",m0_hash="<<ghb_m0_hash<<",m1_hash="<<ghb_m1_hash
            <<",m2_hash="<<ghb_m2_hash<<",m3_hash="<<ghb_m3_hash
            <<",far_match="<<(ghb_far_off==ghb_far_hyb?1:0)<<"\n";
        std::cout<<"GOALD_HYBRID active="<<(hyb_on?1:0)<<" pp="<<pp_w<<" mips="<<pp_mips
                 <<" m0!=off:"<<(ghb_m0_hash!=ghb_off_hash)<<" far_match:"<<(ghb_far_off==ghb_far_hyb)<<"\n";
        if (!hyb_on || pp_w==0u || pp_mips<2u)
            throw std::runtime_error("GoalD Fill=4 hybrid did not activate push-pull pyramid");
        if (ghb_m0_hash==ghb_off_hash || ghb_m3_hash==ghb_off_hash)
            throw std::runtime_error("GoalD Fill=4 hybrid output identical to Off on near foreground");
        if (ghb_far_off!=ghb_far_hyb)
            throw std::runtime_error("GoalD Fill=4 hybrid altered distant >OFF_M background");
        frame.config.settings=ghb_saved_settings;
        m1_depth=ghb_saved_depth;
        m21_fine_depth=ghb_saved_fine;
        m1_geometry.k=ghb_saved_k;
        std::cout<<"PASS: WARP goal D Fill=4 Tight B+C2+3 hybrid active, tap modes valid, >8m untouched\n";
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
    s = s.replace(marker, BLOCK + JITTER_BLOCK + HYBRID_BLOCK + marker)
    if "#include <fstream>" not in s:
        s = "#include <fstream>\n#include <cmath>\n#include <vector>\n" + s
    args.output.write_text(s, encoding="utf-8", newline="\n")
    print("Generated goal D WARP fixture")


if __name__ == "__main__":
    main()

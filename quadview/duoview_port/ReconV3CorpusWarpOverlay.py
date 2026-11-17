#!/usr/bin/env python3
"""Test-only exact production-compositor WARP replay of the frozen V3 RGB-D corpus.

Only edits the generated fixture source. The shipping shaders and runtime are untouched.
The V3 evaluator-only GT files are NEVER opened by this replay.
"""
import argparse
from pathlib import Path

MARKER = '    // Restore every touched field; the final legacy comparison is intended'
INCLUDE = '#include "DuoViewD3D12.hpp"\n'

BLOCK = r'''
    // Independent V3 RGB-D corpus replay: generated test fixture ONLY.
    if(const char* flag=std::getenv("DUOVIEW_RECON_V3");flag && flag[0]=='1') {
        namespace fs=std::filesystem;
        const char* corpus_env=std::getenv("DUOVIEW_RECON_V3_DIR");
        if(!corpus_env || !*corpus_env)
            throw std::runtime_error("DUOVIEW_RECON_V3_DIR missing");
        const fs::path corpus(corpus_env);
        const UINT RW=384u,RH=216u;
        // Measurement profiles select effective post-configure settings only.
        // No saved profile or shipping source is changed by this test fixture.
        const char* profile_env=std::getenv("DUOVIEW_EDGE_PROFILE");
        const std::string requested_profile=profile_env ? profile_env : "P0";
        // Edge toggle K3/K23 = exact P1 settings plus the runtime edge mode (test-only RGB profiles).
        const uint32_t edge_mode=requested_profile=="K3" ? 1u : requested_profile=="K23" ? 2u : 0u;
        const std::string profile=edge_mode ? std::string("P1") : requested_profile;
        struct EdgeSweepProfile {
            const char* name;
            float close_amount,far_amount,start_distance_m,end_distance_m,knee_distance_m;
            bool m4_fovea_grid,m2_fovea_depth;
            uint32_t m25_fine_mode;
        };
        const EdgeSweepProfile sweep_profiles[]={
            {"S1",.25f,0.f,7.869f,32.052f,.2f,true,true,1u},
            {"S2",.5f,0.f,7.869f,32.052f,.2f,true,true,1u},
            {"S3",0.f,.75f,7.869f,32.052f,.2f,true,true,1u},
            {"S4",0.f,0.f,2.f,8.f,.2f,true,true,1u},
            {"S5",0.f,0.f,7.869f,32.052f,0.f,true,true,1u},
            {"S6",0.f,0.f,7.869f,32.052f,.1f,true,true,1u},
            {"S7",0.f,0.f,7.869f,32.052f,.4f,true,true,1u},
            {"S8",0.f,0.f,7.869f,32.052f,.2f,false,false,0u},
        };
        const EdgeSweepProfile* sweep_profile=nullptr;
        for(const auto& candidate:sweep_profiles)
            if(profile==candidate.name) sweep_profile=&candidate;
        const bool baseline_profile=profile=="P0" || profile=="P1" || profile=="P2";
        if(!baseline_profile && !sweep_profile)
            throw std::runtime_error("Unknown baseline profile");
        const char* probe_env=std::getenv("DUOVIEW_EDGE_PROBE");
        const std::string probe=probe_env ? probe_env : "rgb";
        if(probe!="rgb" && probe!="uv" && probe!="depth" && probe!="constants")
            throw std::runtime_error("Unknown baseline readback probe");
        const char* names[]={"weapon_object_motion","layers_object_motion",
            "foliage_stationary_false49","foliage_physical_sway","natural_physical_sway"};
        const auto saved_frame=frame;
        const auto saved_geometry=m1_geometry;
        const auto replay_lease=std::make_shared<const int>(64032);
        auto layout=uevr::duoview::make_layout(RW,RH,.5f,.5f,.25f,1.f,.5f,.5f);
        if(!layout || layout->periphery.width!=96 || layout->periphery.height!=54 ||
           layout->fovea.width!=192 || layout->fovea.height!=108)
            throw std::runtime_error("V3 native active rectangle changed");
        auto compositor=std::make_unique<uevr::duoview::dx12::Compositor>();
        if(!compositor->prewarm(g.device.Get(),RW,RH,false,0))
            throw std::runtime_error("V3 WARP compositor prewarm failed");
        // K profiles only: queue-owned label history, attached to STEREO frames only, so the
        // hysteresis sees consecutive stereo frames (f0->f1->f2->f3), as in the game.
        std::shared_ptr<uevr::duoview::dx12::B40MonoHistory> edge_history;
        uint32_t edge_frames=0u, edge_reused=0u;
        if(edge_mode) {
            edge_history=uevr::duoview::dx12::B40MonoHistory::create(g.device.Get(),g.queue.Get());
            if(!edge_history || !edge_history->edge_history)
                throw std::runtime_error("V3 edge toggle history allocation failed");
        }
        const auto od=texture(2*RW,RH,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
        auto dest=resource(g.device.Get(),od,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT rfp{}; UINT64 rb_bytes{};
        g.device->GetCopyableFootprints(&od,0,1,0,&rfp,nullptr,nullptr,&rb_bytes);
        auto rb=resource(g.device.Get(),buffer(rb_bytes),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
        ComPtr<ID3D12DescriptorHeap> v3rtvheap;
        D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.NumDescriptors=1;hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        check(g.device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&v3rtvheap)));
        const auto v3rtv=v3rtvheap->GetCPUDescriptorHandleForHeapStart();
        g.device->CreateRenderTargetView(dest.Get(),nullptr,v3rtv);
        std::ofstream metadata("recon_v3_capture_contract.jsonl",std::ios::binary);
        if(!metadata) throw std::runtime_error("V3 capture contract cannot be written");
        metadata<<std::setprecision(10);

        auto read_data=[&](const fs::path& name, size_t expected) {
            std::ifstream input(name,std::ios::binary|std::ios::ate);
            if(!input) throw std::runtime_error("V3 missing input: "+name.string());
            const auto actual=input.tellg();
            if(actual<0 || static_cast<uint64_t>(actual)!=expected)
                throw std::runtime_error("V3 input size mismatch: "+name.string());
            input.seekg(0);
            std::vector<uint8_t> data(expected);
            input.read(reinterpret_cast<char*>(data.data()),static_cast<std::streamsize>(expected));
            if(!input) throw std::runtime_error("V3 input truncated: "+name.string());
            return data;
        };
        // Upload input-derived images ONLY; reference colors and IDs must be
        // available exclusively to the offline evaluator, never to the GPU.
        auto upload=[&](const fs::path& filename, bool depth, bool foveal) {
            const UINT aw=depth ? RW : (foveal ? layout->fovea.width : layout->periphery.width);
            const UINT ah=depth ? RH : (foveal ? layout->fovea.height : layout->periphery.height);
            const auto input=read_data(filename,size_t(RW)*RH*4u);
            const auto td=texture(RW,RH,
                depth ? DXGI_FORMAT_R32_TYPELESS : DXGI_FORMAT_B8G8R8A8_TYPELESS,
                depth ? D3D12_RESOURCE_FLAG_NONE : D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
            auto texture_gpu=resource(g.device.Get(),td,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT64 nbytes{};
            g.device->GetCopyableFootprints(&td,0,1,0,&fp,nullptr,nullptr,&nbytes);
            fp.Footprint.Format=depth ? DXGI_FORMAT_R32_FLOAT : DXGI_FORMAT_B8G8R8A8_UNORM;
            auto staging=resource(g.device.Get(),buffer(nbytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
            void* mapped{};check(staging->Map(0,&no_reads,&mapped));
            std::memset(mapped,0,static_cast<size_t>(nbytes));
            if(depth) {
                for(UINT y=0;y<RH;++y)
                    std::memcpy(static_cast<uint8_t*>(mapped)+y*fp.Footprint.RowPitch,
                                input.data()+size_t(y)*RW*4u,RW*4u);
            } else {
                auto src=[&](int x,int y,int c)->float {
                    x=(std::max)(0,(std::min)(int(RW)-1,x));
                    y=(std::max)(0,(std::min)(int(RH)-1,y));
                    return float(input[(size_t(y)*RW+size_t(x))*4u+size_t(c)]);
                };
                for(UINT y=0;y<ah;++y) for(UINT x=0;x<aw;++x) {
                    const float fx=(float(x)+.5f)*float(RW)/float(aw)-.5f;
                    const float fy=(float(y)+.5f)*float(RH)/float(ah)-.5f;
                    const int x0=int(std::floor(fx)),y0=int(std::floor(fy));
                    const float ax=fx-float(x0),ay=fy-float(y0);
                    auto* px=static_cast<uint8_t*>(mapped)+y*fp.Footprint.RowPitch+x*4u;
                    for(int c=0;c<3;++c) {
                        const float top=src(x0,y0,c)*(1.f-ax)+src(x0+1,y0,c)*ax;
                        const float bottom=src(x0,y0+1,c)*(1.f-ax)+src(x0+1,y0+1,c)*ax;
                        const float v=top*(1.f-ay)+bottom*ay;
                        px[c]=static_cast<uint8_t>(std::lround((std::min)(255.f,(std::max)(0.f,v))));
                    }
                    px[3]=255;
                }
            }
            staging->Unmap(0,nullptr);
            D3D12_TEXTURE_COPY_LOCATION from{staging.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
            from.PlacedFootprint=fp;
            D3D12_TEXTURE_COPY_LOCATION to{texture_gpu.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
            g.cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
            transition(g.cmd.Get(),texture_gpu.Get(),D3D12_RESOURCE_STATE_COPY_DEST,
                depth ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE : D3D12_RESOURCE_STATE_RENDER_TARGET);
            g.submit_and_wait();
            keep.push_back(staging);keep.push_back(texture_gpu);
            return texture_gpu;
        };
        unsigned captures=0,nonidentical=0;
        for(int scene=0;scene<5;++scene) for(int fr=0;fr<4;++fr) {
            const fs::path dir=corpus/names[scene];
            const std::string pfx=std::string(fr<10?"0":"")+std::to_string(fr)+"_";
            auto full=upload(dir/(pfx+"source_full.bgra"),false,false);
            auto crop=upload(dir/(pfx+"source_fovea.bgra"),false,true);
            auto coarse=upload(dir/(pfx+"raw_coarse.f32"),true,false);
            auto fine=upload(dir/(pfx+"raw_fine.f32"),true,true);
            uevr::duoview::dx12::M1DepthInput coarse_input{
                coarse.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,RW,RH},{0.f,0.f},replay_lease};
            uevr::duoview::dx12::M1DepthInput fine_input{
                fine.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,RW,RH},{0.f,0.f},replay_lease};
            for(int mode=0;mode<2;++mode) {
                // Paired zero-stereo control and signed-stereo WARP output for
                // EVERY frame. This provides a fair source-limited mono baseline
                // even when the scene, gaze jitter or depth change over time.
                // Both modes use identical frozen RGB-D source allocations.
                const bool calibrate=mode==0;
                const float strength=calibrate ? 0.f : 1.f;
                auto params=saved_frame;
                params.config.layout=*layout;
                params.config.key.generation=500u+unsigned(scene);
                params.config.key.frame=5000u+unsigned(scene*20+fr*2+mode);
                params.config.settings.synthetic_stereo=true;
                params.config.settings.shared_eye_image=false;
                params.config.settings.direct_xr_output=true;
                params.config.settings.seam_match_enabled=false;
                params.config.settings.m2_fovea_depth=true;
                params.config.settings.m25_fine_mode=1u;
                params.config.settings.m4_fovea_grid=true;
                params.config.settings.m3_edges=false;
                params.config.settings.m3_fill=false;
                params.config.settings.m3_jitter_mode=0u;
                params.config.settings.m2_left_sharpen=0.f;
                params.config.settings.m2_right_sharpen=0.f;
                params.config.settings.sharpen_wide=false;
                params.config.settings.stereo_near_m=0.f;
                params.config.settings.stereo_strength=strength;
                params.config.settings.m21_depth_debug=0u;
                params.config.settings.m8_distance=true;
                params.config.settings.m8_near_m=2.f;
                params.config.settings.m8_far_m=8.f;
                params.config.settings.m8_edge_near=.5f;
                params.config.settings.m8_edge_far=.5f;
                params.config.settings.m8_fill_near=0.f;
                params.config.settings.m8_fill_far=0.f;
                params.config.settings.m9_eye_near=0.f;
                params.config.settings.m9_eye_far=0.f;
                params.config.settings.edge_reach_px=20.f;
                if(profile!="P0") {
                    params.config.settings.stereo_softness=.99f;
                    params.config.settings.m24_vertical_taper=0.f;
                    params.config.settings.m21_jitter_correct=false;
                    params.config.settings.edge_history=0.f;
                    params.config.settings.fill_history=0.f;
                    params.config.settings.stereo_near_m=.2f;
                    params.config.settings.m8_near_m=7.869f;
                    params.config.settings.m8_far_m=32.052f;
                    params.config.settings.m8_edge_near=0.f;
                    params.config.settings.m8_edge_far=profile=="P1" ? 0.f : .9f;
                }
                // S profiles start from the existing P1 assignments above,
                // then apply exactly one preregistered effective settings row.
                if(sweep_profile) {
                    params.config.settings.m8_edge_near=sweep_profile->close_amount;
                    params.config.settings.m8_edge_far=sweep_profile->far_amount;
                    params.config.settings.m8_near_m=sweep_profile->start_distance_m;
                    params.config.settings.m8_far_m=sweep_profile->end_distance_m;
                    params.config.settings.stereo_near_m=sweep_profile->knee_distance_m;
                    params.config.settings.m4_fovea_grid=sweep_profile->m4_fovea_grid;
                    params.config.settings.m2_fovea_depth=sweep_profile->m2_fovea_depth;
                    params.config.settings.m25_fine_mode=sweep_profile->m25_fine_mode;
                }
                // 18/19 retain V2 (>=10), and mark copied TEST-ONLY DXBC.
                // The ordinary production DXBC uses 20 and is never replaced.
                if(probe!="rgb") params.config.settings.edge_reach_px=probe=="uv" ? 19.f : probe=="depth" ? 18.f : 17.f;
                if(!params.config.settings.m8_distance || params.config.settings.m3_edges ||
                   params.config.settings.edge_reach_px<10.f ||
                   (profile!="P0" && !sweep_profile &&
                    (params.config.settings.stereo_softness!=.99f ||
                     params.config.settings.stereo_near_m!=.2f ||
                     params.config.settings.m8_edge_near!=0.f ||
                     params.config.settings.m8_edge_far!=(profile=="P1" ? 0.f : .9f))))
                    throw std::runtime_error("Effective V2 baseline profile not applied");
                if(sweep_profile &&
                   (params.config.settings.stereo_softness!=.99f ||
                    params.config.settings.m8_edge_near!=sweep_profile->close_amount ||
                    params.config.settings.m8_edge_far!=sweep_profile->far_amount ||
                    params.config.settings.m8_near_m!=sweep_profile->start_distance_m ||
                    params.config.settings.m8_far_m!=sweep_profile->end_distance_m ||
                    params.config.settings.stereo_near_m!=sweep_profile->knee_distance_m ||
                    params.config.settings.m4_fovea_grid!=sweep_profile->m4_fovea_grid ||
                    params.config.settings.m2_fovea_depth!=sweep_profile->m2_fovea_depth ||
                    params.config.settings.m25_fine_mode!=sweep_profile->m25_fine_mode))
                    throw std::runtime_error("Effective V2 sweep profile not applied");
                auto geometry=saved_geometry;
                geometry.world_to_meters=1.f;
                geometry.depth_coefficients={0.f,1.f,1.f};
                geometry.k={13.f/float(RW)*strength,-13.f/float(RW)*strength};
                geometry.fine_depth_camera={};
                const bool pan=(scene<2)&&!calibrate;
                for(int eye=0;eye<2;++eye) {
                    const float e=eye==0 ? 1.f : -1.f;
                    const float scale=pan ? (eye==0?1.035f:1.024f) : 1.f;
                    const float shift=pan ? 2.6f : 0.f;
                    const float skew=pan ? .012f : 0.f;
                    const float h01=e*skew*float(RH)/float(RW);
                    const float h02=.5f*(1.f-scale)+
                       (e*shift-e*skew*(float(RH)+1.f)*.5f)/float(RW);
                    const float h12=pan ? e*.31f/float(RH) : 0.f;
                    geometry.context_h[eye]={scale,h01,h02,0.f,
                                               0.f,1.f,h12,0.f,
                                               0.f,0.f,1.f,0.f};
                }
                const float sentinel[4]{0.f,1.f,0.f,1.f};
                g.cmd->ClearRenderTargetView(v3rtv,sentinel,0,nullptr);
                params.config.settings.stereo_edge_mode=edge_mode;
                if(edge_mode) compositor->set_b40_history(calibrate ? nullptr : edge_history);
                if(!compositor->record_native(g.device.Get(),g.cmd.Get(),crop.Get(),full.Get(),dest.Get(),
                   D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,
                   params,replay_lease,0,&geometry,&coarse_input,&fine_input))
                    throw std::runtime_error(std::string("V3 WARP record failed: ")+compositor->error());
                if(edge_mode && !calibrate) {
                    // K activation smoke test (review of #360): the requested mode must be the effective
                    // one, with fovea K and the history texture; history must be reused after frame 0.
                    const uint32_t st=uevr::duoview::duo_edge_status().load();
                    if(((st>>2)&3u)!=edge_mode || !(st&16u) || !(st&32u))
                        throw std::runtime_error("edge toggle K not active, status="+std::to_string(st));
                    ++edge_frames;
                    if(st&(1u<<21)) ++edge_reused;
                }
                transition(g.cmd.Get(),dest.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
                D3D12_TEXTURE_COPY_LOCATION rsrc{dest.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
                D3D12_TEXTURE_COPY_LOCATION rdst{rb.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
                rdst.PlacedFootprint=rfp;
                g.cmd->CopyTextureRegion(&rdst,0,0,0,&rsrc,nullptr);
                transition(g.cmd.Get(),dest.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
                g.submit_and_wait();
                // #363: edge history is published only after submission (game path: note_fine_depth_enqueued).
                if(edge_mode && !calibrate) compositor->commit_edge_history();
                void* mapped{};const D3D12_RANGE read_range{0,static_cast<size_t>(rb_bytes)};
                check(rb->Map(0,&read_range,&mapped));
                std::vector<uint8_t> packed(size_t(2*RW)*RH*4u);
                uint64_t signed_eye_diff=0;UINT sentinels=0;
                for(UINT y=0;y<RH;++y) {
                    const auto* row=static_cast<const uint8_t*>(mapped)+y*rfp.Footprint.RowPitch;
                    std::memcpy(packed.data()+size_t(y)*2u*RW*4u,row,size_t(2u*RW)*4u);
                    for(UINT x=0;x<RW;++x) {
                        for(int c=0;c<3;++c)
                            signed_eye_diff+=static_cast<uint64_t>(std::abs(int(row[x*4u+c])-int(row[(x+RW)*4u+c])));
                        if(row[x*4u]==0 && row[x*4u+1]==255 && row[x*4u+2]==0) ++sentinels;
                    }
                }
                rb->Unmap(0,nullptr);
                if(sentinels>RW*RH/2)
                    throw std::runtime_error("V3 unrendered sentinel output");
                if(calibrate && signed_eye_diff!=0)
                    throw std::runtime_error("V3 zero-strength calibration eyes differ");
                if(!calibrate && signed_eye_diff>1000) ++nonidentical;
                const std::string filename=std::string(calibrate?"recon_v3_zero_":"recon_v3_")+
                    names[scene]+"_f"+std::to_string(fr)+".bgra";
                std::ofstream out(filename,std::ios::binary);
                if(!out.write(reinterpret_cast<const char*>(packed.data()),packed.size()))
                    throw std::runtime_error("V3 WARP RGB capture write failed");
                metadata<<"{\"file\":\""<<filename<<"\",\"scene\":\""<<names[scene]
                    <<"\",\"frame\":"<<fr<<",\"calibration\":"<<(calibrate?"true":"false")
                    <<",\"width\":"<<RW<<",\"height\":"<<RH
                    <<",\"output\":\"doublewide_bgra8\",\"eye_order\":\"left_right\""
                    <<",\"fine_depth\":\"full_r32_inverse_z\",\"strength\":"<<strength
                    <<",\"profile\":\""<<requested_profile<<"\",\"probe\":\""<<probe<<"\""
                    <<",\"schema\":\"effective_v2\",\"legacy_curve\":false"
                    <<",\"close\":"<<params.config.settings.m8_edge_near
                    <<",\"far\":"<<params.config.settings.m8_edge_far
                    <<",\"start_m\":"<<params.config.settings.m8_near_m
                    <<",\"end_m\":"<<params.config.settings.m8_far_m
                    <<",\"near_m\":"<<params.config.settings.stereo_near_m
                    <<",\"softness\":"<<params.config.settings.stereo_softness
                    <<",\"policy\":"<<params.config.settings.edge_reach_px
                    <<",\"generation\":"<<params.config.key.generation<<",\"frame_key\":"<<params.config.key.frame
                    <<",\"eye_k\":["<<geometry.k[0]<<","<<geometry.k[1]<<"]"
                    <<",\"active_rects\":{\"periphery\":[96,54],\"fovea\":[192,108]}"
                    <<",\"homography\":[";
                for(int eye=0;eye<2;++eye) {
                    if(eye) metadata<<",";
                    metadata<<"[";
                    for(int v=0;v<12;++v) {
                        if(v) metadata<<",";
                        metadata<<geometry.context_h[eye][v];
                    }
                    metadata<<"]";
                }
                metadata<<"]}\n";
                ++captures;
                std::cout<<"RECON_V3,scene="<<names[scene]<<",frame="<<fr
                         <<",calibration="<<calibrate<<",eyes_absdiff="<<signed_eye_diff
                         <<",capture="<<filename<<"\n";
            }
        }
        metadata.flush();
        if(edge_mode) {
            std::cout<<"EDGE_TOGGLE_ACTIVE,profile="<<requested_profile<<",k_frames="<<edge_frames
                     <<",history_reused="<<edge_reused<<"\n";
            if(edge_frames!=20u || edge_reused<15u)
                throw std::runtime_error("edge toggle K frames/history reuse contract failed");
        }
        if(!metadata || captures!=40u || (probe=="rgb" && nonidentical<16u))
            throw std::runtime_error("V3 WARP capture count/stereo contract failed");
        std::cout<<"PASS: calibrated V3 corpus production WARP, captures="<<captures
                 <<",stereo_nonidentical="<<nonidentical<<"\n";
    }
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    src = a.source.read_text(encoding='utf-8')
    assert src.count(MARKER) == 1, 'V3 source insertion marker drifted'
    assert src.count('DUOVIEW_RECON_LARGE') >= 1, 'expected calibrated large WARP fixture'
    assert src.count(INCLUDE) == 1, 'production include changed'
    src = src.replace(INCLUDE, INCLUDE+'#include <filesystem>\n#include <iomanip>\n', 1)
    src = src.replace(MARKER, BLOCK + MARKER, 1)
    a.output.write_text(src, encoding='utf-8', newline='\n')
    print('Generated test-only independent V3 corpus production WARP fixture')


if __name__ == '__main__':
    main()
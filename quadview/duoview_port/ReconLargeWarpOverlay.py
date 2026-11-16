#!/usr/bin/env python3
"""Add the 384x216 matched RGB-D replay to the *generated* production WARP fixture.

The shipping DuoView shader and original 16-test contract remain untouched.
Do not conflate WARP correctness or its runtime with RTX 5070 frametime.
"""
from pathlib import Path
import argparse

MARKER="    // Restore every touched field; the final legacy comparison is intended"

LARGE_BLOCK=r'''
    // Test-only 384x216 baseline or 1024x816 DLSS Quality jitter-stress replay.
    // full-resolution fine depth, 768x216 doublewide output, both signed eyes.
    // The source is analytically coherent (RGB and depth are the SAME scene).
    // The only deliberate incoherence is a 7x7 false-depth foliage fault.
    if(const char* flag=std::getenv("DUOVIEW_RECON_LARGE");flag && flag[0]=='1') {
        const bool calibrate=std::getenv("DUOVIEW_RECON_CALIBRATE") && std::getenv("DUOVIEW_RECON_CALIBRATE")[0]=='1';
        const bool compare_jitter=std::getenv("DUOVIEW_RECON_COMPARE_JITTER") && std::getenv("DUOVIEW_RECON_COMPARE_JITTER")[0]=='1';
        const bool quality=calibrate || compare_jitter || (std::getenv("DUOVIEW_RECON_QUALITY") && std::getenv("DUOVIEW_RECON_QUALITY")[0]=='1');
        const UINT RW=quality?1024u:384u,RH=quality?816u:216u;
        const UINT QW=quality?683u:RW,QH=quality?544u:RH;
        // These are render-pixel jitter offsets (not output-pixel offsets),
        // as supplied by NGX. The source scene is sampled at -jitter so the
        // production shader's +jitter UV compensation aligns the raw depth.
        const float jitter_x[4]={0.f,-.25f,.25f,-.375f};
        const float jitter_y[4]={0.f,.167f,-.167f,.333f};
        const auto saved_source_frame=frame;
        const auto saved_geom=m1_geometry;
        const auto replay_lease=std::make_shared<const int>(42);
        struct ReplaySample { float r,g,b,dep; };
        auto analytic=[&](float fx,float fy,int scene,int fr,bool fault) -> ReplaySample {
            const int x=int(std::floor((fx+.5f)*384.f/float(RW)));
            const int y=int(std::floor((fy+.5f)*216.f/float(RH)));
            const int sway=scene==4 ? 2*fr : 0;
            const int weapon_shift=scene==1 ? 3*fr : 0;
            const bool weapon=scene==1 &&
                (((x>=115+weapon_shift && x<142+weapon_shift && y>=32 && y<190) ||
                  (x>=84+weapon_shift && x<237+weapon_shift && y>=146 && y<152) ||
                  (x>=131+weapon_shift && x<300+weapon_shift && y>=119 && y<122)));
            const bool leaf=scene==3 || scene==4;
            const int lx=x-sway;
            const bool foliage=leaf &&
                (((lx%23+23)%23<2 && y>=13 && y<204) ||
                 (((lx*11+y*3+4096)%71)==0 && y>=10 && y<205) ||
                 ((lx%41+41)%41>=8 && (lx%41+41)%41<12 && ((y+lx/3)%13+13)%13<2));
            const bool near_obj=weapon || foliage ||
                (scene==2 && x>61 && x<119 && y>25 && y<190);
            const bool mid_obj=scene==2 &&
                (((x>91 && x<279 && y>52 && y<141) ||
                  (x>311 && x<328 && y>30 && y<186)));
            const bool checker=(((x/11+y/10)%2)+2)%2!=0;
            ReplaySample pixel{};
            if(near_obj) pixel={.85f,.11f,.07f,1.0f};
            else if(mid_obj) pixel={.33f,.49f,.17f,.47f};
            else pixel={checker?.21f:.47f,checker?.55f:.24f,checker?.62f:.38f,.12f};
            // False alpha/TAA depth vote: one coherent 49-pixel cell alternates
            // while stationary scene RGB and true foliage geometry never change.
            if(fault && scene==3 && fr%2==1 &&
                x>=175 && x<182 && y>=85 && y<92) {
                pixel.dep= pixel.dep>.70f ? .12f : 1.0f;
            }
            return pixel;
        };
        auto upload_replay=[&](int scene,int fr,bool fovea,bool depth) {
            const DXGI_FORMAT format=depth ? DXGI_FORMAT_R32_TYPELESS : DXGI_FORMAT_B8G8R8A8_TYPELESS;
            const auto desc=texture(depth ? QW : RW,depth ? QH : RH,format,
                depth ? D3D12_RESOURCE_FLAG_NONE : D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
            auto tex=resource(g.device.Get(),desc,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; UINT64 nb{};
            g.device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&nb);
            fp.Footprint.Format=depth ? DXGI_FORMAT_R32_FLOAT : DXGI_FORMAT_B8G8R8A8_UNORM;
            auto up=resource(g.device.Get(),buffer(nb),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
            void* mapped{};const D3D12_RANGE no_reads_local{0,0};
            check(up->Map(0,&no_reads_local,&mapped));
            std::memset(mapped,0,static_cast<size_t>(nb));
            for(UINT y=0;y<(depth?QH:RH);++y) for(UINT x=0;x<(depth?QW:RW);++x) {
                // Quality: the depth is raster sampled at 683x544, while
                // post-SR color remains stable at the 1024x816 output size.
                // The extra scene=3 phase is deliberately UNTRACKED depth
                // trembling, not the regular NGX jitter metadata.
                const float untracked=(depth && quality && scene==3)
                   ? .39f*std::sin(float(fr)*1.71f) : 0.f;
                const float dx=(depth && quality)
                   ? (float(x)+.5f-jitter_x[fr%4]+untracked)*1.5f-.5f
                   : float(x);
                const float dy=(depth && quality)
                   ? (float(y)+.5f-jitter_y[fr%4]+untracked*.5f)*1.5f-.5f
                   : float(y);
                // Central 50% source crop; both RGB and depth share world
                // coordinates within each physical view.
                const float sx=fovea ? float(RW)*.25f+(dx+.5f)*.5f-.5f : dx;
                const float sy=fovea ? float(RH)*.25f+(dy+.5f)*.5f-.5f : dy;
                auto p=analytic(sx,sy,scene,fr,!quality);
                // Diagnostic provenance chart: RGB encodes actual WORLD input
                // coordinates of BOTH independently allocated physical views.
                // Not an input to any stereo reconstruction method.
                if(scene==5) p={sx/float(RW-1),sy/float(RH-1),fovea?.9f:.1f,.12f};
                // One 49-render-pixel false-depth vote per frame when quality.
                if(depth && quality && scene==3 && fr%2==1 &&
                   x>=UINT(QW*.45f) && x<UINT(QW*.45f)+7u &&
                   y>=UINT(QH*.4f) && y<UINT(QH*.4f)+7u)
                   p.dep=p.dep>.7f ? .12f : 1.f;
                auto* row=static_cast<uint8_t*>(mapped)+y*fp.Footprint.RowPitch;
                if(depth) reinterpret_cast<float*>(row)[x]=p.dep;
                else {
                    auto to_u8=[](float v) -> uint8_t { return static_cast<uint8_t>(std::lround((std::max)(0.f,(std::min)(1.f,v))*255.f)); };
                    row[4*x+0]=to_u8(p.b);row[4*x+1]=to_u8(p.g);
                    row[4*x+2]=to_u8(p.r);row[4*x+3]=255;
                }
            }
            up->Unmap(0,nullptr);
            D3D12_TEXTURE_COPY_LOCATION from{up.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};from.PlacedFootprint=fp;
            D3D12_TEXTURE_COPY_LOCATION to{tex.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
            g.cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
            transition(g.cmd.Get(),tex.Get(),D3D12_RESOURCE_STATE_COPY_DEST,
                depth ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE : D3D12_RESOURCE_STATE_RENDER_TARGET);
            g.submit_and_wait();
            keep.push_back(up);keep.push_back(tex);
            return tex;
        };
        auto big=std::make_unique<uevr::duoview::dx12::Compositor>();
        if(!big->prewarm(g.device.Get(),RW,RH,false,0))
            throw std::runtime_error("reconstruction WARP prewarm failed");
        auto big_layout=uevr::duoview::make_layout(RW,RH,.5f,.5f,.25f,1.f,.5f,.5f);
        if(!big_layout) throw std::runtime_error("reconstruction layout failed");
        auto out_desc=texture(2*RW,RH,DXGI_FORMAT_B8G8R8A8_UNORM,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
        auto out_tex=resource(g.device.Get(),out_desc,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT out_fp{};UINT64 out_nbytes{};
        g.device->GetCopyableFootprints(&out_desc,0,1,0,&out_fp,nullptr,nullptr,&out_nbytes);
        auto out_cpu=resource(g.device.Get(),buffer(out_nbytes),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
        ComPtr<ID3D12DescriptorHeap> large_rtv_heap;
        D3D12_DESCRIPTOR_HEAP_DESC lhd{};lhd.NumDescriptors=1;lhd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        check(g.device->CreateDescriptorHeap(&lhd,IID_PPV_ARGS(&large_rtv_heap)));
        auto large_rtv=large_rtv_heap->GetCPUDescriptorHandleForHeapStart();
        g.device->CreateRenderTargetView(out_tex.Get(),nullptr,large_rtv);

        // Calibration scenes exercise strength 0 / 0.5 / 1 with *matching*
        // physical signed eye disparities. Others run full strength.
        const char* names[]={"calibration","weapon","layers","false49","physical","uvchart"};
        unsigned captures=0;unsigned stereo_different=0;
        for(int scene=(calibrate||compare_jitter?1:0);scene<(calibrate?6:5);++scene)
        for(int fr=0;fr<(calibrate?1:(compare_jitter?4:(scene==0?3:scene==2?1:4)));++fr) {
            const float strength=calibrate?0.f:(scene==0 ? float(fr)*.5f : 1.f);
            const int source_frame=scene==0?0:fr;
            const auto full=upload_replay(scene,source_frame,false,false);
            const auto crop=upload_replay(scene,source_frame,true,false);
            const auto raw=upload_replay(scene,source_frame,false,true);
            const auto fine=upload_replay(scene,source_frame,true,true);
            auto params=saved_source_frame;
            params.config.layout=*big_layout;
            params.config.key.frame+=100u+captures;
            params.config.key.generation+=1u;
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
            auto geometry=saved_geom;
            geometry.world_to_meters=1.f;
            geometry.depth_coefficients={0.f,1.f,1.f};
            geometry.k={13.f/384.f*strength,-13.f/384.f*strength};
            geometry.fine_depth_camera={};
            for(auto& h:geometry.context_h)
                h={1.f,0.f,0.f,0.f,0.f,1.f,0.f,0.f,0.f,0.f,1.f,0.f};
            const std::array<float,2> jitter_uv={
                quality ? jitter_x[source_frame%4]/float(QW):0.f,
                quality ? jitter_y[source_frame%4]/float(QH):0.f};
            uevr::duoview::dx12::M1DepthInput coarse_input{
                raw.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,QW,QH},jitter_uv,replay_lease};
            uevr::duoview::dx12::M1DepthInput fine_input{
                fine.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,QW,QH},jitter_uv,replay_lease};
            // Add a depth-field capture on the weapon and 49px scenes, without
            // using diagnostic textures as references for RGB truth.
            for(int dm=0;dm<(calibrate?1:(compare_jitter?3:(quality?2:((scene==1 && fr==0)||(scene==3 && fr==1)?2:1))));++dm) {
                // Quality j0: captured NGX jitter; j1: same depth but no
                // jitter metadata. This isolates *alignment*, not depth truth.
                auto coarse_test=coarse_input;
                auto fine_test=fine_input;
                if(compare_jitter) {
                    // All variants use the SAME raw NGX-like depth and jitter.
                    // v0: legacy field-space compensation, fine weight 1.0.
                    // v1: source-space precondition alignment, fine weight 1.0.
                    // v2: source-space precondition alignment, fine weight 0.75.
                    // Fine depth remains physically captured and enabled in ALL.
                    params.config.settings.m21_jitter_correct=dm>0;
                    fine_test.fine_weight=(dm==2 ? .75f : 1.f);
                } else if(quality && dm==1) {
                    coarse_test.jitter={0.f,0.f};
                    fine_test.jitter={0.f,0.f};
                }
                params.config.settings.m21_depth_debug=quality?0u:(dm?4u:0u);
                const float green[]={0.f,1.f,0.f,1.f};
                g.cmd->ClearRenderTargetView(large_rtv,green,0,nullptr);
                params.config.key.frame+=1;
                if(!big->record_native(g.device.Get(),g.cmd.Get(),crop.Get(),full.Get(),out_tex.Get(),
                   D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,
                   params,replay_lease,0,&geometry,&coarse_test,&fine_test)) {
                    throw std::runtime_error(std::string("384x216 production compositor failed: ")+big->error());
                }
                transition(g.cmd.Get(),out_tex.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
                D3D12_TEXTURE_COPY_LOCATION out_from{out_tex.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
                D3D12_TEXTURE_COPY_LOCATION out_to{out_cpu.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
                out_to.PlacedFootprint=out_fp;
                g.cmd->CopyTextureRegion(&out_to,0,0,0,&out_from,nullptr);
                transition(g.cmd.Get(),out_tex.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
                g.submit_and_wait();
                void* mapped{};D3D12_RANGE read{0,static_cast<size_t>(out_nbytes)};
                check(out_cpu->Map(0,&read,&mapped));
                std::vector<uint8_t> packed(2*RW*RH*4);
                unsigned long long diff=0; unsigned sentinels=0;
                for(UINT y=0;y<RH;++y) {
                    auto* row=static_cast<const uint8_t*>(mapped)+y*out_fp.Footprint.RowPitch;
                    std::memcpy(packed.data()+y*2*RW*4,row,2*RW*4);
                    for(UINT x=0;x<RW;++x) {
                        for(UINT c=0;c<3;++c)
                            diff+=unsigned(std::abs(int(row[x*4+c])-int(row[(x+RW)*4+c])));
                        if(row[x*4]==0 && row[x*4+1]==255 && row[x*4+2]==0) ++sentinels;
                    }
                }
                out_cpu->Unmap(0,nullptr);
                if(sentinels>RW*RH/2) throw std::runtime_error("384 replay unrendered sentinel eye");
                if(strength>0.f && diff>1000) ++stereo_different;
                const auto file=std::string(calibrate?"recon_map_":(compare_jitter?"recon_compare_":(quality?"recon_quality_":"recon_large_")))+names[scene]+
                    "_f"+std::to_string(source_frame)+"_s"+std::to_string(int(strength*100.f))+
                    (compare_jitter?"_v":(quality?"_j":"_d"))+std::to_string(dm)+".bgra";
                std::ofstream output(file,std::ios::binary);
                if(!output.write(reinterpret_cast<const char*>(packed.data()),packed.size()))
                    throw std::runtime_error("384 replay capture write failed");
                ++captures;
                std::cout<<(quality?"RECON_QUALITY,scene=":"RECON_LARGE,scene=")
                         <<names[scene]<<",frame="<<source_frame
                         <<",strength="<<strength<<",debug="<<dm
                         <<",eye_diff="<<diff<<",capture="<<file<<"\n";
            }
        }
        if(captures!=(calibrate?5u:(compare_jitter?48u:(quality?32u:18u))) || (!calibrate && stereo_different<8))
            throw std::runtime_error("WARP replay capture/eye disparity gate failed");
        std::cout<<"PASS: "<<(compare_jitter?"1024x816 source-jitter alignment/fine-weight A-B-C GPU replay":(quality?"1024x816 DLSS Quality 683x544 jitter replay":"384x216 full-res replay"))
                 <<", captures="<<captures<<", stereo_nonidentical="<<stereo_different<<"\n";
    }
'''

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    s=args.source.read_text(encoding="utf-8")
    assert s.count(MARKER)==1, "reconstruction large WARP marker changed"
    assert "DUOVIEW_RECON_REPLAY" in s, "small WARP gate must stay present"
    s=s.replace(MARKER,LARGE_BLOCK+MARKER,1)
    args.output.write_text(s,encoding="utf-8",newline="\n")
    print("Generated production WARP 384x216 RGB-D fixture")

if __name__=="__main__":
    main()

#!/usr/bin/env python3
"""Test-only exact production compositor WARP RGB-D replay.

This overlay modifies only the *generated fixture* C++ source, never UEVR.
Raw BGRA captures deliberately preserve all pixels for independent scoring.
A 32x32 smoke gate is NOT a substitute for a full-resolution validation.
"""
import argparse
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a=p.parse_args()
    s=a.source.read_text(encoding="utf-8")
    include='#include "DuoViewD3D12.hpp"\n'
    assert s.count(include)==1, "production include anchor changed"
    s=s.replace(include,include+'#include <fstream>\n',1)
    marker='    // Restore every touched field; the final legacy comparison is intended'
    assert s.count(marker)==1,"M4 fixture insertion anchor changed"
    assert s.count('auto upload_depth=[&](auto value_at)')==1,"M3 depth uploader disappeared"
    block=r'''    // Separate recon smoke gate: actual compiled production pixel/compute
    // shaders, M4, coarse/fine inputs, both signed eyes, no GPU mocks.
    if (const char* recon=std::getenv("DUOVIEW_RECON_REPLAY"); recon && recon[0]=='1') {
        const auto old_primary=primary,old_secondary=secondary;
        const auto old_depth=m1_depth;
        const auto old_fine=m21_fine_depth;
        const auto old_layout=frame.config.layout;
        const auto old_fine_camera=m1_geometry.fine_depth_camera;
        m1_geometry.world_to_meters=1.f;
        m1_geometry.depth_coefficients={0.f,1.f,1.f};
        m1_geometry.k={.25f,-.25f};
        for (auto& h : m1_geometry.context_h) h={1,0,0,0, 0,1,0,0, 0,0,1,0};
        m1_geometry.fine_depth_camera={};
        frame.config.settings.synthetic_stereo=true;
        frame.config.settings.shared_eye_image=false;
        frame.config.settings.direct_xr_output=true;
        frame.config.settings.seam_match_enabled=false;
        frame.config.settings.m2_fovea_depth=true;
        frame.config.settings.m25_fine_mode=1u;
        frame.config.settings.m3_edges=false;
        frame.config.settings.m3_fill=false;
        frame.config.settings.m3_jitter_mode=0u;
        frame.config.settings.m4_fovea_grid=true;
        frame.config.settings.m8_distance=true;
        frame.config.settings.m8_near_m=2.f;
        frame.config.settings.m8_far_m=8.f;
        frame.config.settings.m8_edge_near=.5f;
        frame.config.settings.m8_edge_far=.5f;
        frame.config.settings.m8_fill_near=0.f;
        frame.config.settings.m8_fill_far=0.f;
        frame.config.settings.m9_eye_near=0.f;
        frame.config.settings.m9_eye_far=0.f;
        frame.config.settings.edge_reach_px=20.f;
        frame.config.settings.stereo_near_m=0.f;
        frame.config.settings.stereo_strength=1.f;
        frame.config.settings.m2_left_sharpen=0.f;
        frame.config.settings.m2_right_sharpen=0.f;
        frame.config.settings.sharpen_wide=false;
        // Independent creation rather than the 1-D depth helper: 7x7 groups
        // and thin y-dependent foreground edges must survive the upload.
        auto upload_recon=[&](bool is_depth,int scene,int frame_idx) {
            const auto fmt=is_depth ? DXGI_FORMAT_R32_TYPELESS : DXGI_FORMAT_B8G8R8A8_TYPELESS;
            const auto flags=is_depth ? D3D12_RESOURCE_FLAG_NONE : D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
            const auto desc=texture(32,32,fmt,flags);
            auto tex=resource(g.device.Get(),desc,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT64 bytes{};
            g.device->GetCopyableFootprints(&desc,0,1,0,&fp,nullptr,nullptr,&bytes);
            fp.Footprint.Format=is_depth ? DXGI_FORMAT_R32_FLOAT : DXGI_FORMAT_B8G8R8A8_UNORM;
            auto up=resource(g.device.Get(),buffer(bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
            void* mapped{};check(up->Map(0,&no_reads,&mapped));
            std::memset(mapped,0,static_cast<size_t>(bytes));
            for (UINT y=0;y<32;++y) for(UINT x=0;x<32;++x) {
                const int xi=int(x),yi=int(y);
                bool foreground=false;
                if (scene==0) { // weapon crossing two background layers
                    const int left=10+frame_idx;
                    foreground=(xi>=left && xi<left+4 && yi>=4 && yi<28) ||
                         (yi>=15 && yi<17 && xi>=left-5 && xi<left+10);
                } else if (scene==1) { // stationary real leaves, false 49-pixel depth patch
                    foreground=((xi%7==0) && yi>=4 && yi<28) ||
                         ((xi+2*yi)%17==0 && yi>=6 && yi<25);
                } else { // physical sway, true color AND depth move together
                    foreground=(((xi-frame_idx)%7+7)%7==0 && yi>=4 && yi<28) ||
                         ((xi-frame_idx+2*yi+68)%17==0 && yi>=6 && yi<25);
                }
                const bool corrupt=(scene==1 && xi>=18 && xi<25 && yi>=11 && yi<18 && frame_idx%2==1);
                if (is_depth) {
                    auto* row=reinterpret_cast<float*>(static_cast<uint8_t*>(mapped)+y*fp.Footprint.RowPitch);
                    row[x]=(foreground!=corrupt) ? .45f : .15f;
                } else {
                    uint8_t* px=static_cast<uint8_t*>(mapped)+y*fp.Footprint.RowPitch+4*x;
                    const bool checker=((xi/2+yi/2)&1)!=0;
                    px[0]=foreground ? 15 : (checker ? 190 : 85);  // B
                    px[1]=foreground ? 20 : (checker ? 95 : 195);  // G
                    px[2]=foreground ? 245 : 25;                  // R
                    px[3]=255;
                }
            }
            up->Unmap(0,nullptr);
            D3D12_TEXTURE_COPY_LOCATION from{up.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
            from.PlacedFootprint=fp;
            D3D12_TEXTURE_COPY_LOCATION to{tex.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
            g.cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
            transition(g.cmd.Get(),tex.Get(),D3D12_RESOURCE_STATE_COPY_DEST,
                is_depth ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE : D3D12_RESOURCE_STATE_RENDER_TARGET);
            g.submit_and_wait();
            keep.push_back(up); keep.push_back(tex);
            return tex;
        };
        const char* labels[]={"weapon","false49","physical"};
        unsigned long long nonidentical=0;
        for (int scene=0;scene<3;++scene) for(int fr=0;fr<4;++fr) {
            auto rgb=upload_recon(false,scene,fr);
            auto dep=upload_recon(true,scene,fr);
            primary=rgb;secondary=rgb;
            m1_depth={dep.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
            m21_fine_depth={dep.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
            frame.config.layout=old_layout;
            if(scene==2) {
                frame.config.layout.u0+=.01f*fr;
                frame.config.layout.u1+=.01f*fr;
            }
            for (int debug_mode=0;debug_mode<2;++debug_mode) {
                frame.config.settings.m21_depth_debug=debug_mode ? 4u : 0u;
                const float green[4]{0.f,1.f,0.f,1.f};
                g.cmd->ClearRenderTargetView(rtv,green,0,nullptr);
                ++frame.config.key.frame;
                if(!a->record_native(g.device.Get(),g.cmd.Get(),primary.Get(),secondary.Get(),stereo.Get(),
                    D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,frame,lease,0,
                    &m1_geometry,&m1_depth,&m21_fine_depth))
                    throw std::runtime_error(std::string("reconstruction WARP record failed: ")+a->error());
                transition(g.cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
                D3D12_TEXTURE_COPY_LOCATION from{stereo.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
                D3D12_TEXTURE_COPY_LOCATION to{readback.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
                to.PlacedFootprint=foot;
                g.cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
                transition(g.cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
                g.submit_and_wait();
                void* mapped{};D3D12_RANGE read{0,static_cast<size_t>(bytes)};
                check(readback->Map(0,&read,&mapped));
                std::vector<uint8_t> packed(64*32*4);
                unsigned long long diff=0;
                for(UINT y=0;y<32;++y) {
                    const auto* row=static_cast<const uint8_t*>(mapped)+y*foot.Footprint.RowPitch;
                    std::memcpy(packed.data()+y*64*4,row,64*4);
                    for(UINT x=0;x<32;++x)
                        for(int channel=0;channel<3;++channel)
                            diff+=unsigned(std::abs(int(row[4*x+channel])-int(row[4*(x+32)+channel])));
                }
                readback->Unmap(0,nullptr);
                const std::string file=std::string("recon_gpu_")+labels[scene]+
                  "_f"+std::to_string(fr)+"_d"+std::to_string(debug_mode)+".bgra";
                std::ofstream output(file,std::ios::binary);
                if(!output.write(reinterpret_cast<const char*>(packed.data()),packed.size()))
                    throw std::runtime_error("reconstruction capture write failed");
                nonidentical+=diff>0;
                std::cout<<"RECON_GPU,scene="<<labels[scene]<<",frame="<<fr
                         <<",debug="<<debug_mode<<",eyes_absdiff="<<diff
                         <<",capture="<<file<<"\n";
            }
        }
        if(nonidentical<4) throw std::runtime_error("WARP stereo input produced identical eyes");
        primary=old_primary;secondary=old_secondary;
        m1_depth=old_depth;m21_fine_depth=old_fine;
        frame.config.layout=old_layout;
        m1_geometry.fine_depth_camera=old_fine_camera;
        std::cout<<"PASS: exact production WARP RGB-D captures, both eyes / three scenes / 49px error\n";
    }
'''
    s=s.replace(marker,block+marker,1)
    a.output.write_text(s,encoding="utf-8",newline="\n")
    print("Generated test-only production stereo reconstruction WARP replay")

if __name__=="__main__":
    main()

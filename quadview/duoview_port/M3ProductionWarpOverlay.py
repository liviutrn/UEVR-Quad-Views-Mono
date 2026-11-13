#!/usr/bin/env python3
"""Extend the production D3D12 WARP fixture: M2.5a positive gate checks,
M3a per-eye edge checks, and the contract C2 role table."""
from pathlib import Path
import argparse


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--source", type=Path, required=True)
    a.add_argument("--output", type=Path, required=True)
    args = a.parse_args()
    s = args.source.read_text(encoding="utf-8")
    include = '#include "DuoViewD3D12.hpp"\n'
    assert s.count(include) == 1, "M3 WARP include anchor drifted"
    s = s.replace(include, include + '#include "UevrSourceRolesProducer.hpp"\n')
    marker = "    // Restore every touched field; the final legacy comparison is intended"
    assert s.count(marker) == 1, "M3 WARP insertion drifted"
    block = r'''    // ---- M2.5a positive gate checks + M3a + C2 (lead build) ----
    // The zero-disparity test above leaves k at 0; every check below needs a real warp.
    m1_geometry.k={.25f,-.25f};
    auto upload_depth=[&](auto value_at) {
        const auto d=texture(32,32,DXGI_FORMAT_R32_TYPELESS,D3D12_RESOURCE_FLAG_NONE);
        auto tex=resource(g.device.Get(),d,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{}; UINT64 nb{};
        g.device->GetCopyableFootprints(&d,0,1,0,&fp,nullptr,nullptr,&nb);
        fp.Footprint.Format=DXGI_FORMAT_R32_FLOAT;
        auto up=resource(g.device.Get(),buffer(nb),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
        void* m{}; check(up->Map(0,&no_reads,&m));
        for (UINT y=0;y<32;++y) {
            auto* r=reinterpret_cast<float*>(static_cast<uint8_t*>(m)+y*fp.Footprint.RowPitch);
            for (UINT x=0;x<32;++x) r[x]=value_at(x);
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
    auto take=[]{ return uevr::duoview::dx12::M1Resources::m25_take_gpu_window(); };
    const auto lease=std::make_shared<const int>(1);
    const float cu0=frame.config.layout.u0, cu1=frame.config.layout.u1;
    auto band=[](float u){ return (u>=.34f && u<.6f) ? .45f : .15f; };
    auto band_moved=[](float u){ return (u>=.66f && u<.8f) ? .45f : .15f; };
    auto coarse_step=upload_depth([&](UINT x){ return band((x+.5f)/32.f); });
    auto fine_same=upload_depth([&](UINT x){ return band(cu0+(x+.5f)/32.f*(cu1-cu0)); });
    auto fine_moved=upload_depth([&](UINT x){ return band_moved(cu0+(x+.5f)/32.f*(cu1-cu0)); });
    frame.config.settings.synthetic_stereo=true;
    frame.config.settings.m2_fovea_depth=true;
    frame.config.settings.m21_depth_debug=0u;
    frame.config.settings.m25_fine_mode=1u;
    frame.config.settings.m3_edges=false;
    frame.config.settings.m3_jitter_mode=0u;
    const auto saved_m1_depth=m1_depth;
    m1_depth={coarse_step.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
    m21_fine_depth={};
    run(*a,false,Route::direct,"M2.5a review: coarse step reference, fine absent");
    const auto coarse_step_hash=m21_image_hash;
    (void)take();
    m21_fine_depth={fine_same.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
    run(*a,false,Route::direct,"M2.5a review: matching fine depth");
    if (!a->last_stereo_fovea_depth()) throw std::runtime_error("M2.5a matching fine depth not bound");
    m21_fine_depth={};
    run(*a,false,Route::direct,"M2.5a review: stats flush (coarse only)");
    const auto same=take();
    std::cout<<"M2.5a matching: frames="<<same[0]<<" guard="<<same[1]<<" cells="<<same[2]
             <<" agree="<<same[3]<<" varied="<<same[4]<<" passing="<<same[5]
             <<" weight_x1000="<<same[6]<<" active_tiles="<<same[7]<<"\n";
    if (same[0]<1 || same[2]==0) throw std::runtime_error("M2.5a gate produced no statistics");
    if (same[1]!=0 || same[3]*100<same[2]*95 || same[7]==0 || same[6]<900*same[7])
        std::cout<<"CHECK: M2.5a gate was strict with matching fine depth (see numbers above)\n";
    m21_fine_depth={fine_moved.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
    run(*a,false,Route::direct,"M2.5a review: wrong-frame fine depth");
    const auto moved_hash=m21_image_hash;
    m21_fine_depth={};
    run(*a,false,Route::direct,"M2.5a review: stats flush (coarse only)");
    const auto moved=take();
    std::cout<<"M2.5a wrong frame: frames="<<moved[0]<<" guard="<<moved[1]<<" cells="<<moved[2]
             <<" agree="<<moved[3]<<" weight_x1000="<<moved[6]<<" active_tiles="<<moved[7]<<"\n";
    if (moved[0]<1) throw std::runtime_error("M2.5a gate produced no statistics");
    if (moved[1]==1 && moved_hash!=coarse_step_hash)
        throw std::runtime_error("M2.5a rejected fine depth still changed the image");
    if (moved[1]!=1) std::cout<<"CHECK: M2.5a gate did not fully reject the wrong-frame fine depth\n";
    std::cout<<"PASS: WARP M2.5a gate statistics and rejection keep the coarse image\n";

    frame.config.settings.m2_fovea_depth=false;
    frame.config.settings.m25_fine_mode=0u;
    m1_depth=saved_m1_depth;
    run(*a,false,Route::direct,"M3a OFF, flat depth");
    const auto flat_off=m21_image_hash;
    frame.config.settings.m3_edges=true;
    frame.config.settings.m3_fill=true;
    run(*a,false,Route::direct,"M3a ON, flat depth");
    if (m21_image_hash!=flat_off) throw std::runtime_error("M3a changed an image with no depth edges");
    // Solid-colour sources only show a warp change across the fovea edge (u=.75): this step's fill
    // gap (pixels 18-20) reads periphery, while checked pixels 1 and 16 stay on their own source.
    auto m3_step=upload_depth([&](UINT x){ const float u=(x+.5f)/32.f; return (u>=.52f && u<.70f) ? .45f : .15f; });
    m1_depth={m3_step.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},lease};
    frame.config.settings.m3_edges=false;
    run(*a,false,Route::direct,"M3a OFF, depth step");
    const auto step_off=m21_image_hash;
    frame.config.settings.m3_jitter_mode=1u;
    run(*a,false,Route::direct,"Jitter alignment + with zero jitter");
    if (m21_image_hash!=step_off) throw std::runtime_error("Jitter alignment changed output with zero jitter");
    frame.config.settings.m3_jitter_mode=0u;
    frame.config.settings.m3_edges=true;
    run(*a,false,Route::direct,"M3a ON, depth step, background fill");
    const auto step_fill=m21_image_hash;
    if (step_fill==step_off) throw std::runtime_error("M3a per-eye edges did not change a depth step");
    frame.config.settings.m3_fill=false;
    run(*a,false,Route::direct,"M3a ON, depth step, membrane side");
    if (m21_image_hash==step_fill) throw std::runtime_error("M3a fill switch had no effect on a depth step");
    frame.config.settings.m3_edges=false;
    frame.config.settings.m3_fill=true;
    m1_depth=saved_m1_depth;
    std::cout<<"PASS: WARP M3a per-eye edges, fill and jitter plumbing\n";

    {
        auto& roles=uevr::contracts::SourceRoleTable::self();
        UevrSourceRolesV1 snap{}; snap.struct_size=sizeof(snap);
        roles.note(0x1000,UEVR_ROLE_DUO_FOVEA,6u,77u,2030,1614,1355,1077);
        roles.note(0x2000,UEVR_ROLE_DUO_PERIPHERY,6u,77u,812,646,542,431);
        if (!roles.snapshot(&snap) || snap.version!=1u || snap.count!=2u ||
            snap.rendering_method!=6u || snap.transition_in_progress!=1u)
            throw std::runtime_error("C2 table: first family wrong");
        roles.note(0x1000,UEVR_ROLE_DUO_FOVEA,6u,77u,2030,1614,1355,1077);
        roles.note(0x2000,UEVR_ROLE_DUO_PERIPHERY,6u,77u,812,646,542,431);
        roles.snapshot(&snap);
        if (snap.transition_in_progress!=0u) throw std::runtime_error("C2 table: transition did not settle");
        const auto generation=snap.layout_generation;
        roles.note(0x3000,UEVR_ROLE_DUO_PERIPHERY,6u,78u,1173,933,783,623);
        roles.snapshot(&snap);
        if (snap.layout_generation!=generation+1 || snap.count!=1u || snap.transition_in_progress!=1u)
            throw std::runtime_error("C2 table: layout change not reported");
        UevrSourceRolesV1 short_struct{}; short_struct.struct_size=8;
        if (roles.snapshot(&short_struct)) throw std::runtime_error("C2 table accepted a short struct");
        std::cout<<"PASS: C2 role table versions, transitions and size check\n";
    }
'''
    s = s.replace(marker, block + marker)
    args.output.write_text(s, encoding="utf-8", newline="\n")
    print("Generated M3a/M2.5a-review/C2 WARP fixture")


if __name__ == "__main__":
    main()

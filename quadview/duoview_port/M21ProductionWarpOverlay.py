#!/usr/bin/env python3
"""Extend the existing B40/M1 WARP test with real M2.1 GPU pixel assertions.

The production compositor, actual FXC shaders and Windows D3D12 WARP are used;
no mocks of depth conditioning or the per-eye pixel shader.
"""
from pathlib import Path
import argparse

def substitute(source, old, new, label):
    count=source.count(old)
    if count!=1: raise ValueError(f"{label}: expected one fixture anchor, got {count}")
    return source.replace(old,new,1)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args()
    source=a.source.read_text(encoding="utf-8")
    source=substitute(source,
        "    std::array<uint8_t,2> m1_probe{};",
        """    std::array<uint8_t,2> m1_probe{};
    uevr::duoview::dx12::M1DepthInput m21_fine_depth{};
    uint64_t m21_image_hash{},m21_eye_difference{};""",
        "M21 fixture state")
    source=substitute(source,
        "                m1_depth.texture ? &m1_depth : nullptr);",
        """                m1_depth.texture ? &m1_depth : nullptr,
                m21_fine_depth.texture ? &m21_fine_depth : nullptr);""",
        "M21 route fine to real GPU compositor")
    source=substitute(source,
        "        if (frame.config.settings.synthetic_stereo) m1_probe={px(8,16)[2],px(40,16)[2]};",
        """        if (frame.config.settings.synthetic_stereo) {
            m1_probe={px(8,16)[2],px(40,16)[2]};
            m21_image_hash=1469598103934665603ull;
            m21_eye_difference=0;
            for (UINT y=0;y<32;++y) for (UINT x=0;x<32;++x)
                for (UINT c=0;c<3;++c) {
                    const auto v=px(x,y)[c],other=px(x+32,y)[c];
                    m21_image_hash=(m21_image_hash^v)*1099511628211ull;
                    m21_eye_difference+=unsigned(std::abs(int(v)-int(other)));
                }
        }""",
        "M21 copy of both eye result probes")
    marker='    frame.config.settings.synthetic_stereo=false;\n    run(*a,true,Route::copy,"Mono after M1 toggle OFF");'
    block=r'''    // Real FXC + WARP: compare conditioned fine depth to coarse, using the
    // unwarped edge overlay; moving the gaze crop must move the depth edge.
    const auto fine_desc=texture(32,32,DXGI_FORMAT_R32_TYPELESS,D3D12_RESOURCE_FLAG_NONE);
    auto fine_tex=resource(g.device.Get(),fine_desc,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT fine_foot{}; UINT64 fine_bytes{};
    g.device->GetCopyableFootprints(&fine_desc,0,1,0,&fine_foot,nullptr,nullptr,&fine_bytes);
    fine_foot.Footprint.Format=DXGI_FORMAT_R32_FLOAT;
    auto fine_upload=resource(g.device.Get(),buffer(fine_bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    void* fine_map{};
    check(fine_upload->Map(0,&no_reads,&fine_map));
    for (UINT y=0;y<32;++y) {
        auto* row=reinterpret_cast<float*>(static_cast<uint8_t*>(fine_map)+y*fine_foot.Footprint.RowPitch);
        for (UINT x=0;x<32;++x) row[x]=(x>=12 && x<21) ? .24f : .88f;
    }
    fine_upload->Unmap(0,nullptr);
    D3D12_TEXTURE_COPY_LOCATION fine_from{fine_upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    fine_from.PlacedFootprint=fine_foot;
    D3D12_TEXTURE_COPY_LOCATION fine_to{fine_tex.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
    g.cmd->CopyTextureRegion(&fine_to,0,0,0,&fine_from,nullptr);
    transition(g.cmd.Get(),fine_tex.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE);
    g.submit_and_wait();
    m21_fine_depth={fine_tex.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},std::make_shared<const int>(1)};
    frame.config.settings.m2_fovea_depth=true;
    frame.config.settings.m21_depth_debug=true;
    run(*a,false,Route::direct,"M2.1 fine-conditioned depth diagnostic, baseline gaze");
    if (!a->last_stereo_fovea_depth())
        throw std::runtime_error("M2.1 fine depth did not activate in production pipeline");
    const auto fine_hash=m21_image_hash;
    m21_fine_depth={};
    run(*a,false,Route::direct,"M2.1 coarse-only depth diagnostic");
    if (m21_image_hash==fine_hash)
        throw std::runtime_error("M2.1 fine depth did not change the conditioned GPU depth edges");
    m21_fine_depth={fine_tex.Get(),DXGI_FORMAT_R32_FLOAT,{0,0,32,32},{},std::make_shared<const int>(1)};
    const float original_u0=frame.config.layout.u0;
    const float original_u1=frame.config.layout.u1;
    frame.config.layout.u0+=.08f;
    frame.config.layout.u1+=.08f;
    run(*a,false,Route::direct,"M2.1 moved crop depth diagnostic");
    if (m21_image_hash==fine_hash)
        throw std::runtime_error("M2.1 gaze crop movement did not change the sampled fine depth");
    std::cout << "PASS: WARP M2.1 distinct coarse/fine depth and moving crop produce different depth edges\n";

    // Check independent LEFT=0, RIGHT=5 sharpness with zero disparity, so
    // a left/right pixel difference cannot be attributed to the stereo warp.
    const auto patterned_desc=texture(32,32,DXGI_FORMAT_B8G8R8A8_TYPELESS,
                                      D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
    auto patterned=resource(g.device.Get(),patterned_desc,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT patterned_foot{}; UINT64 patterned_bytes{};
    g.device->GetCopyableFootprints(&patterned_desc,0,1,0,&patterned_foot,nullptr,nullptr,&patterned_bytes);
    patterned_foot.Footprint.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
    auto patterned_upload=resource(g.device.Get(),buffer(patterned_bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    void* pattern_map{};
    check(patterned_upload->Map(0,&no_reads,&pattern_map));
    for (UINT y=0;y<32;++y) for(UINT x=0;x<32;++x) {
        uint8_t* pixel=static_cast<uint8_t*>(pattern_map)+y*patterned_foot.Footprint.RowPitch+4*x;
        pixel[0]=0; pixel[1]=((x/2+y/2)&1) ? 25 : 190; pixel[2]=240; pixel[3]=255;
    }
    patterned_upload->Unmap(0,nullptr);
    D3D12_TEXTURE_COPY_LOCATION patterned_from{patterned_upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    patterned_from.PlacedFootprint=patterned_foot;
    D3D12_TEXTURE_COPY_LOCATION patterned_to{patterned.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
    g.cmd->CopyTextureRegion(&patterned_to,0,0,0,&patterned_from,nullptr);
    transition(g.cmd.Get(),patterned.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
    g.submit_and_wait();
    auto saved_primary=primary;
    primary=patterned;
    m21_fine_depth={};
    frame.config.settings.m21_depth_debug=false;
    frame.config.settings.m2_unlinked_sharpen=true;
    frame.config.settings.m2_left_sharpen=0.f;
    frame.config.settings.m2_right_sharpen=5.f;
    frame.config.settings.sharpen_wide=true;
    m1_geometry.k={0.f,0.f};
    run(*a,false,Route::direct,"M2.1 zero-disparity independent sharpening left=0 right=5");
    if (!m21_eye_difference)
        throw std::runtime_error("M2.1 left/right sharpening controls were not independent on GPU");
    std::cout << "PASS: WARP M2.1 truly independent left/right sharpen and extra-wide ring (difference="
              << m21_eye_difference << ")\n";
    // Restore every touched field; the final legacy comparison is intended
    // to prove M1/M2.1 toggles do not disturb the original Mono route.
    primary=saved_primary;
    frame.config.layout.u0=original_u0;
    frame.config.layout.u1=original_u1;
    frame.config.settings.sharpen_wide=false;
    frame.config.settings.m2_fovea_depth=false;
    frame.config.settings.m2_unlinked_sharpen=false;
    frame.config.settings.m21_depth_debug=false;
    frame.config.settings.synthetic_stereo=false;
    run(*a,true,Route::copy,"Mono after M1/M2.1 toggle OFF");'''
    source=substitute(source,marker,block,"M21 tests inserted after M1 WARP tests")
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(source,encoding="utf-8",newline="\n")
    print("Generated M2.1 WARP fine-depth/eye-sharpen extension")

if __name__=="__main__":
    main()

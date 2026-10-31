"""Apply CI79 on top of the generated CI77b sources (ChatGPT's CI77 branch).

CI79 = two independent fixes, each with its own menu switch (both default ON,
both OFF = CI77b exactly):
  1. RIGHT fovea: LEFT camera colour/shading/detail chosen with smooth weights
     (successor of CI78; surface pass bit 128, composite flag +1).
  2. LEFT outer view: where no reconstructed pixel exists, show the RIGHT image
     at the place that LEFT pixel really corresponds to, instead of at the same
     screen position (composite flag +4).

Every change is listed below in readable form. Each `old` text must occur
exactly once; there are no whole-file fingerprints, so unrelated edits upstream
cannot break this layer. Run: python ci79/apply.py BACKEND_ROOT
"""
from pathlib import Path
import shutil
import sys

VR = "src/mods/vr/"

COMPOSITE_HELPERS = r'''// CI79 flags carried in the reserved root constant: 2 = CI77 stabilized depth,
// +1 = RIGHT fovea from the CI79 surface pass, +4 = position-corrected LEFT
// outer view. CI73 conservative mode uses 1 and enables neither.
uint DuoFlags() { return uint(max(_reserved,0.f)+.5f); }
bool DuoDetailPass() { const uint f=DuoFlags(); return f>=3u && (f&1u)!=0u; }
bool DuoLeftEdgeFix() { const uint f=DuoFlags(); return f>=2u && (f&4u)!=0u; }
// CI79: LEFT outer view where no reconstructed pixel exists. Before, the RIGHT
// image was shown at the same screen position, but the two eyes' frustums are
// mirrored and the cameras are 6-7 cm apart, so objects landed in the wrong
// place (wrong field of view, a second hand next to the reconstructed one).
// Each LEFT pixel now searches its row of the RIGHT image for the surface it
// really sees, with the native projection mapping of the legacy modes
// (ndcL = a*ndcR + b + c/z): the nearest consistent surface wins because it
// occludes; with no consistent surface (the RIGHT camera cannot see that spot)
// the farthest surface found nearby is shown, so a near object is never
// painted twice.
float4 RightForLeftFallback(float2 uvL) {
    const float a=StereoEyeX.x, b=StereoEyeX.y, c=StereoEyeX.z;
    if(StereoEyeX.w<.5f || abs(a)<1.e-6f) return RightNative(uvL);
    const float ndcL=uvL.x*2.f-1.f;
    // Search disparity s = 1/z from infinity (0) to 30 cm in 12 steps.
    const float sStep=(1.f/30.f)/11.f;
    float bestS=0.f, farNdc=(ndcL-b)/a, farS=1.e30f;
    bool consistent=false;
    [loop] for(int k=0;k<12;++k) {
        const float s=sStep*float(k);
        const float ndcR=(ndcL-b-c*s)/a;
        if(abs(ndcR)<=1.f) {
            const float z=RightEyeForwardZ(DeviceRightDepth(float2(ndcR*.5f+.5f,uvL.y)));
            const float sz=z>0.f?1.f/z:0.f; // sky or invalid = infinitely far
            if(abs(sz-s)<=.5f*sStep && (!consistent || s>bestS)) {bestS=s;consistent=true;}
            if(sz<farS) {farS=sz;farNdc=ndcR;}
        }
    }
    float ndcOut=farNdc;
    if(consistent) {
        // Refine on the chosen surface; stop if a step would jump to another one.
        float s=bestS;
        [loop] for(int r=0;r<3;++r) {
            const float ndcR=(ndcL-b-c*s)/a;
            const float z=RightEyeForwardZ(DeviceRightDepth(float2(saturate(ndcR*.5f+.5f),uvL.y)));
            const float sNew=z>0.f?1.f/z:0.f;
            if(abs(sNew-s)<=sStep)s=sNew;
        }
        ndcOut=(ndcL-b-c*s)/a;
    }
    return RightNative(float2(saturate(ndcOut*.5f+.5f),uvL.y));
}
float4 SurfaceComposite(float2 uv,bool right) {'''

CHANGES = [
    # 1. Surface shader: include the CI79 passes and route pass 0 with bit 128.
    (VR + "DuoViewSurfaceReproject.hlsl",
     """struct BackwardSurfaceOutput {
    float4 color : SV_TARGET0;
    float depth : SV_DEPTH;
};
""",
     """struct BackwardSurfaceOutput {
    float4 color : SV_TARGET0;
    float depth : SV_DEPTH;
};
#include "DuoViewDetailTransfer.hlsl"
"""),
    # PSBackwardSurface stays exactly as in CI77b. The CI79 passes are separate
    # shader entries (PSLeftLowPass, PSDetailTransferSurface) with their own PSOs,
    # so the existing shader does not grow (the WARP test crashed with it merged).

    # 2. Final composite: flags, corrected LEFT fallback, CI79 RIGHT fovea.
    (VR + "DuoViewStereoCompositeRaster.hlsl",
     "float4 SurfaceComposite(float2 uv,bool right) {",
     COMPOSITE_HELPERS),
    (VR + "DuoViewStereoCompositeRaster.hlsl",
     """    float4 periphery=realRight;
    float peripheralCoverage=0;
    if(!right && reconstructPeriphery) {
        const float4 projected=SyntheticLeftPeriphery.SampleLevel(LinearClamp,saturate(uv),0);
        peripheralCoverage=projected.a;
        if(projected.a>=.995f)periphery=float4(projected.rgb/projected.a,1);
    }""",
     """    float4 periphery=realRight;
    float peripheralCoverage=0;
    const bool leftEdgeFix=!right && DuoLeftEdgeFix() && !InCrop(uv);
    float4 projectedLeft=float4(0,0,0,0);
    if(!right && reconstructPeriphery) {
        projectedLeft=SyntheticLeftPeriphery.SampleLevel(LinearClamp,saturate(uv),0);
        peripheralCoverage=projectedLeft.a;
    }
    if(leftEdgeFix) {
        // CI79: fill only what the reconstruction does not cover, with the
        // RIGHT image at the correct place. Both colours come from the RIGHT
        // camera at matching places, so blending by coverage softens edges
        // instead of doubling them.
        float3 fill=float3(0,0,0);
        [branch] if(peripheralCoverage<.999f)fill=RightForLeftFallback(uv).rgb;
        periphery=float4(projectedLeft.rgb+(1.f-saturate(peripheralCoverage))*fill,1);
    } else if(!right && reconstructPeriphery && peripheralCoverage>=.995f)
        periphery=float4(projectedLeft.rgb/projectedLeft.a,1);"""),
    (VR + "DuoViewStereoCompositeRaster.hlsl",
     """            fovealCoverage=projected.a;
            fovea=realRight;
            if(projected.a>=.995f)fovea=float4(projected.rgb/projected.a,1);""",
     """            fovealCoverage=projected.a;
            fovea=realRight;
            if(DuoDetailPass()) {
                // CI79: already the final colour. Alpha is only the confidence;
                // any alpha > 0 is a valid colour.
                if(projected.a>0.f)fovea=float4(projected.rgb,1);
            } else if(projected.a>=.995f)fovea=float4(projected.rgb/projected.a,1);"""),
    (VR + "DuoViewStereoCompositeRaster.hlsl",
     """    const bool stabilized=_reserved>1.5f;
    const bool chooseFovea=(!right && stabilized)?InCrop(uv):feather>=.25f;
    if(((!right && !chooseFovea && !stabilized) || (right && chooseFovea)) && CI73ProtectedNear(uv)) {
        periphery=realRight;
        if(right)fovea=realRight;
    }
    float4 color=chooseFovea?fovea:periphery;""",
     """    const bool stabilized=_reserved>1.5f;
    const bool detailTransfer=right && DuoDetailPass();
    const bool chooseFovea=(!right && stabilized)?InCrop(uv):feather>=.25f;
    if(((!right && !chooseFovea && !stabilized) || (right && chooseFovea && !detailTransfer)) && CI73ProtectedNear(uv)) {
        periphery=realRight;
        if(right)fovea=realRight;
    }
    // CI79: fade the RIGHT fovea in across the feather instead of a hard seam.
    float4 color=detailTransfer?lerp(periphery,fovea,feather):chooseFovea?fovea:periphery;"""),

    # 3. Surface pass recorder: LEFT low-pass prepass, and no mesh after the
    #    complete full-screen CI79 pass.
    (VR + "DuoViewSurfaceD3D12.hpp",
     "    Ptr<ID3D12PipelineState> reverse_,forward_,backward_;",
     "    Ptr<ID3D12PipelineState> reverse_,forward_,backward_,detail_,lowpass_;\n"
     "    D3D12_GRAPHICS_PIPELINE_STATE_DESC ci79_desc_{};"),
    (VR + "DuoViewSurfaceD3D12.hpp",
     """        if(!check(device->CreateGraphicsPipelineState(&p,IID_PPV_ARGS(&backward_)),"Backward dual-depth fovea PSO"))return false;""",
     """        if(!check(device->CreateGraphicsPipelineState(&p,IID_PPV_ARGS(&backward_)),"Backward dual-depth fovea PSO"))return false;
        // CI79 pipelines are built from this state on first use (create_ci79_pipelines),
        // so nothing extra is compiled while the CI79 switch is off.
        ci79_desc_=p;"""),
    (VR + "DuoViewSurfaceD3D12.hpp",
     "    bool create_map(UINT pass,UINT width,UINT height) {",
     """    bool create_ci79_pipelines() {
        if(detail_&&lowpass_)return true;
        auto p=ci79_desc_;
        // RIGHT fovea pass: own shader, same pipeline state as the backward pass.
        p.PS={detail_transfer_pixel_shader_bytecode,sizeof(detail_transfer_pixel_shader_bytecode)};
        if(!check(device_->CreateGraphicsPipelineState(&p,IID_PPV_ARGS(&detail_)),"CI79 RIGHT fovea PSO"))return false;
        // LEFT crop blurred to RIGHT resolution; colour only, no depth.
        p.PS={left_lowpass_pixel_shader_bytecode,sizeof(left_lowpass_pixel_shader_bytecode)};
        p.DepthStencilState.DepthEnable=FALSE;p.DepthStencilState.DepthWriteMask=D3D12_DEPTH_WRITE_MASK_ZERO;
        p.DSVFormat=DXGI_FORMAT_UNKNOWN;
        return check(device_->CreateGraphicsPipelineState(&p,IID_PPV_ARGS(&lowpass_)),"CI79 LEFT low-pass PSO");
    }
    bool create_map(UINT pass,UINT width,UINT height) {"""),
    (VR + "DuoViewSurfaceD3D12.hpp",
     "        if(!create_map(0,fw,fh)||!create_map(1,pw,ph))return false;",
     """        if(!create_map(0,fw,fh)||!create_map(1,pw,ph))return false;
        if((constants[0].mesh_config[3]&128u)!=0u && !create_ci79_pipelines())return false;"""),
    (VR + "DuoViewSurfaceD3D12.hpp",
     "                cmd->SetPipelineState(backward_.Get());cmd->DrawInstanced(3,1,0,0);",
     "                cmd->SetPipelineState((config[3]&128u)!=0u?detail_.Get():backward_.Get());cmd->DrawInstanced(3,1,0,0);"),
    (VR + "DuoViewSurfaceD3D12.hpp",
     "        for(UINT pass=0;pass<(periphery?2u:1u);++pass) {",
     """        if((constants[0].mesh_config[3]&128u)!=0u) {
            // CI79 prepass: LEFT crop blurred to RIGHT resolution, written into
            // the periphery map. Pass 0 reads it as t5; pass 1 then overwrites it.
            transition(cmd,color_[1].Get(),D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
            const auto low_handle=rtv(1);
            const D3D12_VIEWPORT low_viewport{0,0,float(width_[1]),float(height_[1]),0,1};
            const D3D12_RECT low_rect{0,0,LONG(width_[1]),LONG(height_[1])};
            cmd->RSSetViewports(1,&low_viewport);cmd->RSSetScissorRects(1,&low_rect);
            cmd->OMSetRenderTargets(1,&low_handle,FALSE,nullptr);
            cmd->SetPipelineState(lowpass_.Get());
            cmd->SetGraphicsRootConstantBufferView(2,constants_->GetGPUVirtualAddress());
            cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            cmd->DrawInstanced(3,1,0,0);
            transition(cmd,color_[1].Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        }
        for(UINT pass=0;pass<(periphery?2u:1u);++pass) {"""),
    (VR + "DuoViewSurfaceD3D12.hpp",
     """            if(!backward || (constants[pass].quality[3]>.5f && constants[pass].quality[3]<3.5f))
                cmd->DrawInstanced((config[0]-1)*(config[1]-1)*6,1,0,0);""",
     """            // CI79's RIGHT fovea pass is a complete full-screen result: no mesh after it.
            const bool detail=pass==0 && (config[3]&128u)!=0;
            if(!detail && (!backward || (constants[pass].quality[3]>.5f && constants[pass].quality[3]<3.5f)))
                cmd->DrawInstanced((config[0]-1)*(config[1]-1)*6,1,0,0);"""),

    # 4. Compositor: two switches, used only together with CI77 stabilization.
    (VR + "DuoViewD3D12.hpp",
     "                bool pixelFootprints = false) {",
     "                bool pixelFootprints = false, bool detailTransfer = false, bool leftEdgeFix = false) {"),
    (VR + "DuoViewD3D12.hpp",
     """                    for(float& j:c.jitter)j=0.f; // phase already removed by prepass
                }
            }""",
     """                    for(float& j:c.jitter)j=0.f; // phase already removed by prepass
                }
                if(detailTransfer) {
                    // CI79: RIGHT fovea in one full-screen pass
                    // (bit 2 = full-screen pass, bit 128 = CI79 method).
                    surface_constants[0].mesh_config[3]|=2u|128u;
                    constants.reserved+=1.f;
                }
                if(leftEdgeFix)constants.reserved+=4.f; // corrected LEFT outer fallback
            }"""),

    # 5. Pass the switches from the menu to the compositor and the recorder.
    (VR + "D3D12Component.cpp",
     "const bool pixel_footprints=vr->duoview_pixel_footprints();",
     """const bool pixel_footprints=vr->duoview_pixel_footprints();
                            const bool detail_transfer=vr->duoview_detail_transfer();
                            const bool left_edge_fix=vr->duoview_left_edge_fix();"""),
    (VR + "D3D12Component.cpp",
     "ngx_guides=depths.ngx_guides,stereo_quality,stabilize_depth,depth_history_weight,pixel_footprints](",
     "ngx_guides=depths.ngx_guides,stereo_quality,stabilize_depth,depth_history_weight,pixel_footprints,detail_transfer,left_edge_fix]("),
    (VR + "D3D12Component.cpp",
     "ngx_guides,stereo_quality,stabilize_depth,depth_history_weight,pixel_footprints);",
     "ngx_guides,stereo_quality,stabilize_depth,depth_history_weight,pixel_footprints,detail_transfer,left_edge_fix);"),
    (VR + "D3D12Component.cpp",
     '(pixel_footprints?"CI77b_LEFT_PIXEL_FOOTPRINTS":"CI77_HIGH_RES_LEFT_GEOMETRY")',
     '(detail_transfer?"CI79_LEFT_SHADING_SMOOTH_WEIGHTS":pixel_footprints?"CI77b_LEFT_PIXEL_FOOTPRINTS":"CI77_HIGH_RES_LEFT_GEOMETRY")'),
    (VR + "D3D12Component.cpp",
     '<<",\\"pixel_footprints_requested\\":"<<(pixel_footprints?"true":"false")',
     '<<",\\"pixel_footprints_requested\\":"<<(pixel_footprints?"true":"false")\n'
     '                                    <<",\\"ci79_right_fovea_requested\\":"<<(detail_transfer?"true":"false")\n'
     '                                    <<",\\"ci79_left_edge_fix_requested\\":"<<(left_edge_fix?"true":"false")'),

    # 6. Menu switches (default ON), saved with the other settings.
    ("src/mods/VR.hpp",
     "    bool duoview_pixel_footprints() const { return m_duo_pixel_footprints->value(); }",
     """    bool duoview_pixel_footprints() const { return m_duo_pixel_footprints->value(); }
    bool duoview_detail_transfer() const { return m_duo_detail_transfer->value(); }
    bool duoview_left_edge_fix() const { return m_duo_left_edge_fix->value(); }"""),
    ("src/mods/VR.hpp",
     '    const ModToggle::Ptr m_duo_pixel_footprints{ModToggle::create(generate_name("DuoViewPixelFootprintsCI77b"),true)};',
     '''    const ModToggle::Ptr m_duo_pixel_footprints{ModToggle::create(generate_name("DuoViewPixelFootprintsCI77b"),true)};
    const ModToggle::Ptr m_duo_detail_transfer{ModToggle::create(generate_name("DuoViewRightFoveaCI79"),true)};
    const ModToggle::Ptr m_duo_left_edge_fix{ModToggle::create(generate_name("DuoViewLeftEdgeFixCI79"),true)};'''),
    ("src/mods/VR.hpp",
     "*m_duo_depth_stabilization, *m_duo_pixel_footprints, ",
     "*m_duo_depth_stabilization, *m_duo_pixel_footprints, *m_duo_detail_transfer, *m_duo_left_edge_fix, "),
    ("src/mods/VR.cpp",
     '                        m_duo_pixel_footprints->draw("CI77b: Preserve thin geometry (pixel footprints)");',
     '''                        m_duo_detail_transfer->draw("CI79: RIGHT eye centre from LEFT camera, smooth (OFF = CI77b)");
                        m_duo_left_edge_fix->draw("CI79: LEFT eye outer view at correct position (OFF = CI77b)");
                        m_duo_pixel_footprints->draw("CI77b: Preserve thin geometry (pixel footprints)");'''),
]

ADDED = [("DuoViewDetailTransfer.hlsl", VR + "DuoViewDetailTransfer.hlsl")]


def apply(root):
    root = Path(root)
    here = Path(__file__).resolve().parent
    pending = {}
    for rel, old, new in CHANGES:
        path = root / rel
        text = pending.get(path)
        if text is None:
            text = path.read_text(encoding="utf-8")
        count = text.count(old)
        if count != 1:
            raise RuntimeError(f"CI79 anchor found {count} times (need exactly 1) in {rel}:\n{old[:160]}")
        text = text.replace(old, new)
        pending[path] = text
    for path, text in pending.items():
        path.write_text(text, encoding="utf-8")  # same newline handling as CI77
    for source, target in ADDED:
        shutil.copyfile(here / source, root / target)
    print(f"CI79 applied: {len(CHANGES)} anchored edits in {len(pending)} files, {len(ADDED)} new file; "
          "RIGHT fovea from LEFT camera with smooth weights; corrected LEFT outer fallback")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python ci79/apply.py BACKEND_ROOT")
    apply(sys.argv[1])

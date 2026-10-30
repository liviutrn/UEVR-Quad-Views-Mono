"""Apply CI78 (RIGHT base + LEFT detail) on top of the generated CI77 sources.

Every change is listed below in readable form. Each `old` text must occur exactly
once in its file; nothing depends on whole-file fingerprints, so an unrelated
upstream edit (for example the build commit CI75 stamps into the recorder) can
no longer break this layer. Run: python ci78/apply.py BACKEND_ROOT
"""
from pathlib import Path
import shutil
import sys

VR = "src/mods/vr/"

CHANGES = [
    # 1. Surface shader: include the new pass and route to it with bit 64.
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
    (VR + "DuoViewSurfaceReproject.hlsl",
     """BackwardSurfaceOutput PSBackwardSurface(VertexOut i) {
    if((MeshConfig.w&16u)!=0u)return PSResearchBackwardSurface(i);""",
     """BackwardSurfaceOutput PSBackwardSurface(VertexOut i) {
    if((MeshConfig.w&64u)!=0u)return PSDetailTransferSurface(i);
    if((MeshConfig.w&16u)!=0u)return PSResearchBackwardSurface(i);"""),

    # 2. Final composite: use the fused colour (alpha = confidence only) and fade
    #    the borrowed detail across the feather instead of a hard seam.
    (VR + "DuoViewStereoCompositeRaster.hlsl",
     """            fovealCoverage=projected.a;
            fovea=realRight;
            if(projected.a>=.995f)fovea=float4(projected.rgb/projected.a,1);""",
     """            fovealCoverage=projected.a;
            fovea=realRight;
            if(_reserved>2.5f) {
                // CI78: already RIGHT base + LEFT detail. Alpha is only the
                // detail confidence; any alpha > 0 is a valid colour.
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
    const bool detailTransfer=right && _reserved>2.5f;
    const bool chooseFovea=(!right && stabilized)?InCrop(uv):feather>=.25f;
    if(((!right && !chooseFovea && !stabilized) || (right && chooseFovea && !detailTransfer)) && CI73ProtectedNear(uv)) {
        periphery=realRight;
        if(right)fovea=realRight;
    }
    // CI78: both sides share the real RIGHT image, so fading the borrowed
    // detail in across the feather cannot create a second silhouette.
    float4 color=detailTransfer?lerp(periphery,fovea,feather):chooseFovea?fovea:periphery;"""),

    # 3. Surface pass recorder: the detail pass is complete, skip the LEFT mesh.
    (VR + "DuoViewSurfaceD3D12.hpp",
     """            if(!backward || (constants[pass].quality[3]>.5f && constants[pass].quality[3]<3.5f))
                cmd->DrawInstanced((config[0]-1)*(config[1]-1)*6,1,0,0);""",
     """            // CI78 detail transfer is a complete full-screen result: no mesh after it.
            const bool detail=pass==0 && (config[3]&64u)!=0;
            if(!detail && (!backward || (constants[pass].quality[3]>.5f && constants[pass].quality[3]<3.5f)))
                cmd->DrawInstanced((config[0]-1)*(config[1]-1)*6,1,0,0);"""),

    # 3b. LEFT low-pass prepass (LEFT crop blurred onto the RIGHT pixel grid).
    (VR + "DuoViewSurfaceD3D12.hpp",
     "    Ptr<ID3D12PipelineState> reverse_,forward_,backward_;",
     "    Ptr<ID3D12PipelineState> reverse_,forward_,backward_,lowpass_;"),
    (VR + "DuoViewSurfaceD3D12.hpp",
     """        if(!check(device->CreateGraphicsPipelineState(&p,IID_PPV_ARGS(&backward_)),"Backward dual-depth fovea PSO"))return false;""",
     """        if(!check(device->CreateGraphicsPipelineState(&p,IID_PPV_ARGS(&backward_)),"Backward dual-depth fovea PSO"))return false;
        // CI78: LEFT crop blurred to RIGHT resolution; colour only, no depth.
        p.PS={left_lowpass_pixel_shader_bytecode,sizeof(left_lowpass_pixel_shader_bytecode)};
        p.DepthStencilState.DepthEnable=FALSE;p.DepthStencilState.DepthWriteMask=D3D12_DEPTH_WRITE_MASK_ZERO;
        p.DSVFormat=DXGI_FORMAT_UNKNOWN;
        if(!check(device->CreateGraphicsPipelineState(&p,IID_PPV_ARGS(&lowpass_)),"CI78 LEFT low-pass PSO"))return false;"""),
    (VR + "DuoViewSurfaceD3D12.hpp",
     "        if(device_.Get()!=device||srgb_!=srgb||!root_||!reverse_||!forward_||!backward_||!constants_||!rtv_||!dsv_) {",
     "        if(device_.Get()!=device||srgb_!=srgb||!root_||!reverse_||!forward_||!backward_||!lowpass_||!constants_||!rtv_||!dsv_) {"),
    (VR + "DuoViewSurfaceD3D12.hpp",
     "        for(UINT pass=0;pass<(periphery?2u:1u);++pass) {",
     """        if((constants[0].mesh_config[3]&64u)!=0u) {
            // CI78 prepass: LEFT crop blurred to RIGHT resolution, written into
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

    # 4. Compositor: new switch, enabled only together with CI77 stabilization.
    (VR + "DuoViewD3D12.hpp",
     "bool stabilizeDepth = false, float depthHistoryWeight = .75f) {",
     "bool stabilizeDepth = false, float depthHistoryWeight = .75f, bool detailTransfer = false) {"),
    (VR + "DuoViewD3D12.hpp",
     """                    for(float& j:c.jitter)j=0.f; // phase already removed by prepass
                }
            }""",
     """                    for(float& j:c.jitter)j=0.f; // phase already removed by prepass
                }
                if(detailTransfer) {
                    // CI78: RIGHT fovea = real RIGHT image + LEFT fine detail in
                    // one full-screen pass (bit 2 = full-screen pass, bit 64 = method).
                    surface_constants[0].mesh_config[3]|=2u|64u;
                    constants.reserved=3.f;
                }
            }"""),

    # 5. Pass the setting from the menu to the compositor and the recorder.
    (VR + "D3D12Component.cpp",
     "const float depth_history_weight=vr->duoview_depth_temporal()?vr->duoview_depth_history_weight():0.f;",
     """const float depth_history_weight=vr->duoview_depth_temporal()?vr->duoview_depth_history_weight():0.f;
                            const bool detail_transfer=vr->duoview_detail_transfer();"""),
    (VR + "D3D12Component.cpp",
     "ngx_guides=depths.ngx_guides,stereo_quality,stabilize_depth,depth_history_weight](",
     "ngx_guides=depths.ngx_guides,stereo_quality,stabilize_depth,depth_history_weight,detail_transfer]("),
    (VR + "D3D12Component.cpp",
     "ngx_guides,stereo_quality,stabilize_depth,depth_history_weight);",
     "ngx_guides,stereo_quality,stabilize_depth,depth_history_weight,detail_transfer);"),
    (VR + "D3D12Component.cpp",
     'depth_stabilized_recorded && effective_stereo_mode>=4u?"CI77_HIGH_RES_LEFT_GEOMETRY":',
     'depth_stabilized_recorded && effective_stereo_mode>=4u?(detail_transfer?"CI78_RIGHT_BASE_LEFT_DETAIL":"CI77_HIGH_RES_LEFT_GEOMETRY"):'),
    (VR + "D3D12Component.cpp",
     '<<",\\"depth_stabilization_requested\\":"<<(stabilize_depth?"true":"false")',
     '<<",\\"depth_stabilization_requested\\":"<<(stabilize_depth?"true":"false")\n'
     '                                    <<",\\"detail_transfer_requested\\":"<<(detail_transfer?"true":"false")'),

    # 6. Menu toggle (default ON), saved with the other settings.
    ("src/mods/VR.hpp",
     "    bool duoview_depth_temporal() const { return m_duo_depth_temporal->value(); }",
     """    bool duoview_depth_temporal() const { return m_duo_depth_temporal->value(); }
    bool duoview_detail_transfer() const { return m_duo_detail_transfer->value(); }"""),
    ("src/mods/VR.hpp",
     '    const ModSlider::Ptr m_duo_depth_history{ModSlider::create(generate_name("DuoViewDepthHistoryPercentCI77"),0.f,90.f,75.f)};',
     '''    const ModSlider::Ptr m_duo_depth_history{ModSlider::create(generate_name("DuoViewDepthHistoryPercentCI77"),0.f,90.f,75.f)};
    const ModToggle::Ptr m_duo_detail_transfer{ModToggle::create(generate_name("DuoViewDetailTransferCI78"),true)};'''),
    ("src/mods/VR.hpp",
     "*m_duo_depth_stabilization, *m_duo_depth_temporal, *m_duo_depth_history, ",
     "*m_duo_depth_stabilization, *m_duo_depth_temporal, *m_duo_depth_history, *m_duo_detail_transfer, "),
    ("src/mods/VR.cpp",
     """                        if(m_duo_depth_temporal->value())m_duo_depth_history->draw("Depth history weight (%)");
                    }""",
     """                        if(m_duo_depth_temporal->value())m_duo_depth_history->draw("Depth history weight (%)");
                        m_duo_detail_transfer->draw("CI78: RIGHT fovea = real RIGHT image + LEFT detail (OFF = CI77)");
                    }"""),
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
            raise RuntimeError(f"CI78 anchor found {count} times (need exactly 1) in {rel}:\n{old[:160]}")
        text = text.replace(old, new)
        pending[path] = text
    for path, text in pending.items():
        path.write_text(text, encoding="utf-8")  # same newline handling as CI77
    for source, target in ADDED:
        shutil.copyfile(here / source, root / target)
    print(f"CI78 applied: {len(CHANGES)} anchored edits in {len(pending)} files, "
          f"{len(ADDED)} new file; RIGHT fovea = real RIGHT image + LEFT detail")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python ci78/apply.py BACKEND_ROOT")
    apply(sys.argv[1])

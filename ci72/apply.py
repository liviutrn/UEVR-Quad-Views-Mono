"""CI72: research-derived right-eye target-depth inverse gather.
This overlays CI71 without rewriting or removing its default method.
Unverified NGX camera/frame pairing remains gated by the CI70 opt-in.
"""
from pathlib import Path
import sys

def replace(path, old, new):
    s=path.read_text(encoding="utf-8")
    if s.count(old)!=1:
        raise RuntimeError(f"CI72 source anchor mismatch {path}: {old[:100]!r} count={s.count(old)}")
    path.write_text(s.replace(old,new,1),encoding="utf-8")

def apply(root):
    vr=root/"src/mods/vr"
    hdr=root/"src/mods/VR.hpp"
    replace(hdr,
        "    bool duoview_left_anchored_mode() const { return m_duo_left_anchor->value(); }",
        """    bool duoview_left_anchored_mode() const { return m_duo_left_anchor->value(); }
    bool duoview_research_backward_mode() const { return m_duo_research_backward->value(); }""")
    replace(hdr,
        '    const ModToggle::Ptr m_duo_left_anchor{ModToggle::create(generate_name("DuoViewLeftAnchoredReprojection"), true)};',
        '''    const ModToggle::Ptr m_duo_left_anchor{ModToggle::create(generate_name("DuoViewLeftAnchoredReprojection"), true)};
    const ModToggle::Ptr m_duo_research_backward{ModToggle::create(generate_name("DuoViewResearchTargetDepthGather"), false)};''')
    replace(hdr,"*m_duo_foreground_refinement, *m_duo_left_anchor, *m_duo_visibility_absolute,",
        "*m_duo_foreground_refinement, *m_duo_left_anchor, *m_duo_research_backward, *m_duo_visibility_absolute,")
    ui=root/"src/mods/VR.cpp"
    replace(ui,"                    m_duo_left_anchor->value()=true;",
        "                    m_duo_left_anchor->value()=true;\n                    m_duo_research_backward->value()=false;")
    replace(ui,'                m_duo_foreground_refinement->draw("Preserve fine foreground (extra GPU work)");',
        '''                m_duo_research_backward->draw("Mode 5 strategy: RESEARCH target-RIGHT-depth inverse gather (OFF = CI71)");
                ImGui::TextWrapped("OFF: original CI71 LEFT-forward anchored method, unchanged. ON: research-guided 2x2 RIGHT-depth hypothesis search, high-resolution LEFT-depth consistency, native RIGHT-color fallback, no invented depth/disparity. Applies to true stereo Mode 5; change live for A/B. Both strategies require manual DLSS pins.");
                m_duo_foreground_refinement->draw("Preserve fine foreground (extra GPU work)");''')
    comp=vr/"D3D12Component.cpp"
    replace(comp,"vr->duoview_left_anchored_mode()?2.f:",
        "vr->duoview_research_backward_mode()?4.f:vr->duoview_left_anchored_mode()?2.f:")
    gl=vr/"DuoViewD3D12.hpp"
    replace(gl,"const bool left_anchored=pass==0 && quality[3]>1.5f;",
        "const bool left_anchored=pass==0 && quality[3]>1.5f && quality[3]<3.5f;")
    replace(gl,"            if(left_anchored)c.mesh_config[3]|=8u;",
        "            if(left_anchored)c.mesh_config[3]|=8u;\n            if(pass==0 && quality[3]>3.5f)c.mesh_config[3]|=16u;")
    gp=vr/"DuoViewSurfaceD3D12.hpp"
    replace(gp,"if(!backward || constants[pass].quality[3]>.5f)",
        "if(!backward || (constants[pass].quality[3]>.5f && constants[pass].quality[3]<3.5f))")
    sh=vr/"DuoViewSurfaceReproject.hlsl"
    anchor="BackwardSurfaceOutput PSBackwardSurface(VertexOut i) {"
    research=r'''
// CI72 research strategy -- right-eye target-depth guided inverse gathering.
// The alternative CI71 path below is left untouched and is selected by clearing
// MeshConfig.w bit 16. All depths use the real per-eye projection transforms.
BackwardSurfaceOutput PSResearchBackwardSurface(VertexOut i) {
    BackwardSurfaceOutput outp=(BackwardSurfaceOutput)0;
    outp.color=float4(0,0,0,0);
    outp.depth=(MeshConfig.w&4u)!=0u ? 0.f : 1.f;
    const float2 targetUV=CropUv.xy+i.uv*(CropUv.zw-CropUv.xy);
    if(any(targetUV<0.f)||any(targetUV>1.f))return outp;
    const float2 depthCoord=RightDepthRect.xy+(targetUV+MeshJitter.zw)*RightDepthRect.zw-.5f;
    const int2 origin=int2(floor(depthCoord));
    if(any(origin<ActiveDepthMin(RightDepthRect)) ||
       any(origin+int2(1,1)>ActiveDepthMax(RightDepthRect)))return outp;
    const float2 f=frac(depthCoord);
    const float4 targetWeights=float4((1.f-f.x)*(1.f-f.y),f.x*(1.f-f.y),
                               (1.f-f.x)*f.y,f.x*f.y);
    float bestScore=1.e30f, secondScore=1.e30f, bestZ=-1.f, secondZ=-1.f;
    float bestDepth=0.f;
    float2 bestUV=0;
    bool found=false;
    // Each of four actual RIGHT surfaces is a hypothesis. NEVER bilinearly
    // average unrelated foreground/background depths into fictional geometry.
    [unroll] for(int n=0;n<4;++n) {
        const int2 p=origin+int2(n&1,n>>1);
        const float raw=RightSourceDepth.Load(int3(p,0));
        const float targetZ=RightEyeForwardZ(raw);
        if(!isfinite(targetZ)||targetZ<=0.f)continue;
        const float nd=(raw-DepthViewportRanges.z)/
                        (DepthViewportRanges.w-DepthViewportRanges.z);
        if(!isfinite(nd)||nd<0.f||nd>1.f)continue;
        const float4 eye4=mul(TargetEyeFromClip,
                        float4(2.f*targetUV.x-1.f,1.f-2.f*targetUV.y,nd,1.f));
        if(!all(isfinite(eye4))||abs(eye4.w)<1.e-8f)continue;
        const float3 eye=eye4.xyz/eye4.w;
        const float4 proj=mul(SourceClipFromTargetEye,float4(eye,1.f));
        if(!all(isfinite(proj))||proj.w<=1.e-7f)continue;
        const float2 sourceUV=float2(.5f+.5f*proj.x/proj.w,
                                    .5f-.5f*proj.y/proj.w);
        if(any(sourceUV<0.f)||any(sourceUV>1.f))continue;
        // Physical LEFT forward Z, with exactly the captured LEFT projection.
        const float sourceZ=(proj.w-StereoLeftDepthZ.w)/StereoLeftDepthZ.z;
        if(!isfinite(sourceZ)||sourceZ<=0.f)continue;
        const float2 leftCoord=LeftDepthRect.xy+
                       (sourceUV+MeshJitter.xy)*LeftDepthRect.zw-.5f;
        const int2 samplePos=int2(floor(leftCoord+.5f));
        // Four-neighbour source depth visibility check + centre. A nearer
        // LEFT object indicates this RIGHT point is disoccluded in LEFT;
        // reject and use real RIGHT color instead.
        float matchError=1.e30f;
        bool occluded=false;
        const float tol=MeshQuality.x+MeshQuality.y*sourceZ;
        [unroll] for(int k=0;k<5;++k) {
            const int2 shift=k==0?int2(0,0):
                k==1?int2(-1,0):k==2?int2(1,0):
                k==3?int2(0,-1):int2(0,1);
            const float sceneZ=DuoLeftVisibilityZ(samplePos+shift);
            if(sceneZ<=0.f) {occluded=true;break;}
            if(sceneZ+tol<sourceZ){occluded=true;break;}
            matchError=min(matchError,abs(sceneZ-sourceZ));
        }
        if(occluded || matchError>tol)continue;
        // Depth agreement is primary; target-sample footprint is secondary.
        // Within one target depth footprint, stay near measured samples.
        const float footprint=1.f-targetWeights[n];
        const float score=matchError/max(tol,1.e-5f)+.35f*footprint;
        if(score<bestScore) {
            secondScore=bestScore;secondZ=bestZ;
            bestScore=score;bestDepth=nd;bestZ=targetZ;
            bestUV=sourceUV;found=true;
        } else if(score<secondScore) {
            secondScore=score;secondZ=targetZ;
        }
    }
    if(!found)return outp; // native RIGHT eye is the correct fallback.
    // If both foreground and background pass LEFT consistency with similar
    // scores, the edge is intrinsically ambiguous at low RIGHT resolution.
    // Prefer actual RIGHT color rather than alternate 3D surfaces per frame.
    if(secondZ>0.f && abs(bestZ-secondZ)>
        MeshQuality.x+MeshQuality.y*min(bestZ,secondZ) &&
        secondScore-bestScore<.35f)return outp;
    outp.color=float4(LeftNative(CropUv.xy+
        bestUV*(CropUv.zw-CropUv.xy)).rgb,1.f);
    outp.depth=bestDepth;
    return outp;
}
'''
    replace(sh,anchor,research+"\n"+anchor+"\n    if((MeshConfig.w&16u)!=0u)return PSResearchBackwardSurface(i);")
    print("CI72: research inverse-gather alternative; CI71 still exactly selectable",flush=True)

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: ci72/apply.py BACKEND")
    apply(Path(sys.argv[1]).resolve())

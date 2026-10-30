// Source-depth surface reconstruction. No guessed inverse fixed-point warp.
// Continuous source-depth triangles are projected into the target camera and
// compete in its hardware depth buffer. Source texture coordinates remain
// projective, so low-resolution depth does not downsample source color.
#include "DuoViewStereoCompositeRaster.hlsl"

cbuffer SurfaceConfig : register(b1) {
    row_major float4x4 SourceEyeFromClip;
    row_major float4x4 TargetClipFromSourceEye;
    row_major float4x4 TargetFullClipFromSourceEye;
    row_major float4x4 TargetEyeFromClip;
    row_major float4x4 SourceClipFromTargetEye;
    uint4 MeshConfig;      // depth sample columns/rows; sourceLeft; target depth present
    float4 MeshEdge;       // abs/relative discontinuity bound; min/max forward Z
    float4 MeshVisibility;// abs/relative occluder bound; target clip-W coefficients C,D
    float4 MeshJitter; // source/target depth jitter in active-input UV units
    float4 MeshQuality; // absolute cm, relative fraction, edge radius, foreground refinement
};
struct SurfaceVertex {
    float4 position : SV_POSITION;
    float3 sourceQ : TEXCOORD0;
    float4 targetFullClip : TEXCOORD1;
    float clip : SV_ClipDistance0;
};
float4 MeshDepthRect() { return MeshConfig.z!=0 ? LeftDepthRect : RightDepthRect; }
float MeshDeviceDepth(int2 p) {
    return MeshConfig.z!=0 ? LeftSourceDepth.Load(int3(p,0)) : RightSourceDepth.Load(int3(p,0));
}
bool MeshPoint(int2 pixel,out float3 eye,out float2 uv,out float clipW) {
    const float4 rect=MeshDepthRect();
    uv=(float2(pixel)+0.5f-rect.xy)/rect.zw-MeshJitter.xy;
    eye=0;clipW=0;
    const float2 range=MeshConfig.z!=0 ? DepthViewportRanges.xy : DepthViewportRanges.zw;
    const float d=(MeshDeviceDepth(pixel)-range.x)/(range.y-range.x);
    if(!isfinite(d)||d<0||d>1||any(uv<0)||any(uv>1))return false;
    const float4 unprojected=mul(SourceEyeFromClip,float4(2*uv.x-1,1-2*uv.y,d,1));
    if(!all(isfinite(unprojected))||abs(unprojected.w)<1.e-9f)return false;
    eye=unprojected.xyz/unprojected.w;clipW=1.0f/unprojected.w;
    return all(isfinite(eye))&&clipW>0&&eye.z>=MeshEdge.z&&eye.z<=MeshEdge.w;
}
SurfaceVertex VSSurface(uint vertexId:SV_VertexID) {
    SurfaceVertex o=(SurfaceVertex)0;
    o.position=float4(0,0,0,1);o.clip=-1;
    const uint cellsX=MeshConfig.x-1;
    const uint cell=vertexId/6,corner=vertexId%6;
    // A/B opt-in: forward-project the entire LEFT source on a 2-pixel
    // grid. Preserve native projection/camera baseline and true metric Z.
    const uint stride=(MeshConfig.w&8u)!=0u ? 2u : 1u;
    const int2 base=ActiveDepthMin(MeshDepthRect())+
        int2(cell%cellsX,cell/cellsX)*int(stride);
    if(MeshConfig.z!=0 && (MeshConfig.w&2u)!=0 && (MeshConfig.w&8u)==0) {
        // Backward gather supplies the smooth interior. Only source depth edges
        // need the optional fine-foreground mesh; skip matrix work elsewhere.
        const int radius=max(1,int(ceil(MeshQuality.z)));
        const int2 offsets[5]={int2(0,0),int2(-radius,0),int2(radius,0),int2(0,-radius),int2(0,radius)};
        float nearZ=1.e30f,farZ=0;
        bool valid=true;
        [unroll] for(uint n=0;n<5;++n) {
            const int2 pixel=clamp(base+offsets[n],ActiveDepthMin(MeshDepthRect()),ActiveDepthMax(MeshDepthRect()));
            const float z=LeftEyeForwardZ(MeshDeviceDepth(pixel));
            valid=valid && z>0;
            if(z>0){nearZ=min(nearZ,z);farZ=max(farZ,z);}
        }
        if(valid && farZ-nearZ<=MeshQuality.x+MeshQuality.y*nearZ)return o;
    }
    // Each triangle is rejected independently. Never stretch foreground into
    // background across a depth discontinuity to conceal a disocclusion.
    const int step=int(stride);
    const int2 offsets[6]={int2(0,0),int2(step,0),int2(0,step),
                           int2(step,0),int2(step,step),int2(0,step)};
    const uint tri=(corner/3)*3;
    float3 points[3];float2 uvs[3];float ws[3];
    [unroll] for(uint k=0;k<3;++k)
        if(!MeshPoint(clamp(base+offsets[tri+k],ActiveDepthMin(MeshDepthRect()),
                    ActiveDepthMax(MeshDepthRect())),points[k],uvs[k],ws[k]))return o;
    if(stride>1u && MeshConfig.z!=0u) {
        // Critical silhouette guard: stride-2 geometry must not miss a
        // one-texel fine foreground. Inspect cell edge midpoints + centre
        // BEFORE forwarding LEFT geometry into RIGHT eye. We may discard
        // uncertain triangles but must never stretch across real depth.
        float guardNear=min(points[0].z,min(points[1].z,points[2].z));
        float guardFar=max(points[0].z,max(points[1].z,points[2].z));
        const int2 mids[5]={int2(1,0),int2(0,1),int2(1,1),
                             int2(2,1),int2(1,2)};
        [unroll] for(int p=0;p<5;++p) {
            const int2 at=clamp(base+mids[p],ActiveDepthMin(MeshDepthRect()),
                                ActiveDepthMax(MeshDepthRect()));
            const float z=LeftEyeForwardZ(MeshDeviceDepth(at));
            if(z<=0.f)return o;
            guardNear=min(guardNear,z);guardFar=max(guardFar,z);
        }
        if(guardFar-guardNear>MeshEdge.x+MeshEdge.y*guardNear)return o;
    }
    const float nearest=min(points[0].z,min(points[1].z,points[2].z));
    const float farthest=max(points[0].z,max(points[1].z,points[2].z));
    if(farthest-nearest>MeshEdge.x+MeshEdge.y*nearest)return o;
    const uint index=corner%3;
    o.position=mul(TargetClipFromSourceEye,float4(points[index],1));
    o.targetFullClip=mul(TargetFullClipFromSourceEye,float4(points[index],1));
    // GPU perspective interpolation alone is insufficient on a sloped
    // source surface: interpolate homogeneous source coordinates, divide in PS.
    o.sourceQ=float3(uvs[index]*ws[index],ws[index]);
    if(!all(isfinite(o.position))||o.position.w<=1.e-7f)return o;
    o.clip=1;
    return o;
}
bool TargetCertainlyOccludes(float2 targetUV,float candidateZ) {
    if((MeshConfig.w&1u)==0)return false;
    const float4 rect=MeshConfig.z!=0 ? RightDepthRect : LeftDepthRect;
    const float2 coordinate=rect.xy+(targetUV+MeshJitter.zw)*rect.zw-0.5f;
    const int2 first=int2(floor(coordinate));
    const float2 range=MeshConfig.z!=0 ? DepthViewportRanges.zw : DepthViewportRanges.xy;
    const float4 projection=MeshConfig.z!=0 ? StereoDepthZ : StereoLeftDepthZ;
    // NGX hybrid refinement must honor any plausible target foreground.
    // Keep the old all-four veto for the independent legacy forward renderer:
    // its sloped-plane sampling contract intentionally uses that wider test.
    const bool stabilized=(MeshConfig.w&32u)!=0u;
    const bool hybrid=(MeshConfig.w&2u)!=0;
    float nearTarget=1.e30f,farTarget=0.f;uint validTarget=0u;
    bool allOcclude=true;
    uint targetFarther=0;
    [unroll] for(int y=0;y<2;++y)[unroll] for(int x=0;x<2;++x) {
        const int2 p=first+int2(x,y);
        if(any(p<ActiveDepthMin(rect))||any(p>ActiveDepthMax(rect))) {
            if(!hybrid)return false;
            continue;
        }
        const float depth=MeshConfig.z!=0 ? RightSourceDepth.Load(int3(p,0)) : LeftSourceDepth.Load(int3(p,0));
        const float z=EyeForwardZ(depth,projection,range);
        if(z>0.f){nearTarget=min(nearTarget,z);farTarget=max(farTarget,z);++validTarget;}
        const bool occludes=z>0 && z+MeshVisibility.x+MeshVisibility.y*z<candidateZ;
        // A single proven nearer RIGHT sample vetoes LEFT background.
        if(hybrid && occludes)return true;
        if(z>0 && candidateZ+MeshVisibility.x+MeshVisibility.y*candidateZ<z)
            ++targetFarther;
        allOcclude=allOcclude && occludes;
    }
    // Veto unsupported LEFT-only foreground when at least 3 of 4
    // target-depth samples prove the LEFT surface is unexpectedly nearer.
    // Coarse RIGHT depth is a visibility constraint, never right-foveal geometry.
    // Mixed-depth footprints cannot prove a high-resolution LEFT surface hidden.
    if(stabilized)return validTarget==4u &&
        farTarget-nearTarget<=MeshVisibility.x+MeshVisibility.y*nearTarget && allOcclude;
    return hybrid ? ((MeshConfig.w&8u)!=0u && targetFarther>=3u) : allOcclude;
}
float4 PSSurface(SurfaceVertex i):SV_TARGET0 {
    if(i.sourceQ.z<=1.e-7f||i.targetFullClip.w<=1.e-7f)discard;
    const float2 sourceUV=i.sourceQ.xy/i.sourceQ.z;
    if(any(sourceUV<0)||any(sourceUV>1))discard;
    const float2 ndc=i.targetFullClip.xy/i.targetFullClip.w;
    const float2 targetUV=float2(.5f+.5f*ndc.x,.5f-.5f*ndc.y);
    if(any(targetUV<0)||any(targetUV>1))discard;
    const float targetZ=(i.targetFullClip.w-MeshVisibility.w)/MeshVisibility.z;
    if(!isfinite(targetZ)||targetZ<=0||TargetCertainlyOccludes(targetUV,targetZ))discard;
    // CI73 conservative LEFT periphery: never forward-splat near viewmodels.
    // Their native RIGHT silhouette is shared in BOTH peripheral eye outputs;
    // painting a shifted copy would necessarily create doubled hands.
    if(MeshConfig.z==0u && (MeshConfig.w&32u)==0u && MeshQuality.w>=7.5f && targetZ<80.f)discard;
    const float4 color=MeshConfig.z!=0
        ? LeftNative(CropUv.xy+sourceUV*(CropUv.zw-CropUv.xy))
        : RightNative(sourceUV);
    return float4(color.rgb,1); // alpha is final geometric coverage, not color alpha
}


// Target-guided right-fovea reconstruction. Both physical eyes' depth is used:
// RIGHT tells us which surface is visible; LEFT verifies it is also visible in
// the high-resolution source. Alpha zero means use the actual RIGHT image.
struct BackwardSurfaceOutput {
    float4 color : SV_TARGET0;
    float depth : SV_DEPTH;
};
#include "DuoViewDetailTransfer.hlsl"
float DuoLeftVisibilityZ(int2 pixel) {
    if(any(pixel<ActiveDepthMin(LeftDepthRect))||any(pixel>ActiveDepthMax(LeftDepthRect)))return -1;
    return LeftEyeForwardZ(LeftSourceDepth.Load(int3(pixel,0)));
}

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
    // Conservatively protect real RIGHT-eye foreground before testing which
    // LEFT-eye color sample could reproject to this target pixel. A single
    // nearer measured RIGHT surface vetoes all farther neighboring hypotheses.
    // Otherwise a background candidate can pass LEFT validation and erase a
    // one-texel foreground object in the RIGHT image.
    float nearestMeasuredZ=1.e30f;
    [unroll] for(int t=0;t<4;++t) {
        const float z=RightEyeForwardZ(RightSourceDepth.Load(
                         int3(origin+int2(t&1,t>>1),0)));
        if(isfinite(z)&&z>0.f)nearestMeasuredZ=min(nearestMeasuredZ,z);
    }
    if(nearestMeasuredZ>=1.e29f)return outp;
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
        if(targetZ>nearestMeasuredZ+MeshQuality.x+
                       MeshQuality.y*nearestMeasuredZ)continue;
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

BackwardSurfaceOutput PSBackwardSurface(VertexOut i) {
    if((MeshConfig.w&64u)!=0u)return PSDetailTransferSurface(i);
    if((MeshConfig.w&16u)!=0u)return PSResearchBackwardSurface(i);
    BackwardSurfaceOutput o=(BackwardSurfaceOutput)0;
    o.color=0;o.depth=(MeshConfig.w&4u)!=0 ? 0.f : 1.f;
    const float2 targetUV=CropUv.xy+i.uv*(CropUv.zw-CropUv.xy);
    const float2 coordinate=RightDepthRect.xy+(targetUV+MeshJitter.zw)*RightDepthRect.zw-0.5f;
    const int2 origin=int2(floor(coordinate));
    const float2 fraction=frac(coordinate);
    if(any(origin<ActiveDepthMin(RightDepthRect)) || any(origin+int2(1,1)>ActiveDepthMax(RightDepthRect)))return o;
    // Explicit lanes avoid FXC's dynamically-indexed l-value/unroll limitations.
    const float4 depths=float4(RightSourceDepth.Load(int3(origin,0)),
        RightSourceDepth.Load(int3(origin+int2(1,0),0)),
        RightSourceDepth.Load(int3(origin+int2(0,1),0)),
        RightSourceDepth.Load(int3(origin+int2(1,1),0)));
    const float4 zs=float4(RightEyeForwardZ(depths.x),RightEyeForwardZ(depths.y),
        RightEyeForwardZ(depths.z),RightEyeForwardZ(depths.w));
    const float4 validZ=float4(zs.x>0?zs.x:1.e30f,zs.y>0?zs.y:1.e30f,
        zs.z>0?zs.z:1.e30f,zs.w>0?zs.w:1.e30f);
    const float nearest=min(min(validZ.x,validZ.y),min(validZ.z,validZ.w));
    const float farthest=max(max(zs.x,zs.y),max(zs.z,zs.w));
    // Do NOT prewrite target depth for pixels whose color reconstruction
    // may be rejected. That creates invisible depth occluders and masks
    // the later high-resolution LEFT forward mesh, causing edge jitter.
    // An invalid backward sample preserves the cleared hardware depth.
    
    // Physically correct edge-aware upsampling. Never interpolate depth
    // ACROSS unrelated surfaces, including under reversed-Z.
    if(any(zs<=0))return o;
    const float tolerance=MeshQuality.x+MeshQuality.y*nearest;
    const float4 weights=float4((1-fraction.x)*(1-fraction.y),fraction.x*(1-fraction.y),
                                (1-fraction.x)*fraction.y,fraction.x*fraction.y);
    float4 supported=float4(1,1,1,1);
    if(farthest-nearest>tolerance) {
        if(MeshQuality.w<=1.5f)return o; // legacy A/B baseline
        const float4 nearMembers=float4(abs(zs.x-nearest)<=tolerance,
            abs(zs.y-nearest)<=tolerance,abs(zs.z-nearest)<=tolerance,
            abs(zs.w-nearest)<=tolerance);
        const float4 farMembers=float4(abs(zs.x-farthest)<=tolerance,
            abs(zs.y-farthest)<=tolerance,abs(zs.z-farthest)<=tolerance,
            abs(zs.w-farthest)<=tolerance);
        const float nearCount=dot(nearMembers,float4(1,1,1,1));
        const float farCount=dot(farMembers,float4(1,1,1,1));
        if(nearCount>=3.f && farCount<3.f)supported=nearMembers;
        else if(farCount>=3.f && nearCount<3.f)return o; // nearer foreground vetoes background fill
        else return o; // unresolved silhouette: no fake intermediate depth
    }
    const float4 coeff=weights*supported;
    const float norm=dot(coeff,float4(1,1,1,1));
    if(norm<1.e-5f)return o;
    const float d=dot(coeff,depths)/norm;
    const float nd=(d-DepthViewportRanges.z)/(DepthViewportRanges.w-DepthViewportRanges.z);
    o.depth=nd;
    const float4 h=mul(TargetEyeFromClip,float4(2*targetUV.x-1,1-2*targetUV.y,nd,1));
    if(!all(isfinite(h)) || abs(h.w)<1.e-9f)return o;
    const float3 targetEye=h.xyz/h.w;
    const float4 projected=mul(SourceClipFromTargetEye,float4(targetEye,1));
    if(!all(isfinite(projected)) || projected.w<=1.e-7f || abs(StereoLeftDepthZ.z)<1.e-7f)return o;
    const float2 sourceUV=float2(.5f+.5f*projected.x/projected.w,.5f-.5f*projected.y/projected.w);
    if(any(sourceUV<0)||any(sourceUV>1))return o;
    const float sourceZ=(projected.w-StereoLeftDepthZ.w)/StereoLeftDepthZ.z;
    if(!isfinite(sourceZ)||sourceZ<=0)return o;
    const float2 sourceCoord=LeftDepthRect.xy+(sourceUV+MeshJitter.xy)*LeftDepthRect.zw-0.5f;
    // Conservative nearest-surface validation prevents a foreground color tap
    // from leaking onto the target background at character/weapon silhouettes.
    const float radius=MeshQuality.z;
    const int2 center=int2(floor(sourceCoord));
    const float4 central=float4(DuoLeftVisibilityZ(center),DuoLeftVisibilityZ(center+int2(1,0)),
        DuoLeftVisibilityZ(center+int2(0,1)),DuoLeftVisibilityZ(center+int2(1,1)));
    const float4 expanded=float4(
        DuoLeftVisibilityZ(int2(floor(sourceCoord+float2(-radius,-radius)+.5f))),
        DuoLeftVisibilityZ(int2(floor(sourceCoord+float2(radius,-radius)+.5f))),
        DuoLeftVisibilityZ(int2(floor(sourceCoord+float2(-radius,radius)+.5f))),
        DuoLeftVisibilityZ(int2(floor(sourceCoord+float2(radius,radius)+.5f))));
    if(any(central<=0) || any(expanded<=0))return o;
    const float closest=min(min(min(central.x,central.y),min(central.z,central.w)),
        min(min(expanded.x,expanded.y),min(expanded.z,expanded.w)));
    if(abs(sourceZ-closest)>MeshQuality.x+MeshQuality.y*sourceZ)return o;
    o.color=float4(LeftNative(CropUv.xy+sourceUV*(CropUv.zw-CropUv.xy)).rgb,1);
    return o;
}

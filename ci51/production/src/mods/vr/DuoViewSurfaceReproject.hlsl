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
    const int2 base=ActiveDepthMin(MeshDepthRect())+int2(cell%cellsX,cell/cellsX);
    if(MeshConfig.z!=0 && (MeshConfig.w&2u)!=0) {
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
    const int2 offsets[6]={int2(0,0),int2(1,0),int2(0,1),int2(1,0),int2(1,1),int2(0,1)};
    const uint tri=(corner/3)*3;
    float3 points[3];float2 uvs[3];float ws[3];
    [unroll] for(uint k=0;k<3;++k)
        if(!MeshPoint(base+offsets[tri+k],points[k],uvs[k],ws[k]))return o;
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
    // A plausible target foreground must veto source background even at a
    // mixed footprint. Actual RIGHT shading supplies the uncertain boundary.
    [unroll] for(int y=0;y<2;++y)[unroll] for(int x=0;x<2;++x) {
        const int2 p=first+int2(x,y);
        if(any(p<ActiveDepthMin(rect))||any(p>ActiveDepthMax(rect)))continue;
        const float depth=MeshConfig.z!=0 ? RightSourceDepth.Load(int3(p,0)) : LeftSourceDepth.Load(int3(p,0));
        const float z=EyeForwardZ(depth,projection,range);
        if(z>0 && z+MeshVisibility.x+MeshVisibility.y*z<candidateZ)return true;
    }
    return false;
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
BackwardSurfaceOutput PSBackwardSurface(VertexOut i) {
    BackwardSurfaceOutput o=(BackwardSurfaceOutput)0;
    o.color=0;o.depth=(MeshConfig.w&4u)!=0 ? 0.f : 1.f;
    const float2 targetUV=CropUv.xy+i.uv*(CropUv.zw-CropUv.xy);
    const float2 coordinate=RightDepthRect.xy+(targetUV+MeshJitter.zw)*RightDepthRect.zw-0.5f;
    const int2 origin=int2(floor(coordinate));
    const float2 fraction=frac(coordinate);
    float4 depths=0;float nearest=1.e30f,farthest=0,nearestDepth=o.depth;
    bool allValid=true;
    [unroll] for(uint k=0;k<4;++k) {
        const int2 p=origin+int2(k&1u,k>>1u);
        if(any(p<ActiveDepthMin(RightDepthRect))||any(p>ActiveDepthMax(RightDepthRect))) {
            allValid=false;depths[k]=o.depth;continue;
        }
        depths[k]=RightSourceDepth.Load(int3(p,0));
        const float z=RightEyeForwardZ(depths[k]);
        if(z<=0){allValid=false;continue;}
        if(z<nearest){nearest=z;nearestDepth=depths[k];}
        farthest=max(farthest,z);
    }
    if(farthest>0)o.depth=(nearestDepth-DepthViewportRanges.z)/(DepthViewportRanges.w-DepthViewportRanges.z);
    // Do not create geometry by linearly averaging foreground and background.
    // Fine source foreground can still win the subsequent depth-tested pass.
    if(!allValid || farthest-nearest>MeshQuality.x+MeshQuality.y*nearest)return o;
    const float d=lerp(lerp(depths[0],depths[1],fraction.x),lerp(depths[2],depths[3],fraction.x),fraction.y);
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
    float closest=1.e30f;
    [unroll] for(uint tap=0;tap<8;++tap) {
        // Always validate the real bilinear color footprint before expanding
        // the guard. Expanded corners alone can miss a one-texel foreground.
        int2 p=0;
        if(tap<4)p=int2(floor(sourceCoord))+int2(tap&1u,tap>>1u);
        else {
            const float2 offset=float2((tap&1u)!=0?radius:-radius,(tap&2u)!=0?radius:-radius);
            p=int2(floor(sourceCoord+offset+.5f));
        }
        if(any(p<ActiveDepthMin(LeftDepthRect))||any(p>ActiveDepthMax(LeftDepthRect)))return o;
        const float z=LeftEyeForwardZ(LeftSourceDepth.Load(int3(p,0)));
        if(z<=0)return o;
        closest=min(closest,z);
    }
    if(abs(sourceZ-closest)>MeshQuality.x+MeshQuality.y*sourceZ)return o;
    o.color=float4(LeftNative(CropUv.xy+sourceUV*(CropUv.zw-CropUv.xy)).rgb,1);
    return o;
}

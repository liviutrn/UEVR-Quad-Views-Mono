// Source-depth surface reconstruction. No guessed inverse fixed-point warp.
// Continuous source-depth triangles are projected into the target camera and
// compete in its hardware depth buffer. Source texture coordinates remain
// projective, so low-resolution depth does not downsample source color.
#include "DuoViewStereoCompositeRaster.hlsl"

cbuffer SurfaceConfig : register(b1) {
    row_major float4x4 SourceEyeFromClip;
    row_major float4x4 TargetClipFromSourceEye;
    row_major float4x4 TargetFullClipFromSourceEye;
    uint4 MeshConfig;      // depth sample columns/rows; sourceLeft; target depth present
    float4 MeshEdge;       // abs/relative discontinuity bound; min/max forward Z
    float4 MeshVisibility;// abs/relative occluder bound; target clip-W coefficients C,D
    float4 MeshReserved;
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
    uv=(float2(pixel)+0.5f-rect.xy)/rect.zw;
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
    if(MeshConfig.w==0)return false;
    const float4 rect=MeshConfig.z!=0 ? RightDepthRect : LeftDepthRect;
    const float2 coordinate=rect.xy+targetUV*rect.zw-0.5f;
    const int2 first=int2(floor(coordinate));
    const float2 range=MeshConfig.z!=0 ? DepthViewportRanges.zw : DepthViewportRanges.xy;
    const float4 projection=MeshConfig.z!=0 ? StereoDepthZ : StereoLeftDepthZ;
    // Coarse target depth is an occlusion veto, not the foveal surface model.
    // A foreground/background mixed footprint cannot veto fine source detail.
    [unroll] for(int y=0;y<2;++y)[unroll] for(int x=0;x<2;++x) {
        const int2 p=first+int2(x,y);
        if(any(p<ActiveDepthMin(rect))||any(p>ActiveDepthMax(rect)))return false;
        const float depth=MeshConfig.z!=0 ? RightSourceDepth.Load(int3(p,0)) : LeftSourceDepth.Load(int3(p,0));
        const float z=EyeForwardZ(depth,projection,range);
        if(z<0||z+MeshVisibility.x+MeshVisibility.y*z>=candidateZ)return false;
    }
    return true;
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

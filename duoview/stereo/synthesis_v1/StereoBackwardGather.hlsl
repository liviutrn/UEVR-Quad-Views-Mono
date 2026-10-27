// DuoView split-eye: target-depth-guided inverse warp, prototype V1.
// Original implementation; not connected to the live DuoView/UEVR compositor.
// Supports target RIGHT fovea from LEFT high-res color/depth.
// Inputs MUST be same-frame, exact jittered view-projection matrices, and
// source/target depth from the correct UE scene pass. Fail closed otherwise.
// All world-labelled matrices/vectors operate in ONE COMMON CAMERA-RELATIVE
// coordinate frame (double-precision origin rebased by CPU before float upload).
// All rects are normalized resource (x0,y0,width,height), not crop FOV coordinates.
Texture2D<float4> SourceColor : register(t0);
Texture2D<float>  SourceDepth : register(t1);
Texture2D<float>  TargetDepth : register(t2);
Texture2D<float4> TargetRealColor : register(t3);
SamplerState LinearClamp : register(s0);
RWTexture2D<float4> OutColor : register(u0);
RWTexture2D<float> OutConfidence : register(u1);
RWTexture2D<uint> OutReject : register(u2);

cbuffer BackwardSettings : register(b0)
{
    row_major float4x4 TargetWorldFromClip;
    row_major float4x4 SourceDepthClipFromWorld;
    row_major float4x4 SourceDepthWorldFromClip;
    row_major float4x4 SourceColorClipFromWorld;
    float4 SourceCameraWorld;
    float4 TargetCameraWorld;
    float4 SourceDepthRect;
    float4 TargetDepthRect;
    float4 SourceColorRect;
    float4 TargetRealColorRect;
    float4 DepthParams;        // validMin, validMax, worldAbsolute, worldRelative
    float4 EdgeParams;         // depthEdgeAbs, depthEdgeRel, minSourceTapCoverage, photoLumaMaxDelta
    uint4 OutputRegion;        // x, y, width, height (destination pixels)
    uint4 OutputConfig;        // destWidth, destHeight, flags, reserved
};
// OutputConfig.z: bit0 real target color is valid, bit1 target-depth edge guard.
static const uint HAS_TARGET_COLOR = 1u;
static const uint GUARD_TARGET_EDGE = 2u;
static const uint REJECT_TARGET = 1u;
static const uint REJECT_TARGET_EDGE = 2u;
static const uint REJECT_SOURCE_PROJECTION = 4u;
static const uint REJECT_SOURCE_DEPTH = 8u;
static const uint REJECT_NO_REAL_COLOR = 16u;
static const uint REJECT_PHOTOMETRIC = 32u;
static const uint PHOTO_GUARD = 4u;


bool DeviceDepthValid(float z)
{
    return isfinite(z) && z >= DepthParams.x && z <= DepthParams.y;
}
bool UVInside(float2 uv)
{
    return all(uv >= float2(0.0f,0.0f)) && all(uv < 1.0f.xx);
}
bool Unproject(float2 uv, float z, row_major float4x4 inverseMatrix,
               out float3 world)
{
    float4 p = mul(inverseMatrix, float4(2.0f*uv.x-1.0f,
                                        1.0f-2.0f*uv.y, z, 1.0f));
    world = float3(0.0f,0.0f,0.0f);
    if (abs(p.w) < 1.0e-8f || !all(isfinite(p))) return false;
    world = p.xyz / p.w;
    return all(isfinite(world));
}
bool Project(float3 world, row_major float4x4 vp,
             out float2 uv, out float projectedZ)
{
    float4 p = mul(vp, float4(world, 1.0f));
    uv = float2(0.0f,0.0f); projectedZ = 0.0f;
    if (p.w <= 1.0e-7f || !all(isfinite(p))) return false;
    const float3 ndc = p.xyz / p.w;
    uv = float2(ndc.x*0.5f+0.5f, 0.5f-ndc.y*0.5f);
    projectedZ = ndc.z;
    return all(isfinite(ndc)) && UVInside(uv) && projectedZ >= 0.0f && projectedZ <= 1.0f;
}
float2 MapNativeUV(float2 nativeUV, float4 rect)
{
    return rect.xy + nativeUV * rect.zw;
}
bool InsideRect(float2 physicalUV, float4 rect)
{
    return all(rect.zw > float2(0.0f,0.0f)) &&
           all(physicalUV >= rect.xy) &&
           all(physicalUV < rect.xy+rect.zw);
}
float4 RealTargetFallback(float2 targetUV)
{
    if ((OutputConfig.z & HAS_TARGET_COLOR) == 0) return float4(0,0,0,1);
    uint w,h;
    TargetRealColor.GetDimensions(w,h);
    if (!w || !h) return float4(0,0,0,1);
    float2 uv = MapNativeUV(targetUV, TargetRealColorRect);
    if (!InsideRect(uv,TargetRealColorRect)) return float4(0,0,0,1);
    const float2 halfTexel = 0.5f / float2(w,h);
    const float2 lo = TargetRealColorRect.xy + halfTexel;
    const float2 hi = TargetRealColorRect.xy + TargetRealColorRect.zw - halfTexel;
    if (any(hi < lo)) return float4(0,0,0,1);
    return TargetRealColor.SampleLevel(LinearClamp, clamp(uv,lo,hi),0);
}
void Reject(uint2 dest, float4 fallback, uint mask)
{
    OutColor[dest] = fallback;
    OutConfidence[dest] = 0.0f;
    OutReject[dest] = mask | (((OutputConfig.z & HAS_TARGET_COLOR)==0) ? REJECT_NO_REAL_COLOR : 0u);
}
// Reconstruct a surface at the actual HIGH-RES target ray from low-res depth.
// Inside continuous surfaces D3D device Z is interpolable in screen space
// (perspective rasterization already performs the appropriate interpolation).
// NEVER interpolate depth across a large discontinuity: fall back to real
// target-eye low-res color. Source rects are exact native viewport bounds.
// Edge-guard ON = conservative 2x2 target-depth upsampling; OFF = point-depth
// compatibility mode for A/B debugging only.
bool ReconstructTargetDepth(float2 targetUV, uint2 size,
                            out float targetZ, out float support)
{
    targetZ=0.0f;
    support=0.0f;
    const float2 physicalUV=MapNativeUV(targetUV,TargetDepthRect);
    if(!InsideRect(physicalUV,TargetDepthRect) ||
       any(physicalUV < float2(0,0)) || any(physicalUV >= 1.0f.xx))
        return false;
    const float2 xy=physicalUV*float2(size)-0.5f;
    if((OutputConfig.z & GUARD_TARGET_EDGE)==0) {
        const int2 p=int2(floor(physicalUV*float2(size)));
        if(any(p<0)||p.x>=int(size.x)||p.y>=int(size.y))return false;
        targetZ=TargetDepth.Load(int3(p,0));
        support=1.0f;
        return DeviceDepthValid(targetZ);
    }
    const int2 first=int2(floor(xy));
    float depth[4];
    float weight[4];
    float weightSum=0.0f;
    float referenceDistance=-1.0f;
    const float2 projectedTargetUV=targetUV;
    [unroll] for(uint j=0;j<2;j++){
        [unroll] for(uint i=0;i<2;i++){
            const uint k=j*2+i;
            const int2 p=first+int2(i,j);
            const float2 delta=abs(xy-float2(p));
            weight[k]=max(0.0f,1.0f-delta.x)*max(0.0f,1.0f-delta.y);
            depth[k]=0.0f;
            // Border taps outside physical source viewport are rejected,
            // not clamped to unrelated pixels.
            if(any(p<0)||p.x>=int(size.x)||p.y>=int(size.y))return false;
            const float2 tapUV=(float2(p)+0.5f)/float2(size);
            if(!InsideRect(tapUV,TargetDepthRect))return false;
            const float d=TargetDepth.Load(int3(p,0));
            if(!DeviceDepthValid(d))return false;
            depth[k]=d;
            float3 pointOnTargetRay;
            if(!Unproject(projectedTargetUV,d,TargetWorldFromClip,pointOnTargetRay))
                return false;
            const float distance=length(pointOnTargetRay-TargetCameraWorld.xyz);
            if(!isfinite(distance))return false;
            // All depths are compared at SAME ray to remove angular bias.
            if(referenceDistance<0.0f)referenceDistance=distance;
            else {
                const float allowed=max(1.0e-4f,
                    EdgeParams.x+EdgeParams.y*referenceDistance);
                if(abs(distance-referenceDistance)>allowed)return false;
            }
            weightSum+=weight[k];
        }
    }
    if(weightSum<=1.0e-6f)return false;
    targetZ=(depth[0]*weight[0]+depth[1]*weight[1]
            +depth[2]*weight[2]+depth[3]*weight[3])/weightSum;
    support=1.0f;
    return DeviceDepthValid(targetZ);
}
[numthreads(8,8,1)]
void CSBackwardTargetDepth(uint3 threadId : SV_DispatchThreadID)
{
    if(threadId.x>=OutputRegion.z || threadId.y>=OutputRegion.w)return;
    const uint2 outPx=OutputRegion.xy+threadId.xy;
    const uint2 outSize=OutputConfig.xy;
    if(!outSize.x||!outSize.y||outPx.x>=outSize.x||outPx.y>=outSize.y)return;
    const float2 targetUV=(float2(outPx)+0.5f)/float2(outSize);
    const float4 fallback=RealTargetFallback(targetUV);

    uint depthW,depthH;
    TargetDepth.GetDimensions(depthW,depthH);
    const uint2 tdSize=uint2(depthW,depthH);
    float targetZ,targetSupport;
    if(!depthW||!depthH ||
       !ReconstructTargetDepth(targetUV,tdSize,targetZ,targetSupport)) {
        Reject(outPx,fallback,(OutputConfig.z&GUARD_TARGET_EDGE)!=0u ?
            REJECT_TARGET_EDGE : REJECT_TARGET);return;
    }
    float3 visibleTargetWorld;
    if(!Unproject(targetUV,targetZ,TargetWorldFromClip,visibleTargetWorld)) {
        Reject(outPx,fallback,REJECT_TARGET);return;
    }

    float2 sourceNativeUV;float sourceZ;
    if(!Project(visibleTargetWorld,SourceDepthClipFromWorld,sourceNativeUV,sourceZ)) {
        Reject(outPx,fallback,REJECT_SOURCE_PROJECTION);return;
    }
    uint sdW,sdH,scW,scH;
    SourceDepth.GetDimensions(sdW,sdH);
    SourceColor.GetDimensions(scW,scH);
    if(!sdW||!sdH||!scW||!scH){
        Reject(outPx,fallback,REJECT_SOURCE_DEPTH);return;
    }
    const uint2 sdSize=uint2(sdW,sdH);
    const float2 sourcePhysicalUV=MapNativeUV(sourceNativeUV,SourceDepthRect);
    if(!InsideRect(sourcePhysicalUV,SourceDepthRect) ||
       any(sourcePhysicalUV<float2(0.0f,0.0f))||any(sourcePhysicalUV>=1.0f.xx)){
        Reject(outPx,fallback,REJECT_SOURCE_PROJECTION);return;
    }
    const float2 sourceTexelCoord=sourcePhysicalUV*float2(sdSize)-0.5f;
    const int2 lower=int2(floor(sourceTexelCoord));
    const float candidateDistance=length(visibleTargetWorld-SourceCameraWorld.xyz);
    const float tolerance=max(1.0e-5f,DepthParams.z+DepthParams.w*candidateDistance);
    float4 weightedColor=float4(0.0f,0.0f,0.0f,0.0f);
    float accumulated=0.0f;
    float bestError=1.0e20f;
    float allSpatialWeights=0.0f;
    [unroll] for(int j=0;j<2;j++){
        [unroll] for(int i=0;i<2;i++){
            const int2 dp=lower+int2(i,j);
            const float2 delta=abs(sourceTexelCoord-float2(dp));
            const float weight=max(0.0f,1.0f-delta.x)*max(0.0f,1.0f-delta.y);
            if(weight<=0.0f)continue;
            allSpatialWeights+=weight;
            if(any(dp<0)||dp.x>=int(sdW)||dp.y>=int(sdH))continue;
            const float2 tapPhysicalUV=(float2(dp)+0.5f)/float2(sdSize);
            if(!InsideRect(tapPhysicalUV,SourceDepthRect))continue;
            const float tapZ=SourceDepth.Load(int3(dp,0));
            if(!DeviceDepthValid(tapZ))continue;
            const float2 tapNativeUV=(tapPhysicalUV-SourceDepthRect.xy)/SourceDepthRect.zw;
            // Visibility difference on the SAME source-camera ray: do
            // not compare radial distances from DIFFERENT source texels.
            float3 seenOnProjectedRay;
            if(!Unproject(sourceNativeUV,tapZ,SourceDepthWorldFromClip,
                          seenOnProjectedRay))continue;
            const float err=length(seenOnProjectedRay-visibleTargetWorld);
            if(err>tolerance)continue;
            // Actual tap location still controls WHICH color texel is read.
            float3 sourceVisibleWorld;
            if(!Unproject(tapNativeUV,tapZ,SourceDepthWorldFromClip,
                          sourceVisibleWorld))continue;
            // Color MUST correspond to this depth-validated source texel,
            // never to an independently bilinear-filtered foreground edge.
            float2 sourceColorUV;float sourceColorZ;
            if(!Project(sourceVisibleWorld,SourceColorClipFromWorld,sourceColorUV,sourceColorZ))continue;
            const float2 colorPhysicalUV=MapNativeUV(sourceColorUV,SourceColorRect);
            if(!InsideRect(colorPhysicalUV,SourceColorRect) ||
               any(colorPhysicalUV<float2(0.0f,0.0f))||any(colorPhysicalUV>=1.0f.xx))continue;
            const int2 colorPx=int2(floor(colorPhysicalUV*float2(scW,scH)));
            if(any(colorPx<0)||colorPx.x>=int(scW)||colorPx.y>=int(scH))continue;
            const float4 color=SourceColor.Load(int3(colorPx,0));
            weightedColor+=color*weight;
            accumulated+=weight;
            bestError=min(bestError,err);
        }
    }
    const float coverage=saturate(accumulated/max(allSpatialWeights,1.0e-5f));
    // Isolated valid samples next to a silhouette are NOT sufficient.
    // This guard favors real right-eye color over fragile spatial extrapolation.
    if(accumulated<=1.0e-5f || coverage<max(0.0f,EdgeParams.z)) {
        Reject(outPx,fallback,REJECT_SOURCE_DEPTH);return;
    }
    const float4 color=weightedColor/accumulated;
    if((OutputConfig.z & PHOTO_GUARD)!=0u &&
       (OutputConfig.z & HAS_TARGET_COLOR)!=0u) {
        // Use only when source and fallback color SRVs share linear-light
        // encoding/exposure; disabled by default for Lumen/DLSS uncertainty.
        const float3 luma=float3(0.2126f,0.7152f,0.0722f);
        if(abs(dot(color.rgb,luma)-dot(fallback.rgb,luma))>EdgeParams.w) {
            Reject(outPx,fallback,REJECT_PHOTOMETRIC);return;
        }
    }
    OutColor[outPx]=color;
    const float consistency=saturate(1.0f-bestError/tolerance);
    OutConfidence[outPx]=coverage*consistency*targetSupport;
    OutReject[outPx]=0u;  // native fallback is not an unfilled hole
}

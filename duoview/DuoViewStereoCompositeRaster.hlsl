// DuoView Split-Eye actual stereo XR compositor, experimental.
// Source UE0 = physical LEFT high-res fovea; UE1 = physical RIGHT
// low-res periphery. Produces a DIFFERENT image in each XR half.
// The raw DSVs are already GPU-copied/queue-fenced via R5 before entering.
// We retain left-fovea shading in both foveae; right-periphery shading in
// both peripheries. Target right-eye depth guides foreground/disocclusion.
// Stereo projections use the frozen physical V3 left/right projections,
// with native eye baseline in Unreal world units. No invented pixel shift.
#include "DuoViewNativeCompositeRaster.hlsl"
Texture2D<float> LeftSourceDepth : register(t2);
Texture2D<float> RightSourceDepth : register(t3);

// Extra root constants, appended to DuoViewCompositeConfig:
// StereoDepthZ = (right eye clipZ coefficient A,B,C,D);
// StereoEyeX  = (leftToRightNdcRatio, offset, nativeParallaxNdcTimesZ, valid);
// StereoCheck = (zToleranceAbsolute, zToleranceRelative, peripheryMaxShiftUV, debug).
// right camera z reconstruction: z = (B-d*D)/(d*C-A).
float EyeForwardZ(float deviceZ)
{
    const float denom=deviceZ*StereoDepthZ.z-StereoDepthZ.x;
    if(!isfinite(deviceZ)||deviceZ<=0.000001f||deviceZ>=0.999999f||
       abs(denom)<1.e-9f)return -1.0f;
    const float z=(StereoDepthZ.y-deviceZ*StereoDepthZ.w)/denom;
    return (isfinite(z)&&z>0.01f&&z<1.0e8f)?z:-1.0f;
}
float2 SampleColorRight(float2 uv) {
    return NativeSampleUV(uv,PeripheralRect.zw,NativePeripheryDimensions);
}
float4 RightNative(float2 uv) {
    return PeripheralNativeSource.SampleLevel(LinearClamp,SampleColorRight(uv),0);
}
float4 LeftNative(float2 uv) {
    const float2 local=(uv-CropUv.xy)/(CropUv.zw-CropUv.xy);
    return SourceAtlas.SampleLevel(LinearClamp,
        NativeSampleUV(local,FoveaRect.zw,NativeFoveaDimensions),0);
}
float DeviceLeftDepth(float2 local) {
    uint w,h;LeftSourceDepth.GetDimensions(w,h);
    if(!w||!h)return -1;
    // Candidate manual selection must identify a true cropped-foveal DSV.
    const uint2 p=min(uint2(saturate(local)*float2(w,h)),uint2(w-1,h-1));
    return LeftSourceDepth.Load(int3(p,0));
}
float DeviceRightDepth(float2 uv) {
    uint w,h;RightSourceDepth.GetDimensions(w,h);
    if(!w||!h)return -1;
    const uint2 p=min(uint2(saturate(uv)*float2(w,h)),uint2(w-1,h-1));
    return RightSourceDepth.Load(int3(p,0));
}
bool InCrop(float2 uv) {
    return all(uv>=CropUv.xy) && all(uv<=CropUv.zw);
}
// LEFT full-FOV -> RIGHT full-FOV: invert native projection with right
// source depth. Re-evaluate twice to avoid one-step depth displacement.
// Bounded near-eye disparity prevents catastrophic tearing on bad DSVs.
float2 RightSampleForLeft(float2 leftUV, out bool trustworthy) {
    float2 uv=leftUV; trustworthy=false;
    const float targetNdc=leftUV.x*2.0f-1.0f;
    [unroll] for(uint k=0;k<2;k++) {
        const float z=EyeForwardZ(DeviceRightDepth(uv));
        if(z<0) return leftUV;
        const float x=(targetNdc-StereoEyeX.y-StereoEyeX.z/z)/StereoEyeX.x;
        const float2 next=float2(x*0.5f+0.5f,leftUV.y);
        if(!all(next>=float2(0,0))||!all(next<=float2(1,1))||
           abs(next.x-leftUV.x)>StereoCheck.z)return leftUV;
        uv=next;
    }
    trustworthy=true;
    return uv;
}
float4 RightFovea(float2 rightUV, float4 nativeRight, out float confidence) {
    confidence=0;
    const float z=EyeForwardZ(DeviceRightDepth(rightUV));
    if(z<0) return nativeRight;
    const float ndcR=rightUV.x*2.0f-1.0f;
    const float ndcL=StereoEyeX.x*ndcR+StereoEyeX.y+StereoEyeX.z/z;
    const float2 leftUV=float2(ndcL*0.5f+0.5f,rightUV.y);
    if(!InCrop(leftUV)) return nativeRight;
    const float2 local=(leftUV-CropUv.xy)/(CropUv.zw-CropUv.xy);
    const float sourceZ=EyeForwardZ(DeviceLeftDepth(local));
    const float tolerance=StereoCheck.x+StereoCheck.y*z;
    if(sourceZ<0 || abs(sourceZ-z)>max(0.01f,tolerance))return nativeRight;
    // 4-neighbor depth edge test. NEVER bilinearly paint a foreground
    // silhouette into a disoccluded background. Real RIGHT color repairs.
    uint dw,dh;LeftSourceDepth.GetDimensions(dw,dh);
    if(!dw||!dh) return nativeRight;
    const int2 ip=int2(saturate(local)*float2(dw,dh));
    [unroll] for(int j=0;j<2;j++) {
        [unroll] for(int i=0;i<2;i++) {
            int2 q=clamp(ip+int2(i,j),int2(0,0),int2(dw-1,dh-1));
            const float dz=EyeForwardZ(LeftSourceDepth.Load(int3(q,0)));
            if(dz<0 || abs(dz-z)>2.0f*max(0.01f,tolerance))
                return nativeRight;
        }
    }
    confidence=1;
    return LeftNative(leftUV);
}
float4 PSNativeStereo(VertexOut i):SV_TARGET0 {
    const bool right=i.pos.x>=float(OutputSize.x);
    float2 pixel=i.pos.xy;
    if(right)pixel.x-=float(OutputSize.x);
    const float2 uv=(pixel+float2(.5f,.5f))/float2(OutputSize);
    const float feather=BlendWeight(uv);
    const float4 nativeRight=RightNative(uv);
    float4 periphery=nativeRight;
    if(!right) {
        bool good=false;
        const float2 shifted=RightSampleForLeft(uv,good);
        // This corrects peripheral parallax cheaply using RIGHT scene depth.
        // A small rejected area keeps native RIGHT as the comfort fallback.
        if(good)periphery=RightNative(shifted);
    }
    if(feather<=0.0f) return periphery;
    float confidence=0;
    const float4 fovea=right
        ?RightFovea(uv,nativeRight,confidence)
        :LeftNative(uv);
    // Both eye foveae inherit real LEFT shading whenever visible;
    // RIGHT falls back to actual RIGHT on genuine disocclusions.
    const float4 finalColor=lerp(periphery,fovea,feather);
    if(StereoCheck.w>0.5f) {
        // Eye-output proof: blue tint only in RIGHT half; must not be
        // visible in left XR eye when headset stereo submission is correct.
        if(right)return float4(lerp(finalColor.rgb,float3(.0f,.2f,.9f),.24f),1);
    }
    return finalColor;
}

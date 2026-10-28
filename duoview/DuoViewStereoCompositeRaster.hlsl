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
float EyeForwardZ(float deviceZ,float4 projection,float2 depthRange)
{
    deviceZ=(deviceZ-depthRange.x)/(depthRange.y-depthRange.x);
    const float denom=deviceZ*projection.z-projection.x;
    if(!isfinite(deviceZ)||deviceZ<0.0f||deviceZ>1.0f||
       abs(denom)<1.e-9f)return -1.0f;
    const float z=(projection.y-deviceZ*projection.w)/denom;
    return (isfinite(z)&&z>0.01f&&z<1.0e8f)?z:-1.0f;
}
float RightEyeForwardZ(float d) { return EyeForwardZ(d,StereoDepthZ,DepthViewportRanges.zw); }
float LeftEyeForwardZ(float d) { return EyeForwardZ(d,StereoLeftDepthZ,DepthViewportRanges.xy); }
float2 SampleColorRight(float2 uv) {
    return NativeSampleUV(uv,PeripheralRect.zw,NativePeripheryDimensions);
}
float4 RightNative(float2 uv) {
    return PeripheralNativeSource.SampleLevel(LinearClamp,SampleColorRight(uv),0);
}
float4 LeftNative(float2 uv) {
    const float2 local=(uv-CropUv.xy)/(CropUv.zw-CropUv.xy);
    float4 source=SourceAtlas.SampleLevel(LinearClamp,
        NativeSampleUV(local,FoveaRect.zw,NativeFoveaDimensions),0);
    // Apply the legacy V3 sharpening to physical LEFT shading in BOTH eyes.
    if(SharpenStrength>0.0f && DebugViewMode==0)
        source.rgb=GlamSharpenNativeFovea(uv,source.rgb);
    return source;
}
float DeviceLeftDepth(float2 local) {
    uint w,h;LeftSourceDepth.GetDimensions(w,h);
    if(!w||!h)return -1;
    const int2 p=ActiveDepthTexel(local,LeftDepthRect);
    return LeftSourceDepth.Load(int3(p,0));
}
float DeviceRightDepth(float2 uv) {
    uint w,h;RightSourceDepth.GetDimensions(w,h);
    if(!w||!h)return -1;
    const int2 p=ActiveDepthTexel(uv,RightDepthRect);
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
        const float z=RightEyeForwardZ(DeviceRightDepth(uv));
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
    const float z=RightEyeForwardZ(DeviceRightDepth(rightUV));
    if(z<0) return nativeRight;
    const float ndcR=rightUV.x*2.0f-1.0f;
    const float ndcL=StereoEyeX.x*ndcR+StereoEyeX.y+StereoEyeX.z/z;
    const float2 leftUV=float2(ndcL*0.5f+0.5f,rightUV.y);
    if(!InCrop(leftUV)) return nativeRight;
    const float2 local=(leftUV-CropUv.xy)/(CropUv.zw-CropUv.xy);
    const float sourceZ=LeftEyeForwardZ(DeviceLeftDepth(local));
    const float tolerance=StereoCheck.x+StereoCheck.y*z;
    if(sourceZ<0 || abs(sourceZ-z)>max(0.01f,tolerance))return nativeRight;
    // 4-neighbor depth edge test. NEVER bilinearly paint a foreground
    // silhouette into a disoccluded background. Real RIGHT color repairs.
    uint dw,dh;LeftSourceDepth.GetDimensions(dw,dh);
    if(!dw||!dh) return nativeRight;
    // Source depth tap footprint is centered on texel + 0.5.
    const int2 ip=int2(floor(LeftDepthRect.xy+saturate(local)*LeftDepthRect.zw-0.5f));
    [unroll] for(int j=0;j<2;j++) {
        [unroll] for(int i=0;i<2;i++) {
            int2 q=clamp(ip+int2(i,j),ActiveDepthMin(LeftDepthRect),ActiveDepthMax(LeftDepthRect));
            const float dz=LeftEyeForwardZ(LeftSourceDepth.Load(int3(q,0)));
            if(dz<0 || abs(dz-z)>2.0f*max(0.01f,tolerance))
                return nativeRight;
        }
    }
    confidence=1;
    return LeftNative(leftUV);
}
float4 StereoProofColor(float4 color,bool right) {
    if(abs(StereoCheck.w-1.0f)<0.25f && right)
        return float4(lerp(color.rgb,float3(.0f,.2f,.9f),.24f),1);
    return color;
}
float4 PSNativeStereo(VertexOut i):SV_TARGET0 {
    const bool right=i.pos.x>=float(OutputSize.x);
    float2 pixel=i.pos.xy;
    if(right)pixel.x-=float(OutputSize.x);
    // SV_POSITION is already a pixel center; do not add a second half texel.
    const float2 uv=pixel/float2(OutputSize);
    const float feather=BlendWeight(uv);
    const float4 nativeRight=RightNative(uv);
    float4 periphery=nativeRight;
    // Mode 3 isolates only RIGHT fovea synthesis. BOTH peripheries receive
    // identical real RIGHT periphery, so peripheral warping cannot hide or
    // amplify fovea errors. Diagnostic only: provenance remains unverified.
    if(!right && StereoCheck.w<2.5f) {
        bool good=false;
        const float2 shifted=RightSampleForLeft(uv,good);
        // This corrects peripheral parallax cheaply using RIGHT scene depth.
        // A small rejected area keeps native RIGHT as the comfort fallback.
        if(good)periphery=RightNative(shifted);
    }
    if(feather<=0.0f) return StereoProofColor(
        DebugViewMode==2 ? float4(.04f,.04f,.04f,1) : periphery,right);
    float confidence=0;
    const float4 fovea=right
        ?RightFovea(uv,nativeRight,confidence)
        :LeftNative(uv);
    // Both eye foveae inherit real LEFT shading whenever visible;
    // RIGHT falls back to actual RIGHT on genuine disocclusions.
    float4 finalColor=DebugViewMode==2 ? fovea : lerp(periphery,fovea,feather);
    if(DebugViewMode==1)finalColor=periphery;
    if(DebugBorder && feather>0.01f && feather<0.1f)
        finalColor.rgb=float3(1.0f,.3f,0.0f);
    return StereoProofColor(finalColor,right);
}

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
Texture2D<float4> SyntheticRightFovea : register(t4);
Texture2D<float4> SyntheticLeftPeriphery : register(t5);

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
    const int2 p=ActiveDepthTexel(uv+RightDepthJitterUV,RightDepthRect);
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
// CI73 visual-comfort contract. All measurements use RIGHT full-FOV DLSS
// input depth and the RIGHT projection, never the cropped LEFT FOV to decide
// whether a peripheral pixel is a near-field viewmodel. An explicit 3x3 guard
// protects an entire silhouette from partial "original + shifted" coverage.
// This is a spatial policy, not unverified temporal history.
bool CI73ProtectedNear(float2 uv) {
    const int2 center=ActiveDepthTexel(uv+RightDepthJitterUV,RightDepthRect);
    const int2 lo=ActiveDepthMin(RightDepthRect);
    const int2 hi=ActiveDepthMax(RightDepthRect);
    [unroll] for(int y=-1;y<=1;++y) {
        [unroll] for(int x=-1;x<=1;++x) {
            const float z=RightEyeForwardZ(RightSourceDepth.Load(
                int3(clamp(center+int2(x,y),lo,hi),0)));
            if(z>0.f && z<80.f)return true;
        }
    }
    return false;
}
bool CI73RightDepthEdge(float2 uv) {
    const int2 lo=ActiveDepthMin(RightDepthRect);
    const int2 hi=ActiveDepthMax(RightDepthRect);
    // Same pixel-center 2x2 footprint as target inverse gather, not
    // the nearest sample followed by an asymmetric +X/+Y neighborhood.
    const int2 p=int2(floor(RightDepthRect.xy+
        (uv+RightDepthJitterUV)*RightDepthRect.zw-0.5f));
    const float z0=RightEyeForwardZ(RightSourceDepth.Load(int3(clamp(p,lo,hi),0)));
    const float z1=RightEyeForwardZ(RightSourceDepth.Load(int3(clamp(p+int2(1,0),lo,hi),0)));
    const float z2=RightEyeForwardZ(RightSourceDepth.Load(int3(clamp(p+int2(0,1),lo,hi),0)));
    const float z3=RightEyeForwardZ(RightSourceDepth.Load(int3(clamp(p+int2(1,1),lo,hi),0)));
    if(min(min(z0,z1),min(z2,z3))<=0.f)return true;
    const float nearest=min(min(z0,z1),min(z2,z3));
    const float farthest=max(max(z0,z1),max(z2,z3));
    return farthest-nearest > 2.f*(StereoCheck.x+StereoCheck.y*nearest);
}
float4 CI73StableComposite(float2 uv,bool right) {
    const float4 realRight=RightNative(uv);
    const bool protectedNear=CI73ProtectedNear(uv);
    const float feather=BlendWeight(uv);
    const float2 local=(uv-CropUv.xy)/(CropUv.zw-CropUv.xy);
    // Use a deterministic, narrow crop seam instead of cross-fading physical
    // LEFT and RIGHT silhouettes. Shared feather coordinate changes with gaze
    // but cannot produce two simultaneous edges at the same pixel.
    const bool chooseFovea=feather>=0.25f;
    const float4 leftFovea=chooseFovea?LeftNative(uv):realRight;
    if(protectedNear) {
        // The source was not modelled with a separate viewmodel depth camera.
        // Force SAME native RIGHT near geometry in both peripheries to avoid
        // duplicated hands and wrong full-FOV→crop reprojection. Inside crop,
        // LEFT fovea remains real; the RIGHT eye shares it for visual comfort.
        if(chooseFovea)return right?float4(realRight.rgb,1.f):float4(leftFovea.rgb,1.f);
        return float4(realRight.rgb,1.f);
    }
    if(chooseFovea) {
        if(!right)return float4(leftFovea.rgb,1.f);
        // Alpha selects ONE owner; no partial blend of displaced silhouettes.
        const float4 projected=SyntheticRightFovea.SampleLevel(
            LinearClamp,saturate(local),0);
        // Do not reject a smooth surface just because the synthetic-alpha
        // footprint lies near the cropped ROI edge. A true RIGHT-depth edge
        // is the relevant criterion for fail-closed native-eye fallback.
        return projected.a>=.995f && !CI73RightDepthEdge(uv)
             ? float4(projected.rgb/max(projected.a,1.e-5f),1.f)
             : float4(realRight.rgb,1.f);
    }
    if(right)return float4(realRight.rgb,1.f);
    // LEFT periphery is deliberately mono unless its entire small neighborhood
    // has reliable synthetic coverage. This removes the native RIGHT underlay
    // + shifted LEFT duplicate in uncertain/out-of-bounds regions.
    const float2 pix=1.f/float2(OutputSize);
    const float4 samples=float4(
        SyntheticLeftPeriphery.SampleLevel(LinearClamp,saturate(uv),0).a,
        SyntheticLeftPeriphery.SampleLevel(LinearClamp,saturate(uv+float2(pix.x,0)),0).a,
        SyntheticLeftPeriphery.SampleLevel(LinearClamp,saturate(uv-float2(pix.x,0)),0).a,
        SyntheticLeftPeriphery.SampleLevel(LinearClamp,saturate(uv+float2(0,pix.y)),0).a);
    const float below=SyntheticLeftPeriphery.SampleLevel(LinearClamp,
        saturate(uv-float2(0,pix.y)),0).a;
    // A 5-tap stable owner guard refuses partial/antialiased coverage.
    if(min(min(samples.x,samples.y),min(samples.z,min(samples.w,below)))<.995f)
        return float4(realRight.rgb,1.f);
    const float4 project=SyntheticLeftPeriphery.SampleLevel(
        LinearClamp,saturate(uv),0);
    return float4(project.rgb/max(project.a,1.e-5f),1.f);
}
float4 SurfaceComposite(float2 uv,bool right) {
    const float feather=BlendWeight(uv);
    const float4 realRight=RightNative(uv);
    const bool reconstructPeriphery=StereoCheck.w>=4.5f;
    float4 periphery=realRight;
    float peripheralCoverage=0;
    if(!right && reconstructPeriphery) {
        const float4 projected=SyntheticLeftPeriphery.SampleLevel(LinearClamp,saturate(uv),0);
        peripheralCoverage=projected.a;
        if(projected.a>=.995f)periphery=float4(projected.rgb/projected.a,1);
    }
    float4 fovea=periphery;float fovealCoverage=0;
    if(feather>0) {
        if(!right) {fovea=LeftNative(uv);fovealCoverage=1;}
        else {
            const float2 local=(uv-CropUv.xy)/(CropUv.zw-CropUv.xy);
            const float4 projected=SyntheticRightFovea.SampleLevel(LinearClamp,saturate(local),0);
            fovealCoverage=projected.a;
            fovea=realRight;
            if(projected.a>=.995f)fovea=float4(projected.rgb/projected.a,1);
        }
    }
    if(StereoCheck.w>5.5f) {
        // This is GEOMETRY COVERAGE, not a claim of authenticated game depth.
        const float3 outer=right?float3(.1f,.2f,.8f):lerp(float3(.8f,0,.6f),float3(0,.6f,.8f),peripheralCoverage);
        const float3 inner=lerp(float3(.9f,.05f,0),float3(.05f,.9f,.1f),fovealCoverage);
        return float4(lerp(outer,inner,feather),1);
    }
    if(DebugViewMode==1)return periphery;
    if(DebugViewMode==2)return feather>0?fovea:float4(.04f,.04f,.04f,1);
    // CI76: current-frame exclusive image ownership for ALL surface strategies.
    // Coverage is support, never opacity for two displaced silhouettes.
    // The high-res surface pass already tests target visibility; do not turn
    // a coarse RIGHT-depth edge flag into another hard sharpness switch.
    const bool chooseFovea=feather>=.25f;
    if(((!right && !chooseFovea) || (right && chooseFovea)) && CI73ProtectedNear(uv)) {
        periphery=realRight;
        if(right)fovea=realRight;
    }
    float4 color=chooseFovea?fovea:periphery;
    if(DebugBorder && feather>.01f && feather<.1f)color.rgb=float3(1,.3f,0);
    return color;
}
float4 PSNativeStereo(VertexOut i):SV_TARGET0 {
    const bool right=i.pos.x>=float(OutputSize.x);
    float2 pixel=i.pos.xy;
    if(right)pixel.x-=float(OutputSize.x);
    // SV_POSITION is already a pixel center; do not add a second half texel.
    const float2 uv=pixel/float2(OutputSize);
    // Algorithm selection stays in the surface pass. Every strategy uses the
    // same CI76 composition policy; mode 6 remains a coverage visualization.
    if(StereoCheck.w>=3.5f)return SurfaceComposite(uv,right);
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

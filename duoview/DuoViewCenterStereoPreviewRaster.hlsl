// Experimental center-origin stereo preview: one-pass left/right XR raster.
// This is a diagnostic shader, NOT geometry-calibrated A+. It uses P1's frozen
// candidate-Z maps, which are NOT necessarily correctly paired to color.
// NEVER turn on automatically: no stereoscopic readiness claim is implied.
#include "DuoViewNativeCompositeRaster.hlsl"
Texture2D<float> StereoCandidateZ0 : register(t2);
Texture2D<float> StereoCandidateZ1 : register(t3);

// The two candidates may represent unrelated frames. All interpretations
// must remain explicit opt-in until producer lineage is proven.
float candidate0(float2 normalized, float2 active) {
    uint w,h; StereoCandidateZ0.GetDimensions(w,h);
    if (!w||!h || active.x<1 || active.y<1) return 0.0;
    float2 cap=min(float2(w,h),active);
    float2 pixel=clamp(saturate(normalized)*active,float2(.5,.5),cap-float2(.5,.5));
    return StereoCandidateZ0.SampleLevel(LinearClamp,pixel/float2(w,h),0);
}
float candidate1(float2 normalized, float2 active) {
    uint w,h; StereoCandidateZ1.GetDimensions(w,h);
    if (!w||!h || active.x<1 || active.y<1) return 0.0;
    float2 cap=min(float2(w,h),active);
    float2 pixel=clamp(saturate(normalized)*active,float2(.5,.5),cap-float2(.5,.5));
    return StereoCandidateZ1.SampleLevel(LinearClamp,pixel/float2(w,h),0);
}
float peripheralRawZ(float2 uv) {
    return _reserved<.5 ? candidate1(uv,PeripheralRect.zw) :
                          candidate0(uv,PeripheralRect.zw);
}
float fovealRawZ(float2 uv) {
    return _reserved<.5 ? candidate0(uv,FoveaRect.zw) :
                          candidate1(uv,FoveaRect.zw);
}

float4 PSNativeStereoPreview(VertexOut i):SV_TARGET0 {
    float2 pixel=i.pos.xy;
    const bool rightEye = pixel.x>=OutputSize.x;
    if (rightEye) pixel.x-=OutputSize.x;
    const float2 targetUv=(pixel+.5)/float2(OutputSize);

    // Diagnostic only: assume infinite-far reversed Z, zero jitter and central
    // source projection. The exact UE/XR matrices must replace this estimate.
    // Strength is [0..40]% and displacement clamped below 1.2% eye width.
    const float strength=min(40.0,float(OutputOffset.x))/100.0;
    const float raw0=saturate(peripheralRawZ(targetUv));
    const float2 cropSpan=CropUv.zw-CropUv.xy;
    const bool inFovea=all(targetUv>=CropUv.xy)&&all(targetUv<=CropUv.zw) &&
        all(cropSpan>float2(.00001,.00001));
    const float raw1=inFovea ? saturate(
        fovealRawZ((targetUv-CropUv.xy)/max(cropSpan,float2(.00001,.00001)))) : raw0;
    // At silhouette boundaries use peripheral candidate to avoid a high-contrast
    // discontinuity. Candidate Z is still UNVERIFIED, so not interpreted as meters.
    const float raw= (inFovea && abs(raw0-raw1)<.07) ? raw1 : raw0;
    const float shiftNorm=min(.012,raw*.045)*strength;
    const float signEye=rightEye ? 1.0 : -1.0;
    // Left source target samples to the LEFT of the desired left-eye pixel.
    const float2 srcUv=saturate(targetUv+float2(signEye*shiftNorm,0.0));

    // A second conservative gather iteration reduces halo/error in smoothly
    // varying depth regions; reject if depth jumps across an object boundary.
    const float rawNext=saturate(peripheralRawZ(srcUv));
    const float confidence=abs(rawNext-raw0)<.12 ? 1.0 : 0.0;
    const float2 sampleUv=lerp(targetUv,srcUv,confidence);
    const float2 peripheryUv=NativeSampleUV(sampleUv,PeripheralRect.zw,NativePeripheryDimensions);
    const float4 peripheryColor=PeripheralNativeSource.SampleLevel(LinearClamp,peripheryUv,0);
    const float weight=BlendWeight(sampleUv);
    float4 result=peripheryColor;
    if(weight>0.0 && all(CropUv.zw>CropUv.xy)) {
        const float2 local=(sampleUv-CropUv.xy)/(CropUv.zw-CropUv.xy);
        const float2 foveaUv=NativeSampleUV(local,FoveaRect.zw,NativeFoveaDimensions);
        float4 color=SourceAtlas.SampleLevel(LinearClamp,foveaUv,0);
        if(SharpenStrength>0.0) color.rgb=GlamSharpenNativeFovea(sampleUv,color.rgb);
        result=lerp(peripheryColor,color,weight);
    }
    // In case of disocclusion doubt, use conservative center-origin color
    // for both eyes rather than extrapolating an exposed background.
    // Pink tint only when DebugBorder enabled helps confirm the shader is active.
    if(DebugBorder && abs(shiftNorm)>.0001) result.rgb=lerp(result.rgb,float3(1.0,0.0,.6),.06);
    return result;
}

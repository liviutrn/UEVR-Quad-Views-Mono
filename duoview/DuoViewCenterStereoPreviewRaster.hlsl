// Opt-in LIVE center-origin DIBR for DuoView ID6, two independent depth SRVs.
// Uses the Build118 proven R32 candidate extents via LiveDIBRDepthPair.hpp.
// Experimental: projection matrices, RGB-D same-frame validation and disoccluded
// scene completion are NOT yet established. Legacy Mono stays the default.
#include "DuoViewNativeCompositeRaster.hlsl"
Texture2D<float> StereoCandidateZ0 : register(t2); // 860x684: fovea candidate
Texture2D<float> StereoCandidateZ1 : register(t3); // 344x276: periphery candidate

float ReadZ(Texture2D<float> zTex,float2 uv,float2 active) {
    uint w,h;zTex.GetDimensions(w,h);
    if(w<2||h<2||active.x<2||active.y<2)return 0.0;
    float2 limit=max(float2(1,1),min(float2(w,h),active)-1.0);
    float2 pixel=clamp(saturate(uv)*active,float2(0.5,0.5),limit);
    float z=zTex.SampleLevel(LinearClamp,pixel/float2(w,h),0);
    return (z>=0.0 && z<1.0)?z:0.0;
}
float PeripheralZ(float2 uv) {
    return ReadZ(StereoCandidateZ1,uv,PeripheralRect.zw);
}
float FovealZ(float2 uv) {
    return ReadZ(StereoCandidateZ0,uv,FoveaRect.zw);
}
float BlendedDepth(float2 uv) {
    float z=PeripheralZ(uv);
    float2 span=CropUv.zw-CropUv.xy;
    if(all(span>float2(.00001,.00001))) {
        float2 local=(uv-CropUv.xy)/span;
        if(all(local>=0.0)&&all(local<=1.0)) {
            float f=FovealZ(local);
            float weight=BlendWeight(uv);
            // Invalid/sky candidate must not generate a fake occlusion edge.
            if(f>0.00000001)z=lerp(z,f,weight);
        }
    }
    return z;
}
float4 GatherDuoColor(float2 uv) {
    float2 perUv=NativeSampleUV(uv,PeripheralRect.zw,NativePeripheryDimensions);
    float4 p=PeripheralNativeSource.SampleLevel(LinearClamp,perUv,0);
    float blend=BlendWeight(uv);
    float2 span=CropUv.zw-CropUv.xy;
    if(blend<=0.0 || any(span<=float2(0.00001,0.00001)))return p;
    float2 local=(uv-CropUv.xy)/span;
    float2 fuv=NativeSampleUV(local,FoveaRect.zw,NativeFoveaDimensions);
    float4 f=SourceAtlas.SampleLevel(LinearClamp,fuv,0);
    if(SharpenStrength>0.0)f.rgb=GlamSharpenNativeFovea(uv,f.rgb);
    return lerp(p,f,blend);
}
float4 PSNativeStereoPreview(VertexOut i):SV_TARGET0 {
    float2 pixel=i.pos.xy;
    const bool rightEye=pixel.x>=OutputSize.x;
    if(rightEye)pixel.x-=OutputSize.x;
    const float2 uv=saturate((pixel+0.5)/float2(OutputSize));

    // Reversed-Z proof images range ~0..0.012; linear relative inverse-depth
    // is a test approximation. Strength 8 initially yields a few pixels of
    // maximum binocular disparity, with sky nearly unchanged.
    const float strength=min(40.0,float(OutputOffset.x))*0.01;
    const float raw0=BlendedDepth(uv);
    const float near0=saturate(max(0.0,raw0-0.00001)/0.012);
    const float sgn=rightEye?1.0:-1.0;
    // Backward project from each eye toward the center-camera source.
    float2 sampleUv=saturate(uv+float2(sgn*near0*0.017*strength,0));
    float raw1=BlendedDepth(sampleUv);
    float near1=saturate(max(0.0,raw1-0.00001)/0.012);
    // Correct inverse warp once; reject discontinuous/invalid source depth.
    float2 correctedUv=saturate(uv+float2(sgn*near1*0.017*strength,0));
    float2 chosenUv=(abs(near1-near0)<0.32 &&
                      !(raw0>0.00001 && raw1<=0.00001)) ? correctedUv : uv;
    // No fill extrapolation at occlusions: fall back to center-view pixels.
    float4 result=GatherDuoColor(chosenUv);
    if(DebugBorder && abs(chosenUv.x-uv.x)>0.00004)
        result.rgb=lerp(result.rgb,float3(0.14,0.68,0.88),0.06);
    return result;
}

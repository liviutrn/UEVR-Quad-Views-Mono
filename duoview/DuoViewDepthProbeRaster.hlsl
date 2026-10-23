// P1 single-pass depth visualization of TWO owned SceneDepthZ candidate copies.
// Raw hardware Z ONLY: never label as meters or verified fovea/periphery.
// t2/t3 hold frozen, separately owned depth snapshots from RHI barrier events.
#include "DuoViewNativeCompositeRaster.hlsl"
Texture2D<float> DuoDepthCandidate0 : register(t2);
Texture2D<float> DuoDepthCandidate1 : register(t3);

float RawDepthAt0(float2 local,float2 active) {
    uint w,h; DuoDepthCandidate0.GetDimensions(w,h);
    if (!w || !h || active.x<1 || active.y<1) return 0;
    const float2 limits=max(min(active,float2(w,h)),float2(1,1));
    const float2 pixel=clamp(saturate(local)*active,float2(.5,.5),limits-float2(.5,.5));
    return DuoDepthCandidate0.SampleLevel(LinearClamp,pixel/float2(w,h),0);
}
float RawDepthAt1(float2 local,float2 active) {
    uint w,h; DuoDepthCandidate1.GetDimensions(w,h);
    if (!w || !h || active.x<1 || active.y<1) return 0;
    const float2 limits=max(min(active,float2(w,h)),float2(1,1));
    const float2 pixel=clamp(saturate(local)*active,float2(.5,.5),limits-float2(.5,.5));
    return DuoDepthCandidate1.SampleLevel(LinearClamp,pixel/float2(w,h),0);
}
float RawFoveaDepth(float2 local) {
    return _reserved<.5
        ? RawDepthAt0(local,FoveaRect.zw)
        : RawDepthAt1(local,FoveaRect.zw);
}
float RawPeripheryDepth(float2 uv) {
    return _reserved<.5
        ? RawDepthAt1(uv,PeripheralRect.zw)
        : RawDepthAt0(uv,PeripheralRect.zw);
}
float4 PSNativeDepthProbe(VertexOut i) : SV_TARGET0 {
    float2 p=i.pos.xy;
    if (p.x>=OutputSize.x) p.x-=OutputSize.x;
    const float2 fullUv=p/float2(OutputSize);
    const float weight=BlendWeight(fullUv);
    const float rawPeripheral=saturate(RawPeripheryDepth(fullUv));
    float raw=rawPeripheral;
    bool valid=true;
    if (DebugViewMode==12) { raw=0; valid=false; }
    if (DebugViewMode==13 || DebugViewMode==12) {
        if (weight>0) {
            const float2 local=(fullUv-CropUv.xy)/(CropUv.zw-CropUv.xy);
            const float depth=saturate(RawFoveaDepth(local));
            raw=(DebugViewMode==12) ? depth : lerp(rawPeripheral,depth,weight);
            valid=true;
        }
    }
    // Per-eye P1 candidate inspection. These modes do not claim that
    // either snapshot is scene depth or belongs to a particular UE view.
    // Unlike the original P1 cropped modes, map the *entire* depth
    // candidate into the eye's full UV, independent of DLSS output size.
    // DebugViewMode 17 = candidate 0 in both eyes
    // DebugViewMode 18 = candidate 1 in both eyes
    // DebugViewMode 19 = left 0 / right 1
    // DebugViewMode 20 = left 1 / right 0
    if (DebugViewMode>=17 && DebugViewMode<=20) {
        uint d0w,d0h,d1w,d1h;
        DuoDepthCandidate0.GetDimensions(d0w,d0h);
        DuoDepthCandidate1.GetDimensions(d1w,d1h);
        const bool right_eye=i.pos.x>=OutputSize.x;
        const bool use_second=(DebugViewMode==18) ||
            (DebugViewMode==19 && right_eye) ||
            (DebugViewMode==20 && !right_eye);
        const float2 uv=saturate(fullUv);
        const float z=use_second
            ? DuoDepthCandidate1.SampleLevel(LinearClamp,uv,0)
            : DuoDepthCandidate0.SampleLevel(LinearClamp,uv,0);
        // Uncalibrated reversed-Z display; help reveal terrain silhouettes.
        const float3 shade=pow(saturate(z).xxx, float3(.22,.22,.22));
        // Tiny identity stripe: cyan means candidate0; magenta candidate1.
        const float3 id=use_second ? float3(1.0,.05,.66) : float3(0.0,.88,1.0);
        const float side_x=right_eye ? i.pos.x-OutputSize.x : i.pos.x;
        return float4(side_x<12.0 ? id : shade,1.0);
    }
    if (DebugViewMode==14) {
        // Explicit red means candidate order has NOT been proven to match UE views.
        return float4(1,.08,.08,1);
    }
    // Reversed-Z diagnostics: nonlinear display boosts far-field tiny raw-Z.
    // It is NOT a linear-metre depth map (near/far are still unknown).
    const float shade=pow(raw,.22);
    float3 rgb=valid?float3(shade,shade,shade):float3(.02,.02,.02);
    if (weight>.005 && weight<.08) rgb=float3(.95,.28,0);
    return float4(rgb,1);
}

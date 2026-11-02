// DuoView Native Stereo Fix compositor: sample both validated UE source
// textures in place, rather than gathering two rectangles into a doublewide
// intermediate atlas. Matches the legacy blend and half-texel bounds exactly.
// SourceAtlas (t0) is repurposed for the fovea, t1 for the periphery.
// Original Native Fix render targets, scene histories and shading are untouched.
#include "DuoViewCompositeRaster.hlsl"
Texture2D<float4> PeripheralNativeSource : register(t1);
Texture2D<float> NativeFoveaNGXDepth : register(t2);

float2 NativeSampleUV(float2 local, uint2 active, uint2 resourceSize) {
    const float2 texels = clamp(saturate(local) * float2(active),
                                float2(.5,.5), float2(active)-.5);
    return texels / float2(resourceSize);
}

#include "DuoViewGlamaryeFovea.hlsl"

// v207 (SharpenFlags bit 8): Catmull-Rom periphery upscaling with 9 bilinear
// taps. Same texel convention as NativeSampleUV; every tap is clamped to the
// ACTIVE source rect, so padding beyond the engine viewport never bleeds in.
float4 SamplePeripheryCatmullRom(float2 local, uint2 active, uint2 resourceSize) {
    const float2 size = float2(resourceSize);
    const float2 lo = float2(.5, .5);
    const float2 hi = float2(active) - .5;
    const float2 samplePos = clamp(saturate(local) * float2(active), lo, hi);
    const float2 texPos1 = floor(samplePos - .5) + .5;
    const float2 f = samplePos - texPos1;
    const float2 w0 = f * (-.5 + f * (1. - .5 * f));
    const float2 w1 = 1. + f * f * (-2.5 + 1.5 * f);
    const float2 w2 = f * (.5 + f * (2. - 1.5 * f));
    const float2 w3 = f * f * (-.5 + .5 * f);
    const float2 w12 = w1 + w2;
    const float2 t0 = clamp(texPos1 - 1., lo, hi) / size;
    const float2 t3 = clamp(texPos1 + 2., lo, hi) / size;
    const float2 t12 = clamp(texPos1 + w2 / w12, lo, hi) / size;
    float4 r = PeripheralNativeSource.SampleLevel(LinearClamp, float2(t0.x, t0.y), 0.0) * (w0.x * w0.y);
    r += PeripheralNativeSource.SampleLevel(LinearClamp, float2(t12.x, t0.y), 0.0) * (w12.x * w0.y);
    r += PeripheralNativeSource.SampleLevel(LinearClamp, float2(t3.x, t0.y), 0.0) * (w3.x * w0.y);
    r += PeripheralNativeSource.SampleLevel(LinearClamp, float2(t0.x, t12.y), 0.0) * (w0.x * w12.y);
    r += PeripheralNativeSource.SampleLevel(LinearClamp, float2(t12.x, t12.y), 0.0) * (w12.x * w12.y);
    r += PeripheralNativeSource.SampleLevel(LinearClamp, float2(t3.x, t12.y), 0.0) * (w3.x * w12.y);
    r += PeripheralNativeSource.SampleLevel(LinearClamp, float2(t0.x, t3.y), 0.0) * (w0.x * w3.y);
    r += PeripheralNativeSource.SampleLevel(LinearClamp, float2(t12.x, t3.y), 0.0) * (w12.x * w3.y);
    r += PeripheralNativeSource.SampleLevel(LinearClamp, float2(t3.x, t3.y), 0.0) * (w3.x * w3.y);
    return saturate(r); // Catmull-Rom can overshoot slightly at hard edges
}

float4 PSNativeMain(VertexOut i) : SV_TARGET0 {
    // A compatible double-wide XR target can be filled in one raster draw.
    // Reuse the same Mono image coordinates in each half without changing
    // either source rectangle or the eye-local blend math.
    float2 outputPixel = i.pos.xy;
    if (outputPixel.x >= OutputSize.x) outputPixel.x -= OutputSize.x;
    const float2 fullUv = outputPixel / float2(OutputSize);
    const float2 peripherySample = NativeSampleUV(
        fullUv, PeripheralRect.zw, NativePeripheryDimensions);
    const float weight = BlendWeight(fullUv);
    // Catmull-Rom only where the periphery is visible (weight < 1); fully
    // foveal pixels keep the single bilinear tap, whose result lerp discards.
    const float4 periphery = (SharpenFlags & 8u) != 0u && weight < 1.0
        ? SamplePeripheryCatmullRom(fullUv, PeripheralRect.zw, NativePeripheryDimensions)
        : PeripheralNativeSource.SampleLevel(LinearClamp, peripherySample, 0.0);
    float4 result = DebugViewMode == 2 ? float4(.04,.04,.04,1) : periphery;
    if (weight > 0.0 && DebugViewMode != 1) {
        const float2 localFovea = (fullUv - CropUv.xy) / (CropUv.zw - CropUv.xy);
        const float2 foveaSample = NativeSampleUV(
            localFovea, FoveaRect.zw, NativeFoveaDimensions);
        float4 fovea = SourceAtlas.SampleLevel(LinearClamp, foveaSample, 0.0);
        // One point-load of NGX input depth within the cropped fovea only.
        // Unreal (UE5.5) uses reversed-Z by default; allow normal-Z override.
        // The near-plane scalar comes from the frozen UE projection, converted
        // from game centimeters into meters. No temporal / cross-frame reuse.
        float pixelStrength=SharpenStrength;
        float depthRaw=0.0;
        float depthMeters=0.0;
        float depthBlend=0.0;
        bool validDepth=false;
        bool validMetricDepth=false;
        if ((DepthFlags & 1u)!=0u && all(DepthActiveSize>0u) &&
            all(DepthTexSize>0u)) {
            uint2 p=uint2(saturate(localFovea)*float2(DepthActiveSize));
            p=min(p,DepthActiveSize-1u)+DepthBase;
            p=min(p,DepthTexSize-1u);
            depthRaw=NativeFoveaNGXDepth.Load(int3(p,0));
            // Both endpoints are VALID normalized hardware depth:
            // reversed-Z sky may be precisely 0, near-plane geometry 1.
            // Reject NaN/out-of-range; never paint valid sky magenta.
            validDepth=isfinite(depthRaw) && depthRaw>=0.0 &&
                       depthRaw<=1.0;
            if(validDepth && DepthFarMeters>DepthNearMeters &&
               DepthNearClipMeters>0.0 && isfinite(DepthNearClipMeters)) {
                validMetricDepth=true;
                const float div=(DepthFlags&8u)!=0u ? depthRaw : (1.0-depthRaw);
                depthMeters=DepthNearClipMeters/max(div,0.000001);
                depthBlend=saturate((depthMeters-DepthNearMeters)/
                                   max(DepthFarMeters-DepthNearMeters,0.00001));
                if((DepthFlags&4u)!=0u)
                    depthBlend=depthBlend*depthBlend*(3.0-2.0*depthBlend);
                if((DepthFlags&2u)!=0u)
                    pixelStrength=lerp(DepthNearStrength,DepthFarStrength,depthBlend);
            }
        }
        const uint preview=(DepthFlags>>4u)&3u;
        if (preview!=0u) {
            // Magenta means NO valid live depth for this pixel, not a
            // grayscale scene. Never silently display normal sharpness
            // when the user explicitly requests a depth preview.
            if(validDepth && (preview==1u || validMetricDepth)) {
                const float intensity=preview==1u?depthRaw:depthBlend;
                fovea.rgb=float3(intensity,intensity,intensity);
            } else {
                fovea.rgb=float3(1.0,0.0,1.0);
            }
        } else if (pixelStrength>0.0 && DebugViewMode==0) {
            fovea.rgb=GlamSharpenNativeFovea(fullUv,fovea.rgb,pixelStrength);
        }
        result = DebugViewMode == 2 ? fovea : lerp(periphery,fovea,weight);
    }
    if (DebugBorder && weight > 0.01 && weight < 0.1)
        result.rgb = float3(1.0,0.3,0.0);
    return result;
}

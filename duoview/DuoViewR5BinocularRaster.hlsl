// Binocular DuoView: both DIBR outputs are packed left | right RGBA images.
// The foveal pair was reconstructed L->R, peripheral pair R->L.
// SourceAtlas=t0 packed fovea; PeripheralNativeSource=t1 packed periphery.
#include "DuoViewCompositeRaster.hlsl"
Texture2D<float4> PeripheralNativeSource : register(t1);
float2 NativeStereoSampleUV(float2 local, uint2 active, uint2 resourceSize, uint eye) {
    float2 localTexel = clamp(saturate(local)*float2(active),float2(.5,.5),float2(active)-.5);
    localTexel.x += eye*active.x;
    return localTexel / float2(resourceSize);
}
#include "DuoViewGlamaryeStereo.hlsl"
float4 PSR5StereoMain(VertexOut i):SV_TARGET0 {
    const uint eye = i.pos.x >= OutputSize.x ? 1u : 0u;
    const float2 eyePixel=float2(i.pos.x - eye*OutputSize.x,i.pos.y);
    const float2 fullUv=eyePixel / float2(OutputSize);
    const float2 pUV=NativeStereoSampleUV(fullUv,PeripheralRect.zw,NativePeripheryDimensions,eye);
    float4 periphery=PeripheralNativeSource.SampleLevel(LinearClamp,pUV,0);
    const float weight=BlendWeight(fullUv);
    float4 result=DebugViewMode==2 ? float4(.04,.04,.04,1) : periphery;
    if (weight>0.0 && DebugViewMode!=1) {
        const float2 local=(fullUv-CropUv.xy)/(CropUv.zw-CropUv.xy);
        const float2 fUV=NativeStereoSampleUV(local,FoveaRect.zw,NativeFoveaDimensions,eye);
        float4 fovea=SourceAtlas.SampleLevel(LinearClamp,fUV,0);
        if(SharpenStrength>0.0 && DebugViewMode==0)
            fovea.rgb=GlamSharpenNativeFoveaStereo(fullUv,fovea.rgb,eye);
        result=DebugViewMode==2 ? fovea : lerp(periphery,fovea,weight);
    }
    if(DebugBorder && weight>0.01 && weight<0.10) result.rgb=float3(1,.3,0);
    result.a=1.0;
    return result;
}

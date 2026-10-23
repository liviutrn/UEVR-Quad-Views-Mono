// S0 independent left/right-output probe; NO depth buffer required.
// This shader tests presentation ordering, independent of SceneDepthZ discovery.
#include "DuoViewNativeCompositeRaster.hlsl"
float4 PSNativeEyeCheck(VertexOut i) : SV_TARGET0 {
    float4 color=PSNativeMain(i);
    const bool right=i.pos.x>=OutputSize.x;
    const float localX=right ? i.pos.x-OutputSize.x : i.pos.x;
    // Obvious per-eye identifying bars, intentionally NOT convincing stereo.
    const float4 eyeColor=right ? float4(1.0,.15,.05,1.0) : float4(.03,.85,1.0,1.0);
    const bool border=localX<24.0 || localX>OutputSize.x-24.0 ||
        i.pos.y<24.0 || i.pos.y>OutputSize.y-24.0;
    const bool stripe=fmod(floor(i.pos.y/48.0),2.0)<1.0 && localX<70.0;
    color.rgb=lerp(color.rgb,eyeColor.rgb,border ? .92 : (stripe ? .68 : .07));
    return color;
}

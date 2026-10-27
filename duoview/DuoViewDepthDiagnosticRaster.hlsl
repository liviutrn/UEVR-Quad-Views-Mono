// Live depth-candidate preview, ONLY active when explicitly selected in ImGui.
// Physical depth values are non-linear/reversed-Z. False color is for structural
// matching with the real fovea/periphery source images, not metric distance.
#include "DuoViewCompositeRaster.hlsl"
Texture2D<float> LeftDepthCandidate:register(t2);
Texture2D<float> RightDepthCandidate:register(t3);
float4 PSDepthDiagnostic(VertexOut v):SV_TARGET0 {
    float2 p=v.pos.xy;
    uint eye=0u;
    if(p.x>=OutputSize.x) { p.x-=OutputSize.x;eye=1u; }
    const float2 uv=saturate(p/float2(OutputSize));
    // 3 left both XR eyes; 4 right both XR eyes; 5 split side-by-side.
    bool useRight=(DebugViewMode==4u)||(DebugViewMode==5u&&eye==1u);
    uint w,h;
    if(useRight)RightDepthCandidate.GetDimensions(w,h);
    else LeftDepthCandidate.GetDimensions(w,h);
    if(w==0||h==0)return float4(1,0,1,1);
    const uint2 coord=min(uint2(uv*float2(w,h)),uint2(w-1,h-1));
    const float d=useRight?RightDepthCandidate.Load(int3(coord,0)):
                           LeftDepthCandidate.Load(int3(coord,0));
    if(!isfinite(d)||d<=0||d>1)return float4(1,0,1,1);
    const float luminance=saturate(log2(max(d,0.000001f)*65536.0f)/16.0f);
    const float3 tagColor=useRight?float3(.1,.4,1):float3(1,.3,.1);
    return float4(lerp(float3(luminance,luminance,luminance),tagColor,.25f),1);
}

// Manual-first DuoView depth image based reprojection.
// The matrices map normalized source clip coordinates (including the raw
// device-depth sample) to a target eye clip space. They are frozen with the
// accepted source frame. The shader never guesses depth encoding or identity.

Texture2D<float4> CenterColor : register(t0);
Texture2D<float> PeripheryDepth : register(t1);
Texture2D<float> FoveaDepth : register(t2);
SamplerState LinearClamp : register(s0);

cbuffer DibrConfig : register(b0)
{
    uint2 OutputSize;       // one eye's active output extent
    uint2 ColorSize;
    uint2 PeripheryDepthSize;
    uint2 PeripheryPadding;
    uint4 PeripheryDepthRect; // active periphery rect in PeripheryDepthSize
    uint2 FoveaDepthSize;
    uint2 FoveaPadding;
    uint4 FoveaDepthRect;     // active fovea rect in FoveaDepthSize
    uint4 ColorRect;        // active center-color rect in ColorSize
    uint4 Config;           // eye index, iterations, use fovea, reserved
    float4 DepthValidity;   // min, max, clear value, clear epsilon
    float4 FoveaUvRect;     // fovea coverage in full-view UV coordinates
    row_major float4x4 SourceNdcToTargetClip;
};

struct VertexOut {
    float4 pos : SV_POSITION;
    float2 uv : TEXCOORD0;
};

VertexOut VSMain(uint vertexId : SV_VertexID) {
    VertexOut v;
    v.uv = float2((vertexId << 1) & 2, vertexId & 2);
    v.pos = float4(v.uv * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
    return v;
}

bool use_fovea_at(float2 sourceUv) {
    return Config.z != 0 && all(sourceUv >= FoveaUvRect.xy) &&
        all(sourceUv <= FoveaUvRect.zw);
}

float read_depth(float2 sourceUv) {
    if (use_fovea_at(sourceUv)) {
        const float2 foveaUv = (sourceUv - FoveaUvRect.xy) /
            max(FoveaUvRect.zw - FoveaUvRect.xy, float2(1.0e-7, 1.0e-7));
        const int2 maxPixel = int2(FoveaDepthRect.xy + FoveaDepthRect.zw - 1);
        const int2 pixel = clamp(int2(float2(FoveaDepthRect.xy) + saturate(foveaUv) *
            float2(FoveaDepthRect.zw)), int2(FoveaDepthRect.xy), maxPixel);
        return FoveaDepth.Load(int3(pixel, 0));
    }
    const int2 maxPixel = int2(PeripheryDepthRect.xy + PeripheryDepthRect.zw - 1);
    const int2 pixel = clamp(int2(float2(PeripheryDepthRect.xy) + saturate(sourceUv) *
        float2(PeripheryDepthRect.zw)), int2(PeripheryDepthRect.xy), maxPixel);
    return PeripheryDepth.Load(int3(pixel, 0));
}

bool depth_is_valid(float d) {
    // Reversed-Z clear depth is the far-plane direction, not a missing
    // sample. Project it with the same center-to-eye homogeneous matrix:
    // camera translation vanishes for a direction at infinity, while eye
    // projection differences remain represented. Only non-finite and
    // out-of-range values fall back to center color.
    return isfinite(d) && d >= DepthValidity.x && d <= DepthValidity.y;
}

float2 project_to_target(float2 sourceUv, float d) {
    const float2 sourceNdc = float2(sourceUv.x * 2.0 - 1.0, 1.0 - sourceUv.y * 2.0);
    const float4 target = mul(SourceNdcToTargetClip, float4(sourceNdc, d, 1.0));
    if (!all(isfinite(target)) || abs(target.w) < 1.0e-7) return sourceUv;
    const float2 targetNdc = target.xy / target.w;
    return float2(targetNdc.x * 0.5 + 0.5, 0.5 - targetNdc.y * 0.5);
}

float4 PSMain(VertexOut i) : SV_TARGET0 {
    float2 eyePixel = i.pos.xy;
    eyePixel.x -= Config.x * OutputSize.x;
    const float2 targetUv = eyePixel / float2(OutputSize);
    float2 sourceUv = targetUv;
    float d = read_depth(sourceUv);
    const bool valid = depth_is_valid(d);

    if (valid) {
        const uint iterations = clamp(Config.y, 1u, 4u);
        [unroll] for (uint step = 0; step < 4; ++step) {
            if (step >= iterations) break;
            const float2 projected = project_to_target(sourceUv, d);
            sourceUv = saturate(sourceUv + targetUv - projected);
            d = read_depth(sourceUv);
            if (!depth_is_valid(d)) {
                sourceUv = targetUv;
                break;
            }
        }
    }

    const float2 colorPixel = float2(ColorRect.xy) + saturate(sourceUv) * float2(ColorRect.zw);
    const float2 colorUv = clamp(colorPixel / float2(ColorSize),
        (float2(ColorRect.xy) + 0.5) / float2(ColorSize),
        (float2(ColorRect.xy + ColorRect.zw) - 0.5) / float2(ColorSize));
    return CenterColor.SampleLevel(LinearClamp, colorUv, 0.0);
}

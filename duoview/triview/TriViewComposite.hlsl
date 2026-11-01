// Tri-View Stage 1 compositor (rendering method ID 7), one draw over the double-wide XR image.
// t0 = Joey's main Native Fix target: left fovea at (0,0), centre periphery at PeriphRect.
// t1 = Joey's Native Fix scene-capture target: right fovea at (0,0).
// Each eye: periphery remapped into that eye (affine, parallel eyes) underneath, own fovea on top.
Texture2D<float4> MainSource : register(t0);
Texture2D<float4> CaptureSource : register(t1);
SamplerState LinearClamp : register(s0);

cbuffer TriViewConstants : register(b0) {
    float4 EyeAndFovea;   // eye width, eye height, fovea width, fovea height (pixels)
    float4 FoveaWindow;   // u0, v0, u1, v1 in eye UV
    float4 PeriphMapL;    // ax, bx, ay, by: periphery uv = (ax*u + bx, ay*v + by), left eye
    float4 PeriphMapR;    // same, right eye
    float4 PeriphRect;    // x, y, width, height of the periphery in MainSource pixels
    float4 SourceSizes;   // MainSource width/height, CaptureSource width/height
    float4 Params;        // feather (fraction of fovea), periphery present (0/1), debug bits (1 border, 2 raw targets),
                          // colour fix: 0 none, 1 sRGB decode (UNORM source -> sRGB XR), 2 encode (reverse)
};

float3 SrgbToLinear(float3 c) { return c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4); }
float3 LinearToSrgb(float3 c) { return c <= 0.0031308 ? c * 12.92 : 1.055 * pow(c, 1.0 / 2.4) - 0.055; }

struct VertexOut {
    float4 pos : SV_POSITION;
};

VertexOut VSMain(uint id : SV_VertexID) {
    VertexOut o;
    const float2 uv = float2((id << 1) & 2, id & 2);
    o.pos = float4(uv * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
    return o;
}

float2 ActiveTexel(float2 local, float2 origin, float2 size) {
    return origin + clamp(saturate(local) * size, float2(0.5, 0.5), size - 0.5);
}

float4 PSMain(VertexOut i) : SV_TARGET0 {
    const float2 eyeSize = EyeAndFovea.xy;
    const bool rightEye = i.pos.x >= eyeSize.x;
    const float2 uv = float2(rightEye ? i.pos.x - eyeSize.x : i.pos.x, i.pos.y) / eyeSize;

    float4 periphery = float4(0.0, 0.0, 0.0, 1.0);
    if (Params.y > 0.5) {
        const float4 m = rightEye ? PeriphMapR : PeriphMapL;
        const float2 puv = float2(m.x * uv.x + m.y, m.z * uv.y + m.w);
        periphery = MainSource.SampleLevel(LinearClamp,
            ActiveTexel(puv, PeriphRect.xy, PeriphRect.zw) / SourceSizes.xy, 0.0);
    }

    const float2 local = (uv - FoveaWindow.xy) / (FoveaWindow.zw - FoveaWindow.xy);
    float weight = 0.0;
    if (local.x >= 0.0 && local.y >= 0.0 && local.x <= 1.0 && local.y <= 1.0) {
        const float edge = min(min(local.x, 1.0 - local.x), min(local.y, 1.0 - local.y));
        weight = Params.x > 0.0 ? smoothstep(0.0, Params.x, edge) : 1.0;
    }

    float4 result = periphery;
    if (weight > 0.0) {
        const float2 texel = ActiveTexel(local, float2(0.0, 0.0), EyeAndFovea.zw);
        const float4 fovea = rightEye
            ? CaptureSource.SampleLevel(LinearClamp, texel / SourceSizes.zw, 0.0)
            : MainSource.SampleLevel(LinearClamp, texel / SourceSizes.xy, 0.0);
        result = lerp(periphery, fovea, weight);
    }
    const uint debugBits = (uint)(Params.z + 0.5);
    // Debug bit 2: raw render targets. Left eye = the WHOLE main target squeezed 2:1 (fovea on the left,
    // periphery on the right if it landed there); right eye = the whole capture target.
    if ((debugBits & 2u) != 0u) {
        result = rightEye ? CaptureSource.SampleLevel(LinearClamp, uv, 0.0)
                          : MainSource.SampleLevel(LinearClamp, uv, 0.0);
    }
    if ((debugBits & 1u) != 0u && weight > 0.01 && weight < 0.1) result.rgb = float3(1.0, 0.3, 0.0);
    if (Params.w > 1.5) result.rgb = LinearToSrgb(saturate(result.rgb));
    else if (Params.w > 0.5) result.rgb = SrgbToLinear(saturate(result.rgb));
    result.a = 1.0;
    return result;
}

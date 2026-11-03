// Tri-View compositor (rendering method ID 7), one draw over the double-wide XR image.
// Every engine render of STALKER 2.10 (UE 5.5.4) lands at (0,0) of its own target (Build 52 GPU capture),
// so each source image is read from its own texture at local origin:
// t0 = Joey's main Native Fix target: left fovea at (0,0).
// t1 = Joey's Native Fix scene-capture target: right fovea at (0,0).
// t2 = Tri-View's own periphery target: centre periphery at (0,0) (null when view 2 was not rendered).
// Each eye: periphery remapped into that eye (affine, parallel eyes) underneath, own fovea on top.
Texture2D<float4> MainSource : register(t0);
Texture2D<float4> CaptureSource : register(t1);
Texture2D<float4> PeripherySource : register(t2);
SamplerState LinearClamp : register(s0);

cbuffer TriViewConstants : register(b0) {
    float4 EyeAndFovea;   // eye width, eye height, fovea width, fovea height (pixels)
    float4 FoveaWindowL;  // u0, v0, u1, v1 in eye UV, left eye (moves with the gaze)
    float4 FoveaWindowR;  // same, right eye
    float4 PeriphMapL;    // ax, bx, ay, by: periphery uv = (ax*u + bx, ay*v + by), left eye
    float4 PeriphMapR;    // same, right eye
    float4 PeriphRect;    // periphery image width, height (pixels, at (0,0) of t2); t2 width, height
    float4 SourceSizes;   // MainSource width/height, CaptureSource width/height
    float4 Params;        // feather (fraction of fovea), periphery present (0/1), debug bits (1 border),
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

// Texel position of a local UV inside an image of `size` pixels at the texture origin,
// clamped half a texel inside so bilinear taps never read outside the rendered image.
float2 ActiveTexel(float2 local, float2 size) {
    return clamp(saturate(local) * size, float2(0.5, 0.5), size - 0.5);
}

float4 PSMain(VertexOut i) : SV_TARGET0 {
    const float2 eyeSize = EyeAndFovea.xy;
    const bool rightEye = i.pos.x >= eyeSize.x;
    const float2 uv = float2(rightEye ? i.pos.x - eyeSize.x : i.pos.x, i.pos.y) / eyeSize;

    // PROOF mode (debug bit 2): third view = clone of the right eye. Left eye = real left view; right eye, left half
    // = real second view (Native Fix capture), right half = THIRD view tinted red; a 2 px black seam between them.
    if (((uint)(Params.z + 0.5) & 2u) != 0u) {
        const float2 texelOwn = ActiveTexel(uv, EyeAndFovea.zw);
        float4 proof;
        if (!rightEye) {
            proof = MainSource.SampleLevel(LinearClamp, texelOwn / SourceSizes.xy, 0.0);
        } else if (uv.x < 0.5) {
            proof = CaptureSource.SampleLevel(LinearClamp, texelOwn / SourceSizes.zw, 0.0);
        } else {
            proof = float4(0.0, 0.0, 0.0, 1.0);
            if (Params.y > 0.5) {
                proof = PeripherySource.SampleLevel(LinearClamp, ActiveTexel(uv, PeriphRect.xy) / PeriphRect.zw, 0.0);
            }
            proof.rgb *= float3(1.0, 0.35, 0.35);
        }
        if (rightEye && abs(i.pos.x - eyeSize.x - eyeSize.x * 0.5) < 1.0) proof.rgb = float3(0.0, 0.0, 0.0);
        if (Params.w > 1.5) proof.rgb = LinearToSrgb(saturate(proof.rgb));
        else if (Params.w > 0.5) proof.rgb = SrgbToLinear(saturate(proof.rgb));
        proof.a = 1.0;
        return proof;
    }

    float4 periphery = float4(0.0, 0.0, 0.0, 1.0);
    if (Params.y > 0.5) {
        const float4 m = rightEye ? PeriphMapR : PeriphMapL;
        const float2 puv = float2(m.x * uv.x + m.y, m.z * uv.y + m.w);
        periphery = PeripherySource.SampleLevel(LinearClamp, ActiveTexel(puv, PeriphRect.xy) / PeriphRect.zw, 0.0);
    }

    const float4 foveaWindow = rightEye ? FoveaWindowR : FoveaWindowL;
    const float2 local = (uv - foveaWindow.xy) / (foveaWindow.zw - foveaWindow.xy);
    float weight = 0.0;
    if (local.x >= 0.0 && local.y >= 0.0 && local.x <= 1.0 && local.y <= 1.0) {
        const float edge = min(min(local.x, 1.0 - local.x), min(local.y, 1.0 - local.y));
        weight = Params.x > 0.0 ? smoothstep(0.0, Params.x, edge) : 1.0;
    }

    float4 result = periphery;
    if (weight > 0.0) {
        const float2 texel = ActiveTexel(local, EyeAndFovea.zw);
        const float4 fovea = rightEye
            ? CaptureSource.SampleLevel(LinearClamp, texel / SourceSizes.zw, 0.0)
            : MainSource.SampleLevel(LinearClamp, texel / SourceSizes.xy, 0.0);
        result = lerp(periphery, fovea, weight);
    }
    const uint debugBits = (uint)(Params.z + 0.5);
    if ((debugBits & 1u) != 0u && weight > 0.01 && weight < 0.1) result.rgb = float3(1.0, 0.3, 0.0);
    if (Params.w > 1.5) result.rgb = LinearToSrgb(saturate(result.rgb));
    else if (Params.w > 0.5) result.rgb = SrgbToLinear(saturate(result.rgb));
    result.a = 1.0;
    return result;
}

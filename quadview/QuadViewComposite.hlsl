Texture2D<float4> ContextLeftSource : register(t0);
Texture2D<float4> ContextRightSource : register(t1);
Texture2D<float4> FocusLeftSource : register(t2);
Texture2D<float4> FocusRightSource : register(t3);
Texture2D<float> PeripheryDepth : register(t4); // B7: DLSS depth input of the periphery render (reversed-Z)
SamplerState LinearClamp : register(s0);

cbuffer QuadViewConstants : register(b0) {
    uint4 EyeAndAtlas;
    uint4 ContextLeft;
    uint4 ContextRight;
    uint4 FocusLeft;
    uint4 FocusRight;
    float4 CropUvLeft;
    float4 CropUvRight;
    float4 Options;
    float4 Sharpen; // legacy strength, flags, legacy max change, FXAA bias
    float4 SharpenEye; // left strength, right strength, left max change, right max change
    float4 ContextHLeft[3];  // tri-view: h = H * (uv, 1), context uv = h.xy / h.z (identity for four views)
    float4 ContextHRight[3];
    uint4 ContextSource;     // x left eye, y right eye (tri-view: both 0)
    float4 DepthShift;       // B7: context-uv shift per unit reversed-Z depth (left u, v, right u, v)
    uint4 DepthRect;         // B7: depth texel rectangle of the periphery render (x, y, w, h)
    uint4 DepthOptions;      // B9: x = reproject, y = show requested, z = validated depth bound
    float4 DepthEyeOrigin[2];
    float4 DepthProjection;
    float4 DepthCoefficients;
    float4 DepthJitter;
};

struct VertexOut {
    float4 position : SV_POSITION;
};

VertexOut VSMain(uint vertexId : SV_VertexID) {
    const float2 uv = float2((vertexId << 1) & 2, vertexId & 2);
    VertexOut result;
    result.position = float4(uv * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
    return result;
}

// B6: every source is normalised by its OWN texture size (compact per-role
// targets); for the shared atlas or full-size targets this equals EyeAndAtlas.zw.
float2 SourceSize(uint sourceIndex) {
    uint width = 1u, height = 1u;
    [branch] if (sourceIndex == 0u) ContextLeftSource.GetDimensions(width, height);
    else if (sourceIndex == 1u) ContextRightSource.GetDimensions(width, height);
    else if (sourceIndex == 2u) FocusLeftSource.GetDimensions(width, height);
    else FocusRightSource.GetDimensions(width, height);
    return float2(max(width, 1u), max(height, 1u));
}

float2 AtlasUv(uint sourceIndex, uint4 rectangle, float2 uv) {
    const float2 atlasSize = SourceSize(sourceIndex);
    const float2 origin = float2(rectangle.xy);
    const float2 extent = float2(rectangle.zw);
    const float2 texel = clamp(origin + saturate(uv) * extent,
                              origin + 0.5, origin + extent - 0.5);
    return texel / atlasSize;
}

float2 ContextUv(uint eye, float2 eyeUv) {
    const float3 p = float3(eyeUv, 1.0);
    float3 h;
    [flatten] if (eye == 0) h = float3(dot(ContextHLeft[0].xyz, p), dot(ContextHLeft[1].xyz, p), dot(ContextHLeft[2].xyz, p));
    else h = float3(dot(ContextHRight[0].xyz, p), dot(ContextHRight[1].xyz, p), dot(ContextHRight[2].xyz, p));
    return h.xy / max(h.z, 1.0e-4);
}

// Source depth is matched to this context frame. Jitter converts unjittered
// DLSS color UV into the corresponding raw depth sample location.
float PeripheryDepthAt(float2 uv) {
    const float2 p = float2(DepthRect.xy) + saturate(uv + DepthJitter.xy) * float2(DepthRect.zw);
    const uint2 last = DepthRect.xy + max(DepthRect.zw, 1u) - 1u;
    return saturate(PeripheryDepth.Load(int3(min(uint2(p), last), 0)));
}

float InverseDepthAt(float2 uv) {
    return (DepthCoefficients.z * PeripheryDepthAt(uv) - DepthCoefficients.x) / DepthCoefficients.y;
}

// B12: the eye ray is marched through the periphery depth, from near to far, in
// inverse-depth steps; the first surface it meets is what this eye sees. B7-B11
// used a 4-step fixed point that, for close objects (hands, gun: up to ~7 % of
// the periphery width of disparity), stayed on the mono position and showed a
// second, unshifted copy of the arm. Where the eye sees background that the
// periphery camera could not (behind a near object), `fill` is set and the
// caller blends a soft background sample instead of stretching the edge.
// Verified offline against the real fovea of a B11 game snapshot.
float2 WarpContextUv(uint eye, float2 contextUv, out float fill) {
    float2 uv = contextUv; // single exit: fxc /WX rejects early returns here (X4000)
    fill = 0.0;
    [branch] if (DepthOptions.x != 0u) {
        const float3 t = DepthEyeOrigin[eye].xyz;
        const float2 ray = float2((2.0 * contextUv.x - 1.0 - DepthProjection.y) / DepthProjection.x,
                                 (1.0 - 2.0 * contextUv.y - DepthProjection.w) / DepthProjection.z);
        // context-uv shift per unit of inverse depth (full eye translation incl. forward/vertical)
        const float2 k = float2(0.5 * DepthProjection.x, -0.5 * DepthProjection.z) * (t.xy - ray * t.z) * DepthCoefficients.w;
        // nearest surface searched: 8 world units (~8 cm), or the near plane if farther
        const float sMax = min(abs(DepthCoefficients.z / DepthCoefficients.y), 0.125);
        const float ds = sMax / 24.0;
        float2 previousUv = contextUv + k * sMax;
        float previousF = -1.0, previousInverse = 0.0;
        bool found = false;
        [loop] for (uint i = 0; i <= 24u && !found; ++i) {
            const float s = sMax - ds * float(i);
            const float2 c = contextUv + k * s;
            const bool inside = all(c >= 0.0) && all(c <= 1.0);
            const float inverseZ = inside ? InverseDepthAt(c) : 0.0;
            const float f = inverseZ - s;
            [branch] if (inside && f >= 0.0) {
                found = true;
                if (i == 0u) {
                    uv = c;
                } else if (inverseZ > previousInverse * 1.25 + 2.0 * ds) {
                    // depth jumps in front of the ray: hidden background, fill softly
                    uv = contextUv + k * (s + 4.0 * ds);
                    fill = 1.0;
                } else {
                    uv = lerp(previousUv, c, saturate(previousF / min(previousF - f, -1.0e-6)));
                }
            }
            previousF = inside ? f : -1.0;
            previousUv = c;
            previousInverse = inverseZ;
        }
    }
    return uv;
}

// Explicit SM5 resource selection keeps each source independent, including sharpening taps.
float4 ReadSource(uint sourceIndex, float2 uv) {
    float4 color = float4(0.0, 0.0, 0.0, 1.0);
    [branch] if (sourceIndex == 0u) color = ContextLeftSource.SampleLevel(LinearClamp, uv, 0.0);
    else if (sourceIndex == 1u) color = ContextRightSource.SampleLevel(LinearClamp, uv, 0.0);
    else if (sourceIndex == 2u) color = FocusLeftSource.SampleLevel(LinearClamp, uv, 0.0);
    else color = FocusRightSource.SampleLevel(LinearClamp, uv, 0.0);
    return color;
}

float FocusWeight(float2 uv, float4 crop) {
    if (any(uv < crop.xy) || any(uv > crop.zw)) return 0.0;
    const float2 cropExtent = crop.zw - crop.xy;
    const float2 distanceToEdge = min(uv - crop.xy, crop.zw - uv) / cropExtent;
    const float feather = clamp(Options.x, 0.0, 0.49);
    if (feather == 0.0) return 1.0;
    const float edge = saturate(min(distanceToEdge.x, distanceToEdge.y) / feather);
    return edge * edge * (3.0 - 2.0 * edge);
}

static const float3 GlamLuma = float3(0.2126, 0.7152, 0.0722);

float3 GlamDecode(float3 color) {
    if (((uint)Sharpen.y & 4u) == 0u) return color;
    const float3 low = color / 12.92;
    const float3 high = pow(abs(color + 0.055) / 1.055, 2.4);
    return lerp(low, high, float3(color.r > 0.04045, color.g > 0.04045, color.b > 0.04045));
}

float3 GlamEncode(float3 color) {
    if (((uint)Sharpen.y & 4u) == 0u) return color;
    const float3 low = color * 12.92;
    const float3 high = 1.055 * pow(abs(color), 1.0 / 2.4) - 0.055;
    return lerp(low, high, float3(color.r > 0.0031308, color.g > 0.0031308, color.b > 0.0031308));
}

float3 ReadFocus(uint sourceIndex, uint4 rect, float4 crop, float2 fullUv, float2 pixelOffset) {
    // Offsets are in final output pixels after the game's upscaler. AtlasUv
    // clamps each tap to this eye's focus rectangle, so eyes never bleed.
    const float2 shifted = fullUv + pixelOffset / float2(EyeAndAtlas.xy);
    const float2 local = (shifted - crop.xy) / (crop.zw - crop.xy);
    return GlamDecode(ReadSource(sourceIndex, AtlasUv(sourceIndex, rect, local)).rgb);
}

float3 GlamSharpenFocus(uint sourceIndex, uint4 rect, float4 crop, float2 fullUv, float3 center,
                        float strength, float maxChange) {
    // Fused v186.1 Glamarye Bigger-radius four-diagonal filter with its
    // FXAA-style edge guard and maximum-change limiter. No separate pass.
    const float3 c = GlamDecode(center);
    const float radius = 1.4;
    const float3 ne = ReadFocus(sourceIndex, rect, crop, fullUv, float2( radius,  radius));
    const float3 sw = ReadFocus(sourceIndex, rect, crop, fullUv, float2(-radius, -radius));
    const float3 se = ReadFocus(sourceIndex, rect, crop, fullUv, float2( radius, -radius));
    const float3 nw = ReadFocus(sourceIndex, rect, crop, fullUv, float2(-radius,  radius));
    float3 smoothed = (ne + nw) + (se + sw);
    smoothed = clamp((smoothed + c) / 5.0, c * 0.5, c * 2.0);
    smoothed = min(smoothed, 1.0);

    const float dy = dot(GlamLuma, abs((ne + nw) - (se + sw)));
    const float dx = dot(GlamLuma, abs((ne + se) - (nw + sw)));
    const bool horizontal = dy > dx;
    float3 n2 = horizontal ? ne + nw : ne + se;
    float3 s2 = horizontal ? se + sw : nw + sw;
    n2 *= 0.5; s2 *= 0.5;
    const float2 west = horizontal ? float2(-3.5, 0.0) : float2(0.0, 3.5);
    const float2 east = horizontal ? float2( 3.5, 0.0) : float2(0.0,-3.5);
    const float3 ww = ReadFocus(sourceIndex, rect, crop, fullUv, west);
    const float3 ee = ReadFocus(sourceIndex, rect, crop, fullUv, east);
    const float3 d1 = abs((ww - n2) - (ee - s2));
    const float3 d2 = abs((ee - n2) - (ww - s2));
    const float3 totalDiff = d1 + d2 + 0.00004;
    const float3 maxDiff = max(d1, d2) + 0.00001 - Sharpen.w * sqrt(max(smoothed, 0.0));
    const float edgeRatio = max(2.0 * dot(GlamLuma, maxDiff / totalDiff) - 1.0, 0.0);

    const float3 diffRGB = 2.0 * c + (ne + nw + se + sw)
        - 3.0 * (max(max(ne,nw),max(se,sw)) + min(min(ne,nw),min(se,sw)));
    const float diff = dot(GlamLuma, diffRGB);
    float3 possible = min(smoothed, c * 0.5);
    possible = min(possible, 1.0 - max(smoothed, c));
    possible = clamp(possible, 0.00001, maxChange);
    float3 change = diff / (1.0 / max(strength, 0.00001) + abs(diff) / possible);
    change *= (1.0 - edgeRatio);
    return GlamEncode(c + change);
}

float4 ReadContext(uint eye, uint contextSource, uint4 contextRect, float2 contextUv) {
    float fill = 0.0;
    const float2 uv = WarpContextUv(eye, contextUv, fill);
    float4 color = float4(0.0, 0.0, 0.0, 1.0);
    [branch] if (DepthOptions.y != 0u) {
        const float v = pow(PeripheryDepthAt(uv), 0.25);
        color = float4(v, v, v, 1.0);
    } else if (fill > 0.0) {
        // B12: soft 3x5 background average (2-texel spacing) hides row streaks in disocclusions
        const float2 step = 2.0 / max(float2(contextRect.zw), 1.0);
        float4 sum = float4(0.0, 0.0, 0.0, 0.0);
        [unroll] for (int y = -2; y <= 2; ++y)
            [unroll] for (int x = -1; x <= 1; ++x)
                sum += ReadSource(contextSource, AtlasUv(contextSource, contextRect, uv + float2(x, y) * step));
        color = sum / 15.0;
    } else {
        color = ReadSource(contextSource, AtlasUv(contextSource, contextRect, uv));
    }
    return color;
}

float4 ScenePixel(VertexOut input) {
    const uint eye = min((uint)input.position.x / EyeAndAtlas.x, 1u);
    const float2 eyeUv = float2(input.position.x - eye * EyeAndAtlas.x,
                               input.position.y) / float2(EyeAndAtlas.xy);
    const uint4 contextRect = eye == 0 ? ContextLeft : ContextRight;
    const uint contextSource = eye == 0 ? ContextSource.x : ContextSource.y;
    const float2 contextUv = ContextUv(eye, eyeUv);
    const uint4 focusRect = eye == 0 ? FocusLeft : FocusRight;
    const float4 crop = eye == 0 ? CropUvLeft : CropUvRight;
    const uint debugMode = (uint)Options.y;
    const float weight = FocusWeight(eyeUv, crop);

    if (debugMode == 3) {
        const float3 contextColor = eye == 0 ? float3(0.8, 0.1, 0.1) : float3(0.1, 0.8, 0.1);
        const float3 focusColor = eye == 0 ? float3(0.1, 0.2, 1.0) : float3(1.0, 0.8, 0.1);
        return float4(lerp(contextColor, focusColor, weight), 1.0);
    }

    // The context sample is unnecessary under opaque focus. In the default
    // 50% crop this skips a texture fetch for most focused pixels, including
    // pixels using the fused Glamarye filter. Keep diagnostics exact.
    if (debugMode == 1)
        return ReadContext(eye, contextSource, contextRect, contextUv);
    if (weight <= 0.0) {
        if (debugMode == 2) return float4(0.04, 0.04, 0.04, 1.0);
        return ReadContext(eye, contextSource, contextRect, contextUv);
    }

    const float2 focusUv = (eyeUv - crop.xy) / (crop.zw - crop.xy);
    float4 focus = ReadSource(2u + eye, AtlasUv(2u + eye, focusRect, focusUv));
    const float eyeStrength = eye == 0u ? SharpenEye.x : SharpenEye.y;
    const float eyeMaxChange = eye == 0u ? SharpenEye.z : SharpenEye.w;
    [branch] if (eyeStrength > 0.0)
        focus.rgb = GlamSharpenFocus(2u + eye, focusRect, crop, eyeUv, focus.rgb, eyeStrength, eyeMaxChange);
    float4 output = focus;
    [branch] if (debugMode != 2 && weight < 1.0) {
        const float4 context = ReadContext(eye, contextSource, contextRect, contextUv);
        output = lerp(context, focus, weight);
    }
    if (Options.w > 0.5) {
        const float2 edgePx = min(eyeUv - crop.xy, crop.zw - eyeUv) * float2(EyeAndAtlas.xy);
        if (min(edgePx.x, edgePx.y) < 1.0) output.rgb = float3(1.0, 0.75, 0.0);
    }
    return output;
}

// Keep one initialized return path: legacy FXC rejects nested early diagnostic
// returns as potentially uninitialized output under /WX.
float4 CompositePixel(VertexOut input) {
    float4 color = float4(0.0, 0.0, 0.0, 1.0);
    [branch] if (DepthOptions.y != 0u) {
        if (DepthOptions.z == 0u) {
            const uint checker = ((uint(input.position.x) / 8u) + (uint(input.position.y) / 8u)) & 1u;
            color = checker != 0u ? float4(1, 0, 1, 1) : float4(0, 0, 0, 1);
        } else {
            const uint eye = min((uint)input.position.x / EyeAndAtlas.x, 1u);
            const float2 eyeUv = float2(input.position.x - eye * EyeAndAtlas.x,
                input.position.y) / float2(EyeAndAtlas.xy);
            const float v = pow(PeripheryDepthAt(ContextUv(eye, eyeUv)), 0.25);
            color = float4(v, v, v, 1);
        }
    } else {
        color = ScenePixel(input);
    }
    return color;
}

// Preserve the baseline copy's color encoding when a typed UNORM atlas is
// drawn into an sRGB runtime texture. The RTV performs the inverse encoding.
float4 PSMain(VertexOut input) : SV_TARGET0 {
    float4 color = CompositePixel(input);
    if (Options.z > 0.5) {
        const float3 low = color.rgb / 12.92;
        const float3 high = pow(max((color.rgb + 0.055) / 1.055, 0.0), 2.4);
        color.rgb = float3(color.r <= 0.04045 ? low.r : high.r,
                           color.g <= 0.04045 ? low.g : high.g,
                           color.b <= 0.04045 ? low.b : high.b);
    }
    return color;
}

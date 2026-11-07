Texture2D<float4> ContextLeftSource : register(t0);
Texture2D<float4> ContextRightSource : register(t1);
Texture2D<float4> FocusLeftSource : register(t2);
Texture2D<float4> FocusRightSource : register(t3);
Texture2D<float> PeripheryDepth : register(t4); // B7: DLSS depth input of the periphery render (reversed-Z)
StructuredBuffer<float4> SeamMatch : register(t5); // per eye: global + eight boundary gains
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
    float4 Seam;        // mode, strength, maximum relative auto gain, manual sample-domain gain
    float4 SeamOptions; // color strength, reserved rendered-edge pixels, confidence debug, alignment usable
    float4 SeamLocal;   // outward residual radius in output pixels, local strength, reserved
    float4 FocusLift;    // enabled, overall brightness, corner gain minus one, onset r^2
    float4 FocusProfile; // exponent, anti-vignette strength, reserved
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

float2 AtlasUvKnownSize(float2 atlasSize, uint4 rectangle, float2 uv) {
    const float2 origin = float2(rectangle.xy);
    const float2 extent = float2(rectangle.zw);
    const float2 texel = clamp(origin + saturate(uv) * extent,
                              origin + 0.5, origin + extent - 0.5);
    return texel / atlasSize;
}

float2 AtlasUv(uint sourceIndex, uint4 rectangle, float2 uv) {
    return AtlasUvKnownSize(SourceSize(sourceIndex), rectangle, uv);
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
        const float ds = sMax / 3.0;
        float2 previousUv = contextUv + k * sMax;
        float previousF = -1.0, previousInverse = 0.0;
        bool found = false;
        [loop] for (uint i = 0; i <= 3u && !found; ++i) {
            const float s = sMax - ds * float(i);
            const float2 c = contextUv + k * s;
            const bool inside = all(c >= 0.0) && all(c <= 1.0);
            const float inverseZ = inside ? InverseDepthAt(c) : 0.0;
            const float f = inverseZ - s;
            [branch] if (inside && f >= 0.0) {
                found = true;
                if (i == 0u || previousF <= -0.5) {
                    // Never blend with the previous out-of-bounds ray.
                    uv = c;
                } else if (previousF > -0.5 && inverseZ > previousInverse * 1.25 + 2.0 * ds) {
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

float3 ReadFocus(uint sourceIndex, uint4 rect, float2 focusUv, float2 tapScale, float2 pixelOffset, float2 sourceSize) {
    // Share crop/output normalization across the six sharpening taps.
    // AtlasUv still clamps taps to this eye's focus rectangle.
    const float2 local = focusUv + pixelOffset * tapScale;
    return GlamDecode(ReadSource(sourceIndex, AtlasUvKnownSize(sourceSize, rect, local)).rgb);
}

float3 GlamSharpenFocus(uint sourceIndex, uint4 rect, float2 focusUv, float2 tapScale, float3 center,
                        float strength, float maxChange, float2 sourceSize) {
    // Fused v186.1 Glamarye Bigger-radius four-diagonal filter with its
    // FXAA-style edge guard and maximum-change limiter. No separate pass.
    const float3 c = GlamDecode(center);
    const float radius = 1.4;
    const float3 ne = ReadFocus(sourceIndex, rect, focusUv, tapScale, float2( radius,  radius), sourceSize);
    const float3 sw = ReadFocus(sourceIndex, rect, focusUv, tapScale, float2(-radius, -radius), sourceSize);
    const float3 se = ReadFocus(sourceIndex, rect, focusUv, tapScale, float2( radius, -radius), sourceSize);
    const float3 nw = ReadFocus(sourceIndex, rect, focusUv, tapScale, float2(-radius,  radius), sourceSize);
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
    const float3 ww = ReadFocus(sourceIndex, rect, focusUv, tapScale, west, sourceSize);
    const float3 ee = ReadFocus(sourceIndex, rect, focusUv, tapScale, east, sourceSize);
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

float4 ReadContext(uint eye, uint contextSource, uint4 contextRect, float2 eyeUv) {
    // Fully opaque native fovea pixels never need this context homography.
    const float2 contextUv = ContextUv(eye, eyeUv);
    float fill = 0.0;
    const float2 uv = WarpContextUv(eye, contextUv, fill);
    float4 color = float4(0.0, 0.0, 0.0, 1.0);
    [branch] if (DepthOptions.y != 0u) {
        const float v = pow(PeripheryDepthAt(uv), 0.25);
        color = float4(v, v, v, 1.0);
    } else if (fill > 0.0) {
        // B12: soft 3x5 background average (2-texel spacing) hides row streaks in disocclusions
        // One resource-dimension query per disocclusion pixel, not once per tap.
        const float2 sourceSize = SourceSize(contextSource);
        const float2 tap = 2.0 / max(float2(contextRect.zw), 1.0);
        float4 sum = float4(0.0, 0.0, 0.0, 0.0);
        [unroll] for (int y = -2; y <= 2; ++y)
            [unroll] for (int x = -1; x <= 1; ++x)
                sum += ReadSource(contextSource, AtlasUvKnownSize(sourceSize, contextRect, uv + float2(x, y) * tap));
        color = sum / 15.0;
    } else {
        color = ReadSource(contextSource, AtlasUv(contextSource, contextRect, uv));
    }
    return color;
}

// Optional manual compensation, independent of seam mode. The calibrated radial
// mask lifts corners without changing the neutral center.
// This is brightness-only compensation, not recovery of clipped/lost details.
float3 CorrectFocusColor(float3 color, float2 focusUv) {
    [branch] if (FocusLift.x > 0.5) {
        const float2 q=focusUv*2.0-1.0;
        const float r2=saturate(dot(q,q)*0.5);
        float gain=FocusLift.y;
        // The calibrated interior has t=0: do not execute pow() there.
        // Uniform brightness remains effective inside the neutral mask.
        [branch] if (r2 > FocusLift.w && FocusLift.z*FocusProfile.y > 0.0) {
            const float t=saturate((r2-FocusLift.w)/max(1.0-FocusLift.w,0.1));
            gain *= 1.0+FocusLift.z*FocusProfile.y*pow(t,FocusProfile.x);
        }
        color=max(color*gain,0.0);
    }
    return color;
}

// Appearance changes affect only sampled peripheral colors. Estimate and apply
// in the same source-sample domain; preserve B28's final output encoding. This
// costs one multiply per channel, without per-output-pixel gamma conversions.
float3 SeamSideGain(uint baseIndex, uint side, float along, float3 fallback) {
    const float4 a = SeamMatch[baseIndex + 1u + side * 2u];
    const float4 b = SeamMatch[baseIndex + 2u + side * 2u];
    const float t = saturate(along * 2.0 - 0.5);
    return lerp(lerp(fallback, a.rgb, a.a), lerp(fallback, b.rgb, b.a), t);
}

float4 MatchContext(uint eye, float2 uv, float4 crop, float4 color) {
    [branch] if (Seam.x > 0.5) {
        float3 gain = 1.0;
        float confidence = 0.0;
        [branch] if (Seam.x > 1.5 && (Seam.y > 0.0 || SeamOptions.z > 0.5)) {
            const uint baseIndex = eye * 9u;
            const float4 match = SeamMatch[baseIndex];
            gain = lerp(1.0, match.rgb, match.a);
            confidence = match.a;
            const float2 outside = max(max(crop.xy - uv, uv - crop.zw), 0.0) * float2(EyeAndAtlas.xy);
            const float distanceSq = dot(outside, outside);
            // Reject distant pixels before evaluating the square root.
            [branch] if (SeamLocal.y > 0.0 && distanceSq < SeamLocal.x*SeamLocal.x) {
                const float2 along = saturate((uv - crop.xy) / (crop.zw - crop.xy));
                const float4 d = abs(float4(uv.y - crop.y, uv.x - crop.z, uv.y - crop.w, uv.x - crop.x)) *
                                 float4(EyeAndAtlas.y, EyeAndAtlas.x, EyeAndAtlas.y, EyeAndAtlas.x);
                const float4 weights = 1.0 / (1.0 + d * d);
                const float3 local = (SeamSideGain(baseIndex, 0u, along.x, gain) * weights.x +
                                      SeamSideGain(baseIndex, 1u, along.y, gain) * weights.y +
                                      SeamSideGain(baseIndex, 2u, along.x, gain) * weights.z +
                                      SeamSideGain(baseIndex, 3u, along.y, gain) * weights.w) / dot(weights, float4(1.0, 1.0, 1.0, 1.0));
                const float t = saturate(sqrt(distanceSq) / max(SeamLocal.x, 1.0));
                gain = lerp(gain, local, SeamLocal.y * (1.0 - t * t * (3.0 - 2.0 * t)));
            }
        }
        gain = lerp(1.0, gain * Seam.w, Seam.y);
        color.rgb = max(color.rgb * gain, 0.0);
        [branch] if (SeamOptions.z > 0.5)
            color.rgb = lerp(float3(0.7, 0.05, 0.05), float3(0.05, 0.7, 0.05), confidence);
    }
    return color;
}

float SeamFocusWeight(float2 uv, float4 crop) {
    // Off preserves the old feather exactly. Matching mode keeps the complete
    // rendered fovea sharp at transition=0. An optional transition reserves
    // existing edge pixels; it does not claim additional rendered coverage.
    if (Seam.x < 0.5) return FocusWeight(uv, crop);
    if (any(uv < crop.xy) || any(uv > crop.zw)) return 0.0;
    const float2 extentPx = (crop.zw - crop.xy) * float2(EyeAndAtlas.xy);
    const float width = min(SeamOptions.y, 0.49 * min(extentPx.x, extentPx.y));
    if (width <= 0.0) return 1.0;
    const float2 edgePx = min(uv - crop.xy, crop.zw - uv) * float2(EyeAndAtlas.xy);
    const float t = saturate(min(edgePx.x, edgePx.y) / width);
    return t * t * (3.0 - 2.0 * t);
}

float4 ScenePixel(VertexOut input) {
    const uint eye = min((uint)input.position.x / EyeAndAtlas.x, 1u);
    const float2 eyeUv = float2(input.position.x - eye * EyeAndAtlas.x,
                               input.position.y) / float2(EyeAndAtlas.xy);
    const uint4 contextRect = eye == 0 ? ContextLeft : ContextRight;
    const uint contextSource = eye == 0 ? ContextSource.x : ContextSource.y;
    const uint4 focusRect = eye == 0 ? FocusLeft : FocusRight;
    const float4 crop = eye == 0 ? CropUvLeft : CropUvRight;
    const uint debugMode = (uint)Options.y;
    const float weight = debugMode == 0u ? SeamFocusWeight(eyeUv, crop) : FocusWeight(eyeUv, crop);

    if (debugMode == 3) {
        const float3 contextColor = eye == 0 ? float3(0.8, 0.1, 0.1) : float3(0.1, 0.8, 0.1);
        const float3 focusColor = eye == 0 ? float3(0.1, 0.2, 1.0) : float3(1.0, 0.8, 0.1);
        return float4(lerp(contextColor, focusColor, weight), 1.0);
    }

    // The context sample is unnecessary under opaque focus. In the default
    // 50% crop this skips a texture fetch for most focused pixels, including
    // pixels using the fused Glamarye filter. Keep diagnostics exact.
    if (debugMode == 1)
        return ReadContext(eye, contextSource, contextRect, eyeUv);
    if (weight <= 0.0) {
        if (debugMode == 2) return float4(0.04, 0.04, 0.04, 1.0);
        return MatchContext(eye, eyeUv, crop, ReadContext(eye, contextSource, contextRect, eyeUv));
    }

    const float2 focusUv = (eyeUv - crop.xy) / (crop.zw - crop.xy);
    // Share the same source extent across center and all six sharpening taps.
    const float2 focusSourceSize = SourceSize(2u + eye);
    float4 focus = ReadSource(2u + eye, AtlasUvKnownSize(focusSourceSize, focusRect, focusUv));
    const float eyeStrength = eye == 0u ? SharpenEye.x : SharpenEye.y;
    const float eyeMaxChange = eye == 0u ? SharpenEye.z : SharpenEye.w;
    [branch] if (eyeStrength > 0.0) {
        const float2 tapScale = 1.0 / (float2(EyeAndAtlas.xy) * (crop.zw - crop.xy));
        focus.rgb = GlamSharpenFocus(2u + eye, focusRect, focusUv, tapScale, focus.rgb, eyeStrength, eyeMaxChange, focusSourceSize);
    }
    if (debugMode == 0u) focus.rgb = CorrectFocusColor(focus.rgb, focusUv);
    float4 output = focus;
    [branch] if (debugMode != 2 && weight < 1.0) {
        const float4 context = MatchContext(eye, eyeUv, crop, ReadContext(eye, contextSource, contextRect, eyeUv));
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

#ifdef SEAM_COMPUTE
RWStructuredBuffer<float4> SeamOutput : register(u0);
groupshared float4 SeamFocusSums[128];
groupshared float4 SeamContextSums[128];

// Four low-frequency patch samples, solely for analysis: displayed focus
// samples are never blurred. Use the actual same context homography/depth
// warp as composition and reject out-of-bounds/disocclusion-filled samples.
bool SeamPatch(uint eye, float2 center, float4 crop, out float3 focus, out float3 context) {
    focus = 0.0; context = 0.0;
    const uint4 cr = eye == 0u ? ContextLeft : ContextRight;
    const uint4 fr = eye == 0u ? FocusLeft : FocusRight;
    const uint cs = eye == 0u ? ContextSource.x : ContextSource.y;
    const float2 patch = 1.25 / max(float2(cr.zw), 1.0);
    float loF = 1.0e10, hiF = -1.0e10, loC = 1.0e10, hiC = -1.0e10;
    bool valid = true; // CSSeam exits uniformly before probes on invalid alignment.
    [unroll] for (uint i = 0u; i < 4u; ++i) {
        const float2 p = center + float2((i & 1u) == 0u ? -1.0 : 1.0, (i & 2u) == 0u ? -1.0 : 1.0) * patch;
        float fill = 0.0;
        const float2 cu = WarpContextUv(eye, ContextUv(eye, p), fill);
        valid = valid && all(p > crop.xy) && all(p < crop.zw) && all(cu >= 0.0) && all(cu <= 1.0) && fill == 0.0;
        const float2 focusUv = (p - crop.xy) / (crop.zw - crop.xy);
        const float3 f = CorrectFocusColor(ReadSource(2u + eye, AtlasUv(2u + eye, fr, focusUv)).rgb, focusUv);
        const float3 c = ReadSource(cs, AtlasUv(cs, cr, cu)).rgb;
        focus += f; context += c;
        const float lf = dot(f, GlamLuma), lc = dot(c, GlamLuma);
        loF = min(loF, lf); hiF = max(hiF, lf);
        loC = min(loC, lc); hiC = max(hiC, lc);
    }
    focus *= 0.25; context *= 0.25;
    const float lf = dot(focus, GlamLuma), lc = dot(context, GlamLuma);
    // Exclude black, clipped highlights and unstable/high-gradient boundaries.
    // Broad luminance outliers cannot be repaired by a bounded color gain.
    valid = valid && min(lf, lc) > 0.03 && max(lf, lc) < 0.95 &&
        max(hiF - loF, hiC - loC) < 0.25 && lf > 0.5 * lc && lf < 2.0 * lc;
    return valid;
}

[numthreads(128, 1, 1)]
// Groups contain eight independent 16-sample boundary segments. Reuse their
// reductions for a global estimate instead of sampling the image again.
void CSSeam(uint3 group : SV_GroupID, uint lane : SV_GroupIndex) {
    const uint eye = group.x;
    // Alignment usability is uniform across both dispatch groups. All lanes
    // return together, before any groupshared barrier or texture/depth probe.
    // Initialize every record, including after an earlier valid frame.
    [branch] if (SeamOptions.w <= 0.5) {
        if (lane < 9u) SeamOutput[eye * 9u + lane] = float4(1.0, 1.0, 1.0, 0.0);
        return;
    }
    const float4 crop = eye == 0u ? CropUvLeft : CropUvRight;
    const uint side = lane / 32u;
    const float along = (float(lane % 32u) + 0.5) / 32.0;
    // Inset far enough to fit a patch at the peripheral sampling footprint.
    const uint4 cr = eye == 0u ? ContextLeft : ContextRight;
    const float2 inset = min(2.5 / max(float2(cr.zw), 1.0) + 8.0 / float2(EyeAndAtlas.xy),
                             (crop.zw - crop.xy) * 0.3);
    float2 p = lerp(crop.xy + inset, crop.zw - inset, along);
    if (side == 0u) p.y = crop.y + inset.y;
    else if (side == 1u) p.x = crop.z - inset.x;
    else if (side == 2u) p.y = crop.w - inset.y;
    else p.x = crop.x + inset.x;
    float3 f, c;
    const bool valid = SeamPatch(eye, p, crop, f, c);
    SeamFocusSums[lane] = valid ? float4(f, 1.0) : 0.0;
    SeamContextSums[lane] = valid ? float4(c, 1.0) : 0.0;
    GroupMemoryBarrierWithGroupSync();
    [unroll] for (uint stride = 8u; stride > 0u; stride >>= 1u) {
        if ((lane % 16u) < stride) {
            SeamFocusSums[lane] += SeamFocusSums[lane + stride];
            SeamContextSums[lane] += SeamContextSums[lane + stride];
        }
        GroupMemoryBarrierWithGroupSync();
    }
    if ((lane % 16u) == 0u) {
        const float3 sf = SeamFocusSums[lane].rgb, sc = SeamContextSums[lane].rgb;
        const float count = SeamFocusSums[lane].a;
        const float lumGain = dot(sf, GlamLuma) / max(dot(sc, GlamLuma), 1.0e-5);
        const float3 rgbGain = float3(sc.r > count * 0.03 ? sf.r / max(sc.r, 1.0e-5) : lumGain,
                                     sc.g > count * 0.03 ? sf.g / max(sc.g, 1.0e-5) : lumGain,
                                     sc.b > count * 0.03 ? sf.b / max(sc.b, 1.0e-5) : lumGain);
        const float3 gain = clamp(lerp(lumGain.xxx, rgbGain, SeamOptions.x), 1.0 - Seam.z, 1.0 + Seam.z);
        SeamOutput[eye * 9u + 1u + lane / 16u] = float4(count > 4.0 ? gain : float3(1.0, 1.0, 1.0), saturate((count - 4.0) / 8.0));
    }
    GroupMemoryBarrierWithGroupSync();
    if (lane < 8u) {
        SeamFocusSums[lane] = SeamFocusSums[lane * 16u];
        SeamContextSums[lane] = SeamContextSums[lane * 16u];
    }
    GroupMemoryBarrierWithGroupSync();
    [unroll] for (uint reduceStride = 4u; reduceStride > 0u; reduceStride >>= 1u) {
        if (lane < reduceStride) {
            SeamFocusSums[lane] += SeamFocusSums[lane + reduceStride];
            SeamContextSums[lane] += SeamContextSums[lane + reduceStride];
        }
        GroupMemoryBarrierWithGroupSync();
    }
    if (lane == 0u) {
        const float3 sf = SeamFocusSums[0].rgb, sc = SeamContextSums[0].rgb;
        const float count = SeamFocusSums[0].a;
        const float lumGain = dot(sf, GlamLuma) / max(dot(sc, GlamLuma), 1.0e-5);
        const float3 rgbGain = float3(sc.r > count * 0.03 ? sf.r / max(sc.r, 1.0e-5) : lumGain,
                                     sc.g > count * 0.03 ? sf.g / max(sc.g, 1.0e-5) : lumGain,
                                     sc.b > count * 0.03 ? sf.b / max(sc.b, 1.0e-5) : lumGain);
        const float3 gain = clamp(lerp(lumGain.xxx, rgbGain, SeamOptions.x), 1.0 - Seam.z, 1.0 + Seam.z);
        const float confidence = saturate((count - 8.0) / 40.0);
        SeamOutput[eye * 9u] = float4(count > 8.0 ? gain : float3(1.0, 1.0, 1.0), confidence);
    }
}
#endif

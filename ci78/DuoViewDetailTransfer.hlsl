// CI78 detail transfer for the synthesized RIGHT fovea.
//
// Plain idea: the RIGHT eye keeps its own real (low-resolution) image for every
// shape, colour and silhouette, and borrows only the fine detail from the sharp
// LEFT crop:   result = RIGHT + confidence * (LEFT - LEFT blurred to RIGHT size).
//
// Why: the old path replaced each pixel either with warped LEFT colour or with
// the (about 5x blurrier) RIGHT colour, decided by yes/no tests on per-frame
// jittered DLSS depth. Thin geometry (grass, leaves, wires) flipped that choice
// every frame: CI75 measured ~18% holes in the synthetic RIGHT fovea and ~12% of
// its mask changing between neighbouring frames. That is the shimmer.
// Here depth only PROPOSES up to three places the detail could come from
// (nearest, middle and farthest surface around the pixel). The two stable,
// DLSS-resolved colour images DECIDE how much each proposal is trusted, with
// smooth weights. No per-pixel hard switch remains, and a wrong proposal can at
// worst misplace fine texture: it cannot paint a second copy of an object,
// because every low frequency comes from the real RIGHT camera.
//
// Two passes, both reached through the existing surface recorder when
// MeshConfig.w bit 64 is set (C++: DuoViewD3D12.hpp / DuoViewSurfaceD3D12.hpp):
//   PSLeftLowPass       LEFT crop box-averaged onto the RIGHT pixel grid, written
//                       into the periphery map (t5) before pass 0. This is the
//                       same blur the low-resolution RIGHT image has (box per
//                       texel, then bilinear), so the comparison is fair.
//   PSDetailTransferSurface  pass 0 output; alpha = detail confidence (mode 6
//                       shows it), any alpha > 0 means "valid, use this colour".
// Pass 1 (LEFT periphery) overwrites t5 afterwards exactly as before.

static const float3 kDTLuma = float3(0.2126f, 0.7152f, 0.0722f);

struct DTCandidate {
    float weight;
    float3 detail;
    float2 local;
};

float2 DTCropSize() {
    return max(CropUv.zw - CropUv.xy, float2(1.e-4f, 1.e-4f));
}
float2 DTRightTexel() {
    return 1.f / max(float2(PeripheralRect.zw), float2(1.f, 1.f));
}
float3 DTLeftRaw(float2 local) {
    // LEFT crop-local UV, plain bilinear, no sharpening.
    return SourceAtlas.SampleLevel(LinearClamp,
        NativeSampleUV(local, FoveaRect.zw, NativeFoveaDimensions), 0).rgb;
}
float3 DTLeftLow(float2 fullUV) {
    // LEFT blurred to RIGHT resolution, indexed by full-field UV.
    return SyntheticLeftPeriphery.SampleLevel(LinearClamp, fullUV, 0).rgb;
}
float3 DTRight(float2 uv) {
    return RightNative(uv).rgb;
}
float3 DTPerceptual(float3 c) {
    return sqrt(max(c, float3(0.f, 0.f, 0.f)));
}

// Prepass: one output texel = average of the LEFT crop over that texel's area
// (5x5 bilinear taps, enough for LEFT/RIGHT density ratios up to about 7).
float4 PSLeftLowPass(VertexOut i) : SV_TARGET0 {
    const float2 cropSize = DTCropSize();
    const float2 local = (i.uv - CropUv.xy) / cropSize;
    const float2 texelLocal = DTRightTexel() / cropSize;
    if (any(local < -2.f * texelLocal) || any(local > 1.f + 2.f * texelLocal))
        return float4(0.f, 0.f, 0.f, 0.f);
    float3 sum = float3(0.f, 0.f, 0.f);
    [unroll] for (int y = 0; y < 5; ++y) {
        [unroll] for (int x = 0; x < 5; ++x)
            sum += DTLeftRaw(local + (float2(x, y) - 2.f) * .2f * texelLocal);
    }
    return float4(sum * (1.f / 25.f), 1.f);
}

// RIGHT forward Z for clustering. Valid far-plane/sky samples become very far
// (they are still a real proposal); out-of-range samples are invalid (-1).
float DTRightZ(float raw) {
    const float span = DepthViewportRanges.w - DepthViewportRanges.z;
    if (abs(span) < 1.e-7f) return -1.f;
    const float nd = (raw - DepthViewportRanges.z) / span;
    if (!isfinite(nd) || nd < 0.f || nd > 1.f) return -1.f;
    const float z = RightEyeForwardZ(raw);
    return z > 0.f ? z : 1.e8f;
}
float DTTolerance(float z) {
    return MeshEdge.x + MeshEdge.y * min(z, 1.e6f);
}

// One proposal: the RIGHT pixel targetUV lies on a surface with this raw depth.
// Map it into the LEFT crop and score how well the LEFT neighbourhood there,
// blurred to RIGHT resolution, has the same structure as the real RIGHT image.
DTCandidate DTEvaluate(float2 targetUV, float raw, float2 tR,
                       float3 r0, float3 r1, float3 r2, float3 r3, float3 r4,
                       float3 rMean, float sigma) {
    DTCandidate c;
    c.weight = 0.f; c.detail = float3(0.f, 0.f, 0.f); c.local = float2(0.f, 0.f);
    const float span = DepthViewportRanges.w - DepthViewportRanges.z;
    if (abs(span) < 1.e-7f) return c;
    const float nd = (raw - DepthViewportRanges.z) / span;
    if (!isfinite(nd) || nd < 0.f || nd > 1.f) return c;
    // Stay homogeneous: a sky point at infinity still maps correctly.
    float4 eye = mul(TargetEyeFromClip, float4(2.f * targetUV.x - 1.f, 1.f - 2.f * targetUV.y, nd, 1.f));
    if (!all(isfinite(eye))) return c;
    if (eye.w < 0.f) eye = -eye;
    float4 proj = mul(SourceClipFromTargetEye, eye);
    if (!all(isfinite(proj))) return c;
    if (proj.w <= 0.f && abs(eye.w) <= 1.e-6f * max(length(eye.xyz), 1.e-20f)) proj = -proj;
    if (proj.w <= 1.e-7f) return c;
    const float2 local = float2(.5f + .5f * proj.x / proj.w, .5f - .5f * proj.y / proj.w);
    // Keep one RIGHT texel away from the LEFT crop border (the blur reads there)
    // and fade in over the next texel, so the crop edge never pops.
    const float2 cropSize = DTCropSize();
    const float2 margin = max(tR / cropSize, float2(1.e-6f, 1.e-6f));
    const float2 inside = min(local - margin, (1.f - margin) - local);
    if (inside.x < 0.f || inside.y < 0.f) return c;
    const float edgeFade = saturate(min(inside.x / margin.x, inside.y / margin.y));

    const float2 full = CropUv.xy + local * cropSize;
    const float3 lp = DTLeftLow(full);
    const float3 l0 = DTPerceptual(lp);
    const float3 l1 = DTPerceptual(DTLeftLow(full + float2(tR.x, 0.f)));
    const float3 l2 = DTPerceptual(DTLeftLow(full - float2(tR.x, 0.f)));
    const float3 l3 = DTPerceptual(DTLeftLow(full + float2(0.f, tR.y)));
    const float3 l4 = DTPerceptual(DTLeftLow(full - float2(0.f, tR.y)));
    const float3 lMean = (l0 + l1 + l2 + l3 + l4) * .2f;
    // Structure (zero-mean) difference, so a small exposure or shading offset
    // between the two cameras does not reject correct detail.
    float err = dot(abs((l0 - lMean) - (r0 - rMean)), kDTLuma);
    err += dot(abs((l1 - lMean) - (r1 - rMean)), kDTLuma);
    err += dot(abs((l2 - lMean) - (r2 - rMean)), kDTLuma);
    err += dot(abs((l3 - lMean) - (r3 - rMean)), kDTLuma);
    err += dot(abs((l4 - lMean) - (r4 - rMean)), kDTLuma);
    err = err * .2f + .25f * dot(abs(lMean - rMean), kDTLuma);
    const float e = err / sigma;
    c.weight = exp(-e * e) * edgeFade;
    c.detail = DTLeftRaw(local) - lp;
    c.local = local;
    return c;
}

BackwardSurfaceOutput PSDetailTransferSurface(VertexOut i) {
    BackwardSurfaceOutput o = (BackwardSurfaceOutput)0;
    o.depth = (MeshConfig.w & 4u) != 0u ? 0.f : 1.f; // nothing is drawn after this pass
    const float2 targetUV = CropUv.xy + i.uv * (CropUv.zw - CropUv.xy);
    const float3 base = DTRight(targetUV);
    o.color = float4(base, 1.f / 255.f); // valid output, zero detail confidence
    if (any(targetUV < 0.f) || any(targetUV > 1.f)) return o;
    const float2 tR = DTRightTexel();

    // Real RIGHT image around the pixel, one RIGHT texel apart.
    const float3 r0 = DTPerceptual(base);
    const float3 r1 = DTPerceptual(DTRight(targetUV + float2(tR.x, 0.f)));
    const float3 r2 = DTPerceptual(DTRight(targetUV - float2(tR.x, 0.f)));
    const float3 r3 = DTPerceptual(DTRight(targetUV + float2(0.f, tR.y)));
    const float3 r4 = DTPerceptual(DTRight(targetUV - float2(0.f, tR.y)));
    const float3 rMean = (r0 + r1 + r2 + r3 + r4) * .2f;
    float activity = dot(abs(r0 - rMean), kDTLuma) + dot(abs(r1 - rMean), kDTLuma) +
                     dot(abs(r2 - rMean), kDTLuma) + dot(abs(r3 - rMean), kDTLuma) +
                     dot(abs(r4 - rMean), kDTLuma);
    activity *= .2f;
    const float sigma = .025f + .25f * activity;

    // Depth proposals from the RIGHT depth guide (stabilized when CI77 is ON).
    const float2 coord = RightDepthRect.xy + (targetUV + MeshJitter.zw) * RightDepthRect.zw - .5f;
    const int2 lo = ActiveDepthMin(RightDepthRect), hi = ActiveDepthMax(RightDepthRect);
    const int2 origin = int2(floor(coord));
    const float2 f = frac(coord);
    const float raw00 = RightSourceDepth.Load(int3(clamp(origin, lo, hi), 0));
    const float raw10 = RightSourceDepth.Load(int3(clamp(origin + int2(1, 0), lo, hi), 0));
    const float raw01 = RightSourceDepth.Load(int3(clamp(origin + int2(0, 1), lo, hi), 0));
    const float raw11 = RightSourceDepth.Load(int3(clamp(origin + int2(1, 1), lo, hi), 0));
    const float z00 = DTRightZ(raw00), z10 = DTRightZ(raw10), z01 = DTRightZ(raw01), z11 = DTRightZ(raw11);
    const float w00 = (1.f - f.x) * (1.f - f.y), w10 = f.x * (1.f - f.y);
    const float w01 = (1.f - f.x) * f.y, w11 = f.x * f.y;
    // Middle proposal: smooth bilinear depth on a continuous surface (device
    // depth is linear in disparity), otherwise the dominant nearest sample.
    float rawMid = raw00, zMid = z00, wBest = z00 > 0.f ? w00 : -1.f;
    if (z10 > 0.f && w10 > wBest) { rawMid = raw10; zMid = z10; wBest = w10; }
    if (z01 > 0.f && w01 > wBest) { rawMid = raw01; zMid = z01; wBest = w01; }
    if (z11 > 0.f && w11 > wBest) { rawMid = raw11; zMid = z11; wBest = w11; }
    if (wBest < 0.f) return o; // no usable depth: real RIGHT image only
    const float zLo2 = min(min(z00 > 0.f ? z00 : 1.e30f, z10 > 0.f ? z10 : 1.e30f),
                           min(z01 > 0.f ? z01 : 1.e30f, z11 > 0.f ? z11 : 1.e30f));
    const float zHi2 = max(max(z00, z10), max(z01, z11));
    if (z00 > 0.f && z10 > 0.f && z01 > 0.f && z11 > 0.f && zHi2 - zLo2 <= DTTolerance(zLo2)) {
        const float rawSmooth = raw00 * w00 + raw10 * w10 + raw01 * w01 + raw11 * w11;
        const float zSmooth = DTRightZ(rawSmooth);
        if (zSmooth > 0.f) { rawMid = rawSmooth; zMid = zSmooth; }
    }
    // Nearest and farthest surfaces within one RIGHT depth texel around the pixel.
    const int2 centre = int2(floor(coord + .5f));
    float zNear = 1.e30f, zFar = -1.f, rawNear = rawMid, rawFar = rawMid;
    [unroll] for (int y = -1; y <= 1; ++y) {
        [unroll] for (int x = -1; x <= 1; ++x) {
            const float raw = RightSourceDepth.Load(int3(clamp(centre + int2(x, y), lo, hi), 0));
            const float z = DTRightZ(raw);
            if (z > 0.f) {
                if (z < zNear) { zNear = z; rawNear = raw; }
                if (z > zFar) { zFar = z; rawFar = raw; }
            }
        }
    }

    DTCandidate c0 = DTEvaluate(targetUV, rawMid, tR, r0, r1, r2, r3, r4, rMean, sigma);
    DTCandidate c1 = c0; c1.weight = 0.f;
    DTCandidate c2 = c0; c2.weight = 0.f;
    [branch] if (zFar > 0.f && zFar - zNear > DTTolerance(zNear)) {
        if (abs(zMid - zNear) > DTTolerance(zNear))
            c1 = DTEvaluate(targetUV, rawNear, tR, r0, r1, r2, r3, r4, rMean, sigma);
        if (abs(zFar - zMid) > DTTolerance(zMid))
            c2 = DTEvaluate(targetUV, rawFar, tR, r0, r1, r2, r3, r4, rMean, sigma);
    }

    const float sum = c0.weight + c1.weight + c2.weight;
    // A well-matching proposal (weight ~0.8+) gets the full detail; weak
    // matches fade out smoothly instead of being cut at a threshold.
    const float confidence = saturate(1.25f * max(c0.weight, max(c1.weight, c2.weight)) - .05f);
    if (sum <= 1.e-4f || confidence <= 0.f) return o;
    const float3 detail = (c0.weight * c0.detail + c1.weight * c1.detail + c2.weight * c2.detail) / sum;
    float3 result = base + confidence * detail;

    // Match the LEFT eye's optional sharpening, taken from the best proposal.
    if (SharpenStrength > 0.f && DebugViewMode == 0u) {
        float2 bestLocal = c0.local; float bestWeight = c0.weight;
        if (c1.weight > bestWeight) { bestLocal = c1.local; bestWeight = c1.weight; }
        if (c2.weight > bestWeight) { bestLocal = c2.local; bestWeight = c2.weight; }
        const float3 plain = DTLeftRaw(bestLocal);
        const float2 leftFull = CropUv.xy + bestLocal * (CropUv.zw - CropUv.xy);
        result += confidence * (bestWeight / sum) * (GlamSharpenNativeFovea(leftFull, plain) - plain);
    }
    o.color = float4(max(result, float3(0.f, 0.f, 0.f)), max(confidence, 1.f / 255.f));
    return o;
}

// CI79 RIGHT fovea: LEFT camera colour, shading and detail, chosen smoothly.
//
// History: CI78 kept the real RIGHT image as the base and borrowed only LEFT
// detail. In the headset (31 Oct) that was clearly steadier than CI77, but the
// RIGHT camera's colours and shading are visibly different from the LEFT
// camera's (it renders the whole view at ~0.2 scale), so the two eyes disagreed
// and caused rivalry. CI79 keeps CI78's steadiness but shows the LEFT camera's
// picture wherever the LEFT camera saw the same thing.
//
//   result = lerp(RIGHT colour-matched to LEFT, LEFT colour, confidence)
//
// Depth only PROPOSES up to three places the LEFT colour could come from
// (middle, nearest and farthest surface around the pixel). The two stable,
// DLSS-finished colour images DECIDE how much each proposal is trusted, with
// smooth weights over a 3x3 RIGHT-texel neighbourhood (more samples than CI78,
// so the decision moves less from frame to frame). No per-pixel yes/no switch.
// Where the LEFT camera saw nothing (thin strips behind edges) the RIGHT image
// fills in, colour-matched to the LEFT image so it does not stand out.
//
// Passes, reached through the existing surface recorder when MeshConfig.w bit
// 128 is set (C++: DuoViewD3D12.hpp / DuoViewSurfaceD3D12.hpp):
//   PSLeftLowPass   LEFT crop box-averaged onto the RIGHT pixel grid, written
//                   into the periphery map (t5) before pass 0. This is the same
//                   blur the low-resolution RIGHT image has, so comparing the two
//                   is fair. Pass 1 (LEFT periphery) overwrites t5 afterwards.
//   PSDetailTransferSurface  pass 0 output. Alpha = confidence (stereo mode 6
//                   shows it in green); any alpha > 0 means "valid colour".

static const float3 kDTLuma = float3(0.2126f, 0.7152f, 0.0722f);
static const float2 kDTGrid[9] = {
    float2(-1.f, -1.f), float2(0.f, -1.f), float2(1.f, -1.f),
    float2(-1.f,  0.f), float2(0.f,  0.f), float2(1.f,  0.f),
    float2(-1.f,  1.f), float2(0.f,  1.f), float2(1.f,  1.f) };

struct DTCandidate {
    float weight;
    float3 color;   // LEFT colour at full resolution
    float2 local;   // LEFT crop-local UV
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

// Where would the RIGHT pixel targetUV be in the LEFT crop if it lay on a
// surface with this raw RIGHT depth? Uses the real camera matrices.
bool DTProject(float2 targetUV, float raw, float2 tR, out float2 local, out float edgeFade) {
    local = float2(0.f, 0.f); edgeFade = 0.f;
    const float span = DepthViewportRanges.w - DepthViewportRanges.z;
    if (abs(span) < 1.e-7f) return false;
    const float nd = (raw - DepthViewportRanges.z) / span;
    if (!isfinite(nd) || nd < 0.f || nd > 1.f) return false;
    // Stay homogeneous: a sky point at infinity still maps correctly.
    float4 eye = mul(TargetEyeFromClip, float4(2.f * targetUV.x - 1.f, 1.f - 2.f * targetUV.y, nd, 1.f));
    if (!all(isfinite(eye))) return false;
    if (eye.w < 0.f) eye = -eye;
    float4 proj = mul(SourceClipFromTargetEye, eye);
    if (!all(isfinite(proj))) return false;
    if (proj.w <= 0.f && abs(eye.w) <= 1.e-6f * max(length(eye.xyz), 1.e-20f)) proj = -proj;
    if (proj.w <= 1.e-7f) return false;
    local = float2(.5f + .5f * proj.x / proj.w, .5f - .5f * proj.y / proj.w);
    // Keep one RIGHT texel away from the LEFT crop border (the comparison reads
    // there) and fade in over the next texel, so the crop edge never pops.
    const float2 margin = max(tR / DTCropSize(), float2(1.e-6f, 1.e-6f));
    const float2 inside = min(local - margin, (1.f - margin) - local);
    if (inside.x < 0.f || inside.y < 0.f) return false;
    edgeFade = saturate(min(inside.x / margin.x, inside.y / margin.y));
    return true;
}

// Score one proposal: does the LEFT neighbourhood there, blurred to RIGHT
// resolution, look like the colour-matched RIGHT neighbourhood (3x3 texels)?
DTCandidate DTEvaluate(float2 targetUV, float raw, float2 tR, float3 rp[9], float3 rMean, float sigma) {
    DTCandidate c;
    c.weight = 0.f; c.color = float3(0.f, 0.f, 0.f); c.local = float2(0.f, 0.f);
    float2 local; float edgeFade;
    if (!DTProject(targetUV, raw, tR, local, edgeFade)) return c;
    const float2 full = CropUv.xy + local * DTCropSize();
    float3 lp[9];
    float3 lMean = float3(0.f, 0.f, 0.f);
    [unroll] for (int k = 0; k < 9; ++k) {
        lp[k] = DTPerceptual(DTLeftLow(full + kDTGrid[k] * tR));
        lMean += lp[k];
    }
    lMean *= (1.f / 9.f);
    float err = 0.f;
    [unroll] for (int n = 0; n < 9; ++n)
        err += dot(abs((lp[n] - lMean) - (rp[n] - rMean)), kDTLuma);
    // Structure first; the absolute term (after colour matching) rejects a
    // flat surface of a different colour that happens to have no structure.
    err = err * (1.f / 9.f) + .5f * dot(abs(lMean - rMean), kDTLuma);
    const float e = err / sigma;
    c.weight = exp(-e * e) * edgeFade;
    c.color = DTLeftRaw(local);
    c.local = local;
    return c;
}

BackwardSurfaceOutput PSDetailTransferSurface(VertexOut i) {
    BackwardSurfaceOutput o = (BackwardSurfaceOutput)0;
    o.depth = (MeshConfig.w & 4u) != 0u ? 0.f : 1.f; // nothing is drawn after this pass
    const float2 targetUV = CropUv.xy + i.uv * (CropUv.zw - CropUv.xy);
    const float3 rightColour = DTRight(targetUV);
    o.color = float4(rightColour, 1.f / 255.f); // valid output, zero confidence
    if (any(targetUV < 0.f) || any(targetUV > 1.f)) return o;
    const float2 tR = DTRightTexel();

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

    // Colour match RIGHT -> LEFT appearance from a wide window (+-3 RIGHT
    // texels) around the middle proposal. When the proposal is right, both
    // windows show the same content, so the ratio is the shading difference.
    float3 gain = float3(1.f, 1.f, 1.f);
    float2 midLocal; float midFade;
    if (DTProject(targetUV, rawMid, tR, midLocal, midFade)) {
        const float2 midFull = CropUv.xy + midLocal * DTCropSize();
        float3 sumL = float3(0.f, 0.f, 0.f), sumR = float3(0.f, 0.f, 0.f);
        [unroll] for (int k = 0; k < 9; ++k) {
            const float2 o3 = 3.f * kDTGrid[k] * tR;
            sumL += DTLeftLow(clamp(midFull + o3, CropUv.xy + tR, CropUv.zw - tR));
            sumR += DTRight(targetUV + o3);
        }
        gain = clamp((sumL + .18f) / (sumR + .18f), float3(.5f, .5f, .5f), float3(2.f, 2.f, 2.f));
    }
    const float3 base = rightColour * gain;

    // Colour-matched RIGHT image around the pixel, 3x3 RIGHT texels.
    float3 rp[9];
    float3 rMean = float3(0.f, 0.f, 0.f);
    [unroll] for (int k2 = 0; k2 < 9; ++k2) {
        rp[k2] = DTPerceptual(DTRight(targetUV + kDTGrid[k2] * tR) * gain);
        rMean += rp[k2];
    }
    rMean *= (1.f / 9.f);
    float activity = 0.f;
    [unroll] for (int k3 = 0; k3 < 9; ++k3) activity += dot(abs(rp[k3] - rMean), kDTLuma);
    activity *= (1.f / 9.f);
    const float sigma = .035f + .3f * activity;

    DTCandidate c0 = DTEvaluate(targetUV, rawMid, tR, rp, rMean, sigma);
    DTCandidate c1 = c0; c1.weight = 0.f;
    DTCandidate c2 = c0; c2.weight = 0.f;
    [branch] if (zFar > 0.f && zFar - zNear > DTTolerance(zNear)) {
        if (abs(zMid - zNear) > DTTolerance(zNear))
            c1 = DTEvaluate(targetUV, rawNear, tR, rp, rMean, sigma);
        if (abs(zFar - zMid) > DTTolerance(zMid))
            c2 = DTEvaluate(targetUV, rawFar, tR, rp, rMean, sigma);
    }

    const float sum = c0.weight + c1.weight + c2.weight;
    // Favour the LEFT picture: a proposal matching reasonably well (weight
    // ~0.7) already gives full LEFT colour; weak matches fade out smoothly.
    const float confidence = saturate(1.5f * max(c0.weight, max(c1.weight, c2.weight)) - .05f);
    if (sum <= 1.e-4f || confidence <= 0.f) {
        o.color = float4(max(base, float3(0.f, 0.f, 0.f)), 1.f / 255.f);
        return o;
    }
    const float3 leftColour = (c0.weight * c0.color + c1.weight * c1.color + c2.weight * c2.color) / sum;
    float3 result = lerp(base, leftColour, confidence);

    // Match the LEFT eye's optional sharpening, taken from the best proposal.
    if (SharpenStrength > 0.f && DebugViewMode == 0u) {
        float2 bestLocal = c0.local; float bestWeight = c0.weight;
        if (c1.weight > bestWeight) { bestLocal = c1.local; bestWeight = c1.weight; }
        if (c2.weight > bestWeight) { bestLocal = c2.local; bestWeight = c2.weight; }
        const float3 plain = DTLeftRaw(bestLocal);
        const float2 leftFull = CropUv.xy + bestLocal * DTCropSize();
        result += confidence * (bestWeight / sum) * (GlamSharpenNativeFovea(leftFull, plain) - plain);
    }
    o.color = float4(max(result, float3(0.f, 0.f, 0.f)), max(confidence, 1.f / 255.f));
    return o;
}

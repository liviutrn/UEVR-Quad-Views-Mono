// Goal D Fill=4 (Study 93 winner #6 Tight B+C2+3):
//   - CSGoalDPPInit / CSGoalDPPDown / CSGoalDPPPull: 7-mip background-only push-pull pyramid
//     (R16G16B16A16_FLOAT, zero typed UAV loads, zero extra root signature DWORDs).
//   - GDHybridFoveaColor (PSNativeMain, m4g_raster): two-row bilateral Y anti-aliasing on
//     vertical depth cliffs + slope/ratio/far-side 3D self-occlusion guard + shear-free
//     horizontal & zero-shift vertical multi-tap + push-pull fallback (Mip 0=pp_rgb & .a mask,
//     Mip 2=lp_bg, Mip 3=macro_bg).
// Note: kept flat (no nested preprocessor blocks) so strip_goald() preserves exact Off-path identity.
Texture2D<float4> GDPPFine  : register(t9);
Texture2D<float4> GDPP      : register(t10);
RWTexture2D<float4> GDPPOut : register(u6);

[numthreads(16,16,1)]
void CSGoalDPPInit(uint3 id : SV_DispatchThreadID) {
    uint outW, outH;
    GDPPOut.GetDimensions(outW, outH);
    if (id.x >= outW || id.y >= outH) return;
    const float2 local = (float2(id.xy) + 0.5) / float2(outW, outH);
    const float2 foveaUv = NativeSampleUV(local, FoveaRect.zw, NativeFoveaDimensions);
    const float3 rgb = SourceAtlas.SampleLevel(LinearClamp, foveaUv, 0.0).rgb;

    // Sample tight raw knee'd depth (M4FoveaSoft slice 2) at center + 4 cardinal 1-texel neighbors.
    const float2 gridF = float2(max(M4Grid.xy, uint2(1u, 1u)));
    const float2 invAlloc = 1.0 / float2(max(M4Grid.zw, uint2(1u, 1u)));
    const float2 fCell = clamp(local * gridF, float2(0.5, 0.5), gridF - 0.5);
    const float2 cUv = fCell * invAlloc;
    const float2 loUv = float2(0.5, 0.5) * invAlloc;
    const float2 hiUv = (gridF - 0.5) * invAlloc;
    const float dC = M4FoveaSoft.SampleLevel(LinearClamp, float3(cUv, 2.0), 0.0);
    const float dL = M4FoveaSoft.SampleLevel(LinearClamp, float3(clamp(cUv - float2(invAlloc.x, 0.0), loUv, hiUv), 2.0), 0.0);
    const float dR = M4FoveaSoft.SampleLevel(LinearClamp, float3(clamp(cUv + float2(invAlloc.x, 0.0), loUv, hiUv), 2.0), 0.0);
    const float dU = M4FoveaSoft.SampleLevel(LinearClamp, float3(clamp(cUv - float2(0.0, invAlloc.y), loUv, hiUv), 2.0), 0.0);
    const float dD = M4FoveaSoft.SampleLevel(LinearClamp, float3(clamp(cUv + float2(0.0, invAlloc.y), loUv, hiUv), 2.0), 0.0);
    const float dMax1 = max(dC, max(max(dL, dR), max(dU, dD)));

    const float bgMaskWU  = max(asfloat(M7ColorExtent.x), 1.e-4);
    const float midMaskWU = max(asfloat(M7ColorExtent.y), bgMaskWU);
    const bool fgClose = dMax1 > (1.0 / bgMaskWU); // tight 1-texel dilation on close (<1.5 m) weapon/hands
    const bool fgMid   = dC > (1.0 / midMaskWU);   // 0-texel dilation on mid (1.5..3.5 m) wires/branches
    const float w = (fgClose || fgMid) ? 0.0 : 1.0;
    GDPPOut[id.xy] = float4(rgb * w, w);
}

[numthreads(16,16,1)]
void CSGoalDPPDown(uint3 id : SV_DispatchThreadID) {
    uint dstW, dstH, srcW, srcH;
    GDPPOut.GetDimensions(dstW, dstH);
    GDPP.GetDimensions(srcW, srcH);
    if (id.x >= dstW || id.y >= dstH) return;
    const int2 p = int2(id.xy) * 2;
    const int2 hi = max(int2(srcW, srcH) - 1, int2(0, 0));
    float4 sum = GDPP.Load(int3(clamp(p + int2(0, 0), int2(0, 0), hi), 0));
    sum += GDPP.Load(int3(clamp(p + int2(1, 0), int2(0, 0), hi), 0));
    sum += GDPP.Load(int3(clamp(p + int2(0, 1), int2(0, 0), hi), 0));
    sum += GDPP.Load(int3(clamp(p + int2(1, 1), int2(0, 0), hi), 0));
    GDPPOut[id.xy] = 0.25 * sum;
}

[numthreads(16,16,1)]
void CSGoalDPPPull(uint3 id : SV_DispatchThreadID) {
    uint dstW, dstH, coarseW, coarseH;
    GDPPOut.GetDimensions(dstW, dstH);
    GDPP.GetDimensions(coarseW, coarseH);
    if (id.x >= dstW || id.y >= dstH) return;
    const float4 fine = GDPPFine.Load(int3(id.xy, 0));
    const float a = saturate(fine.a);
    const float3 fineRgb = a > 1.e-5 ? (fine.rgb / a) : float3(0.0, 0.0, 0.0);
    // Top coarsest mip binds pp_down[top] to both t9 and t10 -> coarse dims == dst dims.
    [branch] if (coarseW == dstW && coarseH == dstH) {
        GDPPOut[id.xy] = float4(fineRgb, a);
        return;
    }
    const float2 uv = (float2(id.xy) + 0.5) / float2(dstW, dstH);
    const float3 up = GDPP.SampleLevel(LinearClamp, uv, 0.0).rgb;
    const float3 outRgb = fineRgb * a + up * (1.0 - a);
    GDPPOut[id.xy] = float4(outRgb, a);
}

static const float GD_HYB_DY[6]   = { -0.0444, 0.0444, -0.0889, 0.0889, -0.1389, 0.1389 };
static const float GD_HYB_BIAS[6] = {  1.00,   1.00,    0.94,   0.94,    0.86,   0.86   };

float2 GDHybridBaseUv(float2 eyeUv, uint eye) {
    const uint row = 3u * eye;
    const float3 p = float3(eyeUv, 1.0);
    const float w = dot(M1Homography[row + 2u].xyz, p);
    return float2(dot(M1Homography[row].xyz, p), dot(M1Homography[row + 1u].xyz, p)) / w;
}

float3 GDHybridSampleFovea(float u, float v, float cropW, float cropH) {
    const float2 local = float2((u - M2Crop.x) / cropW, (v - M2Crop.y) / cropH);
    return SourceAtlas.SampleLevel(LinearClamp, NativeSampleUV(local, FoveaRect.zw, NativeFoveaDimensions), 0.0).rgb;
}

bool GDHybridSampleTap(float uTap, float vTap, float dBg, float invWu, float cropW, float cropH,
                       out float3 tRgb, out float3 tMac, out float3 tLp) {
    tRgb = float3(0.0, 0.0, 0.0);
    tMac = float3(0.0, 0.0, 0.0);
    tLp  = float3(0.0, 0.0, 0.0);
    const float2 localTap = float2((uTap - M2Crop.x) / cropW, (vTap - M2Crop.y) / cropH);
    if (any(localTap <= 0.003) || any(localTap >= 0.997)) return false;
    const uint yTap = uint(clamp(floor(localTap.y * float(M4Grid.y)), 0.0, float(max(M4Grid.y, 1u) - 1u)));
    const float dTap = GDReadFineRow(uTap, yTap, 2u);
    const bool depthOk = (dTap <= max(dBg * 1.12, dBg + 0.015 * invWu)) &&
                         (dTap >= min(dBg * 0.82, dBg - 0.015 * invWu));
    [branch] if (!depthOk) return false;
    const float bgValid = GDPP.SampleLevel(LinearClamp, localTap, 0.0).a;
    [branch] if (bgValid < 0.95) return false;
    tRgb = SourceAtlas.SampleLevel(LinearClamp, NativeSampleUV(localTap, FoveaRect.zw, NativeFoveaDimensions), 0.0).rgb;
    tMac = GDPP.SampleLevel(LinearClamp, localTap, 3.0).rgb;
    tLp  = GDPP.SampleLevel(LinearClamp, localTap, 2.0).rgb;
    return true;
}

float GDPow6(float a) {
    const float a2 = a * a;
    return a2 * a2 * a2;
}

float3 GDHybridEvalRow(float2 base, float u1s, uint yRow, uint eye, float hbBlend, float3 baseRgb,
                       float cropW, float cropH) {
    const float k = M1Eye[eye];
    const float s = (k < 0.0) ? 1.0 : -1.0; // +1 left eye, -1 right eye (bg -> fg direction)
    const float du = cropW / float(max(M4Grid.x, 1u));
    const float dMid = GDReadFineRow(u1s, yRow, eye);
    const float dM   = GDReadFineRow(u1s - 0.5 * s * du, yRow, eye);
    const float dP   = GDReadFineRow(u1s + 0.5 * s * du, yRow, eye);
    const float stretch = 1.0 + abs(k) * max(dP - dM, 0.0) / max(du, 1.e-7);
    [branch] if (stretch <= 2.0) return baseRgb;

    const float wu = max(asfloat(M7ColorExtent.z), 1.0);
    const float invWu = 1.0 / wu;
    const float bgMaskWU = max(asfloat(M7ColorExtent.x), 1.e-4);
    const float hbNear = asfloat(M6PreviousRect.z);
    const float hbFar  = max(asfloat(M6PreviousRect.w), hbNear * 1.0001 + 1.e-3);

    const float dBg = min(GDReadFineRow(u1s - 1.25 * s * du, yRow, eye),
                          GDReadFineRow(u1s - 2.25 * s * du, yRow, eye));
    const float dFg = max(GDReadFineRow(u1s + 1.25 * s * du, yRow, eye),
                          GDReadFineRow(u1s + 2.25 * s * du, yRow, eye));
    const float jump  = dFg - dBg;
    const float ratio = dFg / max(dBg, 1.e-7);
    const float distW = 1.0 - smoothstep(hbNear, hbFar, 1.0 / max(dFg, 1.e-9));
    const float tRaw  = (dMid - dBg) / max(jump, 1.e-7);
    const float wGap  = hbBlend * distW
                      * smoothstep(2.0, 3.2, stretch)
                      * smoothstep(0.06 * invWu, 0.12 * invWu, jump)
                      * smoothstep(1.45, 1.85, ratio)
                      * (1.0 - smoothstep(1.0 / (bgMaskWU * 1.07), 1.0 / (bgMaskWU * 0.80), dBg))
                      * smoothstep(0.0, 0.03, tRaw)
                      * (1.0 - smoothstep(0.95, 0.995, tRaw));
    [branch] if (wGap <= 0.005) return baseRgb;

    const float uBg = clamp(base.x + k * dBg, M2Crop.x, M2Crop.z);
    const float2 localBg = saturate(float2((uBg - M2Crop.x) / cropW, (base.y - M2Crop.y) / cropH));
    const float3 cRgb = GDPP.SampleLevel(LinearClamp, localBg, 0.0).rgb;
    const float detailStr = saturate(M7Controls.x);
    const uint tapMode = M7ColorExtent.w; // 0=#6 Hybrid, 1=#5 Vert-First, 2=#4 Left-Only, 3=Cand C blur
    [branch] if (tapMode >= 3u || detailStr <= 0.001) return lerp(baseRgb, cRgb, wGap);

    const float inRamp = smoothstep(0.01, 0.10, saturate(tRaw));
    const float gateHi = clamp(M7Controls.y, 0.04, 0.30);
    const float gateLo = gateHi * 0.2727;
    const float shiftScale = clamp(M7Controls.w, 0.50, 1.50);

    // Shear-free constant horizontal clone tap (eye-symmetric, 0 deg taper shear).
    const float shiftFrac = (dFg > 1.0 / bgMaskWU) ? (0.10625 * shiftScale) : (0.021875 * shiftScale);
    const float uClone = clamp(uBg - s * shiftFrac * cropW, M2Crop.x, M2Crop.z);
    float3 bRgb, bMac, bLp;
    const bool okL = GDHybridSampleTap(uClone, base.y, dBg, invWu, cropW, cropH, bRgb, bMac, bLp);
    const float diffL = dot(abs(bMac - cRgb), float3(1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0));

    // Mode 2 (#4 Tight B+C2): pure shear-free Left -> C.
    [branch] if (tapMode == 2u) {
        const float aL2 = okL ? (1.0 - smoothstep(gateLo, gateHi, diffL)) : 0.0;
        const float3 fill2 = lerp(cRgb, bRgb, inRamp * aL2 * detailStr);
        return lerp(baseRgb, fill2, wGap);
    }

    // 6 zero-shift vertical taps at exact wall X (uBg, y +- 16/32/50 px equiv) for #5 and #6.
    const float vLo = (tapMode == 1u) ? (gateHi * 0.36) : gateLo;
    const float vHi = (tapMode == 1u) ? min(gateHi * 1.27, 0.35) : gateHi;

    float3 sumRgb = float3(0.0, 0.0, 0.0);
    float3 sumLp  = float3(0.0, 0.0, 0.0);
    float sumW = 0.0;
    float maxA = 0.0;

    [unroll] for (uint vi = 0u; vi < 6u; ++vi) {
        float3 vRgb, vMac, vLp;
        const float vTap = base.y + GD_HYB_DY[vi] * shiftScale * cropH;
        const bool okV = GDHybridSampleTap(uBg, vTap, dBg, invWu, cropW, cropH, vRgb, vMac, vLp);
        if (okV) {
            const float diffV = dot(abs(vMac - cRgb), float3(1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0));
            const float aV = (1.0 - smoothstep(vLo, vHi, diffV)) * GD_HYB_BIAS[vi];
            const float wV = GDPow6(aV);
            sumRgb += vRgb * wV;
            sumLp  += vLp  * wV;
            sumW   += wV;
            maxA = max(maxA, aV);
        }
    }

    // Mode 1 (#5 Tight B+C3): vertical-preferred U/D -> Left backup -> C.
    [branch] if (tapMode == 1u) {
        const float aL1 = okL ? (1.0 - smoothstep(vLo, vHi, diffL)) : 0.0;
        const float3 leftBak = lerp(cRgb, bRgb, inRamp * aL1 * detailStr);
        const float3 vertRgb = sumW > 1.e-6 ? (sumRgb / sumW) : cRgb;
        const float3 fill1 = lerp(leftBak, vertRgb, inRamp * maxA * detailStr);
        return lerp(baseRgb, fill1, wGap);
    }

    // Mode 0 (#6 Tight B+C2+3 default): best-match U/D + Left with C-anchored high-pass stabilization.
    if (okL) {
        const float aL0 = (1.0 - smoothstep(gateLo, gateHi, diffL)) * 0.82;
        const float wL0 = GDPow6(aL0);
        sumRgb += bRgb * wL0;
        sumLp  += bLp  * wL0;
        sumW   += wL0;
        maxA = max(maxA, aL0);
    }
    const float3 bestRgb = sumW > 1.e-6 ? (sumRgb / sumW) : cRgb;
    const float3 bestLp  = sumW > 1.e-6 ? (sumLp  / sumW) : cRgb;
    const float3 anchored = saturate(cRgb + clamp(bestRgb - bestLp, -0.25, 0.25));
    // detailStr = 0.70 -> exact Study 93 #6 (70% direct matched tap + 30% C-anchored detail); 0 = pure C; 1 = sharp copy.
    const float3 hybRgb = lerp(anchored, bestRgb, detailStr);
    const float opacity = saturate(detailStr / 0.35);
    const float3 fill0 = lerp(cRgb, hybRgb, inRamp * maxA * opacity);
    return lerp(baseRgb, fill0, wGap);
}

float3 GDHybridFoveaColor(float2 outputUv, uint eye, float2 sourceUv, float3 baseFoveaRgb) {
    [branch] if ((M6PreviousRect.y & 0x200000u) == 0u || M4Flags.x <= 0.5 || M4Grid.x == 0u || M4Grid.y == 0u)
        return baseFoveaRgb;
    const float2 base = GDHybridBaseUv(outputUv, eye);
    const float cropW = max(M2Crop.z - M2Crop.x, 1.e-6);
    const float cropH = max(M2Crop.w - M2Crop.y, 1.e-6);
    const float2 localBase = float2((base.x - M2Crop.x) / cropW, (base.y - M2Crop.y) / cropH);
    [branch] if (any(localBase <= 0.0) || any(localBase >= 1.0)) return baseFoveaRgb;

    const float edge = min(min(localBase.x, localBase.y), min(1.0 - localBase.x, 1.0 - localBase.y));
    const float tEdge = saturate(edge / max(M4Flags.w, 0.0001));
    const float hbBlend = tEdge * tEdge * (3.0 - 2.0 * tEdge);
    [branch] if (hbBlend <= 0.0) return baseFoveaRgb;

    const float ty = clamp(localBase.y * float(M4Grid.y) - 0.5, 0.0, float(M4Grid.y) - 1.0001);
    const uint y0 = uint(floor(ty));
    const uint y1 = min(y0 + 1u, M4Grid.y - 1u);
    const float fy = saturate(ty - float(y0));

    const float d0 = GDReadFineRow(sourceUv.x, y0, eye);
    const float d1 = GDReadFineRow(sourceUv.x, y1, eye);
    const float invWu = 1.0 / max(asfloat(M7ColorExtent.z), 1.0);

    // Fast path (~97% of fovea): no vertical depth cliff -> reuse M1PullUv root directly!
    [branch] if (abs(d0 - d1) <= 0.08 * invWu) {
        const uint yn = (fy >= 0.5) ? y1 : y0;
        return GDHybridEvalRow(base, sourceUv.x, yn, eye, hbBlend, baseFoveaRgb, cropW, cropH);
    }

    // Slanted silhouette rim (~2-3% of fovea): pure two-row bilateral Y blend (zero depth shelf, zero 1.46-px steps!).
    const float u0 = GDHybridRootRow(base, y0, eye);
    const float u1 = GDHybridRootRow(base, y1, eye);
    const float3 b0 = GDHybridSampleFovea(u0, base.y, cropW, cropH);
    const float3 b1 = GDHybridSampleFovea(u1, base.y, cropW, cropH);
    const float3 r0 = GDHybridEvalRow(base, u0, y0, eye, hbBlend, b0, cropW, cropH);
    const float3 r1 = GDHybridEvalRow(base, u1, y1, eye, hbBlend, b1, cropW, cropH);
    return lerp(r0, r1, fy);
}

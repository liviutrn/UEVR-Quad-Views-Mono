// Phase 2 — DuoView-only compositing helpers. These functions run in the same
// raster draw as v208d, without a new GPU texture, compute pass, or history reset.
// The caller provides DuoReadFocus/DuoReadContext for native OR gather sources.
static const float3 DuoPhase2Luma = float3(.2126, .7152, .0722);

float3 DuoPhase2FocusLift(float3 color, float2 local) {
    [branch] if (FocusLift.x < .5) return color;
    const float2 q = local * 2.0 - 1.0;
    const float r2 = saturate(dot(q, q) * .5);
    float gain = FocusLift.y;
    [branch] if (r2 > FocusLift.w && FocusProfile.x > 0.0 && FocusProfile.y > 0.0) {
        const float t = saturate((r2 - FocusLift.w) / max(1.0 - FocusLift.w, .1));
        gain *= 1.0 + FocusProfile.x * pow(t, FocusProfile.y);
    }
    return max(color * gain, 0.0);
}

float3 DuoPhase2MatchContext(float2 uv, float3 inputColor) {
    [branch] if (SeamOptions.x < .5) return inputColor;
    const float2 extent = float2(OutputSize);
    // Only run the expensive edge probes near the real, gaze-moving crop edge.
    const float2 beyond = max(max(CropUv.xy - uv, uv - CropUv.zw), 0.0) * extent;
    const float outerDistance = max(beyond.x, beyond.y);
    [branch] if (outerDistance > SeamGeometry.x) return inputColor;

    const float2 da = abs(uv - CropUv.xy) * extent;
    const float2 db = abs(CropUv.zw - uv) * extent;
    const float2 nearest = min(da, db);
    const bool vertical = nearest.x < nearest.y;
    const float2 stepDirection = vertical ? float2(0.0, 1.0) : float2(1.0, 0.0);
    // Sample just INSIDE the real fovea edge so the last texels remain valid.
    float2 edge = clamp(uv, CropUv.xy + 1.5 / extent, CropUv.zw - 1.5 / extent);
    if (vertical) edge.x = da.x < db.x ? CropUv.x + 1.5 / extent.x : CropUv.z - 1.5 / extent.x;
    else edge.y = da.y < db.y ? CropUv.y + 1.5 / extent.y : CropUv.w - 1.5 / extent.y;

    float3 gainSum = 0.0;
    float confidence = 0.0;
    // Four spatial groups instead of one bright-pixel measurement. Samples are
    // clamped INSIDE the fovea crop; no extended/stretched fake focus pixels.
    [unroll] for (int k = 0; k < 4; ++k) {
        const float offsetPx = k == 0 ? -12.0 : (k == 1 ? -4.0 : (k == 2 ? 4.0 : 12.0));
        const float2 sampleUv = clamp(edge + stepDirection * (offsetPx / extent),
                                      CropUv.xy + 1.5 / extent, CropUv.zw - 1.5 / extent);
        const float2 local = (sampleUv - CropUv.xy) / (CropUv.zw - CropUv.xy);
        const float3 focus = DuoPhase2FocusLift(DuoReadFocus(sampleUv), local);
        const float3 context = DuoReadContext(sampleUv);
        const float fl = dot(focus, DuoPhase2Luma);
        const float pl = dot(context, DuoPhase2Luma);
        // Reject black/invalid probes, and reject high-contrast geometry edges
        // instead of letting one bright object dictate the entire seam colour.
        const float consistency = abs(fl - pl) / max(fl + pl, .06);
        [branch] if (min(fl, pl) <= .012 || consistency > .45) continue;
        const float quality = saturate((.45 - consistency) * 4.0);
        const float maxGain = 1.0 + SeamOptions.z;
        const float minGain = 1.0 - SeamOptions.z;
        const float luminanceGain = clamp(fl / max(pl, .012), minGain, maxGain);
        const float3 channelGain = clamp(focus / max(context, float3(.012, .012, .012)),
                                          minGain, maxGain);
        gainSum += quality * lerp(luminanceGain.xxx, channelGain, SeamGeometry.z);
        confidence += quality;
    }
    // No plausible border samples -> neutral, NOT last frame's stale gain.
    [branch] if (confidence < .5) return inputColor;
    const float3 gain = lerp(float3(1.0,1.0,1.0), gainSum / confidence, SeamOptions.y);
    const float falloff = 1.0 - smoothstep(0.0, max(SeamGeometry.x, 1.0), outerDistance);
    return max(inputColor * lerp(float3(1.0,1.0,1.0), gain, falloff), 0.0);
}

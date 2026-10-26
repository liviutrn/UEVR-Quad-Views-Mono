// R6 samples only the executed producer rectangle, including all filter taps.
float2 DepthScale() {
    return DepthUvScaleBias.x > 0 && DepthUvScaleBias.y > 0 ? DepthUvScaleBias.xy :
        float2(DepthIsDoubleWide != 0 ? 0.5f : 1.0f, 1.0f);
}
float2 DepthBias() { return DepthUvScaleBias.x > 0 ? DepthUvScaleBias.zw : float2(0,0); }
int2 ClampDepthCoord(int2 p) {
    const float2 size = float2(DepthWidth, DepthHeight);
    const int2 lo = int2(floor(DepthBias() * size + 0.001f));
    const int2 hi = max(lo, int2(ceil((DepthBias() + DepthScale()) * size - 0.001f)) - 1);
    return clamp(p, lo, min(hi, int2(DepthWidth, DepthHeight) - 1));
}
float RawDepthAt(int2 p) { return SourceDepth.Load(int3(ClampDepthCoord(p), 0)); }
float2 DepthPosition(float2 uv) {
    const float2 half_texel = 0.5f / float2(DepthWidth, DepthHeight);
    const float2 mapped = clamp(saturate(uv) * DepthScale() + DepthBias(),
        DepthBias() + half_texel, DepthBias() + DepthScale() - half_texel);
    return mapped * float2(DepthWidth, DepthHeight) - 0.5f;
}
float RawPointDepth(float2 uv) { return RawDepthAt(int2(floor(DepthPosition(uv) + 0.5f))); }
float SampleSelectedDepth(float2 uv) {
    const float2 p = DepthPosition(uv);
    if (DepthSamplingMode == 0) {
        return SourceDepth.SampleLevel(LinearClamp, (p + 0.5f) / float2(DepthWidth, DepthHeight), 0);
    }
    if (DepthSamplingMode == 1) return RawPointDepth(uv);
    const int2 base = int2(floor(p));
    const float a = RawDepthAt(base), b = RawDepthAt(base + int2(1,0));
    const float c = RawDepthAt(base + int2(0,1)), d = RawDepthAt(base + int2(1,1));
    const float spread = max(max(a,b),max(c,d)) - min(min(a,b),min(c,d));
    if (spread > max(DepthRepairThreshold, 0.00001f)) return RawPointDepth(uv);
    return lerp(lerp(a,b,frac(p.x)),lerp(c,d,frac(p.x)),frac(p.y));
}
float ReadDepth(float2 uv) {
    float value = SampleSelectedDepth(uv);
    if (DepthRepairMode != 0) {
        const int2 center = int2(floor(DepthPosition(uv) + 0.5f));
        float neighbors[8];
        uint n = 0;
        [unroll] for (int y = -1; y <= 1; ++y) {
            [unroll] for (int x = -1; x <= 1; ++x) {
                if (x != 0 || y != 0) neighbors[n++] = RawDepthAt(center + int2(x,y));
            }
        }
        // Sort the eight surrounding samples; no average across a silhouette.
        [unroll] for (uint i = 1; i < 8; ++i) {
            [unroll] for (uint j = 0; j < 7; ++j) {
                if (j < 8-i && neighbors[j] > neighbors[j+1]) {
                    float t = neighbors[j]; neighbors[j] = neighbors[j+1]; neighbors[j+1] = t;
                }
            }
        }
        const float threshold = max(DepthRepairThreshold, 0.00001f);
        const float median = 0.5f * (neighbors[3] + neighbors[4]);
        if (neighbors[7] - neighbors[0] <= threshold && abs(RawDepthAt(center) - median) > threshold)
            value = median;
    }
    // Device-depth convention calibration, deliberately not a metric claim.
    const float scale = DepthScaleCalibration > 0 ? DepthScaleCalibration : 1.0f;
    if (scale != 1.0f) value = ReversedDepth != 0 ? saturate(value * scale) : 1.0f - saturate((1.0f-value) * scale);
    return value;
}
float ReadableDepth(float value) {
    const float exposure = exp2(clamp(DepthDisplayGain, -8.0f, 24.0f));
    const float near_value = ReversedDepth != 0 ? saturate(value) : 1.0f - saturate(value);
    return log2(1.0f + near_value * exposure) / log2(1.0f + exposure);
}

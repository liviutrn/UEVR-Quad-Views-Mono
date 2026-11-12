// One shared, softened inverse-depth field in the center-camera projection.
cbuffer DuoViewM1 : register(b1) {
    float4 M1Homography[6];
    float4 M1Eye; // signed horizontal disparity factors (left/right), jitter UV (xy)
    float4 M1Depth; // m10, m14, m11, near-limit inverse world units
    uint4 M1Rect; // offset and extent in the captured NGX input
    uint4 M1Grid; // active and allocated extent
    float4 M1Filter; // slope per grid texel, inverse-depth cap
};

#ifdef DUOVIEW_M1_CONDITION
Texture2D<float> M1RawDepth : register(t4);
RWTexture2D<float> M1ConditionedDepth : register(u2);

groupshared float M1Row[1024];
groupshared float M1Next[1024];

float DecodeM1Depth(int2 pixel) {
    pixel = clamp(pixel, int2(0,0), int2(M1Rect.zw)-1);
    const float d = M1RawDepth.Load(int3(pixel + int2(M1Rect.xy), 0));
    const float inverse = (M1Depth.z * d - M1Depth.x) / M1Depth.y;
    return isfinite(inverse) ? max(inverse, 0.0) : 0.0;
}

[numthreads(128,1,1)]
void CSConditionM1(uint3 group : SV_GroupID, uint lane : SV_GroupIndex) {
    const uint w = M1Grid.x;
    for (uint x = lane; x < w; x += 128) {
        const int2 center = int2((float2(x, group.x) + 0.5) * float2(M1Rect.zw) / float2(M1Grid.xy));
        float nearDepth = 0.0;
        [unroll] for (int y = -1; y <= 1; ++y)
            [unroll] for (int dx = -1; dx <= 1; ++dx)
                nearDepth = max(nearDepth, DecodeM1Depth(center + int2(dx,y)));
        const float knee = M1Depth.w;
        if (knee > 0.0 && nearDepth > knee) {
            const float excess = nearDepth - knee;
            nearDepth = knee + excess / (1.0 + excess / knee);
        }
        M1Row[x] = knee > 0.0 ? nearDepth : min(nearDepth, M1Filter.y);
    }
    GroupMemoryBarrierWithGroupSync();

    const float limit = M1Depth.w > 0.0 ? 2.0*M1Depth.w : M1Filter.y;
    // Each pass doubles the reachable radius. Stop only when more distant
    // contributions would be <= 0, or all texels in the row are reachable.
    for (uint step = 1; step < w && float(step-1)*M1Filter.x < limit; step *= 2) {
        for (uint x = lane; x < w; x += 128) {
            const float penalty = float(step)*M1Filter.x;
            const float l = x >= step ? M1Row[x-step] - penalty : 0.0;
            const float r = x+step < w ? M1Row[x+step] - penalty : 0.0;
            M1Next[x] = max(M1Row[x], max(l,r));
        }
        GroupMemoryBarrierWithGroupSync();
        for (uint x = lane; x < w; x += 128) M1Row[x] = M1Next[x];
        GroupMemoryBarrierWithGroupSync();
    }
    for (uint x = lane; x < w; x += 128)
        M1ConditionedDepth[uint2(x,group.x)] = M1Row[x];
}
#endif

#ifdef DUOVIEW_M1_RASTER
Texture2D<float> M1SoftDepth : register(t3);

float2 M1PullUv(float2 eyeUv, uint eye) {
    const uint row = 3u*eye;
    const float3 p = float3(eyeUv,1.0);
    const float w = dot(M1Homography[row+2].xyz,p);
    const float2 base = float2(dot(M1Homography[row].xyz,p),dot(M1Homography[row+1].xyz,p)) / w;
    float2 uv = base;
    [branch] if (M1Grid.x > 0 && abs(M1Eye[eye]) > 1.e-6) {
        [unroll] for (uint pass = 0; pass < 6; ++pass) {
            const float2 cell = clamp((uv + M1Eye.zw) * float2(M1Grid.xy),
                                     float2(.5,.5), float2(M1Grid.xy)-.5);
            const float d = M1SoftDepth.SampleLevel(LinearClamp, cell / float2(M1Grid.zw),0);
            uv.x = base.x + M1Eye[eye] * d;
        }
    }
    return saturate(uv);
}
#endif

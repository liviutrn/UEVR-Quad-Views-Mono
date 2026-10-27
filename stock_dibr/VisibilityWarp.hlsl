// R7: current-frame forward visibility. No temporal color/depth is sampled.
// Point coverage avoids dilating a foreground silhouette with tiny splat weights.
float VisibilityReadDepth(float2 uv) {
    return CalibrateAndRepairDepth(uv,DepthSamplingMode == 2 ? SampleSelectedDepth(uv) : RawPointDepth(uv));
}
float VisibilityNearDepth(float value) { return ReversedDepth != 0 ? value : 1-value; }
bool VisibilityProject(float2 source_uv, float depth, out float2 target_uv, out uint key) {
    target_uv = 0; key = 0;
    const float2 ndc = float2(source_uv.x*2-1, 1-source_uv.y*2);
    precise float4 clip = mul(SourceToRight,float4(ndc,depth,1));
    if (!all(isfinite(clip)) || clip.w <= 1e-6f || !isfinite(depth) || depth < 0 || depth > 1) return false;
    precise float target_depth = clip.z / clip.w;
    if (!isfinite(target_depth) || target_depth < 0 || target_depth > 1) return false;
    const float2 projected = float2(clip.x/clip.w*.5f+.5f,.5f-clip.y/clip.w*.5f);
    target_uv = lerp(source_uv,projected,TrueReprojectionStrength);
    if (!all(isfinite(target_uv))) return false;
    const float near_depth = ReversedDepth != 0 ? target_depth : 1-target_depth;
    key = asuint(max(near_depth,0.0f));
    return true;
}
bool VisibilityFootprint(uint2 source, out int2 target, out uint key) {
    const float2 uv = (float2(source)+.5f)/float2(SourceEyeWidth,OutputHeight);
    float2 mapped;
    if (!VisibilityProject(uv,VisibilityReadDepth(uv),mapped,key)) { target=0; return false; }
    if (any(mapped < 0) || any(mapped >= 1)) { target=0; return false; }
    target = int2(floor(mapped*float2(SourceEyeWidth,OutputHeight)));
    return true;
}
[numthreads(8,8,1)]
void ClearVisibility(uint3 tid : SV_DispatchThreadID) {
    if (tid.x >= SourceEyeWidth || tid.y >= OutputHeight) return;
    VisibilityDepth[tid.xy] = 0u;
    VisibilitySource[tid.xy] = 0xffffffffu;
}
[numthreads(8,8,1)]
void ScatterDepth(uint3 tid : SV_DispatchThreadID) {
    if (tid.x >= SourceEyeWidth || tid.y >= OutputHeight) return;
    int2 target; uint key;
    if (VisibilityFootprint(tid.xy,target,key)) {
        uint ignored; InterlockedMax(VisibilityDepth[target],key,ignored);
    }
}
[numthreads(8,8,1)]
void ScatterSource(uint3 tid : SV_DispatchThreadID) {
    if (tid.x >= SourceEyeWidth || tid.y >= OutputHeight) return;
    int2 target; uint key;
    if (VisibilityFootprint(tid.xy,target,key) && VisibilityDepth[target] == key) {
        uint ignored;
        InterlockedMin(VisibilitySource[target],tid.y*SourceEyeWidth+tid.x,ignored);
    }
}
float2 VisibilitySourceUv(uint index) {
    return (float2(index % SourceEyeWidth,index / SourceEyeWidth)+.5f)/float2(SourceEyeWidth,OutputHeight);
}
bool VisibilityCovered(int2 p, out uint index, out float near_depth) {
    index=0xffffffffu; near_depth=0;
    if (any(p < 0) || p.x >= (int)SourceEyeWidth || p.y >= (int)OutputHeight) return false;
    index=VisibilitySource[p];
    near_depth=asfloat(VisibilityDepth[p]);
    return index < SourceEyeWidth*OutputHeight && isfinite(near_depth);
}
bool VisibilityCompatible(float a, float b) {
    return abs(a-b) <= max(1e-7f, max(abs(a),abs(b))*max(VisibilityDepthTolerance,.001f));
}
float4 VisibilityPointColor(uint index) {
    return SourceColor.Load(int3(index % SourceEyeWidth,index / SourceEyeWidth,0));
}
float4 VisibilitySurfaceColor(uint index, float2 target_uv) {
    const float2 anchor=VisibilitySourceUv(index);
    const float anchor_depth=VisibilityReadDepth(anchor);
    float2 projected; uint ignored;
    if (!VisibilityProject(anchor,anchor_depth,projected,ignored)) return VisibilityPointColor(index);
    const float2 refined=anchor+(target_uv-projected);
    if (any(refined < 0) || any(refined > 1) || !VisibilityCompatible(VisibilityNearDepth(VisibilityReadDepth(refined)),VisibilityNearDepth(anchor_depth)))
        return VisibilityPointColor(index);
    const float2 position=refined*float2(SourceEyeWidth,OutputHeight)-.5f;
    const int2 base=int2(floor(position));
    const int2 maximum=int2(SourceEyeWidth,OutputHeight)-1;
    // All four color taps must belong to the winning depth surface. Hardware
    // bilinear color alone leaks foreground into a background silhouette.
    [unroll] for (int y=0;y<2;++y) [unroll] for (int x=0;x<2;++x) {
        const int2 p=clamp(base+int2(x,y),int2(0,0),maximum);
        const float2 uv=(float2(p)+.5f)/float2(SourceEyeWidth,OutputHeight);
        if (!VisibilityCompatible(VisibilityNearDepth(VisibilityReadDepth(uv)),VisibilityNearDepth(anchor_depth))) return VisibilityPointColor(index);
    }
    float2 check_uv; uint check_key;
    if (!VisibilityProject(refined,VisibilityReadDepth(refined),check_uv,check_key) ||
        length((check_uv-target_uv)*float2(SourceEyeWidth,OutputHeight)) > .75f)
        return VisibilityPointColor(index);
    return SourceColor.SampleLevel(LinearClamp,refined,0);
}
bool VisibilityStableRun(int2 boundary, int direction, float near_depth) {
    [unroll] for (int i=1;i<=2;++i) {
        uint index; float next_depth;
        if (!VisibilityCovered(boundary+int2(direction*i,0),index,next_depth) ||
            !VisibilityCompatible(next_depth,near_depth)) return false;
    }
    return true;
}
float4 VisibilityResolve(float2 uv, out uint state) {
    const int2 p=clamp(int2(uv*float2(SourceEyeWidth,OutputHeight)),int2(0,0),int2(SourceEyeWidth,OutputHeight)-1);
    uint index; float near_depth;
    if (VisibilityCovered(p,index,near_depth)) { state=0; return VisibilitySurfaceColor(index,uv); }
    const uint radius=min(VisibilityFillRadius,64u);
    int left_distance=0,right_distance=0;
    uint left_index=0xffffffffu,right_index=0xffffffffu; float left_depth=0,right_depth=0;
    [loop] for (uint distance=1;distance<=radius;++distance) {
        if (left_distance==0 && VisibilityCovered(p-int2((int)distance,0),left_index,left_depth)) left_distance=(int)distance;
        if (right_distance==0 && VisibilityCovered(p+int2((int)distance,0),right_index,right_depth)) right_distance=(int)distance;
        if ((left_distance!=0 || p.x-(int)distance<0) &&
            (right_distance!=0 || p.x+(int)distance>=(int)SourceEyeWidth)) break;
    }
    if (left_distance!=0 && right_distance!=0 && left_distance+right_distance<=5 && VisibilityCompatible(left_depth,right_depth)) {
        // A small sampling crack on one coherent surface is not disocclusion.
        // Reproject its winning surface instead of spreading a foreground mask.
        state=1; return VisibilitySurfaceColor(left_distance<=right_distance?left_index:right_index,uv);
    }
    if (left_distance!=0 && right_distance!=0 && left_distance+right_distance-1 <= (int)radius) {
        const bool left_farther=left_distance!=0 && (right_distance==0 || left_depth<right_depth);
        const int2 boundary=p+int2(left_farther?-left_distance:right_distance,0);
        const float background_depth=left_farther?left_depth:right_depth;
        const bool distinct_boundaries=!VisibilityCompatible(left_depth,right_depth);
        if (distinct_boundaries && VisibilityStableRun(boundary,left_farther?-1:1,background_depth)) {
            state=1;
            // Hidden background color is unknown. Repeat only a verified
            // visible background sample; never stretch the nearer character.
            return VisibilityPointColor(left_farther?left_index:right_index);
        }
    }
    // Explicit unresolved state (red in inspector). A single view contains no
    // evidence for arbitrary large/ambiguous hidden areas. Retain the R6
    // geometric mapping here rather than inventing depth or historical pixels.
    state=2;
    const float d=saturate(ReadDepth(uv));
    const float disparity=DisparityPixels*LegacyDepthResponse(d)/max((float)SourceEyeWidth,1.0f);
    uint clamped;
    const float2 legacy=ResolveSyntheticRightSourceUv(uv,disparity,TrueReprojectionStrength,clamped);
    return SourceColor.SampleLevel(LinearClamp,legacy,0);
}
float4 VisibilityStateColor(uint state) {
    return state==0?float4(.05f,.75f,.1f,1):state==1?float4(0,.7f,1,1):float4(1,.05f,.05f,1);
}

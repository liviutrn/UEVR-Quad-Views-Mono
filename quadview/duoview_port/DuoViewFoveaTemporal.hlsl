// Both ping-pong images store unconditioned history on the current gaze
// crop's unjittered grid. Each texel keeps smoothed near depth, raw colour
// sample depth, packed accumulated colour, and raw near depth.
Texture2D<float4> M7PreviousHistory : register(t9);

bool M7Reproject(float2 fullUv, float inverseZ, out float2 previousLocal, out float zScale) {
    const float4 p=M6CurrentProjection;
    const float4 ray=float4((2.*fullUv.x-1.-p.y)/p.x,
                            (1.-2.*fullUv.y-p.w)/p.z,1.,inverseZ);
    const float3 prev=float3(dot(M6View[0],ray),dot(M6View[1],ray),dot(M6View[2],ray));
    zScale=prev.z;
    previousLocal=0.;
    if (zScale<=.01) return false;
    const float4 pp=M6PreviousProjection;
    const float2 uv=float2(.5+.5*(pp.x*prev.x/zScale+pp.y),.5-.5*(pp.z*prev.y/zScale+pp.w));
    previousLocal=(uv-M6PreviousCrop.xy)/(M6PreviousCrop.zw-M6PreviousCrop.xy);
    return all(previousLocal>=0.) && all(previousLocal<1.);
}

float3 M7UnpackColor(float packed) {
    const uint bits=uint(packed);
    const float3 color=float3(bits&255u,(bits>>8u)&255u,(bits>>16u)&255u)/255.;
    return color*color;
}

#ifdef DUOVIEW_M1_CONDITION
RWTexture2D<float4> M7CurrentWrite : register(u6);
Texture2D<float4> M7FoveaColor : register(t0);
SamplerState M7LinearClamp : register(s0);

float M7PackColor(float3 color) {
    const uint3 bytes=uint3(round(sqrt(saturate(color))*255.));
    return float(bytes.x|(bytes.y<<8u)|(bytes.z<<16u));
}

float M7StabilizeEdge(float2 fullUv, float nearZ, float farZ) {
    const float disparity=max(abs(M1Eye.x),abs(M1Eye.y))*M23Wide.z;
    // Only discontinuity seeds need history. The existing per-eye envelope
    // spreads them to exactly the width set by the edge/softness controls.
    [branch] if (M6PreviousJitter.z<.5 || M7Controls.x<=0. || (nearZ-farZ)*disparity<.16)
        return nearZ;
    float2 previousLocal;
    float zScale;
    if (!M7Reproject(fullUv,nearZ,previousLocal,zScale)) return nearZ;
    const float2 extent=float2(M6PreviousRect.zw);
    const int2 base=int2(floor(previousLocal*extent-.5));
    const float expected=nearZ/zScale;
    float filtered=expected;
    float error=1.e9;
    [unroll] for (int y=0; y<2; ++y) {
        [unroll] for (int x=0; x<2; ++x) {
            const int2 pixel=clamp(base+int2(x,y),int2(0,0),int2(extent)-1);
            const float4 history=M7PreviousHistory.Load(int3(pixel,0));
            const float difference=abs(history.w-expected);
            if (difference<error) {
                filtered=history.x;
                error=difference;
            }
        }
    }
    if (error*disparity>.65) return nearZ;
    const float rotZ=zScale-M6View[2].w*nearZ;
    const float denominator=1.-filtered*M6View[2].w;
    if (denominator<=.01 || rotZ<=.01) return nearZ;
    const float candidate=filtered*rotZ/denominator;
    const float limit=.35/max(disparity,1.e-5);
    return max(0.,lerp(nearZ,clamp(candidate,nearZ-limit,nearZ+limit),M7Controls.x));
}

float3 M7AccumulateFillColor(float2 local, float2 fullUv, float backgroundZ) {
    const float2 colorExtent=float2(M7ColorExtent.xy);
    const float2 texel=clamp(local*colorExtent,.5,colorExtent-.5);
    const float3 current=M7FoveaColor.SampleLevel(M7LinearClamp,texel/float2(M7ColorExtent.zw),0.).rgb;
    [branch] if (M6PreviousJitter.w<.5) return current;
    float2 previousLocal;
    float zScale;
    if (!M7Reproject(fullUv,backgroundZ,previousLocal,zScale)) return current;

    const float2 extent=float2(M6PreviousRect.zw);
    const int2 pixel=min(int2(previousLocal*extent),int2(extent)-1);
    const float4 history=M7PreviousHistory.Load(int3(pixel,0));
    const float expected=backgroundZ/zScale;
    const float disparity=max(abs(M1Eye.x),abs(M1Eye.y))*M23Wide.z;
    if (abs(history.y-expected)*disparity>.5) return current;
    const float3 oldColor=M7UnpackColor(history.z);
    const float3 gap=abs(oldColor-current);
    const float difference=max(gap.x,max(gap.y,gap.z));
    const float retention=M7Controls.y*(1.-smoothstep(.04,.16,difference));
    return lerp(current,clamp(oldColor,current-.07,current+.07),retention);
}
#endif

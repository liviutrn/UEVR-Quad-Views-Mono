// B40 Continuous Ambient seam analysis ported to DuoView Mono ID6.
// Based directly on QuadViewComposite.hlsl UpdateEdgeB40, AmbientEdgeDifference,
// EdgeAnchor and MatchEdgeV2. One Mono path => one 32-knot GPU history.
//
// The same 128 deterministic spatial centers (four per knot), 15 paired RGB
// samples per center, component-wise trimmed groups, and temporal EMA as B40.
// The two Source SRVs and the output share the existing DuoView command slot.
// Native and gathered sources use identical algorithms and pixel coordinates.
static const float3 DuoPhase2Luma = float3(.2126,.7152,.0722);

float3 DuoPhase2FocusLift(float3 color, float2 local) {
    [branch] if (FocusLift.x < .5) return color;
    const float2 q=local*2.0-1.0;
    const float r2=saturate(dot(q,q)*.5);
    float gain=FocusLift.y;
    [branch] if (r2>FocusLift.w && FocusLift.z>0.0 && FocusProfile.x>0.0) {
        const float t=saturate((r2-FocusLift.w)/max(1.0-FocusLift.w,.1));
        gain*=1.0+FocusLift.z*pow(t,FocusProfile.x);
    }
    return max(color*gain,0.0);
}

// B38 restores the B27 raw-context interior feather; the fovea itself
// remains unblurred. The appearance correction fades in from the inner edge.
float DuoB40InwardAnchor(float2 uv) {
    const float2 inside=min(uv-CropUv.xy,CropUv.zw-uv)*float2(OutputSize);
    const float distance=max(min(inside.x,inside.y),0.0);
    const float t=saturate(distance/max(SeamGeometry.y,1.0));
    return 1.0-t*t*(3.0-2.0*t);
}

StructuredBuffer<float4> DuoMonoSeamMatch : register(t2);

float DuoB40EdgeFade(float distance,float reach) {
    const float t=saturate(distance/max(reach,1.0));
    return 1.0-t*t*(3.0-2.0*t);
}

// B40's nearest-side+32-knot interpolation, in display UV, not cropped pixels.
// No per-pixel border-copy, no immediate/raw sample path and no pixel stretching.
float3 DuoPhase2MatchContext(float2 uv,float3 context) {
    [branch] if (SeamOptions.x<.5) return context;
    const float2 size=float2(OutputSize);
    const float2 outside=max(max(max(CropUv.xy-uv,uv-CropUv.zw),0.0)*size-1.0,0.0);
    const float distance=length(outside);
    [branch] if (distance>=SeamGeometry.x || SeamOptions.y<=0.0) return context;

    float2 edge=clamp(uv,CropUv.xy,CropUv.zw);
    const float4 d=float4(abs(edge.y-CropUv.y),abs(edge.x-CropUv.z),
                          abs(edge.y-CropUv.w),abs(edge.x-CropUv.x));
    uint side=0u; float nearest=d.x;
    if(d.y<nearest){side=1u;nearest=d.y;}
    if(d.z<nearest){side=2u;nearest=d.z;}
    if(d.w<nearest){side=3u;}
    if(uv.y<CropUv.y) side=0u;
    else if(uv.y>CropUv.w) side=2u;
    else if(uv.x>CropUv.z) side=1u;
    else if(uv.x<CropUv.x) side=3u;
    const float2 alongUv=saturate((edge-CropUv.xy)/max(CropUv.zw-CropUv.xy,1.0/size));
    const float along=side==0u ? alongUv.x : side==1u ? alongUv.y :
                      side==2u ? 1.0-alongUv.x : 1.0-alongUv.y;
    const float k=float(side*8u)+along*8.0;
    const uint i=((uint)floor(k))%32u, j=(i+1u)%32u;
    const float3 a=DuoMonoSeamMatch[i*2u+1u].rgb;
    const float3 b=DuoMonoSeamMatch[j*2u+1u].rgb;
    const float3 stable=lerp(a,b,frac(k));
    // B40 RGB residual, optional luma-only A/B; 1 = exact B40 RGB.
    const float luma=dot(stable,DuoPhase2Luma);
    const float3 correction=lerp(luma.xxx,stable,SeamGeometry.z);
    return max(context+SeamOptions.y*DuoB40EdgeFade(distance,SeamGeometry.x)*correction,0.0);
}

#ifdef DUOVIEW_B40_COMPUTE
RWStructuredBuffer<float4> DuoMonoSeamOutput : register(u0);
RWStructuredBuffer<float4> DuoMonoEdgeHistory : register(u1);

// B39 inward 3x5 group. Exactly fifteen paired samples per spatial center.
// Unlike TriView, no depth warp is needed: Mono periphery and focus share the
// same full-FOV UV; sample both actual sources and reject nonfinite readings.
bool DuoB40AmbientEdgeDifference(float2 anchor,uint side,out float3 delta) {
    const float2 size=float2(OutputSize);
    const float2 lo=(ceil(CropUv.xy*size-.5)+.5)/size;
    const float2 hi=(ceil(CropUv.zw*size-.5)-.5)/size;
    const float2 inward=side==0u ? float2(0.0,1.0) :
                        side==1u ? float2(-1.0,0.0) :
                        side==2u ? float2(0.0,-1.0) : float2(1.0,0.0);
    const float2 tangent=float2(inward.y,-inward.x);
    float3 sum=0.0; float accepted=0.0;
    [unroll] for(int depth=0;depth<3;++depth) {
        const float dist=SeamOptions.w*(.25+.375*float(depth));
        [unroll] for(int i=-2;i<=2;++i) {
            const float along=.5*float(i)*SeamGeometry.w;
            const float2 p=clamp(anchor+(inward*dist+tangent*along)/size,lo,hi);
            const float2 local=(p-CropUv.xy)/(CropUv.zw-CropUv.xy);
            const float3 f=DuoPhase2FocusLift(DuoReadFocus(p),local);
            const float3 c=DuoReadContext(p);
            [branch] if(all(isfinite(f)) && all(isfinite(c))) {
                sum+=f-c; accepted+=1.0;
            }
        }
    }
    delta=sum/max(accepted,1.0);
    return accepted>=8.0;
}

// Direct B40 port: 32 boundary knots, 4 subanchors per knot, trimmed RGB
// mean/median to reject local outliers, shared queue-owned EMA history. Gaze,
// scene, settings, elapsed>250ms and invalid-sample NEVER reset history.
// Allocating a fresh buffer on actual XR session/device restart is allowed.
[numthreads(32,1,1)]
void CSMonoB40(uint lane:SV_GroupIndex) {
    const uint side=lane/8u;
    const float segment=float(lane%8u);
    float3 q0=0.0,q1=0.0,q2=0.0,q3=0.0;
    uint count=0u;
    const float2 size=float2(OutputSize);
    const float2 lo=(ceil(CropUv.xy*size-.5)+.5)/size;
    const float2 hi=(ceil(CropUv.zw*size-.5)-.5)/size;
    [loop] for(uint sub=0u;sub<4u;++sub) {
        const float t=saturate((segment+(float(sub)-1.5)*.25)/8.0);
        float2 p=side==0u ? float2(lerp(CropUv.x,CropUv.z,t),CropUv.y) :
                 side==1u ? float2(CropUv.z,lerp(CropUv.y,CropUv.w,t)) :
                 side==2u ? float2(lerp(CropUv.z,CropUv.x,t),CropUv.w) :
                            float2(CropUv.x,lerp(CropUv.w,CropUv.y,t));
        p=clamp(p,lo,hi);
        float3 delta=0.0;
        [branch] if(DuoB40AmbientEdgeDifference(p,side,delta)) {
            if(count==0u) q0=delta;
            else if(count==1u) q1=delta;
            else if(count==2u) q2=delta;
            else q3=delta;
            ++count;
        }
    }

    const bool valid=count>=2u;
    float3 target=0.0;
    if(count==4u) {
        target=.5*(q0+q1+q2+q3-
            min(min(q0,q1),min(q2,q3))-max(max(q0,q1),max(q2,q3)));
    } else if(count==3u) {
        target=q0+q1+q2-min(q0,min(q1,q2))-max(q0,max(q1,q2));
    } else if(count==2u) {
        target=.5*(q0+q1);
    }

    const uint h=lane*3u;
    const uint4 stamp=asuint(DuoMonoEdgeHistory[h+2u]);
    const bool initialized=stamp.w==0x40b04001u;
    float3 stable=initialized ? DuoMonoEdgeHistory[h].rgb : float3(0.0,0.0,0.0);
    const uint elapsed=initialized ? B40Temporal.x-stamp.y : 16u;
    const uint dt=min(elapsed,50u);
    if(valid && dt>0u) {
        const float tau=float(max(B40Temporal.y,50u));
        const float alpha=float(dt)/(tau+float(dt));
        const float limit=(100.0/tau)*(float(dt)*.001);
        stable+=clamp((target-stable)*alpha,
                      float3(-limit,-limit,-limit),float3(limit,limit,limit));
    }
    DuoMonoEdgeHistory[h]=float4(stable,1.0);
    DuoMonoEdgeHistory[h+1u]=CropUv; // diagnostic only; no validity/reset check
    DuoMonoEdgeHistory[h+2u]=asfloat(uint4(0u,B40Temporal.x,0u,0x40b04001u));
    DuoMonoSeamOutput[lane*2u]=float4(target,valid ? 1.0 : 0.0);
    DuoMonoSeamOutput[lane*2u+1u]=float4(stable,1.0); // hold on invalid
}
#endif

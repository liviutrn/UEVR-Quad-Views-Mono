// CI77 depth-grid stabilization. Spatially undo NGX depth jitter onto the
// canonical per-eye pixel grid, then conservatively reuse reprojected history.
// The input and output keep device-depth encoding and the source allocation.
Texture2D<float> CurrentDepth : register(t0);
Texture2D<float> PreviousDepth : register(t1);
Texture2D<float4> PreviousState : register(t2);
RWByteAddressBuffer HistoryCounters : register(u2);

cbuffer StabilizeDepthConfig : register(b0) {
    row_major float4x4 CurrentEyeFromClip;
    row_major float4x4 PreviousClipFromCurrentEye;
    row_major float4x4 PreviousEyeFromClip;
    row_major float4x4 CurrentEyeFromPreviousEye;
    row_major float4x4 CurrentClipFromCurrentEye;
    float4 ActiveRect;             // x, y, width, height in source texels
    float4 CurrentProjection;      // A, B, C, D from deviceZ=(Az+B)/(Cz+D)
    float4 PreviousProjection;
    float4 CurrentRangeJitter;     // minDepth, maxDepth, jitterXpx, jitterYpx
    float4 PreviousRangeWeight;    // minDepth, maxDepth, historyWeight, historyValid
    float4 EdgeTolerances;         // absZ, relZ, maxReprojectionErrorPx, reserved
    float4 PreviousRect;           // previous active depth viewport, same allocation
    float4 DiagnosticConfig;       // enabled, eye counter byte offset, sampling stride, reserved
    float4 PersistenceConfig;      // enabled, unsupported hold frames, switch support, roundtrip pixels
};

struct VertexOut {
    float4 pos : SV_POSITION;
    float2 uv : TEXCOORD0;
};

float ForwardZ(float raw, float2 range, float4 projection) {
    const float span=range.y-range.x;
    if(abs(span)<1.e-7f)return -1.f;
    const float d=(raw-range.x)/span;
    const float denominator=d*projection.z-projection.x;
    if(!isfinite(d)||d<0.f||d>1.f||abs(denominator)<1.e-9f)return -1.f;
    const float z=(projection.y-d*projection.w)/denominator;
    return (isfinite(z)&&z>0.01f&&z<1.e8f)?z:-1.f;
}
float RawFromForwardZ(float z, float2 range, float4 projection) {
    const float denominator=z*projection.z+projection.w;
    if(!isfinite(z)||z<=0.f||abs(denominator)<1.e-9f)return range.y;
    const float d=(z*projection.x+projection.y)/denominator;
    return saturate(d)*(range.y-range.x)+range.x;
}
int2 ActiveMin(int2 size,float4 rect) {
    return clamp(int2(ceil(rect.xy-0.5f)),int2(0,0),size-int2(1,1));
}
int2 ActiveMax(int2 size,float4 rect) {
    return clamp(int2(ceil(rect.xy+rect.zw-0.5f))-1,
                  int2(0,0),size-int2(1,1));
}
float2 ClipXY(float2 uv) { return float2(2.f*uv.x-1.f,1.f-2.f*uv.y); }
float2 PixelToUV(float2 pixelCenter,float4 rect) {
    return (pixelCenter-rect.xy)/rect.zw;
}

float StabilizeSpatial(int2 pixel, int2 size, out float selectedZ) {
    selectedZ=-1.f;
    const int2 lo=ActiveMin(size,ActiveRect),hi=ActiveMax(size,ActiveRect);
    if(any(pixel<lo)||any(pixel>hi))return CurrentDepth.Load(int3(clamp(pixel,int2(0,0),size-1),0));

    // A source texel p describes canonical UV p - jitter. Therefore the
    // canonical output pixel samples raw depth at p + jitter.
    const float2 sampleCoord=float2(pixel)+CurrentRangeJitter.zw;
    const int2 base=int2(floor(sampleCoord));
    const float2 f=frac(sampleCoord);
    const int2 tapOffset[4]={int2(0,0),int2(1,0),int2(0,1),int2(1,1)};
    float raw[4], z[4], weight[4];
    [unroll] for(int k=0;k<4;++k) {
        const int2 p=clamp(base+tapOffset[k],lo,hi);
        raw[k]=CurrentDepth.Load(int3(p,0));
        z[k]=ForwardZ(raw[k],CurrentRangeJitter.xy,CurrentProjection);
    }
    weight[0]=(1.f-f.x)*(1.f-f.y);weight[1]=f.x*(1.f-f.y);
    weight[2]=(1.f-f.x)*f.y;weight[3]=f.x*f.y;

    // Pick the locally best-supported same-surface cluster. Ties prefer the
    // nearer surface, so a foreground edge can never be blended into sky.
    float bestSupport=-1.f,bestZ=1.e30f,invalidSupport=0.f;
    int best=-1;
    [unroll] for(int i=0;i<4;++i) {
        if(z[i]<=0.f) {invalidSupport+=weight[i];continue;}
        float support=0.f;
        const float tolerance=EdgeTolerances.x+EdgeTolerances.y*z[i];
        [unroll] for(int j=0;j<4;++j)
            if(z[j]>0.f&&abs(z[j]-z[i])<=tolerance)support+=weight[j];
        if(support>bestSupport+1.e-6f || (abs(support-bestSupport)<=1.e-6f&&z[i]<bestZ)) {
            bestSupport=support;bestZ=z[i];best=i;
        }
    }
    // Do not let a tiny valid foreground tap paint over a majority-sky
    // footprint. Preserve the closest invalid/sky source sample in that case.
    if(best>=0&&bestSupport<0.5f&&invalidSupport>bestSupport) {
        int skyTap=-1;float skyWeight=-1.f;
        [unroll] for(int k=0;k<4;++k)
            if(z[k]<=0.f&&weight[k]>skyWeight){skyTap=k;skyWeight=weight[k];}
        if(skyTap>=0)return raw[skyTap];
    }
    if(best<0) {
        int nearest=0;
        [unroll] for(int k=1;k<4;++k)if(weight[k]>weight[nearest])nearest=k;
        return raw[nearest];
    }
    float sum=0.f,rawSum=0.f;
    const float tolerance=EdgeTolerances.x+EdgeTolerances.y*bestZ;
    [unroll] for(int k=0;k<4;++k) {
        if(z[k]>0.f&&abs(z[k]-bestZ)<=tolerance) {sum+=weight[k];rawSum+=weight[k]*raw[k];}
    }
    const float interpolatedRaw=rawSum/max(sum,1.e-7f);
    selectedZ=ForwardZ(interpolatedRaw,CurrentRangeJitter.xy,CurrentProjection);
    return interpolatedRaw;
}

// A previous foreground endpoint may be retained at a current edge only
// while the current jittered source footprint still contains that same
// foreground surface. Return the current-frame device-depth endpoint; never
// blend it with incompatible current background depth.
bool CurrentForegroundEndpoint(int2 pixel,int2 size,float historyZ,float currentZ,
                               out float endpointRaw,out float support) {
    endpointRaw=0.f;support=0.f;
    const int2 lo=ActiveMin(size,ActiveRect),hi=ActiveMax(size,ActiveRect);
    const float2 sampleCoord=float2(pixel)+CurrentRangeJitter.zw;
    const int2 base=int2(floor(sampleCoord));
    const float2 f=frac(sampleCoord);
    const int2 tapOffset[4]={int2(0,0),int2(1,0),int2(0,1),int2(1,1)};
    const float weights[4]={(1.f-f.x)*(1.f-f.y),f.x*(1.f-f.y),
                             (1.f-f.x)*f.y,f.x*f.y};
    float rawSum=0.f;
    const float sameSurfaceTolerance=EdgeTolerances.x+EdgeTolerances.y*historyZ;
    [unroll] for(int k=0;k<4;++k) {
        const int2 p=clamp(base+tapOffset[k],lo,hi);
        const float raw=CurrentDepth.Load(int3(p,0));
        const float z=ForwardZ(raw,CurrentRangeJitter.xy,CurrentProjection);
        if(z<=0.f||abs(z-historyZ)>sameSurfaceTolerance)continue;
        const float nearerTolerance=EdgeTolerances.x+EdgeTolerances.y*z;
        if(z+nearerTolerance>=currentZ)continue;
        support+=weights[k];rawSum+=weights[k]*raw;
    }
    if(support<=1.e-7f)return false;
    endpointRaw=rawSum/support;
    return true;
}

float TemporalBlend(int2 pixel, float currentRaw, float currentZ, int2 size,
                    out float appliedWeight,out bool edgeReused) {
    appliedWeight=0.f;edgeReused=false;
    if(PreviousRangeWeight.w<0.5f||PreviousRangeWeight.z<=0.f||currentZ<=0.f)return currentRaw;
    float effectiveHistoryWeight=saturate(min(PreviousRangeWeight.z,0.9f));
    // Production config supplies the near-field cutoff in EdgeTolerances.w.
    // Hands and other close moving objects follow the current frame directly.
    if(EdgeTolerances.w>0.f)
        effectiveHistoryWeight*=saturate((currentZ-EdgeTolerances.w)/120.f);
    if(effectiveHistoryWeight<=0.f)return currentRaw;
    const float2 uv=PixelToUV(float2(pixel)+0.5f,ActiveRect);
    const float currentSpan=CurrentRangeJitter.y-CurrentRangeJitter.x;
    if(abs(currentSpan)<1.e-7f)return currentRaw;
    const float currentD=(currentRaw-CurrentRangeJitter.x)/currentSpan;
    const float4 currentEyeH=mul(CurrentEyeFromClip,float4(ClipXY(uv),currentD,1.f));
    if(!all(isfinite(currentEyeH))||abs(currentEyeH.w)<1.e-8f)return currentRaw;
    const float3 currentEye=currentEyeH.xyz/currentEyeH.w;
    const float4 previousClip=mul(PreviousClipFromCurrentEye,float4(currentEye,1.f));
    if(!all(isfinite(previousClip))||previousClip.w<=1.e-7f)return currentRaw;
    const float2 previousUV=float2(.5f+.5f*previousClip.x/previousClip.w,
                                  .5f-.5f*previousClip.y/previousClip.w);
    if(any(previousUV<0.f)||any(previousUV>1.f))return currentRaw;
    const float2 previousCoord=PreviousRect.xy+previousUV*PreviousRect.zw-0.5f;
    const int2 origin=int2(floor(previousCoord));
    const float2 fraction=frac(previousCoord);
    const int2 lo=ActiveMin(size,PreviousRect),hi=ActiveMax(size,PreviousRect);
    const int2 tapOffset[4]={int2(0,0),int2(1,0),int2(0,1),int2(1,1)};
    const float weights[4]={(1.f-fraction.x)*(1.f-fraction.y),fraction.x*(1.f-fraction.y),
                             (1.f-fraction.x)*fraction.y,fraction.x*fraction.y};
    float support=0.f,zsum=0.f,edgeHistorySupport=0.f,edgeScore=0.f,edgeRaw=0.f;
    const float tolerance=EdgeTolerances.x+EdgeTolerances.y*currentZ;
    const float minEdgeSupport=0.5f-0.25f*saturate(effectiveHistoryWeight/0.9f);
    [unroll] for(int k=0;k<4;++k) {
        const int2 p=origin+tapOffset[k];
        if(any(p<lo)||any(p>hi))continue;
        const float historyRaw=PreviousDepth.Load(int3(p,0));
        const float2 previousRange=PreviousRangeWeight.xy;
        const float previousSpan=previousRange.y-previousRange.x;
        if(abs(previousSpan)<1.e-7f||ForwardZ(historyRaw,previousRange,PreviousProjection)<=0.f)continue;
        const float previousD=(historyRaw-previousRange.x)/previousSpan;
        const float2 tapUV=PixelToUV(float2(p)+0.5f,PreviousRect);
        const float4 previousEyeH=mul(PreviousEyeFromClip,float4(ClipXY(tapUV),previousD,1.f));
        if(!all(isfinite(previousEyeH))||abs(previousEyeH.w)<1.e-8f)continue;
        const float3 previousEye=previousEyeH.xyz/previousEyeH.w;
        const float4 currentHistoryH=mul(CurrentEyeFromPreviousEye,float4(previousEye,1.f));
        if(!all(isfinite(currentHistoryH))||abs(currentHistoryH.w)<1.e-8f)continue;
        const float3 historyInCurrent=currentHistoryH.xyz/currentHistoryH.w;
        const float4 currentClip=mul(CurrentClipFromCurrentEye,float4(historyInCurrent,1.f));
        if(!all(isfinite(currentClip))||currentClip.w<=1.e-7f)continue;
        const float2 projectedUV=float2(.5f+.5f*currentClip.x/currentClip.w,
                                       .5f-.5f*currentClip.y/currentClip.w);
        const float2 projectedPixel=ActiveRect.xy+projectedUV*ActiveRect.zw-0.5f;
        if(length(projectedPixel-float2(pixel))>EdgeTolerances.z)continue;
        const float nearerTolerance=EdgeTolerances.x+EdgeTolerances.y*historyInCurrent.z;
        if(historyInCurrent.z+nearerTolerance<currentZ) {
            if(EdgeTolerances.w>0.f&&historyInCurrent.z<=EdgeTolerances.w)continue;
            float currentEndpoint,currentForegroundSupport;
            if(CurrentForegroundEndpoint(pixel,size,historyInCurrent.z,currentZ,
                    currentEndpoint,currentForegroundSupport)&&currentForegroundSupport>=minEdgeSupport) {
                edgeHistorySupport+=weights[k];
                const float score=weights[k]*currentForegroundSupport;
                if(score>edgeScore) {edgeScore=score;edgeRaw=currentEndpoint;}
            }
            continue;
        }
        // Old background never overrides a nearer surface that appeared now.
        if(historyInCurrent.z>currentZ+tolerance)continue;
        if(abs(historyInCurrent.z-currentZ)>tolerance)continue;
        support+=weights[k];zsum+=weights[k]*historyInCurrent.z;
    }
    // Keep only a current-supported foreground endpoint. This is bounded edge
    // hysteresis, not a cross-surface depth average.
    if(edgeScore>0.f&&edgeHistorySupport>=0.5f) {
        edgeReused=true;appliedWeight=effectiveHistoryWeight;return edgeRaw;
    }
    // Require meaningful same-surface coverage before reusing history.
    if(support<0.15f)return currentRaw;
    const float historyZ=zsum/support;
    const float weight=effectiveHistoryWeight*saturate(support);
    appliedWeight=weight;
    const float blendedZ=lerp(currentZ,historyZ,weight);
    return RawFromForwardZ(blendedZ,CurrentRangeJitter.xy,CurrentProjection);
}


// CI81 keeps two surface hypotheses in addition to the selected guide. Their
// device-depth endpoints stay separate; no foreground/background depth average.
// State: foregroundRaw, backgroundRaw, foregroundConfidence, unsupportedAge.
void CurrentLayers(int2 pixel,int2 size,out float fgRaw,out float fgZ,
                   out float bgRaw,out float bgZ,out float support) {
    fgRaw=bgRaw=-1.f;fgZ=bgZ=-1.f;support=0.f;
    const int2 lo=ActiveMin(size,ActiveRect),hi=ActiveMax(size,ActiveRect);
    const float2 q=float2(pixel)+CurrentRangeJitter.zw;
    const int2 first=int2(floor(q));const float2 f=frac(q);
    const int2 offsets[4]={int2(0,0),int2(1,0),int2(0,1),int2(1,1)};
    const float weights[4]={(1-f.x)*(1-f.y),f.x*(1-f.y),(1-f.x)*f.y,f.x*f.y};
    float raw[4],z[4];
    [unroll] for(int k=0;k<4;++k) {
        raw[k]=CurrentDepth.Load(int3(clamp(first+offsets[k],lo,hi),0));
        z[k]=ForwardZ(raw[k],CurrentRangeJitter.xy,CurrentProjection);
        if(weights[k]>.0001f && z[k]>0.f) {
            if(fgZ<=0.f||z[k]<fgZ){fgZ=z[k];fgRaw=raw[k];}
            if(bgZ<=0.f||z[k]>bgZ){bgZ=z[k];bgRaw=raw[k];}
        }
    }
    if(fgZ<=0.f)return;
    float fgSum=0.f,bgSum=0.f,fgDepthSum=0.f,bgDepthSum=0.f;
    const float tolerance=EdgeTolerances.x+EdgeTolerances.y*fgZ;
    [unroll] for(int k=0;k<4;++k) {
        if(z[k]>0.f && abs(z[k]-fgZ)<=tolerance) {
            fgSum+=weights[k];fgDepthSum+=weights[k]*z[k];
        } else if(z[k]>0.f) {bgSum+=weights[k];bgDepthSum+=weights[k]*z[k];}
    }
    support=fgSum;fgZ=fgDepthSum/max(fgSum,1.e-7f);
    fgRaw=RawFromForwardZ(fgZ,CurrentRangeJitter.xy,CurrentProjection);
    if(bgSum>1.e-7f) {
        bgZ=bgDepthSum/bgSum;bgRaw=RawFromForwardZ(bgZ,CurrentRangeJitter.xy,CurrentProjection);
    } else {bgZ=-1.f;bgRaw=-1.f;} // no distinct measured background
}
bool ReprojectEndpoint(int2 priorPixel,float raw,int2 pixel,out float currentZ,out float error) {
    currentZ=-1.f;error=1.e30f;
    if(ForwardZ(raw,PreviousRangeWeight.xy,PreviousProjection)<=0.f)return false;
    const float previousD=(raw-PreviousRangeWeight.x)/(PreviousRangeWeight.y-PreviousRangeWeight.x);
    const float2 oldUV=PixelToUV(float2(priorPixel)+.5f,PreviousRect);
    const float4 oldH=mul(PreviousEyeFromClip,float4(ClipXY(oldUV),previousD,1.f));
    if(!all(isfinite(oldH))||abs(oldH.w)<1.e-8f)return false;
    const float4 currentH=mul(CurrentEyeFromPreviousEye,float4(oldH.xyz/oldH.w,1.f));
    if(!all(isfinite(currentH))||abs(currentH.w)<1.e-8f)return false;
    const float3 currentEye=currentH.xyz/currentH.w;
    const float4 clip=mul(CurrentClipFromCurrentEye,float4(currentEye,1.f));
    if(!all(isfinite(clip))||clip.w<=1.e-7f||currentEye.z<=0.f)return false;
    const float2 uv=float2(.5f+.5f*clip.x/clip.w,.5f-.5f*clip.y/clip.w);
    error=length(ActiveRect.xy+uv*ActiveRect.zw-.5f-float2(pixel));
    currentZ=currentEye.z;
    return error<=PersistenceConfig.w;
}
float PersistentDepth(int2 pixel,int2 size,float currentRaw,float currentZ,
                      out float4 nextState,out float appliedWeight,out bool retainedEdge) {
    appliedWeight=0.f;retainedEdge=false;
    float fgRaw,fgZ,bgRaw,bgZ,currentSupport;
    CurrentLayers(pixel,size,fgRaw,fgZ,bgRaw,bgZ,currentSupport);
    const float threshold=clamp(PersistenceConfig.z,.05f,.9f);
    nextState=float4(fgRaw,bgRaw,currentSupport>=threshold?1.f:0.f,0.f);
    const float weight=clamp(PreviousRangeWeight.z,0.f,.99f);
    if(PreviousRangeWeight.w<.5f||weight<=0.f)return currentRaw;

    // Use the nearest current measured hypothesis as the reprojection anchor.
    // Sky uses a far ray. Camera motion is compensated; moving objects may
    // leave the explicitly accepted bounded trail.
    const float anchorZ=fgZ>0.f?fgZ:(currentZ>0.f?currentZ:1.e6f);
    const float anchorRaw=RawFromForwardZ(anchorZ,CurrentRangeJitter.xy,CurrentProjection);
    const float anchorD=(anchorRaw-CurrentRangeJitter.x)/(CurrentRangeJitter.y-CurrentRangeJitter.x);
    const float2 uv=PixelToUV(float2(pixel)+.5f,ActiveRect);
    const float4 eyeH=mul(CurrentEyeFromClip,float4(ClipXY(uv),anchorD,1.f));
    if(!all(isfinite(eyeH))||abs(eyeH.w)<1.e-8f)return currentRaw;
    const float4 previousClip=mul(PreviousClipFromCurrentEye,float4(eyeH.xyz/eyeH.w,1.f));
    if(!all(isfinite(previousClip))||previousClip.w<=1.e-7f)return currentRaw;
    const float2 oldUV=float2(.5f+.5f*previousClip.x/previousClip.w,.5f-.5f*previousClip.y/previousClip.w);
    if(any(oldUV<0.f)||any(oldUV>1.f))return currentRaw;
    const float2 coord=PreviousRect.xy+oldUV*PreviousRect.zw-.5f;
    const int2 first=int2(floor(coord));
    const int2 lo=ActiveMin(size,PreviousRect),hi=ActiveMax(size,PreviousRect);
    const int2 offsets[4]={int2(0,0),int2(1,0),int2(0,1),int2(1,1)};
    float oldZ=-1.f,oldBackgroundZ=-1.f,confidence=0.f,age=0.f,bestScore=-1.e30f;
    [unroll] for(int k=0;k<4;++k) {
        const int2 tap=first+offsets[k];if(any(tap<lo)||any(tap>hi))continue;
        float4 state=PreviousState.Load(int3(tap,0));
        // Bootstrap from a selected guide when enabling the stronger mode;
        // never let uninitialized state create a foreground endpoint.
        if(state.z<=0.f || ForwardZ(state.x,PreviousRangeWeight.xy,PreviousProjection)<=0.f) {
            state=float4(PreviousDepth.Load(int3(tap,0)),-1.f,1.f,0.f);
        }
        float z,error;if(!ReprojectEndpoint(tap,state.x,pixel,z,error))continue;
        const float sameTolerance=EdgeTolerances.x+EdgeTolerances.y*max(z,fgZ);
        const bool same=fgZ>0.f&&abs(z-fgZ)<=sameTolerance;
        // Nearest reprojected owner wins over a farther matching background.
        // Otherwise a one-pixel stem is replaced by its neighbour on dropout.
        const float score=saturate(state.z)-4.f*error+(same?.05f:0.f);
        if(score>bestScore) {
            bestScore=score;oldZ=z;confidence=saturate(state.z);age=max(0.f,state.w);
            float bgError;
            if(!ReprojectEndpoint(tap,state.y,pixel,oldBackgroundZ,bgError))oldBackgroundZ=-1.f;
        }
    }
    if(oldZ<=0.f)return currentRaw;
    const float tolerance=EdgeTolerances.x+EdgeTolerances.y*oldZ;
    // A new closer occluder wins immediately. Old background must not paint
    // through a newly arrived hand/character even at maximum persistence.
    if(fgZ>0.f && fgZ+tolerance<oldZ && currentSupport>=threshold) {
        nextState=float4(fgRaw,bgRaw,1.f,0.f);return fgRaw;
    }
    if(fgZ>0.f && abs(fgZ-oldZ)<=tolerance && currentSupport>.001f) {
        const float stableZ=lerp(fgZ,oldZ,weight);
        const float stableRaw=RawFromForwardZ(stableZ,CurrentRangeJitter.xy,CurrentProjection);
        if(bgZ>0.f && oldBackgroundZ>0.f &&
           abs(bgZ-oldBackgroundZ)<=EdgeTolerances.x+EdgeTolerances.y*bgZ)
            bgRaw=RawFromForwardZ(lerp(bgZ,oldBackgroundZ,weight),CurrentRangeJitter.xy,CurrentProjection);
        else if(bgZ<=0.f && oldBackgroundZ>0.f)
            bgRaw=RawFromForwardZ(oldBackgroundZ,CurrentRangeJitter.xy,CurrentProjection);
        const float nextConfidence=min(1.f,confidence+.25f*currentSupport);
        nextState=float4(stableRaw,bgRaw,nextConfidence,0.f);
        if(currentSupport>=threshold || confidence>=threshold ||
           (currentZ>0.f&&abs(currentZ-fgZ)<=tolerance)) {
            appliedWeight=weight;return stableRaw;
        }
        return currentRaw;
    }
    const float nextAge=age+1.f;
    const float hold=clamp(round(PersistenceConfig.y),0.f,30.f);
    // Unlike CI80, missing current support is allowed for a bounded number of
    // frames. Foreground ownership survives a brief aliasing/depth dropout.
    if(hold>0.f && nextAge<=hold && confidence>=threshold &&
       (fgZ<=0.f || oldZ+tolerance<fgZ)) {
        const float oldRaw=RawFromForwardZ(oldZ,CurrentRangeJitter.xy,CurrentProjection);
        const float newBackground=fgZ>0.f?fgRaw:bgRaw;
        nextState=float4(oldRaw,newBackground,confidence*(hold/(hold+1.f)),nextAge);
        appliedWeight=weight;retainedEdge=true;return oldRaw;
    }
    // Release once evidence has remained absent for the configured window.
    // Do not average the released foreground into the visible background.
    if(fgZ>0.f&&currentSupport>=threshold)return fgRaw;
    return currentRaw;
}
struct StabilizedOutput {
    float depth : SV_TARGET0;
    float4 state : SV_TARGET1;
};

StabilizedOutput PSStabilizeDepth(VertexOut i) {
    uint width,height;CurrentDepth.GetDimensions(width,height);
    const int2 size=int2(width,height);
    const int2 pixel=int2(i.pos.xy);
    float currentZ;
    const float currentRaw=StabilizeSpatial(pixel,size,currentZ);
    float appliedWeight=0.f;bool edgeReused=false;
    float result=currentRaw;float4 state=0.f;
    if(PersistenceConfig.x>.5f && all(pixel>=ActiveMin(size,ActiveRect)) && all(pixel<=ActiveMax(size,ActiveRect))) {
        result=PersistentDepth(pixel,size,currentRaw,currentZ,state,appliedWeight,edgeReused);
    } else if(currentZ>0.f) {
        result=TemporalBlend(pixel,currentRaw,currentZ,size,appliedWeight,edgeReused);
    } else if(PreviousRangeWeight.w>.5f && PreviousRangeWeight.z>0.f &&
              all(pixel>=ActiveMin(size,ActiveRect)) && all(pixel<=ActiveMax(size,ActiveRect))) {
        // Infinite/sky samples cannot be unprojected directly. Query history
        // with a far ray, but retain ONLY a foreground endpoint also supported
        // by the CURRENT jitter footprint and a valid round-trip projection.
        // A completely exposed sky pixel never inherits old foreground depth.
        const float farZ=1.e6f;
        const float farRaw=RawFromForwardZ(farZ,CurrentRangeJitter.xy,CurrentProjection);
        const float candidate=TemporalBlend(pixel,farRaw,farZ,size,appliedWeight,edgeReused);
        if(edgeReused)result=candidate;
        else appliedWeight=0.f;
    }
    // Sparse GPU measurements of actual shader decisions, not host intent.
    // One sample per 16x16 block bounds atomic work at full headset resolution.
    const uint stride=max(1u,uint(DiagnosticConfig.z));
    if(DiagnosticConfig.x>.5f && uint(pixel.x)%stride==0u && uint(pixel.y)%stride==0u &&
       all(pixel>=ActiveMin(size,ActiveRect)) && all(pixel<=ActiveMax(size,ActiveRect))) {
        const uint base=uint(DiagnosticConfig.y);uint ignored;
        HistoryCounters.InterlockedAdd(base,1u,ignored);
        if(currentZ>0.f)HistoryCounters.InterlockedAdd(base+4u,1u,ignored);
        if((currentZ>max(0.f,EdgeTolerances.w) || edgeReused) && PreviousRangeWeight.w>.5f &&
           PreviousRangeWeight.z>0.f)HistoryCounters.InterlockedAdd(base+8u,1u,ignored);
        if(appliedWeight>0.f) {
            HistoryCounters.InterlockedAdd(base+12u,1u,ignored);
            HistoryCounters.InterlockedAdd(base+20u,uint(round(appliedWeight*1000.f)),ignored);
        }
        if(edgeReused)HistoryCounters.InterlockedAdd(base+16u,1u,ignored);
    }
    StabilizedOutput output;output.depth=result;output.state=state;return output;
}

// CI77 depth-grid stabilization. Spatially undo NGX depth jitter onto the
// canonical per-eye pixel grid, then conservatively reuse reprojected history.
// The input and output keep device-depth encoding and the source allocation.
Texture2D<float> CurrentDepth : register(t0);
Texture2D<float> PreviousDepth : register(t1);

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

float TemporalBlend(int2 pixel, float currentRaw, float currentZ, int2 size) {
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
    if(edgeScore>0.f&&edgeHistorySupport>=0.5f)return edgeRaw;
    // Require meaningful same-surface coverage before reusing history.
    if(support<0.15f)return currentRaw;
    const float historyZ=zsum/support;
    const float weight=effectiveHistoryWeight*saturate(support);
    const float blendedZ=lerp(currentZ,historyZ,weight);
    return RawFromForwardZ(blendedZ,CurrentRangeJitter.xy,CurrentProjection);
}

float PSStabilizeDepth(VertexOut i) : SV_TARGET0 {
    uint width,height;CurrentDepth.GetDimensions(width,height);
    const int2 size=int2(width,height);
    const int2 pixel=int2(i.pos.xy);
    float currentZ;
    const float currentRaw=StabilizeSpatial(pixel,size,currentZ);
    if(currentZ<=0.f)return currentRaw;
    return TemporalBlend(pixel,currentRaw,currentZ,size);
}

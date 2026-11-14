// Raw fine depth from the previous accepted transaction. Both frames use
// their own crop, independent NGX jitter, and frozen camera.
Texture2D<float> M6PreviousDepth : register(t9);

float M6StabilizeFineEdge(float2 local, float fineNear, float fineFar) {
    const float disparity=max(abs(M1Eye.x),abs(M1Eye.y))*M23Wide.z;
    [branch] if (M6PreviousJitter.z < .5 || (fineNear-fineFar)*disparity < .16)
        return fineNear;

    const float2 fullUv=lerp(M2Crop.xy,M2Crop.zw,local);
    const float4 p=M6CurrentProjection;
    const float4 ray=float4((2.*fullUv.x-1.-p.y)/p.x,
                            (1.-2.*fullUv.y-p.w)/p.z, 1., fineNear);
    const float3 prev=float3(dot(M6View[0],ray),dot(M6View[1],ray),dot(M6View[2],ray));
    if (prev.z <= .01) return fineNear;
    const float4 pp=M6PreviousProjection;
    const float2 previousUv=float2(.5+.5*(pp.x*prev.x/prev.z+pp.y),
                                    .5-.5*(pp.z*prev.y/prev.z+pp.w));
    const float2 previousSize=float2(M6PreviousRect.zw);
    const float2 uv=(previousUv-M6PreviousCrop.xy)/(M6PreviousCrop.zw-M6PreviousCrop.xy);
    const float2 cell=(uv+M6PreviousJitter.xy)*previousSize-.5;
    if (any(cell < 0.) || any(cell >= previousSize-1.)) return fineNear;

    const int2 at=int2(floor(cell))+int2(M6PreviousRect.xy);
    const float expected=fineNear/prev.z;
    float nearest=expected;
    float error=1.e9;
    [unroll] for (int y=0; y<2; ++y) {
        [unroll] for (int x=0; x<2; ++x) {
            const float z=M6PreviousDepth.Load(int3(at+int2(x,y),0));
            const float d=(M1Depth.z*z-M1Depth.x)/M1Depth.y;
            const float e=abs(d-expected);
            if (isfinite(d) && d>=0. && e<error) {
                nearest=d;
                error=e;
            }
        }
    }
    // Reject the other side of an occlusion, then cap history's influence
    // in screen pixels so it cannot drag moving silhouettes.
    if (error*disparity > .65) return fineNear;
    const float rotZ=prev.z-M6View[2].w*fineNear;
    const float denominator=1.-nearest*M6View[2].w;
    if (denominator <= .01 || rotZ <= .01) return fineNear;
    const float candidate=nearest*rotZ/denominator;
    const float limit=.32/max(disparity,1.e-5);
    return max(0.,fineNear+.45*clamp(candidate-fineNear,-limit,limit));
}

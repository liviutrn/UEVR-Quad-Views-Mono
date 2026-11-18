// Goal D switch 4 "halo at background depth": raw (knee'd, no envelope) fovea
// depth from slice 2 of the 4096 field, same cell math as M1ReadConditionedEye.
float GDReadRawField(float2 uv) {
    const float2 local=(uv-M2Crop.xy)/(M2Crop.zw-M2Crop.xy);
    const float2 cell=clamp(local*float2(M4Grid.xy),float2(.5,.5),float2(M4Grid.xy)-.5);
    return M4FoveaSoft.SampleLevel(LinearClamp,float3(cell/float2(M4Grid.zw),2.0),0);
}
// Fine conditioned depth of the same 4096 field (no coarse grid) and the
// coarse->fine crop blend weight M1ReadConditionedEye uses at this position.
float GDReadFineEye(float2 uv, uint eye, out float blend) {
    const float2 local=(uv-M2Crop.xy)/(M2Crop.zw-M2Crop.xy);
    const float edge=min(min(local.x,local.y),min(1.0-local.x,1.0-local.y));
    const float t=saturate(edge/max(M4Flags.w,.0001));
    blend=(all(local>0.0) && all(local<1.0)) ? t*t*(3.0-2.0*t) : 0.0;
    const float2 cell=clamp(local*float2(M4Grid.xy),float2(.5,.5),float2(M4Grid.xy)-.5);
    return M4FoveaSoft.SampleLevel(LinearClamp,float3(cell/float2(M4Grid.zw),float(eye)),0);
}
// ---- GOALD_RASTER_BODY
        // ---- Goal D switch 3 "true depth" (Claude, 2026-11-18): inside the fovea
        // the 4096 field has NO ramp, so near objects keep their exact edge and the
        // background next to them keeps its own depth. The residual can then have
        // several roots (the weapon edge AND the background behind it): scan the whole
        // bracket and take the front-most (largest inverse depth) forward-facing root,
        // i.e. the near object covers what is behind it. Disocclusion gaps are left
        // to the fill (switch 4).
        [branch] if((M6PreviousRect.y&16u)!=0u && M4Flags.x>.5 &&
                    all(base>M2Crop.xy) && all(base<M2Crop.zw)) {
            const float gdLo=min(base.x,base.x+delta), gdHi=max(base.x,base.x+delta);
            const float gdSpan=(gdHi-gdLo)/24.0;
            float gdPrevU=gdLo;
            float gdPrevD=M1ReadConditionedEye(float2(gdLo,base.y),eye);
            float gdPrevR=base.x+k*gdPrevD-gdLo;
            float gdBest=-1.0, gdA=gdLo, gdB=gdHi;
            [loop] for(uint gdI=1u;gdI<=24u;++gdI) {
                const float u=gdLo+gdSpan*float(gdI);
                const float d=M1ReadConditionedEye(float2(u,base.y),eye);
                const float r=base.x+k*d-u;
                [branch] if(gdPrevR>0.0 && r<=0.0) {
                    // Rank by the depth AT the root (3 bisections), not at the scan ends.
                    float ca=gdPrevU, cb=u;
                    [unroll] for(uint gdK=0u;gdK<3u;++gdK) {
                        const float m=.5*(ca+cb);
                        if(base.x+k*M1ReadConditionedEye(float2(m,base.y),eye)-m>0.0) ca=m; else cb=m;
                    }
                    const float cd=M1ReadConditionedEye(float2(.5*(ca+cb),base.y),eye);
                    if(cd>gdBest) { gdBest=cd; gdA=ca; gdB=cb; }
                }
                gdPrevU=u; gdPrevD=d; gdPrevR=r;
            }
            [branch] if(gdBest>=0.0) {
                [unroll] for(uint gdJ=0u;gdJ<4u;++gdJ) {
                    const float m=.5*(gdA+gdB);
                    if(base.x+k*M1ReadConditionedEye(float2(m,base.y),eye)-m>0.0) gdA=m; else gdB=m;
                }
                uv.x=.5*(gdA+gdB);
            }
        }
        // ---- Goal D switch 4 "halo at background depth" (flag 32, Claude 2026-11-18,
        // review fixes 11-18 pm). EXPERIMENTAL: the final lerp has NO fold guarantee
        // (ChatGPT reviews #368); not a headset A/B candidate until redesigned.
        // Keep the soft root but, where the FINE conditioned depth is lifted above the
        // FINE raw depth (same field; K1: no coarse/fine mix in the test, faded out
        // with the crop blend), move the source towards the root the background has
        // at its own raw depth. Every failure keeps the soft root: fixed point not
        // converged (depth step, no background root), background not found inside
        // the fine crop, mirror lands on a near object.
        [branch] if((M6PreviousRect.y&32u)!=0u && M4Flags.x>.5 &&
                    uv.x>M2Crop.x && uv.x<M2Crop.z && base.y>M2Crop.y && base.y<M2Crop.w) {
            const float hbRoot=uv.x;
            float hbBlend;
            const float hbF=GDReadFineEye(float2(hbRoot,base.y),eye,hbBlend);
            const float hbR=GDReadRawField(float2(hbRoot,base.y));
            const float hbW=hbBlend*smoothstep(.02,.15,(hbF-hbR)/max(hbF,1.e-6));
            [branch] if(hbW>0.0) {
                const float hbDu=(M2Crop.z-M2Crop.x)/float(max(M4Grid.x,1u));
                float hbU=hbRoot, hbPrev=hbRoot;
                [unroll] for(uint hbI=0u;hbI<4u;++hbI) {
                    hbPrev=hbU;
                    hbU=base.x+k*GDReadRawField(float2(hbU,base.y));
                }
                bool hbOk=abs(hbU-hbPrev)<=hbDu && hbU>M2Crop.x && hbU<M2Crop.z;
                const float hbRaw=GDReadRawField(float2(hbU,base.y));
                [branch] if(hbOk && hbRaw>1.1*hbR) {
                    // On the near object: walk to the side whose raw depth is lower.
                    const float hbL=GDReadRawField(float2(hbU-4.0*hbDu,base.y));
                    const float hbH=GDReadRawField(float2(hbU+4.0*hbDu,base.y));
                    const float hbDir=hbH<=hbL ? 1.0 : -1.0;
                    float hbB=hbU, hbDb=hbRaw;
                    bool hbFound=false;
                    [loop] for(uint hbJ=0u;hbJ<32u;++hbJ) {
                        const float un=hbB+hbDir*hbDu;
                        if(un<=M2Crop.x || un>=M2Crop.z) break; // outside the fine crop: no background data
                        const float dn=GDReadRawField(float2(un,base.y));
                        hbFound=dn<=1.1*hbR && abs(k*(dn-hbDb))<.5*hbDu;
                        hbB=un; hbDb=dn;
                        if(hbFound) break;
                    }
                    const float hbM=2.0*hbB-hbU;
                    hbOk=hbFound && hbM>M2Crop.x && hbM<M2Crop.z &&
                         GDReadRawField(float2(hbM,base.y))<=1.1*hbR;
                    hbU=hbM;
                }
                [branch] if(hbOk) uv.x=clamp(lerp(hbRoot,hbU,hbW),0.0,1.0);
            }
        }

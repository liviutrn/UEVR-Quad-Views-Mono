// Goal D switch 4 "halo at background depth": raw (knee'd, no envelope) fovea
// depth from slice 2 of the 4096 field, same cell math as M1ReadConditionedEye.
float GDReadRawField(float2 uv) {
    const float2 local=(uv-M2Crop.xy)/(M2Crop.zw-M2Crop.xy);
    const float2 cell=clamp(local*float2(M4Grid.xy),float2(.5,.5),float2(M4Grid.xy)-.5);
    return M4FoveaSoft.SampleLevel(LinearClamp,float3(cell/float2(M4Grid.zw),2.0),0);
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
                if(gdPrevR>0.0 && r<=0.0 && max(d,gdPrevD)>gdBest) {
                    gdBest=max(d,gdPrevD); gdA=gdPrevU; gdB=u;
                }
                gdPrevU=u; gdPrevD=d; gdPrevR=r;
            }
            [branch] if(gdBest>=0.0) {
                [unroll] for(uint gdJ=0u;gdJ<6u;++gdJ) {
                    const float m=.5*(gdA+gdB);
                    if(base.x+k*M1ReadConditionedEye(float2(m,base.y),eye)-m>0.0) gdA=m; else gdB=m;
                }
                uv.x=.5*(gdA+gdB);
            }
        }
        // ---- Goal D switch 4 "halo at background depth" (flag 32, Claude 2026-11-18).
        // The soft V2 ramp lifts the background next to a near object to (almost)
        // the near object's depth, so the halo band moves with the weapon. Keep the
        // soft root (same look, same content source) but, where the conditioned
        // depth is clearly lifted above the raw depth, move the source towards the
        // root the background would have at its own (raw) depth. Continuous weight,
        // no binary labels. If that background root lands on the near object, mirror
        // it back to the background side (like M3FillHole, on the raw slice).
        [branch] if((M6PreviousRect.y&32u)!=0u && M4Flags.x>.5 &&
                    uv.x>M2Crop.x && uv.x<M2Crop.z && base.y>M2Crop.y && base.y<M2Crop.w) {
            const float hbRoot=uv.x;
            const float hbD=M1ReadConditionedEye(float2(hbRoot,base.y),eye);
            const float hbR=GDReadRawField(float2(hbRoot,base.y));
            const float hbW=smoothstep(.02,.15,(hbD-hbR)/max(hbD,1.e-6));
            [branch] if(hbW>0.0) {
                float hbU=hbRoot;
                [unroll] for(uint hbI=0u;hbI<3u;++hbI)
                    hbU=base.x+k*GDReadRawField(float2(hbU,base.y));
                const float hbRaw=GDReadRawField(float2(hbU,base.y));
                [branch] if(hbRaw>1.1*hbR) {
                    const float hbDu=(M2Crop.z-M2Crop.x)/float(max(M4Grid.x,1u));
                    const float hbDir=hbRoot>=hbU ? 1.0 : -1.0; // back towards the background
                    float hbB=hbU, hbDb=hbRaw;
                    [loop] for(uint hbJ=0u;hbJ<32u;++hbJ) {
                        const float un=hbB+hbDir*hbDu;
                        const float dn=GDReadRawField(float2(un,base.y));
                        const bool flat=dn<=1.1*hbR && abs(k*(dn-hbDb))<.5*hbDu;
                        hbB=un; hbDb=dn;
                        if(flat) break;
                    }
                    float hbM=2.0*hbB-hbU;
                    if(GDReadRawField(float2(hbM,base.y))>1.1*hbR) hbM=hbB;
                    hbU=hbM;
                }
                uv.x=clamp(lerp(hbRoot,hbU,hbW),0.0,1.0);
            }
        }

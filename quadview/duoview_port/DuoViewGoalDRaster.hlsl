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

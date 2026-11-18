// ---- Goal D (Claude, 2026-11-18). All kernels here are compiled into separate,
// appended m4g_* DXBC; the Off (1024) kernels and their DXBC are unchanged.
//
// Switch 1: M4 fovea depth field up to 4096 texels per axis, so 1625x1435 fine
// NGX depth is conditioned ~1:1 instead of being fitted into 1024x904.
// Production Stereo V2 path only (M8 V2 policy, no per-eye M3 edges): identical
// seed (2x2 near-max at the jittered fine position, knee/cap) and identical
// constant-penalty envelope on mapped depth. Penalties are per field texel and
// already scale with 1/M4Grid, so the ramp width in screen terms is unchanged.
// Groupshared: one 16 KiB row; each of 512 lanes stages its <=8 values in
// registers (two 4096 rows would take the whole 32 KiB D3D12 limit).
// The 4096 field has two slices (one per eye). Without switch 3 both slices
// hold the same depth.
//
// Goal D controls (CPU fills them only while the 4096 path is active; the M6
// slots are otherwise unused under Stereo V2 and stay zero):
//   M6PreviousRect.x   history parity (slice pair written this frame)
//   M6PreviousRect.y   bits: 1 history valid, 2 history on, 4 one-sided ramp, 8 tight ramp, 16 true depth (no ramp),
//                      32 halo at background depth (slice 2 = raw knee'd seed, no envelope; read by the raster)
//   M6PreviousJitter.x fine jitter sign (< 0 flips the fine jitter direction)
//   M6PreviousJitter.y K: history not re-confirmed for K frames is dropped
//   M6PreviousJitter.z camera-locked range: inverse depth >= this follows the camera
//   M6PreviousJitter.w accept radius in field texels
//   M6View/M6CurrentProjection/M6PreviousProjection/M6PreviousCrop: reprojection
groupshared float GDRow[4096];

#define GD_LANES 512u
#define GD_TILES 8u

float2 GDFineJitter() { return M2FineJitter()*(M6PreviousJitter.x<0.0 ? -1.0 : 1.0); }
uint GDFlags() { return M6PreviousRect.y; }

// Raw near-max seed (inverse engine depth) of one field texel.
float GDSeedRaw(uint2 p) {
    const float2 dimension=float2(M2FoveaRect.zw);
    const float2 local=(float2(p)+.5)/float2(M4Grid.xy);
    const float2 jit=clamp(local+GDFineJitter(),.5/dimension,1.0-.5/dimension);
    const int2 f0=int2(floor(jit*dimension-.5));
    float fine=0.0;
    [unroll] for(int fy=0;fy<=1;++fy)
        [unroll] for(int fx=0;fx<=1;++fx)
            fine=max(fine,DecodeM2Depth(f0+int2(fx,fy)));
    return fine;
}

float GDKneeSeed(float fine) {
    const float knee=M1Depth.w;
    float nearDepth=fine;
    if(knee>0.0 && nearDepth>knee) {
        const float excess=nearDepth-knee;
        nearDepth=knee+excess/(1.0+excess/knee);
    }
    return knee>0.0 ? nearDepth : min(nearDepth,M1Filter.y);
}
float GDMapSeed(float fine) { return M8V2Map(GDKneeSeed(fine)); }

// Horizontal envelope of one field row. fromField: the seed was already
// written to slice 0 by the history pass (switch 2). Switch 3 (one-sided):
// per eye, keep the ramp only on the side the pull warp needs for a unique
// root (k*d' > 0, the M3 fold side) and keep the raw step on the other side.
// Tight (flag 8, with one-sided): that ramp is the narrowest the warp allows
// without folding (96% of the fold limit, on true inverse depth, no V2 map),
// so background next to near objects keeps (almost) its own depth.
void GDHorizontal(uint row, uint lane, bool fromField) {
    const uint w=M4Grid.x;
    // Uniform early-outs (constant-buffer or group values only).
    if(row>=M4Grid.y || w==0u || w>4096u) return;
    float seed[GD_TILES];
    [unroll] for(uint t0=0u;t0<GD_TILES;++t0) {
        const uint x=GD_LANES*t0+lane;
        seed[t0]=0.0;
        const bool tight0=(GDFlags()&12u)==12u || (GDFlags()&16u)!=0u;
        if(x<w) {
            const float raw=fromField ? M4FoveaConditioned[uint3(x,row,0u)] : GDSeedRaw(uint2(x,row));
            const float knee0=GDKneeSeed(raw);
            seed[t0]=tight0 ? knee0 : M8V2Map(knee0);
            if((GDFlags()&32u)!=0u) M4FoveaConditioned[uint3(x,row,2u)]=knee0; // switch 4: raw depth for the raster
        }
    }
    const bool oneSided=(GDFlags()&4u)!=0u;
    const bool tight=(GDFlags()&12u)==12u;
    const bool trueDepth=(GDFlags()&16u)!=0u; // switch 3 "true depth": no ramp at all (raster takes the front-most root)
    const uint eyes=oneSided ? 2u : 1u;
    const float limit=M1Depth.w>0.0 ? 2.0*M1Depth.w : M1Filter.y;
    const float pen=tight ? .96*M8SafeLimit() : min(M1Filter.x*M4Flags.y,M8SafeLimit());
    const float mappedLimit=tight ? limit : M8V2Map(limit);
    [loop] for(uint eye=0u;eye<eyes;++eye) {
        GroupMemoryBarrierWithGroupSync();
        [unroll] for(uint t1=0u;t1<GD_TILES;++t1) {
            const uint x=GD_LANES*t1+lane;
            if(x<w) GDRow[x]=seed[t1];
        }
        GroupMemoryBarrierWithGroupSync();
        const int fold=M1Eye[eye]>=0.0 ? 1 : -1;
        for(uint step=1u;!trueDepth && step<w && float(step-1u)*pen<mappedLimit;step*=2u) {
            float next[GD_TILES];
            [unroll] for(uint t=0u;t<GD_TILES;++t) {
                const uint x=GD_LANES*t+lane;
                next[t]=0.0;
                if(x<w) {
                    if(oneSided) {
                        const int xf=int(x)+fold*int(step);
                        const float side=(xf>=0 && xf<int(w)) ? GDRow[uint(xf)]-float(step)*pen : 0.0;
                        next[t]=max(GDRow[x],side);
                    } else {
                        const float left=x>=step ? GDRow[x-step]-float(step)*pen : 0.0;
                        const float right=x+step<w ? GDRow[x+step]-float(step)*pen : 0.0;
                        next[t]=max(GDRow[x],max(left,right));
                    }
                }
            }
            GroupMemoryBarrierWithGroupSync();
            [unroll] for(uint t2=0u;t2<GD_TILES;++t2) {
                const uint x=GD_LANES*t2+lane;
                if(x<w) GDRow[x]=next[t2];
            }
            GroupMemoryBarrierWithGroupSync();
        }
        [unroll] for(uint t3=0u;t3<GD_TILES;++t3) {
            const uint x=GD_LANES*t3+lane;
            if(x<w) {
                const float v=(tight || trueDepth) ? GDRow[x] : M8V2Unmap(GDRow[x]);
                M4FoveaConditioned[uint3(x,row,eye)]=v;
                if(!oneSided) M4FoveaConditioned[uint3(x,row,1u)]=v;
            }
        }
    }
}

[numthreads(512,1,1)]
void CSConditionM4G(uint3 group:SV_GroupID, uint lane:SV_GroupIndex) {
    GDHorizontal(group.x,lane,false);
}

// Switch 2: same horizontal pass, seed read from the history output.
[numthreads(512,1,1)]
void CSConditionM4GH(uint3 group:SV_GroupID, uint lane:SV_GroupIndex) {
    GDHorizontal(group.x,lane,true);
}

// Vertical pass (V2: linear penalty on unmapped depth), identical math to
// CSConditionM4Vertical. One slice (copied to slice 1) unless switch 3 is on.
[numthreads(512,1,1)]
void CSConditionM4GVertical(uint3 group:SV_GroupID, uint lane:SV_GroupIndex) {
    const uint h=M4Grid.y, col=group.x;
    if(col>=M4Grid.x || h==0u || h>4096u) return;
    // Tight one-sided ramp: no vertical spreading (the warp is horizontal only).
    const float pv=((GDFlags()&12u)==12u || (GDFlags()&16u)!=0u) ? 0.0 : M1Filter.z*M4Flags.z;
    const float limit=M1Depth.w>0.0 ? 2.0*M1Depth.w : M1Filter.y;
    const uint slices=(GDFlags()&4u)!=0u ? 2u : 1u;
    [loop] for(uint slice=0u;slice<slices;++slice) {
        GroupMemoryBarrierWithGroupSync();
        [loop] for(uint y0=lane;y0<h;y0+=GD_LANES)
            GDRow[y0]=M4FoveaConditioned[uint3(col,y0,slice)];
        GroupMemoryBarrierWithGroupSync();
        [branch] if(pv>0.0) {
            for(uint step=1u;step<h && float(step-1u)*pv<limit;step*=2u) {
                float next[GD_TILES];
                [unroll] for(uint t1=0u;t1<GD_TILES;++t1) {
                    const uint y=GD_LANES*t1+lane;
                    next[t1]=0.0;
                    if(y<h) {
                        const float penalty=float(step)*pv;
                        const float above=y>=step ? GDRow[y-step]-penalty : 0.0;
                        const float below=y+step<h ? GDRow[y+step]-penalty : 0.0;
                        next[t1]=max(GDRow[y],max(above,below));
                    }
                }
                GroupMemoryBarrierWithGroupSync();
                [unroll] for(uint t2=0u;t2<GD_TILES;++t2) {
                    const uint y=GD_LANES*t2+lane;
                    if(y<h) GDRow[y]=next[t2];
                }
                GroupMemoryBarrierWithGroupSync();
            }
        }
        [loop] for(uint y3=lane;y3<h;y3+=GD_LANES) {
            M4FoveaConditioned[uint3(col,y3,slice)]=GDRow[y3];
            if(slices==1u) M4FoveaConditioned[uint3(col,y3,1u)]=GDRow[y3];
        }
    }
}

// ---- Switch 2: temporal depth history for ALL fovea depth.
// History (u6, R32_UINT array, shared by every XR slot on the one queue):
// slices 2p / 2p+1 = kept raw seed (float bits) / age for parity p;
// slice 4 texels (0..3,0) = per-parity counters {texels, texels from history}.
// Per texel: current seed; previous kept seeds in 3x3 windows around the
// world-reprojected position at three candidate depths (rotation + translation;
// a candidate is accepted only if its own-depth reprojection lands within the
// radius), never in weapon/hands range, and only for thin kept depth.
// Output = max(current, accepted history).
// Re-confirmed by the current frame -> age 0; else age+1; dropped at age K.
RWTexture2DArray<uint> GDHistory : register(u6);
groupshared uint GDCount[2];

float2 GDPreviousCell(float2 local, float inverseDepth, out bool ok) {
    const float2 fullUv=lerp(M2Crop.xy,M2Crop.zw,local);
    const float4 p=M6CurrentProjection;
    const float4 ray=float4((2.0*fullUv.x-1.0-p.y)/p.x,(1.0-2.0*fullUv.y-p.w)/p.z,1.0,inverseDepth);
    const float3 prev=float3(dot(M6View[0],ray),dot(M6View[1],ray),dot(M6View[2],ray));
    ok=prev.z>.01;
    const float z=max(prev.z,.01);
    const float4 pp=M6PreviousProjection;
    const float2 previousUv=float2(.5+.5*(pp.x*prev.x/z+pp.y),.5-.5*(pp.z*prev.y/z+pp.w));
    const float2 uv=(previousUv-M6PreviousCrop.xy)/max(M6PreviousCrop.zw-M6PreviousCrop.xy,1.e-6);
    return uv*float2(M4Grid.xy)-.5;
}

[numthreads(8,8,1)]
void CSGoalDHistory(uint3 id:SV_DispatchThreadID, uint3 group:SV_GroupID, uint gi:SV_GroupIndex) {
    const uint parity=M6PreviousRect.x&1u;
    const bool valid=(GDFlags()&1u)!=0u;
    if(gi==0u) { GDCount[0]=0u; GDCount[1]=0u; }
    GroupMemoryBarrierWithGroupSync();
    uint keep=0u, used=0u;
    [branch] if(id.x<M4Grid.x && id.y<M4Grid.y) {
        const float cur=GDSeedRaw(id.xy);
        float outDepth=cur;
        uint age=0u;
        [branch] if(valid) {
            const float2 local=(float2(id.xy)+.5)/float2(M4Grid.xy);
            const uint previous=2u*(parity^1u);
            const float radius=M6PreviousJitter.w;
            const float lockDepth=M6PreviousJitter.z;
            float best=0.0;
            uint bestAge=0u;
            int2 bestC=int2(0,0);
            // Review fixes (11-18 pm): (a) no history in weapon/hands range (those move
            // on their own: trails); (b) search windows at three candidate depths
            // (infinity, 1/3 and 2/3 of the near range), so camera translation parallax
            // of nearer objects is found, not only rotation; (c) only THIN kept depth
            // (narrower than 5 texels across x or y in the previous frame) may come from
            // history - edges of wide objects that moved away are not held (no trails).
            const uint windows=lockDepth>0.0 ? 3u : 1u;
            [loop] for(uint win=0u;win<windows;++win) {
                bool okCenter;
                const int2 c0=int2(round(GDPreviousCell(local,lockDepth*float(win)/3.0,okCenter)));
                [unroll] for(int dy=-1;dy<=1;++dy) {
                    [unroll] for(int dx=-1;dx<=1;++dx) {
                        const int2 c=c0+int2(dx,dy);
                        if(all(c>=int2(0,0)) && all(c<int2(M4Grid.xy))) {
                            const float h=asfloat(GDHistory[uint3(uint2(c),previous)]);
                            if(h>max(cur,best) && !(lockDepth>0.0 && h>=lockDepth)) {
                                bool ok=true;
                                const float2 q=GDPreviousCell(local,h,ok);
                                if(ok && all(abs(q-float2(c))<=radius)) {
                                    best=h; bestC=c;
                                    bestAge=GDHistory[uint3(uint2(c),previous+1u)];
                                }
                            }
                        }
                    }
                }
            }
            [branch] if(best>0.0) {
                const int2 lim=int2(M4Grid.xy)-1;
                const float lo=best*.97;
                const bool thinX=asfloat(GDHistory[uint3(uint2(clamp(bestC-int2(3,0),int2(0,0),lim)),previous)])<lo &&
                                 asfloat(GDHistory[uint3(uint2(clamp(bestC+int2(3,0),int2(0,0),lim)),previous)])<lo;
                const bool thinY=asfloat(GDHistory[uint3(uint2(clamp(bestC-int2(0,3),int2(0,0),lim)),previous)])<lo &&
                                 asfloat(GDHistory[uint3(uint2(clamp(bestC+int2(0,3),int2(0,0),lim)),previous)])<lo;
                if(!thinX && !thinY) best=0.0;
            }
            [branch] if(best>0.0 && cur<best*.97) {
                const uint nextAge=bestAge+1u;
                if(float(nextAge)<M6PreviousJitter.y) {
                    outDepth=best;
                    age=nextAge;
                    used=1u;
                }
            }
        }
        GDHistory[uint3(id.xy,2u*parity)]=asuint(outDepth);
        GDHistory[uint3(id.xy,2u*parity+1u)]=age;
        M4FoveaConditioned[uint3(id.xy,0u)]=outDepth;
        keep=outDepth>0.0 ? 1u : 0u;
    }
    InterlockedAdd(GDCount[0],keep);
    InterlockedAdd(GDCount[1],used);
    GroupMemoryBarrierWithGroupSync();
    if(gi==0u) {
        InterlockedAdd(GDHistory[uint3(2u*parity,0u,4u)],GDCount[0]);
        InterlockedAdd(GDHistory[uint3(2u*parity+1u,0u,4u)],GDCount[1]);
        if(group.x==0u && group.y==0u) {
            GDHistory[uint3(2u*(parity^1u),0u,4u)]=0u;
            GDHistory[uint3(2u*(parity^1u)+1u,0u,4u)]=0u;
        }
    }
}

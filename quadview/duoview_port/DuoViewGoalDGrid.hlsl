// ---- Goal D switch 1 (Claude, 2026-11-18): M4 fovea depth field up to 4096
// texels per axis, so 1625x1435 fine NGX depth is conditioned ~1:1 instead of
// being fitted into 1024x904. Production Stereo V2 path only (M8 V2 policy,
// no per-eye M3 edges): identical seed (2x2 near-max at the jittered fine
// position, knee/cap) and identical constant-penalty envelope on mapped depth.
// Penalties are per field texel and already scale with 1/M4Grid, so the ramp
// width in screen terms is unchanged; only resolution changes.
// Groupshared: one 16 KiB row; each of 512 lanes stages its <=8 new values in
// registers (two 4096 rows would take the whole 32 KiB D3D12 limit).
// The 4096 field is a single-slice array: V2 writes the same depth for both
// eyes, and a Texture2DArray read of slice 1 clamps to slice 0.
// Appended after the existing kernels; Off kernels and their DXBC are unchanged.
groupshared float GDRow[4096];

#define GD_LANES 512u
#define GD_TILES 8u

[numthreads(512,1,1)]
void CSConditionM4G(uint3 group:SV_GroupID, uint lane:SV_GroupIndex) {
    const uint w=M4Grid.x;
    // Uniform early-outs (constant-buffer or group values only).
    if(group.x>=M4Grid.y || w==0u || w>4096u) return;
    const float2 dimension=float2(M2FoveaRect.zw);
    const float knee=M1Depth.w;
    [loop] for(uint x0=lane;x0<w;x0+=GD_LANES) {
        {
            const float2 local=(float2(x0,group.x)+.5)/float2(M4Grid.xy);
            const float2 jit=clamp(local+M2FineJitter(),.5/dimension,1.0-.5/dimension);
            const int2 f0=int2(floor(jit*dimension-.5));
            float fine=0.0;
            [unroll] for(int fy=0;fy<=1;++fy)
                [unroll] for(int fx=0;fx<=1;++fx)
                    fine=max(fine,DecodeM2Depth(f0+int2(fx,fy)));
            float nearDepth=fine;
            if(knee>0.0 && nearDepth>knee) {
                const float excess=nearDepth-knee;
                nearDepth=knee+excess/(1.0+excess/knee);
            }
            GDRow[x0]=M8V2Map(knee>0.0 ? nearDepth : min(nearDepth,M1Filter.y));
        }
    }
    GroupMemoryBarrierWithGroupSync();

    const float limit=M1Depth.w>0.0 ? 2.0*M1Depth.w : M1Filter.y;
    const float pen=min(M1Filter.x*M4Flags.y,M8SafeLimit());
    const float mappedLimit=M8V2Map(limit);
    for(uint step=1u;step<w && float(step-1u)*pen<mappedLimit;step*=2u) {
        float next[GD_TILES];
        [unroll] for(uint t=0u;t<GD_TILES;++t) {
            const uint x=GD_LANES*t+lane;
            next[t]=0.0;
            if(x<w) {
                const float left=x>=step ? GDRow[x-step]-float(step)*pen : 0.0;
                const float right=x+step<w ? GDRow[x+step]-float(step)*pen : 0.0;
                next[t]=max(GDRow[x],max(left,right));
            }
        }
        GroupMemoryBarrierWithGroupSync();
        [unroll] for(uint t2=0u;t2<GD_TILES;++t2) {
            const uint x=GD_LANES*t2+lane;
            if(x<w) GDRow[x]=next[t2];
        }
        GroupMemoryBarrierWithGroupSync();
    }
    [loop] for(uint x3=lane;x3<w;x3+=GD_LANES)
        M4FoveaConditioned[uint3(x3,group.x,0u)]=M8V2Unmap(GDRow[x3]);
}

// Vertical pass of the same field (V2: one slice, linear penalty on unmapped
// depth), identical math to CSConditionM4Vertical with slices==1.
[numthreads(512,1,1)]
void CSConditionM4GVertical(uint3 group:SV_GroupID, uint lane:SV_GroupIndex) {
    const uint h=M4Grid.y, col=group.x;
    if(col>=M4Grid.x || h==0u || h>4096u) return;
    const float pv=M1Filter.z*M4Flags.z;
    const float limit=M1Depth.w>0.0 ? 2.0*M1Depth.w : M1Filter.y;
    [loop] for(uint y0=lane;y0<h;y0+=GD_LANES)
        GDRow[y0]=M4FoveaConditioned[uint3(col,y0,0u)];
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
    [loop] for(uint y3=lane;y3<h;y3+=GD_LANES)
        M4FoveaConditioned[uint3(col,y3,0u)]=GDRow[y3];
}

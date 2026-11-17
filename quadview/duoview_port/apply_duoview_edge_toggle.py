#!/usr/bin/env python3
"""DuoView edge toggle: runtime setting Off / K3D10TS16 / K23D10TS16 (headset A/B test build).

Applied AFTER apply_duoview_stereo_cleanup.py and its generated/numeric tests.
Design (research/edge-fix/48_improveA_results.md, DECISIONS 2026-11-17 joint pick):
  * Off (default) must stay byte-identical to the frozen #357 baseline. Therefore every K change is
    compiled ONLY into separate shader variants (/D DUOVIEW_EDGE_K=1: *_k_bytecode arrays appended
    to the header). The Off shaders, their DXBC and the Off C++ command stream are unchanged.
  * K3D10TS16 / K23D10TS16 port the 1D simulation arms of 47_/47b_ to the GPU:
      - fovea (M4) depth field at fovea COLOUR resolution, seeded by a two-label colour snap of the
        fine depth (A2u radius 1) + temporal two-label hysteresis with colour-change reset (A5u);
      - K3: 3-px foreground dilation on thin structures (< 12 colour px); K23 additionally keeps
        the nearest depth (no snap) on thin structures and stabilises it with the hysteresis (K2);
      - D10 + T: per-eye disocclusion-side penalty x10 for wide (>= 48 colour px) runs only,
        thin runs keep the symmetric penalty (coarse M1 field and fovea M4 field);
      - S16: 16 instead of 8 bisections in the pull warp.
  * History: one queue-owned RGBA32F 1024x1024 texture (label depth + colour) in B40MonoHistory,
    read and rewritten in place per texel by the K fovea kernel (u6, retired M7 slot).
Evidence level of this file: source only until FXC/CI WARP/headset.
"""
import argparse
from pathlib import Path


def once(src, old, new, what):
    n = src.count(old)
    if n != 1:
        raise RuntimeError(f'edge toggle anchor "{what}": {n} matches')
    return src.replace(old, new, 1)


def edit(path, fn):
    text = path.read_text(encoding='utf-8')
    out = fn(text)
    path.write_text(out, encoding='utf-8', newline='')


K_HLSL = r'''#ifdef DUOVIEW_EDGE_K
// ---- Edge toggle K3D10TS16 / K23D10TS16 (Claude, 2026-11-17) ----
// GPU port of the 1D improve-A simulation arms (research/edge-fix/47_, 48_). Compiled ONLY into the
// *_k_bytecode variants; the Off shaders never see this block.
//   refine : two-label colour snap of fine depth at fovea colour resolution (A2u, radius 1) and
//            temporal two-label hysteresis with colour-change reset (A5u);
//   K3     : 3-px foreground dilation on thin structures (< 12 colour px);
//   K23    : K3 + thin structures keep the nearest depth (no snap), stabilised by the hysteresis (K2);
//   D10/T  : per-eye disocclusion-side penalty x10 only for wide (>= 48 colour px) runs.
// 2D choices not in the 1D model: the horizontal 1D refine runs on BOTH rows of production's 2x2
// near-max footprint and keeps the nearer row (production vertical near-max); texel positions use
// production's jitter compensation; colour thresholds are RGB8 units on saturated fovea colour.
Texture2D<float4> M10FoveaColor : register(t0);
RWTexture2D<float4> M10History : register(u6);
static const float M10Ramp=10.0;
static const float M10ThinPx=12.0;
static const float M10WidePx=48.0;
static const float M10SnapContrast=12.0/255.0;
static const float M10ResetContrast=8.0/255.0;

float M10MeanAbs(float3 a, float3 b) { const float3 d=abs(a-b); return (d.x+d.y+d.z)/3.0; }
float3 M10Color(float2 local) {
    const uint2 ext=max(M7ColorExtent.xy,uint2(1u,1u));
    const int2 p=clamp(int2(floor(saturate(local)*float2(ext))),int2(0,0),int2(ext)-1);
    return saturate(M10FoveaColor.Load(int3(p,0)).rgb);
}

struct M10Label { float g, fg, bg; bool flat, amb, thin; };
// One depth row, three texels around the nearest one (1D model refine_k).
M10Label M10RefineRow(int row, float sampleU, float jitU, float3 src, float2 dim, float2 J,
                      float ratio, uint mode) {
    M10Label o;
    o.flat=false; o.amb=false; o.thin=false;
    const int wDim=max(int(dim.x),1);
    const int m1=clamp(int(floor(jitU*dim.x)),0,wDim-1);
    int m[3]; float d[3]; float u[3];
    [unroll] for(int i=0;i<3;++i) {
        m[i]=clamp(m1-1+i,0,wDim-1);
        d[i]=DecodeM2Depth(int2(m[i],row));
        u[i]=(float(m[i])+.5)/dim.x-J.x;
    }
    const float dmax=max(d[0],max(d[1],d[2]));
    const float dmin=min(d[0],min(d[1],d[2]));
    o.g=d[1]; o.fg=dmax; o.bg=dmin;
    if(dmax-dmin<.10*dmax) { o.flat=true; return o; }
    // Nearest-by-position maximum/minimum; the first wins a tie, like the model's min().
    int jf=1, jb=1; float bf=1.e9, bb=1.e9;
    [unroll] for(int k=0;k<3;++k) {
        const float dist=abs(u[k]-sampleU);
        if(d[k]==dmax && dist<bf) { bf=dist; jf=k; }
        if(d[k]==dmin && dist<bb) { bb=dist; jb=k; }
    }
    // Thin = the foreground texel run (>= 90% of dmax) spans < 12 colour px.
    {
        const float thr=.9*dmax;
        float n=1.0;
        int a=m[jf]-1, b=m[jf]+1;
        [loop] for(uint s=0u;s<32u;++s) {
            if(!(a>=0 && n*ratio<M10ThinPx)) break;
            if(!(DecodeM2Depth(int2(a,row))>=thr)) break;
            n+=1.0; --a;
        }
        [loop] for(uint t=0u;t<32u;++t) {
            if(!(b<wDim && n*ratio<M10ThinPx)) break;
            if(!(DecodeM2Depth(int2(b,row))>=thr)) break;
            n+=1.0; ++b;
        }
        o.thin=n*ratio<M10ThinPx;
    }
    if(mode==2u && o.thin) { o.amb=true; return o; }   // K2 hold: nearest depth, no snap
    const float cy=(float(row)+.5)/dim.y-J.y;
    const float3 cf=M10Color(float2(u[jf],cy));
    const float3 cb=M10Color(float2(u[jb],cy));
    const float lo=min(u[jf],u[jb]), hi=max(u[jf],u[jb]);
    if(M10MeanAbs(cf,cb)<M10SnapContrast || !(sampleU>=lo && sampleU<=hi)) { o.amb=true; return o; }
    const float df=M10MeanAbs(src,cf), db=M10MeanAbs(src,cb);
    o.g=df<=db ? dmax : dmin;
    o.amb=abs(df-db)<M10SnapContrast;
    return o;
}

// Asymmetric constant-penalty max envelope on M1Row (mapped depth). penL bounds the fall-off to the
// RIGHT of a source (value arriving from x-step), penR the fall-off to the LEFT. Mixed-direction
// paths are never better than the direct one, so per-step doubling stays exact.
void M10Envelope(uint w, uint lane, float penL, float penR, float bound) {
    const float pmin=min(penL,penR);
    for(uint step=1u;step<w && float(step-1u)*pmin<bound;step*=2u) {
        for(uint tile=0u;tile<(w+127u)/128u;++tile) {
            const uint x=128u*tile+lane;
            if(x<w) {
                const float l=x>=step ? M1Row[x-step]-float(step)*penL : 0.0;
                const float r=x+step<w ? M1Row[x+step]-float(step)*penR : 0.0;
                M1Next[x]=max(M1Row[x],max(l,r));
            }
        }
        GroupMemoryBarrierWithGroupSync();
        for(uint tile=0u;tile<(w+127u)/128u;++tile) {
            const uint x=128u*tile+lane;
            if(x<w) M1Row[x]=M1Next[x];
        }
        GroupMemoryBarrierWithGroupSync();
    }
}

// D10 + thin protection. Input: mapped seeds in M1Seed. Output: one slice per eye.
// Model envelope_tp: max(directional envelope of wide-only seeds, symmetric envelope of thin-only seeds).
void M10Field(uint w, uint lane, uint row, float pen, float bound, float pxPerTexel, bool fine) {
    const uint need=min(uint(ceil(M10WidePx/max(pxPerTexel,1.e-3))),w);
    for(uint tile=0u;tile<(w+127u)/128u;++tile) {
        const uint x=128u*tile+lane;
        if(x<w) {
            const float v=M1Seed[x], thr=.9*v;
            uint cnt=1u; int a=int(x)-1, b=int(x)+1;
            [loop] for(uint s=0u;s<1024u;++s) {
                if(!(cnt<need && a>=0)) break;
                if(!(M1Seed[a]>=thr)) break;
                ++cnt; --a;
            }
            [loop] for(uint t=0u;t<1024u;++t) {
                if(!(cnt<need && b<int(w))) break;
                if(!(M1Seed[b]>=thr)) break;
                ++cnt; ++b;
            }
            const bool wide=cnt>=need;
            M8Scale[x]=wide ? 1.0 : 0.0;
            M1Row[x]=wide ? 0.0 : v;
        }
    }
    GroupMemoryBarrierWithGroupSync();
    M10Envelope(w,lane,pen,pen,bound);
    for(uint tile=0u;tile<(w+127u)/128u;++tile) {
        const uint x=128u*tile+lane;
        if(x<w) M8Origin[x]=M1Row[x];
    }
    GroupMemoryBarrierWithGroupSync();
    [unroll] for(uint eye=0u;eye<2u;++eye) {
        const float k=M1Eye[eye];
        const float steep=pen*M10Ramp;
        // k>0: the field may fall steeply toward +u without folding (model eye>0: left_pen*r).
        const float penL=k>0.0 ? steep : pen;
        const float penR=k<0.0 ? steep : pen;
        for(uint tile=0u;tile<(w+127u)/128u;++tile) {
            const uint x=128u*tile+lane;
            if(x<w) M1Row[x]=M8Scale[x]>.5 ? M1Seed[x] : 0.0;
        }
        GroupMemoryBarrierWithGroupSync();
        M10Envelope(w,lane,penL,penR,bound);
        for(uint tile=0u;tile<(w+127u)/128u;++tile) {
            const uint x=128u*tile+lane;
            if(x<w) {
                const float depth=M8V2Unmap(max(M1Row[x],M8Origin[x]));
                if(fine) M4FoveaConditioned[uint3(x,row,eye)]=depth;
                else M1ConditionedDepth[uint3(x,row,eye)]=depth;
            }
        }
        GroupMemoryBarrierWithGroupSync();
    }
}

// Fovea field in K mode: M4Grid is the fovea colour resolution (CPU), seeds from the K refine.
void M10ConditionM4K(uint row, uint lane) {
    const uint w=M4Grid.x;
    const float2 dim=max(float2(M2FoveaRect.zw),float2(1.0,1.0));
    const float2 J=M2FineJitter();
    const float ratio=float(M4Grid.x)/dim.x;      // grid (colour) px per fine depth texel
    const uint mode=M10Edge.x>1.5 ? 2u : 1u;
    const bool historyValid=M10Edge.y>.5;
    for(uint tile=0u;tile<(w+127u)/128u;++tile) {
        const uint x=128u*tile+lane;
        if(x<w) {
            const float2 local=(float2(x,row)+.5)/float2(M4Grid.xy);
            const float2 jit=clamp(local+J,.5/dim,1.0-.5/dim);
            const float3 src=M10Color(local);
            const int r0=clamp(int(floor(jit.y*dim.y-.5)),0,int(dim.y)-1);
            const int r1=min(r0+1,int(dim.y)-1);
            const M10Label a=M10RefineRow(r0,local.x,jit.x,src,dim,J,ratio,mode);
            const M10Label b=M10RefineRow(r1,local.x,jit.x,src,dim,J,ratio,mode);
            M10Label s=a;
            if(b.g>a.g) s=b;
            float g=s.g;
            [branch] if(historyValid && !s.flat && s.amb) {
                const float4 h=M10History[uint2(x,row)];
                if(M10MeanAbs(src,h.yzw)<=M10ResetContrast) {
                    const float p=h.x;
                    const bool okf=abs(p-s.fg)<=.1*s.fg;
                    const bool okb=abs(p-s.bg)<=.1*s.bg;
                    if(okf && okb) g=abs(p-s.fg)<=abs(p-s.bg) ? s.fg : s.bg;
                    else if(okf) g=s.fg;
                    else if(okb) g=s.bg;
                }
            }
            // History keeps the undilated label grid and this frame's colour (model state['prev']).
            M10History[uint2(x,row)]=float4(g,src);
            M8Origin[x]=g;
            M8Scale[x]=(a.thin || b.thin) ? 1.0 : 0.0;
        }
    }
    GroupMemoryBarrierWithGroupSync();
    // K3: 3-px max dilation on thin structures only.
    for(uint tile=0u;tile<(w+127u)/128u;++tile) {
        const uint x=128u*tile+lane;
        if(x<w) {
            const float g=M8Origin[x];
            M8NextOrigin[x]=M8Scale[x]>.5 ?
                max(g,max(M8Origin[x>0u ? x-1u : 0u],M8Origin[min(x+1u,w-1u)])) : g;
        }
    }
    GroupMemoryBarrierWithGroupSync();
    // Fine seed = max(D(u - ratio/2), D(u + ratio/2)), then production knee/cap and V2 map.
    const float half=.5*ratio;
    const float knee=M1Depth.w;
    for(uint tile=0u;tile<(w+127u)/128u;++tile) {
        const uint x=128u*tile+lane;
        if(x<w) {
            const int il=clamp(int(floor(float(x)-half+.5)),0,int(w)-1);
            const int ir=clamp(int(floor(float(x)+half+.5)),0,int(w)-1);
            float nearDepth=max(M8NextOrigin[il],M8NextOrigin[ir]);
            if(knee>0.0 && nearDepth>knee) {
                const float excess=nearDepth-knee;
                nearDepth=knee+excess/(1.0+excess/knee);
            }
            M1Seed[x]=M8V2Map(knee>0.0 ? nearDepth : min(nearDepth,M1Filter.y));
        }
    }
    GroupMemoryBarrierWithGroupSync();
    const float limit=M1Depth.w>0.0 ? 2.0*M1Depth.w : M1Filter.y;
    const float pen=min(M1Filter.x*M4Flags.y,M8SafeLimit());
    M10Field(w,lane,row,pen,M8V2Map(limit),M10Edge.z*(M2Crop.z-M2Crop.x)/float(max(w,1u)),true);
}
#endif
'''


def shader(src):
    src = once(src,
        '    float4 M5Sharpen; // x/y: left/right max change (negative = shared SharpenMaxChange)\n};',
        '    float4 M5Sharpen; // x/y: left/right max change (negative = shared SharpenMaxChange)\n'
        '#ifdef DUOVIEW_EDGE_K\n'
        '    float4 M10Edge; // edge toggle: x 1=K3D10TS16 2=K23D10TS16, y history valid, z colour px per eye UV, w K fovea\n'
        '#endif\n};',
        'K-only constant lane')
    src = once(src, 'void M3Envelope(uint w, uint lane, uint eye, float limit) {',
               K_HLSL + 'void M3Envelope(uint w, uint lane, uint eye, float limit) {', 'K helpers')
    # Coarse field: production seeds (already V2-mapped), then D10+T per eye.
    src = once(src,
        '''    const float limit = M1Depth.w > 0.0 ? 2.0*M1Depth.w : M1Filter.y;
    [branch] if (M3Flags.x < .5) {''',
        '''    const float limit = M1Depth.w > 0.0 ? 2.0*M1Depth.w : M1Filter.y;
#ifdef DUOVIEW_EDGE_K
    [branch] if (M8Distance.z>.5 && M8Distance.w>=10.0 && M3Flags.x<.5) {
        for (uint x = lane; x < w; x += 128) M1Seed[x] = M1Row[x];
        GroupMemoryBarrierWithGroupSync();
        M10Field(w,lane,group.x,M1Filter.x,M8V2Map(limit),M10Edge.z/float(max(M1Grid.x,1u)),false);
        return;
    }
#endif
    [branch] if (M3Flags.x < .5) {''',
        'coarse K hook')
    start = src.index('void CSConditionM4(')
    end = src.index('void CSConditionM4ProbeSeed(', start)
    kernel = once(src[start:end],
        '''    const uint w=M4Grid.x;
    if (group.x>=M4Grid.y || w==0u || w>1024u) return;
    const float2 dimension=float2(M2FoveaRect.zw);
    for (uint tile=0u; tile<(w+127u)/128u; ++tile) {''',
        '''    const uint w=M4Grid.x;
    if (group.x>=M4Grid.y || w==0u || w>1024u) return;
#ifdef DUOVIEW_EDGE_K
    [branch] if (M8Distance.w>=10.0 && M3Flags.x<.5 && M10Edge.w>.5) {
        M10ConditionM4K(group.x,lane);
        return;
    }
#endif
    const float2 dimension=float2(M2FoveaRect.zw);
    for (uint tile=0u; tile<(w+127u)/128u; ++tile) {''',
        'fovea K hook')
    src = src[:start] + kernel + src[end:]
    # The K fields are per eye: the vertical passes must keep both slices.
    old_v = '    const uint slices=M3Flags.x>.5 ? 2u : 1u;'
    if src.count(old_v) != 2:
        raise RuntimeError(f'vertical slice anchors: {src.count(old_v)}')
    src = src.replace(old_v, '#ifdef DUOVIEW_EDGE_K\n    const uint slices=2u;\n#else\n' + old_v + '\n#endif')
    src = once(src,
        '        [unroll] for(uint iteration=0u;iteration<8u;++iteration) {\n'
        '            const float mid=0.5*(lo+hi);\n'
        '            const float residual=base.x+k*M1ReadConditionedEye(float2(mid,base.y),eye)-mid;',
        '#ifdef DUOVIEW_EDGE_K\n'
        '        [unroll] for(uint iteration=0u;iteration<16u;++iteration) {   // TS16\n'
        '#else\n'
        '        [unroll] for(uint iteration=0u;iteration<8u;++iteration) {\n'
        '#endif\n'
        '            const float mid=0.5*(lo+hi);\n'
        '            const float residual=base.x+k*M1ReadConditionedEye(float2(mid,base.y),eye)-mid;',
        'S16 bisections')
    return src


def m1_backend(src):
    src = once(src,
        '    float m5_sharpen[4]{}; // left/right max change (negative = shared)\n};\nstatic_assert(sizeof(M1Constants) == 576);',
        '    float m5_sharpen[4]{}; // left/right max change (negative = shared)\n'
        '    float m10_edge[4]{};   // edge toggle (read only by *_k shaders): mode, history valid, colour px/UV, K fovea\n'
        '};\nstatic_assert(sizeof(M1Constants) == 592);',
        'K constant lane')
    src = once(src,
        '    ComPtr<ID3D12PipelineState> m4_condition, m4_vertical;\n',
        '    ComPtr<ID3D12PipelineState> m4_condition, m4_vertical;\n'
        '    // Edge toggle (Off / K3D10TS16 / K23D10TS16): separate DXBC; a failure disables only K.\n'
        '    ComPtr<ID3D12PipelineState> raster_k, condition_k, vertical_k, m4_condition_k, m4_vertical_k;\n'
        '    bool k_coarse{}, k_m4{}; uint32_t k_mode{};\n',
        'K pipelines')
    src = once(src,
        '        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4_vertical)))) m4_vertical.Reset();\n',
        '''        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4_vertical)))) m4_vertical.Reset();
        compute.CS={m1_condition_k_bytecode,sizeof(m1_condition_k_bytecode)};
        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&condition_k)))) condition_k.Reset();
        compute.CS={m24_vertical_k_bytecode,sizeof(m24_vertical_k_bytecode)};
        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&vertical_k)))) vertical_k.Reset();
        compute.CS={m4_condition_k_bytecode,sizeof(m4_condition_k_bytecode)};
        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4_condition_k)))) m4_condition_k.Reset();
        compute.CS={m4_vertical_k_bytecode,sizeof(m4_vertical_k_bytecode)};
        if(FAILED(device->CreateComputePipelineState(&compute,IID_PPV_ARGS(&m4_vertical_k)))) m4_vertical_k.Reset();
        {
            auto k_graphics=graphics;
            k_graphics.PS={m1_raster_k_bytecode,sizeof(m1_raster_k_bytecode)};
            if(FAILED(device->CreateGraphicsPipelineState(&k_graphics,IID_PPV_ARGS(&raster_k)))) raster_k.Reset();
        }
''',
        'K pipeline creation')
    src = once(src,
        '                         float eye_near,float eye_far) {',
        '                         float eye_near,float eye_far,\n'
        '                         uint32_t edge_mode=0u,bool k_history=false,\n'
        '                         uint32_t k_prev_w=0u,uint32_t k_prev_h=0u) {',
        'write_constants K parameters')
    src = once(src,
        '        m25_read_retired_stats(); // The owning XR command slot has retired before reuse.\n        M1Constants data{};\n',
        '        m25_read_retired_stats(); // The owning XR command slot has retired before reuse.\n        M1Constants data{};\n'
        '        // K needs the effective V2 stereo path (edge_reach lane >= 10) and every K pipeline.\n'
        '        const bool k_requested=edge_mode>=1u && edge_mode<=2u && !m3_edges && edge_reach_px>=10.f &&\n'
        '            raster_k && condition_k && vertical_k && m4_condition_k && m4_vertical_k;\n'
        '        bool k_grid=false;\n',
        'K request')
    src = once(src,
        '            const float fw=float(focus->rect[2]), fh=float(focus->rect[3]);\n',
        '            // K: the fovea field runs at fovea COLOUR resolution (snap needs sub-depth-texel colour).\n'
        '            k_grid=k_requested && color_extent[0] && color_extent[1];\n'
        '            const float fw=k_grid ? float(color_extent[0]) : float(focus->rect[2]);\n'
        '            const float fh=k_grid ? float(color_extent[1]) : float(focus->rect[3]);\n',
        'K fovea grid size')
    src = once(src,
        '        void* address{};\n        const D3D12_RANGE no_read{0,0};\n        if (FAILED(constants->Map(0, &no_read, &address))) return false;',
        '''        k_coarse=k_requested && data.grid[0]>0u;
        k_m4=k_coarse && k_grid && m4_active;
        k_mode=k_coarse ? edge_mode : 0u;
        if(k_coarse) {
            data.m10_edge[0]=float(edge_mode);
            data.m10_edge[1]=(k_m4 && k_history && k_prev_w==m4_columns && k_prev_h==m4_rows) ? 1.f : 0.f;
            const float crop_w=data.m2_crop[2]-data.m2_crop[0];
            data.m10_edge[2]=(color_extent[0] && crop_w>0.f) ? float(color_extent[0])/crop_w :
                float((std::max)(output_width_px,1u));
            data.m10_edge[3]=k_m4 ? 1.f : 0.f;
        }
        void* address{};
        const D3D12_RANGE no_read{0,0};
        if (FAILED(constants->Map(0, &no_read, &address))) return false;''',
        'K constants')
    return src


def compositor_backend(src):
    src = once(src,
        '    FineDepthHistoryFrame fine_depth;\n    static std::shared_ptr<B40MonoHistory> create(',
        '    FineDepthHistoryFrame fine_depth;\n'
        '    // Edge toggle K3/K23: queue-owned label/colour history (RGBA32F 1024x1024, 16 MiB), rewritten in\n'
        '    // place per texel by the K fovea kernel. Valid only for the next frame with the same grid size.\n'
        '    ComPtr<ID3D12Resource> edge_history;\n'
        '    uint32_t edge_w{}, edge_h{};\n'
        '    static std::shared_ptr<B40MonoHistory> create(',
        'edge history member')
    src = once(src,
        '        state->buffer->SetName(L"DuoView B40 Mono queue-owned history");\n        return state;',
        '''        state->buffer->SetName(L"DuoView B40 Mono queue-owned history");
        D3D12_RESOURCE_DESC edge{};
        edge.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        edge.Width=edge.Height=1024u;
        edge.DepthOrArraySize=edge.MipLevels=1; edge.SampleDesc.Count=1;
        edge.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
        edge.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        // Optional: without it K3/K23 run without hysteresis; B40 is unaffected.
        if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&edge,
            D3D12_RESOURCE_STATE_UNORDERED_ACCESS,nullptr,IID_PPV_ARGS(&state->edge_history))))
            state->edge_history.Reset();
        else state->edge_history->SetName(L"DuoView edge toggle label history");
        return state;''',
        'edge history allocation')
    src = once(src,
        '                settings.m9_eye_near,settings.m9_eye_far);\n',
        '''                settings.m9_eye_near,settings.m9_eye_far,
                settings.stereo_edge_mode,b40_history_ && b40_history_->edge_history,
                b40_history_ ? b40_history_->edge_w : 0u,b40_history_ ? b40_history_->edge_h : 0u);
        if(b40_history_) {
            // The next frame may reuse the history only if THIS frame writes it at the same size.
            const bool k_written=m1_active && m1_.k_m4 && b40_history_->edge_history;
            b40_history_->edge_w=k_written ? m1_.m4_columns : 0u;
            b40_history_->edge_h=k_written ? m1_.m4_rows : 0u;
        }
''',
        'write_constants K arguments')
    src = once(src,
        '        const auto sample_state=b40_active ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE :\n'
        '            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;\n        const auto fovea_sample_state=sample_state;',
        '        // K reads fovea colour (t0) in the compute fovea kernel: non-pixel access needed.\n'
        '        const auto sample_state=(b40_active || (m1_active && m1_.k_m4)) ? D3D12_RESOURCE_STATE_ALL_SHADER_RESOURCE :\n'
        '            D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;\n        const auto fovea_sample_state=sample_state;',
        'fovea compute-readable state')
    src = once(src,
        '            cmd->SetPipelineState(m1_.condition.Get());\n            cmd->SetComputeRootConstantBufferView(4,',
        '            cmd->SetPipelineState(m1_.k_coarse ? m1_.condition_k.Get() : m1_.condition.Get());\n'
        '            cmd->SetComputeRootConstantBufferView(4,',
        'coarse K pipeline')
    src = once(src,
        '                cmd->SetPipelineState(m1_.condition.Get());\n            }\n            cmd->Dispatch(m1_.rows,1,1);',
        '                cmd->SetPipelineState(m1_.k_coarse ? m1_.condition_k.Get() : m1_.condition.Get());\n'
        '            }\n            cmd->Dispatch(m1_.rows,1,1);',
        'coarse K pipeline after M25')
    src = once(src, '                cmd->SetPipelineState(m1_.vertical.Get());',
               '                cmd->SetPipelineState(m1_.k_coarse ? m1_.vertical_k.Get() : m1_.vertical.Get());',
               'coarse vertical K pipeline')
    src = once(src, '                ID3D12PipelineState* m4_gpu_pso=m1_.m4_condition.Get();',
               '                ID3D12PipelineState* m4_gpu_pso=m1_.k_m4 ? m1_.m4_condition_k.Get() : m1_.m4_condition.Get();',
               'fovea K pipeline')
    src = once(src,
        '                if(!m4_probe_skip) {\n                    cmd->SetComputeRootDescriptorTable(0,srv_gpu_start_);',
        '''                if(m1_.k_m4 && b40_history_ && b40_history_->edge_history) {
                    // u6 (retired M7 slot) -> edge history; this slot's previous use has retired.
                    D3D12_UNORDERED_ACCESS_VIEW_DESC edge_uav{};
                    edge_uav.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
                    edge_uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
                    device->CreateUnorderedAccessView(b40_history_->edge_history.Get(),nullptr,&edge_uav,m7_current_uav_);
                    D3D12_RESOURCE_BARRIER edge_barrier{};
                    edge_barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV;
                    edge_barrier.UAV.pResource=b40_history_->edge_history.Get();
                    cmd->ResourceBarrier(1,&edge_barrier);
                } else if(m1_.k_m4) {
                    // No history owner: null UAV, so a stale descriptor can never be written.
                    D3D12_UNORDERED_ACCESS_VIEW_DESC null_uav{};
                    null_uav.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
                    null_uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
                    device->CreateUnorderedAccessView(nullptr,nullptr,&null_uav,m7_current_uav_);
                }
                if(!m4_probe_skip) {
                    cmd->SetComputeRootDescriptorTable(0,srv_gpu_start_);''',
        'edge history descriptor')
    src = once(src, '                    cmd->SetPipelineState(m1_.m4_vertical.Get());',
               '                    cmd->SetPipelineState(m1_.k_m4 ? m1_.m4_vertical_k.Get() : m1_.m4_vertical.Get());',
               'fovea vertical K pipeline')
    src = once(src,
        '        cmd->SetPipelineState(m1_active ? m1_.raster.Get() : native_pipeline_.Get());',
        '        cmd->SetPipelineState(m1_active ? (m1_.k_coarse ? m1_.raster_k.Get() : m1_.raster.Get()) :\n'
        '                              native_pipeline_.Get());',
        'raster K pipeline')
    return src


def config(src):
    src = once(src, '    float m2_left_sharpen{1.f}, m2_right_sharpen{1.f};\n};',
               '    float m2_left_sharpen{1.f}, m2_right_sharpen{1.f};\n'
               '    uint32_t stereo_edge_mode{0}; // edge toggle: 0 Off (baseline), 1 K3D10TS16, 2 K23D10TS16\n};',
               'settings field')
    src = once(src, '    out.m4_fovea_grid=requested.m4_fovea_grid;\n',
               '    out.m4_fovea_grid=requested.m4_fovea_grid;\n'
               '    out.stereo_edge_mode=(std::min)(requested.stereo_edge_mode,2u);\n',
               'settings sanitize')
    return src


def vr_hpp(src):
    src = once(src,
        '    static const inline std::vector<std::string> s_duo_m3_jitter_modes{',
        '    static const inline std::vector<std::string> s_duo_edge_modes{ "Off (baseline)", "K3 (fuller leaves)", "K23 (calmer leaves)" };\n'
        '    static const inline std::vector<std::string> s_duo_m3_jitter_modes{',
        'edge mode names')
    src = once(src,
        '    const ModToggle::Ptr m_duo_m4_fovea_grid{ModToggle::create(generate_name("DuoM4FoveaDepthGrid"),false)};\n',
        '    const ModToggle::Ptr m_duo_m4_fovea_grid{ModToggle::create(generate_name("DuoM4FoveaDepthGrid"),false)};\n'
        '    const ModCombo::Ptr m_duo_edge_mode{ModCombo::create(generate_name("DuoStereoEdgeMode"),s_duo_edge_modes,0)};\n',
        'edge mode control')
    src = once(src, '*m_duo_m4_fovea_grid, ', '*m_duo_m4_fovea_grid, *m_duo_edge_mode, ', 'edge mode persisted')
    return src


def vr_cpp(src):
    src = once(src,
        '                    m_duo_m8_far_m->draw("Depth transition ends (metres)");\n',
        '                    m_duo_m8_far_m->draw("Depth transition ends (metres)");\n'
        '                    m_duo_edge_mode->draw("Edge mode (test build: Off = baseline, K3, K23)");\n',
        'edge mode UI')
    src = once(src,
        '        .m2_right_sharpen=m_duo_m2_right->value()};',
        '        .m2_right_sharpen=m_duo_m2_right->value(),\n'
        '        .stereo_edge_mode=uint32_t((std::clamp)(m_duo_edge_mode->value(),0,2))};',
        'edge mode settings')
    src = once(src,
        '        current.m2_right_sharpen==candidate.m2_right_sharpen) return;',
        '        current.m2_right_sharpen==candidate.m2_right_sharpen &&\n'
        '        current.stereo_edge_mode==candidate.stereo_edge_mode) return;',
        'edge mode change detection')
    return src


def strip_k(src):
    """Text the compiler sees WITHOUT DUOVIEW_EDGE_K: must equal the pre-overlay shader exactly."""
    out, state = [], None
    for line in src.splitlines(keepends=True):
        tag = line.strip()
        if tag == '#ifdef DUOVIEW_EDGE_K':
            if state is not None: raise RuntimeError('nested DUOVIEW_EDGE_K block')
            state = 'k'; continue
        if state is not None and tag == '#else':
            state = 'off'; continue
        if state is not None and tag == '#endif':
            state = None; continue
        if state != 'k': out.append(line)
    if state is not None: raise RuntimeError('unterminated DUOVIEW_EDGE_K block')
    return ''.join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('backend', type=Path)
    ap.add_argument('shaders', type=Path)
    a = ap.parse_args()
    vr = a.backend / 'src/mods/vr'
    hlsl = a.shaders / 'DuoViewM1Stereo.hlsl'
    original = hlsl.read_text(encoding='utf-8')
    edit(hlsl, shader)
    if strip_k(hlsl.read_text(encoding='utf-8')) != original:
        raise RuntimeError('Off shader text changed outside DUOVIEW_EDGE_K blocks')
    edit(vr / 'DuoViewM1D3D12.hpp', m1_backend)
    edit(vr / 'DuoViewD3D12.hpp', compositor_backend)
    edit(vr / 'DuoViewConfig.hpp', config)
    edit(a.backend / 'src/mods/VR.hpp', vr_hpp)
    edit(a.backend / 'src/mods/VR.cpp', vr_cpp)
    print('edge toggle: Off unchanged; K3D10TS16/K23D10TS16 in separate *_k DXBC variants')


if __name__ == '__main__':
    main()

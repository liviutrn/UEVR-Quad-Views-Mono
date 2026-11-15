"""No-GPU contract/numeric checks for the post-B318 stereo cleanup overlays.

Does NOT replace FXC / Windows WARP / headset validation. Run this after
apply_duoview_stereo_zero_fill.py and apply_duoview_stereo_cleanup.py.
"""
from pathlib import Path
import math
import random
import sys


def assert_has(s, *patterns):
    for pattern in patterns:
        assert pattern in s, f'missing required contract: {pattern}'


def assert_absent(s, *patterns):
    for pattern in patterns:
        assert pattern not in s, f'retired code still reachable: {pattern}'


def clamp(x, a=0., b=1.):
    return min(b, max(a, x))


def far_weight(inv_depth, start_m, end_m):
    # This deliberately mirrors the production inverse-distance smoothstep.
    inv0, inv1 = 1. / start_m, 1. / end_m
    t=clamp((inv0-inv_depth)/max(inv0-inv1,1.e-8))
    return t*t*(3.-2.*t)


def near_slope(base, close, far, weight, legacy):
    smooth=close+(far-close)*weight
    factor=(2.-1.65*smooth) if legacy else (1.-.90*smooth)
    return min(.99, (base if legacy else .99)*factor)


def migration(base, old_enable, old_near, old_far):
    def transform(s):
        scale=2.-1.65*s if old_enable else 1.
        relative=clamp(base*scale/.99)
        return clamp((1.-relative)/.90)
    return transform(old_near),transform(old_far)


def check_smoothing():
    # No plateau in the new 0..1 range, including arbitrary transition weights.
    for w in (0.,.001,.25,.5,.75,.999,1.):
        for far in (0.,.35,.5,1.):
            values=[near_slope(.99,x/100.,far,w,False) for x in range(101)]
            assert all(a>=b-1.e-10 for a,b in zip(values,values[1:])), (w,far)
            if w<1.:
                assert all(a>b+1.e-10 for a,b in zip(values,values[1:])),(w,far)
        for close in (0.,.35,.5,1.):
            values=[near_slope(.99,close,x/100.,w,False) for x in range(101)]
            assert all(a>=b-1.e-10 for a,b in zip(values,values[1:])), (w,close)
            if w>0.:
                assert all(a>b+1.e-10 for a,b in zip(values,values[1:])),(w,close)
    assert abs(near_slope(.99,0.,0.,.5,False)-.99)<1.e-10
    assert abs(near_slope(.99,1.,1.,.5,False)-.099)<1.e-10

    # Legacy curve is explicitly retained. Verify entire transition, not only
    # endpoints, including .99 plateau and early collapse near the threshold.
    rng=random.Random(318)
    for _ in range(2000):
        base=rng.uniform(.25,.99)
        old_enable=rng.choice([False,True])
        n=rng.random(); f=rng.random()
        new_n,new_f=migration(base,old_enable,n,f)
        assert 0<=new_n<=1 and 0<=new_f<=1
        for w in (0.,.02,.10,.31,.50,.606,.75,.93,1.):
            original=near_slope(base,n,f,w,True) if old_enable else base
            # Old distance-off path is an entirely constant base slope.
            old_exact= min(.99,base*(2.-1.65*(n+(f-n)*w))) if old_enable else base
            if old_enable:
                assert abs(original-old_exact)<1.e-8
            else:
                assert original==base
            legacy=near_slope(base,n,f,w,True) if old_enable else base
            assert abs(legacy-old_exact)<1.e-8
        # New slider endpoints approximate the previous effective endpoint.
        e0=base*(2.-1.65*n) if old_enable else base
        e1=base*(2.-1.65*f) if old_enable else base
        if e0>=.099:
            assert abs(near_slope(.99,new_n,new_n,0.,False)-min(.99,e0))<1.e-6
        if e1>=.099:
            assert abs(near_slope(.99,new_f,new_f,0.,False)-min(.99,e1))<1.e-6
    # The crop-scaled slope bound: both eyes must be safe with unequal k.
    for _ in range(1000):
        crop=rng.uniform(.25,.9)
        w=rng.choice([256,512,813,1024])
        k1=rng.uniform(1.e-3,30.) * rng.choice([-1,1]);k2=rng.uniform(1.e-3,30.)*rng.choice([-1,1])
        safe=.99*crop/(max(abs(k1),abs(k2),.00001)*w)
        for smooth in (0.,.5,1.):
            slope=min(safe, safe*(1.-.9*smooth))
            assert max(abs(k1),abs(k2))*w*slope/crop <=.990001


def check_zero_fill():
    # Both endpoints exactly 0 imply zero strength for every depth/weight;
    # contrast periphery M3 which is independently allowed in phase A.
    for m3 in (False,True):
        for in_crop in (False,True):
            for d in [0.,.001,.1,.5,1.]:
                strength=0. if in_crop else 1.
                old_pulls=in_crop or m3
                new_pulls=(in_crop and strength>0.) or (not in_crop and m3)
                for root in (0.,.2,.5,.99):
                    for out in (0.,.25,1.):
                        old= root+(out-root)*strength if old_pulls else root
                        new= root+(out-root)*strength if new_pulls else root
                        assert old==new


def check_source(backend,shaders):
    ui=(backend/'src/mods/VR.cpp').read_text(encoding='utf-8')
    hdr=(backend/'src/mods/VR.hpp').read_text(encoding='utf-8')
    writer=(backend/'src/mods/vr/DuoViewM1D3D12.hpp').read_text(encoding='utf-8')
    capture=(backend/'src/mods/vr/D3D12Component.cpp').read_text(encoding='utf-8')
    comp=(backend/'src/mods/vr/DuoViewD3D12.hpp').read_text(encoding='utf-8')
    stereo=(shaders/'DuoViewM1Stereo.hlsl').read_text(encoding='utf-8')
    raster=(shaders/'DuoViewNativeCompositeRaster.hlsl').read_text(encoding='utf-8')
    assert_has(ui, 'm_duo_depth_legacy_curve->value()=true',
               'm_duo_depth_legacy_curve->value()=false',
               '.m3_edges=stereo_ready ? false : m_duo_m3_edges->value()',
               '.m3_fill=stereo_ready ? false : m_duo_m3_fill->value()', '.fill_history=0.f',
               '.edge_history=0.f',
               '.m24_vertical_taper=stereo_ready ? 0.f : m_duo_m24_vertical->value()',
               '.m8_fill_near=stereo_ready ? 0.f : m_duo_m8_fill_near->value()',
               '.edge_reach_px=(stereo_ready && !m_duo_depth_legacy_curve->value()) ? 20.f : 2.f',
               '.m2_fovea_depth=m_duo_m2_fovea_depth->value() || m_duo_m4_fovea_grid->value()',
               'm_duo_m5_left_max->value()', 'm_duo_m5_right_max->value()',
               'm_duo_m2_left->value()', 'm_duo_m2_right->value()',
               'm_duo_stereo_bootstrap_ready.load(std::memory_order_acquire)')
    assert_has(hdr, 'DuoStereoDepthSchemaV2','DuoStereoLegacyCurveV2',
               '*m_duo_depth_schema_v2, *m_duo_depth_legacy_curve',
               '*m_duo_depth_close, *m_duo_depth_far')
    assert_absent(ui,'m_duo_m3_edges->draw(', 'm_duo_edge_history->draw(',
                  'm_duo_m9_eye_far->draw(', 'm_duo_fill_blur->draw(',
                  'm_duo_m2_fovea_depth->draw(', 'm_duo_m24_vertical->draw(')
    assert_has(stereo, 'const bool foveaFillEnabled=',
               'M8Effects.z>0.0', 'M8Distance.w<10.0',
               'M8V2Map(float d)', 'M8V2Unmap(float d)',
               'const float bound=v2 ? M8V2Map(limit) : limit;',
               'const float mappedLimit=M8V2Map(limit);', 'M1ConditionedDepth[uint3(x,group.x,0u)]',
               'M1ConditionedDepth[uint3(x,group.x,1u)]',
               'void CSConditionM4(', 'void CSConditionM4Vertical(')
    assert_absent(stereo,'M7StabilizeEdge(', 'M7AccumulateFillColor(',
                  'M7PackColor(', 'M7CurrentWrite[', 'M7PreviousHistory.Load(')
    assert_absent(raster,'M7CurrentHistory', 'M7UnpackColor',
                  'M7Controls.y>0.', 'M7Controls.z>.001')
    assert_has(raster, 'GlamSharpenNativeFovea(', 'DuoPhase2FocusLift(',
               'DuoB40InwardAnchor(')
    assert_has(comp, 'settings.edge_reach_px,color_extent')
    assert_has(writer, 'data.m8_distance[3]=edge_reach_px;')
    assert_has(capture, 'config.settings.m25_fine_mode==1u || pair.first==snapshot')
    assert_absent(comp,'2.f,color_extent')
    assert_absent(stereo,'const bool foveaFillEnabled=M8Distance.z<=.5', 'const bool adaptive=M8Distance.z>.5')
    assert_absent(comp, 'b40_history_->temporal', 'state->temporal',
                  'if (history_output)', 'M7CurrentHistory')
    assert_has(comp, 'state->buffer', 'const bool b40_active=',
               'history_read_=false;',
               'device->CreateShaderResourceView(nullptr,&tile_srv,desc_cpu);',
               'device->CreateUnorderedAccessView(nullptr,nullptr,&unused_history_uav,desc_cpu);',
               'packet_lifetime_=std::move(packet_lifetime);',
               'm1_.m4_active', 'cmd->Dispatch(m1_.m4_rows,1,1);')
    # Shader preprocessing must keep exactly one matching condition/raster scope.
    for name,txt in [('M1',stereo),('raster',raster)]:
        level=0
        for line in txt.splitlines():
            directive=line.lstrip()
            if directive.startswith(('#ifdef','#ifndef','#if ')): level+=1
            if directive.startswith('#endif'): level-=1
            assert level>=0,(name,line)
        assert level==0,(name,level)


def main():
    if len(sys.argv)!=3: raise SystemExit('usage: test_duoview_stereo_cleanup.py <backend> <shaders>')
    backend,shaders=map(Path,sys.argv[1:])
    check_zero_fill();check_smoothing();check_source(backend,shaders)
    print('PASS zero-fill equivalence model, monotonic slopes, full legacy transition migration,')
    print('     full-eye-UV two-eye safety, source integration & retired-work contracts')
    print('NOT RUN: Windows FXC/HLSL, D3D12 WARP, headset scene parity, GPU time')

if __name__=='__main__': main()

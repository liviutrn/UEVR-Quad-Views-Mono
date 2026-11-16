#!/usr/bin/env python3
"""Frozen baseline-only evaluator. GT is never supplied to the compositor."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import score_warp_v3 as old
from edge_math import PROFILES, knee, v2_map

W,H=old.W,old.H
DEPTH={0:old.s.D_BG,1:old.s.D_MID,2:old.s.D_FG}
REGIONS=('valid','edge','near_edge','halo','halo_id0','halo_id1','hole_id0','hole_id1',
         'fovea_core','periphery_outer','blend')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def unpack(path):
    a=np.fromfile(path,np.uint8)
    if a.size!=H*W*2*4:
        raise RuntimeError('Invalid probe byte count '+str(path))
    # File BGRA -> the four RGBA encoded bytes, without imposing alpha=255.
    return a.reshape(H,W*2,4)[:,:,[2,1,0,3]].astype(np.uint32)

def floats(path):
    a=unpack(path)
    q=a[:,:,0]|(a[:,:,1]<<8)|(a[:,:,2]<<16)|(a[:,:,3]<<24)
    return np.ascontiguousarray(q).view(np.float32)

def uv(path):
    a=unpack(path)
    x=(a[:,:,0]+(a[:,:,1]<<8)).astype(np.float64)/65535*W-.5
    y=(a[:,:,2]+(a[:,:,3]<<8)).astype(np.float64)/65535*H-.5
    return x,y

def expected_constants(p,eye,zero):
    k=0. if zero else (1. if eye==0 else -1.)*13/W
    return {0:p.close,1:p.far,2:1/p.start_m,3:1/p.end_m,4:1.,5:17.,
            6:0. if p.near_m==0 else 1/p.near_m,7:p.softness/(max(abs(k),.00001)*W),
            8:float(W),9:float(W),10:1.,11:k,12:.5,13:.25,14:.75,15:12.5}

def validate_profile(folder,profile):
    p=PROFILES[profile]
    for mode in ('rgb','uv','depth','constants'):
        rows=[json.loads(z) for z in (folder/mode/'recon_v3_capture_contract.jsonl').read_text().splitlines()]
        if len(rows)!=40 or len({r['file'] for r in rows})!=40:
            raise RuntimeError('Missing/duplicate profile capture records')
        old.validate_capture_contract(folder/mode)
        for r in rows:
            if r.get('profile')!=profile or r.get('probe')!=mode or r.get('legacy_curve') is not False or r.get('schema')!='effective_v2':
                raise RuntimeError('Wrong effective profile/mode/schema')
            for key,expected in {'close':p.close,'far':p.far,'start_m':p.start_m,'end_m':p.end_m,
                                 'near_m':p.near_m,'softness':p.softness}.items():
                if abs(r[key]-expected)>2e-6:
                    raise RuntimeError(f'Wrong profile {key}: {r[key]} != {expected}')
            if mode=='constants':
                values=floats(folder/mode/r['file'])
                if not np.isfinite(values).all():
                    raise RuntimeError('Nonfinite shader constant readback')
                for eye in (0,1):
                    for col,expected in expected_constants(p,eye,r['calibration']).items():
                        got=values[H//2,eye*W+col]
                        if abs(float(got)-expected)>max(2e-6,abs(expected)*2e-5):
                            raise RuntimeError(f'GPU effective constant mismatch {profile} col{col} {got} != {expected}')
            if mode=='uv' and r['calibration']:
                sx,sy=uv(folder/mode/r['file'])
                yy,xx=np.indices((H,W))
                for eye in (0,1):
                    if np.max(np.abs(sx[:,eye*W:(eye+1)*W]-xx))>.01 or np.max(np.abs(sy[:,eye*W:(eye+1)*W]-yy))>.01:
                        raise RuntimeError('Zero-strength packed UV readback is not identity')
    return {'pass':True,'shader_constant_readback':True,'records_per_mode':40,'profile':asdict(p)}

def geometric_masks(ids,centerids,eye,pan,p):
    """Per source row/run and adjacent farther ID, not frame-global max gap.

    k>0: source right boundary -> hole ends at edge-k*D_background;
    k<0: source left boundary -> hole ends at edge-k*D_background.
    Band extends AWAY from that visible-background origin by the full mapped
    cone support, plus conservative 8-source-pixel seed/filter/solver guard.
    Affine H inversion is evaluated row-wise in source coordinates. Overlaps
    union; only valid, reprojectably visible pixels of the adjacent layer count.
    """
    # stereo_lab.grid returns (x,y), NOT numpy.indices' (y,x).
    # Original V3 masks swapped them; preserve its capture/calibration checks,
    # but never carry that coordinate bug into the new frozen baseline.
    xx,yy=old.s.grid(); hx,hy=old.s.Hcoords(xx,yy,eye,pan)
    sign=1 if eye=='left' else -1
    depths=np.choose(ids,[DEPTH[0],DEPTH[1],DEPTH[2]])
    sx=hx+sign*13*depths
    bounded=(sx>=.5)&(sx<W-1.5)&(hy>=.5)&(hy<H-1.5)
    center_id=cv2.remap(centerids,sx.astype(np.float32),hy.astype(np.float32),cv2.INTER_NEAREST,
                        borderMode=cv2.BORDER_CONSTANT,borderValue=255)
    edge=cv2.dilate(ids,np.ones((3,3),np.uint8))!=cv2.erode(ids,np.ones((3,3),np.uint8))
    edge=cv2.dilate(edge.astype(np.uint8),np.ones((5,5),np.uint8)).astype(bool)
    valid=(xx>=4)&(xx<W-4)&(yy>=4)&(yy<H-4)
    m={'visible':bounded&(center_id==ids)&valid,'disoccluded':bounded&(center_id!=ids)&valid,
       'edge':edge&valid,'near_edge':edge&(ids==2)&valid,'valid':valid,
       'out_of_source':(~bounded)&valid}
    halo=np.zeros((H,W),bool)
    events=[]
    pen=min(.99,p.softness)/13.
    # GT/settings only. Eight source pixels conservatively cover the 5x5
    # fine-to-coarse seed footprint, 3x3 coarse seeds and linear/filter edges.
    guard=8.
    for y in range(H):
        sy=int(np.clip(np.rint(hy[y,0]),0,H-1))
        row=centerids[sy]
        for boundary in np.flatnonzero(row[1:]!=row[:-1])+1:
            left,right=int(row[boundary-1]),int(row[boundary])
            fg,bg=(left,right) if sign>0 else (right,left)
            if DEPTH[fg]<=DEPTH[bg]:
                continue
            f,b=knee(DEPTH[fg],p),knee(DEPTH[bg],p)
            radius=max(0.,(v2_map(f,p)-v2_map(b,p))/pen)+guard
            # Integer nearest ID transition lies half-way between source centers.
            origin=(boundary-.5)-sign*13*DEPTH[bg]
            distance=sign*(hx[y]-origin)
            halo[y]|=(distance>=0)&(distance<=radius)&(ids[y]==bg)
            events.append((fg,bg,float(radius)))
    halo &= m['visible']
    m.update({'halo':halo,'halo_id0':halo&(ids==0),'halo_id1':halo&(ids==1),
              'hole_id0':m['disoccluded']&(ids==0),
              'hole_id1':m['disoccluded']&(ids==1)})
    rm=old.region_masks(m)
    m['fovea_core']=rm['fovea_core'];m['periphery_outer']=rm['periphery_outer']
    m['blend']=m['valid']&~(m['fovea_core']|m['periphery_outer'])
    for base in ('halo','hole_id0','hole_id1','near_edge','edge'):
        for region in ('fovea_core','periphery_outer','blend'):
            m[region+'_'+base]=m[region]&m[base]
    return m,{'row_run_events':len(events),'max_source_radius_including_guard':max((z[2] for z in events),default=0.),
              'seed_filter_guard_source_px':guard,'vertical_policy':'P1/P2 vertical taper zero; P0 preserved neutral control'}

def temporal(a,b,ga,gb,mask):
    # Convert before subtraction: unsigned arithmetic is explicitly prohibited.
    residual=np.abs((b.astype(np.int16)-a.astype(np.int16))-
                    (gb.astype(np.int16)-ga.astype(np.int16))).mean(axis=2)
    out=old.summary(residual,mask)
    out['normalized']=out['mae_rgb8']/255 if out['count'] else None
    return out

def paired_delta(candidate,baseline):
    if candidate['count']!=baseline['count']:
        raise RuntimeError('Temporal pair ROI changed')
    if not baseline['count']:
        return {'delta':None,'relative_pct':None,'regression':None,'status':'EMPTY_NOT_PASS'}
    a,b=candidate['normalized'],baseline['normalized']
    return {'delta':a-b,'relative_pct':100*(a-b)/b if b else None,
            'limit':max(.00005,.05*b),'regression':a-b>max(.00005,.05*b),
            'status':'MEASURED'}

def integrity(pred,gt,mask):
    a=(pred==2)&mask;b=(gt==2)&mask
    union=int((a|b).sum());inter=int((a&b).sum())
    return {'intersection':inter,'union':union,'iou':inter/union if union else None,
            'false_positive':int((a&~b).sum()),'false_negative':int((b&~a).sum()),
            'status':'MEASURED' if union else 'EMPTY_NOT_PASS'}

def evaluate(corpus,captures,out):
    out.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((corpus/'manifest.json').read_text())
    all_results={}
    for profile,p in PROFILES.items():
        folder=captures/profile
        checks=validate_profile(folder,profile)
        verification=old.verify(corpus,Path(old.__file__).parent/'expected.json',old.s)
        calibration=old.calibrate(corpus,folder/'rgb',manifest['scenes'])
        if not calibration['pass']:
            raise RuntimeError('Original frozen calibration invalid '+profile)
        checks['corpus']=verification
        checks['zero_calibration']=calibration
        rows=[];transitions=[];stored={};pooled={}
        for record in manifest['scenes']:
            name,scene,pan=record['files_dir'],record['scene'],record['pan_mode']
            sc=old.s.texture_layers(scene)
            for fr in range(4):
                _,_,centerids,_=old.s.render(sc,'center',fr,scene,False,
                    cam_move=record['camera_moves'],physical_move=record['foreground_moves'])
                fn=f'recon_v3_{name}_f{fr}.bgra'
                image=old.rgb(folder/'rgb'/fn,True)
                sx,sy=uv(folder/'uv'/fn)
                depth=floats(folder/'depth'/fn)
                if not np.isfinite(depth).all() or depth.min()<0 or depth.max()>12.5001:
                    raise RuntimeError('Invalid conditioned depth readback')
                for ei,eye in enumerate(('left','right')):
                    got=image[:,ei*W:(ei+1)*W]
                    gt=old.rgb(corpus/name/f'{fr:02}_gt_{eye}.bgra')
                    ids=np.fromfile(corpus/name/f'{fr:02}_gt_{eye}_ids.u8',np.uint8).reshape(H,W)
                    m,geometry=geometric_masks(ids,centerids,eye,pan,p)
                    error=np.abs(got.astype(np.int16)-gt.astype(np.int16)).mean(axis=2)
                    x=sx[:,ei*W:(ei+1)*W];y=sy[:,ei*W:(ei+1)*W]
                    # Actual GPU source lookup, categorical nearest center ID.
                    # Texture filtering can mix owners; this measures warp-center
                    # ownership, NOT a claim of filter-footprint purity.
                    pred=cv2.remap(centerids,x.astype(np.float32),y.astype(np.float32),cv2.INTER_NEAREST,
                                   borderMode=cv2.BORDER_CONSTANT,borderValue=255)
                    gt_depth=np.choose(ids,[DEPTH[0],DEPTH[1],DEPTH[2]])
                    dep=depth[:,ei*W:(ei+1)*W]
                    de=np.abs(dep-gt_depth)
                    regions={k:old.summary(error,m[k]) for k in m if k not in ('out_of_source',)}
                    depth_scores={k:old.summary(de,m[k]) for k in REGIONS}
                    row={'scene':name,'eye':eye,'frame':fr,'regions':regions,'geometry':geometry,
                         'foreground':{r:integrity(pred,ids,m[r]) for r in ('valid','fovea_core','periphery_outer','blend')},
                         'depth_inverse_m':depth_scores,
                         'hole_no_harm':{k:{'baseline':regions[k],'delta_mae_rgb8':0. if regions[k]['count'] else None,
                                           'status':'BASELINE_SELF_REFERENCE' if regions[k]['count'] else 'EMPTY_NOT_PASS'}
                                         for k in ('hole_id0','hole_id1')}}
                    rows.append(row);stored[name,eye,fr]=(got,gt,m)
                    for k in regions:
                        pooled.setdefault((name,eye,k),[]).append(error[m[k]])
            for eye in ('left','right'):
                for fr in range(3):
                    a,ga,ma=stored[name,eye,fr];b,gb,mb=stored[name,eye,fr+1]
                    metrics={}
                    # Both a union of GT masks and their fixed spatial partitions.
                    for k in ('edge','halo','valid','fovea_core','periphery_outer','blend',
                              'fovea_core_edge','periphery_outer_edge','blend_edge',
                              'fovea_core_halo','periphery_outer_halo','blend_halo'):
                        mask=ma[k]|mb[k]
                        v=temporal(a,b,ga,gb,mask)
                        metrics[k]={**v,'baseline_delta':paired_delta(v,v)}
                    transitions.append({'scene':name,'eye':eye,'from_frame':fr,'to_frame':fr+1,'regions':metrics})
        if len(rows)!=40 or len(transitions)!=30:
            raise RuntimeError('Incorrect frame/transition count')
        summaries=[]
        for name in old.EXPECTED_SCENES:
            for eye in ('left','right'):
                frs=[z for z in rows if z['scene']==name and z['eye']==eye]
                regions={k:old.summary(np.concatenate(pooled[name,eye,k]),np.ones(sum(len(v) for v in pooled[name,eye,k]),bool))
                         for k in REGIONS}
                fg=frs[0]['foreground'].keys()
                fgs={}
                for r in fg:
                    inter=sum(z['foreground'][r]['intersection'] for z in frs)
                    union=sum(z['foreground'][r]['union'] for z in frs)
                    fgs[r]={'intersection':inter,'union':union,'iou':inter/union if union else None}
                trs=[z for z in transitions if z['scene']==name and z['eye']==eye]
                temporal_worst={k:max((z['regions'][k]['normalized'] for z in trs if z['regions'][k]['count']),default=None)
                                for k in trs[0]['regions']}
                summaries.append({'scene':name,'eye':eye,'regions':regions,'foreground':fgs,'temporal_worst':temporal_worst})
        result={'evidence':'CI WARP when externally executed; no headset/RTX claim',
                'profile_validation':checks,'frames':rows,'transitions':transitions,'scene_eye':summaries,
                'empty_policy':'count=0 => null / EMPTY_NOT_PASS. Required targets >=16 pooled pixels; missing required region => INVALID.',
                'comparison':'Baseline self-reference only; all reported deltas zero. No candidate rendered or scored.'}
        for z in summaries:
            if z['scene'] in old.EXPECTED_SCENES[:2] and z['regions']['halo']['count']<16:
                raise RuntimeError('Required target halo too small')
        (out/(profile+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        all_results[profile]=result
    hashes={str(p.relative_to(captures)):sha(p) for p in sorted(captures.rglob('*')) if p.is_file()}
    hashes.update({'scorer/'+p.name:sha(p) for p in (Path(__file__),Path(old.__file__),Path(__file__).with_name('edge_math.py'))})
    (out/'hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    (out/'index.json').write_text(json.dumps({'profiles':list(all_results),'baseline_only':True,
        'frame_rows':sum(len(z['frames']) for z in all_results.values()),
        'transition_rows':sum(len(z['transitions']) for z in all_results.values()),
        'scorer_sha256':sha(Path(__file__)),'input_manifest_sha256':sha(corpus/'manifest.json')},indent=2),encoding='utf-8')
    return all_results

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--corpus',type=Path,required=True)
    ap.add_argument('--captures',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();evaluate(a.corpus,a.captures,a.out)
    print('EDGE_BASELINE valid: 3 profiles, 120 per-eye frames, 90 per-eye transitions; no candidate')

if __name__=='__main__':
    main()

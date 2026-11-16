#!/usr/bin/env python3
"""Evaluator-only metric-pinhole raycast quality score for 24 production WARP captures.

This is a DIFFERENT family from the V3 affine/inverse-depth benchmark.
Only independent raycast target RGB, metric Z and object IDs are accessed here.
Never import this scorer in the WARP input-upload fixture.
"""
from __future__ import annotations
import argparse,csv,hashlib,json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw

W,H=512,408
FOCAL=486.4
HALF_BASELINE=.032
SCENES=('occlusion','foliage','weapon')
RGB_CHANNELS=3

def sha256(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def rgb(path:Path,double=False):
    raw=np.fromfile(path,np.uint8)
    width=W*(2 if double else 1)
    if raw.size!=H*width*4:raise RuntimeError(f'Raycast BGRA8 dimensions mismatch: {path}: {raw.size}')
    image=raw.reshape(H,width,4)
    if not np.all(image[:,:,3]==255):raise RuntimeError(f'Raycast BGRA8 alpha invalid: {path}')
    return image[:,:,2::-1].copy()

def read_float(path):
    data=np.fromfile(path,'<f4')
    if len(data)!=W*H:raise RuntimeError('Raycast raw depth size mismatch: '+str(path))
    data=data.reshape(H,W)
    if not np.all(np.isfinite(data)) or not np.all(data>0):
        raise RuntimeError('Raycast nonphysical depth: '+str(path))
    return data

def verify_inputs(root:Path,expected:Path):
    m=json.loads((root/'raycast_replay_manifest.json').read_text())
    gold=json.loads(expected.read_text())
    if sha256(Path(__file__).parent/'stereo_ground_truth_fixture.py')!=gold['original_generator_sha256']:
        raise RuntimeError('Raycast original generator source does not match frozen baseline')
    if (m['width'],m['height'],m['focal_px'],m['baseline_m'],len(m['frames']))!=(W,H,FOCAL,2*HALF_BASELINE,12):
        raise RuntimeError('Raycast metric camera/input count mismatch')
    framekeys={(r['scene'],r['frame']) for r in m['frames']}
    if framekeys!={(s,fr) for s in SCENES for fr in range(4)}:
        raise RuntimeError('Raycast corpus missing or duplicate scene-frame')
    # Hash the generator's exact evaluator-only source and output binary input+GT.
    for row in m['frames']:
        prefix=row['scene']+'_f'+str(row['frame'])
        if set(row['input']) != {'source_full.bgra','source_fovea.bgra','raw_coarse.f32','raw_fine.f32'}:
            raise RuntimeError('Raycast shader input schema changed')
        if set(row['reference_only']) != {'gt_left.bgra','gt_right.bgra','gt_left_ids.u8','gt_right_ids.u8','gt_left_metric_z.f32','gt_right_metric_z.f32'}:
            raise RuntimeError('Raycast evaluator reference schema changed')
        for source in ('input','reference_only'):
            for kind,meta in row[source].items():
                p=root/(prefix+'_'+kind)
                if p.name!=meta['file'] or p.stat().st_size!=meta['bytes'] or sha256(p)!=meta['sha256']:
                    raise RuntimeError('Raycast input/GT manifest hash mismatch '+str(p))
                if gold['binary_sha256'].get(p.name)!=sha256(p):
                    raise RuntimeError('Raycast frozen independent baseline hash mismatch '+str(p))
    if len(gold['binary_sha256'])!=120:raise RuntimeError('Raycast expected hash count changed')
    return {'verified_frames':len(m['frames']),'verified_binary_files':120,'source_camera':'metric pinhole 512x408 focal486.4 baseline64mm',
            'source_script_sha256':gold['original_generator_sha256']}

def verify_gpu_contract(root:Path):
    path=root/'recon_raycast_capture_contract.jsonl'
    if not path.exists():raise RuntimeError('Missing raycast GPU output contract')
    rows=[json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    if len(rows)!=24:raise RuntimeError(f'Expected 24 paired raycast WARP captures, got {len(rows)}')
    wanted={(scene,fr,cal) for scene in SCENES for fr in range(4) for cal in (True,False)}
    if {(z['scene'],z['frame'],z['calibration']) for z in rows}!=wanted:raise RuntimeError('Raycast GPU scene/frame/calibration set differs')
    if len({(z['scene'],z['frame'],z['calibration']) for z in rows})!=24:raise RuntimeError('Raycast GPU duplicate capture record')
    if len({(z['generation'],z['frame_key']) for z in rows})!=24:raise RuntimeError('Raycast GPU duplicate frame-key')
    identity=[1,0,0,0, 0,1,0,0, 0,0,1,0]
    for z in rows:
        if (z['width'],z['height'])!=(W,H) or z['family']!='metric_pinhole' or z['eye_order']!='left_right' or z['output']!='doublewide_bgra8' or z['fine_depth']!='full_r32_inverse_metres':
            raise RuntimeError('Raycast WARP image/unit format contract mismatch')
        if z['active_rects']!={'periphery':[128,102],'fovea':[256,204]}:
            raise RuntimeError('Raycast active source rectangles changed')
        if abs(z['focal_px']-FOCAL)>1e-5 or abs(z['baseline_m']-.064)>1e-6:
            raise RuntimeError('Raycast focal/baseline changed')
        strength=0 if z['calibration'] else 1
        if abs(z['strength']-strength)>1e-7 or np.max(np.abs(np.asarray(z['eye_k'])-np.array([-.0304,+.0304])*strength))>1e-7:
            raise RuntimeError('Raycast WARP signed k mismatch')
        for h in z['homography']:
            if len(h)!=12 or np.max(np.abs(np.asarray(h)-np.asarray(identity)))>1e-6:
                raise RuntimeError('Raycast infinity homography must be identity')
        name=f'recon_raycast_{"zero_" if z["calibration"] else ""}{z["scene"]}_f{z["frame"]}.bgra'
        if z['file']!=name or not (root/name).is_file():raise RuntimeError('Raycast WARP output file missing')
        rgb(root/name,True) # Size and alpha check; never assume provider-capture completeness
    return {'pass':True,'records':24,'calibration_records':12,'stereo_records':12,'unique_frame_keys':True}

def native_expected(full:np.ndarray,aw,ah):
    # Match the GPU fixture's bilinear active-source upload, then bicubic
    # only for the periphery; do not use ideal GT to calibrate source sampling.
    yy,xx=np.indices((ah,aw),np.float32)
    fx=(xx+.5)*W/aw-.5;fy=(yy+.5)*H/ah-.5
    return cv2.remap(full,fx,fy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)

def calibration(root:Path,gpu:Path):
    xx,yy=np.meshgrid(np.arange(W),np.arange(H))
    core=(xx>=.30*W)&(xx<.70*W)&(yy>=.30*H)&(yy<.70*H)
    outer=((xx<.2*W)|(xx>.8*W)|(yy<.2*H)|(yy>.8*H))&(xx>=6)&(xx<W-6)&(yy>=6)&(yy<H-6)
    rows=[]
    for scene in SCENES:
        for fr in range(4):
            out=rgb(gpu/f'recon_raycast_zero_{scene}_f{fr}.bgra',True)
            left,right=out[:,:W],out[:,W:]
            if not np.array_equal(left,right):raise RuntimeError(f'Raycast zero eyes differ: {scene}, frame{fr}')
            prefix=f'{scene}_f{fr}_'
            fov_native=native_expected(rgb(root/(prefix+'source_fovea.bgra')),W//2,H//2)
            native_region=left[H//4:3*H//4,W//4:3*W//4]
            fm=float(np.abs(native_region.astype(np.int16)-fov_native.astype(np.int16))[core[H//4:3*H//4,W//4:3*W//4]].mean())
            periph=native_expected(rgb(root/(prefix+'source_full.bgra')),W//4,H//4)
            periph_up=np.asarray(Image.fromarray(periph,'RGB').resize((W,H),Image.Resampling.BICUBIC))
            pm=float(np.abs(left.astype(np.int16)-periph_up.astype(np.int16))[outer].mean())
            rows.append({'scene':scene,'frame':fr,'zero_eyes_equal':True,'fovea_core_rgb8':fm,'periphery_outer_rgb8':pm,'pass':fm<=2.5 and pm<=3.0})
    return {'pass':len(rows)==12 and all(r['pass'] for r in rows),'records':rows,
            'thresholds_rgb8':{'fovea_core':2.5,'periphery_outer':3.0}}

def masked_score(err,mask):
    v=err[mask]
    return {'count':int(v.size),'mean':float(np.mean(v)) if len(v) else None,
            'p95':float(np.percentile(v,95)) if len(v) else None,
            'p99':float(np.percentile(v,99)) if len(v) else None}

def pair_stats(zero_error,stereo_error,mask):
    a=masked_score(zero_error,mask);b=masked_score(stereo_error,mask)
    return {'pixels':a['count'],'zero_mae':a['mean'],'stereo_mae':b['mean'],
            'delta':b['mean']-a['mean'] if b['mean'] is not None else None,
            'zero_p99':a['p99'],'stereo_p99':b['p99']}

def derive_masks(corpus:Path,original:Path,scene:str,fr:int,eye:str,ids:np.ndarray,zmet:np.ndarray):
    xx,yy=np.meshgrid(np.arange(W,dtype=np.float32),np.arange(H,dtype=np.float32))
    sign=-1 if eye=='left' else 1
    source_x=xx+sign*FOCAL*HALF_BASELINE/zmet
    valid=(xx>=5)&(xx<W-5)&(yy>=5)&(yy<H-5)
    in_bounds=(source_x>=1)&(source_x<W-2)&(yy>=1)&(yy<H-2)
    mono_ids=np.asarray(Image.open(original/f'{scene}_f{fr}_mono_object_id.png').convert('L'))
    if mono_ids.shape!=(H,W):raise RuntimeError('Original raycast mono IDs invalid')
    source_id=cv2.remap(mono_ids,source_x.astype(np.float32),yy,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=255)
    inv=read_float(corpus/f'{scene}_f{fr}_raw_coarse.f32')
    inv_src=cv2.remap(inv,source_x.astype(np.float32),yy,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=0.)
    z_ok=np.abs(1/np.maximum(inv_src,1e-8)-zmet)<.02
    visible=valid&in_bounds&(source_id==ids)&z_ok
    hidden=valid&in_bounds&~visible
    edge=(cv2.dilate(ids,np.ones((3,3),np.uint8))!=cv2.erode(ids,np.ones((3,3),np.uint8)))
    near=edge&(zmet<=3.1)
    # Avoid fovea blend/seam, selecting solid central region only.
    core=(xx>=.30*W)&(xx<.70*W)&(yy>=.30*H)&(yy<.70*H)
    outer=(xx<.2*W)|(xx>.8*W)|(yy<.2*H)|(yy>.8*H)
    return {'valid':valid,'visible':visible,'occluded':hidden,'object_edge':valid&edge,'near_object_edge':valid&near,
            'fovea_core':valid&core,'periphery_outer':valid&outer,
            'fovea_core_near_edge':valid&core&near,
            'periphery_near_edge':valid&outer&near,
            'fovea_core_occluded':valid&core&hidden,'periphery_occluded':valid&outer&hidden}

def pool(rows):
    output={}
    if not rows:return output
    for region in rows[0]['regions']:
        r=[a['regions'][region] for a in rows if a['regions'][region]['pixels']]
        if not r:continue
        n=sum(a['pixels'] for a in r)
        z=sum(a['zero_mae']*a['pixels'] for a in r)/n
        s=sum(a['stereo_mae']*a['pixels'] for a in r)/n
        output[region]={'pixels':n,'zero_mae':z,'stereo_mae':s,'delta':s-z,
                        'relative_gain_pct':100*(z-s)/z if z>1e-8 else None,
                        'worse_frame_eye_count':sum(a['delta']>0 for a in r)}
    return output

def score(corpus,gpu,original,expected,out):
    iv=verify_inputs(corpus,expected);cv=verify_gpu_contract(gpu)
    cal=calibration(corpus,gpu)
    out.mkdir(parents=True,exist_ok=True)
    if not cal['pass']:
        r={'valid_scoring':False,'reason':'12/12 raycast zero-stereo source registration failed','inputs':iv,'contract':cv,'calibration':cal}
        (out/'gate_failure.json').write_text(json.dumps(r,indent=2));return r
    rows=[]
    for scene in SCENES:
        for fr in range(4):
            capture=rgb(gpu/f'recon_raycast_{scene}_f{fr}.bgra',True)
            zero=rgb(gpu/f'recon_raycast_zero_{scene}_f{fr}.bgra',True)
            for ei,eye in enumerate(('left','right')):
                target=rgb(corpus/f'{scene}_f{fr}_gt_{eye}.bgra')
                ids=np.fromfile(corpus/f'{scene}_f{fr}_gt_{eye}_ids.u8',np.uint8).reshape(H,W)
                z=read_float(corpus/f'{scene}_f{fr}_gt_{eye}_metric_z.f32')
                m=derive_masks(corpus,original,scene,fr,eye,ids,z)
                a=zero[:,ei*W:(ei+1)*W];b=capture[:,ei*W:(ei+1)*W]
                ze=np.abs(a.astype(np.int16)-target.astype(np.int16)).mean(axis=2)
                se=np.abs(b.astype(np.int16)-target.astype(np.int16)).mean(axis=2)
                rows.append({'scene':scene,'frame':fr,'eye':eye,
                             'regions':{k:pair_stats(ze,se,mask) for k,mask in m.items()}})
    pooled={scene:pool([r for r in rows if r['scene']==scene]) for scene in SCENES}
    pooled['ALL_SCENES']=pool(rows)
    output={'valid_scoring':True,'generator':'analytic ray-plane RGB-D, metric Z and independent target visibility',
            'input_validation':iv,'GPU_contract':cv,'calibration':cal,
            'pooled':pooled,'per_eye_frame':rows,
            'units':'8-bit mean absolute RGB per pixel; p95/p99 of mean per-pixel RGB channels',
            'limitations':['WARP only, not GPU timing on RTX','source fovea 256x204, peripheral 128x102',
                           '12 frames only; no long temporal history','no DLSS color/depth noise','occlusion oracle uses 2cm metric depth agreement with center source','GT is unavailable to production shader']}
    (out/'raycast_baseline_scores.json').write_text(json.dumps(output,indent=2))
    with (out/'raycast_per_eye_regions.csv').open('w',newline='') as f:
        keys=['scene','frame','eye','region','pixels','zero_mae','stereo_mae','delta','zero_p99','stereo_p99']
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
        for r in rows:
            for k,v in r['regions'].items():writer.writerow({'scene':r['scene'],'frame':r['frame'],'eye':r['eye'],'region':k,**v})
    return output

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--corpus',required=True,type=Path)
    p.add_argument('--expected',required=True,type=Path)
    p.add_argument('--verify-only',action='store_true',help='strict raw-data/hash audit before GPU replay')
    p.add_argument('--captures',type=Path)
    p.add_argument('--original',type=Path)
    p.add_argument('--out',type=Path)
    a=p.parse_args()
    if a.verify_only:
        print('RAYCAST_SOURCE_VERIFY '+json.dumps(verify_inputs(a.corpus,a.expected)))
        return
    if a.captures is None or a.original is None or a.out is None:
        p.error('--captures, --original, and --out required for GPU scoring')
    result=score(a.corpus,a.captures,a.original,a.expected,a.out)
    print('RAYCAST_WARP_SCORE '+json.dumps({'valid':result['valid_scoring'],'calibration':result['calibration']['pass'],
                    'pooled':result.get('pooled',{})}))
    if not result['valid_scoring']:raise SystemExit(1)
if __name__=='__main__':main()
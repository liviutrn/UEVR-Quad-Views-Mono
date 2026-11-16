#!/usr/bin/env python3
"""Evaluator-only scoring for 20 independent V3 target images against WARP output.

GT RGB/IDs are read here, never by the GPU fixture. Fail closed on missing
captures, source/frame/H mismatch, uncalibrated zero-strength alignment and
invalid BGRA. p95/p99 is per-pixel mean absolute RGB8 error, not GPU timing.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,sys
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw
from verify_recon_v3 import verify,EXPECTED_SCENES
LAB=Path(__file__).parent/'DuoView_Stereo_Simulation_Lab_V3_20261115'
sys.path.insert(0,str(LAB))
import stereo_lab as s

W,H=384,216


def rgb(path:Path,double=False)->np.ndarray:
    raw=np.fromfile(path,dtype=np.uint8)
    exp=W*H*4*(2 if double else 1)
    if raw.nbytes!=exp:raise RuntimeError(f'{path}: invalid packed BGRA bytes {raw.nbytes} vs {exp}')
    a=raw.reshape(H,W*(2 if double else 1),4)
    if not np.all(a[:,:,3]==255):raise RuntimeError(f'bad BGRA alpha in {path}')
    return np.ascontiguousarray(a[:,:,2::-1])


def expected_color(path:Path,aw:int,ah:int):
    inp=rgb(path)
    yy,xx=np.indices((ah,aw),np.float32)
    sx=(xx+.5)*W/aw-.5
    sy=(yy+.5)*H/ah-.5
    # Use high-precision interpolation then round to mimic D3D12 staging.
    out=cv2.remap(inp,sx,sy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
    return out


def validation_masks():
    y,x=np.indices((H,W))
    center=(x>=int(.30*W))&(x<int(.70*W))&(y>=int(.30*H))&(y<int(.70*H))
    outer=((x<.20*W)|(x>.80*W)|(y<.20*H)|(y>.80*H))
    outer&=(x>=6)&(x<W-6)&(y>=6)&(y<H-6)
    return center,outer


def calibrate(root:Path,captures:Path,scenes)->dict:
    c_mask,p_mask=validation_masks()
    records=[]
    try:
        for scene in scenes:
            name=scene['files_dir']
            folder=root/name
            for fr in range(4):
                out=rgb(captures/f'recon_v3_zero_{name}_f{fr}.bgra',True)
                left,right=out[:,:W],out[:,W:]
                if not np.array_equal(left,right):
                    raise RuntimeError(f'V3 zero-strength eyes differ: {name}, frame {fr}')
                target_fovea=expected_color(folder/f'{fr:02}_source_fovea.bgra',W//2,H//2)
                # Interior excludes the 2-stage fovea blend and seam.
                src_fovea=left[H//4:3*H//4,W//4:3*W//4]
                cvmask=c_mask[H//4:3*H//4,W//4:3*W//4]
                f_err=np.abs(src_fovea.astype(np.int16)-target_fovea.astype(np.int16))
                native_p=expected_color(folder/f'{fr:02}_source_full.bgra',W//4,H//4)
                p_interp=np.asarray(Image.fromarray(native_p,'RGB').resize((W,H),Image.Resampling.BICUBIC))
                p_err=np.abs(left.astype(np.int16)-p_interp.astype(np.int16))
                fm=float(f_err[cvmask].mean());pm=float(p_err[p_mask].mean())
                result={'scene':name,'frame':fr,'fovea_interior_mae_rgb8':fm,
                        'periphery_bicubic_mae_rgb8':pm,'left_right_equal':True,
                        'pass':fm<=2.5 and pm<=3.0}
                records.append(result)
        return {'pass':len(records)==20 and all(z['pass'] for z in records),
                'records':records, 'record_count':len(records),
                'acceptance':{'fovea_mae_le':2.5,'periphery_mae_le':3.0},
                'contract':'Each of 20 source frames: 192x108 native fovea plus 96x54 Catmull-Rom peripheral filter; zero stereo, identity H.'}
    except (RuntimeError,ValueError) as e:
        return {'pass':False,'error':str(e),'records':records}

def validate_capture_contract(captures:Path)->dict:
    f=captures/'recon_v3_capture_contract.jsonl'
    if not f.is_file():raise RuntimeError('GPU-written V3 capture contract missing')
    rows=[json.loads(z) for z in f.read_text().splitlines() if z.strip()]
    if len(rows)!=40:raise RuntimeError(f'Expected 40 paired V3 GPU capture metadata rows, got {len(rows)}')
    expected=[]
    for scene in EXPECTED_SCENES:
      for fr in range(4):
          expected.append((scene,fr,True))
          expected.append((scene,fr,False))
    got={(r['scene'],r['frame'],r['calibration']) for r in rows}
    if got!=set(expected):raise RuntimeError(f'V3 metadata missing/mismatched scenes: {set(expected)^got}')
    if len(got)!=len(rows):raise RuntimeError('V3 capture metadata duplicate records')
    for row in rows:
        if row['output']!='doublewide_bgra8' or row['eye_order']!='left_right' or row['fine_depth']!='full_r32_inverse_z':
            raise RuntimeError('V3 GPU output format/depth contract mismatch')
        if (row['width'],row['height'])!=(W,H):raise RuntimeError('V3 GPU output dimensions mismatch')
        if row['active_rects']!={'periphery':[96,54],'fovea':[192,108]}:
            raise RuntimeError('V3 GPU active rectangle mismatch')
        if row['file'] not in {f'recon_v3_{row["scene"]}_f{row["frame"]}.bgra',f'recon_v3_zero_{row["scene"]}_f{row["frame"]}.bgra'}:
            raise RuntimeError('Unexpected V3 GPU capture filename')
        if not (captures/row['file']).is_file():raise RuntimeError('Missing V3 GPU output '+row['file'])
        strength=0. if row['calibration'] else 1.
        if abs(row['strength']-strength)>1e-6:raise RuntimeError('Wrong V3 stereo strength')
        k=[strength*13./W,-strength*13./W]
        if np.max(np.abs(np.asarray(k)-row['eye_k']))>1e-7:
            raise RuntimeError('V3 signed-eye k mismatch')
        pan=row['scene'] in EXPECTED_SCENES[:2] and not row['calibration']
        for eye in range(2):
            e=1. if eye==0 else -1.
            sc=(1.035 if eye==0 else 1.024) if pan else 1.
            shift=2.6 if pan else 0.
            skew=.012 if pan else 0.
            h=[sc,e*skew*H/W,.5*(1.-sc)+(e*shift-e*skew*(H+1.)*.5)/W,0.,
               0.,1.,e*.31/H if pan else 0.,0.,0.,0.,1.,0.]
            if np.max(np.abs(np.asarray(h)-row['homography'][eye]))>2e-7:
                raise RuntimeError(f'V3 HLSL H differs from independent projector: {row["file"]} eye {eye}')
    if len({(r['generation'],r['frame_key']) for r in rows}) != len(rows):
        raise RuntimeError('Duplicate GPU frame-key/generation pair in V3 capture contract')
    return {'pass':True,'metadata_records':len(rows),'frame_keys_unique':True}


def masks_for(scene,fr,eye,gtids,srcids,pan):
    yy,xx=s.grid();e=1 if eye=='left' else -1
    depths=np.where(gtids==2,s.D_FG,np.where(gtids==1,s.D_MID,s.D_BG))
    hx,hy=s.Hcoords(xx,yy,eye,pan)
    sx=hx+e*s.K*depths
    sy=hy
    bounded=(sx>=.5)&(sx<W-1.5)&(sy>=.5)&(sy<H-1.5)
    center_id=cv2.remap(srcids,sx.astype(np.float32),sy.astype(np.float32),cv2.INTER_NEAREST,
                        borderMode=cv2.BORDER_CONSTANT,borderValue=255)
    visible=bounded&(center_id==gtids)
    disoccluded=bounded&(center_id!=gtids)
    edge=(cv2.dilate(gtids,np.ones((3,3),np.uint8))!=cv2.erode(gtids,np.ones((3,3),np.uint8)))
    edge=cv2.dilate(edge.astype(np.uint8),np.ones((5,5),np.uint8)).astype(bool)
    valid=(xx>=4)&(xx<W-4)&(yy>=4)&(yy<H-4)
    return {'visible':visible&valid,'disoccluded':disoccluded&valid,'edge':edge&valid,
            'near_edge':edge&(gtids==2)&valid,'background_edge':edge&(gtids==0)&valid,
            'valid':valid,'out_of_source':(~bounded)&valid}


def summary(v,mask):
    sel=v[mask]
    return {'count':int(sel.size),'mae_rgb8':float(np.mean(sel)) if sel.size else None,
            'p95_rgb8':float(np.percentile(sel,95)) if sel.size else None,
            'p99_rgb8':float(np.percentile(sel,99)) if sel.size else None}


def frame_scores(output,gt,ids,centerids,scene,fr,eye,pan):
    mask=masks_for(scene,fr,eye,ids,centerids,pan)
    er=np.abs(output.astype(np.int16)-gt.astype(np.int16)).mean(axis=2)
    out={'scene':scene,'frame':fr,'eye':eye,
         'near_area_pixels':int((ids==2).sum()),
         'disoccluded_fraction_valid':float(mask['disoccluded'].sum()/mask['valid'].sum()),
         'source_oob_fraction_valid':float(mask['out_of_source'].sum()/mask['valid'].sum())}
    for key in ('valid','visible','disoccluded','edge','near_edge','background_edge'):
        out[key]=summary(er,mask[key])
    return out,er,mask


def montage(path,mono,gt,pred,ids,er,title):
    scale=2
    colors=np.stack([(ids==2)*255+(ids==1)*90,(ids==1)*220+(ids==0)*40,(ids==0)*140],axis=-1).astype(np.uint8)
    heat=np.uint8(np.clip(er*4,0,255))
    hm=np.stack([heat,(heat/5).astype(np.uint8),np.zeros_like(heat)],axis=2)
    panels=[('Mono source',mono),('Independent GT',gt),('Production WARP',pred),('GT object ID',colors),('RGB error x4',hm)]
    out=Image.new('RGB',(len(panels)*W*scale,H*scale+25),(16,19,23))
    d=ImageDraw.Draw(out)
    for i,(label,data) in enumerate(panels):
        img=Image.fromarray(data,'RGB').resize((W*scale,H*scale),Image.Resampling.NEAREST)
        out.paste(img,(i*W*scale,25))
        d.text((i*W*scale+5,5),label,fill='white')
    out.save(path)



def region_masks(full_mask:dict)->dict:
    yy,xx=np.indices((H,W))
    core=(xx>=108)&(xx<276)&(yy>=64)&(yy<152)
    outer=( (xx<72)|(xx>=312)|(yy<36)|(yy>=180) )
    valid=full_mask['valid']
    return {'valid':valid,'fovea_core':core&valid,'periphery_outer':outer&valid,
            'near_edge':full_mask['near_edge'],
            'fovea_near_edge':core&full_mask['near_edge'],
            'periphery_near_edge':outer&full_mask['near_edge'],
            'visible':full_mask['visible'],'disoccluded':full_mask['disoccluded'],
            'fovea_disoccluded':core&full_mask['disoccluded'],
            'periphery_disoccluded':outer&full_mask['disoccluded']}


def compare_errors(mono_error,stereo_error,mask):
    a=mono_error[mask];b=stereo_error[mask]
    if not len(a):return {'pixels':0,'mono_mae':None,'stereo_mae':None,
                          'delta_mae':None,'relative_gain_pct':None,'mono_p99':None,'stereo_p99':None}
    m=float(a.mean());s=float(b.mean())
    return {'pixels':int(len(a)),'mono_mae':m,'stereo_mae':s,
            'delta_mae':s-m,'relative_gain_pct':100*(m-s)/m if m>1e-8 else None,
            'mono_p99':float(np.percentile(a,99)),
            'stereo_p99':float(np.percentile(b,99))}


def pooled_comparison(rows):
    result={}
    if not rows:return result
    for region in rows[0]['regions']:
        region_rows=[r['regions'][region] for r in rows]
        pixels=sum(r['pixels'] for r in region_rows)
        if pixels==0:continue
        mono=sum(r['mono_mae']*r['pixels'] for r in region_rows if r['pixels'])/pixels
        stereo=sum(r['stereo_mae']*r['pixels'] for r in region_rows if r['pixels'])/pixels
        result[region]={'pixels':pixels,'mono_mae':mono,'stereo_mae':stereo,
                        'delta_mae':stereo-mono,'relative_gain_pct':100*(mono-stereo)/mono if mono>1e-8 else None,
                        'worse_eye_frame_count':sum(r['delta_mae']>0 for r in region_rows if r['pixels'])}
    return result


def temporal_stationary(corpus:Path,captures:Path):
    name='foliage_stationary_false49'
    folder=corpus/name
    # Fail if the purportedly stationary color or independent GT moves.
    for field in ['source_full.bgra','source_fovea.bgra','gt_left.bgra','gt_right.bgra']:
        if len({(folder/f'{fr:02}_{field}').read_bytes() for fr in range(4)})!=1:
            raise RuntimeError('Stationary V3 color/GT changed unexpectedly: '+field)
    # Here use fixed valid geometry regions, not ground-truth occlusion masks.
    yy,xx=np.indices((H,W));core=(xx>=108)&(xx<276)&(yy>=64)&(yy<152)
    outer=(xx<72)|(xx>=312)|(yy<36)|(yy>=180)
    frames=[rgb(captures/f'recon_v3_{name}_f{fr}.bgra',True) for fr in range(4)]
    rows=[]
    for fr in range(3):
        for index,eye in enumerate(('left','right')):
            a=frames[fr][:,index*W:(index+1)*W].astype(np.float32)
            b=frames[fr+1][:,index*W:(index+1)*W].astype(np.float32)
            delta=np.abs(a-b).mean(axis=2)
            rows.append({'from_frame':fr,'to_frame':fr+1,'eye':eye,
                         'mean_rgb8':float(delta.mean()),
                         'p99_rgb8':float(np.percentile(delta,99)),
                         'max_rgb8':float(delta.max()),
                         'nonzero_fraction':float(np.mean(delta>0)),
                         'fovea_mean_rgb8':float(delta[core].mean()),
                         'outer_mean_rgb8':float(delta[outer].mean())})
    return rows

def evaluate(corpus:Path, captures:Path, output:Path, expected:Path)->dict:
    verify_result=verify(corpus,expected,s)
    contract=validate_capture_contract(captures)
    zero=calibrate(corpus,captures,json.loads((corpus/'manifest.json').read_text())['scenes'])
    # A completely functional shader can still be spatially misregistered. Do
    # not turn such captures into a spurious stereo-quality ranking.
    if not zero['pass']:
        output.mkdir(parents=True,exist_ok=True)
        result={'valid_scoring':False,'reason':'V3 zero-strength source registration failed',
                'corpus':verify_result,'contract':contract,'zero_calibration':zero}
        (output/'gate_failure.json').write_text(json.dumps(result,indent=2))
        return result
    manifest=json.loads((corpus/'manifest.json').read_text())
    scores=[];frames=[];pair_rows=[]
    for record in manifest['scenes']:
        name,scene,pan=record['files_dir'],record['scene'],record['pan_mode']
        sc=s.texture_layers(scene)
        for frmeta in record['frames']:
            fr=frmeta['frame'];folder=corpus/name
            data=rgb(captures/f'recon_v3_{name}_f{fr}.bgra',True)
            zero_data=rgb(captures/f'recon_v3_zero_{name}_f{fr}.bgra',True)
            mono=rgb(folder/f'{fr:02}_source_full.bgra')
            # This independent center-ID oracle is evaluator-only. Never make
            # it a runtime D3D12 shader SRV or a loss/method input.
            _,_,centerids,_=s.render(sc,'center',fr,scene,False,
                 cam_move=record['camera_moves'],physical_move=record['foreground_moves'])
            for ei,eye in enumerate(('left','right')):
                got=data[:,ei*W:(ei+1)*W]
                gt=rgb(folder/f'{fr:02}_gt_{eye}.bgra')
                ids=np.fromfile(folder/f'{fr:02}_gt_{eye}_ids.u8',np.uint8).reshape(H,W)
                row,er,mask=frame_scores(got,gt,ids,centerids,name,fr,eye,pan)
                zero_eye=zero_data[:,ei*W:(ei+1)*W]
                zero_error=np.abs(zero_eye.astype(np.int16)-gt.astype(np.int16)).mean(axis=2)
                reg=region_masks(mask)
                pair_rows.append({'scene':name,'frame':fr,'eye':eye,
                                  'regions':{key:compare_errors(zero_error,er,region_mask)
                                             for key,region_mask in reg.items()}})
                scores.append(row);frames.append((row,mono,gt,got,ids,er))
    assert len(scores)==40
    average={}
    for scene in EXPECTED_SCENES:
        arr=[r for r in scores if r['scene']==scene]
        average[scene]={key+'_mean':float(np.mean([v[key]['mae_rgb8'] for v in arr if v[key]['mae_rgb8'] is not None]))
                       for key in ('valid','visible','disoccluded','near_edge','background_edge')
                       if any(v[key]['mae_rgb8'] is not None for v in arr)}
        average[scene]['near_edge_p99_worst']=max(v['near_edge']['p99_rgb8'] or 0 for v in arr)
    worst=sorted(frames,key=lambda z:z[0]['near_edge']['p99_rgb8'] or 0,reverse=True)[:5]
    output.mkdir(parents=True,exist_ok=True)
    (output/'worst_5').mkdir(exist_ok=True)
    for row,mono,gt,pred,ids,er in worst:
        montage(output/'worst_5'/f"{row['scene']}_f{row['frame']}_{row['eye']}.png",
                mono,gt,pred,ids,er,row['scene'])
    fields=['scene','frame','eye','near_area_pixels','disoccluded_fraction_valid','source_oob_fraction_valid',
            'valid_mae','edge_p95','edge_p99','near_edge_p99','disocclusion_mae']
    with (output/'per_eye_scorecard.csv').open('w',newline='') as csvfile:
        w=csv.DictWriter(csvfile,fieldnames=fields);w.writeheader()
        for a in scores:
            w.writerow({'scene':a['scene'],'frame':a['frame'],'eye':a['eye'],
                        'near_area_pixels':a['near_area_pixels'],
                        'disoccluded_fraction_valid':a['disoccluded_fraction_valid'],
                        'source_oob_fraction_valid':a['source_oob_fraction_valid'],
                        'valid_mae':a['valid']['mae_rgb8'],
                        'edge_p95':a['edge']['p95_rgb8'],
                        'edge_p99':a['edge']['p99_rgb8'],
                        'near_edge_p99':a['near_edge']['p99_rgb8'],
                        'disocclusion_mae':a['disoccluded']['mae_rgb8']})
    pooled={name:pooled_comparison([r for r in pair_rows if r['scene']==name])
            for name in EXPECTED_SCENES}
    pooled['ALL_SCENES']=pooled_comparison(pair_rows)
    stationary=temporal_stationary(corpus,captures)
    (output/'paired_mono_stereo.json').write_text(json.dumps(
        {'origin':'Matched 40 exact-production WARP captures: 20 zero strength vs 20 signed stereo',
         'units':'RGB8 absolute error vs independent left/right GT, no learned perceptual weighting',
         'regions':{'fovea_core':'x=108..275, y=64..151',
                    'periphery_outer':'x<72 or x>=312 or y<36 or y>=180',
                    'near_edge':'5px dilated GT object-ID boundary'},
         'scene_pooled':pooled,'by_eye_frame':pair_rows,
         'stationary_temporal':stationary},indent=2))
    with (output/'paired_mono_stereo.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['scene','frame','eye','region','pixels',
                                            'mono_mae','stereo_mae','delta_mae','relative_gain_pct',
                                            'mono_p99','stereo_p99'])
        writer.writeheader()
        for row in pair_rows:
            for region,values in row['regions'].items():
                writer.writerow({'scene':row['scene'],'frame':row['frame'],
                                 'eye':row['eye'],'region':region,**values})
    result={'valid_scoring':True,'capture_origin':'GPU WARP (external artifact, not CI functional status)',
            'corpus':verify_result,'contract':contract,'zero_calibration':zero,
            'measurement_units':'RGB8 channel levels 0..255; p95/p99 of per-pixel mean RGB8 abs error',
            'frames':scores,'scene_means':average,'paired_mono_stereo_pooled':pooled,
            'stationary_temporal':stationary,
            'worst_near_edge':[{k:v for k,v in x[0].items() if k in ('scene','frame','eye','near_edge')} for x in worst],
            'limitations':['synthetic monocular RGB-D only, no real DLSS','periphery source reduced to 96x54',
                           'no M1 owner or hole mask SRV in baseline capture; labels come from evaluator-only GT',
                           'V3 source camera uses affine reference, no real XR distortion',
                           '20 frames insufficient for long-term temporal confidence','no RTX GPU time measured']}
    (output/'baseline_v3_scorecard.json').write_text(json.dumps(result,indent=2))
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--corpus',type=Path,required=True)
    ap.add_argument('--captures',type=Path,required=True)
    ap.add_argument('--expected',type=Path,default=Path(__file__).parent/'expected.json')
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    result=evaluate(args.corpus,args.captures,args.out,args.expected)
    print('RECON_V3_SCORE '+json.dumps({'valid_scoring':result['valid_scoring'],
          'zero_calibration':result['zero_calibration'].get('pass'),
          'scenes':result.get('scene_means'),
          'paired_regions':result.get('paired_mono_stereo_pooled')},sort_keys=True))
    if not result['valid_scoring']:sys.exit(1)

if __name__=='__main__':main()
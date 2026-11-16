#!/usr/bin/env python3
"""Separate metric-pinhole ray-cast fixture -> test-only BGRA/R32 inverse-z.

Never treat these real-metre Z values as the V3 synthetic inverse-depth levels.
Ground-truth eye images and IDs remain evaluator-only.
"""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
import cv2,numpy as np
from PIL import Image


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(path,data):
    data=np.ascontiguousarray(data)
    Path(path).write_bytes(data.tobytes())
    return {'file':Path(path).name,'sha256':sha(path),'bytes':Path(path).stat().st_size,
            'dtype':str(data.dtype),'shape':list(data.shape)}


def bgra(rgb):
    h,w,c=rgb.shape;assert c==3
    out=np.zeros((h,w,4),np.uint8);out[:,:,:3]=rgb[:,:,::-1];out[:,:,3]=255
    return out


def read_meters(path,w,h):
    a=np.load(path,allow_pickle=False)
    if a.shape!=(h,w) or a.dtype!=np.dtype('<f4'):
        raise ValueError(f'metric depth fixture shape/dtype mismatch: {path}')
    if not np.isfinite(a).all() or not (a>0).all():
        raise ValueError(f'nonphysical Z in raycast: {path}')
    return a


def run(root,out):
    root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((root/'manifest.json').read_text())
    w,h=manifest['width'],manifest['height']
    if (w,h,manifest['baseline_m'],manifest['focal_px'])!=(512,408,.064,486.4):
        raise ValueError('metric raycast camera changed')
    records=[]
    for c in manifest['scenarios']:
        scene,fr=c['scene'],c['frame'];stem=c['files']['mono']
        color=np.asarray(Image.open(root/(stem+'_color.png')).convert('RGB'))
        depth=read_meters(root/(stem+'_depth_m.npy'),w,h)
        # SOURCE INPUTS ONLY. Never substitute a target eye's depth for input.
        fovea_rgb=cv2.resize(color[h//4:3*h//4,w//4:3*w//4],(w,h),interpolation=cv2.INTER_LINEAR)
        inv=(1./depth).astype('<f4')
        fovea_inv=cv2.resize(inv[h//4:3*h//4,w//4:3*w//4],(w,h),interpolation=cv2.INTER_NEAREST)
        prefix=f'{scene}_f{fr}'
        inputs={
            'source_full.bgra':bgra(color),
            'source_fovea.bgra':bgra(fovea_rgb),
            'raw_coarse.f32':inv,
            'raw_fine.f32':fovea_inv,
        }
        refs={}
        for eye in ('left','right'):
            t=c['files'][eye]
            refs['gt_'+eye+'.bgra']=bgra(np.asarray(Image.open(root/(t+'_color.png')).convert('RGB')))
            refs['gt_'+eye+'_ids.u8']=np.asarray(Image.open(root/(t+'_object_id.png')).convert('L'))
            refs['gt_'+eye+'_metric_z.f32']=read_meters(root/(t+'_depth_m.npy'),w,h).astype('<f4')
        rec={'scene':scene,'frame':fr,'input':{},'reference_only':{}}
        for name,data in inputs.items(): rec['input'][name]=write(out/(prefix+'_'+name),data)
        for name,data in refs.items(): rec['reference_only'][name]=write(out/(prefix+'_'+name),data)
        records.append(rec)
    result={'version':1,'provenance':'independent raycast stereo fixture, not V3 and not NGX',
            'width':w,'height':h,'focal_px':486.4,'baseline_m':.064,'half_baseline_m':.032,
            'shader_depth_coefficients':[0,1,1],
            'shader_input_depth':'inverse_z_m^-1; compute as 1 / mono_depth_m, never pass metric Z directly',
            'eye_shift_normalized':{'left':-.0304,'right':+.0304},
            'eye_shift_pixels_at_z1':{'left':-15.5648,'right':15.5648},
            'full_to_fovea_rect':[w//4,h//4,3*w//4,3*h//4],
            'shader_source_active':{'periphery':[w//4,h//4],'fovea':[w//2,h//2]},
            'frames':records}
    (out/'raycast_replay_manifest.json').write_text(json.dumps(result,indent=2))
    print('RAYCAST_INPUT_EXPORT',len(records),'frames',len(records)*4,'shader-input files, GT isolated')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();run(args.input,args.out)
#!/usr/bin/env python3
"""Reproducible V3 RGB-D test corpus for an exact production HLSL D3D12 WARP replay.

This exports *data only*, not a GPU result. Real game transforms and NGX
metadata must be independently verified. Numpy/Python procedural reference
is used only for scoring, never leaked into GPU reconstruction inputs.
"""
import argparse, json, sys, hashlib
from pathlib import Path
import numpy as np
import cv2

LAB=Path(__file__).parent/'DuoView_Stereo_Simulation_Lab_V3_20261115'
sys.path.insert(0,str(LAB))
import stereo_lab as s

CASES=(
  ('weapon','object_motion','clean',True,True,True),
  ('layers','object_motion','clean',True,True,True),
  ('foliage','stationary_false49','groups_depth',False,False,False),
  ('foliage','physical_sway','clean',False,True,False),
  ('natural','physical_sway','clean',False,True,False),
  ('fence','camera_motion','clean',True,False,True),
  ('border','source_fit','clean',False,False,'extreme'),
)

def bgra(color):
    rgb=s.im8(color)
    out=np.empty((rgb.shape[0],rgb.shape[1],4),np.uint8)
    out[...,:3]=rgb[...,::-1];out[...,3]=255
    return out

def file_bytes(path,a):
    a=np.ascontiguousarray(a)
    path.write_bytes(a.tobytes(order='C'))
    return {'name':path.name,'bytes':path.stat().st_size,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'dtype':str(a.dtype),'shape':list(a.shape)}

def run(out,frames=6,subset=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    corpus={'version':1,'source':'V3 archive stereo_lab.py','seed':s.SEED,'width':s.W,'height':s.H,
      'fovea_crop_pixels':[s.W//4,s.H//4,3*s.W//4,3*s.H//4],
      'eye_inverse_depth_disparity_pixels_per_unit':{'left':+s.K,'right':-s.K},
      'physical_frame_interval_ms':50,'scenes':[],
      'limitations':['Synthetic content, NOT STALKER2 NGX color/depth capture',
         'V3 eye projection is affine; physical source fit/HLSL crop not yet matched',
         'Standalone exporter: success does not imply production GPU validation',
         'Fine crop resized using nearest depth/linear color; tests must verify source fit']}
    clusters=s.foliage_clusters('foliage')
    for name,scenario,noise,cam,obj,pan in CASES:
        if subset and scenario not in subset and name not in subset:continue
        scene=s.texture_layers(name)
        d=out/(name+'_'+scenario);d.mkdir(exist_ok=True)
        files=[]
        for frame in range(frames):
            src,depth,ids,pose=s.render(scene,'center',frame,name,False,cam_move=cam,physical_move=obj)
            src=s.capture_color(src,frame,noise,clusters)
            raw,_=s.capture_depth(depth,ids,frame,noise,clusters)
            # In production the foveal view covers a smaller FOV at an independent
            # physical resolution. Export with exact crop and separately document
            # its resize here. A real game sampler is NOT being inferred.
            y0,y1=s.H//4,3*s.H//4; x0,x1=s.W//4,3*s.W//4
            foveal=cv2.resize(src[y0:y1,x0:x1],(s.W,s.H),interpolation=cv2.INTER_LINEAR)
            foveal_depth=cv2.resize(raw[y0:y1,x0:x1],(s.W,s.H),interpolation=cv2.INTER_NEAREST)
            payload={'source_full.bgra':bgra(src),'source_fovea.bgra':bgra(foveal),
                     'raw_coarse.f32':raw.astype('<f4'), 'raw_fine.f32':foveal_depth.astype('<f4')}
            # Only evaluator reads GT; never pass these files to the shader.
            for eye in ('left','right'):
                gt,gtd,gtids,_=s.render(scene,eye,frame,name,pan,cam_move=cam,physical_move=obj)
                payload[f'gt_{eye}.bgra']=bgra(gt)
                payload[f'gt_{eye}_ids.u8']=gtids.astype(np.uint8)
            record={'frame':frame,'frame_time_ms':frame*50,'pose':pose,'inputs':{},'reference_only':{}}
            for key,a in payload.items():
                file=d/f'{frame:02}_{key}'
                info=file_bytes(file,a)
                group='reference_only' if key.startswith('gt_') else 'inputs'
                record[group][key]=info
            files.append(record)
        corpus['scenes'].append({'scene':name,'scenario':scenario,'noise':noise,
              'camera_moves':cam,'foreground_moves':obj,'pan_mode':pan,
              'frames':files,'files_dir':d.name})
        print('EXPORT',d.name,len(files),flush=True)
    (out/'manifest.json').write_text(json.dumps(corpus,indent=2,allow_nan=False))
    return corpus

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',default='recon_corpus');p.add_argument('--frames',type=int,default=6)
    p.add_argument('--scenarios',nargs='*');a=p.parse_args()
    run(a.out,a.frames,a.scenarios)

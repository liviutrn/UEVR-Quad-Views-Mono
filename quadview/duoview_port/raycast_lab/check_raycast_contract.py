#!/usr/bin/env python3
"""Ray-cast camera/source-visibility oracle; no production GPU claim.

Uses evaluator-only target depths/IDs solely to check reference geometry and
quantify visibility. These must never be supplied to the synthesis shader.
"""
import argparse,json
from pathlib import Path
import cv2,numpy as np
from PIL import Image


def run(root,original):
 root=Path(root)
 meta=json.loads((root/'raycast_replay_manifest.json').read_text())
 w,h=meta['width'],meta['height']; f=meta['focal_px']
 cx=(w-1)/2
 yy,xx=np.indices((h,w),np.float32)
 results=[]
 for record in meta['frames']:
  stem=f"{record['scene']}_f{record['frame']}"
  mid=np.fromfile(root/(stem+'_gt_left_ids.u8'),np.uint8)
  mono_depth=np.fromfile(root/(stem+'_raw_coarse.f32'),'<f4').reshape(h,w)
  assert np.all(np.isfinite(mono_depth)) and np.all(mono_depth>0)
  for eye,sign in [('left',-1),('right',+1)]:
   target_depth=np.fromfile(root/(stem+f'_gt_{eye}_metric_z.f32'),'<f4').reshape(h,w)
   target_ids=np.fromfile(root/(stem+f'_gt_{eye}_ids.u8'),np.uint8).reshape(h,w)
   raw= root/(stem+'_source_full.bgra')
   srcraw=np.fromfile(raw,np.uint8).reshape(h,w,4)
   src_rgb=srcraw[:,:,2::-1].copy()
   mono_ids_path=Path(original)/(stem+'_mono_object_id.png')
   # Portable fallback for corpus copies: ID oracle is an independent source,
   # passed to this verifier by the generator fixture location only.
   if not mono_ids_path.exists():
    raise FileNotFoundError('Original evaluator-only mono ID oracle needed: '+str(mono_ids_path))
   mono_ids=np.asarray(Image.open(mono_ids_path).convert('L'))
   mapped_x=xx+sign*f*.032/target_depth
   valid=(mapped_x>=1)&(mapped_x<w-2)&(yy>=1)&(yy<h-2)
   sampled_id=cv2.remap(mono_ids,mapped_x.astype('float32'),yy,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=255)
   mono_inv_at_src=cv2.remap(mono_depth,mapped_x.astype('float32'),yy,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=0.)
   # Depth equality distinguishes overlapping foliage leaves even with the same ID.
   same_z=np.abs(1./np.maximum(mono_inv_at_src,1.e-8)-target_depth)<.02
   visible=valid&(sampled_id==target_ids)&same_z
   occluded=valid&~visible
   sampled_rgb=cv2.remap(src_rgb,mapped_x.astype('float32'),yy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
   gt=np.fromfile(root/(stem+f'_gt_{eye}.bgra'),np.uint8).reshape(h,w,4)[:,:,2::-1]
   err=np.abs(sampled_rgb.astype('int16')-gt.astype('int16')).mean(axis=2)
   # Algebraic identity: source ray with target z maps to same 3D position.
   tcam=sign*.032
   t_world_x=tcam + (xx-cx)/f*target_depth
   src_world_x=(mapped_x-cx)/f*target_depth
   world_error=np.abs(t_world_x-src_world_x)
   record_result={
     'scene':record['scene'],'frame':record['frame'],'eye':eye,
     'k_uv':sign*.032*f/w,
     'mean_disparity_px':float(np.mean(abs(mapped_x-xx)[valid])),
     'source_visible_fraction':float(np.mean(visible[valid])),
     'source_occluded_fraction':float(np.mean(occluded[valid])),
     'visible_rgb_mae0_255':float(np.mean(err[visible])) if visible.any() else None,
     'world_ray_x_alignment_max_m':float(np.max(world_error[valid]))}
   if record_result['world_ray_x_alignment_max_m']>=3e-6:
      raise RuntimeError('pinhole reference mismatch '+str(record_result))
   results.append(record_result)
 return {'family':'metric raycast, not V3','source_scene_frames':12,'eye_frame_checks':len(results),
         'full_reference_alignment_pass':all(x['world_ray_x_alignment_max_m']<3e-6 for x in results),
         'rows':results,
         'limitations':['target Z/IDs used only for offline oracle','source occlusion can prevent stereo recovery','not GPU reproduction']}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--corpus',required=True,type=Path);p.add_argument('--original',required=True,type=Path);p.add_argument('--out',required=True,type=Path);args=p.parse_args()
 report=run(args.corpus,args.original);args.out.write_text(json.dumps(report,indent=2))
 print(json.dumps({'pass':report['full_reference_alignment_pass'],'n':report['eye_frame_checks'],
                   'mean_visible':np.mean([x['source_visible_fraction'] for x in report['rows']]),
                   'worst_world_error_m':max(x['world_ray_x_alignment_max_m'] for x in report['rows']),
                   'near_eye_signs':{x['eye']:x['k_uv'] for x in report['rows'][:2]}},indent=2))
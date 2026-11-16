#!/usr/bin/env python3
"""Deterministic analytic stereo reference scenes (not a production shader run).
Produces mono source, ideal L/R stereo, source depth, object IDs and validity.
Units: metres; horizontal camera baseline 64 mm; pinhole geometry.
"""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image

def render(w,h,frame,eye,scenario):
    yy,xx=np.mgrid[:h,:w].astype(np.float32)
    f=0.95*w; cx=(w-1)/2;cy=(h-1)/2
    # camera position; eye offsets in metres
    cam=0.02*np.sin(frame*0.37)+eye*0.032
    rayx=(xx-cx)/f; rayy=(yy-cy)/f
    z=np.full((h,w),12.,np.float32); ids=np.zeros((h,w),np.uint8)
    # fronto-parallel occluders; projected with true geometric parallax
    def obj(oid,depth,x0,x1,y0,y1):
        nonlocal z,ids
        worldx=cam+rayx*depth;worldy=rayy*depth
        mask=(worldx>=x0)&(worldx<x1)&(worldy>=y0)&(worldy<y1)&(depth<z)
        z[mask]=depth;ids[mask]=oid
    t=frame/3
    obj(1,4.5,-1.65+0.12*t,0.2+0.12*t,-0.65,0.8)
    obj(2,2.1,-0.35+0.2*t,0.45+0.2*t,-0.95,0.45)
    if scenario=='foliage':
        # 49 thin leaves, with deliberately varying distances and motion
        for i in range(49):
            row,col=divmod(i,7); d=3.0+0.22*(i%5)
            x=-1.6+col*0.35+0.03*np.sin(frame*.8+i*.7)
            y=-.65+row*.23
            obj(3,d,x,x+.045,y,y+.085)
    if scenario=='weapon':obj(4,.65,-.35+.05*t,.35+.05*t,-.75,-.22)
    # stable world-coordinate texture, no image-space frame randomization
    wx=cam+rayx*z; wy=rayy*z
    col=np.zeros((h,w,3),np.uint8)
    palettes=np.array([[75,90,105],[65,160,220],[180,100,55],[45,155,65],[90,85,180]],np.uint8)
    col[:]=palettes[ids]
    check=(((np.floor(wx*11)+np.floor(wy*11)).astype(np.int32)&1)*24).astype(np.uint8)
    col=np.clip(col.astype(np.int16)+check[...,None],0,255).astype(np.uint8)
    return col,z,ids

def save(path,arr):
    Image.fromarray(arr).save(path)

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',default='reference_fixture');p.add_argument('--width',type=int,default=512);p.add_argument('--height',type=int,default=408);p.add_argument('--frames',type=int,default=4);args=p.parse_args()
 out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
 manifest={'generator':'analytic ray-plane intersections','baseline_m':.064,'focal_px':.95*args.width,'width':args.width,'height':args.height,'frames':args.frames,'scenarios':[]}
 for scene in ['occlusion','foliage','weapon']:
  for frame in range(args.frames):
   images={}
   for eye,name in [(0,'mono'),(-1,'left'),(1,'right')]:
    color,depth,ids=render(args.width,args.height,frame,eye,scene)
    prefix=f'{scene}_f{frame}_{name}'
    save(out/(prefix+'_color.png'),color)
    save(out/(prefix+'_object_id.png'),ids)
    np.save(out/(prefix+'_depth_m.npy'),depth)
    images[name]=prefix
   # right-eye newly exposed pixels have world background not visible in mono
   # IDs alone are a conservative proxy; not exact per-pixel visibility
   manifest['scenarios'].append({'scene':scene,'frame':frame,'files':images})
 (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
 print('Created',len(manifest['scenarios']),'frame sets in',out)
if __name__=='__main__':main()
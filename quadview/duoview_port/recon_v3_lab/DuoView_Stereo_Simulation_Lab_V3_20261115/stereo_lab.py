#!/usr/bin/env python3
"""DuoView edge-reconstruction *analytic* simulation lab (not production HLSL).

One center RGB-D source feeds all candidates. Known scene geometry is accessible
ONLY in reference rendering and scoring. Fixed seeds. Camera/eye warp is an
explicit affine restriction of B318's projective M1Homography; x solve matches
x_source = H_eye(target).x + M1Eye[eye] * D(x_source,H_eye.y).

Limitations: no real NGX captures, no exact V2 conditioner, no HLSL/WARP, no RTX timings.
"""
from __future__ import annotations
import argparse, json, math, time, hashlib
from pathlib import Path
import numpy as np
import cv2
from PIL import Image, ImageDraw
from scipy.ndimage import maximum_filter1d, minimum_filter1d

W,H=384,216
PAD=96
D_BG,D_MID,D_FG=.12,.47,1.0
SEED=261115
K=13.0
cv2.setNumThreads(1)


def smooth(a,s):return cv2.GaussianBlur(a,(0,0),s,s) if s>0 else a.copy()


def grid(w=W,h=H):
    y,x=np.mgrid[0:h,0:w]
    return x.astype(np.float32),y.astype(np.float32)


def remap(a,x,y,interp=cv2.INTER_LINEAR,border=cv2.BORDER_CONSTANT):
    return cv2.remap(a,np.asarray(x,dtype=np.float32),np.asarray(y,dtype=np.float32),interp,borderMode=border,borderValue=0)


def texture_layers(scene,seed=SEED,w=W,h=H):
    rng=np.random.default_rng(seed+{'bar':1,'weapon':2,'fence':3,'foliage':4,'border':5,'layers':6,'natural':7}[scene])
    xx,yy=np.meshgrid(np.arange(-PAD,w+PAD,dtype=np.float32),np.arange(-12,h+12,dtype=np.float32))
    shape=xx.shape
    noise=smooth(rng.normal(0,1,shape).astype(np.float32),1.8)
    # Fine wall pattern + variation, with weak 'physical' texture motion = zero.
    checker=((np.floor(xx/11)+np.floor(yy/10))%2).astype(np.float32)
    wall=np.stack((.16+.36*checker+.07*np.sin(xx*.11)+.05*noise,
                   .25+.39*(1-checker)+.06*np.cos(yy*.09),
                   .28+.23*checker+.05*noise),axis=2)
    wall=np.clip(wall,0,1).astype(np.float32)
    mid=np.stack((.33+.19*np.sin(xx*.07),.36+.08*np.sin((xx+yy)*.11),.17+.10*np.cos(yy*.1)),axis=2).astype(np.float32)
    near=np.stack((.62+.18*np.cos((xx+yy)*.03),.13+.09*np.sin(yy*.13)**2,.09+.07*np.cos(xx*.1)**2),axis=2).astype(np.float32)
    if scene=='natural':
        # Less adversarial and closer to a game frame: sky, distant wall, grass,
        # trees, dark foreground vegetation. Not a captured STALKER 2 texture.
        sky=np.stack((.38+.11*yy/h,.48+.13*yy/h,.58+.05*yy/h),axis=2)
        ground=np.stack((.19+.055*np.cos(xx*.21)+.03*noise,
                         .25+.13*np.sin(xx*.14)**2+.08*noise,
                         .15+.035*noise),axis=2)
        brick=((np.floor(xx/35)+np.floor(yy/19)%2)*.5%2)
        building=np.stack((.37+.08*brick+.03*noise,.36+.08*brick+.03*noise,.31+.055*brick+.02*noise),axis=2)
        wall=np.where((yy>76)[...,None],ground,sky)
        wall=np.where(((xx<133)&(yy>32)&(yy<138))[...,None],building,wall)
        wall=np.clip(wall,0,1).astype(np.float32)
        mid=np.stack((.20+.06*noise,.25+.085*np.sin(xx*.085)**2,.13+.04*noise),axis=2).astype(np.float32)
        near=np.stack((.12+.06*np.cos(xx*.13)**2,.23+.13*np.sin((xx+yy)*.05)**2,.10+.04*noise),axis=2).astype(np.float32)
    m_mid=np.zeros(shape,np.uint8); m_fg=np.zeros(shape,np.uint8)
    # all geometries are world-anchored in the central pixel coordinate system
    if scene in ('bar','border'):
        m_fg |= (((xx>=128)&(xx<174)&(yy>35)&(yy<184))).astype(np.uint8)
        m_mid |= (((xx>255)&(xx<295)&(yy>65)&(yy<172))).astype(np.uint8)
    elif scene=='weapon':
        body=((xx>56)&(xx<231)&(yy>141)&(yy<182))
        barrel=((xx>164)&(xx<308)&(np.abs(yy-(139-(xx-164)*.23))<5))
        sight=((xx>202)&(xx<214)&(yy>109)&(yy<144))
        hand=((xx>39)&(xx<112)&(yy>163)&(yy<216))
        m_fg=(body|barrel|sight|hand).astype(np.uint8)
        m_mid=(((xx-225)**2/75**2+(yy-92)**2/36**2<1)|((xx>275)&(xx<295)&(yy>67)&(yy<192))).astype(np.uint8)
    elif scene in ('fence','foliage','natural'):
        for pos in ((17,66,117,168,218,274,322,359) if scene!='natural' else (19,179,291)):
            m_mid |= ((xx>=pos)&(xx<pos+2)&(yy>=25)&(yy<211)).astype(np.uint8)
        m_mid |= ((yy>114)&(yy<119)&(xx>0)&(xx<w)).astype(np.uint8)
        # procedurally sampled, partially isolated 1-3px branches / leaves
        for _ in range(920 if scene=='foliage' else (460 if scene=='natural' else 42)):
            cx=float(rng.uniform(12,w-12));cy=float(rng.uniform(8,h-8));rw=float(rng.uniform(.7,2.6));rh=float(rng.uniform(2,8))
            m_fg |= (((xx-cx)**2/rw**2+(yy-cy)**2/rh**2)<1).astype(np.uint8)
        if scene in ('foliage','natural'):
            for _ in range(220 if scene=='foliage' else 100):
                cx=float(rng.uniform(20,w-20));cy=float(rng.uniform(12,h-12))
                m_fg |= ((abs(xx-cx)<1.2)&(abs(yy-cy)<1.2)).astype(np.uint8)
    else: # three or more competing depths
        m_fg|=(((xx>45)&(xx<95)&(yy>52)&(yy<192))|((xx>201)&(xx<238)&(yy>22)&(yy<190))).astype(np.uint8)
        m_mid|=(((xx>95)&(xx<220)&(yy>64)&(yy<156))|((xx>288)&(xx<306)&(yy>29)&(yy<188))).astype(np.uint8)
    # Three clearly colored layers, 2D coordinates retained in the padded world texture.
    return {'wall':wall,'mid':mid,'near':near,'mid_mask':m_mid,'near_mask':m_fg,'world_x':xx,'world_y':yy}


def Hcoords(x,y,eye,pan_mode=False):
    # Pinhole projective homography restricted to affine approximation; stress
    # nonidentical eyes + fitted-source scale/translation/shear + vertical offset.
    e=1 if eye=='left' else (-1 if eye=='right' else 0)
    if pan_mode:
        extreme=pan_mode=='extreme'
        scale=(1.19 if e>0 else 1.17) if extreme else (1.035 if e>0 else 1.024 if e<0 else 1.)
        shift=14. if extreme else 2.6
        skew=.04 if extreme else .012
        sx=(x-(W-1)*.5)*scale+(W-1)*.5 + e*shift+e*skew*(y-H*.5)
        sy=y+e*(.83 if extreme else .31)
    else:
        sx=x;sy=y
    return sx.astype(np.float32),sy.astype(np.float32)


def invert_H(srcx,sy,eye,pan_mode=False):
    e=1 if eye=='left' else -1
    if not pan_mode:return srcx
    extreme=pan_mode=='extreme'
    sc=(1.19 if e>0 else 1.17) if extreme else (1.035 if e>0 else 1.024)
    dy=e*(.83 if extreme else .31)
    tx=sy-dy
    shift=14. if extreme else 2.6
    skew=.04 if extreme else .012
    return (srcx-(W-1)*.5-e*shift-e*skew*(tx-H*.5)) /sc +(W-1)*.5


def render(sc,eye,frame,scene,pan_mode,cam_move=True,physical_move=False):
    """Independent ground truth per eye, not used by candidates."""
    x,y=grid(); baseX,baseY=Hcoords(x,y,eye,pan_mode)
    e=1 if eye=='left' else -1 if eye=='right' else 0
    camera_x= ((frame-5.5)*.65 +.34*np.sin(frame*.78)) if cam_move else 0.
    camera_y= .23*np.sin(frame*.45) if cam_move else 0.
    # moving objects are real changes: GT and central source receive same motion
    moving_fg= (3.2*np.sin(frame*.75) if scene in ('foliage','natural') else 2.1*frame) if physical_move else 0.
    moving_mid=-.72*frame if physical_move and scene=='layers' else 0.
    def coords(depth,moving):
        return baseX+camera_x+e*K*depth+PAD-moving, baseY+camera_y+12
    bg=remap(sc['wall'],*coords(D_BG,0),border=cv2.BORDER_REFLECT_101)
    xm,ym=coords(D_MID,moving_mid);xf,yf=coords(D_FG,moving_fg)
    if scene in ('foliage','natural') and physical_move:
        # spatially variable leaf sway: real motion, represented in both GT
        # and source. Unlike depth corruption, it must not count as false shimmer.
        xf=xf+2.2*np.sin((xf-2*frame)/29.+frame*.52)*np.sin(yf/40.)
    midmask=remap(sc['mid_mask'],xm,ym,interp=cv2.INTER_NEAREST)>0
    fgmask=remap(sc['near_mask'],xf,yf,interp=cv2.INTER_NEAREST)>0
    mid=remap(sc['mid'],xm,ym,border=cv2.BORDER_REFLECT_101)
    fg=remap(sc['near'],xf,yf,border=cv2.BORDER_REFLECT_101)
    out=np.where(midmask[...,None],mid,bg)
    out=np.where(fgmask[...,None],fg,out).astype(np.float32)
    dep=np.where(fgmask,D_FG,np.where(midmask,D_MID,D_BG)).astype(np.float32)
    ids=np.where(fgmask,2,np.where(midmask,1,0)).astype(np.uint8)
    return out,dep,ids,{'camera_x':camera_x,'camera_y':camera_y,'moving_fg':moving_fg,'moving_mid':moving_mid}


def foliage_clusters(scene,seed=SEED):
    # spatially correlated 7x7 = 49-pixel cells, not 49 independent flips
    rng=np.random.default_rng(seed+71)
    masks=[]
    for _ in range(15):
        cx=int(rng.integers(95,W-26));cy=int(rng.integers(22,H-22))
        m=np.zeros((H,W),bool);m[cy-3:cy+4,cx-3:cx+4]=True
        masks.append(m)
    return masks


def capture_depth(src_dep,src_ids,frame,noise_mode,clusters,seed=SEED,cam=0):
    raw=src_dep.copy()
    if noise_mode in ('clean','crop','groups_color','late_depth'):return raw, np.zeros_like(raw,bool)
    rng=np.random.default_rng(seed+200+frame*193)
    # NGX-like depth edge instability: TAA/sample jitter, near-foreground spatial alias
    shifted=remap(raw,grid()[0]+.46*np.sin(frame*1.2),grid()[1],interp=cv2.INTER_NEAREST,border=cv2.BORDER_REPLICATE)
    foliage=(src_ids==2)|(src_ids==1)
    if noise_mode in ('pixel','combined'):
        flip=(rng.random(raw.shape)<.035)&foliage
        raw=np.where(flip,np.maximum(D_BG,raw-.48),raw)
        raw=np.where(foliage, .84*raw+.16*shifted, raw)
        raw=np.clip(raw+rng.normal(0,.024,raw.shape).astype(np.float32)*foliage, D_BG,1.)
    changed=np.zeros_like(foliage)
    if noise_mode=='depth_dropout':
        raw[71:143,143:245]=D_BG
    if noise_mode in ('groups_depth','combined'):
        # 49-pixel tiles switch as a unit, e.g. foliage alpha/TAA depth vote.
        # Intentional temporal phase shifts simulate clusters 'breathing' at 20 FPS.
        for i,m in enumerate(clusters):
            if ((frame//(2+(i%2)) + i*3)%4) in (1,2):
                raw[m]=np.where(raw[m]>.64,D_MID,D_FG) # a coherent 49-pixel false depth vote
                changed|=m
    return np.clip(raw,0,1.15).astype(np.float32),changed


def cone_envelope(raw,slope=.061):
    """Continuous symmetric max cone with |depth'(x)| <= slope; V2-like proxy.

    Production V2 uses a *piecewise reparameterized* max-envelope with fine /
    coarse separately and per-eye parameters; this is not bit-identical.
    """
    x=np.arange(raw.shape[1],dtype=np.float32)[None,:]
    left=np.maximum.accumulate(raw+slope*x,axis=1)-slope*x
    right=np.maximum.accumulate((raw-slope*x)[:,::-1],axis=1)[:,::-1]+slope*x
    return np.maximum(raw,np.maximum(left,right)).astype(np.float32)



def capture_color(source,frame,noise_mode,clusters,seed=SEED):
    """False image shimmer, deliberately separate from true animated geometry.

    7x7 cells share one brightness deviation (not 49 independent impulses).
    No ground truth or hidden layer is fed to candidates.
    """
    color=source.copy()
    if noise_mode in ('groups_color','combined'):
        for i,m in enumerate(clusters):
            phase=(frame//(1+i%3)+i*5)%4
            pulse=(.20 if phase in (1,2) else -.12)
            color[m]=np.clip(color[m]* (1+pulse),0,1)
    if noise_mode in ('pixel','combined'):
        rng=np.random.default_rng(seed+3400+frame*79)
        sprinkle=rng.random((H,W))<.015
        noise=rng.choice([-.35,.35],size=(H,W)).astype(np.float32)
        color[sprinkle]=np.clip(color[sprinkle]+noise[sprinkle,None],0,1)
    return color


def v2_map(d,close=0.,far=.75,near_inv=.50,far_inv=.083):
    """CPU analogue of M8V2Map in accepted cleanup overlay.

    Note the actual engine units/distance thresholds are not established by
    these synthetic scene numbers; these are illustrative test parameters.
    """
    lo=float(far_inv);hi=float(near_inv)
    sc=max(.10,1.-.90*close);sf=max(.10,1.-.90*far);sm=.5*(sc+sf)
    a=lo/sf;b=a+(hi-lo)/sm
    return np.where(d<=lo,d/sf,np.where(d<=hi,a+(d-lo)/sm,b+(d-hi)/sc))


def v2_unmap(d,close=0.,far=.75,near_inv=.50,far_inv=.083):
    lo=float(far_inv);hi=float(near_inv)
    sc=max(.10,1.-.90*close);sf=max(.10,1.-.90*far);sm=.5*(sc+sf)
    a=lo/sf;b=a+(hi-lo)/sm
    return np.where(d<=a,d*sf,np.where(d<=b,lo+(d-a)*sm,hi+(d-b)*sc))


def condition_depth(raw,crop_center=None,coarse_factor=7):
    # Conservative near-max seeds, V2 reparameterization, symmetric max
    # envelope, then inverse mapping. This is closer to current cleanup than
    # Gaussian blur, but fine/coarse sampling/eye-specific units remain proxies.
    max_coarse=cv2.dilate(raw,np.ones((5,5),np.uint8))
    small=cv2.resize(max_coarse,(W//coarse_factor,H//coarse_factor),interpolation=cv2.INTER_AREA)
    coarse_seed=cv2.resize(small,(W,H),interpolation=cv2.INTER_LINEAR)
    safe_slope=.99/K
    coarse=v2_unmap(cone_envelope(v2_map(coarse_seed),safe_slope))
    if crop_center is None:return coarse.astype(np.float32)
    fine_seed=cv2.dilate(raw,np.ones((2,2),np.uint8))
    fine=v2_unmap(cone_envelope(v2_map(fine_seed),safe_slope))
    x,y=grid();cx,cy=crop_center
    l,r=cx-84,cx+84; t,b=cy-58,cy+58
    localx=(x-l)/(r-l);localy=(y-t)/(b-t)
    edge=np.minimum(np.minimum(localx,1-localx),np.minimum(localy,1-localy))
    u=np.clip(edge/.15,0,1);alpha=u*u*(3-2*u)
    return (coarse*(1-alpha)+fine*alpha).astype(np.float32)


def inverse_warp(src,dep,eye,rad,pan_mode=False):
    x,y=grid();bx,by=Hcoords(x,y,eye,pan_mode);e=1 if eye=='left' else -1
    k=e*K
    d=smooth(dep,rad)
    # B318 eight bisections plus continuous secant finish. Production source
    # includes bounded conditioner, which is not represented exactly here.
    lo=np.minimum(bx,bx+k*1.15).astype(np.float32);hi=np.maximum(bx,bx+k*1.15).astype(np.float32)
    rlo=np.zeros_like(lo);rhi=np.zeros_like(lo);hl=np.zeros_like(lo,bool);hh=np.zeros_like(lo,bool)
    for _ in range(8):
        mid=(lo+hi)*.5
        res=bx+k*remap(d,mid,by,border=cv2.BORDER_REPLICATE)-mid
        flip=res>0
        lo=np.where(flip,mid,lo);hi=np.where(flip,hi,mid)
        rlo=np.where(flip,res,rlo);rhi=np.where(flip,rhi,res)
        hl|=flip;hh|=~flip
    root=(lo+hi)*.5
    ok=(hl&hh&(np.abs(rlo-rhi)>1.e-7))
    sec=lo+(hi-lo)*rlo/np.where(np.abs(rlo-rhi)>1.e-7,rlo-rhi,1)
    root=np.where(ok,np.clip(sec,lo,hi),root)
    valid=(root>=.3)&(root<W-.7)&(by>=.3)&(by<H-.7)
    color=remap(src,root,by,border=cv2.BORDER_REPLICATE)
    raw_selected=remap(dep,root,by,border=cv2.BORDER_REPLICATE)
    return color,raw_selected,valid,root,by


def fwd_owner(src,dep,eye,pan_mode=False,mask=None):
    """Deterministic two-tap forward reference, CPU-only and no depth/color race."""
    x,y=grid();e=1 if eye=='left' else -1;k=e*K
    # inverse to the synthetic homography x mapping (eye warp source base)
    bx=x-k*dep
    tx=invert_H(bx,y,eye,pan_mode)
    ty=y-(e*(.83 if pan_mode=='extreme' else .31) if pan_mode else 0.)
    yi=np.rint(ty).astype(np.int32)
    # Pixel footprint: floor and ceil x, max-depth wins. Ties prefer proximity
    # to projected center then earlier source index.
    xf=np.floor(tx).astype(np.int32); frac=np.clip(tx-xf,0,1)
    owner_key=np.zeros(H*W,np.uint64)
    srcflat=np.arange(H*W,dtype=np.uint64).reshape(H,W)
    allmask=np.ones((H,W),bool) if mask is None else mask
    for dx,weight in ((0,1-frac),(1,frac)):
        xx=xf+dx
        valid=(xx>=0)&(xx<W)&(yi>=0)&(yi<H)&allmask&(weight>.07)&((dep<.70)|(weight>=.50))
        dest=(yi[valid]*W+xx[valid]).astype(np.int64)
        dq=np.rint(dep[valid].astype(np.float64)*100000).astype(np.uint64)
        wq=np.rint(weight[valid]*1023).astype(np.uint64)
        key=(dq<<32)+(wq<<20)+(np.uint64(H*W)-srcflat[valid])
        np.maximum.at(owner_key,dest,key)
    valid=owner_key>0
    idx=(np.uint64(H*W)-(owner_key&((np.uint64(1)<<np.uint64(20))-1))).astype(np.int64)
    idx=np.clip(idx,0,H*W-1)
    owner_depth=dep.reshape(-1)[idx].reshape(H,W)
    # Recover subpixel texture at the winning *surface* without bilinearly
    # mixing occluding foreground with background. The initial depth priority
    # remains conservative; this fixes naive integer-splat checker aliasing.
    bx,by=Hcoords(x,y,eye,pan_mode)
    samplex=bx+k*owner_depth
    l=np.floor(samplex).astype(np.float32)
    r=l+1.
    wt=np.clip(samplex-l,0,1)
    ld=remap(dep,l,by,border=cv2.BORDER_REPLICATE)
    rd=remap(dep,r,by,border=cv2.BORDER_REPLICATE)
    lc=remap(src,l,by,border=cv2.BORDER_REPLICATE)
    rc=remap(src,r,by,border=cv2.BORDER_REPLICATE)
    vl=np.abs(ld-owner_depth)<.10
    vr=np.abs(rd-owner_depth)<.10
    wl=(1-wt)*vl;wr=wt*vr
    norm=wl+wr
    owner_color=(wl[...,None]*lc+wr[...,None]*rc)/np.maximum(norm[...,None],1e-5)
    fallback=src.reshape(-1,3)[idx].reshape(H,W,3)
    owner_color=np.where((norm>1e-4)[...,None],owner_color,fallback).astype(np.float32)
    owner_color[~valid.reshape(H,W)]=0
    owner_depth[~valid.reshape(H,W)]=0
    return owner_color,owner_depth,valid.reshape(H,W)


def hole_repair(color,depth,valid,reach=19):
    """Only far/mid valid owners; no foreground donor. Never overwrite a valid pixel.

    Fill is intentionally simple; it cannot infer unknown textures.
    """
    h,w=valid.shape; x=np.arange(w)[None,:]
    donors=valid&(depth<.70)
    left=np.maximum.accumulate(np.where(donors,x,-w),axis=1)
    right=np.minimum.accumulate(np.where(donors,x,w*2)[:,::-1],axis=1)[:,::-1]
    L=np.clip(left,0,w-1).astype(np.int32);R=np.clip(right,0,w-1).astype(np.int32)
    rows=np.arange(h)[:,None]
    lv=depth[rows,L];rv=depth[rows,R]
    both=(left>=0)&(right<w)&((right-left)<=reach)&(np.abs(lv-rv)<.12)
    ld=x-left;rd=right-x
    one_l=(left>=0)&(ld<=max(3,reach//3))
    one_r=(right<w)&(rd<=max(3,reach//3))
    fill=(~valid)&(both|one_l|one_r)
    t=np.clip((x-left)/np.maximum(right-left,1),0,1).astype(np.float32)
    c=(1-t[...,None])*color[rows,L]+t[...,None]*color[rows,R]
    c=np.where((both&(~valid))[...,None],c,np.where((one_l&(~valid))[...,None],color[rows,L],color[rows,R]))
    out=color.copy();out[fill]=c[fill]
    outdep=depth.copy();outdep[fill]=np.where(both,(1-t)*lv+t*rv,np.where(one_l,lv,rv))[fill]
    return out,outdep,fill


def edge_source_mask(raw,rad=3):
    grad=np.abs(np.diff(raw,axis=1,prepend=raw[:,:1]))>.18
    grad|=np.abs(np.diff(raw,axis=1,append=raw[:,-1:]))>.18
    return maximum_filter1d(grad.astype(np.uint8),2*rad+1,axis=1)>0


def directional(src,raw,eye,pan_mode=False):
    """Low-cost restricted directional sample test; NOT old M3 HLSL."""
    base,depth,valid,sx,sy=inverse_warp(src,raw,eye,rad=1.8,pan_mode=pan_mode)
    d=smooth(raw,1.8)
    x,y=grid()
    l=remap(d,sx-2,sy,border=cv2.BORDER_REPLICATE)
    r=remap(d,sx+2,sy,border=cv2.BORDER_REPLICATE)
    edge=np.abs(l-r)>.13
    # Low-depth side of jump is the potential revealed background. Wrong
    # direction can erode a thin slat -- one of the tests this comparison exposes.
    direction=np.where(l<r,-1,1).astype(np.float32)
    candidates=[]
    for dist in (3,5,8,11,15):
        xx=sx+direction*dist
        dd=remap(raw,xx,sy,border=cv2.BORDER_REPLICATE)
        cc=remap(src,xx,sy,border=cv2.BORDER_REPLICATE)
        candidates.append((dd,cc,(xx>1)&(xx<W-2)))
    new=base.copy();dep=depth.copy()
    allow=edge&(depth>.30)
    for dd,cc,vv in candidates:
        take=allow&vv&(dd<dep-.16)
        new[take]=cc[take];dep[take]=dd[take]
    return new,dep,valid,{'source_fraction':1.,'target_fraction':float(allow.mean())}


def hybrid(src,raw,eye,pan_mode=False,radius=3):
    """Sparse edge-only owner *reference* + inverse base; no GT in repair.

    Demonstrates attainable quality if projected depth/color samples near edges
    are allowed to compete, not a claim of cheap production shader implementation.
    """
    base,bdepth,valid,sx,sy=inverse_warp(src,raw,eye,rad=.75,pan_mode=pan_mode)
    srcmask=edge_source_mask(raw,rad=radius)|(raw>.70)
    fc,fd,fvalid=fwd_owner(src,raw,eye,pan_mode,mask=srcmask)
    influence=maximum_filter1d(fvalid.astype(np.uint8),size=2*math.ceil(K)+7,axis=1)>0
    candidate=base.copy();cd=bdepth.copy()
    # output near owner is trusted over the inverse pull; otherwise use valid
    # near-edge source owner where present.
    overwrite=influence&fvalid
    candidate[overwrite]=fc[overwrite];cd[overwrite]=fd[overwrite]
    # For gap bands, conservatively repair only when the existing inverse pull
    # selected near, yet no sparse near owner covers this target.
    supported=fvalid&(fd<.70)
    repaired,rdepth,filled=hole_repair(fc,fd,supported,reach=int(K*1.3)+8)
    suspect=influence&(~fvalid)&(bdepth>.70)&filled
    candidate[suspect]=repaired[suspect];cd[suspect]=rdepth[suspect]
    # An exact source border failure should remain visible, not be hidden by clamp.
    return candidate,cd,valid,{'source_fraction':float(srcmask.mean()),'target_fraction':float(influence.mean()),'sparse_valid_fraction':float(fvalid.mean()),'hole_filled_fraction':float(suspect.mean())}


def full_forward(src,raw,eye,pan_mode=False):
    c,d,v=fwd_owner(src,raw,eye,pan_mode)
    final,depth,filled=hole_repair(c,d,v,reach=int(K*1.6)+6)
    return final,depth,(v|filled),{'hole_before':float((~v).mean()),'hole_after':float((~(v|filled)).mean()),'source_fraction':1.,'target_fraction':1.}


def evaluate_frame(im,dep,valid,gt,gtdep,ids):
    x,y=grid()
    # Far/mid pixels near any nearer visible object (GT used for scoring only).
    obj=ids>0
    band=maximum_filter1d(obj.astype(np.uint8),size=29,axis=1)>0
    bg_band=band&(ids==0)
    valid_region=np.ones_like(valid,bool) # all target pixels scored, holes penalized
    err=np.abs(im-gt).mean(axis=2)
    m_near=ids==2
    predicted_near=dep>.73
    intersection=(m_near&predicted_near).sum()
    union=(m_near|predicted_near).sum()
    edge_err=float((m_near^predicted_near).mean())
    out={'mae':float(err.mean()),'background_edge_mae':float(err[bg_band].mean()) if bg_band.any() else np.nan,
         'foreground_iou':float(intersection/union) if union else np.nan,
         'foreground_mismatch_fraction':edge_err,
         'foreground_leak_to_bg_fraction':float((predicted_near&bg_band).sum()/max(1,bg_band.sum())),
         'invalid_fraction':float((~valid).mean()),
         'large_error_fraction':float((err>.19).mean())}
    return out,err,bg_band


def im8(a):return np.uint8(np.clip(a,0,1)*255+.5)

def annotate_tiles(tiles,title,path):
    names=list(tiles)
    w,h=next(iter(tiles.values())).shape[1],next(iter(tiles.values())).shape[0]
    cv=Image.new('RGB',(len(names)*w,h+26),(13,15,18));d=ImageDraw.Draw(cv)
    for i,n in enumerate(names):
        cv.paste(Image.fromarray(im8(tiles[n])),(i*w,26));d.text((i*w+8,7),n,fill=(255,255,255))
    cv.save(path)



def world_stabilized_residual(pred,gt,ids,band,eye,pose,pan,layer_depth):
    """Subtract true frame GT, then track residual at fixed WORLD coordinates.

    Visibility and truth IDs are scoring-only and never enter an algorithm.
    This discounts legitimate camera/object-induced motion in the reference.
    """
    worldx,worldy=grid()
    e=1 if eye=='left' else -1
    sourcey=worldy-pose['camera_y']
    tx=invert_H(worldx-pose['camera_x']-e*K*layer_depth,sourcey,eye,pan)
    ty=sourcey-(e*(.83 if pan=='extreme' else .31) if pan else 0.)
    error=(pred-gt).astype(np.float32)
    er=remap(error,tx,ty,interp=cv2.INTER_LINEAR)
    true_owner=2 if layer_depth==D_FG else 0
    owner=remap(ids,tx,ty,interp=cv2.INTER_NEAREST)==true_owner
    edge=remap(band.astype(np.uint8),tx,ty,interp=cv2.INTER_NEAREST)>0
    inside=(tx>=1)&(tx<W-2)&(ty>=1)&(ty<H-2)
    return er,owner&inside,edge


def temporal_metrics(residuals,masks,regions):
    """World-coordinate residual flicker, excluding correctly changing GT.

    Require two consecutive frames with the SAME visible layer and within the
    ROI. No internal temporal smoothing is used by any candidate.
    """
    if len(residuals)<2:return {'tracked_delta':0.,'tracked_p95':0.,'pairs':0,'tracked_std':0.}
    es=np.stack(residuals,axis=0);ms=np.stack(masks,axis=0);roi=np.stack(regions,axis=0)
    changes=[]
    for t in range(1,len(es)):
        common=ms[t]&ms[t-1]&roi[t]&roi[t-1]
        if np.any(common):
            delta=np.abs(es[t]-es[t-1]).mean(axis=2)
            changes.append(delta[common])
    if not changes:return {'tracked_delta':float('nan'),'tracked_p95':float('nan'),'pairs':0,'tracked_std':float('nan')}
    all_delta=np.concatenate(changes)
    stable=(ms&roi).sum(axis=0)>=max(3,int(len(es)*.65))
    # Pixelwise temporal STD computed on visible frames only; it measures the
    # instability of the reconstruction error, not physical leaf movement.
    valid=(ms&roi)
    n=np.maximum(valid.sum(axis=0),1)
    mean=(es*valid[...,None]).sum(axis=0)/n[...,None]
    var=(((es-mean)**2)*valid[...,None]).sum(axis=0)/n[...,None]
    return {'tracked_delta':float(np.mean(all_delta)),
            'tracked_p95':float(np.percentile(all_delta,95)),
            'pairs':int(len(all_delta)),
            'tracked_std':float(np.sqrt(var.mean(axis=2))[stable].mean()) if stable.any() else float('nan')}


def gif_crop(tiles,scene):
    # Zoom to two pixels per source pixel to expose leaf/pixel flicker. Present
    # the same region and scale in every method and every frame.
    if scene=='foliage': rect=(97,48,277,172)
    else:rect=(46,54,226,178)
    keys=['GT','V2 envelope proxy','inverse sharp','edge hybrid','full forward']
    tw,th=rect[2]-rect[0],rect[3]-rect[1]
    canvas=Image.new('RGB',(len(keys)*tw*2,th*2+25),(16,18,20))
    d=ImageDraw.Draw(canvas)
    for j,k in enumerate(keys):
        raw=Image.fromarray(im8(tiles[k]))
        im=raw.crop(rect).resize((tw*2,th*2),resample=Image.Resampling.NEAREST)
        canvas.paste(im,(j*tw*2,25));d.text((j*tw*2+5,5),k,fill='white')
    return canvas


def run(out,frames=12,scenes=('weapon','foliage','natural','layers','border'),seed=SEED,scenarios_allow=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    clusters=foliage_clusters('foliage',seed)
    summary=[];videos={}
    methods=['v2_envelope_proxy','inverse_sharp','directional','hybrid','full_forward']
    tests=[('static_clean','clean',False,False,False),
           ('camera_motion','clean',True,False,True),
           ('object_motion','clean',True,True,True),
           ('pixel_noise','pixel',False,False,False),
           ('group49_depth','groups_depth',False,False,False),
           ('group49_color','groups_color',False,False,False),
           ('physical_sway','clean',False,True,False),
           ('late_depth','late_depth',True,True,True),
           ('depth_dropout','depth_dropout',False,False,False),
           ('source_fit_stress','clean',False,False,'extreme'),
           ('combined_crop_motion','combined',True,True,True)]
    # Keep the expensive suite focused. Every scene/eye/algorithm receives identical inputs.
    for scname in scenes:
      sc=texture_layers(scname,seed)
      scenarios=['static_clean','camera_motion','object_motion'] if scname in ('weapon','layers','border') else [t[0] for t in tests]
      if scname=='border':scenarios=['static_clean','camera_motion','source_fit_stress']
      if scname=='layers':scenarios=['static_clean','object_motion','combined_crop_motion','late_depth']
      if scenarios_allow is not None:scenarios=[name for name in scenarios if name in scenarios_allow]
      for scenario in scenarios:
        noise,move,objects,pan=next((a,b,c,d) for name,a,b,c,d in tests if name==scenario)
        nframes=frames if scenario!='static_clean' else 1
        tracks={m:{'left':[],'right':[]} for m in methods}
        spatial={m:{eye:{layer:{'res':[],'mask':[],'roi':[]} for layer in ('bg_edge','fg','cluster')} for eye in ('left','right')} for m in methods}
        pics=[]
        for fr in range(nframes):
            src,sd,sid,pose=render(sc,'center',fr,scname,False,cam_move=move,physical_move=objects)
            src=capture_color(src,fr,noise,clusters,seed)
            raw,patch=capture_depth(sd,sid,fr,noise,clusters,seed)
            if noise=='late_depth' and fr>0:
                _,old_depth,_,_=render(sc,'center',fr-1,scname,False,cam_move=move,physical_move=objects)
                raw=old_depth # intentionally violates source/depth epoch matching
            crop=(W*.5+22*np.sin(fr*.72),H*.50+14*np.cos(fr*.49)) if scenario=='combined_crop_motion' else None
            # Current input deliberately retains raw/conditioned variants; near
            # depth compare is not an exact M4 conditioner replication.
            base_d=condition_depth(raw,crop_center=crop)
            for eye in ('left','right'):
                gt,gtd,ids,_=render(sc,eye,fr,scname,pan,cam_move=move,physical_move=objects)
                responses={}
                for method in methods:
                    if method=='v2_envelope_proxy':
                        c,dep,v,*_=inverse_warp(src,base_d,eye,rad=0,pan_mode=pan);detail={}
                    elif method=='inverse_sharp':
                        c,dep,v,*_=inverse_warp(src,raw,eye,rad=0,pan_mode=pan);detail={}
                    elif method=='directional':c,dep,v,detail=directional(src,base_d,eye,pan_mode=pan)
                    elif method=='hybrid':c,dep,v,detail=hybrid(src,raw,eye,pan_mode=pan)
                    else:c,dep,v,detail=full_forward(src,raw,eye,pan_mode=pan)
                    metric,err,band=evaluate_frame(c,dep,v,gt,gtd,ids)
                    metric.update(detail)
                    metric['frame']=fr
                    for lname,dd in (('bg_edge',D_BG),('fg',D_FG),('cluster',D_BG)):
                        er,own,edge=world_stabilized_residual(c,gt,ids,band,eye,pose,pan,dd)
                        if lname=='cluster':
                            # Source-space cluster masks mapped into background
                            # world positions; used primarily in static camera tests.
                            cluster_mask=np.any(np.stack(clusters,axis=0),axis=0)
                            edge=maximum_filter1d(cluster_mask.astype(np.uint8),size=33,axis=1)>0
                            own=(np.ones_like(own,bool) if not move else own)
                        state=spatial[method][eye][lname]
                        state['res'].append(er);state['mask'].append(own)
                        state['roi'].append(edge if lname!='fg' else (maximum_filter1d(edge.astype(np.uint8),size=23,axis=1)>0))
                    tracks[method][eye].append(metric)
                    responses[method]=(c,dep,err)
                if eye=='left' and (scname in ('weapon','foliage','natural') and scenario in ('camera_motion','group49_depth','group49_color','combined_crop_motion') or (scname=='border' and scenario=='static_clean')):
                    tiles={'GT':gt,'V2 envelope proxy':responses['v2_envelope_proxy'][0], 'inverse sharp':responses['inverse_sharp'][0], 'directional':responses['directional'][0], 'edge hybrid':responses['hybrid'][0], 'full forward':responses['full_forward'][0]}
                    if fr in (0,2,nframes//2,nframes-1):
                        annotate_tiles(tiles,f'{scname}_{scenario}_f{fr:02d}',out/f'{scname}_{scenario}_f{fr:02d}.png')
                    if nframes>1:
                        videos.setdefault((scname,scenario),[]).append(gif_crop(tiles,scname))
        for method in methods:
            for eye in ('left','right'):
                rows=tracks[method][eye]
                row={'scene':scname,'scenario':scenario,'method':method,'eye':eye,'frames':len(rows)}
                for key in ('mae','background_edge_mae','foreground_iou','foreground_mismatch_fraction','foreground_leak_to_bg_fraction','invalid_fraction','large_error_fraction','source_fraction','target_fraction','hole_before','hole_after','hole_filled_fraction'):
                    vals=[f[key] for f in rows if key in f and np.isfinite(f[key])]
                    if vals:row[key]=float(np.mean(vals))
                # Per-frame error variations are an additional metric and should
                # NOT be confused with scene-tracked or perceptual temporal flicker.
                er=np.array([f['background_edge_mae'] for f in rows]);er=er[np.isfinite(er)]
                row['edge_mae_frame_variation']=float(np.std(er)) if len(er)>1 else 0.
                row['edge_mae_frame_delta']=float(np.abs(np.diff(er)).mean()) if len(er)>1 else 0.
                for lname in ('bg_edge','fg','cluster'):
                    state=spatial[method][eye][lname]
                    for k,v in temporal_metrics(state['res'],state['mask'],state['roi']).items():
                        row[f'{lname}_{k}']=v
                summary.append(row)
                if len(summary)%10==0:
                    (out/'metrics_partial.json').write_text(json.dumps({'seed':seed,'partial':True,'results':summary},indent=2))
    for (scname,scenario),ims in videos.items():
        if len(ims)>1:
            # 20-FPS MP4 is more practical than a palette-reduced high-frequency
            # GIF for inspecting simultaneous 49-pixel flicker and real motion.
            width,height=ims[0].size
            video=cv2.VideoWriter(str(out/f'{scname}_{scenario}_20fps.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),20,(width,height))
            for img in ims:
                video.write(cv2.cvtColor(np.asarray(img),cv2.COLOR_RGB2BGR))
            video.release()
            # Small convenient loop for the two central foliage stress cases.
            if scname=='foliage' and scenario in ('group49_depth','group49_color'):
                reduced=[im.resize((width//2,height//2)) for im in ims]
                reduced[0].save(out/f'{scname}_{scenario}_preview.gif',save_all=True,append_images=reduced[1:],duration=150,loop=0,optimize=False)
    (out/'metrics.json').write_text(json.dumps({'seed':seed,'geometry':'affine restriction of per-eye source homography; inverse root 8 bisections plus secant','content_fps':20,'limitations':['not exact production shader','no actual DLSS depth/real frames','CPU operations are not GPU milliseconds','world-tracked difference-of-errors is measured after GT subtraction; not a headset perceptual metric'],'results':summary},indent=2))
    print('saved',len(summary),'method-eye-scenario summaries in',out)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',default='extended/results');p.add_argument('--frames',type=int,default=12);p.add_argument('--scenes',nargs='*',default=['weapon','foliage','natural','layers','border']);p.add_argument('--scenarios',nargs='*',default=None);a=p.parse_args()
    run(a.out,a.frames,a.scenes,scenarios_allow=a.scenarios)

"""Stdlib reference mathematics, not a replacement for production GPU execution."""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class Profile:
    close: float
    far: float
    start_m: float
    end_m: float
    near_m: float
    softness: float

PROFILES={
    'P0':Profile(.5,.5,2.,8.,0.,.5),
    'P1':Profile(0.,0.,7.869,32.052,.2,.99),
    'P2':Profile(0.,.9,7.869,32.052,.2,.99),
}

def v2_map(d,p):
    lo=max(0.,1/p.end_m)
    hi=max(lo+1e-6,1/p.start_m)
    sc=max(.1,1-.9*p.close); sf=max(.1,1-.9*p.far); sm=(sc+sf)/2
    a=lo/sf; b=a+(hi-lo)/sm
    return d/sf if d<=lo else a+(d-lo)/sm if d<=hi else b+(d-hi)/sc

def v2_unmap(d,p):
    lo=max(0.,1/p.end_m)
    hi=max(lo+1e-6,1/p.start_m)
    sc=max(.1,1-.9*p.close); sf=max(.1,1-.9*p.far); sm=(sc+sf)/2
    a=lo/sf; b=a+(hi-lo)/sm
    return d*sf if d<=a else lo+(d-a)*sm if d<=b else hi+(d-b)*sc

def knee(d,p):
    d=max(d,0.)
    if p.near_m<=0:
        return min(d,12.5)
    k=1/p.near_m
    return k+(d-k)/(1+(d-k)/k) if d>k else d

def envelope(seeds,pen,eye=1,r=1.):
    """Fixed directional penalties: +x falloff is steeper iff k>0."""
    left_pen=pen*(r if eye>0 else 1.)
    right_pen=pen*(r if eye<0 else 1.)
    out=list(seeds)
    for x in range(1,len(out)):
        out[x]=max(out[x],out[x-1]-left_pen,0.)
    for x in range(len(out)-2,-1,-1):
        out[x]=max(out[x],out[x+1]-right_pen,0.)
    return out

def sample(values,x,spacing=1.):
    """Grid texel centers are integer reference positions, clamped as HLSL."""
    x=max(0.,min(len(values)-1.,x/spacing))
    i=int(math.floor(x)); t=x-i
    return values[i]*(1-t)+values[min(i+1,len(values)-1)]*t

def solve(base,k,read,cap):
    """Literal 8-bisection + cached-residual secant; final source clamp by caller."""
    lo=min(base,base+k*cap); hi=max(base,base+k*cap)
    rlo=rhi=last=last_r=prev=prev_r=0.
    have_lo=have_hi=False
    for _ in range(8):
        mid=.5*(lo+hi)
        residual=base+k*read(mid)-mid
        prev,prev_r=last,last_r
        last,last_r=mid,residual
        if residual>0:
            lo,rlo,have_lo=mid,residual,True
        else:
            hi,rhi,have_hi=mid,residual,True
    root=.5*(lo+hi)
    if have_lo and have_hi and rlo-rhi>1e-9:
        root=lo+(hi-lo)*rlo/(rlo-rhi)
    elif abs(last_r-prev_r)>1e-9:
        root=last-last_r*(last-prev)/(last_r-prev_r)
    return max(lo,min(hi,root))

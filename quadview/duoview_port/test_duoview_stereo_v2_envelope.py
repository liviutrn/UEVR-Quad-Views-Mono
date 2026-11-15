"""V2 depth-coordinate conditioner oracle. No Windows HLSL or WARP execution."""
import random

def warp(d,n,f,c,g):
    f=max(0.,f);n=max(f+1e-6,n)
    a=max(.1,1.-.9*c);b=max(.1,1.-.9*g);m=(a+b)*.5
    u=f/b;v=u+(n-f)/m
    return d/b if d<=f else (u+(d-f)/m if d<=n else v+(d-n)/a)

def unwarp(u,n,f,c,g):
    f=max(0.,f);n=max(f+1e-6,n)
    a=max(.1,1.-.9*c);b=max(.1,1.-.9*g);m=(a+b)*.5
    p=f/b;q=p+(n-f)/m
    return u*b if u<=p else (f+(u-p)*m if u<=q else n+(u-q)*a)

def test():
    r=random.Random(318333)
    cases=0
    for width in (2,3,8,16,31,64,127):
        for _ in range(400):
            n=r.uniform(.25,2.5);f=r.uniform(.001,.95*n)
            close=r.random();far=r.random();stepbound=r.uniform(.005,.1)
            raw=[r.random()*2.5 if r.random()<.25 else 0. for x in range(width)]
            src=[warp(z,n,f,close,far) for z in raw]
            row=src[:];step=1
            while step<width:
                row=[max(row[x],
                    row[x-step]-step*stepbound if x>=step else 0.,
                    row[x+step]-step*stepbound if x+step<width else 0.)
                    for x in range(width)]
                step*=2
            oracle=[max(0.,max(z-abs(x-i)*stepbound for i,z in enumerate(src)))
                    for x in range(width)]
            assert max(abs(a-b) for a,b in zip(row,oracle))<1e-10
            depth=[unwarp(z,n,f,close,far) for z in row]
            assert all(abs(a-b)<stepbound+1e-10 for a,b in zip(depth,depth[1:]))
            assert all(abs(unwarp(warp(z,n,f,close,far),n,f,close,far)-z)<1e-9 for z in raw)
            cases+=1
    vals=[.10,.05]+[0.]*14;scales=[.0125,.00125]+[.0125]*14
    for step in (1,2,4,8):
        nxt=vals[:];snext=scales[:]
        for x in range(16):
            options=[(vals[x],scales[x])]
            if x>=step:options.append((vals[x-step]-step*scales[x-step],scales[x-step]))
            if x+step<16:options.append((vals[x+step]-step*scales[x+step],scales[x+step]))
            nxt[x],snext[x]=max(options,key=lambda pair:pair[0])
        vals,scales=nxt,snext
    assert abs(vals[8]-vals[9])>.0125
    print('PASS',cases,'mapped cone fields, inverse, no-fold and old counterexample')
if __name__=='__main__':test()

#!/usr/bin/env python3
"""Pure Python numerical oracle for the M2.1 conditioned-field / inverse warp.

No GPU or SDK needed. The shader's one-grid max envelope and eight-read
safeguarded secant are compared with a 36-step monotone bisection reference.
Tests moving crops, steps both within/across crop boundary, two eye signs.
"""
from __future__ import annotations

from bisect import bisect_right

N = 512
EYE_PIXELS = 2000
K = 0.02
CAP = 2.0


def clamp(v, a, b):
    return max(a, min(b, v))


def raw_near(u, left, right):
    return 1.65 if left <= u < right else 0.10


def fused_seed(crop, fine_step):
    result = []
    c0, c1 = crop
    for j in range(N):
        u = (j + .5) / N
        # Coarse near max is the original low resolution 3x3 neighborhood.
        coarse = max(raw_near((j + t + .5) / N, .34, .44) for t in (-1, 0, 1))
        if not (c0 <= u < c1):
            result.append(coarse)
            continue
        local = (u - c0) / (c1 - c0)
        # Fine is independently sampled at a distinct (higher) resolution.
        fine = max(raw_near((int(local * 1024) + t + .5) / 1024,
                            fine_step[0], fine_step[1]) for t in (-1, 0, 1))
        edge = min(local, 1 - local)
        t = clamp(edge / .075, 0, 1)
        feather = t*t*(3 - 2*t)
        result.append(coarse + (fine - coarse) * feather)
    return result


def condition(seed, sharpness):
    slope = sharpness / (K * N)
    current = seed[:]
    step = 1
    while step < N and (step - 1) * slope < CAP:
        nxt = current[:]
        for j in range(N):
            if j >= step:
                nxt[j] = max(nxt[j], current[j-step] - step*slope)
            if j+step < N:
                nxt[j] = max(nxt[j], current[j+step] - step*slope)
        current = nxt
        step *= 2
    return current


def sample(d, u):
    x = clamp(u*N - .5, 0, N-1)
    i = int(x)
    j = min(i+1, N-1)
    return d[i] + (d[j]-d[i]) * (x-i)


def secant(d, base, k):
    lo = min(base, base + k*CAP)
    hi = max(base, base + k*CAP)
    x0 = base
    r0 = k*sample(d, x0)
    x1 = clamp(x0+r0, lo, hi)
    for _ in range(1, 8):
        r1 = base + k*sample(d, x1) - x1
        den = r1-r0
        step = -r1*(x1-x0)/den if abs(den)>1e-8 and abs(x1-x0)>1e-8 else r1
        if abs(step)>60*abs(r1) or x1+step < lo or x1+step > hi:
            step = r1
        x0, r0, x1 = x1, r1, clamp(x1+step, lo, hi)
    return x1


def bisection(d, base, k):
    lo = min(base,base+k*CAP)
    hi = max(base,base+k*CAP)
    for _ in range(36):
        mid = .5*(lo+hi)
        f = base+k*sample(d,mid)-mid
        if f>0:
            lo=mid
        else:
            hi=mid
    return .5*(lo+hi)


def verify():
    cases = 0
    max_error = 0
    # Crop changes position, fine-depth step, and coarse/fine disagreement.
    for crop in ((.20,.66),(.36,.82)):
        for fine_step in ((.20,.37),(.45,.54)):
            seed=fused_seed(crop,fine_step)
            for sharpness in (.25,.50,.65,.80,.90):
                d=condition(seed,sharpness)
                slope=sharpness/(K*N)
                for j in range(N-1):
                    assert abs(d[j+1]-d[j]) <= slope + 1e-10, (
                        "global depth-slope violation",crop,fine_step,sharpness,j)
                for k in (-K,K):
                    # The source->eye map must not fold (k*d' < 1).
                    mapped=[(j+.5)/N - k*d[j] for j in range(N)]
                    assert all(mapped[j+1] > mapped[j] for j in range(N-1)), (
                        "folded stereo map",crop,fine_step,sharpness,k)
                    for pixel in range(80,EYE_PIXELS-80,3):
                        base=(pixel+.5)/EYE_PIXELS
                        actual=secant(d,base,k)
                        expected=bisection(d,base,k)
                        error=abs(actual-expected)*EYE_PIXELS
                        max_error=max(max_error,error)
                        # A numerical tolerance is not a headset guarantee.
                        assert error<1.0, (
                            "secant inverse error >=1px",crop,fine_step,
                            sharpness,k,pixel,error)
                        cases+=1
    print(f"M2.1: {cases} inverse roots, two gaze crops, raw depth seams and "
          f"five sharpnesses: monotone and <1 px; peak={max_error:.4f} px")


if __name__=="__main__":
    verify()

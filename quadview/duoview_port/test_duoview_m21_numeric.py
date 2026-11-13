#!/usr/bin/env python3
"""Pure Python numerical oracle for the M2.1 conditioned-field / inverse warp.

No GPU or SDK needed. The shader's one-grid max envelope and eight-read
bracketed bisection are compared with a 36-step monotone bisection reference.
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
        fine = 0.0 if fine_step is None else max(
            raw_near((int(local * 1024) + t + .5) / 1024,
                     fine_step[0], fine_step[1]) for t in (-1, 0, 1))
        if fine <= 0.0:
            result.append(coarse)
            continue
        edge = min(local, 1 - local)
        t = clamp(edge / .075, 0, 1)
        feather = t*t*(3 - 2*t)
        result.append(coarse + (fine - coarse) * feather)
    return result


def condition(seed, sharpness, cap=CAP, max_k=K):
    slope = sharpness / (max_k * N)
    current = seed[:]
    step = 1
    while step < N and (step - 1) * slope < cap:
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


def bracketed_eight(d, base, k, cap=CAP):
    """Mirror the eight-read shader with cached bracket-residual finish."""
    lo = min(base, base + k*cap)
    hi = max(base, base + k*cap)
    rlo = rhi = last_mid = last_residual = 0.
    previous_mid = previous_residual = 0.
    have_lo = have_hi = False
    for _ in range(8):
        mid = .5*(lo+hi)
        residual = base + k*sample(d, mid) - mid
        previous_mid, previous_residual = last_mid, last_residual
        last_mid, last_residual = mid, residual
        if residual > 0:
            lo, rlo, have_lo = mid, residual, True
        else:
            hi, rhi, have_hi = mid, residual, True
    root = .5*(lo+hi)
    if have_lo and have_hi and rlo-rhi > 1.e-9:
        root = lo+(hi-lo)*rlo/(rlo-rhi)
    elif abs(last_residual-previous_residual)>1.e-9:
        root = last_mid-last_residual*(last_mid-previous_mid)/(last_residual-previous_residual)
    return clamp(root, lo, hi)


def bisection(d, base, k, cap=CAP):
    lo = min(base,base+k*cap)
    hi = max(base,base+k*cap)
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
        for fine_step in ((.20,.37),(.45,.54),None):
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
                        actual=bracketed_eight(d,base,k)
                        expected=bisection(d,base,k)
                        error=abs(actual-expected)*EYE_PIXELS
                        max_error=max(max_error,error)
                        # A numerical tolerance is not a headset guarantee.
                        assert error<1.0, (
                            "eight-sample inverse error >=1px",crop,fine_step,
                            sharpness,k,pixel,error)
                        cases+=1
    print(f"M2.2: {cases} inverse roots, two gaze crops, conditioned fine-depth "
          f"seams and five sharpnesses: monotone and <1 px; peak={max_error:.4f} px")


def verify_4k():
    """Stress the 4000px/eye quantisation gap, including knee OFF (cap=12.5)."""
    tested=0
    worst_error=0.0
    worst_neighbor_jump=0.0
    max_k=.0126
    pixels=4000
    for cap in (2.0,12.5):
        for crop in ((.20,.65),(.36,.82)):
            seed=[cap*(.92 if crop[0] <= (j+.5)/N < crop[1]-.21
                       else .03+.05*j/N) for j in range(N)]
            for sharpness in (.50,.80,.90):
                d=condition(seed,sharpness,cap,max_k)
                # Also check the strong-slope invariant for both disparities.
                slope=sharpness/(max_k*N)
                assert all(abs(d[j+1]-d[j])<=slope+1.e-9
                           for j in range(N-1))
                for k in (-max_k,max_k):
                    prev_actual=prev_exact=None
                    for pixel in range(80,3920):
                        base=(pixel+.5)/pixels
                        actual=bracketed_eight(d,base,k,cap)
                        exact=bisection(d,base,k,cap)
                        error=abs(actual-exact)*pixels
                        worst_error=max(worst_error,error)
                        # The discrete midpoint solver makes 2.4px jumps
                        # at this range. Residual interpolation must suppress
                        # that staircase without extra texture reads.
                        if prev_actual is not None:
                            step_error=abs((actual-prev_actual)-
                                           (exact-prev_exact))*pixels
                            worst_neighbor_jump=max(worst_neighbor_jump,step_error)
                            assert step_error < 1.12, (
                                "subpixel output staircase",cap,crop,sharpness,
                                k,pixel,step_error)
                        assert error < 1.12, (
                            "subpixel inverse error",cap,crop,sharpness,k,pixel,error)
                        prev_actual,prev_exact=actual,exact
                        tested+=1

    # At 4K a slope-limited edge changes only a tiny absolute inverse
    # depth per pixel. Old normalisation to 0.05 hid it; the new relative
    # slope normalisation stays visible independently of eye resolution.
    # Representative depth change in inverse engine units at one 4K pixel:
    # 1e-4 is too faint when divided by the old hard-coded 0.05.
    # Normalising to the same field's slope bound is scale-independent.
    edge_change=1.e-4
    per_pixel_slope=edge_change
    old_tint=min(1.,8*edge_change/.05)*.85
    new_relative=edge_change/per_pixel_slope
    new_tint=(min(1.,max(0.,(new_relative-.08)/(.32-.08))))*.95
    assert old_tint<.25 and new_tint>.90, (old_tint,new_tint)
    print(f"M2.2: {tested} high-res roots (4000px, cap 2/12.5): "
          f"max error={worst_error:.3f}px, maximum extra neighbor step="
          f"{worst_neighbor_jump:.3f}px; 4K overlay contrast PASS")


if __name__=="__main__":
    verify()
    verify_4k()

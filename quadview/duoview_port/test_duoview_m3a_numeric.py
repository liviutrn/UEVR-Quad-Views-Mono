#!/usr/bin/env python3
"""Numeric model of the M3a HLSL (pure Python; mirrors the shader line by line).

Checks: asymmetric doubling == brute-force envelope; per-eye warp stays
monotone (occlusion side bounded); disocclusion side stays sharp; hole fill
samples background on the correct side; vertical max keeps both bounds;
OFF path equals the original symmetric envelope.
"""
import random


def envelope_doubling(row, pf, ps, fold, limit):
    w = len(row)
    row = list(row)
    pmin = min(pf, ps) if ps > 0 else pf
    step = 1
    while step < w and (step - 1) * pmin < limit:
        nxt = []
        for x in range(w):
            v = row[x]
            xf, xs = x + fold * step, x - fold * step
            if 0 <= xf < w:
                v = max(v, row[xf] - step * pf)
            if ps > 0 and 0 <= xs < w:
                v = max(v, row[xs] - step * ps)
            nxt.append(v)
        row = nxt
        step *= 2
    return row


def envelope_brute(row, pf, ps, fold):
    w = len(row)
    out = []
    for x in range(w):
        v = row[x]
        for x2 in range(w):
            d = (x2 - x) * fold
            if d > 0:
                v = max(v, row[x2] - d * pf)
            elif d < 0 and ps > 0:
                v = max(v, row[x2] + d * ps)
        out.append(v)
    return out


def symmetric_original(row, p, limit):
    w = len(row)
    row = list(row)
    step = 1
    while step < w and (step - 1) * p < limit:
        row = [max(row[x], (row[x - step] - step * p) if x >= step else 0.0,
                   (row[x + step] - step * p) if x + step < w else 0.0) for x in range(w)]
        step *= 2
    return row


def sample(field, u):
    # LinearClamp with texel centres at (i+.5)/w, clamped to [.5, w-.5]
    w = len(field)
    c = min(max(u * w, .5), w - .5) - .5
    i = int(c)
    t = c - i
    j = min(i + 1, w - 1)
    return field[i] * (1 - t) + field[j] * t


def pull(field, base, k, cap, fill_threshold):
    delta = k * cap
    lo, hi = min(base, base + delta), max(base, base + delta)
    r_lo = r_hi = last_mid = last_r = prev_mid = prev_r = 0.0
    have_lo = have_hi = False
    for _ in range(8):
        mid = .5 * (lo + hi)
        r = base + k * sample(field, mid) - mid
        prev_mid, prev_r = last_mid, last_r
        last_mid, last_r = mid, r
        if r > 0:
            lo, r_lo, have_lo = mid, r, True
        else:
            hi, r_hi, have_hi = mid, r, True
    root = .5 * (lo + hi)
    if have_lo and have_hi and r_lo - r_hi > 1e-9:
        root = lo + (hi - lo) * r_lo / (r_lo - r_hi)
    elif abs(last_r - prev_r) > 1e-9:
        root = last_mid - last_r * (last_mid - prev_mid) / (last_r - prev_r)
    root = min(max(root, lo), hi)
    if fill_threshold > 0:
        root = fill(field, base, root, k, fill_threshold)
    return min(max(root, 0.0), 1.0)


def fill(field, base, root, k, threshold):
    du = 1.0 / len(field)
    dl, dr = sample(field, root - du), sample(field, root + du)
    stretch = 1.0 - k * (dr - dl) / (2.0 * du)
    if not stretch > threshold:
        return root
    direction = 1.0 if dr < dl else -1.0
    ub = root
    d = sample(field, ub)
    for _ in range(32):
        un = ub + direction * du
        dn = sample(field, un)
        flat = abs(k * (dn - d)) < .5 * du
        ub, d = un, dn
        if flat:
            break
    um = 2.0 * ub - (base + k * d)
    if (um - ub) * direction < 0:
        um = ub
    if abs(sample(field, um) - d) > max(.05 * d, 1e-4):
        um = ub
    return min(max(um, 0.0), 1.0)


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL: " + msg)
    print("PASS: " + msg)


def main():
    rnd = random.Random(7)
    w = 96
    # 1) asymmetric doubling is exact, both eyes, with and without a soft side
    worst = 0.0
    for _ in range(200):
        row = [rnd.choice([0.0, 0.2, 0.9, 2.5]) if rnd.random() < .3 else rnd.random() * .3 for _ in range(w)]
        for fold in (1, -1):
            for ps in (0.0, .02):
                a = envelope_doubling(row, .05, ps, fold, 1e9)
                b = envelope_brute(row, .05, ps, fold)
                worst = max(worst, max(abs(x - y) for x, y in zip(a, b)))
    check(worst < 1e-9, f"asymmetric doubling equals brute-force envelope (max err {worst:.2e})")

    # 2) OFF path: symmetric doubling equals brute force with equal penalties both sides
    row = [rnd.random() for _ in range(w)]
    a = symmetric_original(row, .03, 1e9)
    b = envelope_brute(row, .03, .03, 1)
    check(max(abs(x - y) for x, y in zip(a, b)) < 1e-9, "symmetric OFF path unchanged (two-sided equal penalty)")

    # 3) per-eye warp: weapon-like near box, both eye signs
    seed = [0.05] * w
    for x in range(40, 60):
        seed[x] = 3.0
    s_fold = .95
    for k in (.02, -.02):
        fold = 1 if k >= 0 else -1
        pf = s_fold / (abs(k) * w)
        field = envelope_doubling(seed, pf, 0.0, fold, 1e9)
        # occlusion side bounded: k*dD/du <= s_fold everywhere
        slope = max(k * (field[i + 1] - field[i]) * w for i in range(w - 1))
        check(slope <= s_fold + 1e-6, f"k={k:+}: occlusion side keeps k*D' <= {s_fold} (max {slope:.4f})")
        # disocclusion side stays sharp: one-texel step remains
        steps = [abs(field[i + 1] - field[i]) for i in range(w - 1)]
        check(max(steps) > 2.5, f"k={k:+}: disocclusion side stays a sharp step (max step {max(steps):.2f})")
        # forward map f(u)=u-k*D(u) is monotone on the bilinear field
        us = [i / 2000 for i in range(2001)]
        f = [u - k * sample(field, u) for u in us]
        check(all(f[i + 1] >= f[i] - 1e-12 for i in range(2000)), f"k={k:+}: warp is monotone (no folds)")
        # 4) hole fill: every filled target lands on background (low depth), on the far side
        cap = 3.0
        filled = 0
        for t in range(400):
            base = t / 400
            plain = pull(field, base, k, cap, 0.0)
            withfill = pull(field, base, k, cap, 2.0)
            if abs(plain - withfill) > 1e-9:
                filled += 1
                check_bg = sample(field, withfill) < .2
                if not check_bg:
                    raise SystemExit(f"FAIL: k={k:+} base={base:.4f} fill sampled depth {sample(field, withfill):.3f}")
        check(filled > 0, f"k={k:+}: disocclusion hole detected and filled with background ({filled} targets)")
        # non-hole targets unchanged far from the box
        check(abs(pull(field, .1, k, cap, 2.0) - pull(field, .1, k, cap, 0.0)) < 1e-12,
              f"k={k:+}: targets outside the hole are untouched by fill")

    # 5) vertical max of translated rows keeps both one-sided bounds
    rows = [envelope_doubling([rnd.choice([0, 0, 1.5]) for _ in range(w)], .05, 0.0, 1, 1e9) for _ in range(8)]
    pv = .3
    col = [max(rows[y2][x] - abs(y - y2) * pv for y2 in range(8)) for y in range(8) for x in range(w)]
    ok = True
    for y in range(8):
        r = col[y * w:(y + 1) * w]
        ok = ok and all(r[i + 1] - r[i] <= .05 + 1e-9 for i in range(w - 1))
    check(ok, "vertical taper preserves the occlusion-side bound per slice")
    print("M3a numeric model: all checks passed")


if __name__ == "__main__":
    main()

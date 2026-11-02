#!/usr/bin/env python3
"""Check a TriView_Capture_N.zip written by the Tri-View build (no headset questions needed).

  python analyze_triview_capture.py TriView_Capture_1.zip [more.zip ...]

Prints PASS/FAIL lines:
  placement  - left fovea only at (0,0) of the main target, right fovea only at (0,0) of the capture target,
               periphery only inside its rect of its own target (nothing painted over a fovea),
  edges      - both eyes' outer edges are filled (periphery reached the XR image),
  geometry   - inside each fovea window, the fovea and the periphery show the same scene at the same place
               (normalised cross-correlation of the two at periphery resolution, best shift in pixels),
  seams      - brightness just inside vs just outside the fovea window (shading match).
Needs numpy and Pillow.
"""
import io
import re
import sys
import zipfile

import numpy as np
from PIL import Image


def load(z, name):
    return np.asarray(Image.open(io.BytesIO(z.read(name))).convert("RGB"), dtype=np.float32)


def stats(report):
    out = {}
    for m in re.finditer(r"^(\S+) (\S+) \[(\d+),(\d+)\)-\[(\d+),(\d+)\): nonblack ([\d.]+)% mean rgb ([\d.]+) ([\d.]+) ([\d.]+)",
                         report, re.M):
        out[(m.group(1), m.group(2))] = (float(m.group(7)), float(m.group(8)), float(m.group(9)), float(m.group(10)))
    return out


def luma(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def analyse(path):
    z = zipfile.ZipFile(path)
    report = z.read("report.txt").decode("utf-8", "replace")
    s = stats(report)
    print(f"== {path}")
    print(report.split("\n--- pixel")[0].strip())
    ok = lambda c: "PASS" if c else "FAIL"
    for img in ("main_left_half", "capture"):
        inside = s.get((img, "fovea"), (0,))[0]
        outside = max(s.get((img, "right_of_fovea"), (0,))[0], s.get((img, "below_fovea"), (0,))[0])
        print(f"placement {img}: fovea {inside:.1f}% non-black, outside {outside:.1f}% -> {ok(inside > 50 and outside < 5)}")
    p_in = s.get(("periphery", "image"), (0,))[0]
    p_out = max(s.get(("periphery", "right_of_image"), (0,))[0], s.get(("periphery", "below_image"), (0,))[0])
    print(f"placement periphery: image {p_in:.1f}%, outside {p_out:.1f}% -> {ok(p_in > 50 and p_out < 5)}")
    for e in ("L", "R"):
        edge = min(s.get(("xr_both_eyes", e + "_outer_edge"), (0,))[0], s.get(("xr_both_eyes", e + "_top_edge"), (0,))[0])
        print(f"edges {e}: {edge:.1f}% non-black -> {ok(edge > 50)}")
        for side in ("left", "right"):
            a = s.get(("xr_both_eyes", f"{e}_seam_{side}_inside"))
            b = s.get(("xr_both_eyes", f"{e}_seam_{side}_outside"))
            if a and b:
                la, lb = luma(a[1:]), luma(b[1:])
                rel = abs(la - lb) / max(1.0, (la + lb) / 2)
                print(f"seams {e} {side}: inside {la:.1f} outside {lb:.1f} (diff {100 * rel:.0f}%)")
    # geometry: fovea content vs periphery content at the same directions
    nums = lambda key: [float(x) for x in re.search(key, report).groups()]
    win = nums(r"window L u ([\d.]+)\.\.([\d.]+) v ([\d.]+)\.\.([\d.]+) R u ([\d.]+)\.\.([\d.]+) v ([\d.]+)\.\.([\d.]+)") \
        if "window L u" in report else nums(r"window u ([\d.]+)\.\.([\d.]+) v ([\d.]+)\.\.([\d.]+)") * 2
    maps = nums(r"map L ax ([-\d.]+) bx ([-\d.]+) ay ([-\d.]+) by ([-\d.]+) \| map R ax ([-\d.]+) bx ([-\d.]+) ay ([-\d.]+) by ([-\d.]+)")
    pw, ph = [int(x) for x in re.search(r"periphery (\d+)x(\d+)\n", report).groups()]
    xr = load(z, "xr_both_eyes_half.bmp").mean(axis=2)
    per = load(z, "periphery_half.bmp").mean(axis=2)
    H, W2 = xr.shape
    E = W2 // 2
    for i, e in enumerate(("L", "R")):
        u0, u1, v0, v1 = win[4 * i:4 * i + 4]
        ax, bx, ay, by = maps[4 * i:4 * i + 4]
        # sample a grid inside the window (away from the feather) in eye UV
        us = np.linspace(u0 + 0.12 * (u1 - u0), u1 - 0.12 * (u1 - u0), 48)
        vs = np.linspace(v0 + 0.12 * (v1 - v0), v1 - 0.12 * (v1 - v0), 48)
        U, V = np.meshgrid(us, vs)
        fovea = xr[np.clip((V * H).astype(int), 0, H - 1), np.clip((U * E).astype(int) + i * E, 0, W2 - 1)]
        best = (-2.0, 0, 0)
        for dy in range(-6, 7):
            for dx in range(-6, 7):
                px = np.clip(((ax * U + bx) * pw / 2).astype(int) + dx, 0, per.shape[1] - 1)
                py = np.clip(((ay * V + by) * ph / 2).astype(int) + dy, 0, per.shape[0] - 1)
                c = ncc(fovea, per[py, px])
                if c > best[0]:
                    best = (c, dx, dy)
        c, dx, dy = best
        print(f"geometry {e}: correlation {c:.2f} at shift ({dx},{dy}) periphery px -> "
              f"{ok(c > 0.6 and abs(dx) <= 3 and abs(dy) <= 3)}")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        analyse(arg)

#!/usr/bin/env python3
"""B31 math/static checks; exact compositor behavior is separately WARP-tested."""
from pathlib import Path
import math

root = Path(__file__).resolve().parent
shader = (root / "QuadViewComposite.hlsl").read_text(encoding="utf-8")
backend = (root / "QuadViewD3D12.hpp").read_text(encoding="utf-8")
workflow = (root.parent / ".github/workflows/triview-b1.yml").read_text(encoding="utf-8")

checks = {
    "radial neutral fast path": "r2 > FocusLift.w && FocusLift.z*FocusProfile.y > 0.0" in shader,
    "local squared-distance rejection": "distanceSq < SeamLocal.x*SeamLocal.x" in shader,
    "sqrt guarded inside local band": shader.index("sqrt(distanceSq)") > shader.index("distanceSq < SeamLocal.x*SeamLocal.x"),
    "neutral nine records per eye": "if (lane < 9u) SeamOutput[eye * 9u + lane]" in shader,
    "uniform depth-invalid gate": "if (SeamOptions.w <= 0.5)" in shader,
    "no stale stats at zero strength": "(Seam.y > 0.0 || SeamOptions.z > 0.5)" in shader,
    "skip zero-strength dispatch": "(settings.seam_strength > 0.f || settings.seam_debug)" in backend,
    "no-analysis timer is neutral": "seam_gpu_ms_=timed_seam_active_ ?" in backend,
    "ID7 present in package text": "UEVR ID7 / TriView B39" in workflow,
    "B31 package artifact": "UEVR-TriView-B39-Ambient-" in workflow,
}
assert all(checks.values()), {k: v for k, v in checks.items() if not v}
tests = 0
for corner_gain in (1.0, 1.14799273, 1.5):
    for onset in (0.0, 0.46940367, 0.9):
        for exponent in (0.5, 0.92386647, 3.0):
            for brightness in (0.8, 1.0, 1.3):
                for strength in (0.0, 1.0, 2.0):
                    for i in range(101):
                        r2 = i / 100.0
                        t = max(0.0, min(1.0, (r2 - onset) / max(1.0 - onset, 0.1)))
                        original = brightness * (1.0 + (corner_gain - 1) * strength * t ** exponent)
                        optimized = brightness
                        if r2 > onset and (corner_gain - 1) * strength > 0.0:
                            optimized *= 1.0 + (corner_gain - 1) * strength * t ** exponent
                        assert math.isclose(original, optimized, abs_tol=1e-9), (original, optimized)
                        tests += 1
for radius in (16, 64, 120, 512):
    for x in range(0, 513, 7):
        for y in range(0, 513, 7):
            d2 = x*x + y*y
            assert (math.sqrt(d2) < radius) == (d2 < radius*radius)
            tests += 1

print(f"B31: {tests} pure-math radius/focus checks and all static shader/timing/package guards passed")

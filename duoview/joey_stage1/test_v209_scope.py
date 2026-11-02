#!/usr/bin/env python3
"""Capture the exact post-v208 source tree, then verify v209 adds only controls."""
import hashlib
import json
from pathlib import Path
import sys


def snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / "src").rglob("*")) if p.is_file()}


mode, backend, evidence = sys.argv[1:]
backend, evidence = Path(backend), Path(evidence)
if mode == "--capture":
    evidence.write_text(json.dumps(snapshot(backend), indent=2) + "\n")
elif mode == "--verify":
    old, new = json.loads(evidence.read_text()), snapshot(backend)
    changed = {p for p in old.keys() | new.keys() if old.get(p) != new.get(p)}
    allowed = {"src/mods/VR.hpp", "src/mods/VR.cpp",
               "src/mods/vr/DuoViewConfig.hpp", "src/mods/vr/DuoViewDistanceCurve.hpp"}
    assert changed == allowed, f"Unexpected v209 scope: {changed ^ allowed}"
    cfg = (backend / "src/mods/vr/DuoViewConfig.hpp").read_text(encoding="utf-8-sig")
    assert cfg.count("distance_sharpen_enabled") >= 2
    assert "valid_distance_sharpen_range(proposed.sharpen_near_m, proposed.sharpen_far_m)" in cfg
    ui = (backend / "src/mods/VR.cpp").read_text(encoding="utf-8-sig")
    assert "Depth is not yet connected" in ui
    print("PASS: exactly v209 controls and CPU reference changed; shader/GPU path unchanged")
else:
    raise SystemExit("Expected --capture or --verify")

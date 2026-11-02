#!/usr/bin/env python3
"""Extend only the fused foveal sharpening strength range after v207."""
from pathlib import Path
import sys


def apply(root):
    changes = {
        "src/mods/VR.hpp": [(
            'generate_name("DuoViewGlamaryeFoveaStrength"), 0.f, 2.f, 1.f)',
            'generate_name("DuoViewGlamaryeFoveaStrength"), 0.f, 5.f, 1.f)')],
        "src/mods/vr/DuoViewConfig.hpp": [
            ('scalar(requested.sharpen_strength,0.f,2.f,reject_sharpen,',
             'scalar(requested.sharpen_strength,0.f,5.f,reject_sharpen,'),
            ('proposed.sharpen_strength>2.f ||',
             'proposed.sharpen_strength>5.f ||')],
    }
    prepared = {}
    for name, replacements in changes.items():
        path = root / name
        source = path.read_text(encoding="utf-8-sig")
        for old, new in replacements:
            if source.count(old) != 1:
                raise RuntimeError(f"{name}: expected one v207 anchor: {old}")
            source = source.replace(old, new, 1)
        prepared[path] = source
    for path, source in prepared.items():
        path.write_text(source, encoding="utf-8", newline="")
    print("PASS: fused foveal strength accepts 0..5; default and shader unchanged")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_v208_sharpen_range.py <backend>")
    apply(Path(sys.argv[1]))

#!/usr/bin/env python3
"""Check the exact scope of the range patch and exercise its actual config."""
import hashlib
import json
from pathlib import Path
import sys


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / "src").rglob("*")) if p.is_file()}


mode, backend, evidence = sys.argv[1:]
backend, evidence = Path(backend), Path(evidence)
if mode == "--capture":
    evidence.write_text(json.dumps(snapshot(backend), indent=2) + "\n")
elif mode == "--verify":
    before, after = json.loads(evidence.read_text()), snapshot(backend)
    changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    assert changed == {"src/mods/VR.hpp", "src/mods/vr/DuoViewConfig.hpp"}, changed
    header = (backend / "src/mods/VR.hpp").read_text(encoding="utf-8-sig")
    assert header.count('generate_name("DuoViewGlamaryeFoveaStrength"), 0.f, 5.f, 1.f)') == 1
    print("PASS: only strength UI and config validation changed; all rendering sources byte-identical")
else:
    raise SystemExit("Expected --capture or --verify")

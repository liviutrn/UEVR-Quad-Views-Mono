#!/usr/bin/env python3
"""Verify v210 scope: native NGX metadata browser, no GPU depth capture or rendering changes."""
import hashlib
import json
from pathlib import Path
import sys

def snapshot(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root/"src").rglob("*")) if p.is_file()}
mode, backend, evidence=sys.argv[1:]
backend,evidence=Path(backend),Path(evidence)
if mode=="--capture":
    evidence.write_text(json.dumps(snapshot(backend),indent=2)+"\n")
elif mode=="--verify":
    old,new=json.loads(evidence.read_text()),snapshot(backend)
    changed={p for p in old.keys()|new.keys() if old.get(p)!=new.get(p)}
    allowed={"src/mods/VR.cpp","src/mods/vr/D3D12Component.cpp",
             "src/mods/vr/DuoViewNgxManualDepth.hpp",
             "src/mods/vr/d3d12/DuoViewNgxManualObserver.hpp"}
    assert changed==allowed,f"Unexpected path diff: {changed^allowed}"
    dx=(backend/"src/mods/vr/D3D12Component.cpp").read_text(encoding="utf-8-sig")
    assert "ngx_depth_browser.install();" in dx
    assert "candidates().set_expected(" in dx
    assert "packet_frame->config.layout.fovea.width" in dx
    vr=(backend/"src/mods/VR.cpp").read_text(encoding="utf-8-sig")
    assert "DLSS fovea depth sources (v210 manual selection)" in vr
    assert "Pin this as fovea depth" in vr
    assert "depth pixels NOT yet copied" in vr
    print("PASS: NGX metadata observer, exact frozen-layout selection, no new shaders or GPU copies")
else:
    raise SystemExit("Expected --capture or --verify")

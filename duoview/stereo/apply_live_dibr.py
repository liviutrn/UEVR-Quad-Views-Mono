#!/usr/bin/env python3
"""After S0: replace its frozen SceneDepthZ acquisition with opt-in live DIBR.

Specific game-evidence profile only: Build118 R32_TYPELESS 860x684 and 344x276.
Fail closed when no matching hardware-depth barriers or mono mode selected.
"""
from pathlib import Path
import argparse

def edit(root, name, old, new):
    p=root/name
    s=p.read_text(encoding="utf-8-sig")
    n=s.count(old)
    if n!=1:
        raise RuntimeError(f"Live DIBR source drift in {name}: {n} hits for {old[:100]!r}")
    p.write_text(s.replace(old,new,1),encoding="utf-8",newline="\n")

def apply(backend, workspace):
    hdr=workspace/"duoview/stereo/LiveDIBRDepthPair.hpp"
    if not hdr.exists():raise RuntimeError("Missing Live DIBR owned-depth implementation")
    target=backend/"src/mods/vr/DuoDepthPairP1.hpp"
    if "class DepthPairP1" not in target.read_text(encoding="utf-8-sig"):
        raise RuntimeError("Expected P1 integrated observer missing")
    target.write_text(hdr.read_text(encoding="utf-8"),encoding="utf-8",newline="\n")
    edit(backend,"src/mods/VR.cpp",
        'Capture TWO owned P1 depth snapshots (one shot)',
        'Start LIVE DIBR depth capture (Build118 geometry)')
    edit(backend,"src/mods/VR.cpp",
        'P1 depth GPU copies: %u / 2, GPU queue complete: %s',
        'Live DIBR depth: %u / 2, GPU queue complete: %s')
    edit(backend,"src/mods/VR.cpp",
        'S0 two-eye stereo WARP TEST (unverified Z, OFF recommended)',
        'Experimental LIVE DIBR stereo (two-eye, turn OFF if uncomfortable)')
    edit(backend,"src/mods/VR.cpp",
        'S0 test strength: 0..40% (8% initial)',
        'DIBR disparity 0..40% (8% initial)')
    edit(backend,"src/mods/VR.cpp",
        'S0 two-eye stereo WARP TEST',
        'Live DIBR two-eye stereo WARP TEST') if False else None
    # Deliberately retain the original OFF-path, the stage5 packet and XR output.
    # The live observer owns only two prewarmed depth copies sampled at the
    # existing stereo PSO. No extra Unreal scene or secondary shading pass.
    capture=target.read_text(encoding="utf-8")
    assert "desc.Width==860" in capture and "desc.Width==344" in capture
    assert "D3D12_RESOURCE_STATE_DEPTH_WRITE" in capture
    assert "D3D12_RESOURCE_STATE_COPY_SOURCE" in capture
    assert "CopyTextureRegion" in capture
    print("Build118 live DIBR profile patched; shader from workspace; stereo opt-in.")
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("backend",type=Path)
    ap.add_argument("workspace",type=Path)
    args=ap.parse_args()
    apply(args.backend,args.workspace)

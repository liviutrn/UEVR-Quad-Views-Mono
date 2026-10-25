#!/usr/bin/env python3
"""Fail-closed source identity verification for Build118 frozen stock-DIBR test."""
import argparse,hashlib,json
from pathlib import Path
FILES=[
"src/mods/VR.cpp",
"src/mods/vr/D3D12Component.cpp",
"src/mods/vr/D3D12Component.hpp",
"src/mods/vr/DepthProofSession.hpp",
"src/mods/vr/d3d12/DIBRPreview.cpp",
"src/mods/vr/d3d12/DIBRPreview.hpp",
]
REQUIRED={
"src/mods/VR.cpp": ["STOP stock DIBR test / MONO", "Test Joey DIBR", "Depth proof to disk (experimental)"],
"src/mods/vr/D3D12Component.cpp": ["stock_dibr_proof_slots", "completed_gpu_snapshot", "slot->synthesize(", "CopyResource(destination,stereo)", "D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE"],
"src/mods/vr/D3D12Component.hpp": ["m_stock_dibr_proof_candidate", "stock_dibr_proof_depth_ready", "stock_dibr_proof_slots"],
"src/mods/vr/DepthProofSession.hpp": ["gpu_snapshot", "CopyTextureRegion(&gpu", "completed_gpu_snapshot"],
"src/mods/vr/d3d12/DIBRPreview.cpp": ["allow_proof_scaling", "parameters.allow_depth_resolution_mismatch_for_proof"],
"src/mods/vr/d3d12/DIBRPreview.hpp": ["allow_depth_resolution_mismatch_for_proof{false}"],
}
def main():
    p=argparse.ArgumentParser();p.add_argument("backend",type=Path)
    x=p.add_mutually_exclusive_group(required=True)
    x.add_argument("--record",type=Path);x.add_argument("--compare",type=Path)
    args=p.parse_args()
    fingerprints={}
    for file in FILES:
        path=args.backend/file
        data=path.read_bytes()
        source=data.decode("utf-8-sig")
        for needle in REQUIRED[file]:
            assert needle in source,(file,needle)
        fingerprints[file]=hashlib.sha256(data).hexdigest()
    if args.record:
        args.record.write_text(json.dumps(fingerprints,indent=2,sort_keys=True),encoding="utf8")
        print("PASS: exact Build118 stock DIBR bridge source frozen")
    else:
        assert json.loads(args.compare.read_text(encoding="utf8"))==fingerprints,"bridge source drift during build"
        print("PASS: unchanged Build118 stock DIBR bridge source after backend/frontend build")
if __name__=="__main__":main()

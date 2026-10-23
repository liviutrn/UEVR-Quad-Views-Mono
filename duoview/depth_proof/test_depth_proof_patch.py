#!/usr/bin/env python3
"""Check integration boundaries; GPU correctness is tested separately on WARP."""
from pathlib import Path
import argparse
import hashlib
import json

def main(root, record=None, compare=None):
    files=['DuoViewD3D12.hpp','DuoViewGeometry.hpp','DuoViewState.hpp','DuoViewMonoCopyD3D12.hpp']
    paths=['src/mods/vr/'+f for f in files]+['src/mods/vr/runtimes/OpenXR.cpp','src/mods/vr/FFakeStereoRenderingHook.cpp']
    hashes={f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in paths}
    if record: record.write_text(json.dumps(hashes,indent=2)+'\n')
    if compare:
        assert hashes==json.loads(compare.read_text()),'Depth proof modified protected renderer/pose/producer source'
    if record: return
    cpp=(root/'src/mods/vr/D3D12Component.cpp').read_text(encoding='utf-8-sig')
    hook=(root/'src/hooks/D3D12Hook.cpp').read_text(encoding='utf-8-sig')
    ui=(root/'src/mods/VR.cpp').read_text(encoding='utf-8-sig')
    assert 'm_depth_proof->session.observing()' in cpp
    assert 'Capture depth proof (10 seconds, once per game)' in ui
    assert hook.count('void WINAPI D3D12Hook::depth_proof_execute(')==1
    execute=hook[hook.index('void WINAPI D3D12Hook::depth_proof_execute('):]
    assert execute.index('observer->on_command_lists_submitting(queue,n,lists)')<execute.index('original(queue,n,lists)')<execute.index('observer->on_command_lists_submitted(queue,n,lists)')
    assert 'DuoDepthPairP1' not in cpp and 'p1_debug' not in cpp and 'stereo_preview_strength' not in cpp
    for name in ('DepthProofSession.hpp','DepthProofObserver.hpp'):
        assert (root/'src/mods/vr'/name).read_bytes()==(Path(__file__).parent/name).read_bytes()
    print('Depth proof exact-anchor integration and protected renderer hashes PASS (not live depth proof)')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('backend',type=Path);p.add_argument('--record',type=Path);p.add_argument('--compare',type=Path)
    a=p.parse_args();main(a.backend,a.record,a.compare)

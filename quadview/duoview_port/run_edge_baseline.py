#!/usr/bin/env python3
"""Execute baseline RGB and separate test-only readbacks in clean directories."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rgb-exe',type=Path,required=True)
    ap.add_argument('--probe-exe',type=Path,required=True)
    ap.add_argument('--corpus',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    if a.out.exists():
        raise RuntimeError('Baseline output must be new and empty')
    a.out.mkdir(parents=True)
    base=os.environ.copy()
    base.update(DUOVIEW_RECON_V3='1',DUOVIEW_RECON_V3_DIR=str(a.corpus.resolve()))
    for profile in ('P0','P1','P2'):
        for probe in ('rgb','uv','depth','constants'):
            dest=a.out/profile/probe;dest.mkdir(parents=True)
            env=base|{'DUOVIEW_EDGE_PROFILE':profile,'DUOVIEW_EDGE_PROBE':probe}
            exe=a.rgb_exe if probe=='rgb' else a.probe_exe
            with (dest/'execution.log').open('w',encoding='utf-8') as log:
                subprocess.run([str(exe.resolve())],cwd=dest,env=env,stdout=log,stderr=subprocess.STDOUT,
                               timeout=1200,check=True)
            files=list(dest.glob('recon_v3_*.bgra'))
            if len(files)!=40 or any(p.stat().st_size!=663552 for p in files):
                raise RuntimeError('Missing/invalid baseline readbacks')
            print('BASELINE_CAPTURE',profile,probe,len(files),flush=True)
    sys.path.insert(0,str(Path(__file__).parent/'recon_v3_lab'))
    from edge_baseline_score import evaluate
    evaluate(a.corpus,a.out,a.out/'scores')
    print('BASELINE_FREEZE_PASS: 480 captures, 120 per-eye RGB rows, 90 per-eye transitions',flush=True)

if __name__=='__main__':
    main()

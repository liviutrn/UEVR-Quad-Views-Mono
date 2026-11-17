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
    from edge_math import PROFILES
    sweep_profiles={name:PROFILES.pop(name) for name in tuple(PROFILES) if name.startswith('S')}
    try:
        evaluate(a.corpus,a.out,a.out/'scores')
    finally:
        PROFILES.update(sweep_profiles)
    print('BASELINE_FREEZE_PASS: 480 captures, 120 per-eye RGB rows, 90 per-eye transitions',flush=True)

    for profile in (f'S{i}' for i in range(1,9)):
        for probe in ('rgb','uv','constants'):
            dest=a.out/'sweep'/profile/probe;dest.mkdir(parents=True)
            env=base|{'DUOVIEW_EDGE_PROFILE':profile,'DUOVIEW_EDGE_PROBE':probe}
            exe=a.rgb_exe if probe=='rgb' else a.probe_exe
            with (dest/'execution.log').open('w',encoding='utf-8') as log:
                subprocess.run([str(exe.resolve())],cwd=dest,env=env,stdout=log,stderr=subprocess.STDOUT,
                               timeout=1200,check=True)
            files=list(dest.glob('recon_v3_*.bgra'))
            if len(files)!=40 or any(p.stat().st_size!=663552 for p in files):
                raise RuntimeError('Missing/invalid sweep readbacks: '+profile+'/'+probe)
            print('SWEEP_CAPTURE',profile,probe,len(files),flush=True)

    comparer=Path(__file__).parent/'recon_v3_lab'/'sweep_compare.py'
    subprocess.run([sys.executable,str(comparer),'--corpus',str(a.corpus.resolve()),
                    '--sweep',str((a.out/'sweep').resolve()),
                    '--baseline',str((a.out/'scores'/'P1.json').resolve()),
                    '--summary-json',str((a.out/'sweep_summary.json').resolve()),
                    '--summary-md',str((a.out/'sweep_summary.md').resolve())],
                   check=True)
    print('SWEEP_PASS: 8 profiles, 24 probe batches, 960 captures',flush=True)

    # Edge toggle K3D10TS16 / K23D10TS16: RGB only (the readback probe replaces only the Off raster).
    for profile in ('K3','K23'):
        dest=a.out/'edge_toggle'/profile/'rgb';dest.mkdir(parents=True)
        env=base|{'DUOVIEW_EDGE_PROFILE':profile,'DUOVIEW_EDGE_PROBE':'rgb'}
        with (dest/'execution.log').open('w',encoding='utf-8') as log:
            subprocess.run([str(a.rgb_exe.resolve())],cwd=dest,env=env,stdout=log,stderr=subprocess.STDOUT,
                           timeout=1200,check=True)
        files=list(dest.glob('recon_v3_*.bgra'))
        if len(files)!=40 or any(p.stat().st_size!=663552 for p in files):
            raise RuntimeError('Missing/invalid edge toggle captures: '+profile)
        print('EDGE_TOGGLE_CAPTURE',profile,len(files),flush=True)
    toggle=Path(__file__).parent/'recon_v3_lab'/'edge_toggle_compare.py'
    # Informational only: a comparison failure must not mask the Off/P-profile results above.
    cmp=subprocess.run([sys.executable,str(toggle),'--corpus',str(a.corpus.resolve()),
                        '--p1',str((a.out/'P1'/'rgb').resolve()),'--toggle',str((a.out/'edge_toggle').resolve()),
                        '--out',str((a.out/'edge_toggle_summary.json').resolve())])
    print('EDGE_TOGGLE_PASS: K3/K23 captured (40 each); comparison exit',cmp.returncode,flush=True)

if __name__=='__main__':
    main()

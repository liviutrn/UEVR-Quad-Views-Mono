#!/usr/bin/env python3
"""Fail closed on V3 corpus drift. Offline evaluator owns reference-only assets."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

EXPECTED_SCENES = (
    'weapon_object_motion', 'layers_object_motion',
    'foliage_stationary_false49', 'foliage_physical_sway',
    'natural_physical_sway',
)
INPUT_NAMES=('source_full.bgra','source_fovea.bgra','raw_coarse.f32','raw_fine.f32')
GT_NAMES=('gt_left.bgra','gt_left_ids.u8','gt_right.bgra','gt_right_ids.u8')


def sha(p:Path)->str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def assert_projection(lab) -> float:
    """Compare HLSL normalized affine-row packing to original V3 Hcoords."""
    yy,xx=np.mgrid[0:216:7,0:384:9].astype(np.float32)
    mx=0.0
    for pan in (False,True):
      for eye in ('left','right'):
        e=1. if eye=='left' else -1.
        scale=(1.035 if e>0 else 1.024) if pan else 1.
        shift=2.6 if pan else 0.
        skew=.012 if pan else 0.
        h01=e*skew*216./384.
        h02=.5*(1.-scale)+(e*shift-e*skew*(216.+1.)*.5)/384.
        h12=e*.31/216. if pan else 0.
        u=(xx+.5)/384.;v=(yy+.5)/216.
        px=(scale*u+h01*v+h02)*384.-.5
        py=(v+h12)*216.-.5
        tx,ty=lab.Hcoords(xx,yy,eye,pan)
        mx=max(mx,float(np.max(np.abs(px-tx))),float(np.max(np.abs(py-ty))))
    if mx>=1e-4:
        raise RuntimeError(f'V3 H GPU row mapping differs from the original reference: {mx:.6f}px')
    return mx


def verify(root:Path, expected:Path, lab_module=None)->dict:
    golden=json.loads(expected.read_text())
    root=root.resolve()
    manifest=root/'manifest.json'
    # Windows text-mode write_text emits CRLF; canonical V3 JSON used LF.
    # Normalize only manifest line endings, not any of the 160 binary files.
    canonical=manifest.read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(canonical).hexdigest()!=golden['manifest_sha256']:
        raise RuntimeError('V3 manifest does not match the frozen original corpus')
    meta=json.loads(manifest.read_text())
    if (meta['width'],meta['height'],meta['seed'])!=(384,216,261115):
        raise RuntimeError('V3 dimensions or seed changed')
    scenes=meta['scenes']
    if tuple(x['files_dir'] for x in scenes)!=EXPECTED_SCENES:
        raise RuntimeError('V3 scene ordering/name changed')
    assert len(scenes)==golden['scene_count']==5
    count=0;files=0
    for scene in scenes:
        assert len(scene['frames'])==4
        for f in scene['frames']:
            count+=1
            assert f['frame'] in range(4)
            assert tuple(f['inputs'])==INPUT_NAMES
            assert tuple(f['reference_only'])==GT_NAMES
            for category in ('inputs','reference_only'):
                for name,record in f[category].items():
                    file=root/scene['files_dir']/record['name']
                    if not file.is_file():raise RuntimeError(f'V3 missing {file}')
                    if file.stat().st_size!=record['bytes'] or sha(file)!=record['sha256']:
                        raise RuntimeError(f'V3 corrupted/drifted data: {file}')
                    files+=1
                    if name in ('raw_coarse.f32','raw_fine.f32'):
                        z=np.fromfile(file,dtype='<f4')
                        if z.size!=384*216 or not np.all(np.isfinite(z)) or np.min(z)<0 or np.max(z)>1.15:
                            raise RuntimeError(f'bad inverse depth: {file}')
    if (count,files)!=(golden['frame_count'],golden['files_count']):
        raise RuntimeError(f'V3 unexpected {count=} {files=}')
    result={'pass':True,'frames':count,'files':files,
            'manifest_sha256':hashlib.sha256(canonical).hexdigest(),
            'manifest_raw_sha256':sha(manifest),
            'manifest_crlf_normalized':canonical!=manifest.read_bytes(),
            'scenes':list(EXPECTED_SCENES),'reference_only_not_bound_to_gpu':True}
    if lab_module is not None:result['homography_max_error_px']=assert_projection(lab_module)
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--corpus',type=Path,required=True)
    ap.add_argument('--expected',type=Path,required=True)
    ap.add_argument('--check-projection',action='store_true')
    a=ap.parse_args()
    lab=None
    if a.check_projection:
        import sys
        sys.path.insert(0,str(Path(__file__).parent/'DuoView_Stereo_Simulation_Lab_V3_20261115'))
        import stereo_lab as lab
    result=verify(a.corpus,a.expected,lab)
    print('RECON_V3_VERIFY '+json.dumps(result,sort_keys=True))


if __name__=='__main__':main()

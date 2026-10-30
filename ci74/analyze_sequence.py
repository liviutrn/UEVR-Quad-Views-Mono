#!/usr/bin/env python3
"""Report measured stationary-scene output/source temporal changes from CI74 ZIP.
Not a stereo-depth accuracy test; no native eye ground truth is assumed.
"""
import argparse
import io
import json
import re
import statistics
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

ROLES = ('xr_left', 'xr_right', 'source_left', 'source_right')

def gray(image):
    a = np.asarray(image.convert('RGB'), dtype=np.float32) / 255.0
    return a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

def edges(a):
    dy, dx = np.gradient(a)
    return np.sqrt(dx * dx + dy * dy)

def frame_metric(a, b):
    if a.shape != b.shape:
        raise ValueError('Frame dimensions changed during recording')
    # A simple reproducible unregistered metric. Stationarity is verified
    # separately from pose telemetry; global image motion is NOT removed.
    edge = (edges(a) + edges(b)) * 0.5
    threshold = float(np.percentile(edge, 78))
    mask = edge >= max(0.02, threshold)
    if mask.sum() < 100:
        return {'edge_change_mean': None, 'edge_change_p95': None,
                'edge_fraction': float(mask.mean()), 'reason': 'insufficient_edges'}
    diff = np.abs(a-b)[mask]
    return {'edge_change_mean': float(np.mean(diff)),
            'edge_change_p95': float(np.percentile(diff,95)),
            'edge_fraction': float(mask.mean())}

def parse_position(metadata, eye):
    m = re.search(r'eye'+str(eye)+r'Position=([0-9.,eE+\-]+)', metadata)
    if not m:
        return None
    try:
        parts = [float(v) for v in m.group(1).strip(',').split(',')[:3]]
        return parts if len(parts)==3 else None
    except ValueError:
        return None

def analyze(path):
    with zipfile.ZipFile(path) as z:
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['schema']=='duoview-sequence-1', 'Not a CI74 sequence'
        frames=manifest.get('frames', [])
        if len(frames)<2: raise ValueError('At least two frames are required')
        result={'schema':'duoview-sequence-analysis-1', 'input':Path(path).name,
                'encoded_frames':len(frames), 'recorded_frames':manifest.get('frames_recorded'),
                'truncated_by_size':manifest.get('truncated_by_size'),
                'depth_provenance_authenticated':False,
                'claim':'Stationary-output temporal image instability, not stereoscopic ground-truth accuracy',
                'roles':{}}
        times=[f['time_ms'] for f in frames]
        gaps=[times[k]-times[k-1] for k in range(1,len(times))]
        result['timing']={'duration_ms':times[-1]-times[0],
                          'median_frame_interval_ms':statistics.median(gaps),
                          'max_frame_interval_ms':max(gaps),
                          'nonmonotonic_intervals':sum(d<=0 for d in gaps)}
        poses=[parse_position(f.get('metadata',''),0) for f in frames]
        if all(p is not None for p in poses):
            first=np.asarray(poses[0]); deviations=np.linalg.norm(np.asarray(poses)-first,axis=1)
            result['pose']={'max_left_camera_position_delta_ue_units':float(deviations.max()),
                            'stationary_camera_position_threshold_ue_units':0.5,
                            'position_stationary':bool(deviations.max()<0.5),
                            'note':'Position only; rotation, gaze, motion vectors and scene motion must also be considered'}
        for role in ROLES:
            previous=None; stats=[];heat=None;count=0
            for f in frames:
                fn=f'frames/f{f["index"]}_{role}.jpg'
                arr=gray(Image.open(io.BytesIO(z.read(fn))))
                if previous is not None:
                    stats.append(frame_metric(previous,arr))
                    d=np.abs(previous-arr)
                    heat=d if heat is None else heat+d
                    count+=1
                previous=arr
            valid=[s for s in stats if s.get('edge_change_mean') is not None]
            result['roles'][role]={
                'shape':list(previous.shape),
                'compared_frame_pairs':len(stats),
                'edge_change_mean_median':float(statistics.median(s['edge_change_mean'] for s in valid)) if valid else None,
                'edge_change_p95_median':float(statistics.median(s['edge_change_p95'] for s in valid)) if valid else None,
                'per_pair':stats,
                'heatmap_luminance_difference':(np.clip(heat/max(count,1)*5.0,0,1)*255).astype('uint8') if heat is not None else None}
        # Not a physical A/B: the source crops have different resolutions and
        # foveation; use as evidence only, never as an accuracy score.
        return result

def save_report(data,path):
    out=Path(path);out.parent.mkdir(parents=True,exist_ok=True)
    for role,entry in data['roles'].items():
        heat=entry.pop('heatmap_luminance_difference',None)
        if heat is not None:
            Image.fromarray(heat, mode='L').save(out.with_name(out.stem+'_'+role+'_temporal_heat.png'))
    out.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8')
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('sequence_zip');p.add_argument('--out',default='duoview_sequence_report.json')
    args=p.parse_args();data=analyze(args.sequence_zip);save_report(data,args.out)
    print('Frames:',data['encoded_frames'],'median interval(ms):',data['timing']['median_frame_interval_ms'])
    for role,s in data['roles'].items(): print(role,'median edge change:',s['edge_change_mean_median'])
    print('Wrote',args.out)

if __name__=='__main__':main()

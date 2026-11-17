#!/usr/bin/env python3
"""Edge toggle K3/K23 vs P1 on the frozen V3 WARP corpus: RGB-only, informational, NO gates.

Evidence level: CI WARP on a synthetic corpus WITHOUT DLSS jitter and without a 0.4 m weapon
(nearest depth ~1 m), so it can show that K runs, is finite and what it changes; it cannot show
real headset quality. Reuses the frozen scorer's GT, masks (P1 geometry) and temporal helper.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
import sweep_compare as sc  # noqa: E402

REGIONS = ('valid', 'near_edge', 'halo', 'hole_id0', 'hole_id1')
TEMPORAL = ('edge', 'halo', 'valid')


def load(frozen, folder, name, frame):
    return frozen.old.rgb(folder / f'recon_v3_{name}_f{frame}.bgra', True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--corpus', type=Path, required=True)
    ap.add_argument('--p1', type=Path, required=True)
    ap.add_argument('--toggle', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    frozen = sc._load_frozen(); np = sc.np
    p1 = sc.PROFILES['P1']
    manifest = json.loads((a.corpus / 'manifest.json').read_text())
    arms = {'P1': a.p1, 'K3': a.toggle / 'K3' / 'rgb', 'K23': a.toggle / 'K23' / 'rgb'}
    err = {arm: {} for arm in arms}
    stored = {arm: {} for arm in arms}
    changed = {arm: [0, 0] for arm in arms}
    for record in manifest['scenes']:
        name, scene, pan = record['files_dir'], record['scene'], record['pan_mode']
        texture = frozen.old.s.texture_layers(scene)
        for frame in range(4):
            _, _, center_ids, _ = frozen.old.s.render(
                texture, 'center', frame, scene, False,
                cam_move=record['camera_moves'], physical_move=record['foreground_moves'])
            images = {arm: load(frozen, folder, name, frame) for arm, folder in arms.items()}
            for arm, img in images.items():
                if not np.isfinite(img.astype(np.float64)).all():
                    raise RuntimeError(f'{arm}: nonfinite capture')
                diff = np.abs(img.astype(np.int16) - images['P1'].astype(np.int16)).max(axis=2)
                changed[arm][0] += int((diff > 0).sum()); changed[arm][1] += int(diff.size)
            for eye_index, eye in enumerate(sc.EYES):
                gt = frozen.old.rgb(a.corpus / name / f'{frame:02}_gt_{eye}.bgra')
                ids = np.fromfile(a.corpus / name / f'{frame:02}_gt_{eye}_ids.u8', np.uint8).reshape(frozen.H, frozen.W)
                masks, _ = frozen.geometric_masks(ids, center_ids, eye, pan, p1)
                for arm, img in images.items():
                    out = img[:, eye_index * frozen.W:(eye_index + 1) * frozen.W]
                    e = np.abs(out.astype(np.int16) - gt.astype(np.int16)).mean(axis=2)
                    for region in REGIONS:
                        err[arm].setdefault((name, region), []).append(e[masks[region]])
                    stored[arm][name, eye, frame] = (out, gt, masks)
    summary = {'evidence': 'CI WARP, frozen V3 corpus (no jitter, no 0.4 m weapon); informational, no gates',
               'pixels_changed_vs_P1': {arm: {'changed': c, 'total': t, 'fraction': c / t} for arm, (c, t) in changed.items()},
               'spatial_mae': {}, 'temporal': {}}
    for arm in arms:
        rows = {}
        for (name, region), parts in err[arm].items():
            v = np.concatenate(parts) if parts else np.empty(0)
            rows.setdefault(name, {})[region] = {'mae': float(v.mean()) if v.size else None, 'pixels': int(v.size)}
        summary['spatial_mae'][arm] = rows
        trows = {}
        for name in frozen.old.EXPECTED_SCENES:
            for region in TEMPORAL:
                vals = []
                for eye in sc.EYES:
                    for frame in range(3):
                        oa, ga, ma = stored[arm][name, eye, frame]
                        ob, gb, mb = stored[arm][name, eye, frame + 1]
                        vals.append(frozen.temporal(oa, ob, ga, gb, ma[region] | mb[region]))
                trows.setdefault(name, {})[region] = vals
        summary['temporal'][arm] = trows
    a.out.write_text(json.dumps(summary, indent=2, default=float), encoding='utf-8')
    for arm in ('K3', 'K23'):
        print('EDGE_TOGGLE', arm, 'changed fraction vs P1 %.4f' % summary['pixels_changed_vs_P1'][arm]['fraction'])
        for name in frozen.old.EXPECTED_SCENES:
            r, b = summary['spatial_mae'][arm][name], summary['spatial_mae']['P1'][name]
            print('  ', name, ' '.join('%s %.2f->%.2f' % (k, b[k]['mae'] or 0, r[k]['mae'] or 0) for k in REGIONS))


if __name__ == '__main__':
    main()

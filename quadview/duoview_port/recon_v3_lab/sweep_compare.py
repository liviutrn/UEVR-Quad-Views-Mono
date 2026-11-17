#!/usr/bin/env python3
"""Score S1-S8 captures with frozen #357 scorer helpers; never alter scorer."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from edge_math import PROFILES

frozen = cv2 = np = None


def _load_frozen():
    """Load heavyweight frozen evaluator dependencies only for actual scoring."""
    global frozen, cv2, np
    if frozen is None:
        import cv2 as cv2_module
        import numpy as np_module
        import edge_baseline_score as scorer
        cv2, np, frozen = cv2_module, np_module, scorer
    return frozen

SCENES = (
    'weapon_object_motion',
    'layers_object_motion',
    'foliage_stationary_false49',
    'foliage_physical_sway',
    'natural_physical_sway',
)
EYES = ('left', 'right')
TEMPORAL_REGIONS = ('edge', 'halo', 'valid', 'fovea_core', 'periphery_outer', 'blend')
TARGET_SCENES = ('weapon_object_motion', 'layers_object_motion')
S8_M4_OFF_COLUMNS = (9, 10, 12)  # M4Grid.x, M4Flags.x, M4Flags.y


def _scene_eye_index(result):
    rows = result.get('scene_eye')
    if not isinstance(rows, list):
        raise RuntimeError('Scorer output is missing scene_eye rows')
    indexed = {(row['scene'], row['eye']): row for row in rows}
    expected = {(scene, eye) for scene in SCENES for eye in EYES}
    if len(indexed) != len(rows) or set(indexed) != expected:
        raise RuntimeError('Scorer scene/eye coverage is incomplete or duplicated')
    return indexed


def _transition_index(result):
    rows = result.get('transitions')
    if not isinstance(rows, list):
        raise RuntimeError('Scorer output is missing temporal transition rows')
    indexed = {}
    for row in rows:
        key = (row['scene'], row['eye'], row['from_frame'], row['to_frame'])
        if key in indexed:
            raise RuntimeError('Duplicate temporal transition row')
        indexed[key] = row
    expected = {(scene, eye, frame, frame + 1)
                for scene in SCENES for eye in EYES for frame in range(3)}
    if set(indexed) != expected:
        raise RuntimeError('Scorer matched-transition coverage is incomplete')
    return indexed


def classify_profile(candidate, baseline, paired_delta_fn):
    """Apply preregistered gates; temporal deltas come from the frozen scorer."""
    cand_se = _scene_eye_index(candidate)
    base_se = _scene_eye_index(baseline)
    cand_tr = _transition_index(candidate)
    base_tr = _transition_index(baseline)

    halo_tests = []
    halo_gain = True
    halo_worse = False
    for scene in TARGET_SCENES:
        for eye in EYES:
            key = (scene, eye)
            cm = cand_se[key]['regions']['halo']
            bm = base_se[key]['regions']['halo']
            if not cm['count'] or not bm['count'] or cm['mae_rgb8'] is None or bm['mae_rgb8'] is None:
                raise RuntimeError('Required target halo is empty; classification is invalid')
            improve = bm['mae_rgb8'] - cm['mae_rgb8']
            gain_limit = max(.5, .05 * bm['mae_rgb8'])
            worsen = cm['mae_rgb8'] - bm['mae_rgb8']
            worse_limit = max(.5, .05 * bm['mae_rgb8'])
            passes_gain = improve >= gain_limit
            is_worse = worsen >= worse_limit
            halo_gain &= passes_gain
            halo_worse |= is_worse
            halo_tests.append({
                'scene': scene, 'eye': eye,
                'baseline_mae_rgb8': bm['mae_rgb8'],
                'candidate_mae_rgb8': cm['mae_rgb8'],
                'improvement_rgb8': improve,
                'gain_limit_rgb8': gain_limit,
                'gain_pass': passes_gain,
                'worsening_rgb8': worsen,
                'worse_limit_rgb8': worse_limit,
                'worse': is_worse,
            })

    spatial_failures = []
    spatial_tests = []
    hole_failures = []
    iou_failures = []
    iou_tests = []
    for key in sorted(base_se):
        c_row, b_row = cand_se[key], base_se[key]
        for region in ('valid', 'hole_id0', 'hole_id1'):
            cm = c_row['regions'][region]
            bm = b_row['regions'][region]
            measured = bool(cm['count'] and bm['count'] and
                            cm['mae_rgb8'] is not None and bm['mae_rgb8'] is not None and
                            cm['p99_rgb8'] is not None and bm['p99_rgb8'] is not None)
            test = {
                'scene': key[0], 'eye': key[1], 'region': region,
                'candidate_count': cm['count'], 'baseline_count': bm['count'],
                'candidate_mae_rgb8': cm['mae_rgb8'], 'baseline_mae_rgb8': bm['mae_rgb8'],
                'candidate_p99_rgb8': cm['p99_rgb8'], 'baseline_p99_rgb8': bm['p99_rgb8'],
                'mae_delta_rgb8': None, 'mae_limit_rgb8': None,
                'p99_delta_rgb8': None, 'p99_limit_rgb8': 1.,
                'pass': False,
            }
            if measured:
                test['mae_delta_rgb8'] = cm['mae_rgb8'] - bm['mae_rgb8']
                test['mae_limit_rgb8'] = max(.5, .02 * bm['mae_rgb8'])
                test['p99_delta_rgb8'] = cm['p99_rgb8'] - bm['p99_rgb8']
                test['pass'] = (test['mae_delta_rgb8'] <= test['mae_limit_rgb8'] and
                                test['p99_delta_rgb8'] <= test['p99_limit_rgb8'])
            spatial_tests.append(test)
            if not test['pass']:
                item = {'scene': key[0], 'eye': key[1], 'region': region,
                        'reason': 'MAE_OR_P99_LIMIT' if measured else 'EMPTY_NOT_PASS'}
                spatial_failures.append(item)
                if region.startswith('hole_'):
                    hole_failures.append(item)
        c_iou = c_row['foreground']['valid']
        b_iou = b_row['foreground']['valid']
        measured_iou = bool(c_iou['union'] and b_iou['union'] and
                            c_iou['iou'] is not None and b_iou['iou'] is not None)
        iou_test = {
            'scene': key[0], 'eye': key[1],
            'baseline_iou': b_iou['iou'], 'candidate_iou': c_iou['iou'],
            'iou_drop': b_iou['iou'] - c_iou['iou'] if measured_iou else None,
            'max_drop': .005, 'pass': bool(measured_iou and b_iou['iou'] - c_iou['iou'] <= .005),
        }
        iou_tests.append(iou_test)
        if not iou_test['pass']:
            iou_failures.append(iou_test)

    temporal_failures = []
    temporal_tests = []
    for key in sorted(base_tr):
        c_regions = cand_tr[key]['regions']
        b_regions = base_tr[key]['regions']
        for region in TEMPORAL_REGIONS:
            cand_value, base_value = c_regions[region], b_regions[region]
            delta = paired_delta_fn(cand_value, base_value)
            test = {
                'scene': key[0], 'eye': key[1],
                'from_frame': key[2], 'to_frame': key[3], 'region': region,
                'candidate_count': cand_value['count'], 'baseline_count': base_value['count'],
                'candidate_normalized': cand_value['normalized'],
                'baseline_normalized': base_value['normalized'],
                **delta,
            }
            temporal_tests.append(test)
            if delta['status'] != 'MEASURED' or delta['regression']:
                temporal_failures.append(test)

    foliage_temporal_failures = [row for row in temporal_failures
                                 if row['scene'] in SCENES[2:]]
    no_harm = not spatial_failures and not iou_failures
    no_temporal_regression = not temporal_failures
    if halo_gain and no_temporal_regression and no_harm:
        classification = 'BETTER'
    elif halo_gain and (foliage_temporal_failures or hole_failures):
        classification = 'TRADE'
    elif halo_worse or (not halo_gain and not no_harm):
        classification = 'WORSE'
    else:
        classification = 'NEUTRAL'
    return {
        'classification': classification,
        'halo_gain_all_target_scene_eyes': bool(halo_gain),
        'halo_worse_any_target_scene_eye': bool(halo_worse),
        'halo_tests': halo_tests,
        'no_temporal_regression': no_temporal_regression,
        'temporal_failure_count': len(temporal_failures),
        'temporal_failures': temporal_failures,
        'foliage_natural_temporal_failure_count': len(foliage_temporal_failures),
        'spatial_safety_failure_count': len(spatial_failures),
        'spatial_safety_failures': spatial_failures,
        'spatial_safety_tests': spatial_tests,
        'hole_failure_count': len(hole_failures),
        'hole_failures': hole_failures,
        'foreground_iou_failure_count': len(iou_failures),
        'foreground_iou_failures': iou_failures,
        'foreground_iou_tests': iou_tests,
        'temporal_tests': temporal_tests,
    }

def compare_spatial_vs_p1(candidate, baseline):
    candidate_rows = _scene_eye_index(candidate)
    baseline_rows = _scene_eye_index(baseline)
    comparisons = []
    for key in sorted(baseline_rows):
        candidate_row, baseline_row = candidate_rows[key], baseline_rows[key]
        for region in ('halo', 'near_edge', 'valid', 'hole_id0', 'hole_id1'):
            cm = candidate_row['regions'][region]
            bm = baseline_row['regions'][region]
            measured = bool(cm['count'] and bm['count'] and
                            cm['mae_rgb8'] is not None and bm['mae_rgb8'] is not None and
                            cm['p99_rgb8'] is not None and bm['p99_rgb8'] is not None)
            comparisons.append({
                'scene': key[0], 'eye': key[1], 'region': region,
                'candidate_count': cm['count'], 'baseline_count': bm['count'],
                'candidate_mae_rgb8': cm['mae_rgb8'], 'baseline_mae_rgb8': bm['mae_rgb8'],
                'delta_mae_rgb8': cm['mae_rgb8'] - bm['mae_rgb8'] if measured else None,
                'candidate_p99_rgb8': cm['p99_rgb8'], 'baseline_p99_rgb8': bm['p99_rgb8'],
                'delta_p99_rgb8': cm['p99_rgb8'] - bm['p99_rgb8'] if measured else None,
                'status': 'MEASURED' if measured else 'EMPTY_NOT_PASS',
            })
        ci = candidate_row['foreground']['valid']
        bi = baseline_row['foreground']['valid']
        measured_iou = bool(ci['union'] and bi['union'] and ci['iou'] is not None and bi['iou'] is not None)
        comparisons.append({
            'scene': key[0], 'eye': key[1], 'region': 'foreground_valid_iou',
            'candidate_iou': ci['iou'], 'baseline_iou': bi['iou'],
            'delta_iou': ci['iou'] - bi['iou'] if measured_iou else None,
            'status': 'MEASURED' if measured_iou else 'EMPTY_NOT_PASS',
        })
    return comparisons


def _validate_sweep_capture(folder, profile, probe):
    path = folder / probe
    files = sorted(path.glob('recon_v3_*.bgra'))
    if len(files) != 40 or any(p.stat().st_size != frozen.H * frozen.W * 2 * 4 for p in files):
        raise RuntimeError(f'{profile}/{probe}: expected 40 captures of 663552 bytes')
    contract = frozen.old.validate_capture_contract(path)
    rows = [json.loads(line) for line in (path / 'recon_v3_capture_contract.jsonl').read_text().splitlines()]
    p = PROFILES[profile]
    if len(rows) != 40:
        raise RuntimeError(f'{profile}/{probe}: expected 40 contract records')
    for row in rows:
        if (row.get('profile') != profile or row.get('probe') != probe or
                row.get('legacy_curve') is not False or row.get('schema') != 'effective_v2'):
            raise RuntimeError(f'{profile}/{probe}: wrong profile/probe/schema')
        for key, expected in {
            'close': p.close, 'far': p.far, 'start_m': p.start_m,
            'end_m': p.end_m, 'near_m': p.near_m, 'softness': p.softness,
        }.items():
            if abs(row[key] - expected) > 2e-6:
                raise RuntimeError(f'{profile}/{probe}: wrong {key}: {row[key]} != {expected}')
        if probe == 'constants':
            values = frozen.floats(path / row['file'])
            if not np.isfinite(values).all():
                raise RuntimeError(f'{profile}: nonfinite constant readback')
            for eye in (0, 1):
                expected_values = frozen.expected_constants(p, eye, row['calibration'])
                if profile == 'S8':
                    # M4 off: no fine-fovea grid. GPU #358 readback showed exactly
                    # cols 9 (M4Grid.x), 10 (M4Flags.x), 12 (M4Flags.y) at 0; all
                    # other columns equal P1.
                    for m4_column in S8_M4_OFF_COLUMNS:
                        expected_values[m4_column] = 0.
                for column, expected in expected_values.items():
                    got = values[frozen.H // 2, eye * frozen.W + column]
                    if abs(float(got) - expected) > max(2e-6, abs(expected) * 2e-5):
                        raise RuntimeError(
                            f'{profile} GPU effective constant col{column}: {got} != {expected}')
        if probe == 'uv' and row['calibration']:
            sx, sy = frozen.uv(path / row['file'])
            yy, xx = np.indices((frozen.H, frozen.W))
            for eye in (0, 1):
                if (np.max(np.abs(sx[:, eye * frozen.W:(eye + 1) * frozen.W] - xx)) > .01 or
                        np.max(np.abs(sy[:, eye * frozen.W:(eye + 1) * frozen.W] - yy)) > .01):
                    raise RuntimeError(f'{profile}: zero-strength packed UV readback is not identity')
    return {'capture_contract': contract, 'records_per_probe': 40,
            'capture_bytes': 663552}


def score_sweep_profile(corpus, captures, profile, baseline_result):
    """Compute classification metrics using frozen scorer's functions/helpers."""
    frozen = _load_frozen()
    if profile not in {f'S{i}' for i in range(1, 9)}:
        raise RuntimeError('Unknown sweep profile')
    corpus, captures = Path(corpus), Path(captures)
    p = PROFILES[profile]
    checks = {probe: _validate_sweep_capture(captures, profile, probe)
              for probe in ('rgb', 'uv', 'constants')}
    manifest = json.loads((corpus / 'manifest.json').read_text())
    verification = frozen.old.verify(
        corpus, Path(frozen.old.__file__).parent / 'expected.json', frozen.old.s)
    calibration = frozen.old.calibrate(corpus, captures / 'rgb', manifest['scenes'])
    if not calibration['pass']:
        raise RuntimeError(f'{profile}: original zero-strength calibration invalid')
    checks['corpus'] = verification
    checks['zero_calibration'] = calibration

    pooled = {}
    fg_counts = {}
    stored = {}
    reference_profile = PROFILES['P1']
    for record in manifest['scenes']:
        name, scene, pan = record['files_dir'], record['scene'], record['pan_mode']
        texture = frozen.old.s.texture_layers(scene)
        for frame in range(4):
            _, _, center_ids, _ = frozen.old.s.render(
                texture, 'center', frame, scene, False,
                cam_move=record['camera_moves'], physical_move=record['foreground_moves'])
            filename = f'recon_v3_{name}_f{frame}.bgra'
            image = frozen.old.rgb(captures / 'rgb' / filename, True)
            source_x, source_y = frozen.uv(captures / 'uv' / filename)
            for eye_index, eye in enumerate(EYES):
                output = image[:, eye_index * frozen.W:(eye_index + 1) * frozen.W]
                gt = frozen.old.rgb(corpus / name / f'{frame:02}_gt_{eye}.bgra')
                ids = np.fromfile(corpus / name / f'{frame:02}_gt_{eye}_ids.u8', np.uint8).reshape(frozen.H, frozen.W)
                profile_masks, _ = frozen.geometric_masks(ids, center_ids, eye, pan, p)
                reference_masks, _ = frozen.geometric_masks(
                    ids, center_ids, eye, pan, reference_profile)
                error = np.abs(output.astype(np.int16) - gt.astype(np.int16)).mean(axis=2)
                x = source_x[:, eye_index * frozen.W:(eye_index + 1) * frozen.W]
                y = source_y[:, eye_index * frozen.W:(eye_index + 1) * frozen.W]
                predicted = cv2.remap(center_ids, x.astype(np.float32), y.astype(np.float32),
                                      cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT,
                                      borderValue=255)
                for key in ('valid', 'near_edge', 'halo', 'hole_id0', 'hole_id1'):
                    pooled.setdefault((name, eye, key), []).append(error[profile_masks[key]])
                fg = frozen.integrity(predicted, ids, profile_masks['valid'])
                acc = fg_counts.setdefault((name, eye), [0, 0])
                acc[0] += fg['intersection']
                acc[1] += fg['union']
                stored[name, eye, frame] = (output, gt, reference_masks)

    scene_eye = []
    for name in frozen.old.EXPECTED_SCENES:
        for eye in EYES:
            regions = {}
            for region in ('valid', 'near_edge', 'halo', 'hole_id0', 'hole_id1'):
                arrays = pooled[name, eye, region]
                values = np.concatenate(arrays) if arrays else np.empty(0, np.float64)
                regions[region] = frozen.old.summary(
                    values, np.ones(values.size, dtype=bool))
            intersection, union = fg_counts[name, eye]
            foreground = {'valid': {
                'intersection': intersection, 'union': union,
                'iou': intersection / union if union else None,
            }}
            scene_eye.append({'scene': name, 'eye': eye,
                              'regions': regions, 'foreground': foreground})

    transitions = []
    for name in frozen.old.EXPECTED_SCENES:
        for eye in EYES:
            for frame in range(3):
                a, ga, ma = stored[name, eye, frame]
                b, gb, mb = stored[name, eye, frame + 1]
                regions = {}
                for region in TEMPORAL_REGIONS:
                    mask = ma[region] | mb[region]
                    regions[region] = frozen.temporal(a, b, ga, gb, mask)
                transitions.append({
                    'scene': name, 'eye': eye,
                    'from_frame': frame, 'to_frame': frame + 1,
                    'regions': regions,
                })
    result = {
        'profile': profile,
        'profile_validation': checks,
        'scene_eye': scene_eye,
        'transitions': transitions,
        'temporal_roi': 'Fixed P1 geometric masks for candidate-vs-P1 matched transitions.',
        'scorer_helpers_reused': [
            'edge_baseline_score.floats', 'edge_baseline_score.expected_constants',
            'edge_baseline_score.uv', 'edge_baseline_score.geometric_masks',
            'edge_baseline_score.temporal', 'edge_baseline_score.integrity',
            'edge_baseline_score.paired_delta', 'score_warp_v3.validate_capture_contract',
            'score_warp_v3.verify', 'score_warp_v3.calibrate', 'score_warp_v3.texture_layers',
            'score_warp_v3.render', 'score_warp_v3.rgb', 'score_warp_v3.summary',
        ],
    }
    result['spatial_comparison_vs_P1'] = compare_spatial_vs_p1(result, baseline_result)
    result['classification'] = classify_profile(result, baseline_result, frozen.paired_delta)
    return result


def _markdown(summary):
    lines = [
        '# Frozen #357 V2 settings sweep',
        '',
        'Measurement-only WARP evidence; no settings recommendation or headset claim.',
        'Classifier: preregistered BETTER / TRADE / WORSE / NEUTRAL gates vs P1.',
        '',
        '| Profile | Result | Target halo gains (weapon L/R, layers L/R) | Temporal failures | Spatial safety failures | IoU failures |',
        '|---|---|---|---:|---:|---:|',
    ]
    for profile in (f'S{i}' for i in range(1, 9)):
        item = summary['profiles'][profile]
        classification = item['classification']
        gains = '; '.join(
            f"{row['baseline_mae_rgb8']:.2f}→{row['candidate_mae_rgb8']:.2f} "
            f"(gain {row['improvement_rgb8']:.2f}, {'pass' if row['gain_pass'] else 'fail'})"
            for row in item['classification_detail']['halo_tests'])
        detail = item['classification_detail']
        lines.append(
            f"| {profile} | {classification} | {gains} | "
            f"{detail['temporal_failure_count']} | {detail['spatial_safety_failure_count']} | "
            f"{detail['foreground_iou_failure_count']} |")
    lines.extend([
        '',
        'The frozen scorer file is imported unchanged. Temporal candidate metrics use the same P1 geometric ROI masks as the P1 reference so matched counts and regions are comparable.',
        'S8 additionally requires GPU constant readback `M4Grid.x == M4Flags.x == M4Flags.y == 0`; the fixture effective-settings guard asserts `m4_fovea_grid=false`, `m2_fovea_depth=false`, and `m25_fine_mode=0`.',
        '',
    ])
    return '\n'.join(lines)


def run(corpus, sweep_root, baseline_json, summary_json, summary_md):
    baseline_result = json.loads(Path(baseline_json).read_text())
    profiles = {}
    for profile in (f'S{i}' for i in range(1, 9)):
        result = score_sweep_profile(corpus, Path(sweep_root) / profile,
                                     profile, baseline_result)
        profiles[profile] = {
            'classification': result['classification']['classification'],
            'classification_detail': result['classification'],
            'profile_validation': result['profile_validation'],
            'scene_eye': result['scene_eye'],
            'spatial_comparison_vs_P1': result['spatial_comparison_vs_P1'],
            'transitions': result['transitions'],
            'temporal_roi': result['temporal_roi'],
            'scorer_helpers_reused': result['scorer_helpers_reused'],
        }
        (Path(sweep_root) / f'{profile}_score.json').write_text(
            json.dumps(result, indent=2), encoding='utf-8')
        print('SWEEP_SCORED', profile, profiles[profile]['classification'], flush=True)
    summary = {
        'baseline': 'P1',
        'baseline_commit': '1ea95a5f6738d0af9518d3473585c89b6a365a63',
        'classification_rules': {
            'better': 'Both target-scene halos improve by >= max(0.5 RGB8, 5%) on both eyes; no temporal regression; valid/hole MAE and p99 limits pass; FG IoU drop <= 0.005.',
            'trade': 'Halo gain passes, but foliage/natural temporal or hole safety gate fails.',
            'worse': 'Target halo worsens by >= max(0.5 RGB8, 5%) on either target scene/eye, or a safety gate fails without a complete halo gain.',
            'neutral': 'All other outcomes.',
        },
        'profiles': profiles,
    }
    summary_json, summary_md = Path(summary_json), Path(summary_md)
    summary_json.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    summary_md.write_text(_markdown(summary), encoding='utf-8')
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--corpus', type=Path, required=True)
    ap.add_argument('--sweep', type=Path, required=True)
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--summary-json', type=Path, required=True)
    ap.add_argument('--summary-md', type=Path, required=True)
    args = ap.parse_args()
    run(args.corpus, args.sweep, args.baseline,
        args.summary_json, args.summary_md)
    print('SWEEP_COMPARE_PASS: 8 profiles classified vs frozen P1', flush=True)


if __name__ == '__main__':
    main()

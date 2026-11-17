"""Synthetic classification tests for the preregistered S1-S8 sweep rules."""
import copy
from pathlib import Path
import unittest

from sweep_compare import classify_profile
from edge_math import PROFILES


SCENES = (
    'weapon_object_motion',
    'layers_object_motion',
    'foliage_stationary_false49',
    'foliage_physical_sway',
    'natural_physical_sway',
)
EYES = ('left', 'right')
TEMPORAL_REGIONS = ('edge', 'halo', 'valid', 'fovea_core', 'periphery_outer', 'blend')


def synthetic_scores():
    scene_eye = []
    for scene in SCENES:
        for eye in EYES:
            scene_eye.append({
                'scene': scene,
                'eye': eye,
                'regions': {
                    'halo': {'count': 100, 'mae_rgb8': 10.0, 'p99_rgb8': 20.0},
                    'valid': {'count': 1000, 'mae_rgb8': 5.0, 'p99_rgb8': 20.0},
                    'hole_id0': {'count': 100, 'mae_rgb8': 5.0, 'p99_rgb8': 20.0},
                    'hole_id1': {'count': 100, 'mae_rgb8': 5.0, 'p99_rgb8': 20.0},
                },
                'foreground': {'valid': {'union': 1000, 'iou': 0.99}},
            })
    transitions = []
    for scene in SCENES:
        for eye in EYES:
            for frame in range(3):
                transitions.append({
                    'scene': scene,
                    'eye': eye,
                    'from_frame': frame,
                    'to_frame': frame + 1,
                    'regions': {
                        region: {'count': 100, 'normalized': 0.0}
                        for region in TEMPORAL_REGIONS
                    },
                })
    return {'scene_eye': scene_eye, 'transitions': transitions}


def halo_profile(scores, mae):
    for row in scores['scene_eye']:
        if row['scene'] in ('weapon_object_motion', 'layers_object_motion'):
            row['regions']['halo']['mae_rgb8'] = mae


def paired_delta(candidate, baseline):
    if candidate['count'] != baseline['count']:
        raise RuntimeError('Temporal pair ROI changed')
    if not baseline['count']:
        return {'status': 'EMPTY_NOT_PASS', 'regression': None}
    delta = candidate['normalized'] - baseline['normalized']
    limit = max(.00005, .05 * baseline['normalized'])
    return {'status': 'MEASURED', 'delta': delta,
            'regression': delta > limit}


class SweepClassification(unittest.TestCase):
    def test_preregistered_profiles_are_one_factor_from_p1(self):
        expected = {
            'S1': (.25, 0., 7.869, 32.052, .2, .99),
            'S2': (.5, 0., 7.869, 32.052, .2, .99),
            'S3': (0., .75, 7.869, 32.052, .2, .99),
            'S4': (0., 0., 2., 8., .2, .99),
            'S5': (0., 0., 7.869, 32.052, 0., .99),
            'S6': (0., 0., 7.869, 32.052, .1, .99),
            'S7': (0., 0., 7.869, 32.052, .4, .99),
            'S8': (0., 0., 7.869, 32.052, .2, .99),
        }
        for name, values in expected.items():
            profile = PROFILES[name]
            self.assertEqual((profile.close, profile.far, profile.start_m,
                              profile.end_m, profile.near_m, profile.softness), values)

    def test_s8_off_columns_are_exactly_the_m4_probe_columns(self):
        import re
        from sweep_compare import S8_M4_OFF_COLUMNS
        probe = (Path(__file__).resolve().parent.parent / 'prepare_edge_probe.py').read_text(encoding='utf-8')
        mapping = {int(c): v for c, v in re.findall(r'if\(column==(\d+)u\) value=(?:float\()?([A-Za-z0-9_.\[\]]+)', probe)}
        m4_columns = tuple(sorted(c for c, v in mapping.items() if v.startswith('M4')))
        self.assertEqual(len(mapping), 16)
        self.assertEqual(S8_M4_OFF_COLUMNS, m4_columns)
        self.assertEqual([mapping[c] for c in S8_M4_OFF_COLUMNS], ['M4Grid.x', 'M4Flags.x', 'M4Flags.y'])

    def setUp(self):
        self.baseline = synthetic_scores()
        self.candidate = copy.deepcopy(self.baseline)

    def test_better_at_exact_temporal_regression_limit(self):
        halo_profile(self.candidate, 9.5)
        self.candidate['transitions'][0]['regions']['edge']['normalized'] = 0.00005
        self.assertEqual(classify_profile(self.candidate, self.baseline, paired_delta)['classification'], 'BETTER')

    def test_trade_when_halo_gain_has_foliage_temporal_regression(self):
        halo_profile(self.candidate, 9.5)
        row = next(r for r in self.candidate['transitions']
                   if r['scene'] == 'foliage_physical_sway' and r['eye'] == 'left'
                   and r['from_frame'] == 0)
        row['regions']['halo']['normalized'] = 0.000051
        self.assertEqual(classify_profile(self.candidate, self.baseline, paired_delta)['classification'], 'TRADE')

    def test_worse_when_a_target_halo_worsens_by_limit(self):
        row = next(r for r in self.candidate['scene_eye']
                   if r['scene'] == 'weapon_object_motion' and r['eye'] == 'right')
        row['regions']['halo']['mae_rgb8'] = 10.5
        self.assertEqual(classify_profile(self.candidate, self.baseline, paired_delta)['classification'], 'WORSE')

    def test_neutral_when_halo_gain_is_below_limit(self):
        halo_profile(self.candidate, 9.51)
        self.assertEqual(classify_profile(self.candidate, self.baseline, paired_delta)['classification'], 'NEUTRAL')


if __name__ == '__main__':
    unittest.main(verbosity=2)

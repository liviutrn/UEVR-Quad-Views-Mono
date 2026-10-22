import unittest
from pathlib import Path

from quadview_log_regression import analyze_text


FIXTURES = Path(__file__).with_name("log_fixtures")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class QuadViewLogRegressionTests(unittest.TestCase):
    def test_startup_black_with_waiting_and_no_stage_views_fails(self):
        result = analyze_text(fixture("synthetic_startup_black.log"))

        self.assertEqual("FAIL_STARTUP_BLACK", result.classification)
        self.assertEqual(0, result.fresh_scene_submits)
        self.assertEqual(3, result.output_waiting)
        self.assertEqual(3, result.no_stage_views)
        self.assertEqual("startup_black", result.mode_windows[0].status)

    def test_two_real_submits_sixty_two_seconds_apart_then_starvation_fails(self):
        result = analyze_text(fixture("historical_excerpt_20261021-185053.log"))

        self.assertEqual("FAIL_STARVATION", result.classification)
        self.assertEqual(2, result.fresh_scene_submits)
        self.assertEqual(2, len(result.mode_windows))
        self.assertAlmostEqual(62.202, result.largest_fresh_submit_gap_seconds, places=3)
        self.assertTrue(all(window.status == "starvation_tail" for window in result.mode_windows))
        self.assertGreater(result.output_waiting, 0)

    def test_sustained_delivery_survives_mode_changes_and_per_generation_serial_reset(self):
        result = analyze_text(fixture("synthetic_sustained_mode_generations.log"))

        self.assertEqual("PROGRESS_OBSERVED_WINDOW", result.classification)
        self.assertEqual(2, len(result.mode_windows))
        self.assertEqual([10, 11, 12], result.mode_windows[0].fresh_serials)
        self.assertEqual([1, 2, 3], result.mode_windows[1].fresh_serials)
        self.assertTrue(all(window.status == "progress_observed" for window in result.mode_windows))
        self.assertEqual(0, sum(window.serial_regressions for window in result.mode_windows))
        self.assertTrue(all(window.max_scene_gap_seconds <= 2.0 for window in result.mode_windows))

    def test_held_stereo_output_is_counted_but_not_as_new_scene_delivery(self):
        result = analyze_text(fixture("synthetic_held_then_starved.log"))

        self.assertEqual("FAIL_STARVATION", result.classification)
        self.assertEqual(1, result.fresh_scene_submits)
        self.assertEqual(2, result.held_submits)
        self.assertEqual(3, result.stereo_submits)
        self.assertEqual([77], result.mode_windows[0].fresh_serials)
        self.assertEqual("starvation_tail", result.mode_windows[0].status)

    def test_historical_progress_with_starvation_and_runtime_anomaly_is_not_acceptance(self):
        result = analyze_text(fixture("historical_excerpt_20261020-153726.log"))

        self.assertEqual("FAIL_STARVATION", result.classification)
        self.assertGreaterEqual(result.fresh_scene_submits, 30)
        self.assertGreaterEqual(result.rhi_source_executed, 1)
        self.assertGreater(result.runtime_anomalies, 0)
        self.assertIn("progress_observed", [window.status for window in result.mode_windows])
        self.assertIn("starvation_gap", [window.status for window in result.mode_windows])
        self.assertTrue(any("not stability evidence" in item for item in result.issues))

    def test_submit_without_two_eyes_is_not_scene_progress(self):
        text = "\n".join([
            "[2026-10-22 12:00:00.000] [UnrealVR] [info] [Mono] Committed rendering method 7 at viewport boundary, generation=1",
            "[2026-10-22 12:00:01.000] [UnrealVR] [info] [D3D12Component.cpp:1] [QuadView][CopyEnqueued] serial=7 histories=15 source=abc output=def",
            "[2026-10-22 12:00:01.001] [UnrealVR] [info] [OpenXR.cpp:1] [QuadView][Submit] serial=7 held=false eyes=1",
            "[2026-10-22 12:00:08.000] [UnrealVR] [info] [Mono] Committed rendering method 6 at viewport boundary, generation=2",
        ])
        result = analyze_text(text)

        self.assertEqual("FAIL_NO_FRESH_SCENE_PROGRESS", result.classification)
        self.assertEqual(0, result.fresh_scene_submits)
        self.assertEqual(1, result.mode_windows[0].invalid_eye_submits)

    def test_zero_serial_fresh_submit_fails_serial_invariant_and_is_not_counted(self):
        text = "\n".join([
            "[2026-10-22 12:00:00.000] [UnrealVR] [info] [Mono] Committed rendering method 7 at viewport boundary, generation=1",
            "[2026-10-22 12:00:01.000] [UnrealVR] [info] [OpenXR.cpp:1] [QuadView][Submit] serial=1 held=false eyes=2",
            "[2026-10-22 12:00:02.000] [UnrealVR] [info] [OpenXR.cpp:1] [QuadView][Submit] serial=2 held=false eyes=2",
            "[2026-10-22 12:00:03.000] [UnrealVR] [info] [OpenXR.cpp:1] [QuadView][Submit] serial=3 held=false eyes=2",
            "[2026-10-22 12:00:04.000] [UnrealVR] [info] [OpenXR.cpp:1] [QuadView][Submit] serial=0 held=false eyes=2",
            "[2026-10-22 12:00:08.000] [UnrealVR] [info] [Mono] Committed rendering method 6 at viewport boundary, generation=2",
        ])
        result = analyze_text(text)

        self.assertEqual("FAIL_SERIAL_INVARIANT", result.classification)
        self.assertEqual(3, result.fresh_scene_submits)
        self.assertEqual([1, 2, 3], result.mode_windows[0].fresh_serials)
        self.assertEqual(1, result.mode_windows[0].invalid_serial_submits)
        self.assertEqual("serial_invariant_failure", result.mode_windows[0].status)

    def test_serial_regression_within_generation_fails_serial_invariant(self):
        text = "\n".join([
            "[2026-10-22 12:00:00.000] [UnrealVR] [info] [Mono] Committed rendering method 7 at viewport boundary, generation=1",
            "[2026-10-22 12:00:01.000] [UnrealVR] [info] [OpenXR.cpp:1] [QuadView][Submit] serial=9 held=false eyes=2",
            "[2026-10-22 12:00:02.000] [UnrealVR] [info] [OpenXR.cpp:1] [QuadView][Submit] serial=10 held=false eyes=2",
            "[2026-10-22 12:00:03.000] [UnrealVR] [info] [OpenXR.cpp:1] [QuadView][Submit] serial=8 held=false eyes=2",
            "[2026-10-22 12:00:04.000] [UnrealVR] [info] [OpenXR.cpp:1] [QuadView][Submit] serial=11 held=false eyes=2",
            "[2026-10-22 12:00:08.000] [UnrealVR] [info] [Mono] Committed rendering method 6 at viewport boundary, generation=2",
        ])
        result = analyze_text(text)

        self.assertEqual("FAIL_SERIAL_INVARIANT", result.classification)
        self.assertEqual(4, result.fresh_scene_submits)
        self.assertEqual(1, result.mode_windows[0].serial_regressions)
        self.assertEqual("serial_invariant_failure", result.mode_windows[0].status)

    def test_unrecognized_text_is_actionable_inconclusive(self):
        result = analyze_text("not a timestamped runtime log")
        self.assertEqual("INCONCLUSIVE_NO_TIMESTAMPED_LOG_EVENTS", result.classification)


if __name__ == "__main__":
    unittest.main()

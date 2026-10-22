"""Tests for the callback-level QuadViews trace summary."""

from pathlib import Path
import unittest

from quadview_hook_trace_summary import analyze_inputs, format_text


REPO_ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_BUILD49_LOG = REPO_ROOT.parent / "upload" / "log(20261022-181350).txt"


def trace(event, generation=7, serial=20, frame=300, role=255, **attrs):
    fields = {
        "event": event,
        "generation": generation,
        "serial": serial,
        "frame": frame,
        "role": role,
        "mode": 7,
    }
    fields.update(attrs)
    encoded = " ".join(f"{key}={value}" for key, value in fields.items())
    return f"[2026-10-22 21:13:10.635] [UnrealVR] [info] [Hook.cpp:1] [QuadViews][HookTrace] {encoded}"


class HookTraceSummaryTests(unittest.TestCase):
    def test_interleaved_roles_and_transactions_complete_from_observed_stages(self):
        records = [
            trace("GT_REGISTER", serial=20),
            trace("GT_REGISTER", serial=21),
            trace("ROLE_GT_BOUND", serial=20, role=0),
            trace("RT_ENTER", serial=21, role=2),
            # A late role registration stays with the matching owner despite interleaving.
            trace("ROLE_GT_BOUND", serial=20, role=1),
        ]
        per_role_stages = [
            "RT_ENTER", "RT_MATCH", "SLATE_QUEUED", "SLATE_ENTER", "HOOK_ENTER",
            "HOOK_TAIL", "HOOK_ATTACHED", "HOOK_INSTALLED", "RHI_ENTRY", "RHI_LOCKED",
            "ORIGINAL_ENTER", "ORIGINAL_RETURN", "RHI_COMPLETE",
        ]
        for role in (0, 1):
            for event in per_role_stages:
                extra = {"recorded": "true", "ours_known": "true", "ours": "false"} if event == "HOOK_INSTALLED" and role == 0 else {}
                records.append(trace(event, serial=20, role=role, **extra))
        records.extend([
            trace("SOURCE_SELECT", serial=20),
            trace("COPY_ENQUEUED", serial=20),
            trace("XR_SUBMIT", serial=20),
        ])

        result = analyze_inputs([("interleaved.log", "\n".join(records))])
        self.assertEqual(result["status"], "XR_SUBMIT_OBSERVED")
        self.assertEqual(result["group_count"], 2)
        self.assertEqual(result["counts"]["hook_installed"], 2)
        self.assertEqual(result["counts"]["rhi_entry"], 2)
        self.assertEqual(result["counts"]["rhi_complete"], 2)
        self.assertEqual(result["counts"]["copy_enqueued"], 1)
        self.assertEqual(result["counts"]["xr_submit"], 1)
        complete = next(group for group in result["groups"] if group["serial"] == 20)
        self.assertEqual(complete["status"], "XR_SUBMIT_OBSERVED")
        self.assertEqual([role["role"] for role in complete["roles"]], [0, 1, 255])
        self.assertEqual(len(complete["possible_stale_vtable_records"]), 1)
        self.assertEqual(complete["possible_stale_vtable_records"][0]["classification"],
                         "possible_stale_vtable_record")
        self.assertFalse(complete["unresolved_transitions"])
        self.assertNotIn("success", result)

    def test_first_rejection_reason_is_preserved(self):
        text = "\n".join([
            trace("GT_REGISTER", serial=40),
            trace("HOOK_REJECT", serial=40, role=2, reason="unsafe_vtable"),
            trace("HOOK_REJECT", serial=40, role=0, reason="later_duplicate"),
        ])
        result = analyze_inputs([("reject.log", text)])
        group = result["groups"][0]
        self.assertEqual(result["status"], "REJECTED_NO_COPY_ENQUEUE_OBSERVED")
        self.assertEqual(group["earliest_reject"]["reason"], "unsafe_vtable")
        self.assertEqual(group["earliest_reject"]["role"], 2)

    def test_installed_without_rhi_entry_is_only_a_missing_observation(self):
        text = trace("HOOK_INSTALLED", generation=9, serial=41, role=3,
                     recorded="true", ours_known="true", ours="false")
        result = analyze_inputs([("installed.log", text)])
        group = result["groups"][0]
        self.assertEqual(result["counts"]["hook_installed"], 1)
        self.assertEqual(result["counts"]["rhi_entry"], 0)
        self.assertTrue(group["installed_without_rhi_entry"])
        self.assertEqual(group["installed_without_rhi_entry_roles"], [3])
        self.assertIn("not proof of no execution", group["unresolved_transitions"][0])
        self.assertEqual(result["status"], "NO_COPY_ENQUEUE_OBSERVED")

    def test_unknown_hook_vtable_does_not_imply_stale_address(self):
        text=trace("HOOK_ENTER", recorded="true", ours_known="false", ours="false")
        result=analyze_inputs([("unknown.log",text)])
        self.assertEqual(result["groups"][0]["possible_stale_vtable_records"], [])

    def test_zero_owner_fields_are_kept_as_unowned_correlation(self):
        text = "\n".join([
            trace("HOOK_ENTER", generation=0, serial=0, frame=0, role=255),
            trace("HOOK_REJECT", generation=0, serial=0, frame=0, role=255,
                  reason="owner_unavailable"),
        ])
        result = analyze_inputs([("unowned.log", text)])
        self.assertEqual(result["group_count"], 1)
        group = result["groups"][0]
        self.assertEqual(group["owner_correlation"], "partial_or_unowned")
        self.assertIn("owner-correlation=partial", format_text(result))

    def test_auxiliary_and_unknown_events_are_accepted(self):
        events = ["HOOK_RETURN", "STATUS", "NATIVE_ATTACH", "NATIVE_EXECUTION",
                  "ENGINE_EXECUTION", "FUTURE_DIAGNOSTIC"]
        result = analyze_inputs([("auxiliary.log", "\n".join(
            trace(event, serial=42, status="observed") for event in events
        ))])
        group = result["groups"][0]
        self.assertEqual(group["event_counts"], {event: 1 for event in events})
        self.assertEqual(group["status"], "NO_COPY_ENQUEUE_OBSERVED")
        self.assertEqual(result["counts"]["copy_enqueued"], 0)
        self.assertEqual(result["counts"]["xr_submit"], 0)

    def test_no_trace_fails_closed(self):
        result = analyze_inputs([("old.log", "[QuadViews][NativeDispatch] registered=true\n")])
        self.assertEqual(result["status"], "HOOK_TRACE_MISSING")
        self.assertFalse(result["trace_available"])
        self.assertEqual(result["counts"]["copy_enqueued"], 0)
        self.assertNotIn("success", result)
        self.assertIn("no successful submit is inferred", format_text(result))

    @unittest.skipUnless(HISTORICAL_BUILD49_LOG.exists(), "local Build49 log is not bundled")
    def test_unmodified_historical_build49_log_has_no_new_trace(self):
        content = HISTORICAL_BUILD49_LOG.read_text(encoding="utf-8", errors="replace")
        result = analyze_inputs([(str(HISTORICAL_BUILD49_LOG), content)])
        self.assertEqual(result["status"], "HOOK_TRACE_MISSING")
        self.assertFalse(result["trace_available"])
        self.assertEqual(result["counts"]["copy_enqueued"], 0)
        self.assertNotIn("success", result)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Classify QuadView log continuity without treating log messages as GPU proof.

This reads the production log strings emitted by apply_quadviews.py and
apply_quadview_consumer.py. The result reports logged stereo-submit progress;
it cannot prove that D3D12 work completed or that headset pixels were valid.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


TIMESTAMP_RE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\]")
MODE_RE = re.compile(
    r"\[Mono\] Committed rendering method (?P<method>\d+) "
    r"at viewport boundary, generation=(?P<generation>\d+)"
)
WAIT_RE = re.compile(r"\[QuadView\]\[OutputWaiting\].*?generation=(\d+)")
COPY_RE = re.compile(r"\[QuadView\]\[CopyEnqueued\].*?\bserial=(\d+)(?:\s|$)")
SUBMIT_RE = re.compile(
    r"\[QuadView\]\[Submit\].*?\bserial=(\d+)\s+held=(true|false)\s+eyes=(\d+)"
)
BOUND_RE = re.compile(r"\[QuadViews\]\[GTProducer\] BOUND\b.*?\bserial=(\d+)")
RENDER_MATCH_RE = re.compile(r"\[QuadViews\]\[RenderFamily\] matched\b.*?\bserial=(\d+)")
RENDER_REJECT_RE = re.compile(r"\[QuadViews\]\[RenderFamily\] (?:rejected|unmatched)")
RHI_TAIL_RE = re.compile(r"\[QuadViews\]\[RHI\] tail hooked\b.*?\bserial=(\d+)")
RHI_EXEC_RE = re.compile(r"\[QuadViews\]\[RHI\] source executed\b.*?\bserial=(\d+)")
NATIVE_RENDER_RE = re.compile(r"\[QuadViews\]\[NativeDispatch\] rendered four sources\b")
NO_STAGE_RE = re.compile(r"\[VR\] No stage views to submit")
RUNTIME_ANOMALY_RE = re.compile(
    r"attempted dereference of null pointer|"
    r"previous instruction does not use the same register as the dereference|"
    r"unhandled exception|access violation|fatal error|crash dump",
    re.IGNORECASE,
)


@dataclass
class Event:
    timestamp: datetime
    kind: str
    serial: Optional[int] = None
    method: Optional[int] = None
    generation: Optional[int] = None
    held: Optional[bool] = None
    eyes: Optional[int] = None
    line_number: int = 0


@dataclass
class ModeWindow:
    method: int
    generation: int
    start: datetime
    end: Optional[datetime] = None
    events: List[Event] = field(default_factory=list)

    def duration_seconds(self, observed_until: datetime) -> float:
        end = self.end or observed_until
        return max(0.0, (end - self.start).total_seconds())


@dataclass
class WindowReport:
    method: int
    generation: int
    start: datetime
    end: datetime
    duration_seconds: float
    fresh_serials: List[int]
    held_submits: int
    invalid_eye_submits: int
    invalid_serial_submits: int
    duplicate_serial_submits: int
    unpaired_fresh_submits: int
    copy_enqueued: int
    output_waiting: int
    no_stage_views: int
    max_scene_gap_seconds: Optional[float]
    trailing_scene_gap_seconds: Optional[float]
    serial_regressions: int
    status: str


@dataclass
class Analysis:
    classification: str
    mode_windows: List[WindowReport]
    observed_seconds: float
    fresh_scene_submits: int
    held_submits: int
    stereo_submits: int
    copy_enqueued: int
    output_waiting: int
    no_stage_views: int
    gt_bound: int
    render_matched: int
    render_rejected: int
    rhi_tail_hooked: int
    rhi_source_executed: int
    native_four_source_dispatch: int
    runtime_anomalies: int
    largest_fresh_submit_gap_seconds: Optional[float]
    issues: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "classification": self.classification,
            "observed_seconds": round(self.observed_seconds, 3),
            "fresh_scene_submits": self.fresh_scene_submits,
            "held_submits": self.held_submits,
            "stereo_submits": self.stereo_submits,
            "copy_enqueued": self.copy_enqueued,
            "output_waiting": self.output_waiting,
            "no_stage_views": self.no_stage_views,
            "pipeline_log_counts": {
                "gt_bound": self.gt_bound,
                "render_matched": self.render_matched,
                "render_rejected_or_unmatched": self.render_rejected,
                "rhi_tail_hooked": self.rhi_tail_hooked,
                "rhi_source_executed": self.rhi_source_executed,
                "native_four_source_dispatch": self.native_four_source_dispatch,
            },
            "runtime_anomalies": self.runtime_anomalies,
            "largest_fresh_submit_gap_seconds": (
                round(self.largest_fresh_submit_gap_seconds, 3)
                if self.largest_fresh_submit_gap_seconds is not None else None
            ),
            "windows": [
                {
                    "method": w.method,
                    "generation": w.generation,
                    "start": w.start.isoformat(sep=" "),
                    "end": w.end.isoformat(sep=" "),
                    "duration_seconds": round(w.duration_seconds, 3),
                    "fresh_serials": w.fresh_serials,
                    "held_submits": w.held_submits,
                    "invalid_eye_submits": w.invalid_eye_submits,
                    "invalid_serial_submits": w.invalid_serial_submits,
                    "duplicate_serial_submits": w.duplicate_serial_submits,
                    "unpaired_fresh_submits": w.unpaired_fresh_submits,
                    "copy_enqueued": w.copy_enqueued,
                    "output_waiting": w.output_waiting,
                    "no_stage_views": w.no_stage_views,
                    "max_scene_gap_seconds": (
                        round(w.max_scene_gap_seconds, 3)
                        if w.max_scene_gap_seconds is not None else None
                    ),
                    "trailing_scene_gap_seconds": (
                        round(w.trailing_scene_gap_seconds, 3)
                        if w.trailing_scene_gap_seconds is not None else None
                    ),
                    "serial_regressions": w.serial_regressions,
                    "status": w.status,
                }
                for w in self.mode_windows
            ],
            "issues": list(self.issues),
            "interpretation_limit": (
                "Submit held=false and CopyEnqueued are runtime log claims, not GPU fence, "
                "four-source write-provenance, or headset-pixel proof."
            ),
        }


def _parse_line(line: str, line_number: int) -> Tuple[Optional[datetime], Optional[Event]]:
    match = TIMESTAMP_RE.match(line)
    if not match:
        return None, None
    try:
        timestamp = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None, None

    mode = MODE_RE.search(line)
    if mode:
        return timestamp, Event(
            timestamp, "mode", method=int(mode.group("method")),
            generation=int(mode.group("generation")), line_number=line_number,
        )
    wait = WAIT_RE.search(line)
    if wait:
        return timestamp, Event(timestamp, "output_waiting", generation=int(wait.group(1)), line_number=line_number)
    copy = COPY_RE.search(line)
    if copy:
        return timestamp, Event(timestamp, "copy", serial=int(copy.group(1)), line_number=line_number)
    submit = SUBMIT_RE.search(line)
    if submit:
        return timestamp, Event(
            timestamp, "submit", serial=int(submit.group(1)), held=submit.group(2) == "true",
            eyes=int(submit.group(3)), line_number=line_number,
        )
    if BOUND_RE.search(line):
        return timestamp, Event(timestamp, "gt_bound", line_number=line_number)
    if RENDER_MATCH_RE.search(line):
        return timestamp, Event(timestamp, "render_matched", line_number=line_number)
    if RENDER_REJECT_RE.search(line):
        return timestamp, Event(timestamp, "render_rejected", line_number=line_number)
    if RHI_TAIL_RE.search(line):
        return timestamp, Event(timestamp, "rhi_tail_hooked", line_number=line_number)
    if RHI_EXEC_RE.search(line):
        return timestamp, Event(timestamp, "rhi_source_executed", line_number=line_number)
    if NATIVE_RENDER_RE.search(line):
        return timestamp, Event(timestamp, "native_four_source_dispatch", line_number=line_number)
    if NO_STAGE_RE.search(line):
        return timestamp, Event(timestamp, "no_stage_views", line_number=line_number)
    if RUNTIME_ANOMALY_RE.search(line):
        return timestamp, Event(timestamp, "runtime_anomaly", line_number=line_number)
    return timestamp, None


def _window_report(
    window: ModeWindow,
    observed_until: datetime,
    max_scene_gap_seconds: float,
    min_fresh_per_window: int,
    min_observation_seconds: float,
    black_start_seconds: float,
) -> WindowReport:
    end = window.end or observed_until
    duration = window.duration_seconds(observed_until)
    copies = {e.serial for e in window.events if e.kind == "copy" and e.serial is not None}
    submits = [e for e in window.events if e.kind == "submit"]
    fresh_events: List[Event] = []
    held = 0
    invalid_eyes = 0
    invalid_serials = 0
    duplicate = 0
    unpaired = 0
    seen_serials = set()
    previous_serial: Optional[int] = None
    regressions = 0

    for event in submits:
        if event.held:
            held += 1
            continue
        if event.eyes != 2 or event.serial is None:
            invalid_eyes += 1
            continue
        if event.serial <= 0:
            invalid_serials += 1
            continue
        if event.serial in seen_serials:
            duplicate += 1
            continue
        if previous_serial is not None and event.serial < previous_serial:
            regressions += 1
        previous_serial = event.serial
        seen_serials.add(event.serial)
        fresh_events.append(event)
        # These logs are independently throttled. A missing matching copy line
        # is diagnostic only; a fresh OpenXR submit still records scene progress.
        if event.serial not in copies:
            unpaired += 1

    fresh_events.sort(key=lambda e: e.timestamp)
    gaps = [
        max(0.0, (fresh_events[i].timestamp - fresh_events[i - 1].timestamp).total_seconds())
        for i in range(1, len(fresh_events))
    ]
    max_gap = max(gaps) if gaps else None
    trailing = max(0.0, (end - fresh_events[-1].timestamp).total_seconds()) if fresh_events else duration
    waits = sum(e.kind == "output_waiting" for e in window.events)
    no_stage = sum(e.kind == "no_stage_views" for e in window.events)
    copy_count = sum(e.kind == "copy" for e in window.events)

    if invalid_serials or regressions:
        status = "serial_invariant_failure"
    elif not fresh_events:
        if duration >= black_start_seconds and (waits or no_stage):
            status = "startup_black"
        elif duration >= black_start_seconds:
            status = "no_fresh_scene_progress"
        else:
            status = "insufficient_observation"
    elif max_gap is not None and max_gap > max_scene_gap_seconds:
        status = "starvation_gap"
    elif duration >= min_observation_seconds and trailing > max_scene_gap_seconds:
        status = "starvation_tail"
    elif duration < min_observation_seconds or len(seen_serials) < min_fresh_per_window:
        status = "insufficient_progress"
    else:
        status = "progress_observed"

    return WindowReport(
        method=window.method,
        generation=window.generation,
        start=window.start,
        end=end,
        duration_seconds=duration,
        fresh_serials=[event.serial for event in fresh_events if event.serial is not None],
        held_submits=held,
        invalid_eye_submits=invalid_eyes,
        invalid_serial_submits=invalid_serials,
        duplicate_serial_submits=duplicate,
        unpaired_fresh_submits=unpaired,
        copy_enqueued=copy_count,
        output_waiting=waits,
        no_stage_views=no_stage,
        max_scene_gap_seconds=max_gap,
        trailing_scene_gap_seconds=trailing,
        serial_regressions=regressions,
        status=status,
    )


def analyze_text(
    text: str,
    *,
    active_method: int = 7,
    max_scene_gap_seconds: float = 5.0,
    min_fresh_per_window: int = 3,
    min_observation_seconds: float = 5.0,
    black_start_seconds: float = 5.0,
) -> Analysis:
    """Analyze a log string. Method 7 is Build47's QuadView rendering method."""
    parsed: List[Event] = []
    timestamps: List[datetime] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        timestamp, event = _parse_line(line, line_number)
        if timestamp:
            timestamps.append(timestamp)
        if event:
            parsed.append(event)
    if not timestamps:
        return Analysis(
            "INCONCLUSIVE_NO_TIMESTAMPED_LOG_EVENTS", [], 0.0, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0, 0, None, ["No timestamped production log lines were recognized."],
        )

    parsed.sort(key=lambda event: (event.timestamp, event.line_number))
    observed_start, observed_end = min(timestamps), max(timestamps)
    observed_seconds = max(0.0, (observed_end - observed_start).total_seconds())
    mode_events = [event for event in parsed if event.kind == "mode"]
    windows: List[ModeWindow] = []
    current: Optional[ModeWindow] = None

    if mode_events:
        for event in parsed:
            if event.kind == "mode":
                if current:
                    current.end = event.timestamp
                    current = None
                if event.method == active_method and event.generation is not None:
                    current = ModeWindow(event.method, event.generation, event.timestamp)
                    windows.append(current)
                continue
            if current and current.start <= event.timestamp:
                current.events.append(event)
        if current:
            current.end = observed_end
    else:
        # Older logs can lack Mono's mode-commit message. Keep them actionable,
        # while marking the single window's generation/mode as inferred.
        qv_events = [event for event in parsed if event.kind in {
            "output_waiting", "copy", "submit", "gt_bound", "render_matched",
            "render_rejected", "rhi_tail_hooked", "rhi_source_executed",
            "native_four_source_dispatch", "no_stage_views",
        }]
        if qv_events:
            generation = next((e.generation for e in qv_events if e.generation is not None), 0)
            inferred = ModeWindow(active_method, generation, qv_events[0].timestamp, observed_end, qv_events)
            windows.append(inferred)

    reports = [
        _window_report(w, observed_end, max_scene_gap_seconds,
                       min_fresh_per_window, min_observation_seconds, black_start_seconds)
        for w in windows
    ]
    active_events = [event for window in windows for event in window.events]
    fresh_all: List[Event] = []
    for window in windows:
        seen_in_window = set()
        for event in window.events:
            if (event.kind == "submit" and event.held is False and event.eyes == 2
                    and event.serial is not None and event.serial > 0
                    and event.serial not in seen_in_window):
                seen_in_window.add(event.serial)
                fresh_all.append(event)
    fresh_all.sort(key=lambda e: e.timestamp)
    global_gaps = [
        max(0.0, (fresh_all[i].timestamp - fresh_all[i - 1].timestamp).total_seconds())
        for i in range(1, len(fresh_all))
    ]
    # Report inter-window gaps as well; they explain the historical two-submit
    # trace, while mode-aware status avoids blaming time spent in another mode.
    largest_global_gap = max(global_gaps) if global_gaps else None
    statuses = {report.status for report in reports}
    anomalies = sum(event.kind == "runtime_anomaly" for event in parsed)
    if "serial_invariant_failure" in statuses:
        classification = "FAIL_SERIAL_INVARIANT"
    elif "startup_black" in statuses:
        classification = "FAIL_STARTUP_BLACK"
    elif "starvation_gap" in statuses or "starvation_tail" in statuses:
        classification = "FAIL_STARVATION"
    elif "no_fresh_scene_progress" in statuses:
        classification = "FAIL_NO_FRESH_SCENE_PROGRESS"
    elif not reports or statuses.intersection({"insufficient_progress", "insufficient_observation"}):
        classification = "INCONCLUSIVE_SHORT_OR_INSUFFICIENT_PROGRESS"
    elif anomalies:
        classification = "PROGRESS_OBSERVED_WITH_RUNTIME_ANOMALY"
    else:
        classification = "PROGRESS_OBSERVED_WINDOW"

    issues: List[str] = []
    if not mode_events:
        issues.append("No Mono mode-window messages were found; a single mode-7 window was inferred.")
    if largest_global_gap is not None and largest_global_gap > max_scene_gap_seconds:
        issues.append(
            f"Fresh stereo-submit log records are {largest_global_gap:.3f}s apart across mode windows; "
            "inactive-mode time is excluded from per-window starvation status."
        )
    if anomalies:
        issues.append(f"Found {anomalies} runtime-fault signature line(s); observed progress is not stability evidence.")
    if any(report.unpaired_fresh_submits for report in reports):
        count = sum(report.unpaired_fresh_submits for report in reports)
        issues.append(
            f"{count} fresh submit record(s) have no same-serial CopyEnqueued record; these logs are independently throttled."
        )
    if any(report.serial_regressions for report in reports):
        issues.append("Serial decreased inside a single mode generation; scene progress fails the serial invariant.")
    invalid_serial_count = sum(report.invalid_serial_submits for report in reports)
    if invalid_serial_count:
        issues.append(
            f"Found {invalid_serial_count} fresh stereo submit record(s) with serial zero; these do not count as scene progress."
        )
    if not reports:
        issues.append(f"No rendering-method-{active_method} mode window was found.")

    def count(kind: str) -> int:
        return sum(event.kind == kind for event in active_events)

    return Analysis(
        classification=classification,
        mode_windows=reports,
        observed_seconds=observed_seconds,
        fresh_scene_submits=sum(len(report.fresh_serials) for report in reports),
        held_submits=sum(report.held_submits for report in reports),
        stereo_submits=sum(event.kind == "submit" and event.eyes == 2 for event in active_events),
        copy_enqueued=count("copy"),
        output_waiting=count("output_waiting"),
        no_stage_views=count("no_stage_views"),
        gt_bound=count("gt_bound"),
        render_matched=count("render_matched"),
        render_rejected=count("render_rejected"),
        rhi_tail_hooked=count("rhi_tail_hooked"),
        rhi_source_executed=count("rhi_source_executed"),
        native_four_source_dispatch=count("native_four_source_dispatch"),
        runtime_anomalies=anomalies,
        largest_fresh_submit_gap_seconds=largest_global_gap,
        issues=issues,
    )


def _print_report(path: str, analysis: Analysis) -> None:
    result = analysis.to_dict()
    print(f"log: {path}")
    print(f"classification: {analysis.classification}")
    print(
        "observed: {seconds:.3f}s; fresh stereo scene submits: {fresh}; held submits: {held}; "
        "stereo submits: {stereo}; copies enqueued: {copies}; output-waiting: {waiting}; "
        "no-stage-view lines: {missing}".format(
            seconds=analysis.observed_seconds, fresh=analysis.fresh_scene_submits,
            held=analysis.held_submits, stereo=analysis.stereo_submits,
            copies=analysis.copy_enqueued, waiting=analysis.output_waiting,
            missing=analysis.no_stage_views,
        )
    )
    if analysis.largest_fresh_submit_gap_seconds is not None:
        print(f"largest gap between fresh submit records: {analysis.largest_fresh_submit_gap_seconds:.3f}s")
    pipeline = result["pipeline_log_counts"]
    print("pipeline log counts: " + ", ".join(f"{key}={value}" for key, value in pipeline.items()))
    for window in analysis.mode_windows:
        max_gap = "n/a" if window.max_scene_gap_seconds is None else f"{window.max_scene_gap_seconds:.3f}s"
        tail_gap = "n/a" if window.trailing_scene_gap_seconds is None else f"{window.trailing_scene_gap_seconds:.3f}s"
        print(
            f"  method={window.method} generation={window.generation}: {window.status}; "
            f"fresh={len(window.fresh_serials)} serials={window.fresh_serials[:6]}{('…' if len(window.fresh_serials)>6 else '')}; "
            f"held={window.held_submits}; max-gap={max_gap}; tail-gap={tail_gap}; "
            f"OutputWaiting={window.output_waiting}; NoStageViews={window.no_stage_views}"
        )
    for issue in analysis.issues:
        print(f"note: {issue}")
    print("limit: logged submits/copies do not prove GPU completion, four source writes, or headset pixels.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", help="path to a QuadView runtime log")
    parser.add_argument("--active-method", type=int, default=7, help="active QuadView rendering method (default: 7)")
    parser.add_argument("--max-gap-seconds", type=float, default=5.0,
                        help="maximum permitted gap in fresh scene-submit logs (default: 5; avoids FPS claims)")
    parser.add_argument("--min-fresh-per-window", type=int, default=3)
    parser.add_argument("--min-observation-seconds", type=float, default=5.0)
    parser.add_argument("--black-start-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)
    path = Path(args.log)
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    analysis = analyze_text(
        content,
        active_method=args.active_method,
        max_scene_gap_seconds=args.max_gap_seconds,
        min_fresh_per_window=args.min_fresh_per_window,
        min_observation_seconds=args.min_observation_seconds,
        black_start_seconds=args.black_start_seconds,
    )
    _print_report(str(path), analysis)
    return 1 if analysis.classification.startswith("FAIL_") else 0


if __name__ == "__main__":
    raise SystemExit(main())

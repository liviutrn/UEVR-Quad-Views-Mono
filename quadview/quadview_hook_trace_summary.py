#!/usr/bin/env python3
"""Summarize QuadViews HookTrace observations without inferring runtime success."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence


MARKER = "[QuadViews][HookTrace]"
ATTRIBUTE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(?:\"([^\"]*)\"|'([^']*)'|(\S+))")
TIMESTAMP_RE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\]")

STAGES = (
    "GT_REGISTER",
    "ROLE_GT_BOUND",
    "RT_ENTER",
    "RT_MATCH",
    "SLATE_QUEUED",
    "SLATE_ENTER",
    "HOOK_ENTER",
    "HOOK_TAIL",
    "HOOK_ATTACHED",
    "HOOK_INSTALLED",
    "RHI_ENTRY",
    "RHI_LOCKED",
    "ORIGINAL_ENTER",
    "ORIGINAL_RETURN",
    "RHI_COMPLETE",
    "SOURCE_SELECT",
    "COPY_ENQUEUED",
    "XR_SUBMIT",
)
STAGE_INDEX = {stage: index for index, stage in enumerate(STAGES)}
COUNTED_EVENTS = (
    "HOOK_INSTALLED",
    "RHI_ENTRY",
    "RHI_COMPLETE",
    "COPY_ENQUEUED",
    "XR_SUBMIT",
)


@dataclass(frozen=True)
class TraceRecord:
    source: str
    line: int
    order: int
    event: str
    generation: int
    serial: int
    frame: int
    role: int
    attrs: dict[str, str]
    timestamp: Optional[str] = None


def _integer(value: str) -> int:
    return int(value, 16 if value.lower().startswith("0x") else 10)


def parse_text(text: str, source: str = "<text>", order_start: int = 0):
    """Return (records, malformed-line diagnostics, next order)."""
    records: list[TraceRecord] = []
    diagnostics: list[str] = []
    order = order_start
    for line_number, line in enumerate(text.splitlines(), 1):
        marker_at = line.find(MARKER)
        if marker_at < 0:
            continue
        attrs: dict[str, str] = {}
        tail = line[marker_at + len(MARKER):]
        for match in ATTRIBUTE_RE.finditer(tail):
            attrs[match.group(1)] = next(
                value for value in match.groups()[1:] if value is not None
            )
        try:
            event = attrs["event"].upper()
            generation = _integer(attrs["generation"])
            serial = _integer(attrs["serial"])
            frame = _integer(attrs["frame"])
            role = _integer(attrs["role"])
            if not event or not (0 <= generation < 2**64 and 0 <= serial < 2**64):
                raise ValueError("invalid event/generation/serial")
            if not 0 <= frame < 2**32 or role not in (0, 1, 2, 3, 255):
                raise ValueError("frame or role is outside the trace schema")
        except (KeyError, ValueError, StopIteration) as exc:
            diagnostics.append(f"{source}:{line_number}: malformed HookTrace record ({exc})")
            continue
        timestamp_match = TIMESTAMP_RE.match(line)
        records.append(TraceRecord(
            source=source,
            line=line_number,
            order=order,
            event=event,
            generation=generation,
            serial=serial,
            frame=frame,
            role=role,
            attrs=attrs,
            timestamp=timestamp_match.group(1) if timestamp_match else None,
        ))
        order += 1
    return records, diagnostics, order


def _earliest_reject(records: Sequence[TraceRecord]):
    for record in records:
        if record.event == "HOOK_REJECT":
            return {
                "event": record.event,
                "reason": record.attrs.get("reason", "unspecified"),
                "role": record.role,
                "frame": record.frame,
                "source": record.source,
                "line": record.line,
            }
    return None


def _stale_vtable_records(records: Sequence[TraceRecord]):
    candidates = []
    for record in records:
        values = {key: value.lower() for key, value in record.attrs.items()}
        if (values.get("recorded") == "true" and values.get("ours_known") == "true"
                and values.get("ours") == "false"):
            candidates.append({
                "source": record.source,
                "line": record.line,
                "event": record.event,
                "role": record.role,
                "frame": record.frame,
                "classification": "possible_stale_vtable_record",
                "note": "recorded=true/ours=false is a clue only; it does not prove cleanup is safe",
            })
    return candidates


def _unresolved_for(records: Sequence[TraceRecord]):
    """Report the next group handoff and role-local installed/RHI gaps."""
    by_role: dict[int, list[TraceRecord]] = defaultdict(list)
    for record in records:
        by_role[record.role].append(record)
    unresolved: list[str] = []
    installed_missing_rhi: list[int] = []
    role_summaries = []
    for role in sorted(by_role):
        role_records = by_role[role]
        observed = {record.event for record in role_records}
        stages = [stage for stage in STAGES if stage in observed]
        if "HOOK_INSTALLED" in observed and "RHI_ENTRY" not in observed:
            installed_missing_rhi.append(role)
        if stages or "HOOK_REJECT" in observed:
            role_summaries.append({
                "role": role,
                "observed_stages": stages,
                "hook_rejected": "HOOK_REJECT" in observed,
                "installed_without_rhi_entry": role in installed_missing_rhi,
            })
    observed = {record.event for record in records}
    stages = [stage for stage in STAGES if stage in observed]
    if "HOOK_INSTALLED" in observed and "RHI_ENTRY" not in observed:
        unresolved.append(
            "HOOK_INSTALLED->RHI_ENTRY not observed "
            "(callback absence in log is not proof of no execution)"
        )
    elif stages and stages[-1] != "XR_SUBMIT":
        latest = max(STAGE_INDEX[stage] for stage in stages)
        current = STAGES[latest]
        # A reject is an explicit alternate branch after entering/attaching.
        if "HOOK_REJECT" in observed and latest <= STAGE_INDEX["HOOK_TAIL"]:
            next_stage = None
        else:
            next_stage = STAGES[latest + 1]
        if next_stage:
            unresolved.append(f"{current}->{next_stage} not observed")
    return unresolved, installed_missing_rhi, role_summaries


def _group_summary(generation: int, serial: int, records: Sequence[TraceRecord]):
    event_counts = Counter(record.event for record in records)
    observed_stages = list(dict.fromkeys(
        record.event for record in records if record.event in STAGE_INDEX
    ))
    unresolved, installed_missing_rhi, role_summaries = _unresolved_for(records)
    copy_count = event_counts["COPY_ENQUEUED"]
    submit_count = event_counts["XR_SUBMIT"]
    reject = _earliest_reject(records)
    if submit_count:
        status = "XR_SUBMIT_OBSERVED"
    elif copy_count:
        status = "COPY_ENQUEUED_NO_XR_SUBMIT_OBSERVED"
    elif reject:
        status = "REJECTED_NO_COPY_ENQUEUE_OBSERVED"
    else:
        status = "NO_COPY_ENQUEUE_OBSERVED"
    if submit_count and not copy_count:
        unresolved.append("XR_SUBMIT observed without COPY_ENQUEUED record")
    return {
        "generation": generation,
        "serial": serial,
        "owner_correlation": (
            "partial_or_unowned" if generation == 0 or serial == 0 else "generation_serial"
        ),
        "record_count": len(records),
        "event_counts": dict(sorted(event_counts.items())),
        "counts": {event.lower(): event_counts[event] for event in COUNTED_EVENTS},
        "observed_stages": observed_stages,
        "roles": role_summaries,
        "earliest_reject": reject,
        "installed_without_rhi_entry": (
            event_counts["HOOK_INSTALLED"] > 0 and event_counts["RHI_ENTRY"] == 0
        ),
        "installed_without_rhi_entry_roles": installed_missing_rhi,
        "possible_stale_vtable_records": _stale_vtable_records(records),
        "unresolved_transitions": unresolved,
        "status": status,
    }


def analyze_records(records: Iterable[TraceRecord], diagnostics: Optional[list[str]] = None,
                    sources: Optional[list[str]] = None):
    records = sorted(records, key=lambda record: record.order)
    diagnostics = list(diagnostics or [])
    by_owner: dict[tuple[int, int], list[TraceRecord]] = defaultdict(list)
    for record in records:
        by_owner[(record.generation, record.serial)].append(record)
    groups = [
        _group_summary(generation, serial, group_records)
        for (generation, serial), group_records in sorted(by_owner.items())
    ]
    totals = Counter(record.event for record in records)
    if not records and not diagnostics:
        status = "HOOK_TRACE_MISSING"
        diagnostics.append(
            "No [QuadViews][HookTrace] records found; callback delivery cannot be assessed, "
            "and no successful submit is inferred."
        )
    elif not records:
        status = "HOOK_TRACE_MALFORMED"
        diagnostics.append("HookTrace markers were present, but no valid records could be parsed.")
    elif totals["XR_SUBMIT"]:
        status = "XR_SUBMIT_OBSERVED"
    elif totals["COPY_ENQUEUED"]:
        status = "COPY_ENQUEUED_NO_XR_SUBMIT_OBSERVED"
    elif totals["HOOK_REJECT"]:
        status = "REJECTED_NO_COPY_ENQUEUE_OBSERVED"
    else:
        status = "NO_COPY_ENQUEUE_OBSERVED"
    return {
        "status": status,
        "trace_available": bool(records),
        "record_count": len(records),
        "group_count": len(groups),
        "counts": {event.lower(): totals[event] for event in COUNTED_EVENTS},
        "groups": groups,
        "diagnostics": diagnostics,
        "interpretation_limit": (
            "These are log observations only. XR_SUBMIT is not headset-pixel or GPU-fence proof; "
            "missing callback records do not prove that execution never occurred."
        ),
        "sources": sources or [],
    }


def analyze_inputs(inputs: Sequence[tuple[str, str]]):
    records: list[TraceRecord] = []
    diagnostics: list[str] = []
    next_order = 0
    sources: list[str] = []
    for source, content in inputs:
        sources.append(source)
        parsed, parse_diagnostics, next_order = parse_text(content, source, next_order)
        records.extend(parsed)
        diagnostics.extend(parse_diagnostics)
    return analyze_records(records, diagnostics, sources)


def format_text(result: dict):
    lines = [
        f"HookTrace {result['status']}: records={result['record_count']} groups={result['group_count']} "
        f"installed={result['counts']['hook_installed']} rhi_entry={result['counts']['rhi_entry']} "
        f"complete={result['counts']['rhi_complete']} copy={result['counts']['copy_enqueued']} "
        f"xr_submit={result['counts']['xr_submit']}"
    ]
    if not result["trace_available"]:
        lines.extend(result["diagnostics"])
        return "\n".join(lines)
    for group in result["groups"]:
        stages = ",".join(group["observed_stages"]) or "(none)"
        line = (
            f"gen={group['generation']} serial={group['serial']} {group['status']} "
            f"events={group['record_count']} stages={stages}"
        )
        if group["owner_correlation"] == "partial_or_unowned":
            line += " owner-correlation=partial"
        reject = group["earliest_reject"]
        if reject:
            line += f" reject={reject['reason']}@{reject['source']}:{reject['line']}"
        if group["installed_without_rhi_entry_roles"]:
            line += " installed_without_rhi_entry=" + ",".join(
                str(role) for role in group["installed_without_rhi_entry_roles"]
            ) + "(callback-not-observed)"
        if group["possible_stale_vtable_records"]:
            line += f" possible_stale_vtable_records={len(group['possible_stale_vtable_records'])}"
        if group["unresolved_transitions"]:
            line += " gaps=" + "; ".join(group["unresolved_transitions"])
        lines.append(line)
    lines.extend(result["diagnostics"])
    return "\n".join(lines)


def _read_inputs(paths: Sequence[str]):
    if not paths:
        return [("<stdin>", sys.stdin.read())]
    inputs = []
    for path in paths:
        if path == "-":
            inputs.append(("<stdin>", sys.stdin.read()))
        else:
            file_path = Path(path)
            inputs.append((str(file_path), file_path.read_text(encoding="utf-8", errors="replace")))
    return inputs


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the full summary as JSON")
    parser.add_argument("paths", nargs="*", help="log paths, or - for stdin; defaults to stdin")
    args = parser.parse_args(argv)
    try:
        result = analyze_inputs(_read_inputs(args.paths))
    except OSError as exc:
        print(f"HookTrace read error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

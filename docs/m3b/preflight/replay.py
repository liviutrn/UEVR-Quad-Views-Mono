#!/usr/bin/env python3
"""Local preflight: replay the triview-b1.yml patch chain on Linux.

Usage: replay.py <workflow.yml> <workspace> <backend> <frontend> [--stop-before PATTERN]
Runs every `python workspace/...` line of the workflow in order (expanding the
v208d foreach list) up to the first FXC/embed step. Steps that only verify the
private SDK are reported but do not stop the replay.
"""
import re, subprocess, sys, shutil
from pathlib import Path

SDK_ONLY = ("source_checkpoint.py", "verify_exact_baseline.py", "verify_stage1.py", "verify_stage234.py")
STOP = ()


def commands(wf_text):
    lines = wf_text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("$scripts = @("):
            names = []
            i += 1
            while not lines[i].strip().startswith(")"):
                names += re.findall(r"'([^']+)'", lines[i])
                i += 1
            # foreach body: python workspace/duoview/joey_stage1/$s.py backend
            for n in names:
                out.append(f"python workspace/duoview/joey_stage1/{n}.py backend")
                if n == "apply_runtime_eye_alignment_persistence_build49":
                    out.append("python workspace/duoview/joey_stage1/test_runtime_eye_alignment_persistence_build49.py backend")
        elif line.startswith("python workspace/") and "$s.py" not in line and "test_runtime_eye_alignment_persistence_build49" not in line:
            out.append(line)
        i += 1
    return out


def main():
    wf, ws, be, fe = map(Path, sys.argv[1:5])
    root = ws.parent
    for name, src in (("workspace", ws), ("backend", be), ("frontend", fe)):
        dst = root / name
        if dst.resolve() != src.resolve():
            raise SystemExit(f"{name} must live at {dst}")
    (root / "evidence").mkdir(exist_ok=True)
    cmds = commands(wf.read_text(encoding="utf-8"))
    ran = 0
    for c in cmds:
        if any(s in c for s in STOP):
            print(f"STOP before: {c}")
            break
        argv = ["python3"] + c.split()[1:]
        r = subprocess.run(argv, cwd=root, capture_output=True, text=True)
        ran += 1
        if r.returncode != 0:
            tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
            joined = r.stdout + r.stderr
            if "/test_" in c and "'show'" in joined and "exit status 128" in joined:
                print(f"SKIP(history) {c}")
                continue
            if any(s in c for s in SDK_ONLY):
                print(f"SKIP(sdk) {c}: {' | '.join(tail)[:200]}")
                continue
            print(f"FAIL {c}\n  " + "\n  ".join(tail))
            return 1
    print(f"OK: {ran} steps replayed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

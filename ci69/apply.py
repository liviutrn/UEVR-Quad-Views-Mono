"""Apply the reviewed CI69 NGX-only source changes after the verified CI67 overlay.

The stable original source payload remains unchanged. The final delta rebases its
observer source context against the *actual CI67* production patch and incorporates
the fixed manual keying and unassigned-depth capture path. All payloads are SHA
checked, and git apply --check must pass without fuzzy or partial application.
"""
from pathlib import Path
import base64
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile

if len(sys.argv) != 2:
    raise SystemExit("usage: python workspace/ci69/apply.py BACKEND_ROOT")
base = Path(__file__).resolve().parent
backend = Path(sys.argv[1]).resolve()
old = gzip.decompress(base64.b64decode((base / "payload.b64").read_text().strip()))
if hashlib.sha256(old).hexdigest() != "fa97c28572dafe133611a725ae7f731ee935481b2eb08891e00ed8ba82b7e3e6":
    raise RuntimeError("Original CI69 source payload integrity mismatch")
delta = json.loads(gzip.decompress(base64.b64decode((base / "final_delta.b64").read_text().strip())))
lines = old.decode("utf-8").splitlines(keepends=True)
parts = []
cursor = 0
for tag, start, end, replacement in delta:
    if tag not in ("replace", "delete", "insert") or start < cursor or end > len(lines) or start > end:
        raise RuntimeError("CI69 rebase delta failed bounds validation")
    parts.extend(lines[cursor:start])
    parts.append(replacement)
    cursor = end
parts.extend(lines[cursor:])
patch = "".join(parts).encode("utf-8")
expected_sha256 = "e7aba90d7b9aebab355810b51be8894bce05fa084da8fc612f5c3f340109ad40"
if hashlib.sha256(patch).hexdigest() != expected_sha256:
    raise RuntimeError("CI69 fully rebased source payload integrity mismatch")

with tempfile.TemporaryDirectory() as temp:
    patchfile = Path(temp) / "ci69_final.patch"
    patchfile.write_bytes(patch)
    subprocess.run(["git", "apply", "--check", "--whitespace=nowarn", str(patchfile)],
                   cwd=backend, check=True)
    subprocess.run(["git", "apply", "--whitespace=nowarn", str(patchfile)],
                   cwd=backend, check=True)
print("CI69 DLSS manual source applied, source sha256:", expected_sha256, flush=True)

#!/usr/bin/env python3
"""Assemble the real DuoView source tree from the patch stack, without compiling.

Why this exists: the repo stores ~30 ordered patch scripts (stage1 ... ci78) that
the Windows workflow applies to Joey's UEVR. Nobody could read the code that
actually runs. This script replays exactly the same apply steps, in the same
order as .github/workflows/duoview-true-stereo-xr-v1.yml, and copies the final
DuoView-related files into an output folder you can read.

It needs only Python 3 and git (Linux, macOS or Windows). It does NOT need the
private UESDK: no apply step reads it. Shader bytecode is a placeholder unless
a real fxc.exe is on PATH, so the output is for reading and diffing, not for
building. The Windows workflow remains the only real build.

Usage:
  python tools/assemble_source.py OUTPUT_DIR [--work WORK_DIR] [--keep] [--review]

Output: OUTPUT_DIR/full/<path> holds every readable file as built. With --review
it also writes OUTPUT_DIR/new/<path> (files DuoView added) and
OUTPUT_DIR/changed/<path>.diff (what DuoView changed in Joey's UEVR files);
that smaller review layout is what the repo keeps in assembled_source/.

Keep the step list in sync with the workflow when a new ciNN layer is added.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UEVR = ("https://github.com/joeyhodge/UEVR", "5ac7edc207866569334175e4ed8a7517971547f6")
FRONTEND = ("https://github.com/joeyhodge/uevr-frontend", "60be4b0f9a646109fd9fdf448bacd41477234091")

FXC_STUB = """#!/usr/bin/env python3
import sys
a=sys.argv
open(a[a.index('/Fo')+1],'wb').write(b'DXBC'+b'\\0'*124)
"""


def run(args, cwd, env=None):
    print(">>", " ".join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], cwd=cwd, check=True, env=env)


def fetch(url, commit, dest):
    dest.mkdir(parents=True)
    run(["git", "init", "-q"], dest)
    run(["git", "remote", "add", "origin", url], dest)
    run(["git", "fetch", "-q", "--depth", "1", "origin", commit], dest)
    run(["git", "checkout", "-q", "FETCH_HEAD"], dest)


def unpack_tar_payload(job, folder, compressed_text):
    root = (job / "workspace").resolve()
    blob = lzma.decompress(base64.b64decode(compressed_text))
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if not member.isfile() or not parts or parts[0] != folder or ".." in parts:
                raise RuntimeError(f"unsafe {folder} payload path")
            target = root.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())


def normalize_to_contract(job, contract_rel, key):
    contract = json.loads((job / "workspace" / contract_rel).read_text(encoding="utf-8"))
    for relative, identity in contract.items():
        expected = identity.get(key)
        path = job / "backend" / relative
        if expected is None or not path.is_file():
            continue
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() == expected:
            continue
        lf = raw.replace(b"\r\n", b"\n")
        if hashlib.sha256(lf).hexdigest() != expected:
            raise RuntimeError(f"{contract_rel}: {relative} differs beyond line endings")
        path.write_bytes(lf)


def ci48_namespace_fix(job):
    for relative in ("src/mods/vr/d3d12/StockDibrDepth.hpp", "src/mods/vr/D3D12Component.hpp"):
        path = job / "backend" / relative
        raw = path.read_bytes()
        path.write_bytes(re.sub(rb"(?<!:)duoview::depthpin::", b"::duoview::depthpin::", raw))


def ci50_decode(job):
    root = job / "workspace" / "ci50"
    encoded = "".join((root / f"upgrade_p{i}.b64").read_text(encoding="utf-8").strip() for i in range(1, 5))
    (root / "apply.py").write_bytes(lzma.decompress(base64.b64decode(encoded, validate=True)))


def steps(job):
    """The workflow's apply order. Tests and compiles are intentionally skipped."""
    py = lambda *a: ("py", a)
    yield py("duoview/joey_stage1/apply_stage1.py", "backend", "frontend", "evidence")
    yield py("duoview/joey_stage1/apply_stage234.py", "backend", "frontend", "workspace/duoview")
    for name in ("apply_foreground_mpc_minimal", "apply_mono_hud_convergence", "apply_mono_alignment_build48",
                 "apply_runtime_eye_alignment_persistence_build49", "apply_xyz_head_scaling",
                 "apply_native_split_eye_165"):
        yield py(f"duoview/joey_stage1/{name}.py", "backend")
    for name in ("apply", "apply_provenance", "apply_runtime_fix", "apply_queue_fix", "apply_review_fix",
                 "apply_transaction_fix", "apply_adversarial_hooks", "apply_ui_retirement_fix"):
        yield py(f"stock_dibr/{name}.py", "backend")
    for name in ("integrate_r5_v1", "enhance_depth_bridge_v1", "add_manual_capture", "attach_depth_probe",
                 "enable_true_stereo_xr", "apply_gameplay_guards"):
        yield py(f"duoview/stereo/{name}.py", "backend")
    yield py("duoview/stereo/provenance_v1/apply_provenance_audit.py", "backend")
    yield py("duoview/stereo/provenance_v1/apply_capture_retention.py", "backend")
    yield py("duoview/stereo/apply_surface_renderer.py", "backend")
    yield ("fn", lambda: unpack_tar_payload(job, "ci48", (job / "workspace/ci48/payload.b64").read_text(encoding="ascii")))
    yield ("fn", lambda: normalize_to_contract(job, "ci48/hashes.json", "old_sha256"))
    yield py("ci48/apply.py", "backend")
    yield ("fn", lambda: normalize_to_contract(job, "ci48/hashes.json", "new_sha256"))
    yield py("ci48/windows_macro_compat.py", "backend")
    yield ("fn", lambda: ci48_namespace_fix(job))
    yield ("fn", lambda: unpack_tar_payload(job, "ci49", (job / "workspace/ci49/payload.b64").read_text().strip()))
    yield py("ci49/apply.py", "backend")
    yield ("fn", lambda: normalize_to_contract(job, "ci49/hashes.json", "new_sha256"))
    yield ("fn", lambda: ci50_decode(job))
    yield py("ci50/apply.py", "backend")
    yield py("ci50/fix_compilation.py", "backend")
    yield py("ci51/apply.py", "backend")
    yield py("ci51/build67_bridge.py", "backend")
    for layer in ("ci69", "ci70", "ci71", "ci72", "ci73", "ci74", "ci75", "ci76"):
        yield py(f"{layer}/apply.py", "backend")
    yield py("ci77/apply.py", "backend")
    # Later layers, in number order, whichever exist on this branch.
    for number in range(78, 100):
        if (job / f"workspace/ci{number}/apply.py").is_file():
            yield py(f"ci{number}/apply.py", "backend")


# Files worth reading. Everything else in backend is unchanged upstream UEVR.
READABLE = [
    "src/mods/VR.cpp", "src/mods/VR.hpp", "src/hooks/D3D12Hook.cpp",
    "src/mods/vr/D3D12Component.cpp", "src/mods/vr/D3D12Component.hpp",
    "src/mods/vr/FFakeStereoRenderingHook.cpp",
]
READABLE_GLOBS = ["src/mods/vr/DuoView*", "src/mods/vr/SurfaceGeometry.hpp", "src/mods/vr/PSVR2*",
                  "src/mods/vr/d3d12/*"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path)
    parser.add_argument("--work", type=Path, help="work folder (default: a temporary folder)")
    parser.add_argument("--keep", action="store_true", help="keep the work folder")
    parser.add_argument("--review", action="store_true", help="also write new/ and changed/*.diff")
    args = parser.parse_args()

    work = args.work or Path(tempfile.mkdtemp(prefix="duoview-assemble-"))
    job = work.resolve()
    if job.exists() and any(job.iterdir()):
        raise SystemExit(f"work folder {job} must be empty")
    job.mkdir(parents=True, exist_ok=True)
    try:
        (job / "evidence").mkdir()
        fetch(*UEVR, job / "backend")
        fetch(*FRONTEND, job / "frontend")
        (job / "workspace").mkdir()
        archive = subprocess.run(["git", "archive", "HEAD"], cwd=REPO, check=True, capture_output=True).stdout
        tarfile.open(fileobj=io.BytesIO(archive)).extractall(job / "workspace")
        # Uncommitted ciNN folders (work in progress) are copied over the archive.
        for folder in REPO.glob("ci[0-9]*"):
            shutil.copytree(folder, job / "workspace" / folder.name, dirs_exist_ok=True)
        # ci69 uses `git apply`, which needs the backend to be a git work tree (it is).
        env = dict(os.environ)
        # CI75 stamps the build commit into the recorder; later layers expect a
        # 40-hex commit there, so give local runs a fixed placeholder commit.
        env.setdefault("GITHUB_SHA", "0" * 40)
        stubbed = not (shutil.which("fxc") or shutil.which("fxc.exe"))
        if stubbed:
            stub = job / "bin"
            stub.mkdir()
            (stub / "fxc").write_text(FXC_STUB)
            (stub / "fxc").chmod(0o755)
            env["PATH"] = str(stub) + os.pathsep + env["PATH"]
            os.environ["PATH"] = env["PATH"]
        for kind, payload in steps(job):
            if kind == "fn":
                payload()
            else:
                run([sys.executable, f"workspace/{payload[0]}", *payload[1:]], job, env)
        out = args.output.resolve()
        out.mkdir(parents=True, exist_ok=True)
        backend = job / "backend"
        chosen = {backend / r for r in READABLE}
        for pattern in READABLE_GLOBS:
            chosen.update(backend.glob(pattern))
        files = sorted(p for p in chosen if p.is_file())
        for path in files:
            target = out / "full" / path.relative_to(backend)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        if args.review:
            for path in files:
                rel = path.relative_to(backend).as_posix()
                upstream = subprocess.run(["git", "cat-file", "-e", f"{UEVR[1]}:{rel}"], cwd=backend,
                                          stderr=subprocess.DEVNULL)
                if upstream.returncode != 0:
                    if rel.endswith("DuoViewShaderSource.hpp") and stubbed:
                        continue  # placeholder bytecode only; not worth keeping
                    target = out / "new" / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                    continue
                diff = subprocess.run(["git", "diff", "--no-color", "--ignore-cr-at-eol", UEVR[1], "--", rel],
                                      cwd=backend, check=True, capture_output=True).stdout
                if diff:
                    target = out / "changed" / (rel + ".diff")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(diff)
        print(f"Assembled {len(files)} readable source files into {out}")
    finally:
        if not args.keep and not args.work:
            shutil.rmtree(job, ignore_errors=True)


if __name__ == "__main__":
    main()

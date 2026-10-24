#!/usr/bin/env python3
"""Install reviewed manual DIBR units into the exact pinned Joey backend.

This is an intentionally fail-closed production integration stage.  It never
relaxes the existing stable source verifier, builds generated shaders offline,
and only installs source that belongs to the approved feature branch.
The subsequent verifier must still prove *live callsites* before packaging.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    original = path.read_text(encoding="utf-8-sig")
    occurrences = original.count(old)
    if occurrences != 1:
        raise RuntimeError(f"{label}: expected one source anchor, found {occurrences}")
    path.write_text(original.replace(old, new, 1), encoding="utf-8", newline="")


def install_file(original: Path, dest: Path) -> None:
    if not original.is_file():
        raise RuntimeError(f"Reviewed DIBR source missing: {original}")
    if dest.exists():
        raise RuntimeError(f"Refusing to overwrite existing backend source: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(original, dest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", type=Path)
    parser.add_argument("frontend", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()

    source = args.source
    backend = args.backend
    if not (backend / "src/mods/vr/DuoViewD3D12.hpp").is_file():
        raise RuntimeError("Accepted Stage 2-4 DuoView producer must be patched first")
    stable_mono = (backend / "src/mods/vr/DuoViewD3D12.hpp").read_text(encoding="utf-8")
    if "ID3D12Resource* mono_output() const" not in stable_mono:
        raise RuntimeError("DIBR requires a properly owned and fenced Mono source")
    if not (source / "dibr/manual_dibr_warp_test.cpp").is_file():
        raise RuntimeError("Required production DX12 WARP source missing")

    # The WARP acceptance job compiles these same exact headers. We install
    # them without rewriting their content so the final verifier can compare
    # their bytes, and source-level regressions remain detectable.
    modules = {
        "dibr/ManualDibrContract.hpp": "dibr/ManualDibrContract.hpp",
        "dibr/ManualDibrPreview.hpp": "dibr/ManualDibrPreview.hpp",
        "dibr/ManualDibrProjection.hpp": "dibr/ManualDibrProjection.hpp",
        "dibr/ManualDibrUi.hpp": "dibr/ManualDibrUi.hpp",
        "dibr/DuoViewDibrD3D12.hpp": "dibr/DuoViewDibrD3D12.hpp",
        "dibr/ManualDibrCapture.hpp": "d3d12/ManualDibrCapture.hpp",
    }
    installed = []
    for relative_src, relative_backend in modules.items():
        dest = backend / "src/mods/vr" / relative_backend
        install_file(source / relative_src, dest)
        installed.append(str(dest.relative_to(backend)))

    # Compile and embed the production DIBR shaders on the Windows CI runner.
    # This is *not* a runtime D3DCompile call.
    embed = source / "embed_shader.py"
    target = backend / "src/mods/vr/DuoViewShaderSource.hpp"
    subprocess.run([sys.executable, str(embed), str(target), "--include-dibr"],
                   check=True)
    shaders = target.read_text(encoding="utf-8")
    if "dibr_vertex_shader_bytecode[]" not in shaders or \
       "dibr_pixel_shader_bytecode[]" not in shaders:
        raise RuntimeError("DIBR bytecode absent after offline HLSL compilation")

    # Only the already accepted DuoView paths are installed here. The separate
    # production callsites / GPU fence hooks are still mandatory and are
    # rejected by verify_manual_dibr.py until actually implemented.
    (args.evidence / "manual_dibr_modules_installed.txt").write_text(
        "\n".join(installed) + "\n", encoding="utf-8"
    )
    print("Manual DIBR shader and reviewed sources installed. Production integration verification remains mandatory.")


if __name__ == "__main__":
    main()

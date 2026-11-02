#!/usr/bin/env python3
"""Compile TriViewComposite.hlsl to DXBC with the Windows SDK fxc (CI) and embed it as a C++ header.
Same approach as duoview/embed_shader.py: no shader compiler ever runs inside the game."""
from pathlib import Path
import argparse
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from embed_shader import fxc_executable, format_array  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent / "TriViewComposite.hlsl"
    fxc = fxc_executable()
    sections = []
    with tempfile.TemporaryDirectory(prefix="triview-shader-") as tmp:
        for entry, profile, name in (("VSMain", "vs_5_0", "triview_vertex_shader_bytecode"),
                                     ("PSMain", "ps_5_0", "triview_pixel_shader_bytecode")):
            output = Path(tmp) / (name + ".cso")
            result = subprocess.run([str(fxc), "/nologo", "/O3", "/T", profile, "/E", entry,
                                     "/Fo", str(output), str(source)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f"Tri-View shader {entry} failed: {result.stdout}\n{result.stderr}")
            sections.append(format_array(name, output.read_bytes()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("#pragma once\n// TriViewComposite.hlsl precompiled by fxc in CI.\n"
                           "namespace uevr::triview::dx12 {\n" + "".join(sections) + "}\n",
                           encoding="utf-8", newline="")
    print("Tri-View DXBC shaders compiled offline: " + str(args.output))


if __name__ == "__main__":
    main()

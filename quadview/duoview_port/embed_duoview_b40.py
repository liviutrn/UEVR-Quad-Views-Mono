#!/usr/bin/env python3
"""DuoView B40: deterministic offline DXBC for native/fallback PS + seam CS.
All five shaders compile in CI via Windows SDK fxc.exe, NEVER in OpenXR copy.
The v208d source tree remains pinned and unmodified; use the CI working tree.
"""
from pathlib import Path
import argparse
import subprocess
import tempfile
import sys

def main():
    a=argparse.ArgumentParser()
    a.add_argument("source", type=Path)
    a.add_argument("output", type=Path)
    args=a.parse_args()
    sys.path.insert(0,str(args.source))
    from embed_shader import fxc_executable, format_array
    fxc=fxc_executable()
    results=[]
    shaders=(
        ("VSMain","vs_5_0","vertex_shader_bytecode","DuoViewCompositeRaster.hlsl",False),
        ("PSMain","ps_5_0","pixel_shader_bytecode","DuoViewCompositeRaster.hlsl",False),
        ("PSNativeMain","ps_5_0","native_pixel_shader_bytecode","DuoViewNativeCompositeRaster.hlsl",False),
        ("CSMonoB40","cs_5_0","gather_b40_compute_bytecode","DuoViewCompositeRaster.hlsl",True),
        ("CSMonoB40","cs_5_0","native_b40_compute_bytecode","DuoViewNativeCompositeRaster.hlsl",True),
    )
    with tempfile.TemporaryDirectory(prefix="duoview-b40-") as temp:
        for entry,profile,name,source,is_compute in shaders:
            output=Path(temp)/(name+".cso")
            cmd=[str(fxc),"/nologo","/O3","/T",profile,"/E",entry,
                 "/I",str(args.source),"/Fo",str(output)]
            if is_compute: cmd+=["/D","DUOVIEW_B40_COMPUTE=1"]
            cmd+=[str(args.source/source)]
            run=subprocess.run(cmd,capture_output=True,text=True)
            if run.returncode:
                raise RuntimeError(f"FXC {name} failed: {run.stdout}\n{run.stderr}")
            results.append(format_array(name,output.read_bytes()))
            print(f"DuoView B40 fxc {entry}: {name} PASS")
    args.output.write_text(
        "#pragma once\n// CI precompiled DuoView Mono PS/CS shader set.\n"
        "namespace uevr::duoview::dx12 {\n"+"".join(results)+"}\n",
        encoding="utf-8",newline="")
    print("DuoView B40 native & gathered DXBC complete")
if __name__=="__main__":
    main()

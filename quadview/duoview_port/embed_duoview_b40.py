#!/usr/bin/env python3
"""DuoView B40: deterministic offline DXBC for native/fallback PS + seam CS.
All five shaders compile in CI via Windows SDK fxc.exe, NEVER in OpenXR copy.
The v208d source tree remains pinned and unmodified; use the CI working tree.
"""
from pathlib import Path
import argparse
import re
import subprocess
import tempfile
import sys

def main():
    a=argparse.ArgumentParser()
    a.add_argument("source", type=Path)
    a.add_argument("output", type=Path)
    a.add_argument("--m1", action="store_true")
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
    if args.m1:
        # Stage 2–4 already compiled the exact pinned v208d shader before overlays.
        original = args.output.read_text(encoding="utf-8")
        legacy = re.search(r"inline constexpr unsigned char pixel_shader_bytecode\[\] = \{.*?\};",
                           original, re.DOTALL)
        if legacy is None:
            raise RuntimeError("Pinned v208d packed raster bytecode missing")
        results.append(legacy.group().replace("pixel_shader_bytecode", "legacy_packed_pixel_bytecode", 1) + "\n")
        # The two original WARP fixtures both remove the device in the
        # independent atlas shader. Reuse the Native entry and only specialize
        # source coordinates for the packed texture.
        shaders=(
            shaders[0],
            ("PSNativeMain","ps_5_0","pixel_shader_bytecode","DuoViewNativeCompositeRaster.hlsl",("DUOVIEW_ATLAS_GATHER",)),
            shaders[2],
            ("CSMonoB40","cs_5_0","gather_b40_compute_bytecode","DuoViewNativeCompositeRaster.hlsl",
             ("DUOVIEW_ATLAS_GATHER","DUOVIEW_B40_COMPUTE")),
            shaders[4],
            ("PSNativeMain","ps_5_0","m1_raster_bytecode","DuoViewNativeCompositeRaster.hlsl",("DUOVIEW_M1_RASTER",)),
            ("CSConditionM1","cs_5_0","m1_condition_bytecode","DuoViewM1Stereo.hlsl",("DUOVIEW_M1_CONDITION",)),
            ("CSConditionM1Vertical","cs_5_0","m24_vertical_bytecode","DuoViewM1Stereo.hlsl",("DUOVIEW_M1_CONDITION",)),
        )
    with tempfile.TemporaryDirectory(prefix="duoview-b40-") as temp:
        for entry,profile,name,source,define in shaders:
            output=Path(temp)/(name+".cso")
            cmd=[str(fxc),"/nologo","/O3","/T",profile,"/E",entry,
                 "/I",str(args.source),"/Fo",str(output)]
            for macro in (("DUOVIEW_B40_COMPUTE",) if define is True else define or ()):
                cmd+=["/D",macro+"=1"]
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

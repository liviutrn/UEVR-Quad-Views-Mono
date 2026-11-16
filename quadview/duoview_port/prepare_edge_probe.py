#!/usr/bin/env python3
"""Make a fixture-only header copy; NEVER replace the shipping DXBC header."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

PROBE = r'''
    // TEST-ONLY readback compiled into a separate fixture header copy.
    // Markers 17/18/19 are all effective V2 selectors, with retired fill OFF.
    if (M8Distance.w > 16.5 && M8Distance.w < 19.5) {
        const uint eye = i.pos.x >= OutputSize.x ? 1u : 0u;
        if (M8Distance.w > 18.5) {
            const uint2 q = uint2(round(saturate(sourceUv) * 65535.0));
            return float4(q.x & 255u, q.x >> 8u, q.y & 255u, q.y >> 8u) / 255.0;
        }
        float value = M1ReadConditionedEye(sourceUv, eye);
        if (M8Distance.w < 17.5) {
            const uint column = uint(outputPixel.x) % 16u;
            if(column==0u) value=M8Effects.x;
            if(column==1u) value=M8Effects.y;
            if(column==2u) value=M8Distance.x;
            if(column==3u) value=M8Distance.y;
            if(column==4u) value=M8Distance.z;
            if(column==5u) value=M8Distance.w;
            if(column==6u) value=M1Depth.w;
            if(column==7u) value=M1Filter.x;
            if(column==8u) value=float(M1Grid.x);
            if(column==9u) value=float(M4Grid.x);
            if(column==10u) value=M4Flags.x;
            if(column==11u) value=M1Eye[eye];
            if(column==12u) value=M4Flags.y;
            if(column==13u) value=M2Crop.x;
            if(column==14u) value=M2Crop.z;
            if(column==15u) value=M1Filter.y;
        }
        const uint q=asuint(value);
        return float4(q & 255u, (q >> 8u) & 255u, (q >> 16u) & 255u, q >> 24u) / 255.0;
    }
'''

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--shaders', type=Path, required=True)
    ap.add_argument('--backend', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a=ap.parse_args()
    if a.out.exists():
        raise RuntimeError('Probe destination must not exist; never merge stale headers')
    original=a.backend/'src/mods/vr/DuoViewShaderSource.hpp'
    original_hash=sha(original)
    # Keep shader sources as evidence, without altering the generated originals.
    shutil.copytree(a.shaders,a.out/'shaders')
    shutil.copytree(a.backend/'src/mods/vr',a.out/'include')
    raster=a.out/'shaders/DuoViewNativeCompositeRaster.hlsl'
    text=raster.read_text(encoding='utf-8')
    anchor='    const float2 fullUv=DuoSourceToLogicalUv(sourceUv);'
    if text.count(anchor)!=1:
        raise RuntimeError('Exact fitted-source readback anchor drift')
    raster.write_text(text.replace(anchor,anchor+PROBE),encoding='utf-8',newline='\n')
    sys.path.insert(0,str(a.shaders))
    from embed_shader import fxc_executable, format_array
    output=a.out/'probe.cso'
    subprocess.run([str(fxc_executable()),'/nologo','/O3','/T','ps_5_0',
                    '/E','PSNativeMain','/D','DUOVIEW_M1_RASTER=1',
                    '/I',str(raster.parent),'/Fo',str(output),str(raster)],check=True)
    header=a.out/'include/DuoViewShaderSource.hpp'
    src=header.read_text(encoding='utf-8')
    pattern=r'inline constexpr unsigned char m1_raster_bytecode\[\] = \{.*?\};'
    replacement=format_array('m1_raster_bytecode',output.read_bytes())
    src,n=re.subn(pattern,lambda _:replacement,src,flags=re.S)
    if n!=1:
        raise RuntimeError('Exact m1 raster bytecode array missing')
    header.write_text(src,encoding='utf-8',newline='\n')
    if sha(original)!=original_hash:
        raise RuntimeError('Shipping shader header was modified')
    (a.out/'identity.json').write_text(json.dumps({
        'purpose':'test-only UV/conditioned-depth/effective-constant readback',
        'shipping_header_sha256':original_hash,'probe_header_sha256':sha(header),
        'probe_dxbc_sha256':sha(output),'shipping_unchanged':True,
        'uv_quantization_source_pixels_max':[384/65535/2,216/65535/2],
        'changes':'Only m1_raster_bytecode differs in copied header; all conditioning DXBC unchanged'
    },indent=2),encoding='utf-8')
    print('TEST-ONLY probe prepared; shipping header unchanged',original_hash)

if __name__=='__main__':
    main()

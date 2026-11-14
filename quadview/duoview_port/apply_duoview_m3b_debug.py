#!/usr/bin/env python3
"""M3b P7: debug and distance-fade reads must use the displayed eye slice."""
import sys
from pathlib import Path
from apply_duoview_b40_pipeline import patch

def main():
    if len(sys.argv)!=3: raise SystemExit("Usage: apply_duoview_m3b_debug.py <backend> <shader-dir>")
    sh=Path(sys.argv[2])/"DuoViewNativeCompositeRaster.hlsl"
    patch(sh,[
      ("per-eye debug selector",
       "        const float2 pos=outputUv;\n        const float mid=M1ReadConditioned(pos);",
       "        const float2 pos=outputUv;\n        const uint debugEye=i.pos.x>=OutputSize.x ? 1u : 0u;\n        const float mid=M1ReadConditionedEye(pos,debugEye);"),
      ("per-eye debug left sample",
       "const float left=M1ReadConditioned(pos-float2(delta.x,0));",
       "const float left=M1ReadConditionedEye(pos-float2(delta.x,0),debugEye);"),
      ("per-eye debug right sample",
       "const float right=M1ReadConditioned(pos+float2(delta.x,0));",
       "const float right=M1ReadConditionedEye(pos+float2(delta.x,0),debugEye);"),
      ("per-eye debug upper sample",
       "const float up=M1ReadConditioned(pos-float2(0,delta.y));",
       "const float up=M1ReadConditionedEye(pos-float2(0,delta.y),debugEye);"),
      ("per-eye debug lower sample",
       "const float down=M1ReadConditioned(pos+float2(0,delta.y));",
       "const float down=M1ReadConditionedEye(pos+float2(0,delta.y),debugEye);"),
      ("per-eye distance-based sharpen",
       "const float D=M1ReadConditioned(fullUv);",
       "const float D=M1ReadConditionedEye(fullUv,rightEye ? 1u : 0u);"),
    ])
    print("M3b P7 per-eye debug and distance-fade depth reads installed")

if __name__=="__main__":main()

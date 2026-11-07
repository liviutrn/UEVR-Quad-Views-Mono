#!/usr/bin/env python3
"""Keep B23's exact four-sample warp, allowing only the pinned B29 ALU port."""
from pathlib import Path
import subprocess
import sys

BASE = "11ae53daf224bd04137177ec900e96e619845488"

def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_triview_b23_four_samples.py WORKSPACE")
    root = Path(sys.argv[1]).resolve()
    original = subprocess.check_output(
        ["git", "-C", str(root), "show", f"{BASE}:quadview/QuadViewComposite.hlsl"],
        text=True)
    actual = (root / "quadview" / "QuadViewComposite.hlsl").read_text(encoding="utf-8")
    assert original.count("const float ds = sMax / 24.0;") == 1
    assert original.count("i <= 24u && !found") == 1
    expected = original.replace("const float ds = sMax / 24.0;",
                                "const float ds = sMax / 3.0;")
    expected = expected.replace("i <= 24u && !found",
                                "i <= 3u && !found")
    # B29 ports only B27's normalization/homography ALU optimizations. Preserve
    # an exact full-file allowlist AND compare the depth algorithm separately.
    optimized = subprocess.check_output(
        ["git", "-C", str(root), "show",
         "b024570edbbdc8852aa7e7e2e508235c228ca245:quadview/QuadViewComposite.hlsl"], text=True)
    restored=actual
    start=restored.index('// Screenshot-fitted brightness-only compensation.')
    end=restored.index('float4 ScenePixel(',start)
    restored=restored[:start]+restored[end:]
    restored=restored.replace('    float4 FocusLift;    // enabled, overall brightness, corner gain minus one, onset r^2\n','')
    restored=restored.replace('    float4 FocusProfile; // falloff exponent, anti-vignette strength, reserved\n','')
    restored=restored.replace('    if (debugMode == 0u) focus.rgb=CorrectFocusColor(focus.rgb,focusUv);\n','')
    assert restored == optimized, 'Unexpected rendering changes outside isolated focus compensation'
    def warp(s):
        return s.split("float2 WarpContextUv(",1)[1].split("// Explicit SM5 resource selection",1)[0]
    assert warp(actual) == warp(expected), "B23 depth geometry or four-sample search changed"
    assert actual.split("float4 PSMain(",1)[1] == expected.split("float4 PSMain(",1)[1], "Output encoding changed"
    assert actual.count("InverseDepthAt(c)") == 1
    print("B23 depth/output contracts: PASS (4 samples; exact B23 or pinned B27 ALU-only shader)")

if __name__ == "__main__":
    main()

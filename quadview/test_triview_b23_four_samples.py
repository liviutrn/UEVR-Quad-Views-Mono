#!/usr/bin/env python3
"""Keep B23 depth/output math and B29 sampling/sharpening intact under B30."""
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
    # B30 adds seam analysis/composition around the unchanged source helpers.
    # Protect the complete depth algorithm, sampling and sharpening functions
    # instead of incorrectly demanding whole-file identity with old shaders.
    optimized = subprocess.check_output(
        ["git", "-C", str(root), "show",
         "b024570edbbdc8852aa7e7e2e508235c228ca245:quadview/QuadViewComposite.hlsl"], text=True)
    def warp(s):
        return s.split("float2 WarpContextUv(",1)[1].split("// Explicit SM5 resource selection",1)[0]
    assert warp(actual) == warp(expected), "B23 depth geometry or four-sample search changed"
    assert actual.split("float4 PSMain(",1)[1].split("#ifdef SEAM_COMPUTE",1)[0].rstrip() == expected.split("float4 PSMain(",1)[1].rstrip(), "Output encoding changed"
    def function(s, start):
        return s.split(start,1)[1].split('\n}',1)[0]
    for name in ('float2 SourceSize(', 'float2 AtlasUvKnownSize(', 'float2 AtlasUv(', 'float2 ContextUv(',
                 'float4 ReadSource(', 'float FocusWeight(', 'float3 GlamDecode(', 'float3 GlamEncode(',
                 'float3 ReadFocus(', 'float3 GlamSharpenFocus(', 'float4 ReadContext('):
        assert function(actual,name)==function(optimized,name), 'Changed protected B29 source helper: '+name
    assert actual.count("InverseDepthAt(c)") == 1
    # B43: extra-wide ring = protected sharpen body with radius/guard parameters,
    # used only in ScenePixel (never in seam analysis / DisplayFocus).
    ref = function(actual, 'float3 GlamSharpenFocus(').split('    const float radius = 1.4;\n',1)[1]
    ref = ref.replace('float2(-3.5, 0.0) : float2(0.0, 3.5)', 'float2(-guard, 0.0) : float2(0.0, guard)')
    ref = ref.replace('float2( 3.5, 0.0) : float2(0.0,-3.5)', 'float2( guard, 0.0) : float2(0.0,-guard)')
    ref = ref.replace('    return GlamEncode(c + change);', '    return change;')
    ring = function(actual, 'float3 GlamSharpenRingChange(').split(') {\n',1)[1]
    assert ring == ref, 'B43 ring differs from the protected sharpen body'
    assert actual.count('GlamSharpenRingChange(') == 2, 'B43 ring must be used exactly once (ScenePixel)'
    scene = function(actual, 'float4 ScenePixel(')
    assert 'GlamSharpenRingChange(2u + eye' in scene and "(eye == 0u ? 8u : 16u)" in scene
    assert 'GlamSharpenRingChange' not in function(actual, 'float4 DisplayFocus(')
    print("B23/B29 protected depth, sampling, sharpening and output contracts: PASS; B30 seam code tested separately")

if __name__ == "__main__":
    main()

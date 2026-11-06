#!/usr/bin/env python3
"""Verify B23 differs from the vetted B22 HLSL by only two march-count literals."""
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
    assert actual == expected, "Unexpected HLSL edits beyond two sample-count literals"
    assert actual.count("InverseDepthAt(c)") == 1
    print("B23 source diff: PASS (4 depth samples; only 2 B22 HLSL literals changed)")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""B22 shader-only optimization invariants. GPU WARP tests separately verify behavior."""
from pathlib import Path
import subprocess
import sys

BASE = "89eff76791010bc1de477bdf82cd4eff9fb42896"
def require(condition, message):
    if not condition:
        raise AssertionError(message)

def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    old = subprocess.check_output(
        ["git", "-C", str(root), "show", f"{BASE}:quadview/QuadViewComposite.hlsl"],
        encoding="utf-8")
    new = (root / "quadview" / "QuadViewComposite.hlsl").read_text(encoding="utf-8")
    # The depth loop and final transfer-function logic are explicitly immutable.
    def segment(text, start, end):
        return text.split(start, 1)[1].split(end, 1)[0]
    require(segment(old, "float2 WarpContextUv(", "// Explicit SM5 resource selection") ==
            segment(new, "float2 WarpContextUv(", "// Explicit SM5 resource selection"),
            "B21 depth ray tracing was modified")
    require(old.split("float4 PSMain(", 1)[1] == new.split("float4 PSMain(", 1)[1],
            "B21 final output modified")
    require(new.count("AtlasUvKnownSize(") == 5, "Unexpected size-helper call sites")
    require(new.count("ReadFocus(") == 7, "Changed number of sharpening taps")
    require("const float2 sourceSize = SourceSize(contextSource);" in new,
            "15-tap disocclusion lookup did not hoist texture dimensions")
    require("const float2 focusSourceSize = SourceSize(2u + eye);" in new,
            "Fovea dimensions not shared across taps")
    require("GlamSharpenFocus(2u + eye, focusRect, crop, eyeUv, focus.rgb, eyeStrength, eyeMaxChange, focusSourceSize)" in new,
            "Fovea sharpening does not receive the same cached texture dimensions")
    require(new.count("const float ds = sMax / 24.0;") == 1,
            "Depth sample count changed")
    print("B22 shader-only safety invariants: pass; original 24-step depth geometry preserved")

if __name__ == "__main__":
    main()

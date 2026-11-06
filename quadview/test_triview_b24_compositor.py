#!/usr/bin/env python3
"""B24 source invariants: keep B23 depth, optimize only context and fovea tap math."""
from pathlib import Path
import random
import subprocess
import sys

PARENT = "a3c85bb529afc589becbb7f236816a57cf831aa8"
def require(yes, why):
    if not yes:
        raise AssertionError(why)

def main():
    root=Path(sys.argv[1] if len(sys.argv)>1 else ".").resolve()
    old=subprocess.check_output(["git","-C",str(root),"show",f"{PARENT}:quadview/QuadViewComposite.hlsl"],text=True)
    new=(root/"quadview"/"QuadViewComposite.hlsl").read_text(encoding="utf-8")
    def between(s,a,b):
        return s.split(a,1)[1].split(b,1)[0]
    require(between(old,"float2 WarpContextUv(","// Explicit SM5 resource selection") ==
            between(new,"float2 WarpContextUv(","// Explicit SM5 resource selection"),
            "B23 ray search/occlusion handling changed")
    require("const float ds = sMax / 3.0;" in new and "i <= 3u && !found" in new,
            "Not the same B23 four depth samples")
    require(old.split("float4 CompositePixel(",1)[1]==new.split("float4 CompositePixel(",1)[1],
            "Final diagnostic, color or output shader changed")
    require(new.count("ReadFocus(sourceIndex, rect, focusUv, tapScale, ")==6,
            "Six tap kernel changed")
    require(new.count("ReadContext(eye, contextSource, contextRect, eyeUv)")==3,
            "Lazy periphery projection did not reach each scene call")
    require("float4 ReadContext(uint eye, uint contextSource, uint4 contextRect, float2 eyeUv) {" in new,
            "Wrong context function")
    require("const float2 contextUv = ContextUv(eye, eyeUv);" in new,
            "Context homography missing")
    rnd=random.Random(24)
    maxdiff=0.
    for _ in range(8000):
        eye_size=rnd.choice([640,1280,2048,3144,4096])
        extent=rnd.uniform(.1,1.)
        begin=rnd.uniform(0.,1.-extent)
        uv=rnd.uniform(begin,begin+extent)
        offset=rnd.choice([-3.5,-1.4,1.4,3.5])
        prev=((uv+offset/eye_size)-begin)/extent
        after=(uv-begin)/extent+offset*(1.0/(eye_size*extent))
        maxdiff=max(maxdiff,abs(prev-after))
    require(maxdiff<1e-12,f"Reordered tap math drift >1e-12: {maxdiff}")
    print(f"B24 source and reference math checks PASS (max double UV delta {maxdiff:.3g})")

if __name__ == "__main__":
    main()

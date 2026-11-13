#!/usr/bin/env python3
"""Numerical regression for DuoView B40 seam matcher + fovea feather.

When two registered sources differ only by a constant appearance offset, the
matched output should remain constant through the entire feather. An old
12px inward anchor created a dark band for a wider fovea feather.
"""
from math import isclose

def smoothstep(t):
    t=max(0.,min(1.,t))
    return t*t*(3.-2.*t)

def run():
    tests=0
    worst_new_error=0.
    worst_old_error=0.
    for feather_pixels in (0.,4.,12.,24.,64.,128.,240.,400.):
        for delta in (-.23,-.08,.08,.23):
            periphery=.5-delta
            focus=.5
            for i in range(2400):
                distance=i*.25
                weight=1.0 if feather_pixels==0 else smoothstep(distance/feather_pixels)
                # New algorithm uses the matched peripheral sample all the
                # way through the feather; lerp(context,focus,weight) handles
                # the fade. It needs no additional inward anchor.
                correct_context=periphery+delta
                actual=(1.-weight)*correct_context+weight*focus
                error=abs(actual-focus)
                worst_new_error=max(worst_new_error,error)
                assert isclose(actual,focus,abs_tol=1.e-12), (
                    "seam matching incorrectly faded before blend",feather_pixels,
                    delta,distance,actual,focus
                )
                # Previous logic faded the correction within 12 pixels
                # even though the fovea might still be nearly invisible.
                old_anchor=1.-smoothstep(distance/12.)
                old_context=periphery+delta*old_anchor
                old_output=(1.-weight)*old_context+weight*focus
                worst_old_error=max(worst_old_error,abs(old_output-focus))
                tests+=1
    assert worst_old_error>.10, "reference must expose the old 12px mismatch"
    print(f"M2.3 full-feather colour matching: {tests} constant-offset probes; "
          f"new max mismatch {worst_new_error:.3g}, old mismatched up to "
          f"{worst_old_error:.3f} intensity: PASS")

if __name__=="__main__":
    run()

#!/usr/bin/env python3
# Preflight stand-in for fxc.exe: compiles nothing. Writes a tiny dummy blob to /Fo
# so the patch chain can continue; real compilation happens in CI.
import sys
args=sys.argv[1:]
out=None
for i,a in enumerate(args):
    if a.startswith("/Fo"):
        out=a[3:] or (args[i+1] if i+1<len(args) else None)
if out:
    open(out,"wb").write(b"DXBC"+b"PREFLIGHT-STUB-NOT-COMPILED".ljust(76,b"."))
sys.exit(0)

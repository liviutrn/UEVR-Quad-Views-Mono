"""Verified MSVC compatibility fix for a Windows.h max macro collision.

Run only after the exact Build48 source contract and post-patch verification.
"""
from pathlib import Path
import hashlib
import sys

root=Path(sys.argv[1]).resolve()
path=root/"src/mods/vr/d3d12/ObservedPassCounter.hpp"
expected_before="80568470a2e44b1b5c62386033bf4f3f0b191c656d598bd221da94c699f55ef4"
expected_after="300a0a2ba0c5c372f44516898e159c0387f5f39c5477200211c7a4aa0e7e0e9a"
source=path.read_bytes()
digest=lambda content:hashlib.sha256(content).hexdigest()
if digest(source)!=expected_before:
    raise SystemExit("ObservedPassCounter pre-fix SHA mismatch: "+digest(source))
old=b"std::numeric_limits<std::uint32_t>::max()"
new=b"(std::numeric_limits<std::uint32_t>::max)()"
if source.count(old)!=1:
    raise SystemExit("Expected exactly one macro-sensitive max expression")
corrected=source.replace(old,new)
if digest(corrected)!=expected_after:
    raise SystemExit("ObservedPassCounter corrected SHA mismatch: "+digest(corrected))
path.write_bytes(corrected)
print("PASS: MSVC max-macro protection in observed-depth pass counter, hash verified")

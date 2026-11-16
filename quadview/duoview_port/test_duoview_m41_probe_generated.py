#!/usr/bin/env python3
"""Test instrumented generated full backend after applying the M4.1 probe."""
import sys,tempfile,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from apply_m41_metadata_probe import apply,transform,DECLARATIONS,TAKE_STATS,LOG

def main(backend):
    base=Path(backend)/"src/mods/vr"
    names=("QuadViewNgxDepth.hpp","D3D12Component.cpp")
    a,b=[(base/n).read_text(encoding="utf-8") for n in names]
    assert a.count("m41_probe_stats() const noexcept")==1
    assert a.count("++m41_probe_reason_[0];")==1
    assert a.count("m41_probe_lookup_ready_")==3
    assert "++m41_probe_marker_coarse_epoch_" in a and "++m41_probe_fine_coarse_epoch_" in a
    assert b.count("[DuoView][M41-Probe]")==2
    assert b.index("[DuoView][M41-Probe]") < b.index("} else if (require_fine && !fine_pair.fine) {")
    assert "m41_close_capture_interval(" in a
    assert "duo_command.deferred_roles == 3u" in (base/"FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
    for s in ("CopyResource(","CopyTextureRegion(","Map(","Readback"):
        assert s not in DECLARATIONS+TAKE_STATS+LOG
    # Reject duplicate patches atomically, with neither output modified.
    with tempfile.TemporaryDirectory() as root:
        dest=Path(root)/"src/mods/vr";dest.mkdir(parents=True)
        for n in names:shutil.copyfile(base/n,dest/n)
        before=[(dest/n).read_bytes() for n in names]
        try:apply(root)
        except RuntimeError:pass
        else:raise AssertionError("reapplying probe must fail closed")
        assert before==[(dest/n).read_bytes() for n in names]
    try:transform("","")
    except RuntimeError:pass
    else:raise AssertionError("invalid source accepted")
    print("PASS: generated M41 probe placement, no readbacks, replay & drift denied")

if __name__=="__main__":
    if len(sys.argv)!=2:raise SystemExit("usage: test_duoview_m41_probe_generated.py <backend>")
    main(sys.argv[1])

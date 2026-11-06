#!/usr/bin/env python3
"""Validate coherent NGX dimensions in the final generated production backend."""
from pathlib import Path
import sys
def main():
    vr=Path(sys.argv[1])/'src/mods/vr'
    source=(vr/'QuadViewNgxDepth.hpp').read_text(encoding='utf-8')
    h=(vr/'QuadViewDepthIdentity.hpp').read_text(encoding='utf-8')
    assert 'class ExpectedPeripheryExtent {' in h
    assert 'std::atomic<uint64_t> packed_{0};' in h
    assert 'ExpectedPeripheryExtent expected_extent_{};' in source
    assert source.count('expected_extent_.load()') >= 4
    assert 'expected_extent_.store(w, h)' in source
    assert 'want_w_' not in source and 'want_h_' not in source
    print('B19 coherent extent verified in generated capture, prune, lookup and diagnostics')
if __name__=='__main__': main()

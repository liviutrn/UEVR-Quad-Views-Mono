#!/usr/bin/env python3
"""Tri-view B11 depth consumer wiring. Run after apply_triview_depth.py.

B10 tried to authenticate NGX evaluations through a thread-local scope around
the retained RHI callback; NGX does not evaluate inside that callback, so it
could never capture. B11 identifies the periphery by its unique DLSS output
size (see QuadViewNgxSelect.hpp) and only forwards the captured DLSS jitter
here. QuadViewDepthIdentity.hpp still provides the fence helpers.
"""
from pathlib import Path
import shutil
import sys


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'Depth consumer anchor count {text.count(old)}: {old[:100]!r}')
    return text.replace(old, new, 1)


def consumer(text):
    anchor = ('                                    depth_input.srv_format=snapshot->srv_format;\n'
              '                                    for (size_t i=0; i!=4;')
    return once(text, anchor,
        '                                    depth_input.srv_format=snapshot->srv_format;\n'
        '                                    depth_input.jitter_uv[0]=snapshot->jitter_uv[0];\n'
        '                                    depth_input.jitter_uv[1]=snapshot->jitter_uv[1];\n'
        '                                    depth_input.jitter_valid=snapshot->jitter_valid;\n'
        '                                    for (size_t i=0; i!=4;')


def main():
    if len(sys.argv) != 3:
        raise SystemExit('Usage: apply_triview_depth_live.py <backend> <quadview-dir>')
    root, overlay = map(Path, sys.argv[1:])
    c = root/'src/mods/vr/D3D12Component.cpp'
    cs = consumer(c.read_text())
    shutil.copy2(overlay/'QuadViewDepthIdentity.hpp', root/'src/mods/vr/QuadViewDepthIdentity.hpp')
    c.write_text(cs)
    print('B11 depth consumer: newest submitted periphery copy with its DLSS jitter.')


if __name__ == '__main__':
    main()

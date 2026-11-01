#!/usr/bin/env python3
"""Build52 guarded diagnostic overlay; apply AFTER Build51's full overlay chain."""
from pathlib import Path
import shutil
import sys

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Build52 exact source anchor count {text.count(old)} (wanted 1): {old[:110]!r}")
    return text.replace(old, new, 1)

def patch_header(text):
    text = once(text, '#include "QuadViewShaderBytecode.hpp"',
                '#include "QuadViewShaderBytecode.hpp"\n#include "QuadViewAutoCapture.hpp"')
    text = once(text, '        read_timing();\n        owner_.reset();',
                '        read_timing();\n        build52_capture_.finish();\n        owner_.reset();')
    checkpoint = '''        if (timed) {
            commands->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
            commands->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timestamps_.Get(),0);
            timing_pending_=true;
        }
        for (size_t i = 0; i != 4; ++i) {'''
    text = once(text, checkpoint, checkpoint.replace(
        '        for (size_t i = 0; i != 4; ++i) {',
        '        // Build52: read-only GPU copy AFTER composition, BEFORE sources leave shader state.\n'
        '        // Readback is consumed only when the existing per-slot fence retires.\n'
        '        build52_capture_.queue(commands,device_.Get(),sources,layout);\n'
        '        for (size_t i = 0; i != 4; ++i) {'))
    text = once(text, '    ComPtr<ID3D12Device> device_;',
                '    uevr::quadview::diagnostics::AutoCapture build52_capture_{};\n'
                '    ComPtr<ID3D12Device> device_;')
    return text

def main():
    if len(sys.argv)!=2:
        raise SystemExit("Usage: apply_auto_capture.py BACKEND_DIRECTORY")
    source=Path(__file__).resolve().parent
    target=Path(sys.argv[1]) / "src/mods/vr"
    file=target / "QuadViewD3D12.hpp"
    raw=file.read_text(encoding="utf-8")
    patched=patch_header(raw)  # Fail closed, before changing any file.
    capture=source / "QuadViewAutoCapture.hpp"
    if not capture.is_file():
        raise RuntimeError("Missing Build52 capture header")
    shutil.copyfile(capture,target / "QuadViewAutoCapture.hpp")
    file.write_text(patched,encoding="utf-8")
    print("Build52: guarded capture instrumentation added. No shader or eye-image changes.")

if __name__=="__main__":
    main()

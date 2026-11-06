#!/usr/bin/env python3
"""B22 ensures verbose hook tracing is optional in the real generated backend."""
from pathlib import Path
import sys

def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_triview_b22_trace_gate.py BACKEND_ROOT")
    p=Path(sys.argv[1]) / "src/mods/vr/FFakeStereoRenderingHook.cpp"
    s=p.read_text(encoding="utf-8")
    before="void emit_hook_trace(size_t site,const HookTraceRecord& r) {"
    start=s.index(before)
    body=s[start:start+350]
    assert "if (!hook_trace_enabled()) return;" in body
    assert body.index("if (!hook_trace_enabled()) return;") < body.index("gate.visit(") if "gate.visit(" in body else True
    assert 'GetEnvironmentVariableA("UEVR_VERBOSE_HOOK_TRACE"' in s
    assert 'SPDLOG_INFO("[QuadViews][HookTrace]' in s
    print("B22 detailed HookTrace is opt-in; production implementation retained")
if __name__ == "__main__":
    main()

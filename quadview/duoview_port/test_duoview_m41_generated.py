#!/usr/bin/env python3
"""Static contracts for M4.1 (depth bound to the colour packet's OpenXR frame)."""
import sys
from pathlib import Path

failures = []


def need(text, snippet, why, count=1):
    n = text.count(snippet)
    if n != count:
        failures.append(f"{why}: expected {count}x, found {n}x: {snippet[:90]!r}")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_duoview_m41_generated.py <backend>")
    vr = Path(sys.argv[1])/"src/mods/vr"
    ngx = (vr/"QuadViewNgxDepth.hpp").read_text(encoding="utf-8")
    d3d = (vr/"D3D12Component.cpp").read_text(encoding="utf-8")
    need(ngx, "if(provider(frame) && frame) { slot->m41_frame=frame; slot->m41_frame_valid=true; }", "capture stamps the frame")
    need(ngx, "slot->m41_frame=0; slot->m41_frame_valid=false;", "stale stamp cleared on slot reuse")
    need(ngx, "if(s->m41_frame!=frame) continue;", "exact frame only")
    need(ngx, "if(coarse && fine) {++m41_exact_;return {coarse,fine};}", "both images or none")
    need(d3d, "std::scoped_lock lock{xr->sync_assignment_mtx};\n    if(!xr->has_render_frame_count)", "provider must not lock", 0)
    need(d3d, "depth.m41_set_frame_provider(&m41_render_frame);", "provider registered")
    need(d3d, "current_queue,packet_frame->mono_source_frame.value_or(0u)) :", "packet's own frame")
    need(d3d, "const auto m41_pair=config.settings.m4_fovea_grid ?", "M4 OFF keeps the old selection")
    need(d3d, "config.settings.m4_fovea_grid ?\n                                                std::shared_ptr<const uevr::quadview::ngx::DepthSnapshot>{} :",
         "M4 ON never uses fine depth from another frame")
    need(d3d, "[DuoView][M4.1] exact={}", "diagnostic log")
    if failures:
        print("\n".join("FAIL " + f for f in failures))
        raise SystemExit(1)
    print("PASS: M4.1 frame-bound depth contracts")


if __name__ == "__main__":
    main()

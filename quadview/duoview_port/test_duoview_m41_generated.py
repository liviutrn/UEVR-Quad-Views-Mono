#!/usr/bin/env python3
"""Check the generated DuoView transaction join and its fail-closed paths."""
import sys
from pathlib import Path


def main(backend):
    vr = Path(backend) / "src/mods/vr"
    ngx = (vr / "QuadViewNgxDepth.hpp").read_text(encoding="utf-8")
    delivery = (vr / "DuoViewDelivery.hpp").read_text(encoding="utf-8")
    rhi = (vr / "FFakeStereoRenderingHook.cpp").read_text(encoding="utf-8")
    d3d = (vr / "D3D12Component.cpp").read_text(encoding="utf-8")

    assert "m41_render_frame" not in d3d and "m41_frame_provider" not in ngx
    assert "slot->m41_packet_serial = 0;" in ngx
    assert "serial == m41_marker_serial_ + 1" in ngx
    assert "coarse.count != 1 || fine.count != 1" in ngx
    assert "coarse.thread != thread || fine.thread != thread" in ngx
    assert "slot->m41_packet_serial != serial || slot->duoview_request != request" in ngx
    assert "slot->duoview_producer_queue.Get() != consumer_queue" in ngx
    assert "return {coarse, {}};" in ngx
    assert delivery.index("slot=source;") < delivery.index("if (deferred) deferred_roles")
    assert "duo_command.deferred_roles == 3u" in rhi
    assert "owns_both ? owner->serial : 0, GetCurrentThreadId()" in rhi
    assert rhi.index("m41_close_capture_interval(") < rhi.index('qv_emit_rhi(12,"ORIGINAL_ENTER"')
    assert rhi.count("duo_source, quad_source, quad_engine, quad_native, true);") == 3
    assert "cmd_list->root, frame_count + compensation, duo_source, quad_source, quad_engine, quad_native);" in rhi
    assert "depths.m41_pair_for_packet(config.key.generation, packet->serial," in d3d
    assert "const auto m25_fine=config.settings.m4_fovea_grid ? m41_pair.second :" in d3d
    assert "[DuoView][M4.1] bound={} rejected={} exact={} coarse_only={}" in d3d
    assert "m1_raw_srv_,m2_fovea_srv_,settings.m4_fovea_grid);" in (
        vr / "DuoViewD3D12.hpp").read_text(encoding="utf-8")
    print("PASS: M4.1 generated transaction-bound depth contracts")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_duoview_m41_generated.py <backend>")
    main(sys.argv[1])

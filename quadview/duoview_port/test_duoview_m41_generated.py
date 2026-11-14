#!/usr/bin/env python3
"""Check that only complete fine-depth transactions can reach XR in M4."""
import sys
from pathlib import Path


def main(backend):
    vr = Path(backend) / "src/mods/vr"
    def read(path):
        return (vr / path).read_text(encoding="utf-8")

    ngx = read("QuadViewNgxDepth.hpp")
    delivery = read("DuoViewDelivery.hpp")
    rhi = read("FFakeStereoRenderingHook.cpp")
    d3d = read("D3D12Component.cpp")
    compositor = read("DuoViewD3D12.hpp")
    xr = read("runtimes/OpenXR.cpp")

    assert "m41_render_frame" not in d3d and "m41_frame_provider" not in ngx
    assert "serial == m41_marker_serial_ + 1" in ngx
    assert "coarse.count != 1 || fine.count != 1" in ngx
    assert "coarse.thread != thread || fine.thread != thread" in ngx
    assert "m41_packets_[serial % m41_packets_.size()] = {serial, coarse.depth, fine.depth};" in ngx
    assert "if (!ready(pair.coarse) || !ready(pair.fine) || !pair.fine->jitter_valid) return {};" in ngx
    assert "slot->submitted" in ngx and "FAILED(queue->Wait(" in ngx
    assert delivery.index("slot=source;") < delivery.index("if (deferred) deferred_roles")
    assert "duo_command.deferred_roles == 3u" in rhi
    assert "owns_both ? owner->serial : 0, GetCurrentThreadId()" in rhi
    assert rhi.index("m41_close_capture_interval(") < rhi.index('qv_emit_rhi(12,"ORIGINAL_ENTER"')
    assert rhi.count("duo_source, quad_source, quad_engine, quad_native, true);") == 3
    assert "cmd_list->root, frame_count + compensation, duo_source, quad_source, quad_engine, quad_native);" in rhi
    gate = d3d.index("} else if (require_fine && !fine_pair.fine) {")
    assert d3d.index("depths.m41_pair_for_packet(") < gate < d3d.index("const bool submitted = m_openxr.copy(", gate)
    assert "const auto snapshot=require_fine ? fine_pair.coarse :" in d3d
    assert "const auto m25_fine=require_fine ? fine_pair.fine :" in d3d
    assert "m41_order_for_composition(fine_pair, queue)" in d3d
    assert "if (require_fine && (!m1_active || !m1_.m4_active))" in compositor
    assert 'return reject("Gather cannot record M4 full-resolution stereo");' in compositor
    assert "m1_raw_srv_,m2_fovea_srv_,settings.m4_fovea_grid);" in compositor
    assert "m25_content_active=fine_ok && fine_mode==1u && !m4_fovea_grid;" in read("DuoViewM1D3D12.hpp")
    assert "pose.duoview_full_resolution_depth=require_fine;" in d3d
    assert "require_fine && duoview_pending_pose && !duoview_pending_pose->duoview_full_resolution_depth" in xr
    assert "(!require_fine || duoview_submitted_pose->duoview_full_resolution_depth)" in xr
    print("PASS: M4 requires same-transaction fine depth through XR submission")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_duoview_m41_generated.py <backend>")
    main(sys.argv[1])

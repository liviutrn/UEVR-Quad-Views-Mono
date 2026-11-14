#!/usr/bin/env python3
"""M3b P7 one-second gate and runtime status diagnostics without readback stalls."""
import sys
from pathlib import Path
from apply_duoview_b40_pipeline import patch

def main():
    if len(sys.argv) != 3:
        raise SystemExit('usage: apply_duoview_m3b_log.py <backend> <shaders>')
    mods = Path(sys.argv[1])/'src/mods'
    patch(mods/'vr/D3D12Component.cpp', [
        ('P7 one-second gate window',
         'next_m25_log_ms.compare_exchange_strong(expected,m25_ms+2000)) {',
         'next_m25_log_ms.compare_exchange_strong(expected,m25_ms+1000)) {'),
        ('P7 per-second M3b gate counters and explicit unavailable GPU percentages',
         '                                                    s.fine_coarse[0],s.fine_coarse[1],s.fine_coarse[2],s.fine_coarse[3],s.fine_coarse[4],s.fine_coarse[5],s.fine_coarse[6]);',
         '''                                                    s.fine_coarse[0],s.fine_coarse[1],s.fine_coarse[2],s.fine_coarse[3],s.fine_coarse[4],s.fine_coarse[5],s.fine_coarse[6]);
                                                SPDLOG_INFO("[DuoView][M3b] gate enabled={} frames={} guard={} cells={} agree={} varied={} passing={} weighted={} active_tiles={} vertical={} jitter_minus={} jitter_zero={} jitter_plus={} active_sign={} temporal_resets={} clamp_pct=n/a repair_pct=n/a fgdepth=OFF",
                                                    config.settings.m3b_gate_tuning,
                                                    g[0],g[1],g[2],g[3],g[4],g[5],g[6],g[7],g[8],
                                                    g[9],g[10],g[11],
                                                    uevr::duoview::dx12::M1Resources::M3bAutoJitter::sign.load(std::memory_order_relaxed),
                                                    uevr::duoview::dx12::M1Resources::m3b_temporal_resets.exchange(0));'''),
    ])
    print('M3b P7: 1-second gate scores, jitter sign, temporal reset counters, documented GPU metric gaps')

if __name__ == '__main__':
    main()

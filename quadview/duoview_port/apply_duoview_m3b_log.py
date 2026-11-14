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
    patch(mods/'vr/D3D12Component.cpp', [
        ('P7 log each Auto jitter vote from a completed GPU score window',
         '                                                double(m21.pool_bytes)/1048576.0,\n                                                packet_frame->config.settings.m21_jitter_correct);',
         '                                                double(m21.pool_bytes)/1048576.0,\n                                                packet_frame->config.settings.m21_jitter_correct);\n                                            using M3bVote=uevr::duoview::dx12::M1Resources::M3bAutoJitter;\n                                            static std::atomic<uint64_t> last_jitter_window_logged{0};\n                                            const uint64_t window=M3bVote::window_sequence.load(std::memory_order_acquire);\n                                            uint64_t observed=last_jitter_window_logged.load(std::memory_order_relaxed);\n                                            if(window>observed && last_jitter_window_logged.compare_exchange_strong(observed,window)) {\n                                                SPDLOG_INFO("[DuoView][M3b] jitter score minus={} zero={} plus={} active={}",\n                                                    M3bVote::last_minus.load(),M3bVote::last_zero.load(),M3bVote::last_plus.load(),\n                                                    M3bVote::sign.load());\n                                            }'),
    ])
    print('M3b P7: 1-second gate scores, jitter sign, temporal reset counters, documented GPU metric gaps')

if __name__ == '__main__':
    main()

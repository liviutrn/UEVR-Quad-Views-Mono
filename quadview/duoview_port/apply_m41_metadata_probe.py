#!/usr/bin/env python3
"""M41 metadata-only source-pair probe. Apply after M41 frame-bind overlay.
Exact anchors; validate both generated files before writing either.
"""
import argparse
from pathlib import Path

DECLARATIONS='''    // Experimental metadata-only counters (process lifetime).
    std::array<std::atomic<uint64_t>, 9> m41_probe_reason_{};
    std::atomic<uint64_t> m41_probe_lookup_ineligible_{0}, m41_probe_lookup_unready_{0},
        m41_probe_lookup_ready_{0};
    std::array<std::atomic<uint64_t>, 7> m41_probe_marker_coarse_epoch_{},
        m41_probe_fine_coarse_epoch_{};
'''
TAKE_STATS='''    struct M41ProbeStats {
        std::array<uint64_t, 9> reasons{};
        std::array<uint64_t, 7> marker_coarse_epoch{}, fine_coarse_epoch{};
        uint64_t lookup_ineligible{}, lookup_unready{}, lookup_ready{};
    };
    M41ProbeStats m41_probe_stats() const noexcept {
        M41ProbeStats s{};
        for (size_t i = 0; i < s.reasons.size(); ++i)
            s.reasons[i] = m41_probe_reason_[i].load(std::memory_order_relaxed);
        for (size_t i = 0; i < 7; ++i) {
            s.marker_coarse_epoch[i] = m41_probe_marker_coarse_epoch_[i].load(std::memory_order_relaxed);
            s.fine_coarse_epoch[i] = m41_probe_fine_coarse_epoch_[i].load(std::memory_order_relaxed);
        }
        s.lookup_ineligible = m41_probe_lookup_ineligible_.load(std::memory_order_relaxed);
        s.lookup_unready = m41_probe_lookup_unready_.load(std::memory_order_relaxed);
        s.lookup_ready = m41_probe_lookup_ready_.load(std::memory_order_relaxed);
        return s;
    }
'''
LOG='''                        // Log before XR acquisition even for a rejected M4 pair.
                        if (require_fine) {
                            static std::atomic<int64_t> next_m41_probe_ms{0};
                            const auto t = std::chrono::duration_cast<std::chrono::milliseconds>(
                                std::chrono::steady_clock::now().time_since_epoch()).count();
                            auto until = next_m41_probe_ms.load(std::memory_order_relaxed);
                            if (t >= until && next_m41_probe_ms.compare_exchange_strong(until, t + 2000)) {
                                const auto m = depths.m41_probe_stats();
                                SPDLOG_INFO("[DuoView][M41-Probe] accepted={} zero={} marker_discontinuity={} coarse_missing={} coarse_duplicate={} fine_missing={} fine_duplicate={} capture_thread={} invalid_request_or_capture={} lookup_ineligible={} lookup_unready={} lookup_ready={}",
                                    m.reasons[0], m.reasons[1], m.reasons[2], m.reasons[3],
                                    m.reasons[4], m.reasons[5], m.reasons[6], m.reasons[7],
                                    m.reasons[8], m.lookup_ineligible, m.lookup_unready, m.lookup_ready);
                                SPDLOG_INFO("[DuoView][M41-Probe] accepted_pair_epoch marker-coarse={},{},{},{},{},{},{} fine-coarse={},{},{},{},{},{},{}",
                                    m.marker_coarse_epoch[0],m.marker_coarse_epoch[1],m.marker_coarse_epoch[2],
                                    m.marker_coarse_epoch[3],m.marker_coarse_epoch[4],m.marker_coarse_epoch[5],
                                    m.marker_coarse_epoch[6],m.fine_coarse_epoch[0],m.fine_coarse_epoch[1],
                                    m.fine_coarse_epoch[2],m.fine_coarse_epoch[3],m.fine_coarse_epoch[4],
                                    m.fine_coarse_epoch[5],m.fine_coarse_epoch[6]);
                            }
                        }
'''

def once(text, old, new, label):
    count=text.count(old)
    if count!=1: raise RuntimeError(f"{label}: expected unique source anchor, got {count}; no files modified")
    return text.replace(old,new,1)

def transform(ngx,d3d):
    ngx=once(ngx,'    uint32_t m41_marker_thread_{};\n',
        '    uint32_t m41_marker_thread_{};\n'+DECLARATIONS,'M41 counters')
    ngx=once(ngx,
        '        if (!serial) { m41_packets_ = {}; return; }\n'
        '        if (!consecutive) m41_packets_ = {};\n'
        '        if (!consecutive || coarse.count != 1 || fine.count != 1 ||\n'
        '            coarse.thread != thread || fine.thread != thread) {\n'
        '            return;\n'
        '        }\n\n'
        '        const auto request = duoview_expected_.load(std::memory_order_acquire);\n'
        '        if (!request || request->generation != generation || !coarse.depth || !fine.depth ||\n'
        '            coarse.depth->duoview_request != request || fine.depth->duoview_request != request ||\n'
        '            !coarse.depth->valid_evaluation || !fine.depth->valid_evaluation) {\n'
        '            return;\n'
        '        }\n'
        '        m41_packets_[serial % m41_packets_.size()] = {serial, coarse.depth, fine.depth};',
        '''        if (!serial) { m41_packets_ = {}; ++m41_probe_reason_[1]; return; }
        if (!consecutive) { m41_packets_ = {}; ++m41_probe_reason_[2]; return; }
        if (coarse.count != 1) { ++m41_probe_reason_[coarse.count == 0 ? 3 : 4]; return; }
        if (fine.count != 1) { ++m41_probe_reason_[fine.count == 0 ? 5 : 6]; return; }
        if (coarse.thread != thread || fine.thread != thread) { ++m41_probe_reason_[7]; return; }
        const auto request = duoview_expected_.load(std::memory_order_acquire);
        if (!request || request->generation != generation || !coarse.depth || !fine.depth ||
            coarse.depth->duoview_request != request || fine.depth->duoview_request != request ||
            !coarse.depth->valid_evaluation || !fine.depth->valid_evaluation) {
            ++m41_probe_reason_[8]; return;
        }
        ++m41_probe_reason_[0];
        // Present epoch is NOT source-frame identity, only a skew indicator.
        const auto bucket = [](uint64_t a, uint64_t b) -> size_t {
            const uint64_t d = a > b ? a - b : b - a;
            if (d > 3u) return a > b ? 6u : 0u;
            return size_t(a > b ? 3u + d : 3u - d);
        };
        const auto marker_epoch = m24_present_epoch_.load(std::memory_order_acquire);
        ++m41_probe_marker_coarse_epoch_[bucket(marker_epoch, coarse.depth->m24_present_epoch)];
        ++m41_probe_fine_coarse_epoch_[bucket(fine.depth->m24_present_epoch, coarse.depth->m24_present_epoch)];
        m41_packets_[serial % m41_packets_.size()] = {serial, coarse.depth, fine.depth};''',
        'M41 marker classifier')
    ngx=once(ngx,
        '            capture_mode_.load(std::memory_order_acquire) != DepthCaptureMode::DuoView) return {};',
        '            capture_mode_.load(std::memory_order_acquire) != DepthCaptureMode::DuoView) {\n'
        '            ++m41_probe_lookup_ineligible_; return {};\n        }',
        'M41 ineligible lookup')
    ngx=once(ngx,
        '        if (!ready(pair.coarse) || !ready(pair.fine) || !pair.fine->jitter_valid) return {};\n'
        '        return pair;',
        '        if (!ready(pair.coarse) || !ready(pair.fine) || !pair.fine->jitter_valid) {\n'
        '            ++m41_probe_lookup_unready_; return {};\n        }\n'
        '        ++m41_probe_lookup_ready_;\n        return pair;',
        'M41 lookup readiness')
    ngx=once(ngx,'    struct M25Stats {',TAKE_STATS+'    struct M25Stats {',
        'probe stats')
    d3d=once(d3d,
        '                            : uevr::quadview::ngx::PeripheryDepth::M41DepthPair{};\n'
        '                        if (!packet_pair_valid) {',
        '                            : uevr::quadview::ngx::PeripheryDepth::M41DepthPair{};\n'+LOG+
        '                        if (!packet_pair_valid) {',
        'early no-XR log')
    return ngx,d3d

def apply(backend):
    root=Path(backend)/'src/mods/vr'
    p=root/'QuadViewNgxDepth.hpp';q=root/'D3D12Component.cpp'
    a,b=p.read_text(encoding='utf-8'),q.read_text(encoding='utf-8')
    aa,bb=transform(a,b)
    p.write_text(aa,encoding='utf-8')
    q.write_text(bb,encoding='utf-8')
    return p,q

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('backend')
    args=parser.parse_args()
    for f in apply(args.backend):print('M41 metadata diagnostic patched:',f)

#!/usr/bin/env python3
"""B20 (based on confirmed-working B18-42): skip redundant depth pool locks.

No foreign-queue waits, shader modifications, resource-count changes, or
startup changes. B18 remains the exact fallback. Apply after B18 parity tests.
"""
from pathlib import Path
import sys

def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"B20 {label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)

def transform(text: str) -> str:
    text = once(text, """    void set_expected(uint32_t w, uint32_t h) {
        want_w_.store(w, std::memory_order_relaxed); want_h_.store(h, std::memory_order_relaxed);
    }""", """    void set_expected(uint32_t w, uint32_t h) {
        // Publish the two dimensions as a single atomic snapshot.
        // Diagnostics remain separate and cannot influence selection.
        expected_extent_.store((uint64_t(w) << 32) | h, std::memory_order_release);
        want_w_.store(w, std::memory_order_relaxed);
        want_h_.store(h, std::memory_order_relaxed);
    }""", "extent publication")
    text = once(text, """    void set_enabled(bool on) {
        enabled_.store(on && capture_supported(), std::memory_order_release);
        std::scoped_lock lock(mutex_);
        prune_locked(want_w_.load(),want_h_.load(),!on);
    }""", """    void set_enabled(bool on) {
        const bool enabled=on && capture_supported();
        const bool toggled=enabled_.exchange(enabled,std::memory_order_acq_rel)!=enabled;
        const uint64_t extent=expected_extent_.load(std::memory_order_acquire);
        // B18 locked/scanned all depth snapshots every present. Keep transition
        // pruning immediate; retry GPU-fence retirement every 32 presents.
        const bool retry_retirement=(retirement_tick_.fetch_add(1,std::memory_order_relaxed)&31u)==0u;
        if (!toggled && !retry_retirement &&
            last_pruned_extent_.load(std::memory_order_acquire)==extent) return;
        std::scoped_lock lock(mutex_);
        prune_locked(uint32_t(extent>>32),uint32_t(extent),!enabled);
        last_pruned_extent_.store(extent,std::memory_order_release);
    }""", "no redundant present-thread mutex")
    text = once(text, """        const auto w = want_w_.load(std::memory_order_relaxed), h = want_h_.load(std::memory_order_relaxed);
        if (!enabled_.load(std::memory_order_acquire) || !w || !h) { ++missed_; return {}; }""", """        const uint64_t extent=expected_extent_.load(std::memory_order_acquire);
        const uint32_t w=uint32_t(extent>>32), h=uint32_t(extent);
        if (!enabled_.load(std::memory_order_acquire) || !w || !h) { ++missed_; return {}; }""", "consistent depth selection dimensions")
    text = once(text, """    std::atomic<bool> enabled_{false};
    std::atomic<uint32_t> want_w_{}, want_h_{}, last_out_w_{}, last_out_h_{}, last_in_w_{}, last_in_h_{}, last_format_{};""", """    std::atomic<bool> enabled_{false};
    std::atomic<uint64_t> expected_extent_{0},last_pruned_extent_{~uint64_t{}};
    std::atomic<uint32_t> retirement_tick_{0};
    std::atomic<uint32_t> want_w_{}, want_h_{}, last_out_w_{}, last_out_h_{}, last_in_w_{}, last_h_{}, last_format_{};""".replace("last_in_w_{}, last_h_{}", "last_in_w_{}, last_in_h_{}"), "housekeeping atomics")
    text = once(text, """        const auto want_w = want_w_.load(std::memory_order_relaxed), want_h = want_h_.load(std::memory_order_relaxed);
        const auto out_w = ngx_uint(p, "OutWidth"), out_h = ngx_uint(p, "OutHeight");""", """        const uint64_t extent=expected_extent_.load(std::memory_order_acquire);
        const uint32_t want_w=uint32_t(extent>>32),want_h=uint32_t(extent);
        const auto out_w = ngx_uint(p, "OutWidth"), out_h = ngx_uint(p, "OutHeight");""", "consistent NGX capture dimensions")
    return text

def main() -> None:
    if len(sys.argv)!=2: raise SystemExit("Usage: apply_triview_b20_from_b18.py <backend>")
    p=Path(sys.argv[1])/"src/mods/vr/QuadViewNgxDepth.hpp"
    updated=transform(p.read_text(encoding="utf-8"))
    p.write_text(updated,encoding="utf-8",newline="\n")
    print("B20 from B18-42: atomic extent, amortized depth retirement, no GPU waits added")

if __name__=="__main__":
    main()

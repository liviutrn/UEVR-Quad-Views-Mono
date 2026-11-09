#pragma once
// B41: TriView-only replacement for uevr::duoview::SubmitContinuity.
// Same interface and rules (no hold before the first submit, no hold across a
// mode/generation or swapchain change), but the hold window is a user setting
// (100..1000 ms, default 250) instead of DuoView's fixed 100 ms. DuoView keeps
// its own class unchanged.
#include <algorithm>
#include <atomic>
#include <cstdint>

namespace uevr::quadview {

class TriViewHold {
public:
    static constexpr uint32_t min_window_ms = 100;
    static constexpr uint32_t max_window_ms = 1000;
    static constexpr uint32_t default_window_ms = 250;

    static void set_window_ms(uint32_t ms) {
        window_ms_.store(std::clamp(ms, min_window_ms, max_window_ms), std::memory_order_relaxed);
    }
    static uint32_t window_ms() { return window_ms_.load(std::memory_order_relaxed); }

    void reset() { ready_ = false; }
    void submitted(uint64_t generation, uint64_t swapchain, uint64_t now_ms) {
        generation_ = generation; swapchain_ = swapchain; submitted_ms_ = now_ms; ready_ = true;
    }
    bool can_hold(uint64_t generation, uint64_t swapchain, uint64_t now_ms) const {
        return ready_ && generation == generation_ && swapchain && swapchain == swapchain_ &&
            now_ms >= submitted_ms_ && now_ms - submitted_ms_ <= window_ms();
    }
    bool ready() const { return ready_; }
    // Milliseconds since the last real (not held) submit; 0 before the first.
    uint64_t age_ms(uint64_t now_ms) const {
        return ready_ && now_ms >= submitted_ms_ ? now_ms - submitted_ms_ : 0;
    }

private:
    static inline std::atomic<uint32_t> window_ms_{default_window_ms};
    uint64_t generation_{}, swapchain_{}, submitted_ms_{};
    bool ready_{};
};

} // namespace uevr::quadview

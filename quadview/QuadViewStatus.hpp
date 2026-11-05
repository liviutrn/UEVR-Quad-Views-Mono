#pragma once
#include <cstdint>
#include <mutex>

namespace uevr::quadview {
enum class DisplayState { transitioning, unavailable, waiting_targets, waiting_submit, active, stalled };
struct StatusFacts {
    uint64_t generation{}, tick{};
    bool transitioning{}, unavailable{}, targets_ready{};
};
class StatusTracker {
public:
    struct Submission { uint64_t generation{}, serial{}, tick{}; };
    // No wall-clock inference of ownership: only a successful fresh XR submit
    // supplies all three fields in one transaction.
    bool submitted(uint64_t generation, uint64_t serial, uint64_t tick) {
        std::scoped_lock lock(mutex_);
        if (!generation || !serial || generation < last_.generation) return false;
        if (generation == last_.generation && (serial <= last_.serial || tick < last_.tick)) return false;
        last_ = {generation, serial, tick};
        return true;
    }
    Submission snapshot(uint64_t generation) {
        std::scoped_lock lock(mutex_);
        if (generation > last_.generation) last_ = {generation, 0, 0};
        return last_;
    }
    DisplayState state(const StatusFacts& facts) {
        const auto last = snapshot(facts.generation);
        if (facts.unavailable) return DisplayState::unavailable;
        if (facts.transitioning) return DisplayState::transitioning;
        const bool same = last.generation == facts.generation && last.serial != 0;
        // A fresh submission is authoritative even if a new draw is currently
        // acquiring targets. Held continuity images never refresh this clock.
        if (same && facts.tick >= last.tick && facts.tick - last.tick < 1000) return DisplayState::active;
        if (!facts.targets_ready) return DisplayState::waiting_targets;
        return same ? DisplayState::stalled : DisplayState::waiting_submit;
    }
private:
    std::mutex mutex_;
    Submission last_{};
};
inline const char* display_state_text(DisplayState state) {
    switch (state) {
    case DisplayState::transitioning: return "Changing rendering mode";
    case DisplayState::unavailable: return "Unavailable";
    case DisplayState::waiting_targets: return "Waiting for source targets";
    case DisplayState::waiting_submit: return "Waiting for first fresh XR submission";
    case DisplayState::active: return "Active: fresh stereo image submitted";
    case DisplayState::stalled: return "Stalled: no fresh XR submission for 1 second";
    }
    return "Waiting";
}
}

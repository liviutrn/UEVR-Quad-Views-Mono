#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace uevr::duoview::ngx::recovery {

inline constexpr std::uint8_t RequiredFreshPairs = 8;
using SourceSignature = std::array<std::uint64_t, 6>;
using EyePair = std::array<std::uint64_t, 2>;

struct Observation {
    bool pair_present{};
    SourceSignature source{}; // left feature/width/height, right feature/width/height
    std::uint64_t present_epoch{};
    EyePair serials{};
    EyePair evaluations{};
};

enum class Reason : std::uint8_t {
    recovering,
    ready,
    missing_pair,
    invalid_source,
    invalid_sample,
    source_changed,
    repeated_pair,
    duplicate_epoch,
    stale_epoch,
    epoch_gap,
};

struct Decision {
    bool allow{};
    std::uint8_t consecutive_fresh_pairs{};
    Reason reason{Reason::recovering};
};

inline const char* reason_name(Reason reason) noexcept {
    switch (reason) {
    case Reason::recovering: return "recovering";
    case Reason::ready: return "ready";
    case Reason::missing_pair: return "missing_pair";
    case Reason::invalid_source: return "invalid_source";
    case Reason::invalid_sample: return "invalid_sample";
    case Reason::source_changed: return "source_changed";
    case Reason::repeated_pair: return "repeated_pair";
    case Reason::duplicate_epoch: return "duplicate_epoch";
    case Reason::stale_epoch: return "stale_epoch";
    case Reason::epoch_gap: return "epoch_gap";
    }
    return "unknown";
}

// Prevents a transiently missing/replaced manual NGX pair from immediately
// re-enabling stereo with one nearby evaluation. Feature handles and requested
// output dimensions define source identity; transient evaluation generations
// and evaluation ordinals deliberately do not.
class PairRecovery final {
    struct Stamp {
        std::uint64_t epoch{};
        EyePair serials{};
        EyePair evaluations{};
    };

    SourceSignature source_{};
    bool have_source_{};
    Stamp last_{};
    bool have_last_{};
    std::array<Stamp, RequiredFreshPairs> history_{};
    std::uint8_t history_size_{};
    std::uint8_t count_{};
    Reason reason_{Reason::recovering};

    static bool valid_source(const SourceSignature& source) noexcept {
        for (const auto value : source) {
            if (!value) return false;
        }
        return true;
    }

    static bool valid_sample(const Observation& observation) noexcept {
        if (!observation.present_epoch ||
            !observation.serials[0] || !observation.serials[1] ||
            !observation.evaluations[0] || !observation.evaluations[1]) {
            return false;
        }
        return true;
    }

    static bool same_pair(const Stamp& a, const Observation& b) noexcept {
        // Each eye must contribute a new depth serial and evaluation. Reusing
        // either eye makes the stereo pair unsuitable for recovery.
        return a.serials[0] == b.serials[0] || a.serials[1] == b.serials[1] ||
               a.evaluations[0] == b.evaluations[0] ||
               a.evaluations[1] == b.evaluations[1];
    }

    void clear_progress() noexcept {
        history_ = {};
        history_size_ = 0;
        count_ = 0;
        have_last_ = false;
        last_ = {};
    }

    void remember(const Observation& observation) noexcept {
        const Stamp stamp{observation.present_epoch, observation.serials, observation.evaluations};
        if (history_size_ < RequiredFreshPairs) {
            history_[history_size_++] = stamp;
        } else {
            for (std::size_t i = 1; i < history_.size(); ++i) history_[i - 1] = history_[i];
            history_.back() = stamp;
        }
        count_ = history_size_;
        last_ = stamp;
        have_last_ = true;
    }

    Decision decision(bool allow, Reason reason) noexcept {
        reason_ = reason;
        return {allow, count_, reason_};
    }

    void start_with(const Observation& observation) noexcept {
        clear_progress();
        source_ = observation.source;
        have_source_ = true;
        remember(observation);
    }

public:
    Decision observe(const Observation& observation) noexcept {
        if (!observation.pair_present) {
            reset();
            return decision(false, Reason::missing_pair);
        }
        if (!valid_source(observation.source)) {
            reset();
            return decision(false, Reason::invalid_source);
        }
        if (!valid_sample(observation)) {
            reset();
            return decision(false, Reason::invalid_sample);
        }

        if (!have_source_) {
            start_with(observation);
            return decision(false, Reason::recovering);
        }

        if (source_ != observation.source) {
            start_with(observation);
            return decision(false, Reason::source_changed);
        }

        if (have_last_) {
            if (observation.present_epoch == last_.epoch) {
                // A repeated Present never authorizes reusing its previous depth.
                // It does not erase progress from the same still-current epoch.
                return decision(false, Reason::duplicate_epoch);
            }
            if (observation.present_epoch < last_.epoch) {
                reset();
                return decision(false, Reason::stale_epoch);
            }
            if (observation.present_epoch != last_.epoch + 1) {
                start_with(observation);
                return decision(false, Reason::epoch_gap);
            }
            if (observation.serials[0] == last_.serials[0] ||
                observation.serials[1] == last_.serials[1] ||
                observation.evaluations[0] == last_.evaluations[0] ||
                observation.evaluations[1] == last_.evaluations[1]) {
                clear_progress();
                last_ = {observation.present_epoch, observation.serials, observation.evaluations};
                have_last_ = true;
                return decision(false, Reason::repeated_pair);
            }
        }

        for (std::size_t i = 0; i < history_size_; ++i) {
            if (same_pair(history_[i], observation)) {
                clear_progress();
                last_ = {observation.present_epoch, observation.serials, observation.evaluations};
                have_last_ = true;
                return decision(false, Reason::repeated_pair);
            }
        }

        if (!have_last_) {
            // This follows an explicit invalidation (for example a stale pair).
            source_ = observation.source;
            have_source_ = true;
        }
        remember(observation);
        return decision(count_ >= RequiredFreshPairs,
                        count_ >= RequiredFreshPairs ? Reason::ready : Reason::recovering);
    }

    // Call when the caller knows the selected pair cannot be used this Present.
    Decision reject() noexcept {
        reset();
        return decision(false, Reason::missing_pair);
    }

    void reset() noexcept {
        source_ = {};
        have_source_ = false;
        clear_progress();
        reason_ = Reason::recovering;
    }

    std::uint8_t fresh_pair_count() const noexcept { return count_; }
    bool allowed() const noexcept { return reason_ == Reason::ready; }
    Reason reason() const noexcept { return reason_; }
};

} // namespace uevr::duoview::ngx::recovery

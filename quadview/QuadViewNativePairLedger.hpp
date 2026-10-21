#pragma once
// Experimental Build 43: account for exactly two separately executed
// native-stereo *pair* render calls before publishing the original atlas.
// The original single-family Build 40 path remains the default.
#include <cstdint>
#include <mutex>

namespace uevr::quadview {

class NativePairLedger {
public:
    enum class Phase : uint8_t { Invalid, First, Second };
    struct Owner {
        uint64_t generation{};
        uint32_t frame{};
        uintptr_t target{}, scene{};
        friend bool operator==(const Owner&, const Owner&) = default;
        explicit operator bool() const {
            return generation != 0 && frame != 0xffffffffu && target != 0 && scene != 0;
        }
    };

    Phase observe(Owner key) {
        if (!key) return Phase::Invalid;
        std::scoped_lock guard{mutex_};
        if (owner_ != key) {
            owner_ = key;
            calls_ = 1;
            return Phase::First;
        }
        if (calls_ == 1) {
            calls_ = 2;
            return Phase::Second;
        }
        return Phase::Invalid; // Never attribute an unexpected third callback.
    }

    void reset() {
        std::scoped_lock guard{mutex_};
        owner_ = {};
        calls_ = 0;
    }

private:
    std::mutex mutex_{};
    Owner owner_{};
    uint8_t calls_{};
};
} // namespace uevr::quadview

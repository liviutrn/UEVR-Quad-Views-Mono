#pragma once
#include <cstdint>

namespace uevr::quadview {
// A maintenance callback services the transition's RHI worker only.
// It is never a source owner or evidence that an old resource has retired.
struct TransitionCallbackTicket {
    uint64_t generation{}, request{};
    explicit operator bool() const { return generation && request; }
    bool current(uint64_t live_generation, uint64_t live_request,
                 bool selected, bool pending, bool closed) const {
        return bool(*this) && generation == live_generation && request == live_request &&
            selected && pending && closed;
    }
};

constexpr bool allow_transition_callback(bool selected, bool pending, bool closed,
                                         bool has_source_owner, bool known_drain) {
    return selected && pending && closed && !has_source_owner && known_drain;
}
}

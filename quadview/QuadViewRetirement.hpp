#pragma once

#include <cstdint>

namespace uevr::quadview {

// Presentation resource reconfiguration may proceed while new engine view
// owners continue to arrive. A rendering-mode transition must drain them.
enum class RetirementScope : std::uint8_t {
    presentation,
    mode_transition,
};

constexpr bool requires_engine_retirement(RetirementScope scope) noexcept {
    // Treat unknown enum values conservatively as mode-transition scope.
    return scope != RetirementScope::presentation;
}

} // namespace uevr::quadview

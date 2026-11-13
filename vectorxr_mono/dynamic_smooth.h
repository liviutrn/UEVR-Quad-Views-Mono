#pragma once
// Optional VectorXR Dynamic JIT policy: pure helpers, regression tested.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <chrono>
#include <cstddef>
namespace depthxr::dynamic_smooth {
inline std::uint32_t Slots(double measured, std::uint32_t ceiling) {
    if (measured <= 0.0) return 2;
    return static_cast<std::uint32_t>(std::clamp(std::lround(measured), 2l, static_cast<long>(ceiling)));
}
// Stock uses 0,1,2. Reserve-only scores 3=thin slack, 4=unknown.
// With reserve=0 this preserves stock scoring for every input.
enum : std::uint8_t { kLeadOnTime=0, kLeadLate=1, kLeadSpare=2, kLeadThin=3, kLeadUnknown=4 };
inline std::uint8_t ScoreLead(bool late, bool has_slack, double slack_ms,
                              double period_ms, std::uint32_t reserve) {
    if (late) return kLeadLate;
    if (!has_slack) return reserve ? kLeadUnknown : kLeadOnTime;
    if (slack_ms > period_ms * (1.1 + static_cast<double>(reserve))) return kLeadSpare;
    if (reserve && slack_ms < period_ms * static_cast<double>(reserve)) return kLeadThin;
    return kLeadOnTime;
}
// Pure reserve decisions; keep mixed unknown samples from trapping a high
// lead, while rejecting the overlapping 7-spare/3-thin flap case.
inline bool ReserveWantsUp(std::size_t thin) { return thin >= 3; }
inline bool ReserveWantsDown(std::size_t history, std::size_t ontime,
                             std::size_t spare, std::size_t thin) {
    const std::size_t measured = ontime + spare + thin;
    return history >= 8 && measured >= 5 && spare * 10 >= measured * 7 && thin <= 1;
}
// Tested using synthetic time points; never consults wall-clock internally.
struct DownHold {
    using Clock = std::chrono::steady_clock;
    Clock::time_point last_down{};
    Clock::time_point until{};
    std::chrono::milliseconds hold{0};
    void NoteDown(Clock::time_point now) { last_down = now; }
    bool BlockDown(Clock::time_point now) const { return now < until; }
    bool NoteUp(Clock::time_point now, std::chrono::milliseconds max_hold) {
        if (last_down == Clock::time_point{} || now < last_down ||
            now - last_down >= std::chrono::seconds(15)) return false;
        const auto cap = std::max(std::chrono::milliseconds(20000), max_hold);
        hold = std::clamp(hold * 2, std::chrono::milliseconds(20000), cap);
        until = now + hold;
        return true;
    }
};
// Count only a shortage attributable to the *current lead*, not a cover
// frame or a late presenter. A three-frame ring is intentionally allowed.
inline bool ReserveRingShort(bool short_write, bool cover, bool draining,
                             bool matching_composition, bool matching_lead,
                             bool matching_multiplier, bool timely) {
    return short_write && !cover && !draining && matching_composition &&
           matching_lead && matching_multiplier && timely;
}
// Counts accepted JIT submission slots. A successful RuntimeEnd is not proof
// of scanout, and only actual distinct, non-exact JIT writes (path 3) count
// as interpolation or prediction. All copies/repeats/fallback paths are other.
enum class JitKind : std::uint8_t { kOther, kInterpolate, kPredict };
inline JitKind ClassifyJit(bool accepted, int path, bool distinct,
                           bool written, bool exact, bool interpolate) {
    if (!accepted || path != 3 || !distinct || !written || exact) return JitKind::kOther;
    return interpolate ? JitKind::kInterpolate : JitKind::kPredict;
}
// Inferred missing target grid slots, NOT proof of a dropped panel scanout.
// Clamp giant hitches so one discontinuity cannot overflow the summary.
inline std::uint32_t MissingGridSlots(std::int64_t delta_ns, std::int64_t grid_period_ns) {
    if (delta_ns <= 0 || grid_period_ns <= 0) return 0;
    const double periods = static_cast<double>(delta_ns) / static_cast<double>(grid_period_ns);
    return static_cast<std::uint32_t>(std::clamp(std::floor(periods + 0.5) - 1.0, 0.0, 120.0));
}
// Classification of a *proxy content timeline*, not actual optical-flow
// correctness nor SteamVR scanout. Compare only continuously rendered slots.
enum class MotionStep : std::uint8_t { kEven, kFreeze, kJump, kRewind };
inline MotionStep ClassifyMotionStep(std::int64_t step, std::int64_t target_gap, std::int64_t period) {
    if (period <= 0 || target_gap <= 0) return MotionStep::kEven;
    if (step <= -period / 4) return MotionStep::kRewind;
    if (step < period / 4) return MotionStep::kFreeze;
    if (static_cast<double>(step) - static_cast<double>(target_gap) > 0.75 * static_cast<double>(period))
        return MotionStep::kJump;
    return MotionStep::kEven;
}
inline std::int64_t ContentTime(std::int64_t previous, std::int64_t newest,
                                float fraction, bool interpolate, bool exact) {
    if (exact || previous <= 0 || newest <= previous) return newest;
    const std::int64_t delta = static_cast<std::int64_t>(
        std::llround(static_cast<double>(fraction) * static_cast<double>(newest - previous)));
    return (interpolate ? previous : newest) + delta;
}
} // namespace depthxr::dynamic_smooth

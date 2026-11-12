#pragma once
// Optional VectorXR Dynamic JIT policy: pure helpers, regression tested.
#include <algorithm>
#include <cmath>
#include <cstdint>
namespace depthxr::dynamic_smooth {
inline std::uint32_t Slots(double measured, std::uint32_t ceiling) {
    if (measured <= 0.0) return 2;
    return static_cast<std::uint32_t>(std::clamp(std::lround(measured), 2l, static_cast<long>(ceiling)));
}
// Prevent down-probes immediately below a configured reserve floor.
inline bool CanProbeDown(std::uint32_t current, std::uint32_t minimum) {
    return current > std::max(1u, minimum);
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
inline std::uint32_t LeadFloor(double work_ms, double interval_ms, double refresh_ms,
                               std::uint32_t reserve, std::uint32_t cap) {
    if (!reserve || !cap || refresh_ms <= 0.0) return 0;
    const double work = work_ms > 0.0 ? work_ms : (interval_ms > 0.0 ? interval_ms : refresh_ms);
    const double interval = interval_ms > 0.0 ? interval_ms : work;
    const double target = std::ceil((work + interval + 1.0) / refresh_ms) - 1.0 + reserve;
    return static_cast<std::uint32_t>(std::clamp(target, 1.0, static_cast<double>(cap)));
}
} // namespace depthxr::dynamic_smooth

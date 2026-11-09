#pragma once
// Tri-view B42: keep video memory below a safe share of the DXGI budget.
//
// Headset finding (9-10 Nov 2026): STALKER 2 + TriView BSODs (0x139) when the
// game process fills its VRAM budget (~10 GB on a 12 GB RTX 5070). Our own
// colour targets are small (13-56 MB per set); the growth comes from Unreal's
// per-size scene buffers (G-buffer, Lumen, DLSS histories ...) that each new
// view size allocates while the previous set is still alive. So before every
// new source-target set we estimate its cost per source pixel and refuse the
// build when "used now + estimate" would pass the limit. A refused build keeps
// the current image (TriView keeps drawing the live set).
//
// Pure logic, no D3D: unit-tested by TriViewVramGuardTests.cpp.
#include <array>
#include <cmath>
#include <cstdint>

namespace uevr::quadview::vram {

// Estimated bytes for every source pixel of a NEW set: our colour target (4 B)
// plus a generous allowance for Unreal's per-view-size scene buffers. Calibrate
// from the B42 "[TriView][VRAM] build" log lines (used before/after).
constexpr uint64_t bytes_per_source_pixel = 100;
// Per-eye-pixel cost of a headset resolution change: OpenXR colour swapchain
// (3 images x 4 B), Slate/UI and copy targets (allowance).
constexpr uint64_t bytes_per_eye_pixel = 24;
constexpr float default_limit_percent = 85.f;

using Extents = std::array<std::array<uint32_t, 2>, 4>;

inline uint64_t source_pixels(const Extents& e) {
    uint64_t px = 0;
    for (const auto& one : e) px += uint64_t(one[0]) * one[1];
    return px;
}

// Cost of building a new set with these extents (the old set stays alive until
// the new one is published, so the whole new set counts, not only the growth).
inline uint64_t build_estimate(const Extents& e) { return source_pixels(e) * bytes_per_source_pixel; }

inline uint64_t limit_bytes(uint64_t budget, float limit_percent) {
    if (!std::isfinite(limit_percent)) limit_percent = default_limit_percent;
    if (limit_percent < 50.f) limit_percent = 50.f;
    if (limit_percent > 98.f) limit_percent = 98.f;
    return uint64_t(double(budget) * double(limit_percent) / 100.0);
}

// budget == 0: no DXGI reading yet -> allow (never block TriView on missing data).
inline bool allows(uint64_t used, uint64_t budget, uint64_t estimate, float limit_percent) {
    if (budget == 0 || estimate == 0) return true;
    return used + estimate <= limit_bytes(budget, limit_percent);
}

// TriView source pixels (one shared periphery + two foveas) for an eye size and
// the menu fractions; mirrors make_layout's rounding closely enough for an estimate.
inline uint64_t triview_source_pixels(uint32_t eye_w, uint32_t eye_h, float crop_w, float crop_h,
                                      float context_scale, float density) {
    const auto r = [](double v) { return uint64_t(v < 1.0 ? 1.0 : std::round(v)); };
    const uint64_t ctx = r(eye_w * double(context_scale)) * r(eye_h * double(context_scale));
    const uint64_t fov = r(eye_w * double(crop_w) * density) * r(eye_h * double(crop_h) * density);
    return ctx + 2 * fov;
}

// Cost of switching the headset resolution from (old) to (new) while TriView runs.
inline uint64_t resolution_switch_estimate(uint32_t old_w, uint32_t old_h, uint32_t new_w, uint32_t new_h,
                                           float crop_w, float crop_h, float context_scale, float density) {
    // The low-resolution set stays alive until the new one is published, so the
    // whole new set counts, plus the growth of the per-eye resources.
    const uint64_t src_new = triview_source_pixels(new_w, new_h, crop_w, crop_h, context_scale, density);
    const uint64_t eye_new = uint64_t(new_w) * new_h * 2, eye_old = uint64_t(old_w) * old_h * 2;
    return src_new * bytes_per_source_pixel + (eye_new > eye_old ? (eye_new - eye_old) * bytes_per_eye_pixel : 0);
}

// B42: fewer distinct view sizes. Unreal keeps scene buffers per view size, so
// every 1-2 % slider step used to allocate a new set. Fractions snap to 0.05.
inline float snap_fraction(float v, float lo, float hi, float step = .05f) {
    if (!std::isfinite(v)) return v;
    float s = std::round(v / step) * step;
    if (s < lo) s = lo;
    if (s > hi) s = hi;
    return s;
}

} // namespace uevr::quadview::vram

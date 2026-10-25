#pragma once
#include <cstdint>
#include <cmath>

namespace stock_dibr {
enum class Layout : uint32_t { Invalid, Eye, Packed };
// UE aligns internal render allocations to a few pixels. Compare physical
// aspect, not output resolution; DLSS is allowed to change pixel density.
inline Layout layout(uint64_t w, uint32_t h, uint64_t packed_w, uint32_t out_h) {
    if (!w || !h || !packed_w || !out_h || packed_w % 2 || w > 32768 || h > 32768)
        return Layout::Invalid;
    const double scale = double(h) / out_h;
    if (scale < .20 || scale > 1.01) return Layout::Invalid;
    const double eye = double(packed_w / 2) * scale;
    const double eye_error = std::abs(double(w) - eye);
    const double packed_error = std::abs(double(w) - 2 * eye);
    const double tolerance = 8.0;
    if (eye_error <= tolerance && eye_error < packed_error) return Layout::Eye;
    if (packed_error <= tolerance) return Layout::Packed;
    return Layout::Invalid;
}
inline bool completed(uint64_t value, uint64_t wanted) {
    return wanted && value != UINT64_MAX && value >= wanted;
}
}

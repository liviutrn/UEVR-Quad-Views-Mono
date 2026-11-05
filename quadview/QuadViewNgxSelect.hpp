#pragma once
// Tri-view B7: portable periphery-depth selection rule (unit-tested on Linux).
#include <cstdint>

namespace uevr::quadview::ngx {
// The periphery's DLSS output size equals its view rectangle (eye x context
// scale, ~0.2); the foveas are ~2.5x larger. Accept a within 1/8 of b per axis.
inline bool matches_periphery(uint32_t out_w, uint32_t out_h, uint32_t want_w, uint32_t want_h) {
    if (!out_w || !out_h || !want_w || !want_h) return false;
    // (no identifier named near/far: Windows.h defines them as empty macros)
    const auto within = [](uint64_t a, uint64_t b) { return a * 8 >= b * 7 && a * 7 <= b * 8; };
    return within(out_w, want_w) && within(out_h, want_h);
}
} // namespace uevr::quadview::ngx

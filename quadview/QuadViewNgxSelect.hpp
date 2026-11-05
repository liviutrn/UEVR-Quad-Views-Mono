#pragma once
// Tri-view B11: portable periphery-depth selection rules (unit-tested on Linux).
//
// Identity: the periphery is the only DLSS evaluation whose output size equals
// the shared context view. make_layout() guarantees the two foveas never have
// a size inside the conflict window (see unique_context_factor), so an output
// size match is unambiguous; no timing or thread ownership is involved.
#include <cstdint>

namespace uevr::quadview::ngx {
namespace detail {
// a within pct percent of b, or within px pixels (UE may align view rects).
inline bool close(uint64_t a, uint64_t b, uint64_t pct, uint64_t px) {
    const uint64_t d = a > b ? a - b : b - a;
    return d <= px || d * 100 <= b * pct;
}
} // namespace detail

// A DLSS output (out) is the periphery when both axes are within 3 % / 4 px.
inline bool matches_periphery(uint32_t out_w, uint32_t out_h, uint32_t want_w, uint32_t want_h) {
    if (!out_w || !out_h || !want_w || !want_h) return false;
    return detail::close(out_w, want_w, 3, 4) && detail::close(out_h, want_h, 3, 4);
}

// A fovea size this close to the context could be confused with it.
inline bool focus_conflicts_context(uint32_t focus_w, uint32_t focus_h, uint32_t ctx_w, uint32_t ctx_h) {
    if (!focus_w || !focus_h || !ctx_w || !ctx_h) return false;
    return detail::close(ctx_w, focus_w, 6, 8) && detail::close(ctx_h, focus_h, 6, 8);
}

// Uniform scale for the context so that it can never match a fovea: 1 when no
// conflict, else the context width becomes 93 % of the fovea width (aspect kept,
// the geometry depends on the projection, not on the pixel count).
inline float unique_context_factor(uint32_t focus_w, uint32_t focus_h, uint32_t ctx_w, uint32_t ctx_h) {
    if (!focus_conflicts_context(focus_w, focus_h, ctx_w, ctx_h)) return 1.f;
    return 0.93f * float(focus_w) / float(ctx_w);
}
} // namespace uevr::quadview::ngx

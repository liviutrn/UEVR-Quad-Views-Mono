#pragma once
// Tri-view B14: synthetic ground-truth stereo scene for the periphery depth warp.
// The periphery (centre) camera sees a card 30 cm away (hand distance) in front of a
// wall 10 m away. Each eye sits 3.2 cm left/right of the centre camera with the
// same orientation and projection, so the eye-to-context homography is identity.
// The context colour stores its own texel-centre UV (R, G) and the object (B), so
// a rendered eye pixel tells exactly which periphery point it sampled. Expected
// values are exact ray intersections; pixels where the true answer is ambiguous for
// a depth buffer (rays passing behind the card, disocclusions, borders) are skipped.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <functional>
#include <vector>

namespace uevr::quadview::depth_scene {

constexpr uint32_t CW = 128, CH = 64;   // periphery colour and depth (same size)
constexpr uint32_t EW = 64, EH = 32;    // one output eye
constexpr double Near = 10.0, CardZ = 30.0, WallZ = 1000.0, HalfIpd = 3.2;
constexpr double CardU0 = 0.375, CardU1 = 0.625, CardV0 = 0.25, CardV1 = 0.75;
constexpr float CardId = 0.75f, WallId = 0.25f;

inline bool card_texel(uint32_t x, uint32_t y) {
    const double u = (x + .5) / CW, v = (y + .5) / CH;
    return u >= CardU0 && u < CardU1 && v >= CardV0 && v < CardV1;
}
// Reversed-Z with an infinite far plane, as UE: device depth = near / z.
inline float device_depth(uint32_t x, uint32_t y) { return float(Near / (card_texel(x, y) ? CardZ : WallZ)); }
inline std::array<float, 4> context_texel(uint32_t x, uint32_t y) {
    return {float((x + .5) / CW), float((y + .5) / CH), card_texel(x, y) ? CardId : WallId, 1.f};
}
inline double eye_x(unsigned eye) { return eye == 0 ? -HalfIpd : HalfIpd; }

// Shader constants that differ from zero (projection ax = ay = 1, centred).
struct DepthConstants {
    std::array<float, 4> eye_origin[2]{{float(eye_x(0)), 0, 0, 0}, {float(eye_x(1)), 0, 0, 0}};
    std::array<float, 4> projection{1.f, 0.f, 1.f, 0.f};          // ax, bx, ay, by
    std::array<float, 4> coefficients{0.f, float(Near), 1.f, 1.f}; // A, B, C, strength
};

enum class Kind { Skip, Card, Wall };
struct Expected { Kind kind{Kind::Skip}; double u{}, v{}; };

// Exact answer for eye pixel (px, py). Margin in periphery texels.
inline Expected expected(unsigned eye, uint32_t px, uint32_t py, double margin = 1.5) {
    const double u = (px + .5) / EW, v = (py + .5) / EH;
    const double rx = 2. * u - 1., ry = 1. - 2. * v, tx = eye_x(eye);
    const double mu = margin / CW, mv = margin / CH;
    const auto in_card = [&](double cu, double cv, double grow_u, double grow_v) {
        return cu >= CardU0 - grow_u && cu < CardU1 + grow_u && cv >= CardV0 - grow_v && cv < CardV1 + grow_v;
    };
    // context point of the eye ray at depth z: u(z) = 0.5 * ((tx + z*rx)/z + 1), v constant
    const auto cu = [&](double inv_z) { return .5 * (tx * inv_z + rx + 1.); };
    const double cv = .5 * (1. - ry);
    if (cv < 2. / CH || cv > 1. - 2. / CH) return {};
    const double card_u = cu(1. / CardZ);
    if (in_card(card_u, cv, 0, 0)) {
        if (!in_card(card_u, cv, -mu, -mv)) return {};
        return {Kind::Card, card_u, cv};
    }
    // Missed the card. Skip when the ray passes behind it anywhere up to infinity
    // (a depth buffer cannot tell a thin card from a solid one) or near its edge.
    const double a = cu(0.), b = card_u;
    const double lo = std::min(a, b) - mu, hi = std::max(a, b) + mu;
    if (cv >= CardV0 - mv && cv < CardV1 + mv && hi >= CardU0 && lo < CardU1) return {};
    const double wall_u = cu(1. / WallZ);
    if (wall_u < 2. / CW || wall_u > 1. - 2. / CW) return {};
    return {Kind::Wall, wall_u, cv};
}

struct Verdict {
    uint32_t card[2]{}, wall[2]{};
    double max_card_error_texels{}, max_wall_error_texels{}, max_v_error_texels{};
    uint32_t wrong_object{};
    bool ok(double tolerance_texels = 1.0) const {
        return card[0] >= 100 && card[1] >= 100 && wall[0] >= 400 && wall[1] >= 400 && !wrong_object &&
               max_card_error_texels <= tolerance_texels && max_wall_error_texels <= tolerance_texels &&
               max_v_error_texels <= tolerance_texels;
    }
};

// sample(eye, px, py) returns the rendered (R, G, B) of that eye pixel.
inline Verdict judge(const std::function<std::array<float, 3>(unsigned, uint32_t, uint32_t)>& sample) {
    Verdict r{};
    for (unsigned eye = 0; eye != 2; ++eye) for (uint32_t py = 0; py != EH; ++py) for (uint32_t px = 0; px != EW; ++px) {
        const auto e = expected(eye, px, py);
        if (e.kind == Kind::Skip) continue;
        const auto got = sample(eye, px, py);
        const double du = std::abs(got[0] - e.u) * CW, dv = std::abs(got[1] - e.v) * CH;
        const bool card = e.kind == Kind::Card;
        if (std::abs(got[2] - (card ? CardId : WallId)) > .05f) ++r.wrong_object;
        (card ? r.card : r.wall)[eye]++;
        auto& max_u = card ? r.max_card_error_texels : r.max_wall_error_texels;
        max_u = std::max(max_u, du);
        r.max_v_error_texels = std::max(r.max_v_error_texels, dv);
    }
    return r;
}

} // namespace uevr::quadview::depth_scene

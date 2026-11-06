// Tri-view B14: portable check of the ground-truth stereo scene (DepthWarpScene.hpp)
// against a line-by-line C++ copy of QuadViewComposite.hlsl WarpContextUv +
// ReadContext. It proves the scene's expectations and tolerances are right; the
// WARP test (QuadViewDepthWarpTest.cpp) then holds the REAL shader to the same scene.
// The two control runs (no reprojection, flipped sign) must fail the verdict.
#include "DepthWarpScene.hpp"
#include <iostream>
#include <stdexcept>
#include <string>
using namespace uevr::quadview::depth_scene;

struct F2 { float x, y; };
static float depth_at(F2 uv) {
    const float px = std::clamp(uv.x, 0.f, 1.f) * CW, py = std::clamp(uv.y, 0.f, 1.f) * CH;
    const uint32_t x = std::min(uint32_t(px), CW - 1), y = std::min(uint32_t(py), CH - 1);
    return std::clamp(device_depth(x, y), 0.f, 1.f);
}
static float inverse_depth_at(const DepthConstants& c, F2 uv) {
    return (c.coefficients[2] * depth_at(uv) - c.coefficients[0]) / c.coefficients[1];
}
static F2 warp(const DepthConstants& c, unsigned eye, F2 cuv, bool reproject, float& fill) {
    F2 uv = cuv; fill = 0;
    if (!reproject) return uv;
    const auto& t = c.eye_origin[eye]; const auto& p = c.projection;
    const F2 ray{(2.f * cuv.x - 1.f - p[1]) / p[0], (1.f - 2.f * cuv.y - p[3]) / p[2]};
    const F2 k{.5f * p[0] * (t[0] - ray.x * t[2]) * c.coefficients[3], -.5f * p[2] * (t[1] - ray.y * t[2]) * c.coefficients[3]};
    const float sMax = std::min(std::abs(c.coefficients[2] / c.coefficients[1]), .125f), ds = sMax / 24.f;
    F2 previousUv{cuv.x + k.x * sMax, cuv.y + k.y * sMax};
    float previousF = -1.f, previousInverse = 0.f; bool found = false;
    for (uint32_t i = 0; i <= 24u && !found; ++i) {
        const float s = sMax - ds * float(i);
        const F2 cc{cuv.x + k.x * s, cuv.y + k.y * s};
        const bool inside = cc.x >= 0 && cc.y >= 0 && cc.x <= 1 && cc.y <= 1;
        const float inverseZ = inside ? inverse_depth_at(c, cc) : 0.f;
        const float f = inverseZ - s;
        if (inside && f >= 0.f) {
            found = true;
            if (i == 0u || previousF <= -.5f) uv = cc;
            else if (previousF > -.5f && inverseZ > previousInverse * 1.25f + 2.f * ds) {
                uv = {cuv.x + k.x * (s + 4.f * ds), cuv.y + k.y * (s + 4.f * ds)}; fill = 1;
            } else {
                const float w = std::clamp(previousF / std::min(previousF - f, -1.e-6f), 0.f, 1.f);
                uv = {previousUv.x + (cc.x - previousUv.x) * w, previousUv.y + (cc.y - previousUv.y) * w};
            }
        }
        previousF = inside ? f : -1.f; previousUv = cc; previousInverse = inverseZ;
    }
    return uv;
}
// Bilinear sample of the context texture after AtlasUv's texel-centre clamp.
static std::array<float, 3> sample_context(F2 uv) {
    const float tx = std::clamp(std::clamp(uv.x, 0.f, 1.f) * CW, .5f, CW - .5f) - .5f;
    const float ty = std::clamp(std::clamp(uv.y, 0.f, 1.f) * CH, .5f, CH - .5f) - .5f;
    const uint32_t x0 = uint32_t(tx), y0 = uint32_t(ty);
    const uint32_t x1 = std::min(x0 + 1, CW - 1), y1 = std::min(y0 + 1, CH - 1);
    const float fx = tx - x0, fy = ty - y0;
    std::array<float, 3> out{};
    for (int ch = 0; ch < 3; ++ch) {
        const float a = context_texel(x0, y0)[ch] * (1 - fx) + context_texel(x1, y0)[ch] * fx;
        const float b = context_texel(x0, y1)[ch] * (1 - fx) + context_texel(x1, y1)[ch] * fx;
        out[ch] = a * (1 - fy) + b * fy;
    }
    return out;
}
static Verdict run(bool reproject, float strength) {
    DepthConstants c{}; c.coefficients[3] = strength;
    return judge([&](unsigned eye, uint32_t px, uint32_t py) {
        float fill{};
        const F2 cuv{(px + .5f) / EW, (py + .5f) / EH}; // identity eye-to-context homography
        return sample_context(warp(c, eye, cuv, reproject, fill));
    });
}
static void print(const char* name, const Verdict& v) {
    std::cout << name << ": card " << v.card[0] << "/" << v.card[1] << " wall " << v.wall[0] << "/" << v.wall[1]
              << " max card err " << v.max_card_error_texels << " wall err " << v.max_wall_error_texels
              << " v err " << v.max_v_error_texels << " wrong object " << v.wrong_object << (v.ok() ? " PASS\n" : " FAIL\n");
}
int main() {
    const auto good = run(true, 1.f), mono = run(false, 1.f), flipped = run(true, -1.f);
    print("depth warp", good); print("control: no reprojection", mono); print("control: flipped sign", flipped);
    if (!good.ok() || mono.ok() || flipped.ok()) { std::cerr << "depth warp scene check failed\n"; return 1; }
    return 0;
}

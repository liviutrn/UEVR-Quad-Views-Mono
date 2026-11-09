// Tri-view B42: VRAM guard arithmetic (pure logic).
#include "TriViewVramGuard.hpp"
#include <iostream>
#include <stdexcept>
#include <string>
using namespace uevr::quadview::vram;
static void check_at(bool b, int line) { if (!b) throw std::runtime_error("vram guard assertion at line " + std::to_string(line)); }
#define check(b) check_at((b), __LINE__)
constexpr uint64_t MB = 1ull << 20;

int main() try {
    // The B41 crash (log 10 Nov 01:00:12): 8350 / 10187 MB, build of 1792x1984 foveas
    // + 1218x968 periphery. B42 must refuse it at the default 85 %.
    const Extents crash{{{1218, 968}, {0, 0}, {1792, 1984}, {1792, 1984}}};
    check(!allows(8350 * MB, 10187 * MB, build_estimate(crash), default_limit_percent));
    // Same build with the menu VRAM (6359 MB): allowed.
    check(allows(6359 * MB, 11175 * MB, build_estimate(crash), default_limit_percent));
    // No DXGI reading yet: never block.
    check(allows(0, 0, build_estimate(crash), default_limit_percent));
    // Limit is clamped to 50..98 %.
    check(limit_bytes(1000, 10.f) == 500 && limit_bytes(1000, 200.f) == 980);
    // Resolution switch 0.3 -> 1.0 (4060x3228 per eye, focus .6x.6, periphery .3):
    const auto sw = resolution_switch_estimate(1218, 968, 4060, 3228, .6f, .6f, .3f, 1.f);
    check(sw > 1400 * MB && sw < 1900 * MB);
    check(allows(5500 * MB, 10200 * MB, sw, default_limit_percent));
    check(!allows(8000 * MB, 10200 * MB, sw, default_limit_percent));
    // Snapping: 0.62 -> 0.60, 0.63 -> 0.65, clamped into the slider range.
    check(std::abs(snap_fraction(.62f, .05f, 1.f) - .60f) < 1e-5f);
    check(std::abs(snap_fraction(.63f, .05f, 1.f) - .65f) < 1e-5f);
    check(std::abs(snap_fraction(.01f, .05f, 1.f) - .05f) < 1e-5f);
    check(std::abs(snap_fraction(.52f, .05f, .50f) - .50f) < 1e-5f);
    std::cout << "triview vram guard: ok\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr << e.what() << "\n";
    return 1;
}

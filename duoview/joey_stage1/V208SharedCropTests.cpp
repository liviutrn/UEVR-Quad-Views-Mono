// v208 CPU contract for "Same image for both eyes": the shared rectangle that
// both OpenXR views reference must cover both eye crops of the Mono image and
// carry exactly the FOV of its integer-pixel rectangle (same convention as
// projection_crop), so every pixel is still shown in the same direction.
#include "MonoRenderingPolicy.hpp"
#include <cmath>
#include <cstdio>
#include <cstdlib>

static int failures = 0;
#define EXPECT(cond, msg) do { if (!(cond)) { std::printf("FAIL: %s\n", msg); ++failures; } } while (0)

static bool close_to(float a, float b) { return std::abs(a - b) <= 1e-5f * (1.f + std::abs(b)); }

static void check_case(const char* name, const std::array<uevr::mono::Eye, 2>& eyes, uint32_t w, uint32_t h) {
    const auto g = uevr::mono::geometry(eyes);
    EXPECT(g.has_value(), name);
    if (!g) return;
    const auto c0 = uevr::mono::projection_crop(*g, 0, w, h);
    const auto c1 = uevr::mono::projection_crop(*g, 1, w, h);
    EXPECT(c0 && c1, name);
    if (!c0 || !c1) return;
    const auto s = uevr::mono::shared_projection_crop(*c0, *c1);
    EXPECT(s.has_value(), name);
    if (!s) return;
    for (const auto* c : {&*c0, &*c1}) {
        EXPECT(s->x <= c->x && s->y <= c->y, "shared rect must start at or before each crop");
        EXPECT(s->x + s->width >= c->x + c->width && s->y + s->height >= c->y + c->height,
               "shared rect must end at or after each crop");
        EXPECT(s->fov[0] <= c->fov[0] && s->fov[1] >= c->fov[1] &&
               s->fov[2] >= c->fov[2] && s->fov[3] <= c->fov[3], "shared FOV must contain each eye FOV");
    }
    EXPECT(s->x + s->width <= w && s->y + s->height <= h, "shared rect must stay inside one eye half");
    // Exact pixel <-> tangent convention of projection_crop.
    EXPECT(close_to(s->fov[0], (2.f * s->x / w - 1.f) * g->horizontal), "left tangent matches pixel rect");
    EXPECT(close_to(s->fov[1], (2.f * (s->x + s->width) / w - 1.f) * g->horizontal), "right tangent matches pixel rect");
    EXPECT(close_to(s->fov[2], (1.f - 2.f * s->y / h) * g->vertical), "up tangent matches pixel rect");
    EXPECT(close_to(s->fov[3], (1.f - 2.f * (s->y + s->height) / h) * g->vertical), "down tangent matches pixel rect");
    std::printf("%s: eye0 %ux%u@%u,%u eye1 %ux%u@%u,%u shared %ux%u@%u,%u\n", name,
        c0->width, c0->height, c0->x, c0->y, c1->width, c1->height, c1->x, c1->y,
        s->width, s->height, s->x, s->y);
}

int main() {
    // PSVR2-like asymmetric per-eye FOV tangents (L, R, U, D), 72 mm IPD.
    const std::array<uevr::mono::Eye, 2> straight{{
        {{0.f, 0.f, 0.f, 1.f}, {-0.036f, 1.6f, 0.f}, {-1.43f, 1.06f, 1.19f, -1.32f}},
        {{0.f, 0.f, 0.f, 1.f}, {0.036f, 1.6f, 0.f}, {-1.06f, 1.43f, 1.19f, -1.32f}}}};
    check_case("straight eyes 3840x3100", straight, 3840, 3100);
    // Canted displays: each eye yawed 2 degrees outward.
    const float s = std::sin(0.5f * 2.f * 3.14159265f / 180.f), c = std::cos(0.5f * 2.f * 3.14159265f / 180.f);
    const std::array<uevr::mono::Eye, 2> canted{{
        {{0.f, s, 0.f, c}, {-0.036f, 1.6f, 0.f}, {-1.43f, 1.06f, 1.19f, -1.32f}},
        {{0.f, -s, 0.f, c}, {0.036f, 1.6f, 0.f}, {-1.06f, 1.43f, 1.19f, -1.32f}}}};
    check_case("canted eyes 5000x5000", canted, 5000, 5000);
    // Degenerate input is rejected, never submitted.
    uevr::mono::ProjectionCrop empty{};
    uevr::mono::ProjectionCrop one{10, 10, 100, 100, {-1.f, 1.f, 1.f, -1.f}};
    EXPECT(!uevr::mono::shared_projection_crop(empty, one), "empty crop rejected");
    uevr::mono::ProjectionCrop nan_crop = one; nan_crop.fov[0] = std::nanf("");
    EXPECT(!uevr::mono::shared_projection_crop(nan_crop, one), "non-finite FOV rejected (first)");
    EXPECT(!uevr::mono::shared_projection_crop(one, nan_crop), "non-finite FOV rejected (second)");
    if (failures) { std::printf("%d failure(s)\n", failures); return 1; }
    std::printf("PASS: v208 shared rectangle covers both eye crops with its exact FOV\n");
    return 0;
}

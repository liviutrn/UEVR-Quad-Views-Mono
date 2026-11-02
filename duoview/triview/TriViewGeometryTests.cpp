// Tri-View Stage 1: CPU checks that the engine-side projections and the compositor map agree.
#include "TriViewGeometry.hpp"
#include <array>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <string>

using Matrix = std::array<std::array<double, 4>, 4>; // m[col][row], like GLM / UEVR

static void expect(bool ok, const char* what) {
    if (!ok) throw std::runtime_error(what);
}
static bool approx(double a, double b, double eps = 1e-5) { return std::abs(a - b) <= eps; }

// Joey's OpenXR projection (OpenXR.cpp): x_ndc = (2*tx - R - L)/(R - L), clip.w = z.
static Matrix joey_projection(const uevr::triview::Tans& t, double near_z = 10.0) {
    Matrix m{};
    m[0][0] = 2.0 / (t.right - t.left);
    m[1][1] = 2.0 / (t.top - t.bottom);
    m[2][0] = -(t.right + t.left) / double(t.right - t.left);
    m[2][1] = -(t.top + t.bottom) / double(t.top - t.bottom);
    m[2][3] = 1.0;
    m[3][2] = near_z;
    return m;
}
// NDC of a view-space direction with tangents (tx, ty) at depth z = 1.
static std::array<double, 2> ndc(const Matrix& m, double tx, double ty) {
    const double x = m[0][0] * tx + m[1][0] * ty + m[2][0] + m[3][0];
    const double y = m[0][1] * tx + m[1][1] * ty + m[2][1] + m[3][1];
    const double w = m[0][3] * tx + m[1][3] * ty + m[2][3] + m[3][3];
    return {x / w, y / w};
}

int main() try {
    namespace tv = uevr::triview;
    // PSVR2-like asymmetric, mirrored eyes.
    const tv::Tans left{-1.30f, 1.05f, 1.25f, -1.30f};
    const tv::Tans right{-1.05f, 1.30f, 1.25f, -1.30f};
    const auto read_back = tv::tans_from_projection(joey_projection(left));
    expect(read_back && approx(read_back->left, left.left) && approx(read_back->right, left.right) &&
           approx(read_back->top, left.top) && approx(read_back->bottom, left.bottom),
           "tangents read back from Joey's projection");

    const auto layout = tv::make_layout(2000, 2040, left, right, .5f);
    expect(layout.has_value(), "layout");
    const auto& l = *layout;
    expect(l.fovea_width == 1000 && l.fovea_height == 1020, "fovea is half of each eye axis");
    expect(approx(l.periphery.left, -1.30) && approx(l.periphery.right, 1.30) &&
           approx(l.periphery.top, 1.25) && approx(l.periphery.bottom, -1.30), "union frustum");
    expect(l.periphery_x == 0 && l.periphery_width == 1106 && l.periphery_height == 1020,
           "periphery image at its own target origin, at the requested density");

    // Fovea crop: the window corners land exactly on the viewport edges.
    auto fovea = joey_projection(left);
    tv::apply_fovea_projection(fovea, l);
    const double w0 = left.right - left.left, h0 = left.top - left.bottom;
    const auto a = ndc(fovea, left.left + .25 * w0, left.top - .25 * h0);
    const auto b = ndc(fovea, left.left + .75 * w0, left.top - .75 * h0);
    expect(approx(a[0], -1) && approx(a[1], 1) && approx(b[0], 1) && approx(b[1], -1), "fovea window maps to full viewport");
    expect(fovea[2][3] == 1.0 && fovea[3][2] == 10.0, "depth and w rows untouched");

    // Periphery projection covers the union frustum exactly.
    auto periphery = joey_projection(left);
    tv::apply_periphery_projection(periphery, l);
    const auto c = ndc(periphery, l.periphery.left, l.periphery.top);
    const auto d = ndc(periphery, l.periphery.right, l.periphery.bottom);
    expect(approx(c[0], -1) && approx(c[1], 1) && approx(d[0], 1) && approx(d[1], -1), "periphery = union frustum");

    // End-to-end: for every eye pixel, compositor periphery UV == where the engine rendered that ray.
    for (int eye = 0; eye < 2; ++eye) {
        const auto& e = l.eye[eye];
        const auto map = tv::periphery_map(l, eye);
        for (double u : {0.0, 0.1, 0.5, 0.93, 1.0}) {
            for (double v : {0.0, 0.37, 1.0}) {
                const double tx = e.left + u * (e.right - e.left);
                const double ty = e.top - v * (e.top - e.bottom);
                const auto p = ndc(periphery, tx, ty); // same direction from the centre camera (parallel eyes)
                const double pu = (p[0] + 1) * .5, pv = (1 - p[1]) * .5;
                expect(approx(map.ax * u + map.bx, pu, 1e-4) && approx(map.ay * v + map.by, pv, 1e-4),
                       "compositor map matches the periphery render");
                expect(pu >= -1e-5 && pu <= 1 + 1e-5 && pv >= -1e-5 && pv <= 1 + 1e-5,
                       "every eye ray is inside the periphery");
            }
        }
    }

    expect(!tv::make_layout(2000, 2040, left, right, 2.f), "invalid scale rejected");
    expect(!tv::make_layout(2000, 2040, {1, -1, 1, -1}, right, .5f), "invalid frustum rejected");
    const auto full = tv::make_layout(2000, 2040, left, right, 1.f);
    expect(full && full->periphery_width == 2000 && full->periphery_height == 2040,
           "periphery never exceeds the free half of the main target");
    std::puts("Tri-View geometry tests passed.");
    return 0;
} catch (const std::exception& e) {
    std::fprintf(stderr, "FAILED: %s\n", e.what());
    return 1;
}

#include "DuoViewStereoGeometry.hpp"

#include <cassert>
#include <limits>

using namespace uevr::duoview::stereo;

namespace {

void close(double actual, double expected) {
    assert(std::abs(actual - expected) < 1.e-6);
}

std::array<float, 16> projection() {
    // The real render projection can be wider and offset relative to the
    // tight eye frustum union, e.g. a Mono projection with game FOV matching.
    return {0.54f, 0, 0, 0, 0, 0.74f, 0, 0, 0.05f, -0.09f, -0.002f, 1, 0, 0, 8, 0};
}

std::array<float, 4> yaw(double angle) {
    return {0.f, static_cast<float>(std::sin(angle * .5)), 0.f,
        static_cast<float>(std::cos(angle * .5))};
}

void check_infinity_projection(const Geometry& g, const std::array<float, 16>& p,
        const std::array<Eye, 2>& eyes, double cant) {
    for (size_t eye = 0; eye != eyes.size(); ++eye) {
        const auto& [left, right, up, down] = eyes[eye].tangents;
        const auto& h = g.context_h[eye];
        const double c = std::cos(eye == 0 ? 0. : cant), s = std::sin(eye == 0 ? 0. : cant);
        for (double u : {0., .31, .5, 1.}) for (double v : {0., .68, .5, 1.}) {
            const double local_x = left + (right - left) * u;
            const double local_y = up + (down - up) * v;
            // OpenXR rays have -Z forward. Rotate directly, then project
            // with the Mono matrix using positive forward depth.
            const double forward = c + s * local_x;
            const double center_x = c * local_x - s;
            const double hx = h[0] * u + h[1] * v + h[2];
            const double hy = h[4] * u + h[5] * v + h[6];
            const double hz = h[8] * u + h[9] * v + h[10];
            close(hx / hz, (1. + p[8] + p[0] * center_x / forward) * .5);
            close(hy / hz, (1. - p[9] - p[5] * local_y / forward) * .5);
        }
    }
}

void check_soft_depth() {
    constexpr size_t width=256;
    constexpr double k=.1, softness=.5, slope=softness/(k*width);
    std::array<double,width> raw{};
    for (size_t x=0;x<width;++x) raw[x]=x>=100 && x<140 ? 1. : .05;
    auto filtered=raw;
    for (size_t step=1;step<width && double(step-1)*slope<1.;step*=2) {
        auto next=filtered;
        for (size_t x=0;x<width;++x) {
            if (x>=step) next[x]=(std::max)(next[x],filtered[x-step]-step*slope);
            if (x+step<width) next[x]=(std::max)(next[x],filtered[x+step]-step*slope);
        }
        filtered=next;
    }
    for (size_t x=0;x<width;++x) {
        double exact=raw[x];
        for (size_t j=0;j<width;++j)
            exact=(std::max)(exact,raw[j]-slope*std::abs(double(x)-double(j)));
        close(filtered[x],exact);
        assert(filtered[x]>=raw[x]);
        if (x) assert(std::abs(filtered[x]-filtered[x-1])<=slope+1.e-8);
    }
    close(filtered.front(),raw.front());
    close(filtered.back(),raw.back());
    const auto pull=[](const auto& field,double base,double shift) {
        double u=base;
        for (int i=0;i<6;++i) {
            const double x=(std::clamp)(u*width-.5,0.,double(width-1));
            const auto lo=static_cast<size_t>(x);
            const double d=std::lerp(field[lo],field[(std::min)(lo+1,width-1)],x-lo);
            u=base+shift*d;
        }
        return u;
    };
    for (double shift : {-k,k}) {
        double previous_soft=pull(filtered,0.,shift), previous_raw=pull(raw,0.,shift);
        bool raw_fold=false;
        for (int i=1;i<=8192;++i) {
            const auto x=double(i)/8192.;
            const auto soft=pull(filtered,x,shift), unconditioned=pull(raw,x,shift);
            assert(soft>previous_soft);
            raw_fold|=unconditioned<previous_raw;
            previous_soft=soft;
            previous_raw=unconditioned;
        }
        assert(raw_fold);
    }
}

} // namespace

int main() {
    check_soft_depth();
    auto p = projection();
    constexpr double stage_yaw = .63;
    constexpr double cant = .13;
    constexpr double baseline_m = .072;
    constexpr double world_units_per_metre = 113.;
    constexpr double strength = .8;
    std::array<Eye, 2> eyes{{
        {yaw(stage_yaw), {1.1f, 1.6f, -.23f}, {-1.2f, .88f, .85f, -1.01f}},
        {yaw(stage_yaw + cant), {static_cast<float>(1.1 + baseline_m * std::cos(stage_yaw)),
            1.61f, static_cast<float>(-.23 - baseline_m * std::sin(stage_yaw))},
            {-.97f, 1.24f, .9f, -1.12f}}
    }};
    const auto geometry = make_geometry(p, eyes, world_units_per_metre, strength);
    assert(geometry);
    check_infinity_projection(*geometry, p, eyes, cant);
    close(geometry->world_to_meters, world_units_per_metre);
    close(geometry->depth_coefficients[0], p[10]);
    close(geometry->depth_coefficients[1], p[14]);
    close(geometry->depth_coefficients[2], p[11]);
    const auto shift = .5 * p[0] * .5 * baseline_m * world_units_per_metre * strength;
    close(geometry->k[0], -shift);
    close(geometry->k[1], shift);

    const auto zero = make_geometry(p, eyes, world_units_per_metre, 0.);
    assert(zero && zero->context_h == geometry->context_h);
    assert(zero->k[0] == 0.f && zero->k[1] == 0.f);

    assert(!make_geometry(p, eyes, 0., strength));
    auto invalid_eyes = eyes;
    invalid_eyes[1].orientation = {};
    assert(!make_geometry(p, invalid_eyes, world_units_per_metre, strength));
    invalid_eyes = eyes;
    invalid_eyes[0].tangents[0] = invalid_eyes[0].tangents[1];
    assert(!make_geometry(p, invalid_eyes, world_units_per_metre, strength));
    invalid_eyes = eyes;
    invalid_eyes[0].position[0] = std::numeric_limits<float>::infinity();
    assert(!make_geometry(p, invalid_eyes, world_units_per_metre, strength));
    p[14] = 0.f;
    assert(!make_geometry(p, eyes, world_units_per_metre, strength));
}

#pragma once

#include "QuadViewGeometry.hpp"

namespace uevr::duoview::stereo {

struct Eye {
    std::array<float, 4> orientation; // OpenXR stage quaternion x, y, z, w
    std::array<float, 3> position;    // OpenXR stage metres
    std::array<float, 4> tangents;   // left, right, up, down
};

struct Geometry {
    // UV at infinity: H * (u, v, 1), divided by its z. Rows padded to float4.
    std::array<std::array<float, 12>, 2> context_h{};
    // M1 projects translation onto the center camera's horizontal axis. A
    // constant k keeps the 1D inverse warp compatible with a horizontal slope bound.
    std::array<float, 2> k{};
    std::array<float, 3> depth_coefficients{}; // A, B, C: inverse Z = (C*d - A)/B
    float world_to_meters{}; // engine units per metre, including world scale
};

inline std::optional<Geometry> make_geometry(
        const std::array<float, 16>& center_projection,
        const std::array<Eye, 2>& eyes, double world_to_meters, double strength) {
    if (!std::isfinite(world_to_meters) || world_to_meters <= 0. ||
        !std::isfinite(strength) || strength < 0. || strength > 2.) return {};

    std::array<std::array<float, 4>, 2> orientations{};
    std::array<std::array<float, 16>, 2> eye_projections{};
    for (size_t i = 0; i != eyes.size(); ++i) {
        const auto& eye = eyes[i];
        double norm_squared = 0.;
        for (float v : eye.orientation) norm_squared += double(v) * v;
        if (!std::isfinite(norm_squared) || std::abs(norm_squared - 1.) > 1.e-3) return {};
        const double norm = std::sqrt(norm_squared);
        for (size_t j = 0; j != eye.orientation.size(); ++j)
            orientations[i][j] = static_cast<float>(eye.orientation[j] / norm);
        for (float v : eye.position) if (!std::isfinite(v)) return {};
        for (float v : eye.tangents) if (!std::isfinite(v)) return {};
        const auto& [left, right, up, down] = eye.tangents;
        const double horizontal = double(right) - left;
        const double vertical = double(up) - down;
        if (horizontal <= 1.e-6 || vertical <= 1.e-6) return {};
        auto& p = eye_projections[i];
        p[0] = static_cast<float>(2. / horizontal);
        p[5] = static_cast<float>(2. / vertical);
        p[8] = static_cast<float>(-(double(right) + left) / horizontal);
        p[9] = static_cast<float>(-(double(up) + down) / vertical);
        p[11] = 1.f;
    }

    quadview::Layout layout{};
    if (!quadview::apply_shared_context(layout, eye_projections[0], eye_projections[1],
            &orientations[0], &orientations[1])) return {};

    // Take half of the eye baseline in the optical basis of the left eye.
    // The same center translation applies to both eyes, so XYZ head gains
    // cancel. World scale still applies to the physical eye baseline.
    const auto& [x, y, z, w] = orientations[0];
    const std::array<double, 3> right_axis{
        1. - 2. * (double(y) * y + double(z) * z),
        2. * (double(x) * y + double(z) * w),
        2. * (double(x) * z - double(y) * w)};
    double half_baseline = 0.;
    for (size_t axis = 0; axis != right_axis.size(); ++axis)
        half_baseline += right_axis[axis] * (double(eyes[1].position[axis]) - eyes[0].position[axis]);
    half_baseline *= world_to_meters * .5;
    const std::array<std::array<double, 3>, 2> origins{{
        {-half_baseline, 0., 0.}, {half_baseline, 0., 0.}}};

    std::array<double, 16> projection{};
    std::copy(center_projection.begin(), center_projection.end(), projection.begin());
    if (!quadview::configure_depth_geometry(layout, projection, origins, strength)) return {};

    // TriView's H maps into its tight frustum union. Retarget its output to
    // the actual Mono projection frozen with the draw, including FOV scaling.
    const auto& [union_ax, union_bx, union_ay, union_by] = layout.context_projection;
    const auto& [ax, bx, ay, by] = layout.depth_projection;
    const double sx = ax / union_ax, sy = ay / union_ay;
    const double ox = (1. + bx - sx * (1. + union_bx)) * .5;
    const double oy = (1. - by - sy * (1. - union_by)) * .5;
    if (!std::isfinite(sx) || !std::isfinite(sy) || sx <= 0. || sy <= 0. ||
        !std::isfinite(ox) || !std::isfinite(oy)) return {};

    Geometry result{};
    result.context_h = layout.context_h;
    for (auto& h : result.context_h) {
        for (size_t col = 0; col != 3; ++col) {
            h[col] = static_cast<float>(sx * h[col] + ox * h[8 + col]);
            h[4 + col] = static_cast<float>(sy * h[4 + col] + oy * h[8 + col]);
            if (!std::isfinite(h[col]) || !std::isfinite(h[4 + col]) ||
                !std::isfinite(h[8 + col])) return {};
        }
    }
    const auto shift = static_cast<float>(.5 * ax * half_baseline * strength);
    result.k = {-shift, shift};
    std::copy_n(layout.depth_coefficients.begin(), 3, result.depth_coefficients.begin());
    result.world_to_meters = static_cast<float>(world_to_meters);
    if (!std::isfinite(shift) || !std::isfinite(result.world_to_meters) ||
        result.world_to_meters <= 0.f) return {};
    return result;
}

} // namespace uevr::duoview::stereo

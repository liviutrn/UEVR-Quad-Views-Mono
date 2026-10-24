#include "ManualDibrProjection.hpp"

#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

using namespace uevr::duoview::dibr;

namespace {

constexpr double kPi = 3.141592653589793238462643383279502884;
constexpr double kWorldToMeters = 100.0;

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

std::array<double, 16> perspective(double left, double right, double up, double down,
    double near_plane) {
    std::array<double, 16> projection{}; // column-major GLM matrix
    projection[0] = 2.0 / (right - left);
    projection[5] = 2.0 / (up - down);
    projection[8] = -(right + left) / (right - left);
    projection[9] = -(up + down) / (up - down);
    projection[11] = 1.0;       // clip W = +view Z
    projection[14] = near_plane; // GLM [3][2], infinite reversed-Z
    return projection;
}

NativeEyeFovAngles angles_from_tangents(double left, double right, double up, double down) {
    return {std::atan(left), std::atan(right), std::atan(up), std::atan(down)};
}

std::array<double, 16> rigid_target_from_source(double eye_x, double eye_y,
    double eye_z, double yaw_radians) {
    // A target eye located at `eye_*` with a world/source-space yaw of yaw_radians.
    // Convert source points into target view space using R_y(-yaw) and -R^T eye.
    const double c = std::cos(yaw_radians);
    const double s = std::sin(yaw_radians);
    std::array<double, 16> transform{};
    transform[0] = c;
    transform[2] = s;
    transform[5] = 1.0;
    transform[8] = -s;
    transform[10] = c;
    transform[12] = -c * eye_x + s * eye_z;
    transform[13] = -eye_y;
    transform[14] = -s * eye_x - c * eye_z;
    transform[15] = 1.0;
    return transform;
}

std::array<double, 4> source_clip(const std::array<double, 16>& projection,
    double x, double y, double z) {
    return {
        projection[0] * x + projection[8] * z,
        projection[5] * y + projection[9] * z,
        projection[14],
        z,
    };
}

std::array<double, 4> apply_row_major(const std::array<float, 16>& matrix,
    const std::array<double, 4>& vector) {
    std::array<double, 4> result{};
    for (size_t row = 0; row != 4; ++row)
        for (size_t column = 0; column != 4; ++column)
            result[row] += static_cast<double>(matrix[row * 4 + column]) * vector[column];
    return result;
}

std::array<double, 4> transform_point(const std::array<double, 16>& column_major,
    double x, double y, double z) {
    return {
        column_major[0] * x + column_major[4] * y + column_major[8] * z + column_major[12],
        column_major[1] * x + column_major[5] * y + column_major[9] * z + column_major[13],
        column_major[2] * x + column_major[6] * y + column_major[10] * z + column_major[14],
        1.0,
    };
}

std::array<double, 4> project_target(const NativeEyeFovAngles& fov, double near_plane,
    const std::array<double, 4>& point) {
    const double left = std::tan(fov.left);
    const double right = std::tan(fov.right);
    const double up = std::tan(fov.up);
    const double down = std::tan(fov.down);
    const double sx = 2.0 / (right - left);
    const double sy = 2.0 / (up - down);
    return {
        sx * point[0] - (right + left) / (right - left) * point[2],
        sy * point[1] - (up + down) / (up - down) * point[2],
        near_plane,
        point[2],
    };
}

std::array<double, 4> project_target_direction(const NativeEyeFovAngles& fov,
    const std::array<double, 16>& target_from_source, double source_x,
    double source_y, double source_z) {
    // Direction vectors have homogeneous W=0, so the rigid eye translation
    // must not move the infinite-distance sky ray.
    const double x = target_from_source[0] * source_x +
        target_from_source[4] * source_y + target_from_source[8] * source_z;
    const double y = target_from_source[1] * source_x +
        target_from_source[5] * source_y + target_from_source[9] * source_z;
    const double z = target_from_source[2] * source_x +
        target_from_source[6] * source_y + target_from_source[10] * source_z;
    const double left = std::tan(fov.left);
    const double right = std::tan(fov.right);
    const double up = std::tan(fov.up);
    const double down = std::tan(fov.down);
    return {
        2.0 / (right - left) * x - (right + left) / (right - left) * z,
        2.0 / (up - down) * y - (up + down) / (up - down) * z,
        0.0,
        z,
    };
}

void require_close(double actual, double expected, double tolerance, const char* message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(message);
}

void require_clip_matches(const ManualDibrProjectionInput& input,
    const ManualDibrClipTransform& built, double x, double y, double z,
    double tolerance = 2.0e-5) {
    const auto source = source_clip(input.sourceProjectionColumnMajor, x, y, z);
    const auto actual = apply_row_major(built.sourceClipToTargetClipRowMajor, source);
    const auto target_view = transform_point(input.targetFromSourceColumnMajor, x, y, z);
    const auto expected = project_target(input.targetFov,
        input.sourceProjectionColumnMajor[14], target_view);
    const double float_tolerance = tolerance * (std::max)(1.0, std::abs(expected[3]));
    for (size_t component = 0; component != 4; ++component) {
        if (!std::isfinite(actual[component]) ||
            std::abs(actual[component] - expected[component]) > float_tolerance) {
            throw std::runtime_error("Built source-clip transform mismatch at component " +
                std::to_string(component) + ": actual=" + std::to_string(actual[component]) +
                " expected=" + std::to_string(expected[component]));
        }
    }
}

} // namespace

int main() try {
    constexpr double near_plane = 10.0; // 10 cm at the test's 100 UE units / meter
    const double source_left = -1.25;
    const double source_right = 0.75;
    const double source_up = 0.95;
    const double source_down = -0.85;
    const double target_left = -1.0;
    const double target_right = 0.9;
    const double target_up = 0.8;
    const double target_down = -1.1;
    const auto source_projection = perspective(source_left, source_right,
        source_up, source_down, near_plane);
    const auto target_fov = angles_from_tangents(target_left, target_right,
        target_up, target_down);

    // Identity eye pose and matching asymmetric FOV must produce the exact
    // identity homogeneous mapping, including raw reversed-Z.
    ManualDibrProjectionInput identity_input{
        source_projection,
        angles_from_tangents(source_left, source_right, source_up, source_down),
        rigid_target_from_source(0.0, 0.0, 0.0, 0.0),
    };
    ManualDibrClipTransform identity_output{};
    ProjectionBuildError error{};
    require(build_manual_dibr_clip_transform(identity_input, identity_output, &error),
        "Matching source and target projection must build");
    require(error == ProjectionBuildError::none, "Successful build must clear its error status");
    for (size_t row = 0; row != 4; ++row) {
        for (size_t column = 0; column != 4; ++column) {
            const double expected = row == column ? 1.0 : 0.0;
            require_close(identity_output.sourceClipToTargetClipRowMajor[row * 4 + column],
                expected, 2.0e-6, "Zero-IPD matching-FOV output must be identity");
        }
    }

    // A real 64 mm baseline with 100 UE units / meter gives +/-3.2 UE-unit
    // eye offsets. The packet projection is intentionally asymmetric and the
    // native eyes have their own asymmetric FOVs.
    const double baseline_meters = 0.064;
    const double eye_offset_ue = baseline_meters * kWorldToMeters * 0.5;
    ManualDibrProjectionInput left_input{source_projection, target_fov,
        rigid_target_from_source(-eye_offset_ue, 0.0, 0.0, 0.0)};
    ManualDibrProjectionInput right_input{source_projection, target_fov,
        rigid_target_from_source(eye_offset_ue, 0.0, 0.0, 0.0)};
    ManualDibrClipTransform left_output{}, right_output{};
    require(build_manual_dibr_clip_transform(left_input, left_output, &error),
        "Left native eye transform must build");
    require(build_manual_dibr_clip_transform(right_input, right_output, &error),
        "Right native eye transform must build");

    const double cant = -5.0 * kPi / 180.0;
    ManualDibrProjectionInput canted_input{source_projection, target_fov,
        rigid_target_from_source(-eye_offset_ue, 0.0, 0.0, cant)};
    ManualDibrClipTransform canted_output{};
    require(build_manual_dibr_clip_transform(canted_input, canted_output, &error),
        "Canted target eye transform must build");

    // A clear reversed-Z sample (NDC Z=0) is a homogeneous direction at
    // infinity. Its ray is rotated into each real eye but is never translated
    // by IPD; native asymmetric FOV still maps the sky to the correct NDC.
    const std::array<double, 4> sky_source_clip{0.31, -0.27, 0.0, 1.0};
    const double sky_source_x = (sky_source_clip[0] - source_projection[8]) /
        source_projection[0];
    const double sky_source_y = (sky_source_clip[1] - source_projection[9]) /
        source_projection[5];
    const auto sky_expected = project_target_direction(target_fov,
        left_input.targetFromSourceColumnMajor, sky_source_x, sky_source_y, 1.0);
    const auto sky_actual = apply_row_major(left_output.sourceClipToTargetClipRowMajor,
        sky_source_clip);
    for (size_t component = 0; component != 4; ++component)
        require_close(sky_actual[component], sky_expected[component], 2.0e-6,
            "Clear reversed-Z sky must project as a rotated infinite direction");
    require_close(sky_actual[2], 0.0, 2.0e-6,
        "Infinite-distance sky must preserve raw reversed-Z zero");

    const auto canted_sky_expected = project_target_direction(target_fov,
        canted_input.targetFromSourceColumnMajor, sky_source_x, sky_source_y, 1.0);
    const auto canted_sky_actual = apply_row_major(canted_output.sourceClipToTargetClipRowMajor,
        sky_source_clip);
    for (size_t component = 0; component != 4; ++component)
        require_close(canted_sky_actual[component], canted_sky_expected[component], 2.0e-6,
            "Canted eye sky projection must rotate rays without IPD translation");

    for (double depth_meters : {1.0, 10.0}) {
        const double depth_ue = depth_meters * kWorldToMeters;
        const auto source = source_clip(source_projection, 0.0, 0.0, depth_ue);
        const auto left_clip = apply_row_major(left_output.sourceClipToTargetClipRowMajor, source);
        const auto right_clip = apply_row_major(right_output.sourceClipToTargetClipRowMajor, source);
        require_close(source[2] / source[3], near_plane / depth_ue, 1.0e-8,
            "Source NDC depth must remain physical infinite reversed-Z near/Z");
        require_close(left_clip[2] / left_clip[3], near_plane / depth_ue, 2.0e-6,
            "Left-eye clip must preserve the physical reversed-Z depth");
        require_close(right_clip[2] / right_clip[3], near_plane / depth_ue, 2.0e-6,
            "Right-eye clip must preserve the physical reversed-Z depth");
        const double pixel_disparity = (left_clip[0] / left_clip[3] -
            right_clip[0] / right_clip[3]) * 0.5 * 1000.0;
        const double tangent_span = target_right - target_left;
        const double analytic_pixels = 1000.0 * baseline_meters /
            (tangent_span * depth_meters);
        require_close(pixel_disparity, analytic_pixels, 2.0e-4,
            "Eye disparity must match the 64 mm stereo baseline at 1 m and 10 m");
        require_clip_matches(left_input, left_output, 0.12 * depth_ue,
            -0.08 * depth_ue, depth_ue);
        require_clip_matches(right_input, right_output, -0.07 * depth_ue,
            0.05 * depth_ue, depth_ue);
    }

    // The native FOV asymmetry maps its actual edges to NDC +/-1. This checks
    // real per-eye FOV extents instead of a symmetric half-FOV approximation.
    const double edge_depth = 400.0;
    ManualDibrProjectionInput edge_input{source_projection, target_fov,
        rigid_target_from_source(0.0, 0.0, 0.0, 0.0)};
    ManualDibrClipTransform edge_output{};
    require(build_manual_dibr_clip_transform(edge_input, edge_output, &error),
        "Asymmetric target-FOV edge transform must build");
    const auto left_edge_source = source_clip(source_projection,
        target_left * edge_depth, target_up * edge_depth, edge_depth);
    const auto left_edge_clip = apply_row_major(edge_output.sourceClipToTargetClipRowMajor,
        left_edge_source);
    require_close(left_edge_clip[0] / left_edge_clip[3], -1.0, 2.0e-6,
        "Native left FOV edge must project to NDC -1");
    require_close(left_edge_clip[1] / left_edge_clip[3], 1.0, 2.0e-6,
        "Native upper FOV edge must project to NDC +1");

    // Canting rotates the real target view axis. A source ray along that axis
    // must land on the target FOV's optical-axis point with the same depth.
    const double canted_depth = 600.0;
    const double ray_x = -eye_offset_ue + std::sin(cant) * canted_depth;
    const double ray_z = std::cos(cant) * canted_depth;
    require_clip_matches(canted_input, canted_output, ray_x, 0.0, ray_z);
    const auto canted_view = transform_point(canted_input.targetFromSourceColumnMajor,
        ray_x, 0.0, ray_z);
    require_close(canted_view[0], 0.0, 1.0e-9,
        "Canted native eye axis must have zero target-space X");
    require_close(canted_view[2], canted_depth, 1.0e-9,
        "Canted native eye axis must preserve eye-space distance");

    // Invalid projection, FOV, or non-rigid/world-scaled transforms fail
    // explicitly and cannot overwrite a previously usable output.
    ManualDibrClipTransform sentinel{};
    sentinel.sourceClipToTargetClipRowMajor.fill(17.0f);
    auto invalid = identity_input;
    invalid.sourceProjectionColumnMajor[14] = 0.0;
    require(!build_manual_dibr_clip_transform(invalid, sentinel, &error) &&
        error == ProjectionBuildError::invalid_source_projection,
        "Missing/nonphysical frozen near plane must be rejected");
    for (float value : sentinel.sourceClipToTargetClipRowMajor)
        require(value == 17.0f, "Failed builds must leave output untouched");

    invalid = identity_input;
    invalid.targetFov.left = std::numeric_limits<double>::quiet_NaN();
    require(!build_manual_dibr_clip_transform(invalid, sentinel, &error) &&
        error == ProjectionBuildError::invalid_target_fov,
        "Nonfinite native FOV must be rejected");
    invalid = identity_input;
    invalid.targetFov.left = invalid.targetFov.right;
    require(!build_manual_dibr_clip_transform(invalid, sentinel, &error) &&
        error == ProjectionBuildError::invalid_target_fov,
        "Degenerate native FOV must be rejected");

    invalid = identity_input;
    invalid.targetFromSourceColumnMajor[0] = 1.02; // accidental scale
    require(!build_manual_dibr_clip_transform(invalid, sentinel, &error) &&
        error == ProjectionBuildError::invalid_target_transform,
        "Scaled eye transforms must not be mistaken for rigid meter/UE transforms");
    invalid = identity_input;
    invalid.targetFromSourceColumnMajor[3] = 0.01; // non-affine bottom row
    require(!build_manual_dibr_clip_transform(invalid, sentinel, &error) &&
        error == ProjectionBuildError::invalid_target_transform,
        "Non-affine eye transforms must be rejected");
    invalid = identity_input;
    invalid.targetFromSourceColumnMajor[12] = std::numeric_limits<double>::infinity();
    require(!build_manual_dibr_clip_transform(invalid, sentinel, &error) &&
        error == ProjectionBuildError::invalid_target_transform,
        "Nonfinite eye translations must be rejected");

    invalid = identity_input;
    invalid.targetFromSourceColumnMajor[12] = 1.0e100;
    require(!build_manual_dibr_clip_transform(invalid, sentinel, &error) &&
        error == ProjectionBuildError::output_out_of_range,
        "Unrepresentable clip transforms must fail instead of overflowing HLSL floats");

    std::cout << "manual DIBR projection: physical reversed-Z, asymmetric FOV, "
        "64 mm baseline, canted eyes, validation: PASS\n";
    return 0;
} catch (const std::exception& exception) {
    std::cerr << exception.what() << '\n';
    return 1;
}

#pragma once

// Portable projection math for the manual DIBR output path. Inputs use the
// frozen +Z-forward, infinite reversed-Z projection produced by the pinned
// UEVR runtime. The result is a complete homogeneous source-clip to native
// target-eye-clip transform, ready for row-major HLSL `mul(M, vector)`.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>

namespace uevr::duoview::dibr {

struct NativeEyeFovAngles {
    // OpenXR angle values, in radians. Left/down are normally negative and
    // right/up positive, but all four angles are validated by ordering and
    // finite tangent instead of assuming a symmetric headset.
    double left{};
    double right{};
    double up{};
    double down{};
};

struct NativeEyePose {
    // OpenXR native stage-space pose: quaternion x/y/z/w and position in
    // meters. The helper converts native local -Z forward into its +Z-forward
    // UE view basis when building target-from-source.
    std::array<double, 4> orientationXyzw{0.0, 0.0, 0.0, 1.0};
    std::array<double, 3> positionMeters{};
};

struct ManualDibrProjectionInput {
    // Mathematical source projection in GLM-compatible column-major storage.
    // This must be the actual frozen Mono projection from the producer packet.
    std::array<double, 16> sourceProjectionColumnMajor{};
    NativeEyeFovAngles targetFov{};
    // Rigid target-view-from-center-source-view transform, column-major. Both
    // spaces use UE view coordinates (+X right, +Y up, +Z forward). Translation
    // is already expressed in Unreal units after applying the engine's actual
    // WorldToMeters scale. Rotation must be orthonormal with no scale/shear.
    std::array<double, 16> targetFromSourceColumnMajor{};
};

struct ManualDibrClipTransform {
    // Row-major mathematical matrix for HLSL `mul(M, sourceClip)`.
    std::array<float, 16> sourceClipToTargetClipRowMajor{};
};

enum class ProjectionBuildError : uint8_t {
    none,
    invalid_source_projection,
    singular_source_projection,
    invalid_target_fov,
    invalid_target_transform,
    output_out_of_range,
};

enum class PoseTransformError : uint8_t {
    none,
    invalid_world_to_meters,
    invalid_source_pose,
    invalid_target_pose,
    output_out_of_range,
};

namespace manual_dibr_projection_detail {

using Matrix4 = std::array<double, 16>; // internal mathematical row-major

inline Matrix4 from_column_major(const std::array<double, 16>& source) {
    Matrix4 result{};
    for (size_t row = 0; row != 4; ++row)
        for (size_t column = 0; column != 4; ++column)
            result[row * 4 + column] = source[column * 4 + row];
    return result;
}

inline Matrix4 multiply(const Matrix4& a, const Matrix4& b) {
    Matrix4 result{};
    for (size_t row = 0; row != 4; ++row) {
        for (size_t column = 0; column != 4; ++column) {
            double value = 0.0;
            for (size_t k = 0; k != 4; ++k)
                value += a[row * 4 + k] * b[k * 4 + column];
            result[row * 4 + column] = value;
        }
    }
    return result;
}

inline bool finite_matrix(const Matrix4& matrix) {
    for (double value : matrix)
        if (!std::isfinite(value)) return false;
    return true;
}

inline bool inverse(const Matrix4& matrix, Matrix4& result) {
    if (!finite_matrix(matrix)) return false;

    double augmented[4][8]{};
    double largest = 0.0;
    for (size_t row = 0; row != 4; ++row) {
        for (size_t column = 0; column != 4; ++column) {
            augmented[row][column] = matrix[row * 4 + column];
            largest = (std::max)(largest, std::abs(augmented[row][column]));
        }
        augmented[row][row + 4] = 1.0;
    }
    if (!(largest > 0.0) || !std::isfinite(largest)) return false;

    const double pivot_floor = largest * 1.0e-12;
    for (size_t column = 0; column != 4; ++column) {
        size_t pivot_row = column;
        for (size_t row = column + 1; row != 4; ++row) {
            if (std::abs(augmented[row][column]) > std::abs(augmented[pivot_row][column]))
                pivot_row = row;
        }
        const double pivot = augmented[pivot_row][column];
        if (!std::isfinite(pivot) || std::abs(pivot) <= pivot_floor) return false;
        if (pivot_row != column) {
            for (size_t k = 0; k != 8; ++k) {
                const double temporary = augmented[column][k];
                augmented[column][k] = augmented[pivot_row][k];
                augmented[pivot_row][k] = temporary;
            }
        }
        const double divisor = augmented[column][column];
        for (size_t k = 0; k != 8; ++k) augmented[column][k] /= divisor;
        for (size_t row = 0; row != 4; ++row) {
            if (row == column) continue;
            const double factor = augmented[row][column];
            for (size_t k = 0; k != 8; ++k)
                augmented[row][k] -= factor * augmented[column][k];
        }
    }

    for (size_t row = 0; row != 4; ++row)
        for (size_t column = 0; column != 4; ++column)
            result[row * 4 + column] = augmented[row][column + 4];
    return finite_matrix(result);
}

inline bool nearly_equal(double a, double b, double tolerance = 1.0e-8) {
    return std::abs(a - b) <= tolerance * (std::max)({1.0, std::abs(a), std::abs(b)});
}

inline bool valid_source_projection(const std::array<double, 16>& column_major) {
    for (double value : column_major)
        if (!std::isfinite(value)) return false;

    // Frozen Mono is an infinite reversed-Z perspective matrix in +Z-forward
    // coordinates. In GLM indexing, [3][2] is column-major element 14 and is
    // the positive UE-unit near plane; [2][3] (element 11) gives clip W = Z.
    if (!(column_major[0] > 0.0) || !(column_major[5] > 0.0) ||
        !(column_major[14] > 0.0) || !nearly_equal(column_major[11], 1.0))
        return false;

    // Accept harmless float noise in structural zeroes while refusing an
    // orthographic, finite-far, negative-Z, or otherwise unrelated matrix.
    constexpr size_t allowed[] = {0, 5, 8, 9, 11, 14};
    for (size_t index = 0; index != 16; ++index) {
        bool allowed_entry = false;
        for (size_t valid : allowed) allowed_entry |= index == valid;
        if (!allowed_entry && !nearly_equal(column_major[index], 0.0)) return false;
    }
    return true;
}

inline bool valid_rigid_transform(const Matrix4& transform) {
    if (!finite_matrix(transform)) return false;
    constexpr double tolerance = 5.0e-3; // allows float quaternion roundoff
    if (!nearly_equal(transform[12], 0.0, tolerance) ||
        !nearly_equal(transform[13], 0.0, tolerance) ||
        !nearly_equal(transform[14], 0.0, tolerance) ||
        !nearly_equal(transform[15], 1.0, tolerance))
        return false;

    // A 3x3 proper rotation is required. This rejects zero/unit mistakes,
    // accidental world-scale multiplication, reflection, and shear.
    for (size_t column_a = 0; column_a != 3; ++column_a) {
        for (size_t column_b = 0; column_b != 3; ++column_b) {
            double dot = 0.0;
            for (size_t row = 0; row != 3; ++row)
                dot += transform[row * 4 + column_a] * transform[row * 4 + column_b];
            if (!nearly_equal(dot, column_a == column_b ? 1.0 : 0.0, tolerance)) return false;
        }
    }
    const double determinant =
        transform[0] * (transform[5] * transform[10] - transform[6] * transform[9]) -
        transform[1] * (transform[4] * transform[10] - transform[6] * transform[8]) +
        transform[2] * (transform[4] * transform[9] - transform[5] * transform[8]);
    return std::isfinite(determinant) && nearly_equal(determinant, 1.0, tolerance);
}

inline bool valid_fov(const NativeEyeFovAngles& fov, double& left, double& right,
    double& up, double& down) {
    constexpr double half_pi = 1.57079632679489661923;
    if (!std::isfinite(fov.left) || !std::isfinite(fov.right) ||
        !std::isfinite(fov.up) || !std::isfinite(fov.down) ||
        fov.left <= -half_pi || fov.left >= half_pi ||
        fov.right <= -half_pi || fov.right >= half_pi ||
        fov.up <= -half_pi || fov.up >= half_pi ||
        fov.down <= -half_pi || fov.down >= half_pi ||
        !(fov.left < fov.right) || !(fov.down < fov.up))
        return false;
    left = std::tan(fov.left);
    right = std::tan(fov.right);
    up = std::tan(fov.up);
    down = std::tan(fov.down);
    return std::isfinite(left) && std::isfinite(right) &&
        std::isfinite(up) && std::isfinite(down) &&
        right > left && up > down;
}

} // namespace manual_dibr_projection_detail

namespace manual_dibr_pose_detail {

struct Quat { double x{}, y{}, z{}, w{1.0}; };
struct Vec3 { double x{}, y{}, z{}; };

inline bool valid_pose(const NativeEyePose& pose) {
    double norm_squared = 0.0;
    for (double component : pose.orientationXyzw) {
        if (!std::isfinite(component)) return false;
        norm_squared += component * component;
    }
    // Keep the exact pose-quality threshold used by OpenXR mono_geometry.
    if (!std::isfinite(norm_squared) || std::abs(norm_squared - 1.0) > 0.001) return false;
    for (double component : pose.positionMeters)
        if (!std::isfinite(component)) return false;
    return true;
}

inline Quat normalized_quaternion(const NativeEyePose& pose) {
    const double norm = std::sqrt(
        pose.orientationXyzw[0] * pose.orientationXyzw[0] +
        pose.orientationXyzw[1] * pose.orientationXyzw[1] +
        pose.orientationXyzw[2] * pose.orientationXyzw[2] +
        pose.orientationXyzw[3] * pose.orientationXyzw[3]);
    return {pose.orientationXyzw[0] / norm, pose.orientationXyzw[1] / norm,
        pose.orientationXyzw[2] / norm, pose.orientationXyzw[3] / norm};
}

inline Quat conjugate(Quat q) { return {-q.x, -q.y, -q.z, q.w}; }

inline Quat multiply(Quat a, Quat b) {
    return {
        a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
        a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
        a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
        a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
    };
}

inline Vec3 rotate(Quat q, Vec3 v) {
    const Vec3 u{q.x, q.y, q.z};
    const double dot = u.x * v.x + u.y * v.y + u.z * v.z;
    const double uu = u.x * u.x + u.y * u.y + u.z * u.z;
    const Vec3 cross{u.y * v.z - u.z * v.y,
        u.z * v.x - u.x * v.z, u.x * v.y - u.y * v.x};
    return {
        2.0 * dot * u.x + (q.w * q.w - uu) * v.x + 2.0 * q.w * cross.x,
        2.0 * dot * u.y + (q.w * q.w - uu) * v.y + 2.0 * q.w * cross.y,
        2.0 * dot * u.z + (q.w * q.w - uu) * v.z + 2.0 * q.w * cross.z,
    };
}

inline bool finite_transform(const std::array<double, 16>& matrix) {
    for (double value : matrix)
        if (!std::isfinite(value)) return false;
    return true;
}

} // namespace manual_dibr_pose_detail

// Build the rigid target-view-from-source-center-view transform used by the
// projection builder. The source camera matches mono_geometry: left-eye
// optical orientation and the arithmetic midpoint of both native eye
// positions. All three raw OpenXR poses are validated before normalization.
// `worldToMeters` is the actual engine getter (including configured world
// scale) and is applied once to the native-meter translation.
inline bool build_native_eye_target_from_source(
    const NativeEyePose& source_left,
    const NativeEyePose& source_right,
    const NativeEyePose& target,
    double worldToMeters,
    std::array<double, 16>& targetFromSourceColumnMajor,
    PoseTransformError* error = nullptr)
{
    using namespace manual_dibr_pose_detail;
    auto fail = [error](PoseTransformError reason) {
        if (error) *error = reason;
        return false;
    };
    if (!std::isfinite(worldToMeters) || worldToMeters <= 0.0 || worldToMeters > 100000.0)
        return fail(PoseTransformError::invalid_world_to_meters);
    if (!valid_pose(source_left) || !valid_pose(source_right))
        return fail(PoseTransformError::invalid_source_pose);
    if (!valid_pose(target)) return fail(PoseTransformError::invalid_target_pose);

    const Quat source_orientation = normalized_quaternion(source_left);
    const Quat target_orientation = normalized_quaternion(target);
    const Quat target_inverse = conjugate(target_orientation);
    const Quat target_from_source_native = multiply(target_inverse, source_orientation);

    // OpenXR native view space is +X right, +Y up, -Z forward. S converts
    // vectors to the projection helper's +Z-forward camera basis. Conjugating
    // the relative rotation by S preserves proper handedness.
    const auto rotate_ue_basis = [&](Vec3 value) {
        const auto rotated = rotate(target_from_source_native, {value.x, value.y, -value.z});
        return Vec3{rotated.x, rotated.y, -rotated.z};
    };

    std::array<double, 16> candidate{};
    for (size_t column = 0; column != 3; ++column) {
        Vec3 basis{};
        if (column == 0) basis.x = 1.0;
        else if (column == 1) basis.y = 1.0;
        else basis.z = 1.0;
        const Vec3 transformed = rotate_ue_basis(basis);
        candidate[column * 4] = transformed.x;
        candidate[column * 4 + 1] = transformed.y;
        candidate[column * 4 + 2] = transformed.z;
        candidate[column * 4 + 3] = 0.0;
    }

    const Vec3 source_center{
        source_left.positionMeters[0] * 0.5 + source_right.positionMeters[0] * 0.5,
        source_left.positionMeters[1] * 0.5 + source_right.positionMeters[1] * 0.5,
        source_left.positionMeters[2] * 0.5 + source_right.positionMeters[2] * 0.5,
    };
    const Vec3 center_delta{
        source_center.x - target.positionMeters[0],
        source_center.y - target.positionMeters[1],
        source_center.z - target.positionMeters[2],
    };
    const Vec3 target_translation_native = rotate(target_inverse, center_delta);
    candidate[12] = target_translation_native.x * worldToMeters;
    candidate[13] = target_translation_native.y * worldToMeters;
    candidate[14] = -target_translation_native.z * worldToMeters;
    candidate[15] = 1.0;
    if (!finite_transform(candidate)) return fail(PoseTransformError::output_out_of_range);

    targetFromSourceColumnMajor = candidate;
    if (error) *error = PoseTransformError::none;
    return true;
}

// Build `Ptarget * targetFromSource * inverse(Psource)`. The output is only
// committed after every validation and range check succeeds; invalid input
// never turns into a plausible identity matrix.
inline bool build_manual_dibr_clip_transform(
    const ManualDibrProjectionInput& input,
    ManualDibrClipTransform& output,
    ProjectionBuildError* error = nullptr)
{
    using namespace manual_dibr_projection_detail;
    auto fail = [error](ProjectionBuildError reason) {
        if (error) *error = reason;
        return false;
    };
    if (!valid_source_projection(input.sourceProjectionColumnMajor))
        return fail(ProjectionBuildError::invalid_source_projection);

    double left{}, right{}, up{}, down{};
    if (!valid_fov(input.targetFov, left, right, up, down))
        return fail(ProjectionBuildError::invalid_target_fov);

    const Matrix4 target_from_source = from_column_major(input.targetFromSourceColumnMajor);
    if (!valid_rigid_transform(target_from_source))
        return fail(ProjectionBuildError::invalid_target_transform);

    const Matrix4 source_projection = from_column_major(input.sourceProjectionColumnMajor);
    Matrix4 inverse_source_projection{};
    if (!inverse(source_projection, inverse_source_projection))
        return fail(ProjectionBuildError::singular_source_projection);

    const double horizontal_span = right - left;
    const double vertical_span = up - down;
    const double near_plane = input.sourceProjectionColumnMajor[14];
    Matrix4 target_projection{
        2.0 / horizontal_span, 0.0, -(right + left) / horizontal_span, 0.0,
        0.0, 2.0 / vertical_span, -(up + down) / vertical_span, 0.0,
        0.0, 0.0, 0.0, near_plane,
        0.0, 0.0, 1.0, 0.0,
    };
    if (!finite_matrix(target_projection)) return fail(ProjectionBuildError::invalid_target_fov);

    const Matrix4 target_clip_from_source_clip = multiply(
        multiply(target_projection, target_from_source), inverse_source_projection);
    if (!finite_matrix(target_clip_from_source_clip))
        return fail(ProjectionBuildError::output_out_of_range);

    ManualDibrClipTransform candidate{};
    for (size_t index = 0; index != 16; ++index) {
        const double value = target_clip_from_source_clip[index];
        if (!std::isfinite(value) ||
            std::abs(value) > static_cast<double>((std::numeric_limits<float>::max)()))
            return fail(ProjectionBuildError::output_out_of_range);
        candidate.sourceClipToTargetClipRowMajor[index] = static_cast<float>(value);
        if (!std::isfinite(candidate.sourceClipToTargetClipRowMajor[index]))
            return fail(ProjectionBuildError::output_out_of_range);
    }

    output = candidate;
    if (error) *error = ProjectionBuildError::none;
    return true;
}

} // namespace uevr::duoview::dibr

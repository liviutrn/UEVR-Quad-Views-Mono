#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <optional>
#include <utility>

namespace uevr::quadview {

struct Rect {
    uint32_t x{}, y{}, width{}, height{};
    friend bool operator==(const Rect&, const Rect&) = default;
};

struct Crop {
    float u0{}, v0{}, u1{1.f}, v1{1.f};
    friend bool operator==(const Crop&, const Crop&) = default;
};

struct FocusPoint {
    float u{.5f}, v{.5f};
};

struct Layout {
    // Engine view order is explicitly zero based:
    // 0 left context, 1 right context, 2 left focus, 3 right focus.
    std::array<Rect, 4> views{};
    uint32_t eye_width{}, eye_height{}, atlas_width{}, atlas_height{};
    // Each runtime eye projects the same head-space gaze ray through its own
    // optical rotation and asymmetric full-eye frustum. Keep both crops in
    // the immutable draw layout; one shared center is not stereo gaze.
    std::array<Crop, 2> focus_crops{};
    float context_scale{};
    // Tri-view: view 0 is ONE centre context shared by both eyes (union FOV of
    // both eye frusta); view 1 is still constructed but never rendered.
    bool shared_context{};
    // Projection entries written into view 0: m[0][0], m[2][0], m[1][1], m[2][1].
    std::array<double, 4> context_projection{};
    // Per eye: 3x3 homography (rows padded to 4) from eye uv to context uv:
    // h = H * (u, v, 1), context uv = h.xy / h.z. Identity for four views.
    std::array<std::array<float, 12>, 2> context_h{{{1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f},
                                                    {1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f}}};
};

// Turns a four-view layout into tri-view. Projections are column-major, +Z
// forward, clip w = m[2][3] * z; per axis an eye maps view tangent t to NDC as
// a*t + b. The shared context has the LEFT eye's orientation (the centre camera
// keeps the left optical rotation). Eye orientations are OpenXR stage
// quaternions (x, y, z, w); when given, the right eye's frustum is rotated into
// the left-eye frame before the union, and each eye samples the context
// through an exact-at-infinity homography (no equal-orientation assumption).
inline bool apply_shared_context(Layout& layout, const std::array<float, 16>& left,
                                 const std::array<float, 16>& right,
                                 const std::array<float, 4>* left_orientation = nullptr,
                                 const std::array<float, 4>* right_orientation = nullptr) {
    using M3 = std::array<std::array<double, 3>, 3>;
    const auto mul = [](const M3& x, const M3& y) {
        M3 r{};
        for (int i = 0; i != 3; ++i) for (int j = 0; j != 3; ++j)
            for (int k = 0; k != 3; ++k) r[i][j] += x[i][k] * y[k][j];
        return r;
    };
    const auto from_quaternion = [](const std::array<float, 4>& q) {
        const double x = q[0], y = q[1], z = q[2], w = q[3];
        return M3{{{1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)},
                   {2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)},
                   {2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)}}};
    };
    M3 rotation[2]{{{{1, 0, 0}, {0, 1, 0}, {0, 0, 1}}}, {{{1, 0, 0}, {0, 1, 0}, {0, 0, 1}}}};
    if (left_orientation && right_orientation) {
        for (const auto* q : {left_orientation, right_orientation}) {
            const double n = double((*q)[0]) * (*q)[0] + double((*q)[1]) * (*q)[1] +
                             double((*q)[2]) * (*q)[2] + double((*q)[3]) * (*q)[3];
            if (!std::isfinite(n) || std::abs(n - 1.) > 1.e-2) return false;
        }
        const auto l = from_quaternion(*left_orientation), r = from_quaternion(*right_orientation);
        M3 lt{};
        for (int i = 0; i != 3; ++i) for (int j = 0; j != 3; ++j) lt[i][j] = l[j][i];
        auto rel = mul(lt, r); // right-eye local -> left-eye local (OpenXR, -Z forward)
        for (int i = 0; i != 3; ++i) for (int j = 0; j != 3; ++j)
            if ((i == 2) != (j == 2)) rel[i][j] = -rel[i][j]; // to +Z forward: S*rel*S
        rotation[1] = rel;
    }
    const std::array<const std::array<float, 16>*, 2> eyes{&left, &right};
    double a[2][2]{}, b[2][2]{}; // [eye][axis]
    double lo[2]{1.e30, 1.e30}, hi[2]{-1.e30, -1.e30};
    for (size_t e = 0; e != 2; ++e) {
        const auto& p = *eyes[e];
        const double w = p[11];
        if (!std::isfinite(w) || std::abs(w) < 1.e-6) return false;
        const double raw_a[2]{p[0], p[5]}, raw_b[2]{p[8], p[9]};
        double t[2][2]{};
        for (size_t axis = 0; axis != 2; ++axis) {
            a[e][axis] = raw_a[axis] / w;
            b[e][axis] = raw_b[axis] / w;
            if (!std::isfinite(a[e][axis]) || !std::isfinite(b[e][axis]) || std::abs(a[e][axis]) < 1.e-6) return false;
            t[axis][0] = (-1. - b[e][axis]) / a[e][axis];
            t[axis][1] = (1. - b[e][axis]) / a[e][axis];
        }
        // A projective map keeps the frustum convex: its tangent bounds lie at the corners.
        for (int cx = 0; cx != 2; ++cx) for (int cy = 0; cy != 2; ++cy) {
            const double d[3]{t[0][cx], t[1][cy], 1.};
            double c[3]{};
            for (int i = 0; i != 3; ++i) for (int k = 0; k != 3; ++k) c[i] += rotation[e][i][k] * d[k];
            if (!(c[2] > 1.e-3)) return false;
            for (size_t axis = 0; axis != 2; ++axis) {
                lo[axis] = (std::min)(lo[axis], c[axis] / c[2]);
                hi[axis] = (std::max)(hi[axis], c[axis] / c[2]);
            }
        }
    }
    double ca[2]{}, cb[2]{};
    for (size_t axis = 0; axis != 2; ++axis) {
        if (!(hi[axis] - lo[axis] > 1.e-6)) return false;
        ca[axis] = (a[0][axis] > 0. ? 2. : -2.) / (hi[axis] - lo[axis]);
        cb[axis] = -1. - ca[axis] * (ca[axis] > 0. ? lo[axis] : hi[axis]);
    }
    // u: ndc = 2u - 1 (right).  v: ndc = 1 - 2v (texture rows go down).
    const M3 context{{{ca[0] * .5, 0., (cb[0] + 1.) * .5}, {0., -ca[1] * .5, (1. - cb[1]) * .5}, {0., 0., 1.}}};
    auto homographies = layout.context_h; // commit only after both eyes validate
    for (size_t e = 0; e != 2; ++e) {
        const M3 eye_to_tangent{{{2. / a[e][0], 0., (-1. - b[e][0]) / a[e][0]},
                                 {0., -2. / a[e][1], (1. - b[e][1]) / a[e][1]}, {0., 0., 1.}}};
        const auto h = mul(context, mul(rotation[e], eye_to_tangent));
        for (int i = 0; i != 3; ++i) for (int j = 0; j != 3; ++j) {
            if (!std::isfinite(h[i][j])) return false;
            homographies[e][i * 4 + j] = static_cast<float>(h[i][j]);
        }
    }
    layout.context_h = homographies;
    const double w = left[11];
    layout.context_projection = {ca[0] * w, cb[0] * w, ca[1] * w, cb[1] * w};
    layout.shared_context = true;
    return true;
}

class LayoutLatch {
public:
    std::optional<Layout> get(uint64_t generation, uint64_t serial) const {
        if (generation_ != generation || serial_ != serial) return {};
        return layout_;
    }

    std::optional<Layout> freeze(uint64_t generation, uint64_t serial, Layout candidate) {
        if (!generation || !serial) return {};
        if (const auto current = get(generation, serial)) return current;
        generation_ = generation;
        serial_ = serial;
        layout_ = std::move(candidate);
        return layout_;
    }

    void reset() { generation_ = serial_ = 0; layout_.reset(); }

private:
    uint64_t generation_{}, serial_{};
    std::optional<Layout> layout_{};
};

inline std::optional<Layout> make_layout(
    uint32_t eye_width, uint32_t eye_height,
    float crop_width = .50f, float crop_height = .50f,
    float context_scale = .20f, float focus_density = 1.f,
    std::array<FocusPoint, 2> focus = {})
{
    if (!eye_width || !eye_height || eye_width > 8192 || eye_height > 8192 ||
        !std::isfinite(crop_width) || !std::isfinite(crop_height) ||
        !std::isfinite(context_scale) || !std::isfinite(focus_density) ||
        crop_width < .05f || crop_width > 1.f || crop_height < .05f || crop_height > 1.f ||
        context_scale < .05f || context_scale > .5f || focus_density < .25f || focus_density > 4.f ||
        std::any_of(focus.begin(), focus.end(), [](const FocusPoint& p) {
            return !std::isfinite(p.u) || !std::isfinite(p.v) || p.u < 0.f || p.u > 1.f || p.v < 0.f || p.v > 1.f;
        })) return {};

    const auto rounded = [](float value) {
        return static_cast<uint32_t>((std::max)(1.0f, std::round(value)));
    };
    const auto context_width = rounded(eye_width * context_scale);
    const auto context_height = rounded(eye_height * context_scale);
    const auto focus_width = rounded(eye_width * crop_width * focus_density);
    const auto focus_height = rounded(eye_height * crop_height * focus_density);
    // The pair is packed horizontally within each eye's existing half of the
    // 2W x H render target. The crops preserve each source rectangle's aspect.
    if (uint64_t(context_width) + focus_width > eye_width ||
        context_height > eye_height || focus_height > eye_height) return {};

    Layout result{};
    result.eye_width = eye_width;
    result.eye_height = eye_height;
    result.atlas_width = eye_width * 2;
    result.atlas_height = eye_height;
    for (uint32_t eye = 0; eye != 2; ++eye) {
        const float cu = std::clamp(focus[eye].u, crop_width * .5f, 1.f - crop_width * .5f);
        const float cv = std::clamp(focus[eye].v, crop_height * .5f, 1.f - crop_height * .5f);
        result.focus_crops[eye] = {cu - crop_width * .5f, cv - crop_height * .5f,
                                   cu + crop_width * .5f, cv + crop_height * .5f};
    }
    result.context_scale = context_scale;
    for (uint32_t eye = 0; eye != 2; ++eye) {
        const auto base_x = eye * eye_width;
        result.views[eye] = {base_x, 0, context_width, context_height};
        result.views[eye + 2] = {base_x + context_width, 0, focus_width, focus_height};
    }
    return result;
}

// Compatibility convenience for center/single-point callers and the geometry
// unit tests. Production stereo gaze uses the two-point overload above.
inline std::optional<Layout> make_layout(
    uint32_t eye_width, uint32_t eye_height,
    float crop_width, float crop_height, float context_scale, float focus_density,
    float focus_u, float focus_v)
{
    const std::array<FocusPoint, 2> both{{{focus_u, focus_v}, {focus_u, focus_v}}};
    return make_layout(eye_width, eye_height, crop_width, crop_height,
                       context_scale, focus_density, both);
}

constexpr bool valid_view_index(int32_t index) { return index >= 0 && index < 4; }
constexpr uint32_t eye_for_view(uint32_t index) { return index & 1u; }
constexpr bool is_focus_view(uint32_t index) { return index >= 2u && index < 4u; }

template <typename Matrix>
inline void apply_focus_crop(Matrix& matrix, const Crop& crop) {
    const auto width = crop.u1 - crop.u0;
    const auto height = crop.v1 - crop.v0;
    if (!(std::isfinite(width) && std::isfinite(height)) || width <= 0.f || height <= 0.f) return;
    const auto x_scale = 1.f / width;
    const auto y_scale = 1.f / height;
    const auto x_shift = (1.f - crop.u0 - crop.u1) * x_scale;
    const auto y_shift = (crop.v0 + crop.v1 - 1.f) * y_scale;
    for (int col = 0; col != 4; ++col) {
        const auto old_x = matrix[col][0];
        const auto old_y = matrix[col][1];
        const auto old_w = matrix[col][3];
        matrix[col][0] = old_x * x_scale + old_w * x_shift;
        matrix[col][1] = old_y * y_scale + old_w * y_shift;
    }
}

} // namespace uevr::quadview

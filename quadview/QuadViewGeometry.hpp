#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <optional>
#include <utility>
#include "QuadViewNgxSelect.hpp"

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
    // Tri-view B6 compact sources: every role renders into its OWN small native
    // target and `views` hold target-local rectangles (see apply_native_local).
    // false = the original shared 2W x H atlas rectangles.
    bool native_local{};
    // Tri-view B7: periphery depth reprojection shift per eye (see periphery_depth_shift).
    std::array<float, 4> depth_shift{};
    // Exact perspective reprojection: eye origins expressed in the frozen
    // context camera basis and units. Homographies supply each rotated eye ray.
    bool depth_geometry_valid{};
    std::array<std::array<float,4>,2> depth_eye_origin{};
    std::array<float,4> depth_projection{}; // ax,bx,ay,by
    std::array<float,4> depth_coefficients{}; // A=m22,B=m32,C=m23,strength

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
    auto context_width = rounded(eye_width * context_scale);
    auto context_height = rounded(eye_height * context_scale);
    const auto focus_width = rounded(eye_width * crop_width * focus_density);
    const auto focus_height = rounded(eye_height * crop_height * focus_density);
    // The pair is packed horizontally within each eye's existing half of the
    // 2W x H render target. The crops preserve each source rectangle's aspect.
    if (uint64_t(context_width) + focus_width > eye_width ||
        context_height > eye_height || focus_height > eye_height) return {};
    // Tri-view B11 (after the fit check, so accepted settings are unchanged): the periphery's DLSS depth is recognised by its output size,
    // so the context must never have (almost) the same size as a fovea. Only in
    // that case it is made slightly smaller (same aspect, same field of view).
    if (const float k = ngx::unique_context_factor(focus_width, focus_height, context_width, context_height); k != 1.f) {
        context_width = rounded(float(context_width) * k);
        context_height = rounded(float(context_height) * k);
    }

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

// Tri-view B7: context-uv shift per unit of reversed-Z device depth for each
// eye seeing the shared centre periphery (layout.context_projection = m00, m20,
// m11, m21). An eye at lateral offset t (same units as near) sees context
// direction tan_inf + t / Z; Z = near / d gives du = 0.5 * m00 * t * d / near.
// Returns {left u, left v, right u, right v}; zero when inputs are invalid.
inline std::array<float, 4> periphery_depth_shift(const Layout& layout, double near_units,
                                                  double half_ipd_units, double strength) {
    const double m00 = layout.context_projection[0];
    if (!layout.shared_context || !std::isfinite(near_units) || !std::isfinite(half_ipd_units) ||
        !std::isfinite(strength) || !std::isfinite(m00) || near_units <= 0.0 || half_ipd_units < 0.0 || m00 <= 0.0)
        return {};
    const double k = 0.5 * m00 * half_ipd_units / near_units * strength;
    if (!std::isfinite(k) || std::abs(k) > 4.0) return {};
    return {static_cast<float>(-k), 0.f, static_cast<float>(k), 0.f};
}

// Freeze the actual render projection and eye origins, never infer an IPD.
// Supports the standard UE perspective form, including finite/infinite far
// planes and asymmetric frusta. Refuse unsupported skew/oblique projections.
inline bool configure_depth_geometry(Layout& layout, const std::array<double,16>& p,
        const std::array<std::array<double,3>,2>& eye_origins, double strength=1.) {
    layout.depth_geometry_valid=false;
    if (!layout.shared_context || !std::isfinite(strength)) return false;
    for (double v:p) if (!std::isfinite(v)) return false;
    for (unsigned i:{1u,2u,3u,4u,6u,7u,12u,13u,15u})
        if (std::abs(p[i])>1.e-9) return false;
    if (std::abs(p[0])<1.e-9 || std::abs(p[5])<1.e-9 || p[14]<=0. || p[11]<=0.) return false;
    for (size_t eye=0;eye<2;++eye) for (size_t axis=0;axis<3;++axis) {
        const double v=eye_origins[eye][axis];
        if (!std::isfinite(v) || std::abs(v)>1.e6) return false;
        layout.depth_eye_origin[eye][axis]=static_cast<float>(v);
    }
    layout.depth_projection={float(p[0]/p[11]),float(p[8]/p[11]),float(p[5]/p[11]),float(p[9]/p[11])};
    layout.depth_coefficients={float(p[10]),float(p[14]),float(p[11]),float(strength)};
    layout.depth_geometry_valid=true;
    return true;
}

// Reference for shader validation. infinity_uv comes from the existing exact
// eye-to-context homography. Device depth is sampled at the iterated source UV.
inline std::array<double,2> reproject_context_ray(const Layout& l, unsigned eye,
        std::array<double,2> infinity_uv, double device_depth) {
    if (!l.depth_geometry_valid || eye>1 || !std::isfinite(device_depth)) return infinity_uv;
    const auto& p=l.depth_projection; const auto& c=l.depth_coefficients;
    const auto& t=l.depth_eye_origin[eye];
    const double inverse_z=(c[2]*device_depth-c[0])/c[1];
    const double rx=(2.*infinity_uv[0]-1.-p[1])/p[0];
    const double ry=(1.-2.*infinity_uv[1]-p[3])/p[2];
    return {infinity_uv[0]+.5*p[0]*(t[0]-rx*t[2])*inverse_z*c[3],
            infinity_uv[1]-.5*p[2]*(t[1]-ry*t[2])*inverse_z*c[3]};
}

// Tri-view B6 compact sources. Width/height of each role's native target.
using SourceExtents = std::array<std::array<uint32_t, 2>, 4>;
// Distinct x-only origins keep all four engine view rectangles unique for every
// setting (the producer identifies a constructed view by its exact rectangle)
// while every rectangle keeps y = 0 like the proven atlas layout:
// context pair x = 0 / 8, focus pair x = 16 / 24. Extents are rounded up to
// 64 px so small slider steps reuse the same targets instead of rebuilding.
inline constexpr uint32_t compact_source_margin = 8;
inline constexpr uint32_t compact_source_granularity = 64;

// Engine construction rectangles retain their role-identifying origins.
// A standalone Native Stereo Fix family's final color image is presented at
// texture origin; these are different coordinate contracts. Snapshot B35-125:
// 2030x1614 color at (0,0), although engine roles start at x16/x24.
inline Rect color_source_rect(const Layout& layout, size_t role) {
    auto rect=layout.views[role];
    if(layout.native_local) { rect.x=0; rect.y=0; }
    return rect;
}

inline SourceExtents source_extents(const Layout& layout) {
    SourceExtents extents{};
    for (size_t i = 0; i != 4; ++i) {
        if (!layout.native_local) {
            extents[i] = {layout.atlas_width, layout.atlas_height};
            continue;
        }
        const auto& size_from = layout.views[i < 2 ? 0 : 2];
        const auto pad = i < 2 ? compact_source_margin : 3 * compact_source_margin;
        const auto up = [](uint64_t v) {
            return static_cast<uint32_t>((v + compact_source_granularity - 1) / compact_source_granularity * compact_source_granularity);
        };
        extents[i] = {up(uint64_t(size_from.width) + pad), up(size_from.height)};
    }
    return extents;
}

// Converts an atlas layout (from make_layout, optionally tri-view) into
// target-local rectangles. Sizes, crops and homographies are unchanged: the
// homographies map eye uv to context uv, which is rectangle-relative.
// B17: retain logical role 1 for view-family identity while never allocating a
// corresponding physical source. This also applies to unprojected "wanted"
// layouts during B14 resize negotiation (not only frozen shared-context layouts).
inline SourceExtents triview_source_extents(const Layout& layout) {
    auto extents = source_extents(layout);
    extents[1] = {0, 0};
    return extents;
}

inline bool apply_native_local(Layout& layout) {
    if (layout.native_local) return true;
    const auto context = layout.views[0], focus = layout.views[2];
    const auto m = compact_source_margin;
    if (!context.width || !context.height || !focus.width || !focus.height ||
        layout.views[1].width != context.width || layout.views[1].height != context.height ||
        layout.views[3].width != focus.width || layout.views[3].height != focus.height ||
        uint64_t(context.width) + m > layout.atlas_width || uint64_t(focus.width) + 3 * m > layout.atlas_width) return false;
    layout.views[0] = {0, 0, context.width, context.height};
    layout.views[1] = {m, 0, context.width, context.height};
    layout.views[2] = {2 * m, 0, focus.width, focus.height};
    layout.views[3] = {3 * m, 0, focus.width, focus.height};
    layout.native_local = true;
    return true;
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

// Tri-view B14: one source-target build per SETTLED size change, at most one in
// flight, and the sizes of every published set are known. B12 started a new
// four-target build on every 64 px slider step; each build allocates four render
// targets that only Unreal's garbage collector frees (about once a minute), and
// a build replaced mid-flight could publish with sizes the draw no longer knew.
struct ResizeSizes {
    float crop_width{}, crop_height{}, context_scale{}, foveal_density{};
};
class ResizeGate {
public:
    static constexpr uint64_t settle_ms = 400;      // wanted extents unchanged this long
    static constexpr uint64_t latch_timeout_ms = 35000; // > the 30 s build timeout
    // While a build is in flight it is re-requested at most this often: a build that
    // fails fast must not respawn four targets every frame. Between requests the
    // caller asks for the live extents, which leaves an in-flight build untouched.
    static constexpr uint64_t retry_ms = 2000;
    struct Decision {
        bool hold{};            // draw with `draw` (the published set's sizes)
        ResizeSizes draw{};
        bool request{};         // ask for a build of `request_extents`
        SourceExtents request_extents{};
    };
    // A draw used the published set with these sizes.
    void confirm_live(const SourceExtents& extents, const ResizeSizes& sizes) {
        live_valid_ = true; live_extents_ = extents; live_sizes_ = sizes;
    }
    // B42: minimum pause after a new set was published before the next build is
    // latched (0 = off, B14 behaviour). Survives reset().
    void set_cooldown_ms(uint64_t ms) { cooldown_ms_ = ms; }
    uint64_t cooldown_ms() const { return cooldown_ms_; }
    // B42: the caller refused the latched build (VRAM guard): forget it and let the
    // current wish settle again, so a later, different wish is not blocked for 35 s.
    void cancel_latch() { latched_ = false; seen_ = false; }
    void reset() { const auto c = cooldown_ms_; *this = ResizeGate{}; cooldown_ms_ = c; }
    // published: extents of the set published right now (nullopt = none).
    Decision update(const std::optional<SourceExtents>& published, const SourceExtents& wanted,
                    const ResizeSizes& wanted_sizes, uint64_t now_ms) {
        Decision d{};
        // No published set (world change, mode switch): the caller's normal path
        // requests what it draws; an old in-flight request is not carried over.
        if (!published) { latched_ = false; seen_ = false; return d; }
        if (latched_ && *published == latched_extents_) {
            confirm_live(*published, latched_sizes_);
            latched_ = false;
            published_ms_ = now_ms; // B42 cooldown starts when the new set is live
        }
        if (latched_ && now_ms - latched_ms_ > latch_timeout_ms) latched_ = false;
        if (latched_ && now_ms - requested_ms_ >= retry_ms) {
            d.request = true; d.request_extents = latched_extents_; requested_ms_ = now_ms;
        }
        // Unknown sizes for the published set: no hold (the caller's normal path).
        if (!live_valid_ || *published != live_extents_) { seen_ = false; return d; }
        if (wanted == live_extents_) { seen_ = false; return d; }
        d.hold = true; d.draw = live_sizes_;
        if (!seen_ || wanted != seen_extents_) { seen_ = true; seen_extents_ = wanted; seen_ms_ = now_ms; return d; }
        if (!latched_ && now_ms - seen_ms_ >= settle_ms &&
            (cooldown_ms_ == 0 || now_ms - published_ms_ >= cooldown_ms_)) {
            latched_ = true; latched_extents_ = wanted; latched_sizes_ = wanted_sizes; latched_ms_ = now_ms;
            requested_ms_ = now_ms;
            d.request = true; d.request_extents = wanted;
        }
        return d;
    }
    bool latched() const { return latched_; }
private:
    bool live_valid_{}; SourceExtents live_extents_{}; ResizeSizes live_sizes_{};
    bool latched_{}; SourceExtents latched_extents_{}; ResizeSizes latched_sizes_{}; uint64_t latched_ms_{}, requested_ms_{};
    bool seen_{}; SourceExtents seen_extents_{}; uint64_t seen_ms_{};
    uint64_t cooldown_ms_{}, published_ms_{}; // B42
};

// Tri-view B15: which pose-ring frame answers "where is the head now" (recenter,
// standing origin/height). ID7 renders its roles with their own frame numbers
// (canonical N, then N+1, N+2), and each role render moves the runtime's current
// frame to N+1/N+2. Only N gets a located head pose; with a 6-slot ring and 3
// frames per draw the role slots are never refreshed, so a recenter between
// draws read a pose that could be minutes old. In TriView answer with the newest
// located frame; every other mode keeps the current frame exactly as before.
inline uint32_t current_pose_frame(bool triview, bool located_any, uint32_t current, uint32_t newest_located) {
    return (triview && located_any && current != newest_located) ? newest_located : current;
}
// Wraparound-safe "a is newer than b" for 32-bit frame counters.
inline bool pose_frame_newer(uint32_t a, uint32_t b) { return static_cast<int32_t>(a - b) > 0; }

} // namespace uevr::quadview

#pragma once
// Tri-View Stage 1 geometry (rendering method ID 7). No UE/D3D dependencies.
// Views 0/1 = the two real eyes cropped to a fixed centre window (the foveas).
// View 2    = one centre camera covering the union of both eye frusta (the periphery).
// Assumes parallel eye views (true for PSVR2); the menu reports the measured eye cant.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <optional>

namespace uevr::triview {

// Tangent-space extent of a frustum: left < right, bottom < top.
struct Tans {
    float left{}, right{}, top{}, bottom{};
};

struct Layout {
    uint32_t eye_width{}, eye_height{};           // full per-eye render size (one half of the main target)
    uint32_t fovea_width{}, fovea_height{};       // each eye's fovea render, placed at (0,0) of its target
    uint32_t periphery_x{};                       // periphery render rect in the main target: (x, 0, w, h)
    uint32_t periphery_width{}, periphery_height{};
    float u0{}, v0{}, u1{}, v1{};                 // fovea window in eye UV (top-left origin)
    Tans eye[2]{};                                // left / right eye frusta
    Tans periphery{};                             // union frustum rendered by view 2
};

// What a published Native Fix packet carries to the compositor.
struct PacketLayout {
    Layout layout{};
    bool valid{};
    bool third{};                                 // view 2 was really rendered for this packet
};

// Read tangents back from a UEVR/OpenXR GLM-style projection (m[col][row], clip.w = z).
template <typename Matrix>
std::optional<Tans> tans_from_projection(const Matrix& m) {
    const double sx = m[0][0], ox = m[2][0], sy = m[1][1], oy = m[2][1];
    if (!std::isfinite(sx) || !std::isfinite(ox) || !std::isfinite(sy) || !std::isfinite(oy) ||
        sx <= 0.0 || sy <= 0.0) return {};
    const Tans t{static_cast<float>((-1.0 - ox) / sx), static_cast<float>((1.0 - ox) / sx),
                 static_cast<float>((1.0 - oy) / sy), static_cast<float>((-1.0 - oy) / sy)};
    if (!(t.right > t.left) || !(t.top > t.bottom)) return {};
    return t;
}

// Map eye UV window [u0,u1] x [v0,v1] (may extend past 0..1) to the whole viewport.
// Same x/y-row math as v207's proven DuoView fovea crop; depth and w rows untouched.
template <typename Matrix>
void apply_uv_window(Matrix& m, double u0, double u1, double v0, double v1) {
    const double x_scale = 1.0 / (u1 - u0);
    const double y_scale = 1.0 / (v1 - v0);
    const double x_shift = (1.0 - u0 - u1) * x_scale;
    const double y_shift = (v0 + v1 - 1.0) * y_scale;
    for (int col = 0; col < 4; ++col) {
        const auto old_x = m[col][0];
        const auto old_y = m[col][1];
        const auto old_w = m[col][3];
        m[col][0] = static_cast<decltype(old_x)>(old_x * x_scale + old_w * x_shift);
        m[col][1] = static_cast<decltype(old_y)>(old_y * y_scale + old_w * y_shift);
    }
}

inline std::optional<Layout> make_layout(uint32_t eye_width, uint32_t eye_height,
                                         const Tans& left, const Tans& right, float periphery_scale) {
    if (eye_width < 64 || eye_height < 64 || eye_width > 16384 || eye_height > 16384 ||
        !std::isfinite(periphery_scale) || periphery_scale < .1f || periphery_scale > 1.f) return {};
    for (const auto* t : {&left, &right}) {
        if (!std::isfinite(t->left) || !std::isfinite(t->right) || !std::isfinite(t->top) ||
            !std::isfinite(t->bottom) || !(t->right > t->left) || !(t->top > t->bottom)) return {};
    }
    Layout l{};
    l.eye_width = eye_width;
    l.eye_height = eye_height;
    l.u0 = .25f; l.u1 = .75f; l.v0 = .25f; l.v1 = .75f;     // fixed centre 0.5 x 0.5 window
    l.fovea_width = static_cast<uint32_t>(std::lround(eye_width * (l.u1 - l.u0)));
    l.fovea_height = static_cast<uint32_t>(std::lround(eye_height * (l.v1 - l.v0)));
    l.eye[0] = left;
    l.eye[1] = right;
    l.periphery = {(std::min)(left.left, right.left), (std::max)(left.right, right.right),
                   (std::max)(left.top, right.top), (std::min)(left.bottom, right.bottom)};
    // Same angular pixel density as a full eye render times the periphery scale.
    const double wide = (l.periphery.right - l.periphery.left) / double(left.right - left.left);
    const double tall = (l.periphery.top - l.periphery.bottom) / double(left.top - left.bottom);
    const auto clamp_size = [](double pixels, uint32_t limit) {
        return static_cast<uint32_t>(std::clamp<double>(std::lround(pixels), 16.0, double(limit)));
    };
    l.periphery_width = clamp_size(eye_width * periphery_scale * wide, eye_width);
    l.periphery_height = clamp_size(eye_height * periphery_scale * tall, eye_height);
    l.periphery_x = eye_width;                     // free right half of the 2W x H main target
    return l;
}

// Views 0/1: crop the eye's own projection to the fovea window.
template <typename Matrix>
void apply_fovea_projection(Matrix& m, const Layout& l) {
    apply_uv_window(m, l.u0, l.u1, l.v0, l.v1);
}

// View 2: widen the LEFT eye projection to the union frustum (centre camera, left-eye rotation).
template <typename Matrix>
void apply_periphery_projection(Matrix& left_eye_projection, const Layout& l) {
    const auto& e = l.eye[0];
    const auto& p = l.periphery;
    const double w = e.right - e.left, h = e.top - e.bottom;
    apply_uv_window(left_eye_projection, (p.left - e.left) / w, (p.right - e.left) / w,
                    (e.top - p.top) / h, (e.top - p.bottom) / h);
}

// Eye UV -> periphery UV is affine for parallel eyes: pu = ax*u + bx, pv = ay*v + by.
struct EyeMap {
    float ax{}, bx{}, ay{}, by{};
};
inline EyeMap periphery_map(const Layout& l, int eye) {
    const auto& e = l.eye[eye != 0 ? 1 : 0];
    const auto& p = l.periphery;
    const float pw = p.right - p.left, ph = p.top - p.bottom;
    return {(e.right - e.left) / pw, (e.left - p.left) / pw,
            (e.top - e.bottom) / ph, (p.top - e.top) / ph};
}

} // namespace uevr::triview

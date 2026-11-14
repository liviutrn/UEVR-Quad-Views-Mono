#pragma once

#include <array>

namespace uevr::duoview::stereo {

struct FineDepthCamera {
    std::array<float,4> projection{}; // ax, bx, ay, by, divided by clip W coefficient
    std::array<float,4> orientation{}; // OpenXR stage, x/y/z/w
    std::array<float,3> position{};    // midpoint of the eyes, stage metres
    float world_to_meters{};
};

struct FineDepthReprojection {
    std::array<std::array<float,4>,3> rows{};
    std::array<float,4> previous_projection{};
};

// Maps current +Z-forward tangent rays into the previous camera. The last
// column is in engine units so the shader scales it by current inverse Z.
inline FineDepthReprojection fine_depth_reprojection(
        const FineDepthCamera& current, const FineDepthCamera& previous) {
    const auto rotate = [](const std::array<float,4>& q, const std::array<float,3>& v) {
        const auto [x,y,z,w] = q;
        const auto [a,b,c] = v;
        const float tx=2.f*(y*c-z*b), ty=2.f*(z*a-x*c), tz=2.f*(x*b-y*a);
        return std::array<float,3>{a+w*tx+y*tz-z*ty, b+w*ty+z*tx-x*tz, c+w*tz+x*ty-y*tx};
    };
    const auto& q=previous.orientation;
    const std::array<float,4> inverse{-q[0],-q[1],-q[2],q[3]};
    FineDepthReprojection result{};
    result.previous_projection=previous.projection;
    for (unsigned axis=0; axis<3; ++axis) {
        std::array<float,3> basis{};
        basis[axis]=axis==2 ? -1.f : 1.f;
        const auto column=rotate(inverse,rotate(current.orientation,basis));
        for (unsigned row=0; row<3; ++row)
            result.rows[row][axis]=row==2 ? -column[row] : column[row];
    }
    std::array<float,3> delta{};
    for (unsigned axis=0; axis<3; ++axis)
        delta[axis]=(current.position[axis]-previous.position[axis])*current.world_to_meters;
    const auto translation=rotate(inverse,delta);
    for (unsigned row=0; row<3; ++row)
        result.rows[row][3]=row==2 ? -translation[row] : translation[row];
    return result;
}

} // namespace uevr::duoview::stereo

#pragma once

namespace uevr::head_movement {

// Gains describe recentered player axes, not the runtime's arbitrary room axes.
// Keep this before the game's view rotation and after the recenter rotation.
// Do not use the live HMD orientation: looking around must not move the camera.
template<class Rotation, class Vector>
Vector scale_translation(const Rotation& recenter, const Vector& tracking_delta,
                         const Vector& gains) {
    const Vector aligned = recenter * tracking_delta;
    return Vector{aligned.x * gains.x, aligned.y * gains.y, aligned.z * gains.z};
}

} // namespace uevr::head_movement

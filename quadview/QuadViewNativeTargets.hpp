#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace uevr::quadview {

// The renderer writes four independent UE-owned targets before a stereo packet
// can be published. Keep the identity proof independent of D3D/UE headers so it
// can be exercised by the portable contract tests.
struct NativeTargetIdentity {
    uintptr_t owner_texture{};
    uintptr_t render_target{};
    uintptr_t rhi_texture{};
    uintptr_t native_resource{};
    uint64_t target_set_generation{};
    uint32_t width{}, height{}, format{};
};

inline bool valid_native_target_quartet(const std::array<NativeTargetIdentity, 4>& targets) {
    const auto& first = targets[0];
    if (!first.owner_texture || !first.render_target || !first.rhi_texture || !first.native_resource ||
        !first.target_set_generation || !first.width || !first.height || !first.format) return false;
    for (size_t i = 0; i != targets.size(); ++i) {
        const auto& target = targets[i];
        if (!target.owner_texture || !target.render_target || !target.rhi_texture || !target.native_resource ||
            target.target_set_generation != first.target_set_generation || target.width != first.width ||
            target.height != first.height || target.format != first.format) return false;
        for (size_t j = 0; j < i; ++j) {
            const auto& prior = targets[j];
            if (target.owner_texture == prior.owner_texture || target.render_target == prior.render_target ||
                target.rhi_texture == prior.rhi_texture || target.native_resource == prior.native_resource) return false;
        }
    }
    return true;
}

// Tri-view B6: same contract as the quartet, but each role has its own
// expected extent (compact sources). Equal extents == the quartet rule.
inline bool valid_native_target_roles(const std::array<NativeTargetIdentity, 4>& targets,
                                      const std::array<std::array<uint32_t, 2>, 4>& extents) {
    const auto& first = targets[0];
    if (!first.target_set_generation || !first.format) return false;
    for (size_t i = 0; i != targets.size(); ++i) {
        const auto& target = targets[i];
        if (!target.owner_texture || !target.render_target || !target.rhi_texture || !target.native_resource ||
            !extents[i][0] || !extents[i][1] || target.width != extents[i][0] || target.height != extents[i][1] ||
            target.target_set_generation != first.target_set_generation || target.format != first.format) return false;
        for (size_t j = 0; j < i; ++j) {
            const auto& prior = targets[j];
            if (target.owner_texture == prior.owner_texture || target.render_target == prior.render_target ||
                target.rhi_texture == prior.rhi_texture || target.native_resource == prior.native_resource) return false;
        }
    }
    return true;
}



// B17: the logical view array still has four indices (0,1,2,3), but slot 1
// is intentionally dormant. Only roles 0 (shared periphery), 2 (left fovea),
// and 3 (right fovea) own UE textures, FRenderTargets and GPU resources.
inline bool valid_native_triview_targets(
    const std::array<NativeTargetIdentity, 4>& targets,
    const std::array<std::array<uint32_t, 2>, 4>& extents) {
    if (extents[1][0] || extents[1][1]) return false;
    const auto& unused = targets[1];
    if (unused.owner_texture || unused.render_target || unused.rhi_texture ||
        unused.native_resource || unused.target_set_generation ||
        unused.width || unused.height || unused.format) return false;

    constexpr std::array<size_t, 3> roles{0, 2, 3};
    const auto& first = targets[0];
    if (!first.target_set_generation || !first.format) return false;
    for (size_t pos = 0; pos < roles.size(); ++pos) {
        const auto i = roles[pos];
        const auto& target = targets[i];
        if (!target.owner_texture || !target.render_target || !target.rhi_texture ||
            !target.native_resource || !extents[i][0] || !extents[i][1] ||
            target.width != extents[i][0] || target.height != extents[i][1] ||
            target.target_set_generation != first.target_set_generation ||
            target.format != first.format) return false;
        for (size_t prev = 0; prev < pos; ++prev) {
            const auto& earlier = targets[roles[prev]];
            if (target.owner_texture == earlier.owner_texture ||
                target.render_target == earlier.render_target ||
                target.rhi_texture == earlier.rhi_texture ||
                target.native_resource == earlier.native_resource) return false;
        }
    }
    return true;
}

} // namespace uevr::quadview

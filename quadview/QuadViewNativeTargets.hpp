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

} // namespace uevr::quadview

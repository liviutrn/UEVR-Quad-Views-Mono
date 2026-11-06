#pragma once
#include <array>
#include <cstdint>
#include <cstddef>
#include <memory>

namespace uevr::quadview {
using NativeResourceExtents = std::array<std::array<uint32_t,2>,4>;
struct NativeResourceReusePlan {
    uint8_t reuse_mask{};
    uint64_t new_color_bytes{}; // BGRA8 payload estimate, excluding driver/engine auxiliaries.
    bool reuses(size_t role) const { return role<4 && (reuse_mask & uint8_t(1u<<role)); }
};
inline NativeResourceReusePlan plan_native_resource_reuse(
    bool same_world, bool complete_and_live,
    const NativeResourceExtents& old_extents, const NativeResourceExtents& requested) {
    NativeResourceReusePlan result{};
    for (size_t role : std::array<size_t,3>{0,2,3}) {
        const auto& e=requested[role];
        if (!e[0] || !e[1]) continue;
        if (same_world && complete_and_live && old_extents[role]==e)
            result.reuse_mask |= uint8_t(1u<<role);
        else result.new_color_bytes += uint64_t(e[0])*e[1]*4;
    }
    return result;
}
inline bool valid_resource_publication(uint64_t publication, uint64_t snapshot_publication,
                                       uint64_t allocation) {
    return publication && publication==snapshot_publication && allocation && allocation<=publication;
}
// Copy the publication record while retaining the exact physical owner lease.
// Never mutate an old snapshot: packets can still hold it while a replacement builds.
template<typename Snapshot>
std::shared_ptr<Snapshot> republish_resource_snapshot(const std::shared_ptr<const Snapshot>& source,
                                                     uint64_t publication) {
    if (!source || !valid_resource_publication(publication,publication,source->resource_allocation_generation) ||
        publication<=source->generation) return {};
    auto snapshot=std::make_shared<Snapshot>(*source);
    snapshot->generation=publication;
    return snapshot;
}
} // namespace uevr::quadview

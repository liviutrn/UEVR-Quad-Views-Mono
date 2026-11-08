#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include "QuadViewNgxSelect.hpp"

namespace uevr::quadview::ngx::continuity {

struct Candidate {
    uint64_t sequence{};
    uint32_t width{}, height{};
    uint32_t age_ms{};
    bool submitted{}, valid_evaluation{}, has_texture{};
    bool foreign_queue{}, fence_complete{};
};

inline bool protectable(const Candidate& c, uint32_t width, uint32_t height) noexcept {
    return c.submitted && c.valid_evaluation && c.has_texture &&
        matches_periphery(c.width,c.height,width,height) && c.age_ms < 250 &&
        (!c.foreign_queue || c.fence_complete);
}

template<class Range>
size_t newest_protected(const Range& candidates, uint32_t width, uint32_t height) noexcept {
    size_t best = std::numeric_limits<size_t>::max();
    uint64_t sequence = 0;
    for (size_t i = 0; i < candidates.size(); ++i) {
        const auto& c = candidates[i];
        if (protectable(c, width, height) && (best == std::numeric_limits<size_t>::max() || c.sequence > sequence)) {
            best = i;
            sequence = c.sequence;
        }
    }
    return best;
}

} // namespace uevr::quadview::ngx::continuity

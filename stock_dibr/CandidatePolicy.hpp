#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

namespace stock_dibr {

// A copied description of a source that passed capture and producer-proof
// validation. This intentionally owns no D3D objects.
struct CandidateInfo {
    uint64_t id{};
    uint64_t width{};
    uint32_t height{};
    uint32_t format{};
    uint64_t last_seen_epoch{};
    bool available{};
};

// Bounded, portable bookkeeping shared by the D3D capture path and its policy
// tests. identity is an opaque token used only for equality; it is never
// dereferenced and the table retains no COM references.
template<size_t Capacity>
class CandidatePolicy final {
    struct Entry {
        uint64_t identity{};
        CandidateInfo info{};
    };

    std::array<Entry, Capacity> entries_{};
    size_t count_{};
    uint64_t next_id_{1};
    uint64_t selected_id_{};
    bool capacity_exhausted_{};

    size_t find_identity(uint64_t identity) const {
        for (size_t i = 0; i < count_; ++i)
            if (entries_[i].identity == identity) return i;
        return Capacity;
    }
    size_t find_id(uint64_t id) const {
        for (size_t i = 0; i < count_; ++i)
            if (entries_[i].info.id == id) return i;
        return Capacity;
    }

public:
    // Returns zero if identity or metadata is invalid, or no safe bounded
    // registry slot is available. ID zero is reserved for automatic selection.
    uint64_t observe(uint64_t identity, uint64_t width, uint32_t height,
        uint32_t format, uint64_t epoch) {
        if (!identity || !width || !height || !format || !epoch) return 0;
        auto index = find_identity(identity);
        if (index == Capacity) {
            if (!next_id_) {
                capacity_exhausted_ = true;
                return 0;
            }
            if (count_ < Capacity) {
                index = count_++;
            } else {
                // Retain current-epoch sources and any explicitly selected
                // source. Only an older, nonselected identity is safe to
                // forget; a later observation must fail closed otherwise.
                index = Capacity;
                for (size_t i = 0; i < count_; ++i) {
                    const auto& entry = entries_[i];
                    if (entry.info.id == selected_id_ || entry.info.last_seen_epoch >= epoch) continue;
                    if (index == Capacity || entry.info.last_seen_epoch < entries_[index].info.last_seen_epoch)
                        index = i;
                }
                if (index == Capacity) {
                    capacity_exhausted_ = true;
                    return 0;
                }
            }
            entries_[index].identity = identity;
            entries_[index].info.id = next_id_;
            next_id_ = next_id_ == std::numeric_limits<uint64_t>::max() ? 0 : next_id_ + 1;
        }
        auto& info = entries_[index].info;
        info.width = width;
        info.height = height;
        info.format = format;
        info.last_seen_epoch = epoch;
        return info.id;
    }

    bool select(uint64_t id) {
        if (id != 0 && find_id(id) == Capacity) return false;
        selected_id_ = id;
        return true;
    }

    uint64_t selected() const { return selected_id_; }
    bool knows(uint64_t id) const { return id != 0 && find_id(id) != Capacity; }
    // Used by the capture owner to prune its retained identity references after
    // observation. Unknown identities, including evicted sources, return 0.
    uint64_t id_for_identity(uint64_t identity) const {
        const auto index = find_identity(identity);
        return index == Capacity ? 0 : entries_[index].info.id;
    }
    bool accepts_slot(uint64_t candidate_id) const {
        return selected_id_ == 0 || candidate_id == selected_id_;
    }
    bool capacity_exhausted() const { return capacity_exhausted_; }

    std::vector<CandidateInfo> candidates() const {
        std::vector<CandidateInfo> result;
        result.reserve(count_);
        for (size_t i = 0; i < count_; ++i) result.push_back(entries_[i].info);
        return result;
    }

    void reset() {
        // Keep IDs monotonic across capture generations so a stale UI/client ID
        // cannot accidentally select a new resource after reset. Old IDs are
        // invalidated with the registry and selection returns to automatic.
        entries_ = {};
        count_ = 0;
        selected_id_ = 0;
        capacity_exhausted_ = false;
    }
};

} // namespace stock_dibr

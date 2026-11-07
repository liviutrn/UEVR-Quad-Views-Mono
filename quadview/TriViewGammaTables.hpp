#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <mutex>

namespace uevr::quadview {
// Like DuoView's static Native Fix table: Unreal may invoke its resource's
// virtual destructor after the last plugin packet owner has retired. These
// tiny immutable tables outlive all engine resources; they retain no textures.
template<size_t Slots, size_t Capacity = 8> class PersistentGammaTables {
public:
    using Table = std::array<uintptr_t, Slots>;
    const Table* acquire(uintptr_t original_address, const Table& original,
                         size_t gamma_slot, uintptr_t replacement) {
        if (!original_address || !replacement || gamma_slot >= Slots) return nullptr;
        std::scoped_lock lock{mutex_};
        for (const auto& entry : entries_) {
            if (entry.used && entry.address == original_address && entry.slot == gamma_slot &&
                entry.replacement == replacement && entry.original == original) return &entry.hooked;
        }
        for (auto& entry : entries_) {
            if (entry.used) continue;
            entry.address = original_address; entry.slot = gamma_slot; entry.replacement = replacement;
            entry.original = original; entry.hooked = original;
            entry.hooked[gamma_slot] = replacement;
            entry.used = true;
            return &entry.hooked;
        }
        return nullptr; // Bounded storage, never overwrite a published table.
    }
private:
    struct Entry {
        bool used{}; uintptr_t address{}, replacement{}; size_t slot{};
        Table original{}, hooked{};
    };
    std::mutex mutex_{};
    std::array<Entry, Capacity> entries_{};
};
} // namespace uevr::quadview
